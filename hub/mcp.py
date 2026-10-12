"""The hub as an MCP connector, so a ChatGPT agent (dot) works in the hub without holding a key itself.

ChatGPT registers itself (dynamic client registration), sends Jack or Darragh to /oauth/authorize, where they
pick the agent and press Approve on their board login; ChatGPT trades the code (PKCE S256) for that agent's
token and keeps it. Every tool call then acts as that agent, exactly like the fleet CLI. Reconnecting replaces
the token. Streamable HTTP, JSON responses only (no server-initiated stream).
"""
import base64
import hashlib
import html
import json
import secrets
import time
from urllib.parse import urlencode, urlparse

PROTOCOL = "2025-06-18"
REDIRECT_HOSTS = ("chatgpt.com", "chat.openai.com", "openai.com")   # where an approval code may be sent


def redirect_ok(uri):
    p = urlparse(uri or "")
    return p.scheme == "https" and any(p.hostname == h or (p.hostname or "").endswith("." + h) for h in REDIRECT_HOSTS)


def resource_meta(base):
    return {"resource": base + "/mcp", "authorization_servers": [base], "bearer_methods_supported": ["header"]}


def server_meta(base):
    return {"issuer": base, "authorization_endpoint": base + "/oauth/authorize", "token_endpoint": base + "/oauth/token",
            "registration_endpoint": base + "/oauth/register", "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"], "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"]}


def register(body):
    # ponytail: client ids aren't stored; the gates are the redirect allowlist, a board member's Approve, and PKCE
    uris = body.get("redirect_uris") or []
    if not uris or not all(redirect_ok(u) for u in uris):
        raise ValueError("redirect_uris must be ChatGPT callback URLs")
    return {"client_id": "fleet-" + secrets.token_urlsafe(12), "redirect_uris": uris, "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code"], "response_types": ["code"], "client_name": body.get("client_name", "")}


def _pending(h):
    return h.__dict__.setdefault("mcp_pending", {})


def authorize_page(h, q, who):
    """The Approve page. The form carries only a one-time nonce, so another site can't forge an approval."""
    if q.get("response_type") != "code" or q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
        raise ValueError("this sign-in needs response_type=code and a PKCE S256 code_challenge")
    if not redirect_ok(q.get("redirect_uri")):
        raise ValueError("that redirect address isn't ChatGPT's")
    with h.lock:
        agents = [r["name"] for r in h.db.execute(
            "select name from agents where kind in ('slack','poll') and state != 'parked' order by name='dot' desc, name")]
    if not agents:
        raise ValueError("no agent can connect this way")
    nonce = secrets.token_urlsafe(16)
    _pending(h)[nonce] = (dict(q), time.time())
    opts = "".join(f"<option>{html.escape(a)}</option>" for a in agents)
    e = html.escape
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>Connect to the hub</title>"
            f"<body style='font:16px system-ui;max-width:560px;margin:40px auto;padding:0 16px;background:#0d1117;color:#e6edf3'>"
            f"<h2>Connect ChatGPT to the Foundlings hub?</h2>"
            f"<p>Signed in as <b>{e(who)}</b>. ChatGPT will act in the hub as the agent you pick: message agents, read and "
            f"answer that agent's inbox, see its status and tasks, and run the company commands its seat allows. "
            f"It gets no dashboard login. Connecting again replaces this access.</p>"
            f"<form method=post action='/oauth/authorize'><input type=hidden name=nonce value='{e(nonce)}'>"
            f"<p><label>Agent <select name=agent>{opts}</select></label></p>"
            f"<button name=decision value=approve style='font:inherit;padding:8px 18px'>Approve</button> "
            f"<button name=decision value=deny style='font:inherit;padding:8px 18px'>Deny</button></form>")


def approve(h, form, who):
    """-> the URL to send the browser back to ChatGPT with."""
    got = _pending(h).pop(form.get("nonce", ""), None)
    if not got or time.time() - got[1] > 600:
        raise ValueError("this approval expired; start the connection again from ChatGPT")
    q = got[0]
    back = {"state": q["state"]} if "state" in q else {}
    if form.get("decision") != "approve":
        return q["redirect_uri"] + ("&" if "?" in q["redirect_uri"] else "?") + urlencode(dict(back, error="access_denied"))
    agent = form.get("agent", "")
    with h.lock:
        ok = h.db.execute("select 1 from agents where name=? and kind in ('slack','poll') and state != 'parked'", (agent,)).fetchone()
    if not ok:
        raise ValueError(f"{agent!r} can't connect this way")
    code = secrets.token_urlsafe(24)
    h.__dict__.setdefault("mcp_codes", {})[code] = (q["code_challenge"], q["redirect_uri"], agent, time.time(), who)
    return q["redirect_uri"] + ("&" if "?" in q["redirect_uri"] else "?") + urlencode(dict(back, code=code))


def token(h, form):
    if form.get("grant_type") != "authorization_code":
        raise ValueError("unsupported_grant_type")
    got = h.__dict__.get("mcp_codes", {}).pop(form.get("code", ""), None)     # one use, even if it fails below
    if not got or time.time() - got[3] > 600:
        raise ValueError("invalid_grant")
    challenge, redirect, agent, _, approver = got
    verifier = form.get("code_verifier", "")
    calc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    if calc != challenge or (form.get("redirect_uri") and form["redirect_uri"] != redirect):
        raise ValueError("invalid_grant")
    kind = h._agent(agent)["kind"]
    tok = h.add_agent(agent, kind)
    with h.lock:                                   # shows on the dashboard's changes list
        h.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)",
                     (approver, "connect " + agent, "connected through the ChatGPT connector", h.clock()))
    return {"access_token": tok, "token_type": "Bearer"}


TOOLS = [
    {"name": "ask", "description": "Message another agent in the fleet (or 'all' for one combined answer). Their reply arrives in your inbox.",
     "inputSchema": {"type": "object", "properties": {"to": {"type": "string", "description": "agent name, or all"},
                                                      "text": {"type": "string"}}, "required": ["to", "text"]}},
    {"name": "inbox", "description": "Your oldest waiting message from the hub (requests and replies to your asks).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "reply", "description": "Answer an item from your inbox by its number.",
     "inputSchema": {"type": "object", "properties": {"item": {"type": "integer"}, "text": {"type": "string"}},
                     "required": ["item", "text"]}},
    {"name": "status", "description": "Your product, role, powers, open tasks, and what's waiting for you.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "fleet", "description": "Run a company command as on the fleet CLI, e.g. 'portfolio', 'changes', "
                                     "'task add <project id> \"<title>\" <role> \"<done when>\"', 'task set <id> owner <agent>'. "
                                     "Send 'help' for the full list.",
     "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
]


def _call(h, agent, name, a):
    if name == "ask":
        if a["to"] == "all":
            return f"Asked the fleet (council #{h.ask_all(agent, a['text'])}). One answer will come back to your inbox."
        return f"Sent as #{h.ask(agent, a['to'], a['text'])}. {a['to']}'s reply will come back to your inbox."
    if name == "inbox":
        it = h.inbox(agent)
        return f"#{it['id']} from {it['from']}:\n{it['text']}" if it else "Nothing waiting."
    if name == "reply":
        h.reply(agent, int(a["item"]), a["text"])
        return f"Replied to #{a['item']}."
    if name == "status":
        return json.dumps(h.status(agent), indent=1)
    if name == "fleet":
        line = a["command"].strip()
        line = line[6:] if line.startswith("fleet ") else line
        if line in ("", "help"):
            return h.MANAGE_HELP
        return h.manage(agent, line)
    raise KeyError(f"unknown tool {name}")


def rpc(h, agent, msg):
    """One JSON-RPC message -> its response, or None for a notification."""
    mid, method, p = msg.get("id"), msg.get("method", ""), msg.get("params") or {}
    if mid is None:
        return None
    if method == "initialize":
        res = {"protocolVersion": p.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {}},
               "serverInfo": {"name": "foundlings-hub", "version": "1"}}
    elif method == "ping":
        res = {}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        try:
            res = {"content": [{"type": "text", "text": str(_call(h, agent, p.get("name"), p.get("arguments") or {}))}]}
        except (ValueError, KeyError, PermissionError) as e:
            res = {"content": [{"type": "text", "text": str(e)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": res}
