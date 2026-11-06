"""PLAN10: Amazon FBA proposals with every cost, Jack buys, hub lists, re-prices and pulls sales.
Against a fake SP-API (and the fake CJ from test_orders); no network.

    python3 test_amazon.py <case> [<case> ...]
"""
import json
import os
import sys
import tempfile
import urllib.parse

import hub
from test_hub import Clock, FakeMuse
from test_orders import FakeCJ


class FakeSPAPI:
    def __init__(self):
        self.calls, self.lwa = [], 0
        self.buybox, self.referral, self.fba = 14.99, 0.15, 2.85
        self.restricted, self.listings, self.orders = False, {}, []
        self.dims = {"length": {"value": 6, "unit": "inches"}, "width": {"value": 6, "unit": "inches"},
                     "height": {"value": 1, "unit": "inches"}}              # 36 in3 = 0.0208 ft3

    def __call__(self, method, url, headers=None, data=None, form=False):
        self.calls.append((method, url, headers or {}, data))
        u = urllib.parse.urlparse(url)
        path, q = u.path, dict(urllib.parse.parse_qsl(u.query))
        if url.startswith("https://api.amazon.com/auth/o2/token"):
            self.lwa += 1
            ok = data["grant_type"] == "refresh_token" and data["refresh_token"] == "Atzr|R" and data["client_id"] == "CID"
            return (200, {"access_token": "Atza|A", "expires_in": 3600}) if ok else (400, {"error": "invalid_grant"})
        assert headers["x-amz-access-token"] == "Atza|A", headers
        if path == "/listings/2021-08-01/restrictions":
            return 200, {"restrictions": [{"reasons": [{"message": "approval required"}]}] if self.restricted else []}
        if path.startswith("/products/pricing/v0/items/"):
            return 200, {"payload": {"Summary": {"BuyBoxPrices": [{"condition": "New", "LandedPrice": {"Amount": self.buybox}}]}}}
        if path.endswith("/feesEstimate"):
            p = data["FeesEstimateRequest"]["PriceToEstimateFees"]["ListingPrice"]["Amount"]
            ref = round(p * self.referral + 0.004999, 2)
            return 200, {"payload": {"FeesEstimateResult": {"Status": "Success", "FeesEstimate": {
                "TotalFeesEstimate": {"Amount": round(ref + self.fba, 2)},
                "FeeDetailList": [{"FeeType": "ReferralFee", "FinalFee": {"Amount": ref}},
                                  {"FeeType": "FBAFees", "FinalFee": {"Amount": self.fba}}]}}}}
        if path.startswith("/catalog/2022-04-01/items/"):
            return 200, {"asin": "B0TEST", "summaries": [{"itemName": "Garlic Press"}], "dimensions": [{"package": self.dims}]}
        if path.startswith("/listings/2021-08-01/items/"):
            sku = urllib.parse.unquote(path.split("/")[-1])
            if method == "PUT":
                self.listings[sku] = data
            else:
                self.listings[sku]["patches"] = data["patches"]
            return 200, {"status": "ACCEPTED", "sku": sku}
        if path == "/orders/v0/orders":
            return 200, {"payload": {"Orders": self.orders}}
        if path.startswith("/orders/v0/orders/") and path.endswith("/orderItems"):
            return 200, {"payload": {"OrderItems": [{"SellerSKU": "fba-B0TEST", "QuantityOrdered": 1,
                                                     "ItemPrice": {"Amount": "14.98"}, "ShippingPrice": {"Amount": "0.00"}}]}}
        return 404, {"errors": [{"message": "no such fake route " + path}]}

    def price(self, sku="fba-B0TEST"):
        a = self.listings[sku]
        if "patches" in a:
            return a["patches"][0]["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
        return a["attributes"]["purchasable_offer"][0]["our_price"][0]["schedule"][0]["value_with_tax"]


def world():
    import amazon
    import cj
    fake, fcj = FakeSPAPI(), FakeCJ()
    amazon.http, cj.http = fake, fcj
    fcj.price, fcj.freight = 3.20, 20.00                      # 20 units: $3.20 each + $1.00 each freight = $4.20
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.secret_put("cj-key", json.dumps({"email": "a@b.c", "api_key": "K"}), "hub", by="test")
    h.secret_put("amazon-app", json.dumps({"client_id": "CID", "client_secret": "CS", "refresh_token": "Atzr|R",
                                           "seller_id": "S1"}), "hub", by="test")
    h.add_agent("Pam", "poll")
    h.add_product("Garlic press FBA", brief="CJ V1 to FBA", pm="Pam")
    return h, fake, fcj, amazon


def jack(h):
    return " | ".join(r["text"] for r in h.db.execute("select text from needs_jack where done=0"))


def auth():
    h, fake, fcj, amazon = world()
    amazon.buybox(h, "B0TEST")
    amazon.buybox(h, "B0TEST")
    assert fake.lwa == 1, f"one token for both calls: {fake.lwa}"
    print("auth OK")


def fba_proposal():
    h, fake, fcj, amazon = world()
    amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA")
    j = jack(h)
    for want in ("Buy Box $14.99", "fees $5.10", "unit + freight $4.20", "storage $0.15", "profit $5.54/unit",
                 "20 units", "$84.00", "break even after 9 sales", "https://www.amazon.com/dp/B0TEST"):
        assert want in j, f"Jack's item shows {want!r}: {j}"
    assert not fcj.created(), "nothing is bought"
    print("fba_proposal OK")


def fba_refused():
    h, fake, fcj, amazon = world()
    fake.fba = 7.25                                           # fees $9.50: 14.99 - 9.50 - 4.20 - 0.15 = $1.14
    try:
        amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA")
        err = ""
    except ValueError as e:
        err = str(e)
    assert "profit $1.14" in err and not jack(h), (err, jack(h))
    fake.fba, fake.restricted = 2.85, True
    try:
        amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA")
        err = ""
    except ValueError as e:
        err = str(e)
    assert "restrict" in err and not jack(h), (err, jack(h))
    print("fba_refused OK")


def fba_list():
    h, fake, fcj, amazon = world()
    pid = amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA")
    amazon.list_stock(h, pid)
    assert fake.price() == 14.98, fake.listings
    a = fake.listings["fba-B0TEST"]["attributes"]
    assert a["fulfillment_availability"][0]["fulfillment_channel_code"] == "AMAZON_NA" \
        and a["merchant_suggested_asin"][0]["value"] == "B0TEST", a
    print("fba_list OK")


def reprice():
    h, fake, fcj, amazon = world()
    amazon.list_stock(h, amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA"))
    fake.buybox = 7.00                                        # far under the floor
    amazon.reprice(h)
    floor = amazon.floor_price(h, "fba-B0TEST")
    assert fake.price() == floor and floor > 7.00, (fake.price(), floor)
    told = [r["text"] for r in h.db.execute("select text from items where too='Pam' and kind='note'")]
    assert any("floor" in t for t in told), told
    print("reprice OK")


def amazon_sales():
    h, fake, fcj, amazon = world()
    amazon.list_stock(h, amazon.propose(h, "Pam", "B0TEST", "V1", "Garlic press FBA"))
    fake.orders = [{"AmazonOrderId": "111-1", "OrderStatus": "Shipped", "FulfillmentChannel": "AFN",
                    "PurchaseDate": "2026-10-28T12:00:00Z", "OrderTotal": {"Amount": "16.18"}}]
    h.pull_revenue(lambda: amazon.sales(h))
    h.pull_revenue(lambda: amazon.sales(h))
    rows = [(r["amount"], r["product"]) for r in h.db.execute("select amount, product from sales where source='amazon'")]
    assert rows == [(14.98, "Garlic press FBA")], rows
    print("amazon_sales OK")


CASES = {f.__name__: f for f in (auth, fba_proposal, fba_refused, fba_list, reprice, amazon_sales)}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        CASES[name]()
