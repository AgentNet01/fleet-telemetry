"""CJdropshipping API v2: quotes, orders, wallet payment, tracking. Nothing else talks to CJ.

Jack keeps the account in the vault as "cj-key" = {"email", "api_key"}, scope hub. Paths and field names follow
developers.cjdropshipping.com; `smoke()` checks them against the real API before any order (PLAN8 step 6).
"""
import json
import time
import urllib.error
import urllib.request

API = "https://developers.cjdropshipping.com/api2.0/v1"
KEY = "cj-key"
MAX_DAYS = 8                 # slowest delivery we accept: eBay's stated window with 3 days' handling
_tok = {}                    # {"token", "expires"}: kept in memory, CJ limits how often a token may be fetched


def http(method, url, headers=None, data=None):
    """(status, json). JSON in and out. Swapped out in tests."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method,
                                 headers=dict(headers or {}, **({"Content-Type": "application/json"} if body else {})))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {}


def _key(h):
    with h.lock:
        r = h.db.execute("select value from secrets where name=?", (KEY,)).fetchone()
    if not r:
        raise ValueError("CJ isn't linked yet: Jack puts cj-key in the vault")
    return json.loads(r["value"])


def _token(h):
    if _tok.get("expires", 0) - time.time() > 3600:
        return _tok["token"]
    k = _key(h)
    # ponytail: newer CJ docs take apiKey, older ones email + password=apiKey; both are sent, smoke() confirms
    st, out = http("POST", f"{API}/authentication/getAccessToken",
                   data={"email": k["email"], "password": k["api_key"], "apiKey": k["api_key"]})
    d = out.get("data") or {}
    if st != 200 or not d.get("accessToken"):
        raise RuntimeError(f"CJ refused the key ({st}): {out.get('message') or out}")
    _tok.update(token=d["accessToken"], expires=time.time() + 14 * 86400)
    return _tok["token"]


def _call(h, method, path, data=None):
    st, out = http(method, API + path, headers={"CJ-Access-Token": _token(h)}, data=data)
    if st != 200 or out.get("code") not in (200, None) or out.get("result") is False:
        raise RuntimeError(f"CJ said {st} for {path.split('?')[0]}: {out.get('message') or out}")
    return out.get("data")


def quote(h, vid, qty, zip_code, start="US", max_days=MAX_DAYS):
    """The real cost to get qty of variant vid to a US zip: item + cheapest shipping that arrives in max_days
    (None: any speed, for stock going to an Amazon warehouse)."""
    item = round(float(_call(h, "GET", f"/product/variant/queryByVid?vid={vid}")["variantSellPrice"]) * qty, 2)
    ways = _call(h, "POST", "/logistic/freightCalculate", {"startCountryCode": start, "endCountryCode": "US",
                                                            "zip": zip_code, "products": [{"vid": vid, "quantity": qty}]})
    fast = [w for w in ways or [] if max_days is None or int(str(w.get("logisticAging", "99")).split("-")[-1]) <= max_days]
    if not fast:
        raise ValueError(f"CJ can't get {vid} from {start} to the US within {max_days} days")
    w = min(fast, key=lambda w: float(w["logisticPrice"]))
    freight = round(float(w["logisticPrice"]), 2)
    return {"item": item, "freight": freight, "tax": 0.0, "total": round(item + freight, 2),
            "logistic": w["logisticName"], "days": w["logisticAging"], "start": start}


def place(h, our_no, vid, qty, addr, logistic, start="US"):
    """One CJ order to the buyer; returns CJ's order id. our_no is our row id, so a lost answer can be found again."""
    d = _call(h, "POST", "/shopping/order/createOrderV2", {
        "orderNumber": str(our_no), "shippingCountryCode": addr.get("country", "US"), "shippingCountry": addr.get("country", "US"),
        "shippingProvince": addr["state"], "shippingCity": addr["city"], "shippingAddress": addr["line1"],
        "shippingAddress2": addr.get("line2", ""), "shippingZip": addr["zip"], "shippingCustomerName": addr["name"],
        "shippingPhone": addr.get("phone", ""), "logisticName": logistic, "fromCountryCode": start,
        "products": [{"vid": vid, "quantity": qty}]})
    return d["orderId"]


def pay(h, cj_id):
    _call(h, "POST", "/shopping/pay/payBalance", {"orderId": cj_id})


def find(h, our_no):
    """CJ's id for our order number, or None if CJ never made it."""
    d = _call(h, "GET", f"/shopping/order/list?orderNumber={our_no}&pageNum=1&pageSize=10") or {}
    got = [o for o in d.get("list") or [] if str(o.get("orderNumber")) == str(our_no)]
    return got[0]["orderId"] if got else None


def tracking(h, cj_id):
    """(carrier, number) once CJ has shipped, else None."""
    d = _call(h, "GET", f"/shopping/order/getOrderDetail?orderId={cj_id}") or {}
    return (d.get("logisticName") or "Other", d["trackNumber"]) if d.get("trackNumber") else None


def balance(h):
    return float((_call(h, "GET", "/shopping/pay/getBalance") or {}).get("amount") or 0)


def smoke(vid, zip_code="10001"):
    """PLAN8 step 6 on the hub PC: token, wallet and one real quote. Places nothing."""
    import etsy_audit
    h = etsy_audit.H(r"C:\fleet\hub.db")
    return {"balance": balance(h), "quote": quote(h, vid, 1, zip_code)}
