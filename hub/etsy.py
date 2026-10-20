"""Etsy shops linked to the hub (Etsy Open API v3, OAuth 2 with PKCE).

Darragh registers an Etsy app once (etsy.com/developers) and pastes its keystring + shared secret into the
dashboard; "Connect Etsy" sends him to Etsy to approve read access to his orders; the hub keeps the token
fresh and pulls paid orders every hour into the sales table, under the product he picked for that shop.
Everything is kept in the vault with scope "hub", so no agent can read it.
Agents post listings live through the hub (post()). Jack, Oct 15: posting is theirs; only spending money is his.
"""
import base64
import hashlib
import json
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
API = "https://openapi.etsy.com/v3/application"
SCOPES = "transactions_r shops_r listings_r listings_w"
APP = "etsy-app"            # vault: {"key": keystring, "secret": shared secret}
SHOP = "etsy-shop:"         # vault: one per linked shop


def http(method, url, headers=None, data=None, files=None):
    """(status, json). files = {field: (filename, bytes)} sends multipart. Swapped out in tests."""
    headers = dict(headers or {})
    if data is not None:
        # Etsy API expects lowercase true/false for booleans in form-encoded bodies;
        # urlencode would send Python's True/False (capitalized), which Etsy rejects.
        data = {k: ("true" if v is True else "false" if v is False else v) for k, v in data.items()}
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    if files:
        b = secrets.token_hex(16)
        parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in (data or {}).items()]
        parts += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'
                  f'Content-Type: application/octet-stream\r\n\r\n'.encode() + raw + b"\r\n" for k, (fn, raw) in files.items()]
        body, headers["Content-Type"] = b"".join(parts) + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def _vault(h, name):
    with h.lock:            # Oct 15: read from the listing-sync thread without it -> sqlite "bad parameter or other API misuse"
        r = h.db.execute("select value from secrets where name=?", (name,)).fetchone()
    return json.loads(r["value"]) if r else None


def _save(h, name, obj):
    h.secret_put(name, json.dumps(obj), "hub", by="hub")


def set_app(h, key, secret):
    with h.lock:
        _save(h, APP, {"key": key.strip(), "secret": secret.strip()})


def start(h, product, redirect_uri):
    """The URL to send the browser to, remembering what to check when Etsy sends it back."""
    app = _vault(h, APP)
    if not app:
        raise ValueError("add the Etsy app's keystring and shared secret first")
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(16)
    h.__dict__.setdefault("etsy_pending", {})[state] = (verifier, product, time.time())
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": app["key"], "redirect_uri": redirect_uri, "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})


def finish(h, state, code, redirect_uri):
    """Etsy sent the browser back: trade the code for tokens, find the shop, keep it in the vault."""
    pending = h.__dict__.get("etsy_pending", {}).pop(state, None)
    if not pending or time.time() - pending[2] > 900:
        raise ValueError("this Etsy link expired or didn't start here; press Connect Etsy again")
    verifier, product, _ = pending
    app = _vault(h, APP)
    st, tok = http("POST", TOKEN_URL, data={"grant_type": "authorization_code", "client_id": app["key"],
                                             "redirect_uri": redirect_uri, "code": code, "code_verifier": verifier})
    if st != 200 or "access_token" not in tok:
        raise ValueError(f"Etsy refused the sign-in ({st}): {tok.get('error_description') or tok.get('error') or ''}")
    shop = _shop_of(app, tok["access_token"])
    rec = {"shop_id": shop["shop_id"], "shop_name": shop.get("shop_name", ""), "product": product,
           "access": tok["access_token"], "refresh": tok["refresh_token"], "expires": time.time() + int(tok.get("expires_in", 3600)),
           "connected": time.time(), "last_sync": None, "error": None}
    with h.lock:
        _save(h, SHOP + str(shop["shop_id"]), rec)
    return rec


def _headers(app, access, combined=True):
    # Etsy wants "keystring:shared secret" as the api key; older apps accept the keystring alone
    return {"x-api-key": f"{app['key']}:{app['secret']}" if combined and app.get("secret") else app["key"],
            "Authorization": "Bearer " + access}


def _get(app, access, url, method="GET", data=None, files=None):
    st, out = http(method, url, headers=_headers(app, access), data=data, files=files)
    if st in (401, 403) and app.get("secret"):
        st, out = http(method, url, headers=_headers(app, access, combined=False), data=data, files=files)
    if st not in (200, 201, 204):
        raise RuntimeError(f"Etsy said {st} for {url.split('/application')[-1]}: {out.get('error') or out}")
    return out


def _shop_of(app, access):
    user_id = access.split(".", 1)[0]
    return _get(app, access, f"{API}/users/{user_id}/shops")


def _fresh(h, app, rec):
    if rec["expires"] - time.time() > 300:
        return rec
    st, tok = http("POST", TOKEN_URL, data={"grant_type": "refresh_token", "client_id": app["key"],
                                             "refresh_token": rec["refresh"]})
    if st != 200 or "access_token" not in tok:
        raise RuntimeError(f"Etsy wouldn't renew the link ({st}); press Connect Etsy again")
    rec.update(access=tok["access_token"], refresh=tok.get("refresh_token", rec["refresh"]),
               expires=time.time() + int(tok.get("expires_in", 3600)))
    return rec


def sales(h):
    """Paid orders from every linked shop, as sales rows. A broken shop records its error and is skipped."""
    app = _vault(h, APP)
    with h.lock:
        names = [r["name"] for r in h.db.execute("select name from secrets where name like ?", (SHOP + "%",))]
    rows = []
    for name in names:
        rec = _vault(h, name)
        try:
            rec = _fresh(h, app, rec)
            offset = 0
            while offset < 2000:
                page = _get(app, rec["access"], f"{API}/shops/{rec['shop_id']}/receipts?limit=100&offset={offset}")
                got = page.get("results", [])
                for r in got:
                    if not r.get("is_paid"):
                        continue
                    g = r.get("grandtotal") or {}
                    rows.append({"source": "etsy", "external_id": str(r["receipt_id"]),
                                 "amount": g.get("amount", 0) / (g.get("divisor") or 100),
                                 "currency": (g.get("currency_code") or "usd").lower(), "product": rec["product"],
                                 "at": r.get("created_timestamp") or r.get("create_timestamp") or time.time()})
                if len(got) < 100:
                    break
                offset += 100
            rec.update(last_sync=time.time(), error=None)
        except Exception as e:
            rec["error"] = str(e)[:200]
        with h.lock:
            _save(h, name, rec)
    return rows


def shops(h):
    """What the dashboard shows: no tokens."""
    out = []
    with h.lock:
        rows = h.db.execute("select value from secrets where name like ? order by name", (SHOP + "%",)).fetchall()
    for r in rows:
        rec = json.loads(r["value"])
        out.append({k: rec.get(k) for k in ("shop_id", "shop_name", "product", "connected", "last_sync", "error")})
    return {"app": bool(_vault(h, APP)), "shops": out}


def _taxonomy(app, access, want):
    """A category id from a number or a word ("magnets"): the most specific category whose name matches."""
    if str(want).isdigit():
        return int(want)
    found, w = [], str(want).lower().strip()
    def walk(nodes, depth):
        for n in nodes:
            if w in n.get("name", "").lower():
                found.append((n["name"].lower() == w, depth, n["id"]))
            walk(n.get("children") or [], depth + 1)
    walk(_get(app, access, f"{API}/seller-taxonomy/nodes").get("results", []), 0)
    if not found:
        raise ValueError(f"no Etsy category matches {want!r}; try a broader word or the category id")
    return max(found)[2]


def _first(app, access, url, key):
    try:
        return (_get(app, access, url).get("results") or [{}])[0].get(key)
    except RuntimeError:
        return None


def _shop(h, product=None):
    """(app, secret name, shop record): the product's own shop, else the first linked one."""
    app = _vault(h, APP)
    with h.lock:
        names = [r["name"] for r in h.db.execute("select name from secrets where name like ?", (SHOP + "%",))]
    if not app or not names:
        raise ValueError("no Etsy shop is linked yet: Jack presses Connect Etsy on the Vault tab")
    name, rec = next(((n, r) for n, r in ((n, _vault(h, n)) for n in names) if product and r.get("product") == product),
                     (names[0], _vault(h, names[0])))
    return app, name, rec


def _listing_id(link):
    m = re.search(r"etsy\.com/listing/(\d+)", link or "")
    return m and int(m.group(1))


def howto(lid="<listing id>"):
    """Oct 15: the hub named `fleet etsy update` while the agents' fleet (pulled from GitHub) didn't have it yet, and the
    whole fleet asked each other how. The fallback runs the same hub call through the fleet.py they already have."""
    return (f"`fleet etsy update {lid} changes.json`, or if your fleet has no etsy command yet: "
            f"python3 -c \"import sys,json,os; sys.path[:0]=[os.path.expanduser(p) for p in ('~/.fleet/repo/hub','~/fleet-telemetry/hub')]; "
            f"import fleet; print(fleet.call('POST','/api/etsy/update',dict(json.load(open('changes.json')),listing_id={lid if str(lid).isdigit() else 'ID'})))\"")


def sync_listings(h, only=None):
    """Jack, Oct 15: products linked to listings that had been taken down, and agents spent tasks finding out by hand.
    Reads each product's listing state from Etsy; a change is recorded and its PM is told."""
    app, name, rec = _shop(h)
    rec = _fresh(h, app, rec)
    with h.lock:
        _save(h, name, rec)
        rows = h.db.execute("select name, pm, link, listing_state from products where status='active' and link like '%etsy.com/listing/%'").fetchall()
    for p in rows:
        lid = _listing_id(p["link"])
        if only and lid != only:
            continue
        try:
            state = _get(app, rec["access"], f"{API}/listings/{lid}").get("state") or "unknown"
        except RuntimeError as e:
            state = "removed" if "404" in str(e) else None
        if not state or state == p["listing_state"]:
            continue
        with h.lock:
            h.db.execute("update products set listing_state=? where name=?", (state, p["name"]))
            h._log(None, "hub", "out", f"etsy listing {lid} for {p['name']} is now {state}")
            if p["pm"]:
                h._note(p["pm"], f"{p['name']}: Etsy listing {lid} is now {state.upper()}",
                        f"{p['link']} is {state} on Etsy (the hub reads it every 10 minutes). "
                        + ("Buyers can see it." if state == "active" else
                           "Buyers can't see or buy it. Tell anyone working on this product. Once it meets the listing rules, "
                           f"put changes.json = {{\"state\": \"active\"}} (plus \"images\" to replace the pictures) and run {howto(lid)}"))


def update(h, who, lid, f, image):
    """Change a live listing: "images" replaces every picture (first = hero), "state" is active|inactive, any other
    Etsy listing field (title, description, tags, ...) passes through. Jack, Oct 15: every edit queued on one agent's browser."""
    app, name, rec = _shop(h)
    lid = int(lid)
    with h.lock:            # Jack, Oct 15: everyone may edit Etsy, but not each other's products at cross purposes
        p = next((r["name"] for r in h.db.execute("select name, link from products") if _listing_id(r["link"]) == lid), None)
        mine = p and h.db.execute("select 1 from tasks t join projects j on t.project=j.id join products pr on j.product=pr.id "
                                  "where pr.name=? and t.owner=? and t.status='working'", (p, who)).fetchone()
        if not (mine or h.may_manage(who, p)):
            raise PermissionError(f"listing {lid} belongs to {p or 'no product'}: only its PM, the CEO, or someone with a "
                                  f"task on {p or 'it'} changes it")
    pics = [image(ref) for ref in f.get("images") or []]            # fetch first: a bad picture changes nothing
    if f.pop("dry_run", False):     # Oct 15: passed through to Etsy, which ignored it and applied the change for real
        return {"listing_id": lid, "live": f"https://www.etsy.com/listing/{lid}", "dry_run": True,
                "changed": (["images"] if pics else []) + [k for k in f if k not in ("images", "product")]}
    with EDITING:
        return _apply(h, who, app, name, rec, lid, f, pics)


EDITING = threading.Lock()  # ponytail: one listing edit at a time fleet-wide, so two never interleave; per-listing if it queues


def _apply(h, who, app, name, rec, lid, f, pics):
    rec = _fresh(h, app, rec)
    shop, tok = rec["shop_id"], rec["access"]
    if pics:
        old = [i["listing_image_id"] for i in _get(app, tok, f"{API}/listings/{lid}/images").get("results", [])]
        for i, (fn, raw) in enumerate(pics, 1):
            _get(app, tok, f"{API}/shops/{shop}/listings/{lid}/images", "POST", data={"rank": i}, files={"image": (fn, raw)})
        for iid in old:
            _get(app, tok, f"{API}/shops/{shop}/listings/{lid}/images/{iid}", "DELETE")
    data = {k: v for k, v in f.items() if k not in ("images", "product")}
    if isinstance(data.get("tags"), list):
        data["tags"] = ",".join(data["tags"])
    if data:
        _get(app, tok, f"{API}/shops/{shop}/listings/{lid}", "PATCH", data=data)
    with h.lock:
        _save(h, name, rec)
        h._log(None, who, "out", f"etsy listing {lid} updated: " + ", ".join(
            (["pictures replaced"] if pics else []) + [f"state={data[k]}" if k == "state" else k for k in data]))
    sync_listings(h, only=lid)
    return {"listing_id": lid, "live": f"https://www.etsy.com/listing/{lid}", "changed": (["images"] if pics else []) + list(data)}


def _item(title):
    """The item a title names: its first three words that aren't sizes, counts or filler."""
    # ponytail: first-3-words match, catches "Silicone Stretch Lids Set of 6" vs "... 6 Pack"; a smarter match if
    # agents start posting true duplicates under reworded titles
    words = [w for w in re.findall(r"[a-z]+", title.lower()) if w not in _FILLER and len(w) > 1]
    return " ".join(words[:3])


_FILLER = {"set", "of", "pack", "pcs", "pc", "piece", "the", "a", "an", "and", "for", "with", "cm", "mm", "in"}


def _twin(app, tok, shop, title):
    """A live listing in the shop selling the same item, or None. Oct 20: three agents posted silicone stretch lids
    and two posted makeup pads within an hour; the hub's product list didn't show listings posted without a product."""
    want, offset = _item(title), 0
    while True:
        page = _get(app, tok, f"{API}/shops/{shop}/listings?state=active&limit=100&offset={offset}").get("results", [])
        for l in page:
            if _item(l.get("title", "")) == want:
                return l
        if len(page) < 100:
            return None
        offset += 100


def post(h, who, f, image):
    """An agent's listing, put live on Etsy with its pictures (and, for a download, its files).
    f: title, description, price, tags, category, kind physical|download, quantity, product, images, files, plus any
    other Etsy listing field. image(ref) -> (filename, bytes). Returns {listing_id, edit, live}."""
    app, name, rec = _shop(h, f.get("product"))
    # Oct 20: listings posted without a product never got a link, so the hub kept planning them as unlaunched
    with h.lock:
        known = f.get("product") and h.db.execute("select 1 from products where name=? and status='active'", (f["product"],)).fetchone()
    if not known:
        raise ValueError('"product" must name the hub product this listing sells (fleet product add it first)')
    pics = [image(ref) for ref in f.get("images") or []]           # fetch first: a bad picture leaves no half-made draft
    if not pics:
        raise ValueError("a listing needs at least one picture")
    kind = f.get("kind") or "physical"
    files = [image(ref) for ref in f.get("files") or []]
    if kind == "download" and not files:
        raise ValueError('a download listing needs "files": the PDF or zip the buyer gets')
    for k in ("title", "description", "price", "category"):
        if not f.get(k):
            raise ValueError(f"missing {k}")
    rec = _fresh(h, app, rec)
    shop, tok = rec["shop_id"], rec["access"]
    twin = _twin(app, tok, shop, f["title"])
    if twin:
        raise ValueError(f"the shop already sells this: listing {twin['listing_id']} \"{twin.get('title', '')[:80]}\" "
                         f"https://www.etsy.com/listing/{twin['listing_id']} is live. Pick a different item, or improve that "
                         "listing with fleet etsy update instead")
    data = {k: v for k, v in f.items() if k not in ("images", "files", "category", "kind", "product", "tags")}
    data.update(title=f["title"], taxonomy_id=_taxonomy(app, tok, f["category"]), type=kind,
                quantity=f.get("quantity") or (999 if kind == "download" else 99),
                who_made=f.get("who_made") or "i_did", when_made=f.get("when_made") or "made_to_order")
    if f.get("tags"):
        data["tags"] = ",".join(f["tags"]) if isinstance(f["tags"], list) else f["tags"]
    if kind == "physical":                                          # Etsy wants these; the shop's own defaults
        data.setdefault("shipping_profile_id", _first(app, tok, f"{API}/shops/{shop}/shipping-profiles", "shipping_profile_id"))
        data.setdefault("readiness_state_id", _first(app, tok, f"{API}/shops/{shop}/readiness-state-definitions", "readiness_state_id"))
        data = {k: v for k, v in data.items() if v is not None}
    listing = _get(app, tok, f"{API}/shops/{shop}/listings", "POST", data=data)
    lid = listing["listing_id"]
    for i, (fn, raw) in enumerate(pics, 1):
        _get(app, tok, f"{API}/shops/{shop}/listings/{lid}/images", "POST", data={"rank": i}, files={"image": (fn, raw)})
    for fn, raw in files:
        _get(app, tok, f"{API}/shops/{shop}/listings/{lid}/files", "POST", data={"name": fn}, files={"file": (fn, raw)})
    edit, live = f"https://www.etsy.com/your/shops/me/listing-editor/edit/{lid}", f"https://www.etsy.com/listing/{lid}"
    with h.lock:
        _save(h, name, rec)                                         # a renewed token is kept
    try:
        _get(app, tok, f"{API}/shops/{shop}/listings/{lid}", "PATCH", data={"state": "active"})
    except RuntimeError as e:
        raise RuntimeError(f"{e}. It's saved as a draft: fix it at {edit}, or post again") from None
    with h.lock:
        if f.get("product"):
            h.db.execute("update products set link=?, listing_state='active' where name=? and coalesce(link,'')=''", (live, f["product"]))
        h._log(None, who, "out", f"etsy listing live {lid}: {f['title'][:120]} {live}")
    return {"listing_id": lid, "edit": edit, "live": live}
