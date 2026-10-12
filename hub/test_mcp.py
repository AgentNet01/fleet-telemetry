"""ChatGPT connector: register -> board member approves -> PKCE token -> MCP tools act as that agent.

    python3 test_mcp.py
"""
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import hub
from test_hub import Clock, FakeMuse

CB = "https://chatgpt.com/connector_platform_oauth_redirect"


def main():
    muse = FakeMuse()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), muse, Clock())
    h.add_agent("dot", "slack")
    h.add_agent("Per", "muse")
    srv = hub.serve(h, "127.0.0.1", 0, "pw", logins={"darragh": "dpw"})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    darragh = {"Authorization": "Basic " + base64.b64encode(b"darragh:dpw").decode()}
    no_redirect = urllib.request.build_opener(type("N", (urllib.request.HTTPRedirectHandler,), {"redirect_request": lambda *a: None}))

    def req(path, body=None, headers=None, form=False):
        hd = dict(headers or {})
        data = None
        if body is not None:
            data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
            hd["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        try:
            with no_redirect.open(urllib.request.Request(base + path, data=data, headers=hd)) as r:
                return r.status, r.headers, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read().decode()

    st, hd, _ = req("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert st == 401 and "resource_metadata=" in hd["WWW-Authenticate"], (st, dict(hd))
    meta = json.loads(req("/.well-known/oauth-protected-resource")[2])
    assert meta["authorization_servers"] == [base], meta
    asm = json.loads(req("/.well-known/oauth-authorization-server")[2])
    assert asm["code_challenge_methods_supported"] == ["S256"] and asm["registration_endpoint"].endswith("/oauth/register")

    assert req("/oauth/register", {"redirect_uris": ["https://evil.example/cb"]})[0] == 400, "only ChatGPT callbacks"
    st, _, body = req("/oauth/register", {"redirect_uris": [CB], "client_name": "ChatGPT"})
    assert st == 201, (st, body)
    cid = json.loads(body)["client_id"]

    verifier = "v" * 50
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = urllib.parse.urlencode({"response_type": "code", "client_id": cid, "redirect_uri": CB, "state": "s1",
                                "code_challenge": challenge, "code_challenge_method": "S256"})
    assert req("/oauth/authorize?" + q)[0] == 401, "the Approve page needs a board login"
    st, _, page = req("/oauth/authorize?" + q, headers=darragh)
    assert st == 200 and "Approve" in page and "<option>dot</option>" in page and "Per" not in page, page
    nonce = re.search(r"name=nonce value='([^']+)'", page).group(1)

    assert req("/oauth/authorize", {"nonce": "forged", "decision": "approve", "agent": "dot"}, darragh, form=True)[0] == 400
    st, hd, _ = req("/oauth/authorize", {"nonce": nonce, "decision": "approve", "agent": "dot"}, darragh, form=True)
    assert st == 302 and hd["Location"].startswith(CB + "?"), (st, dict(hd))
    back = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(hd["Location"]).query))
    assert back["state"] == "s1"

    tok_form = {"grant_type": "authorization_code", "code": back["code"], "redirect_uri": CB, "client_id": cid}
    assert req("/oauth/token", dict(tok_form, code_verifier="wrong" * 10), form=True)[0] == 400
    assert req("/oauth/token", dict(tok_form, code_verifier=verifier), form=True)[0] == 400, "a code works once, even after a bad try"

    st, hd, page = req("/oauth/authorize?" + q, headers=darragh)
    nonce = re.search(r"name=nonce value='([^']+)'", page).group(1)
    back = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(
        req("/oauth/authorize", {"nonce": nonce, "decision": "approve", "agent": "dot"}, darragh, form=True)[1]["Location"]).query))
    st, _, body = req("/oauth/token", dict(tok_form, code=back["code"], code_verifier=verifier), form=True)
    assert st == 200, (st, body)
    token = json.loads(body)["access_token"]
    assert h.agent_by_token(token) == "dot" and h._agent("dot")["kind"] == "slack", "dot keeps its Slack bridge"
    assert any("connect dot" in r["line"] for r in h.db.execute("select line from changes")), "the connection shows on the dashboard"

    auth = {"Authorization": "Bearer " + token}

    def rpc(method, params=None, i=[0]):
        i[0] += 1
        st, _, body = req("/mcp", {"jsonrpc": "2.0", "id": i[0], "method": method, "params": params or {}}, auth)
        assert st == 200, (st, body)
        return json.loads(body)["result"]

    assert rpc("initialize", {"protocolVersion": "2025-06-18"})["serverInfo"]["name"] == "foundlings-hub"
    assert req("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}, auth)[0] == 202
    assert {t["name"] for t in rpc("tools/list")["tools"]} == {"ask", "inbox", "reply", "status", "fleet"}
    out = rpc("tools/call", {"name": "ask", "arguments": {"to": "Per", "text": "can you publish today?"}})
    assert "Sent as #" in out["content"][0]["text"], out
    h.tick()
    assert any("can you publish today?" in m for m in muse.sent.get("Per", [])), "the ask reaches the agent"
    assert '"agent": "dot"' in rpc("tools/call", {"name": "status"})["content"][0]["text"]
    assert "portfolio" in rpc("tools/call", {"name": "fleet", "arguments": {"command": "help"}})["content"][0]["text"]
    bad = rpc("tools/call", {"name": "reply", "arguments": {"item": 99999, "text": "x"}})
    assert bad.get("isError"), bad
    srv.shutdown()
    print("mcp OK")


if __name__ == "__main__":
    main()
