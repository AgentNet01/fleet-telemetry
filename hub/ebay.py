"""eBay: resale listings priced by the money rule (money.py), fulfilled by CJ (orders.py). PLAN9.

Jack links the account once: the eBay app's keys go in on the Vault tab, "Connect eBay" sends him to eBay's
consent page, the hub keeps the seller token fresh. Agents post with `fleet ebay post`; the hub sets the price
from a fresh CJ quote and comparable eBay listings, never the agent. eBay's dropshipping rule allows a wholesale
supplier only, so every listing is a CJ variant (SKU "cj-<vid>") shipped from CJ's US warehouse.
"""
import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import cj
import money
from etsy import _item, _same, _save, _vault

AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
API = "https://api.ebay.com"
SCOPES = " ".join("https://api.ebay.com/oauth/api_scope" + s for s in ("", "/sell.inventory", "/sell.account", "/sell.fulfillment"))
APP = "ebay-app"             # vault: {"client_id", "client_secret", "runame", "endpoint", "verify_token"}
SELLER = "ebay-seller"       # vault: {"access", "refresh", "expires", "policies", "location"}
LOCATION, LOCATION_ZIP = "hub-us", "91710"   # ponytail: CJ's US warehouse (Chino, CA); one location until CJ ships from more
QUOTE_ZIPS = ("10001", "60601", "90001")     # priced on the dearest of east, middle, west
MARKET_MIN = 3               # fewer comparables than this and the market price isn't trusted
NO_MARKET_CAP = 19.99
_app_tok = {}


def http(method, url, headers=None, data=None, form=False):
    """(status, json). Swapped out in tests."""
    body = None
    headers = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
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


# ---- linking ---------------------------------------------------------------------------------
def set_app(h, client_id, client_secret, runame, endpoint):
    old = _vault(h, APP) or {}
    with h.lock:
        _save(h, APP, {"client_id": client_id.strip(), "client_secret": client_secret.strip(), "runame": runame.strip(),
                       "endpoint": endpoint, "verify_token": old.get("verify_token") or secrets.token_urlsafe(48)[:64]})
    return endpoint


def _basic(app):
    return "Basic " + base64.b64encode(f"{app['client_id']}:{app['client_secret']}".encode()).decode()


def start(h):
    app = _vault(h, APP)
    if not app:
        raise ValueError("add the eBay app's client ID, client secret and RuName first")
    state = secrets.token_urlsafe(16)
    h.__dict__.setdefault("ebay_pending", {})[state] = time.time()
    return AUTH_URL + "?" + urllib.parse.urlencode({"client_id": app["client_id"], "redirect_uri": app["runame"],
                                                    "response_type": "code", "scope": SCOPES, "state": state})


def finish(h, state, code):
    """eBay sent the browser back: tokens, the account's business policies, our ship-from location."""
    t = h.__dict__.get("ebay_pending", {}).pop(state, None)
    if not t or time.time() - t > 900:
        raise ValueError("this eBay link expired or didn't start here; press Connect eBay again")
    app = _vault(h, APP)
    st, tok = http("POST", TOKEN_URL, headers={"Authorization": _basic(app)}, form=True,
                   data={"grant_type": "authorization_code", "code": code, "redirect_uri": app["runame"]})
    if st != 200 or "access_token" not in tok:
        raise ValueError(f"eBay refused the sign-in ({st}): {tok.get('error_description') or tok.get('error') or ''}")
    rec = {"access": tok["access_token"], "refresh": tok["refresh_token"], "expires": time.time() + int(tok.get("expires_in", 7200)),
           "connected": time.time(), "policies": {}, "location": None, "error": None}
    with h.lock:
        _save(h, SELLER, rec)
    for kind in ("fulfillment", "payment", "return"):
        got = (_api(h, "GET", f"/sell/account/v1/{kind}_policy?marketplace_id=EBAY_US") or {}).get(f"{kind}Policies") or []
        if got:
            rec["policies"][f"{kind}PolicyId"] = got[0][f"{kind}PolicyId"]
    try:
        _api(h, "POST", f"/sell/inventory/v1/location/{LOCATION}", {
            "location": {"address": {"postalCode": LOCATION_ZIP, "country": "US"}}, "name": "CJ US warehouse",
            "locationTypes": ["WAREHOUSE"], "merchantLocationStatus": "ENABLED"})
    except RuntimeError as e:
        if "409" not in str(e) and "already exists" not in str(e):
            raise
    rec.update(location=LOCATION, access=_vault(h, SELLER)["access"])
    with h.lock:
        _save(h, SELLER, rec)
    return rec


def deletion_answer(h, challenge):
    """eBay's Marketplace Account Deletion check: production keys stay off until this endpoint answers."""
    app = _vault(h, APP) or {}
    return hashlib.sha256((challenge + app.get("verify_token", "") + app.get("endpoint", "")).encode()).hexdigest()


def status(h):
    """What the dashboard shows: no tokens."""
    app, rec = _vault(h, APP), _vault(h, SELLER)
    return {"app": bool(app), "endpoint": (app or {}).get("endpoint"), "verify_token": (app or {}).get("verify_token"),
            "connected": (rec or {}).get("connected"), "policies": sorted((rec or {}).get("policies") or {}),
            "error": (rec or {}).get("error")}


# ---- calls -----------------------------------------------------------------------------------
def _user_token(h):
    rec = _vault(h, SELLER)
    if not rec:
        raise ValueError("eBay isn't linked yet: Jack presses Connect eBay on the Vault tab")
    if rec["expires"] - time.time() < 300:
        app = _vault(h, APP)
        st, tok = http("POST", TOKEN_URL, headers={"Authorization": _basic(app)}, form=True,
                       data={"grant_type": "refresh_token", "refresh_token": rec["refresh"], "scope": SCOPES})
        if st != 200 or "access_token" not in tok:
            raise RuntimeError(f"eBay wouldn't renew the link ({st}); press Connect eBay again")
        rec.update(access=tok["access_token"], expires=time.time() + int(tok.get("expires_in", 7200)))
        with h.lock:
            _save(h, SELLER, rec)
    return rec["access"]


def _app_token(h):
    if _app_tok.get("expires", 0) - time.time() > 300:
        return _app_tok["token"]
    app = _vault(h, APP)
    st, tok = http("POST", TOKEN_URL, headers={"Authorization": _basic(app)}, form=True,
                   data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"})
    if st != 200 or "access_token" not in tok:
        raise RuntimeError(f"eBay refused the app token ({st})")
    _app_tok.update(token=tok["access_token"], expires=time.time() + int(tok.get("expires_in", 7200)))
    return _app_tok["token"]


def _api(h, method, path, data=None, app=False):
    st, out = http(method, API + path, data=data, headers={
        "Authorization": "Bearer " + (_app_token(h) if app else _user_token(h)),
        "Content-Language": "en-US", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"})
    if st not in (200, 201, 204):
        msg = "; ".join(e.get("message", "") for e in out.get("errors") or []) or out
        raise RuntimeError(f"eBay said {st} for {path.split('?')[0]}: {msg}")
    return out


# ---- pricing ---------------------------------------------------------------------------------
def _market(h, keywords):
    q = urllib.parse.urlencode({"q": keywords, "limit": 20, "sort": "price",
                                "filter": "conditions:{NEW},itemLocationCountry:US,buyingOptions:{FIXED_PRICE}"})
    items = (_api(h, "GET", f"/buy/browse/v1/item_summary/search?{q}", app=True) or {}).get("itemSummaries") or []
    ship = lambda i: float(((i.get("shippingOptions") or [{}])[0].get("shippingCost") or {}).get("value") or 0)
    return sorted(round(float(i["price"]["value"]) + ship(i), 2) for i in items if (i.get("price") or {}).get("currency", "USD") == "USD")


def price_for(h, vid, keywords):
    """The price this item lists at, or ValueError saying why it can't be listed. Jack, Oct 28: never a loss
    after fees; $1.50 and 10% at least; as high as stays competitive."""
    quotes = [cj.quote(h, vid, 1, z) for z in QUOTE_ZIPS]          # ValueError: no fast US route
    q = max(quotes, key=lambda x: x["total"])
    floor = money.floor("ebay", q["total"])
    comps = _market(h, keywords)
    if len(comps) >= MARKET_MIN:
        market = comps[0]
        price = round(market - 0.01, 2)
        if price < floor:
            raise ValueError(f"floor ${floor:.2f} is above the market ${market:.2f}: CJ ${q['item']:.2f} + "
                             f"${q['freight']:.2f} shipping leaves no price that clears $1.50 and 10% after eBay's fee")
    else:
        market = None
        price = max(floor, min(round(floor * 1.5, 2), NO_MARKET_CAP))
    if not money.ok("ebay", price, q["total"]):                  # never: floor() guarantees it; checked anyway
        raise ValueError(f"${price:.2f} doesn't clear the money rule on a ${q['total']:.2f} cost")
    return {"price": price, "floor": floor, "market": market, "cost": q["total"], "quote": q}


# ---- listings --------------------------------------------------------------------------------
def post(h, who, f):
    """An agent's resale item, live on eBay at the hub's price. f: product, vid, title, description, keywords,
    images (public https URLs, CJ's own are fine), quantity, aspects. Returns {listing_id, live, price, floor, market}."""
    for k in ("product", "vid", "title", "description", "keywords"):
        if not f.get(k):
            raise ValueError(f"missing {k}")
    if not f.get("images"):
        raise ValueError("a listing needs at least one picture URL")
    with h.lock:
        if not h.db.execute("select 1 from products where name=? and status='active'", (f["product"],)).fetchone():
            raise ValueError('"product" must name the hub product this listing sells (fleet product add it first)')
        live = [dict(r) for r in h.db.execute("select sku, title, listing_id from ebay_listings where state='active'")]
    sku = f"cj-{f['vid']}"
    twin = next((r for r in live if r["sku"] == sku or _same(_item(r["title"]), _item(f["title"]))), None)
    if twin:
        raise ValueError(f"the eBay shop already sells this: https://www.ebay.com/itm/{twin['listing_id']} "
                         f"\"{twin['title'][:80]}\"; pick a different item")
    seller = _vault(h, SELLER) or {}
    if len(seller.get("policies") or {}) < 3:
        raise ValueError("the eBay account has no business policies yet (shipping, payment, returns): on Jack's list")
    p = price_for(h, f["vid"], f["keywords"])
    sug = (_api(h, "GET", "/commerce/taxonomy/v1/category_tree/0/get_category_suggestions?" +
                urllib.parse.urlencode({"q": f["keywords"]})) or {}).get("categorySuggestions") or []
    if not sug:
        raise ValueError(f"eBay suggests no category for \"{f['keywords']}\"; try plainer keywords")
    qty = int(f.get("quantity") or 10)
    _api(h, "PUT", f"/sell/inventory/v1/inventory_item/{sku}", {
        "availability": {"shipToLocationAvailability": {"quantity": qty}}, "condition": "NEW",
        "product": {"title": f["title"][:80], "description": f["description"], "imageUrls": f["images"][:12],
                    "aspects": f.get("aspects") or {}}})
    offer = {"sku": sku, "marketplaceId": "EBAY_US", "format": "FIXED_PRICE", "availableQuantity": qty,
             "categoryId": sug[0]["category"]["categoryId"], "listingDescription": f["description"],
             "listingPolicies": seller["policies"], "merchantLocationKey": seller["location"],
             "pricingSummary": {"price": {"value": f"{p['price']:.2f}", "currency": "USD"}}}
    oid = _api(h, "POST", "/sell/inventory/v1/offer", offer)["offerId"]
    try:
        lid = _api(h, "POST", f"/sell/inventory/v1/offer/{oid}/publish")["listingId"]
    except RuntimeError as e:
        if "limit" in str(e).lower():                 # new sellers start with low monthly limits
            with h.lock:
                h._needs_jack_once(f"eBay selling limit reached, {f['title'][:60]} not posted: {e}. "
                                   "Ask eBay for a higher limit: https://www.ebay.com/sh/ovw")
        raise
    live_url = f"https://www.ebay.com/itm/{lid}"
    with h.lock:
        h.db.execute("insert or replace into ebay_listings(sku, product, vid, title, keywords, offer_id, listing_id, price, "
                     "offer, state, updated) values(?,?,?,?,?,?,?,?,?,'active',?)",
                     (sku, f["product"], f["vid"], f["title"], f["keywords"], oid, lid, p["price"], json.dumps(offer), h.clock()))
        h.db.execute("update products set link=?, listing_state='active' where name=? and coalesce(link,'')=''", (live_url, f["product"]))
        h._log(None, who, "out", f"ebay listing live {lid} at ${p['price']:.2f} (floor ${p['floor']:.2f}): {f['title'][:100]} {live_url}")
    return {"listing_id": lid, "live": live_url, "price": p["price"], "floor": p["floor"], "market": p["market"]}


def requote(h):
    """Daily: every live listing re-priced from a fresh CJ quote and today's market; one no price can carry ends."""
    with h.lock:
        rows = [dict(r) for r in h.db.execute("select * from ebay_listings where state='active'")]
    for r in rows:
        try:
            try:
                p = price_for(h, r["vid"], r["keywords"])
            except ValueError as e:
                _api(h, "POST", f"/sell/inventory/v1/offer/{r['offer_id']}/withdraw")
                with h.lock:
                    h.db.execute("update ebay_listings set state='ended', updated=? where sku=?", (h.clock(), r["sku"]))
                    pm = h.db.execute("select pm from products where name=?", (r["product"],)).fetchone()
                    h._log(None, "hub", "out", f"ebay listing {r['listing_id']} ended: {e}")
                    if pm and pm["pm"]:
                        h._note(pm["pm"], f"{r['product']}: eBay listing {r['listing_id']} ended",
                                f"https://www.ebay.com/itm/{r['listing_id']} was ended by the daily re-quote: {e}")
                continue
            if p["price"] != r["price"]:
                offer = json.loads(r["offer"])
                offer["pricingSummary"]["price"]["value"] = f"{p['price']:.2f}"
                _api(h, "PUT", f"/sell/inventory/v1/offer/{r['offer_id']}", offer)
                with h.lock:
                    h.db.execute("update ebay_listings set price=?, offer=?, updated=? where sku=?",
                                 (p["price"], json.dumps(offer), h.clock(), r["sku"]))
        except RuntimeError as e:
            with h.lock:
                h._log(None, "hub", "out", f"ebay re-quote of {r['sku']} failed, kept as is: {e}")


# ---- orders ----------------------------------------------------------------------------------
def _orders(h):
    return (_api(h, "GET", "/sell/fulfillment/v1/order?limit=200") or {}).get("orders") or []


def _money(o):
    s = o["pricingSummary"]
    sale = round(float(s["priceSubtotal"]["value"]) + float((s.get("deliveryCost") or {}).get("value") or 0), 2)
    tax = round(sum(float(t["amount"]["value"]) for li in o["lineItems"] for t in li.get("ebayCollectAndRemitTaxes") or []), 2)
    return sale, tax


def _product(h, sku):
    with h.lock:
        r = h.db.execute("select product from ebay_listings where sku=?", (sku,)).fetchone()
    return r and r["product"]


def sales(h):
    """Paid eBay orders as sales rows (the buyer's price, not the tax eBay collects)."""
    if not _vault(h, SELLER):
        return []
    rows = []
    for o in _orders(h):
        if o.get("orderPaymentStatus") != "PAID":
            continue
        sale, _ = _money(o)
        at = time.mktime(time.strptime(o["creationDate"][:19], "%Y-%m-%dT%H:%M:%S")) if o.get("creationDate") else h.clock()
        rows.append({"source": "ebay", "external_id": o["orderId"], "amount": sale, "currency": "usd",
                     "product": _product(h, o["lineItems"][0]["sku"]), "at": at})
    return rows


def paid_orders(h):
    """For orders.py: paid, not yet shipped, one CJ variant each. Anything else goes to Jack."""
    if not _vault(h, SELLER):
        return []
    out = []
    for o in _orders(h):
        if o.get("orderPaymentStatus") != "PAID" or o.get("orderFulfillmentStatus") != "NOT_STARTED":
            continue
        link = f"https://www.ebay.com/sh/ord/details?orderid={o['orderId']}"
        lis = o["lineItems"]
        if len(lis) != 1 or not lis[0]["sku"].startswith("cj-"):
            # ponytail: one item per order covers our listings; a multi-item cart is ordered by hand
            with h.lock:
                h._needs_jack_once(f"eBay order {o['orderId']} has {len(lis)} items or a non-CJ item; order it by hand. {link}")
            continue
        to = o["fulfillmentStartInstructions"][0]["shippingStep"]["shipTo"]
        a = to["contactAddress"]
        sale, tax = _money(o)
        out.append({"order_id": o["orderId"], "vid": lis[0]["sku"][3:], "qty": lis[0]["quantity"], "sale": sale, "tax": tax,
                    "product": _product(h, lis[0]["sku"]), "link": link,
                    "ship_by": ((lis[0].get("lineItemFulfillmentInstructions") or {}).get("shipByDate") or "")[:10],
                    "address": {"name": to["fullName"], "line1": a["addressLine1"], "line2": a.get("addressLine2", ""),
                                "city": a["city"], "state": a["stateOrProvince"], "zip": a["postalCode"],
                                "country": a.get("countryCode", "US"), "phone": (to.get("primaryPhone") or {}).get("phoneNumber", "")}})
    return out


CARRIERS = {"usps": "USPS", "ups": "UPS", "fedex": "FEDEX", "dhl": "DHL"}


def send_tracking(h, order_id, carrier, number):
    o = _api(h, "GET", f"/sell/fulfillment/v1/order/{order_id}")
    code = next((v for k, v in CARRIERS.items() if k in carrier.lower()), carrier)
    _api(h, "POST", f"/sell/fulfillment/v1/order/{order_id}/shipping_fulfillment", {
        "lineItems": [{"lineItemId": li["lineItemId"], "quantity": li["quantity"]} for li in o["lineItems"]],
        "shippedDate": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "shippingCarrierCode": code, "trackingNumber": number})


def smoke():
    """PLAN9 step 7 on the hub PC: the link works and the market can be read. Posts nothing."""
    import etsy_audit
    h = etsy_audit.H(r"C:\fleet\hub.db")
    return {"status": status(h), "market": _market(h, "garlic press")[:3]}
