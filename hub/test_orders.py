"""PLAN8: supplier quotes, the profit floor, automatic CJ orders. Against a fake CJ; no network.

    python3 test_orders.py <case> [<case> ...]
"""
import json
import os
import sys
import tempfile

import hub
from test_hub import Clock, FakeMuse

DAY = 86400


class FakeCJ:
    """CJ API v2 as cj.py calls it: token, variant, freight, create, pay, detail, list by our number, balance."""
    def __init__(self):
        self.calls, self.orders = [], {}
        self.price, self.freight, self.balance = 3.20, 2.10, 100.0
        self.drop_create = False                       # CJ makes the order but the answer never arrives

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url, data))
        path = url.split("/api2.0/v1")[-1]
        if path == "/authentication/getAccessToken":
            return 200, {"code": 200, "data": {"accessToken": "tok", "accessTokenExpiryDate": "2099-01-01T00:00:00+08:00"}}
        assert (headers or {}).get("CJ-Access-Token") == "tok", headers
        if path.startswith("/product/variant/queryByVid"):
            return 200, {"code": 200, "data": {"vid": "V1", "variantSellPrice": self.price}}
        if path == "/logistic/freightCalculate":
            return 200, {"code": 200, "data": [{"logisticName": "CJPacket", "logisticPrice": self.freight + 3, "logisticAging": "8-12"},
                                               {"logisticName": "USPS", "logisticPrice": self.freight, "logisticAging": "3-5"}]}
        if path == "/shopping/order/createOrderV2":
            cid = f"CJ{len(self.orders) + 1}"
            self.orders[cid] = dict(data, orderId=cid, paid=False, trackNumber=None)
            if self.drop_create:
                raise ConnectionError("CJ hung up")
            return 200, {"code": 200, "data": {"orderId": cid}}
        if path == "/shopping/pay/payBalance":
            self.orders[data["orderId"]]["paid"] = True
            return 200, {"code": 200, "data": {}}
        if path.startswith("/shopping/order/list"):
            no = url.split("orderNumber=")[1].split("&")[0]
            return 200, {"code": 200, "data": {"list": [o for o in self.orders.values() if o["orderNumber"] == no]}}
        if path.startswith("/shopping/order/getOrderDetail"):
            o = self.orders[url.split("orderId=")[1]]
            return 200, {"code": 200, "data": {"orderId": o["orderId"], "trackNumber": o["trackNumber"],
                                               "logisticName": o.get("logisticName")}}
        if path == "/shopping/pay/getBalance":
            return 200, {"code": 200, "data": {"amount": self.balance}}
        return 404, {"code": 404}

    def created(self):
        return [c for c in self.calls if c[1].endswith("/shopping/order/createOrderV2")]


class FakeChannel:
    """A sales channel as orders.py sees one: paid orders in, tracking out."""
    def __init__(self):
        self.paid, self.sent = [], []

    def paid_orders(self, h):
        return list(self.paid)

    def send_tracking(self, h, order_id, carrier, number):
        self.sent.append((order_id, carrier, number))


ADDRESS = {"name": "Pat Buyer", "line1": "1 Main St", "city": "Albany", "state": "NY", "zip": "12207",
           "country": "US", "phone": "5550100"}


def world():
    import orders
    import cj
    fake, chan = FakeCJ(), FakeChannel()
    cj.http = fake
    clock = Clock()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), clock)
    h.secret_put("cj-key", json.dumps({"email": "a@b.c", "api_key": "K"}), "hub", by="test")
    orders.CHANNELS = {"ebay": chan}
    chan.paid.append({"order_id": "E1", "vid": "V1", "qty": 1, "sale": 9.99, "tax": 0.80, "address": dict(ADDRESS),
                      "ship_by": "2026-10-31", "product": "Garlic press", "link": "https://www.ebay.com/sh/ord/details?orderid=E1"})
    return h, fake, chan, clock, orders


def jack(h):
    return " | ".join(r["text"] for r in h.db.execute("select text from needs_jack where done=0"))


def floor():
    import money
    assert money.floor("ebay", 5.30) == 8.38, money.floor("ebay", 5.30)
    assert money.profit("ebay", 8.38, 5.30) >= 1.50 and money.profit("ebay", 8.38, 5.30) >= 0.838, money.profit("ebay", 8.38, 5.30)
    assert not money.ok("ebay", 8.37, 5.30), "a cent under the floor fails the rule"
    print("floor OK")


def fees():
    import money
    assert money.fees("ebay", 20.00, tax=1.60) == 3.34, money.fees("ebay", 20.00, tax=1.60)   # 13.6% of 21.60 + 0.40
    assert money.fees("ebay", 9.99, tax=0.80) == 1.77, money.fees("ebay", 9.99, tax=0.80)     # 13.6% of 10.79 + 0.30
    print("fees OK")


def quote():
    h, fake, chan, clock, orders = world()
    import cj
    q = cj.quote(h, "V1", 1, "12207")
    assert (q["item"], q["freight"], q["total"], q["logistic"]) == (3.20, 2.10, 5.30, "USPS"), q
    print("quote OK")


def order_auto():
    h, fake, chan, clock, orders = world()
    orders.tick(h)
    made = fake.created()
    assert len(made) == 1, f"one CJ order: {made}"
    body = made[0][2]
    assert body["shippingZip"] == "12207" and body["products"] == [{"vid": "V1", "quantity": 1}], body
    assert all(o["paid"] for o in fake.orders.values()), "paid from the wallet"
    assert not jack(h), jack(h)
    print("order_auto OK")


def order_refused():
    h, fake, chan, clock, orders = world()
    fake.freight = 4.50                                   # 3.20 + 4.50 = 7.70; 9.99 - 1.77 fee - 7.70 = 0.52
    orders.tick(h)
    assert not fake.created(), "nothing is ordered at a loss-making cost"
    j = jack(h)
    for want in ("item $3.20", "freight $4.50", "fee $1.77", "profit $0.52", "ship by 2026-10-31"):
        assert want in j, f"Jack's item shows {want!r}: {j}"
    orders.tick(h)
    assert j == jack(h), "refused once, not every tick"
    print("order_refused OK")


def order_cap():
    h, fake, chan, clock, orders = world()
    with h.lock:
        h.db.execute("insert into supplier_orders(channel, order_id, state, cost, placed) values('ebay','E0','placed',47.00,?)",
                     (clock(),))
    orders.tick(h)
    assert not fake.created(), "over the $50 day nothing is ordered"
    assert "$50" in jack(h) and "E1" in jack(h), jack(h)
    print("order_cap OK")


def order_once():
    h, fake, chan, clock, orders = world()
    fake.drop_create = True
    try:
        orders.tick(h)
    except ConnectionError:
        pass                                              # the hub died mid-call
    fake.drop_create = False
    orders.tick(h)
    orders.tick(h)
    assert len(fake.created()) == 1, f"CJ create-order called once in total: {len(fake.created())}"
    print("order_once OK")


def tracking():
    h, fake, chan, clock, orders = world()
    orders.tick(h)
    orders.track(h)
    assert not chan.sent, "no tracking yet, nothing sent"
    next(iter(fake.orders.values()))["trackNumber"] = "9400111"
    orders.track(h)
    orders.track(h)
    assert chan.sent == [("E1", "USPS", "9400111")], chan.sent
    assert h.db.execute("select state from supplier_orders where order_id='E1'").fetchone()["state"] == "shipped"
    print("tracking OK")


def purge():
    h, fake, chan, clock, orders = world()
    orders.tick(h)
    next(iter(fake.orders.values()))["trackNumber"] = "9400111"
    orders.track(h)
    clock.go(orders.KEEP_ADDRESS - DAY)
    orders.track(h)
    assert h.db.execute("select address from supplier_orders where order_id='E1'").fetchone()["address"], "kept while in transit"
    clock.go(2 * DAY)
    orders.track(h)
    assert h.db.execute("select address from supplier_orders where order_id='E1'").fetchone()["address"] is None, "address deleted"
    print("purge OK")


CASES = {f.__name__: f for f in (floor, fees, quote, order_auto, order_refused, order_cap, order_once, tracking, purge)}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        CASES[name]()
