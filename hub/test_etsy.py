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
        self.receipts = [
            {"receipt_id": 11, "is_paid": True, "grandtotal": {"amount": 450, "divisor": 100, "currency_code": "USD"}, "created_timestamp": 1000},
            {"receipt_id": 12, "is_paid": False, "grandtotal": {"amount": 999, "divisor": 100, "currency_code": "USD"}, "created_timestamp": 1001},
        ]

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url, headers or {}, data))
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
    srv.shutdown()
    print("etsy OK")


if __name__ == "__main__":
    main()
