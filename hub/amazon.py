"""Amazon FBA: stock proposals with every cost, Jack buys, the hub lists, re-prices and pulls sales. PLAN10.

FBA, not dropshipping: we buy stock, ship it to Amazon's warehouse, Amazon packs and ships every order, so the
buyer sees only us as seller. The hub never buys stock: every buy is Jack's yes on a proposal that shows each
cost. Selling Partner API, own-account app; Jack keeps "amazon-app" = {"client_id", "client_secret",
"refresh_token", "seller_id"} in the vault, scope hub.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request

import cj
import money

LWA_URL = "https://api.amazon.com/auth/o2/token"
API = "https://sellingpartnerapi-na.amazon.com"
MARKET = "ATVPDKIKX0DER"     # amazon.com
APP = "amazon-app"
FBA_ZIP = "92551"            # ponytail: a west-coast FBA site for the freight quote; Amazon names the real one per shipment
STORAGE_PER_CUFT = 2.40      # Oct-Dec standard-size monthly rate, the dearest; https://sellercentral.amazon.com/help/hub/reference/external/G3EDYEF6KUCFQTNM
STORAGE_MONTHS = 3           # assumed sell-through
FIRST_UNITS, FIRST_CASH = 20, 100.00   # first buy of a product: at most 20 units or $100
_tok = {}


def http(method, url, headers=None, data=None, form=False):
    """(status, json). Swapped out in tests."""
    body, headers = None, dict(headers or {})
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


def _app(h):
    with h.lock:
        r = h.db.execute("select value from secrets where name=?", (APP,)).fetchone()
    if not r:
        raise ValueError("Amazon isn't linked yet: Jack puts amazon-app in the vault")
    return json.loads(r["value"])


def _token(h):
    if _tok.get("expires", 0) - time.time() > 300:
        return _tok["token"]
    a = _app(h)
    st, out = http("POST", LWA_URL, form=True, data={"grant_type": "refresh_token", "refresh_token": a["refresh_token"],
                                                     "client_id": a["client_id"], "client_secret": a["client_secret"]})
    if st != 200 or "access_token" not in out:
        raise RuntimeError(f"Amazon refused the app's refresh token ({st}): {out.get('error_description') or out.get('error')}")
    _tok.update(token=out["access_token"], expires=time.time() + int(out.get("expires_in", 3600)))
    return _tok["token"]


def _api(h, method, path, data=None):
    st, out = http(method, API + path, data=data, headers={"x-amz-access-token": _token(h)})
    if st not in (200, 201, 202, 204):
        msg = "; ".join(e.get("message", "") for e in out.get("errors") or []) or out
        raise RuntimeError(f"Amazon said {st} for {path.split('?')[0]}: {msg}")
    return out


# ---- the numbers -----------------------------------------------------------------------------
def buybox(h, asin):
    s = (_api(h, "GET", f"/products/pricing/v0/items/{asin}/offers?MarketplaceId={MARKET}&ItemCondition=New")
         .get("payload") or {}).get("Summary") or {}
    box = [b for b in s.get("BuyBoxPrices") or [] if b.get("condition", "New").lower() == "new"]
    if not box:
        raise ValueError(f"{asin} has no Buy Box price right now, so there's no market price to check against")
    return float(box[0]["LandedPrice"]["Amount"])


def _fees(h, asin, price):
    """(total, referral rate, fixed FBA fee) at this price, from Amazon's own estimate."""
    body = {"FeesEstimateRequest": {"MarketplaceId": MARKET, "IsAmazonFulfilled": True, "Identifier": f"{asin}-{price}",
                                    "PriceToEstimateFees": {"ListingPrice": {"CurrencyCode": "USD", "Amount": price}}}}
    r = _api(h, "POST", f"/products/fees/v0/items/{asin}/feesEstimate", body)["payload"]["FeesEstimateResult"]
    if r.get("Status") != "Success":
        raise ValueError(f"Amazon can't estimate fees for {asin}: {r.get('Error') or r}")
    est = r["FeesEstimate"]
    parts = {d["FeeType"]: float(d["FinalFee"]["Amount"]) for d in est.get("FeeDetailList") or []}
    total = float(est["TotalFeesEstimate"]["Amount"])
    return total, parts.get("ReferralFee", 0.0) / price, total - parts.get("ReferralFee", 0.0)


def _cuft(h, asin):
    items = _api(h, "GET", f"/catalog/2022-04-01/items/{asin}?marketplaceIds={MARKET}&includedData=dimensions,summaries")
    d = ((items.get("dimensions") or [{}])[0].get("package")) or {}
    if not all(k in d for k in ("length", "width", "height")):
        raise ValueError(f"Amazon has no package size for {asin}, so storage can't be costed")
    inch = lambda k: float(d[k]["value"]) / (2.54 if str(d[k].get("unit", "")).startswith("centimeter") else 1)
    title = ((items.get("summaries") or [{}])[0]).get("itemName", asin)
    return inch("length") * inch("width") * inch("height") / 1728, title


def _profit(price, fee_total, unit, storage):
    return round(price - fee_total - unit - storage, 2)


def _passes(price, fee_total, unit, storage):
    return _profit(price, fee_total, unit, storage) >= max(money.MIN_PROFIT, round(money.MIN_MARGIN * price, 2))


def _floor(h, asin, unit, storage, rate, fixed):
    """Lowest price that clears the money rule: solved from the fee split, then checked with Amazon's estimate."""
    base = fixed + unit + storage
    p = max((base + money.MIN_PROFIT) / (1 - rate), base / (1 - rate - money.MIN_MARGIN))
    p = math.ceil(round(p * 100, 6)) / 100
    for _ in range(50):                               # a few cents for rounding in Amazon's fee
        if _passes(p, _fees(h, asin, p)[0], unit, storage):
            return p
        p = round(p + 0.01, 2)
    raise ValueError(f"no price near ${p:.2f} clears the money rule for {asin}")


# ---- proposals -------------------------------------------------------------------------------
def propose(h, who, asin, vid, product):
    """An agent's FBA pick, costed. Fails the money rule or restricted: refused to the agent with the numbers.
    Passes: one Jack item, nothing bought. Returns the proposal id."""
    with h.lock:
        if not h.db.execute("select 1 from products where name=? and status='active'", (product,)).fetchone():
            raise ValueError('"product" must name the hub product (fleet product add it first)')
    a = _app(h)
    r = _api(h, "GET", f"/listings/2021-08-01/restrictions?asin={asin}&sellerId={a['seller_id']}"
                       f"&marketplaceIds={MARKET}&conditionType=new_new")
    if r.get("restrictions"):
        why = "; ".join(x.get("message", "") for res in r["restrictions"] for x in res.get("reasons") or [])
        raise ValueError(f"Amazon restricts {asin} for our account ({why or 'approval required'}); pick another")
    price = buybox(h, asin)
    fee_total, rate, fixed = _fees(h, asin, price)
    cuft, title = _cuft(h, asin)
    storage = round(cuft * STORAGE_PER_CUFT * STORAGE_MONTHS, 2)
    q = cj.quote(h, vid, FIRST_UNITS, FBA_ZIP, start="CN", max_days=None)
    unit = round(q["total"] / FIRST_UNITS, 2)
    units = min(FIRST_UNITS, int(FIRST_CASH // unit))
    cash = round(units * unit, 2)
    profit = _profit(price, fee_total, unit, storage)
    lines = (f"Buy Box ${price:.2f}, fees ${fee_total:.2f}, unit + freight ${unit:.2f}, storage ${storage:.2f} "
             f"→ profit ${profit:.2f}/unit")
    if not _passes(price, fee_total, unit, storage):
        raise ValueError(f"{asin} fails the money rule: {lines} (needs ${max(money.MIN_PROFIT, round(money.MIN_MARGIN * price, 2)):.2f})")
    even = math.ceil(cash / (price - fee_total - storage))
    with h.lock:
        pid = h.db.execute("insert into amazon_proposals(asin, vid, product, title, units, unit, storage, price, state, who, created) "
                           "values(?,?,?,?,?,?,?,?,'proposed',?,?)",
                           (asin, vid, product, title, units, unit, storage, price, who, h.clock())).lastrowid
        h._needs_jack(f"Amazon FBA buy? #{pid} {title} https://www.amazon.com/dp/{asin} (from {who}): {lines}. "
                      f"Buy {units} units = ${cash:.2f} cash out, break even after {even} sales. If yes: order {units} of "
                      f"CJ variant {vid} shipped to the FBA address from a Send to Amazon shipment (Amazon-optimized "
                      f"splits, no placement fee), then tell the hub the stock is in: fleet amazon list {pid}")
    return pid


def list_stock(h, pid):
    """Stock is at Amazon: list it against the ASIN at Buy Box - $0.01, never under the floor."""
    with h.lock:
        p = dict(h.db.execute("select * from amazon_proposals where id=?", (pid,)).fetchone())
    a = _app(h)
    sku = f"fba-{p['asin']}"
    price = buybox(h, p["asin"])
    _, rate, fixed = _fees(h, p["asin"], price)
    floor = _floor(h, p["asin"], p["unit"], p["storage"], rate, fixed)
    ours = max(round(price - 0.01, 2), floor)
    _api(h, "PUT", f"/listings/2021-08-01/items/{a['seller_id']}/{urllib.parse.quote(sku)}?marketplaceIds={MARKET}", {
        "productType": "PRODUCT", "requirements": "LISTING_OFFER_ONLY", "attributes": {
            "condition_type": [{"value": "new_new"}], "merchant_suggested_asin": [{"value": p["asin"]}],
            "fulfillment_availability": [{"fulfillment_channel_code": "AMAZON_NA"}],
            "purchasable_offer": [{"currency": "USD", "marketplace_id": MARKET, "our_price": [{"schedule": [{"value_with_tax": ours}]}]}]}})
    with h.lock:
        h.db.execute("insert or replace into amazon_listings(sku, asin, product, unit, storage, price, state, updated) "
                     "values(?,?,?,?,?,?,'active',?)", (sku, p["asin"], p["product"], p["unit"], p["storage"], ours, h.clock()))
        h.db.execute("update amazon_proposals set state='listed' where id=?", (pid,))
        h.db.execute("update products set link=?, listing_state='active' where name=? and coalesce(link,'')=''",
                     (f"https://www.amazon.com/dp/{p['asin']}", p["product"]))
    return {"sku": sku, "price": ours, "floor": floor}


def floor_price(h, sku):
    with h.lock:
        r = dict(h.db.execute("select * from amazon_listings where sku=?", (sku,)).fetchone())
    _, rate, fixed = _fees(h, r["asin"], r["price"])
    return _floor(h, r["asin"], r["unit"], r["storage"], rate, fixed)


def reprice(h):
    """Daily: follow the Buy Box down to the floor, never under; the PM hears when the floor holds."""
    a = _app(h)
    with h.lock:
        rows = [dict(r) for r in h.db.execute("select * from amazon_listings where state='active'")]
    for r in rows:
        try:
            box = buybox(h, r["asin"])
            floor = floor_price(h, r["sku"])
            ours = max(round(box - 0.01, 2), floor)
            if ours != r["price"]:
                _api(h, "PATCH", f"/listings/2021-08-01/items/{a['seller_id']}/{urllib.parse.quote(r['sku'])}?marketplaceIds={MARKET}",
                     {"productType": "PRODUCT", "patches": [{"op": "replace", "path": "/attributes/purchasable_offer", "value": [
                         {"currency": "USD", "marketplace_id": MARKET, "our_price": [{"schedule": [{"value_with_tax": ours}]}]}]}]})
                with h.lock:
                    h.db.execute("update amazon_listings set price=?, updated=? where sku=?", (ours, h.clock(), r["sku"]))
            if ours == floor and box < floor:
                with h.lock:
                    pm = h.db.execute("select pm from products where name=?", (r["product"],)).fetchone()
                    if pm and pm["pm"]:
                        h._note(pm["pm"], f"{r['product']}: Amazon Buy Box ${box:.2f} is under our floor ${floor:.2f}",
                                f"https://www.amazon.com/dp/{r['asin']} stays at the floor; we won't win the Buy Box until "
                                "the market comes back up. Don't reorder stock for it until then.")
        except (ValueError, RuntimeError) as e:
            with h.lock:
                h._log(None, "hub", "out", f"amazon re-price of {r['sku']} failed, kept as is: {e}")


def sales(h):
    """Amazon orders as sales rows: what the buyer paid for the items, not the tax Amazon collects."""
    try:
        _app(h)
    except ValueError:
        return []
    after = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(h.clock() - 30 * 86400))
    orders = (_api(h, "GET", f"/orders/v0/orders?MarketplaceIds={MARKET}&CreatedAfter={after}").get("payload") or {}).get("Orders") or []
    with h.lock:
        seen = {r["external_id"] for r in h.db.execute("select external_id from sales where source='amazon'")}
    rows = []
    for o in orders:
        if o["AmazonOrderId"] in seen or o.get("OrderStatus") in ("Pending", "Canceled"):
            continue
        items = _api(h, "GET", f"/orders/v0/orders/{o['AmazonOrderId']}/orderItems")["payload"]["OrderItems"]
        amount = round(sum(float((i.get("ItemPrice") or {}).get("Amount") or 0) + float((i.get("ShippingPrice") or {}).get("Amount") or 0)
                           for i in items), 2)
        with h.lock:
            p = h.db.execute("select product from amazon_listings where sku=?", (items[0]["SellerSKU"],)).fetchone() if items else None
        at = time.mktime(time.strptime(o["PurchaseDate"][:19], "%Y-%m-%dT%H:%M:%S")) if o.get("PurchaseDate") else h.clock()
        rows.append({"source": "amazon", "external_id": o["AmazonOrderId"], "amount": amount, "currency": "usd",
                     "product": p and p["product"], "at": at})
    return rows


def smoke(asin):
    """PLAN10 step 6 on the hub PC: the token works and one ASIN's Buy Box and fees can be read. Buys nothing."""
    import etsy_audit
    h = etsy_audit.H(r"C:\fleet\hub.db")
    box = buybox(h, asin)
    return {"buybox": box, "fees": _fees(h, asin, box)[0]}
