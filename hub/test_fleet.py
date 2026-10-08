"""The `fleet` command and the dashboard, against a real hub server on a temp port.

    python3 test_fleet.py             # inbox/reply, bad token, outbox while the hub is down
    python3 test_fleet.py dashboard   # password, page sections, board JSON
"""
import base64
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

import hub
from test_hub import Clock, FakeMuse

HERE = os.path.dirname(os.path.abspath(__file__))
PASSWORD = "test-pass-123"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start(port=None, db=None):
    """A hub server; a fresh database gets two agents, an existing one is reopened as is."""
    h = hub.Hub(db or os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    tokens = {} if db else {n: h.add_agent(n, k) for n, k in (("Boboe 3", "muse"), ("dot", "poll"))}
    port = port or free_port()
    srv = hub.serve(h, "127.0.0.1", port, PASSWORD)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return h, srv, port, tokens


def fleet(port, token, *args, home):
    env = dict(os.environ, FLEET_HUB=f"http://127.0.0.1:{port}", FLEET_TOKEN=token, FLEET_HOME=home)
    return subprocess.run([sys.executable, os.path.join(HERE, "fleet.py"), *args],
                          env=env, capture_output=True, text=True, timeout=30)


def poll_agent_flow():
    h, srv, port, tok = start()
    home = tempfile.mkdtemp()
    first = h.ask("Boboe 3", "dot", "what's the plan?")
    h.ask("Boboe 3", "dot", "and after that?")

    r = fleet(port, tok["dot"], "inbox", home=home)
    assert r.returncode == 0 and f"#{first}" in r.stdout and "what's the plan?" in r.stdout, r
    r = fleet(port, tok["dot"], "reply", str(first), "ship the templates", home=home)
    assert r.returncode == 0, r
    assert h.item(first)["status"] == "answered" and h.item(first)["reply"] == "ship the templates"

    r = fleet(port, "wrong-token", "inbox", home=home)
    assert r.returncode != 0 and "401" in (r.stdout + r.stderr), f"bad token must be refused: {r}"

    # Boboe 3 asks dot through the CLI
    r = fleet(port, tok["Boboe 3"], "ask", "dot", "status?", home=home)
    assert r.returncode == 0, r
    assert h.items_for("dot")[-1]["text"] == "status?", h.items_for("dot")

    # hub down: the ask goes to the outbox, then is sent exactly once when it's back
    db = h.db_path
    srv.shutdown(); srv.server_close()
    r = fleet(port, tok["Boboe 3"], "ask", "dot", "while you were out", home=home)
    assert r.returncode == 0 and "outbox" in r.stdout.lower(), r
    h2, srv2, _, _ = start(port=port, db=db)       # same database: Boboe 3's token still works
    fleet(port, tok["Boboe 3"], "status", home=home)   # any call flushes the outbox
    fleet(port, tok["Boboe 3"], "status", home=home)   # a second call must not resend it
    sent = [i for i in h2.items_for("dot") if i["text"] == "while you were out"]
    assert len(sent) == 1, f"outbox must deliver exactly once, got {len(sent)}"
    assert not os.listdir(os.path.join(home, "outbox")), "outbox emptied"
    srv2.shutdown()
    print("fleet OK")


def get(port, path, password=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
    if password:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"jack:{password}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def dashboard():
    h, srv, port, tok = start()
    h.ask("Boboe 3", "dot", "hello dot")
    assert get(port, "/")[0] == 401, "dashboard needs the password"
    assert get(port, "/", "nope")[0] == 401
    code, page = get(port, "/", PASSWORD)
    assert code == 200 and "Needs Jack" in page, "page loads with a Needs Jack section"
    code, body = get(port, "/api/board", PASSWORD)
    board = json.loads(body)
    names = sorted(a["name"] for a in board["agents"])
    assert names == ["Boboe 3", "dot"], names
    assert {"state", "queue", "last_in", "last_out"} <= set(board["agents"][0]), board["agents"][0]
    code, body = get(port, "/api/timeline?agent=dot", PASSWORD)
    assert code == 200 and "hello dot" in body, body
    srv.shutdown()
    print("dashboard OK")


if __name__ == "__main__":
    {"dashboard": dashboard}.get(sys.argv[1] if len(sys.argv) > 1 else "", poll_agent_flow)()
