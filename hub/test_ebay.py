"""PLAN9: eBay listings priced by the money rule, paid orders into sales and CJ ordering, tracking back.
Against a fake eBay (and the fake CJ from test_orders); no network.

    python3 test_ebay.py <case> [<case> ...]
"""
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import hub
from test_hub import Clock, FakeMuse
from test_orders import ADDRESS, FakeCJ

PASSWORD = "pw"


class FakeEbay:
    def __init__(self):
        self.calls = []
        self.comps = [10.49, 12.99, 13.50]                  # item prices; each ships for $1.00
        self.offers, self.orders = {}, []

    def __call__(self, method, url, headers=None, data=None, form=False):
        self.calls.append((method, url, headers or {}, data))
        u = urllib.parse.urlparse(url)
        path, q = u.path, dict(urllib.parse.parse_qsl(u.query))
        if path == "/identity/v1/oauth2/token":
            assert headers["Authorization"] == "Basic " + base64.b64encode(b"CID:CSEC").decode(), headers
            g = data["grant_type"]
            if g == "authorization_code":
                return (200, {"access_token": "acc1", "refresh_token": "ref1", "expires_in": 7200,
                              "refresh_token_expires_in": 47304000}) if data["code"] == "c0de" and data["redirect_uri"] == "Hub-RuName" \
                    else (400, {"error": "invalid_grant"})
            if g == "refresh_token":
                return 200, {"access_token": "acc2", "expires_in": 7200}
            if g == "client_credentials":
                return 200, {"access_token": "app1", "expires_in": 7200}
        if path.startswith("/buy/browse/"):
            assert headers["Authorization"] == "Bearer app1", headers
            return 200, {"itemSummaries": [{"title": f"Garlic Press {i}", "price": {"value": f"{p:.2f}", "currency": "USD"},
                                            "shippingOptions": [{"shippingCost": {"value": "1.00", "currency": "USD"}}]}
                                           for i, p in enumerate(self.comps)]}
        assert headers.get("Authorization", "").startswith("Bearer acc"), (url, headers)
        for kind in ("fulfillment", "payment", "return"):
            if path == f"/sell/account/v1/{kind}_policy":
                return 200, {f"{kind}Policies": [{f"{kind}PolicyId": f"{kind[:3].upper()}1", "name": kind}]}
        if path.startswith("/sell/inventory/v1/location/"):
            return 204, {}
        if path.startswith("/commerce/taxonomy/v1/category_tree/0/get_category_suggestions"):
            return 200, {"categorySuggestions": [{"category": {"categoryId": "20625", "categoryName": "Garlic Presses"}}]}
        if method == "PUT" and path.startswith("/sell/inventory/v1/inventory_item/"):
            return 204, {}
        if method == "POST" and path == "/sell/inventory/v1/offer":
            oid = f"OF{len(self.offers) + 1}"
            self.offers[oid] = dict(data, status="UNPUBLISHED")
            return 201, {"offerId": oid}
        if method == "POST" and path.endswith("/publish"):
            oid = path.split("/")[-2]
            self.offers[oid]["status"] = "PUBLISHED"
            return 200, {"listingId": "L" + oid[2:]}
        if method == "PUT" and path.startswith("/sell/inventory/v1/offer/"):
            self.offers[path.split("/")[-1]].update(data)
            return 204, {}
        if method == "POST" and path.endswith("/withdraw"):
            self.offers[path.split("/")[-2]]["status"] = "ENDED"
            return 200, {"listingId": "L1"}
        if method == "GET" and path == "/sell/fulfillment/v1/order":
            return 200, {"orders": self.orders}
        if method == "GET" and path.startswith("/sell/fulfillment/v1/order/"):
            return 200, next(o for o in self.orders if o["orderId"] == path.split("/")[-1])
        if method == "POST" and path.endswith("/shipping_fulfillment"):
            return 201, {}
        return 404, {"errors": [{"message": "no such fake route " + path}]}

    def offer_price(self, oid="OF1"):
        return self.offers[oid]["pricingSummary"]["price"]["value"]


def paid_order(oid="O1", sale=9.99, tax=0.80):
    a = ADDRESS
    return {"orderId": oid, "orderPaymentStatus": "PAID", "orderFulfillmentStatus": "NOT_STARTED",
            "creationDate": "2026-10-28T12:00:00.000Z",
            "pricingSummary": {"priceSubtotal": {"value": f"{sale - 1:.2f}"}, "deliveryCost": {"value": "1.00"}},
            "lineItems": [{"lineItemId": "LI1", "sku": "cj-V1", "quantity": 1,
                           "ebayCollectAndRemitTaxes": [{"amount": {"value": f"{tax:.2f}"}}],
                           "lineItemFulfillmentInstructions": {"shipByDate": "2026-10-31T23:59:59.000Z"}}],
            "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {
                "fullName": a["name"], "primaryPhone": {"phoneNumber": a["phone"]},
                "contactAddress": {"addressLine1": a["line1"], "city": a["city"], "stateOrProvince": a["state"],
                                   "postalCode": a["zip"], "countryCode": "US"}}}}]}


def world(linked=True):
    import ebay
    import cj
    fake, fcj = FakeEbay(), FakeCJ()
    ebay.http, cj.http = fake, fcj
    clock = Clock()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), clock)
    h.secret_put("cj-key", json.dumps({"email": "a@b.c", "api_key": "K"}), "hub", by="test")
    h.add_product("Garlic press", brief="CJ variant V1, $3.20 + $2.10 US shipping", pm="Pam")
    h.add_agent("Pam", "poll")
    h.add_agent("Ada", "poll")
    if linked:
        ebay.set_app(h, "CID", "CSEC", "Hub-RuName", "https://hub.example/ebay/deletion")
        state = urllib.parse.parse_qs(urllib.parse.urlparse(ebay.start(h)).query)["state"][0]
        ebay.finish(h, state, "c0de")
    return h, fake, fcj, clock, ebay


LISTING = {"product": "Garlic press", "vid": "V1", "title": "Garlic Press Stainless Steel Crusher",
           "description": "Crushes garlic.", "keywords": "garlic press stainless", "images": ["https://cf.cjdropshipping.com/a.jpg"]}


def ebay_post():
    h, fake, fcj, clock, ebay = world()
    r = ebay.post(h, "Ada", dict(LISTING))
    assert r["price"] == 11.48 and r["live"] == "https://www.ebay.com/itm/L1", r
    assert fake.offer_price() == "11.48" and fake.offers["OF1"]["sku"] == "cj-V1", fake.offers
    assert fake.offers["OF1"]["listingPolicies"] == {"fulfillmentPolicyId": "FUL1", "paymentPolicyId": "PAY1",
                                                     "returnPolicyId": "RET1"}, fake.offers["OF1"]
    link = h.db.execute("select link from products where name='Garlic press'").fetchone()["link"]
    assert link == "https://www.ebay.com/itm/L1", link
    try:
        ebay.post(h, "Ada", dict(LISTING))
        twice = True
    except ValueError:
        twice = False
    assert not twice, "a second post of the same item is refused"
    assert len(fake.offers) == 1, fake.offers
    print("ebay_post OK")


def ebay_price():
    h, fake, fcj, clock, ebay = world()
    fake.comps = [6.99, 7.50, 8.00]                        # cheapest $7.99 shipped
    try:
        ebay.post(h, "Ada", dict(LISTING))
        err = ""
    except ValueError as e:
        err = str(e)
    assert "floor $8.38 is above the market $7.99" in err, err
    assert not [c for c in fake.calls if "/sell/inventory/v1/inventory_item/" in c[1]], "nothing reaches eBay"
    print("ebay_price OK")


def requote():
    h, fake, fcj, clock, ebay = world()
    ebay.post(h, "Ada", dict(LISTING))
    fake.comps = [12.49, 13.00, 14.00]                     # market up: price follows to $13.48
    ebay.requote(h)
    assert fake.offer_price() == "13.48", fake.offer_price()
    fcj.price = 7.00                                       # cost $9.10: floor $12.98, above a $12.48 market
    fake.comps = [11.49, 12.00, 12.50]
    ebay.requote(h)
    assert fake.offers["OF1"]["status"] == "ENDED", fake.offers["OF1"]
    told = [r["text"] for r in h.db.execute("select text from items where too='Pam' and kind='note'")]
    assert any("ended" in t for t in told), told
    print("requote OK")


def ebay_sales():
    import orders
    h, fake, fcj, clock, ebay = world()
    ebay.post(h, "Ada", dict(LISTING))
    fake.orders = [paid_order()]
    h.pull_revenue(lambda: ebay.sales(h))
    h.pull_revenue(lambda: ebay.sales(h))
    rows = h.db.execute("select amount, product from sales where source='ebay'").fetchall()
    assert [(r["amount"], r["product"]) for r in rows] == [(9.99, "Garlic press")], [dict(r) for r in rows]
    orders.CHANNELS = {"ebay": ebay}
    orders.tick(h)
    orders.tick(h)
    assert len(fcj.created()) == 1, f"offered to CJ once: {len(fcj.created())}"
    assert fcj.created()[0][2]["shippingZip"] == "12207"
    print("ebay_sales OK")


def tracking():
    h, fake, fcj, clock, ebay = world()
    fake.orders = [paid_order()]
    ebay.send_tracking(h, "O1", "USPS", "9400111")
    sent = [c[3] for c in fake.calls if c[1].endswith("/order/O1/shipping_fulfillment")]
    assert sent and sent[0]["trackingNumber"] == "9400111" and sent[0]["shippingCarrierCode"] == "USPS" \
        and sent[0]["lineItems"] == [{"lineItemId": "LI1", "quantity": 1}], sent
    print("tracking OK")


def serve(h):
    srv = hub.serve(h, "127.0.0.1", 0, PASSWORD)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    auth = {"Authorization": "Basic " + base64.b64encode(f"jack:{PASSWORD}".encode()).decode(), "Content-Type": "application/json"}
    no_redirect = urllib.request.build_opener(type("N", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a: None}))

    def req(path, body=None, headers=auth):
        r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with no_redirect.open(r) as resp:
                return resp.status, resp.headers, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read().decode()
    return srv, req


def link():
    h, fake, fcj, clock, ebay = world(linked=False)
    srv, req = serve(h)
    assert req("/ebay/connect", headers={})[0] == 401, "linking needs the dashboard login"
    st, _, body = req("/api/jack/ebay/app", {"client_id": "CID", "client_secret": "CSEC", "runame": "Hub-RuName"})
    assert st == 200 and json.loads(body)["deletion_endpoint"].endswith("/ebay/deletion"), (st, body)
    st, hd, _ = req("/ebay/connect")
    assert st == 302 and hd["Location"].startswith(ebay.AUTH_URL), (st, dict(hd))
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(hd["Location"]).query))
    assert q["client_id"] == "CID" and q["redirect_uri"] == "Hub-RuName" and "sell.inventory" in q["scope"], q
    assert req("/ebay/callback?state=forged&code=c0de")[0] == 400, "a callback that didn't start here is refused"
    st, _, body = req(f"/ebay/callback?state={q['state']}&code=c0de")
    assert st == 200 and "eBay" in body, (st, body)
    seller = json.loads(h.db.execute("select value from secrets where name='ebay-seller'").fetchone()["value"])
    assert seller["policies"] == {"fulfillmentPolicyId": "FUL1", "paymentPolicyId": "PAY1", "returnPolicyId": "RET1"}, seller
    assert "acc1" not in req("/api/board")[2], "tokens never reach the dashboard"
    srv.shutdown()
    print("link OK")


def deletion():
    h, fake, fcj, clock, ebay = world()
    srv, req = serve(h)
    app = json.loads(h.db.execute("select value from secrets where name='ebay-app'").fetchone()["value"])
    st, _, body = req("/ebay/deletion?challenge_code=abc123", headers={})
    want = hashlib.sha256(("abc123" + app["verify_token"] + "https://hub.example/ebay/deletion").encode()).hexdigest()
    assert st == 200 and json.loads(body) == {"challengeResponse": want}, (st, body)
    st, _, _ = req("/ebay/deletion", {"metadata": {"topic": "MARKETPLACE_ACCOUNT_DELETION"}, "notification": {"data": {"userId": "u"}}}, headers={"Content-Type": "application/json"})
    assert st == 200, st
    srv.shutdown()
    print("deletion OK")


CASES = {f.__name__: f for f in (ebay_post, ebay_price, requote, ebay_sales, tracking, link, deletion)}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        CASES[name]()
