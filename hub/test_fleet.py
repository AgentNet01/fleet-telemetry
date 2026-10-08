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
    pid = h.add_product("Templates", brief="Etsy budgeting templates", metric="first sale")
    prj = h.add_project(pid, "launch")
    t1 = h.add_task(prj, "build sheet", role="developer", done_def="xlsx")
    h.add_task(prj, "cover image", role="designer", done_def="png", blocked_by=[t1])
    h.place("Boboe 3", pid, "developer")
    h.secret_put("etsy-key", "SECRET", "product:Templates", by="jack")
    h.secret_get("etsy-key", "Boboe 3")
    h.pull_revenue(lambda: [{"source": "etsy", "external_id": "r1", "amount": 1.99, "currency": "usd", "product": "Templates", "at": 1}])
    cid = h.ask_all("Boboe 3", "ship it?")

    assert get(port, "/")[0] == 401, "dashboard needs the password"
    assert get(port, "/", "nope")[0] == 401
    code, page = get(port, "/", PASSWORD)
    assert code == 200 and "Needs Jack" in page, "page loads with a Needs Jack section"
    for section in ("Revenue", "Portfolio", "Vault", "Council"):
        assert section in page, f"dashboard is missing the {section} section"
    board = json.loads(get(port, "/api/board", PASSWORD)[1])
    assert round(board["revenue"]["total"], 2) == 1.99, board["revenue"]
    assert any(p["name"] == "Templates" for p in board["products"]), board.get("products")
    a3 = {a["name"]: a for a in board["agents"]}["Boboe 3"]
    assert a3["product"] == "Templates" and a3["role"] == "developer", a3
    tl = get(port, "/api/timeline?agent=Boboe%203", PASSWORD)[1]
    assert "hello dot" in tl
    reads = json.loads(get(port, "/api/vault", PASSWORD)[1])
    assert any(r["secret"] == "etsy-key" and r["agent"] == "Boboe 3" for r in reads["reads"]), reads
    assert "SECRET" not in get(port, "/api/vault", PASSWORD)[1], "the vault view never shows values"
    board2 = json.loads(get(port, "/api/board", PASSWORD)[1])
    tasks = [t for pr in board2.get("products", []) for prj in pr.get("projects", []) for t in prj.get("tasks", [])]
    assert any(t["title"] == "cover image" and t.get("blocked_by") for t in tasks), "a task shows its blocker"
    coun = json.loads(get(port, "/api/council?id=%d" % cid, PASSWORD)[1])
    assert coun["question"] == "ship it?", coun
    srv.shutdown()
    print("dashboard OK")


def company():
    h, srv, port, tok = start()
    home = tempfile.mkdtemp()
    h.add_product("Templates", brief="b")
    h.place("Boboe 3", "Templates", "developer")
    h.place("dot", "Templates", "pm")
    h.seat("ceo", "dot")
    h.secret_put("shared", "SHARED-VAL", "fleet", by="jack")

    r = fleet(port, tok["Boboe 3"], "ask", "all", "ready to ship?", home=home)
    assert r.returncode == 0, r
    assert any(c["question"] == "ready to ship?" for c in h.councils()), h.councils()

    r = fleet(port, tok["Boboe 3"], "secret", "get", "shared", home=home)
    assert r.returncode == 0 and "SHARED-VAL" in r.stdout, r
    r = subprocess.run([sys.executable, os.path.join(HERE, "fleet.py"), "secret", "put", "mine", "--scope", "agent"],
                       env=dict(os.environ, FLEET_HUB=f"http://127.0.0.1:{port}", FLEET_TOKEN=tok["Boboe 3"], FLEET_HOME=home),
                       input="MY-VALUE\n", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r
    r = fleet(port, tok["Boboe 3"], "secret", "get", "mine", home=home)
    assert r.returncode == 0 and "MY-VALUE" in r.stdout, r

    r = fleet(port, tok["Boboe 3"], "status", home=home)
    assert "Templates" in r.stdout and "developer" in r.stdout, f"status shows product and role: {r.stdout}"
    srv.shutdown()
    print("company OK")


if __name__ == "__main__":
    {"dashboard": dashboard, "company": company}.get(sys.argv[1] if len(sys.argv) > 1 else "", poll_agent_flow)()
