"""PLAN7: eBay dropship, Amazon FBA, Etsy designed-only. Against fakes only; no network.

    python3 test_commerce.py <case> [<case> ...]
"""
import json
import os
import sys
import tempfile
import time

import etsy
import hub
from test_etsy import FakeEtsy
from test_hub import Clock, FakeMuse


def etsy_hub():
    fake = FakeEtsy()
    etsy.http = fake
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.secret_put(etsy.APP, json.dumps({"key": "KEY", "secret": "SECRET"}), "hub", by="test")
    h.secret_put(etsy.SHOP + "42", json.dumps({"shop_id": 42, "access": "777.tokA", "refresh": "ref1",
                                                "expires": time.time() + 3600, "product": "Worksheets"}), "hub", by="test")
    return h, fake


def etsy_resale():
    """Jack, Oct 28: "etsy will only be custom/designed stuff like prints and other custom/engraved/generated items"."""
    h, fake = etsy_hub()
    h.add_product("Garlic press", brief="AliExpress supplier, cost $1.80 shipped, sell $7.99")
    h.add_product("Pet portrait print", brief="Printify poster, our generated art, cost $6, sell $19")
    pic = lambda ref: ("a.png", b"PNG")
    base = {"title": "Garlic Press Stainless", "description": "Presses garlic.", "price": 7.99, "category": "magnets",
            "images": ["x"]}
    try:
        etsy.post(h, "Ada", dict(base, product="Garlic press"), pic)
        accepted = True
    except ValueError as e:
        accepted = False
        assert "eBay" in str(e), f"the refusal points the agent to eBay: {e}"
    assert not accepted, "etsy accepted a resale listing"
    assert not [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/listings")], "a refused listing reaches Etsy"
    try:
        etsy.post(h, "Ada", dict(base, product="Pet portrait print", title="Custom Pet Portrait Poster",
                                 description="Sourced from AliExpress"), pic)
        accepted = True
    except ValueError:
        accepted = False
    assert not accepted, "etsy accepted a resale listing"
    r = etsy.post(h, "Ada", dict(base, product="Pet portrait print", title="Custom Pet Portrait Poster",
                                 description="Your pet, drawn by us, printed by Printify."), pic)
    assert r["live"].endswith("/9001"), r
    print("etsy_resale OK")


def scout():
    """An idle agent sent to find a product is told resale goes to eBay and only designed items go to Etsy."""
    from test_autonomy import new_hub
    h, muse, clock = new_hub("Cee", "Ada")
    h.seat("ceo", "Cee")
    h.add_product("Cups", brief="cups", pm="Cee")
    h.tick()
    clock.go(hub.SCOUT_AFTER + 1); h.tick(); h.tick()
    ask = next((m for m in muse.sent.get("Ada", []) if hub.Hub.SCOUT in m), "")
    assert ask, "no scout ask was sent"
    assert "eBay" in ask and "Etsy only" in ask and "AliExpress or similar dropship suppliers are fine" not in ask, \
        "scout still sends resale to Etsy"
    print("scout OK")


def _needs(mod):
    def case():
        __import__(mod)
        raise AssertionError(f"{mod} exists but this case is not written yet")
    return case


CASES = {"etsy_resale": etsy_resale, "scout": scout,
         **{c: _needs("ebay") for c in ("ebay_post", "ebay_price", "requote", "ebay_sales")},
         **{c: _needs("orders") for c in ("order_auto", "order_refused", "order_cap", "order_once", "tracking")},
         **{c: _needs("amazon") for c in ("amazon_sales", "fba_proposal")}}

if __name__ == "__main__":
    for name in sys.argv[1:]:
        CASES[name]()
