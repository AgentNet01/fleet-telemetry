"""Linking an Etsy shop: dashboard → Etsy sign-in → hub keeps the token and pulls paid orders hourly.

    python3 test_etsy.py        # against a fake Etsy; no network
"""
import base64
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import etsy
import hub
from test_hub import Clock, FakeMuse

PASSWORD = "pw"


class FakeEtsy:
    def __init__(self):
        self.challenge = None
        self.calls = []
        self.state, self.images = "active", [501, 502]
        self.live = []                                  # the shop's other active listings
        self.receipts = [
            {"receipt_id": 11, "is_paid": True, "grandtotal": {"amount": 450, "divisor": 100, "currency_code": "USD"}, "created_timestamp": 1000},
            {"receipt_id": 12, "is_paid": False, "grandtotal": {"amount": 999, "divisor": 100, "currency_code": "USD"}, "created_timestamp": 1001},
        ]

    def __call__(self, method, url, headers=None, data=None, files=None):
        self.calls.append((method, url, headers or {}, data, files))
        if url == etsy.TOKEN_URL and data["grant_type"] == "authorization_code":
            ok = base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest()).rstrip(b"=").decode() == self.challenge
            return (200, {"access_token": "777.tokA", "refresh_token": "ref1", "expires_in": 3600}) if ok and data["code"] == "c0de" \
                else (400, {"error": "invalid_grant"})
        if url == etsy.TOKEN_URL and data["grant_type"] == "refresh_token":
            return 200, {"access_token": "777.tokB", "refresh_token": "ref2", "expires_in": 3600}
        assert headers["x-api-key"] == "KEY:SECRET", headers
        if url.endswith("/users/777/shops"):
            return 200, {"shop_id": 42, "shop_name": "FoundlingsPrints"}
        if "/shops/42/receipts" in url:
            return 200, {"results": self.receipts if "offset=0" in url else []}
        if url.endswith("/seller-taxonomy/nodes"):
            return 200, {"results": [{"id": 1, "name": "Home & Living", "children": [
                {"id": 2, "name": "Magnets & Frames", "children": [{"id": 3, "name": "Magnets"}]}]}]}
        if url.endswith("/shops/42/shipping-profiles"):
            return 200, {"results": [{"shipping_profile_id": 555}]}
        if url.endswith("/shops/42/readiness-state-definitions"):
            return 200, {"results": [{"readiness_state_id": 66}]}
        if method == "GET" and "/shops/42/listings?state=active" in url:
            return 200, {"results": self.live if "offset=0" in url else []}
        if method == "POST" and url.endswith("/shops/42/listings"):
            return 201, {"listing_id": 9001, "state": "draft"}
        if method == "POST" and url.endswith("/listings/9001/images"):
            self.images.append(len(self.calls))
            return 201, {"listing_image_id": len(self.calls)}
        if method == "POST" and url.endswith("/listings/9001/files"):
            return 201, {"listing_file_id": 1}
        if method == "PATCH" and url.endswith("/shops/42/listings/9001"):
            self.state = data.get("state", self.state)
            return 200, {"listing_id": 9001, "state": self.state}
        if method == "GET" and url.endswith("/listings/9001"):
            return 200, {"listing_id": 9001, "state": self.state}
        if method == "GET" and url.endswith("/listings/9001/images"):
            return 200, {"results": [{"listing_image_id": i} for i in self.images]}
        if method == "DELETE" and "/listings/9001/images/" in url:
            self.images.remove(int(url.rsplit("/", 1)[1]))
            return 204, {}
        return 404, {}


def main():
    fake = FakeEtsy()
    etsy.http = fake
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.add_product("Worksheets", brief="b")
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

    assert req("/etsy/connect?product=Worksheets", headers={})[0] == 401, "linking needs the dashboard login"
    st, _, body = req("/etsy/connect?product=Worksheets")
    assert st == 400 and "keystring" in body, (st, body)
    assert req("/api/jack/etsy/app", {"key": "KEY", "secret": "SECRET"})[0] == 200

    st, hd, _ = req("/etsy/connect?product=Worksheets")
    assert st == 302 and hd["Location"].startswith(etsy.AUTH_URL), (st, dict(hd))
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(hd["Location"]).query))
    assert q["client_id"] == "KEY" and q["code_challenge_method"] == "S256" and "transactions_r" in q["scope"], q
    assert q["redirect_uri"] == base + "/etsy/callback", q
    fake.challenge = q["code_challenge"]

    assert req(f"/etsy/callback?state=forged&code=c0de")[0] == 400, "a callback that didn't start here is refused"
    st, _, body = req(f"/etsy/callback?state={q['state']}&code=c0de")
    assert st == 200 and "FoundlingsPrints" in body, (st, body)
    assert req(f"/etsy/callback?state={q['state']}&code=c0de")[0] == 400, "a link can only be finished once"

    board = json.loads(req("/api/board")[2])
    assert board["etsy"]["shops"][0]["shop_name"] == "FoundlingsPrints" and board["etsy"]["shops"][0]["product"] == "Worksheets"
    assert "tokA" not in json.dumps(board) and "ref1" not in json.dumps(board), "tokens never reach the dashboard"
    try:
        h.secret_get("etsy-shop:42", "dot")
        raise AssertionError("agents can't read the Etsy link")
    except PermissionError:
        pass

    h.pull_revenue(lambda: hub._revenue_fetch(h, {}))
    h.pull_revenue(lambda: hub._revenue_fetch(h, {}))
    rev = h.revenue()
    assert round(rev["total"], 2) == 4.50 and round(rev["by_product"]["Worksheets"], 2) == 4.50, rev

    rec = json.loads(h.db.execute("select value from secrets where name='etsy-shop:42'").fetchone()["value"])
    rec["expires"] = time.time() - 1
    h.secret_put("etsy-shop:42", json.dumps(rec), "hub", by="test")
    fake.receipts.append({"receipt_id": 13, "is_paid": True, "grandtotal": {"amount": 300, "divisor": 100, "currency_code": "USD"}, "created_timestamp": 2000})
    h.pull_revenue(lambda: hub._revenue_fetch(h, {}))
    assert round(h.revenue()["total"], 2) == 7.50, h.revenue()
    rec = json.loads(h.db.execute("select value from secrets where name='etsy-shop:42'").fetchone()["value"])
    assert rec["access"] == "777.tokB" and rec["refresh"] == "ref2" and rec["error"] is None, "an expired link renews itself"

    # Jack, Oct 15: "They can post whatever things on Etsy they want. The only thing they can't do is spend money."
    assert "listings_w" in q["scope"], "the link lets the hub write listings"
    h.jobs_dir = tempfile.mkdtemp()
    hero = h.jack_file("hero.png", b"PNGHERO").split()[3:]
    tok = h.add_agent("Ada", "poll")
    agent = {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}
    listing = {"title": "Custom Pet Photo Magnet", "description": "Your pet on a magnet.", "price": 14.99,
               "tags": ["pet magnet", "photo magnet"], "category": "magnets", "product": "Worksheets",
               "images": ["job:" + "/".join(hero)]}
    st, _, body = req("/api/etsy/draft", dict(listing, images=["http://127.0.0.1:8770/api/vault"]), agent)
    assert st == 400 and "muse.ai/files" in body, f"etsy: the hub fetches only Muse files and its own job files: {st} {body}"
    assert not [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/listings")], "etsy: a bad picture makes no draft"
    st, _, body = req("/api/etsy/post", listing, agent)
    assert st == 200 and json.loads(body)["live"] == "https://www.etsy.com/listing/9001", (st, body)
    made = [c for c in fake.calls if c[0] == "POST" and c[1].endswith("/shops/42/listings")][0][3]
    assert (made["taxonomy_id"], made["type"], made["shipping_profile_id"], made["readiness_state_id"]) == (3, "physical", 555, 66), \
        f"etsy: the closest category, and the shop's own shipping and processing: {made}"
    assert made["tags"] == "pet magnet,photo magnet" and made["price"] == 14.99, made
    pics = [c[4]["image"] for c in fake.calls if c[1].endswith("/listings/9001/images")]
    assert pics == [("hero.png", b"PNGHERO")], f"etsy: the pictures go up: {pics}"
    live = [c for c in fake.calls if c[0] == "PATCH"]
    assert live and live[-1][3] == {"state": "active"}, f"etsy: the listing is put live, after its pictures: {live}"
    assert not h.needs_jack(), f"etsy: posting never lands on Jack's list: {h.needs_jack()}"
    assert [p["link"] for p in h.portfolio() if p["name"] == "Worksheets"] == ["https://www.etsy.com/listing/9001"], \
        "etsy: the product shows its live listing"
    book = h.jack_file("book.pdf", b"%PDF").split()[3:]
    st, _, body = req("/api/etsy/post", dict(listing, kind="download", files=["job:" + "/".join(book)]), agent)
    files = [c[4]["file"] for c in fake.calls if c[1].endswith("/listings/9001/files")]
    assert st == 200 and files == [("book.pdf", b"%PDF")], f"etsy: a download's file goes up before it goes live: {st} {body} {files}"
    st, _, body = req("/api/etsy/post", dict(listing, kind="download"), agent)
    assert st == 400 and "file" in body, f"etsy: a download with nothing to download is refused: {st} {body}"
    # Oct 20: three agents posted silicone stretch lids within an hour
    fake.live = [{"listing_id": 77, "title": "Custom Pet Photo Magnets Set of 2, Fridge Gift"}]
    before = len([c for c in fake.calls if c[0] == "POST" and c[1].endswith("/shops/42/listings")])
    st, _, body = req("/api/etsy/post", listing, agent)
    assert st == 400 and "77" in body and "already sells" in body, f"etsy: a second listing of the same item is refused: {st} {body}"
    assert len([c for c in fake.calls if c[0] == "POST" and c[1].endswith("/shops/42/listings")]) == before, "etsy: and no draft is made"
    st, _, body = req("/api/etsy/post", dict(listing, title="Wooden Pinecone Gift Tags 50 Pack"), agent)
    assert st == 200, f"etsy: a different item still posts: {st} {body}"
    fake.live = []

    # Jack, Oct 15: a listing was taken down and agents spent whole tasks finding out by hand; the PM never heard
    h.add_agent("Pam", "poll")
    h.db.execute("update products set pm='Pam' where name='Worksheets'")
    fake.state = "inactive"
    etsy.sync_listings(h)
    told = [r["text"] for r in h.db.execute("select text from items where too='Pam' and kind='note'")]
    assert len(told) == 1 and "INACTIVE" in told[0], f"etsy: the PM is told the listing went down: {told}"
    assert h.portfolio()[0]["listing_state"] == "inactive", "etsy: the product records it"
    etsy.sync_listings(h)
    assert h.db.execute("select count(*) from items where too='Pam' and kind='note'").fetchone()[0] == 1, "etsy: told once per change"
    proj = h.add_project(h.portfolio()[0]["id"], "Launch")
    tid = h.add_task(proj, "Redo the photos", "maker", "photos")
    assert "INACTIVE (buyers can't see it)" in h._listing_line(tid), f"etsy: every task on it says so: {h._listing_line(tid)}"

    # anyone working on the product fixes it through the API: no browser sign-in, no queue on one agent
    new_pic = h.jack_file("new.png", b"PNGNEW").split()[3:]
    change = {"listing_id": 9001, "images": ["job:" + "/".join(new_pic)], "state": "active"}
    st, _, body = req("/api/etsy/update", change, agent)
    assert st == 400 and "only its PM" in body, f"etsy: someone with no work on the product can't change its listing: {st} {body}"
    with h.lock:
        h.db.execute("update tasks set owner='Ada', status='working' where id=?", (tid,))
    # Oct 15: Boboe 11 sent {"dry_run": true, "description": ...}; the hub passed dry_run to Etsy and changed it for real
    before = len(fake.calls)
    st, _, body = req("/api/etsy/update", dict(change, dry_run=True), agent)
    assert st == 200 and json.loads(body)["dry_run"] and "state" in json.loads(body)["changed"], (st, body)
    assert not [c for c in fake.calls[before:] if c[0] in ("POST", "PATCH", "DELETE")], "etsy: a dry run changes nothing on Etsy"
    assert fake.state == "inactive", fake.state
    st, _, body = req("/api/etsy/update", change, agent)
    assert st == 200, (st, body)
    assert fake.state == "active" and fake.images == [fake.images[-1]] and 501 not in fake.images, \
        f"etsy: the new picture replaces the old ones and the listing is back on: {fake.state} {fake.images}"
    assert h.portfolio()[0]["listing_state"] == "active" and "LIVE" in h._listing_line(tid), "etsy: the hub knows at once"
    srv.shutdown()

    h2 = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    try:
        etsy.post(h2, "Ada", listing, h2.listing_picture)
        raise AssertionError("etsy: no shop linked, no listing")
    except ValueError as e:
        assert "Connect Etsy" in str(e), e
    print("etsy OK")


if __name__ == "__main__":
    main()
