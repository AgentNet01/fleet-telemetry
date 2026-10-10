"""Etsy shops linked to the hub (Etsy Open API v3, OAuth 2 with PKCE).

Darragh registers an Etsy app once (etsy.com/developers) and pastes its keystring + shared secret into the
dashboard; "Connect Etsy" sends him to Etsy to approve read access to his orders; the hub keeps the token
fresh and pulls paid orders every hour into the sales table, under the product he picked for that shop.
Everything is kept in the vault with scope "hub", so no agent can read it.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

AUTH_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
API = "https://openapi.etsy.com/v3/application"
SCOPES = "transactions_r shops_r"
APP = "etsy-app"            # vault: {"key": keystring, "secret": shared secret}
SHOP = "etsy-shop:"         # vault: one per linked shop


def http(method, url, headers=None, data=None):
    """(status, json). Swapped out in tests."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def _vault(h, name):
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


def _get(app, access, url):
    st, out = http("GET", url, headers=_headers(app, access))
    if st in (401, 403) and app.get("secret"):
        st, out = http("GET", url, headers=_headers(app, access, combined=False))
    if st != 200:
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
    for r in h.db.execute("select value from secrets where name like ? order by name", (SHOP + "%",)):
        rec = json.loads(r["value"])
        out.append({k: rec.get(k) for k in ("shop_id", "shop_name", "product", "connected", "last_sync", "error")})
    return {"app": bool(_vault(h, APP)), "shops": out}
