"""The `fleet` command and the dashboard, against a real hub server on a temp port.

    python3 test_fleet.py             # inbox/reply, bad token, outbox while the hub is down
    python3 test_fleet.py dashboard   # password, page sections, board JSON, org/seat/suggestion endpoints
    python3 test_fleet.py cli         # fleet task note|done|verify|release, fleet suggest / suggestion
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


JOIN = "join-only-code"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def start(port=None, db=None):
    """A hub server; a fresh database gets two agents, an existing one is reopened as is."""
    h = hub.Hub(db or os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    tokens = {} if db else {n: h.add_agent(n, k) for n, k in (("Boboe 3", "muse"), ("dot", "poll"))}
    port = port or free_port()
    srv = hub.serve(h, "127.0.0.1", port, PASSWORD, join_code=JOIN, logins={"darragh": "d-pass"})
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


def post(port, path, body, password=PASSWORD):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    if password:
        req.add_header("Authorization", "Basic " + base64.b64encode(f"jack:{password}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


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
    assert code == 200 and "Needs you" in page, "page loads with a Needs you section"
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

    # running the company: seats, PMs, roles, suggestions, releasing a task
    for section in ("Org", "Suggestions"):
        assert section in page, f"dashboard is missing the {section} section"
    assert post(port, "/api/jack/seat", {"role": "ceo", "who": "jack"})[0] == 200
    assert post(port, "/api/jack/pm", {"product": "Templates", "who": "Boboe 3"})[0] == 200
    assert post(port, "/api/jack/role", {"name": "engineer", "soul": "You build."})[0] == 200
    org = json.loads(get(port, "/api/org", PASSWORD)[1])
    assert org["ceo"] == "jack" and org["pms"]["Templates"] == "Boboe 3" and org["roles"]["engineer"] == "You build.", org
    assert get(port, "/api/org")[0] == 401, "org needs the password"
    h.place("Boboe 3", "Templates", "optimizer")
    sid = h.suggest("Boboe 3", "bundle the templates")
    sugs = json.loads(get(port, "/api/suggestions", PASSWORD)[1])["suggestions"]
    assert sugs and sugs[0]["text"] == "bundle the templates", sugs
    assert post(port, "/api/jack/suggestion", {"id": sid, "accept": False, "note": "not yet"})[0] == 200
    assert h.suggestions()[0]["status"] == "rejected", h.suggestions()
    h.place("Boboe 3", "Templates", "engineer")
    t3 = h.add_task(prj, "price it", role="engineer", done_def="a price")
    h.tick()
    a3 = {a["name"]: a for a in json.loads(get(port, "/api/board", PASSWORD)[1])["agents"]}["Boboe 3"]
    assert a3["task"] and a3["task"]["title"] in ("build sheet", "price it"), f"agent card shows the held task: {a3}"
    assert "free_since" in a3, a3
    held = a3["task"]["id"]
    assert post(port, "/api/jack/release", {"task": held})[0] == 200
    assert h.task(held)["owner"] is None, h.task(held)
    srv.shutdown()
    print("dashboard OK")


def cli():
    h, srv, port, tok = start()
    h.evidence_ok = lambda link: True
    home = tempfile.mkdtemp()
    pid = h.add_product("Shop", brief="b"); prj = h.add_project(pid, "launch")
    h.place("Boboe 3", "Shop", "engineer"); h.place("dot", "Shop", "engineer")
    t = h.add_task(prj, "write the listing", role="engineer", done_def="x")
    h.tick()
    owner = h.task(t)["owner"]
    other = "dot" if owner == "Boboe 3" else "Boboe 3"
    r = fleet(port, tok[owner], "status", home=home)
    assert r.returncode == 0 and f"#{t}" in r.stdout and "write the listing" in r.stdout, f"status shows my task: {r}"
    r = fleet(port, tok[owner], "task", "wait", str(t), "jack", "the publish OK", home=home)
    assert r.returncode == 0 and "parked" in r.stdout, f"task wait: {r}"
    assert h.task(t)["waiting_on"] == "jack" and any("publish OK" in n["text"] for n in h.needs_jack()), h.task(t)
    r = fleet(port, tok[owner], "task", "resume", str(t), home=home)
    assert r.returncode == 0 and h.task(t)["waiting_on"] is None, f"task resume: {r}"
    h.tick(); h.tick()
    assert h.task(t)["owner"] == owner, f"back to its holder: {h.task(t)}"
    r = fleet(port, tok[owner], "task", "note", str(t), "draft done", home=home)
    assert r.returncode == 0 and h.task(t)["progress_note"] == "draft done", (r, h.task(t))
    r = fleet(port, tok[other], "task", "done", str(t), "https://example.com/e", home=home)
    assert r.returncode != 0 and "403" in r.stderr, f"only the holder can finish it: {r}"
    r = fleet(port, tok[owner], "task", "done", str(t), "https://example.com/e", home=home)
    assert r.returncode == 0 and h.task(t)["status"] == "verifying", (r, h.task(t))
    h.tick()
    r = fleet(port, tok[other], "task", "verify", str(t), "fail", "totals off", home=home)
    assert r.returncode == 0 and h.task(t)["status"] == "working", (r, h.task(t))
    fleet(port, tok[owner], "task", "done", str(t), "https://example.com/e2", home=home)
    h.tick()
    r = fleet(port, tok[other], "task", "verify", str(t), "pass", home=home)
    assert r.returncode == 0 and h.task(t)["status"] == "done", (r, h.task(t))

    t2 = h.add_task(prj, "another", role="engineer", done_def="x")
    h.tick()
    r = fleet(port, tok[h.task(t2)["owner"]], "task", "release", str(t2), home=home)
    assert r.returncode != 0 and "403" in r.stderr, f"workers can't release: {r}"

    h.place("dot", "Shop", "optimizer")
    r = fleet(port, tok["dot"], "suggest", "bigger thumbnails", home=home)
    assert r.returncode == 0 and h.suggestions()[0]["text"] == "bigger thumbnails", (r, h.suggestions())
    sid = h.suggestions()[0]["id"]
    r = fleet(port, tok["Boboe 3"], "suggestion", "accept", str(sid), home=home)
    assert r.returncode != 0 and "403" in r.stderr, f"only the PM or CEO decides: {r}"
    h.set_pm("Shop", "Boboe 3")
    r = fleet(port, tok["Boboe 3"], "suggestion", "accept", str(sid), "next listing", home=home)
    assert r.returncode == 0 and h.suggestions()[0]["status"] == "accepted", (r, h.suggestions())
    srv.shutdown()
    print("cli OK")


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

    # the CEO runs the company from the command line; a plain agent is refused
    r = fleet(port, tok["dot"], "project", "add", "Templates", "launch", home=home)
    assert r.returncode == 0 and "project #" in r.stdout, r
    r = fleet(port, tok["dot"], "portfolio", home=home)
    assert "launch" in r.stdout and "Boboe 3" in r.stdout, r.stdout
    r = fleet(port, tok["Boboe 3"], "product", "add", "Mine", "x", home=home)
    assert r.returncode != 0 and "403" in r.stderr, r
    srv.shutdown()
    print("company OK")


def join():
    """Another team's agent joins with its own code: a new name only, no takeover, no dashboard."""
    h, srv, port, tok = start()
    h.add_agent("darragh", "jack")
    home = tempfile.mkdtemp()
    hub_url = f"http://127.0.0.1:{port}"
    env = dict(os.environ, FLEET_HOME=home)
    env.pop("FLEET_HUB", None); env.pop("FLEET_TOKEN", None)
    run = lambda *a: subprocess.run([sys.executable, os.path.join(HERE, "fleet.py"), *a], env=env,
                                    capture_output=True, text=True, timeout=30)

    r = run("join", "Dara Scout", JOIN, hub_url)
    assert r.returncode == 0 and "Dara Scout" in r.stdout, r
    assert h._agent("Dara Scout")["kind"] == "poll"
    r = run("status")
    assert r.returncode == 0 and "not placed" in r.stdout, r

    # the join code can't take over anyone, and isn't the dashboard password
    for name in ("Boboe 3", "dot", "darragh", "jack", "Dara Scout"):
        r = run("join", name, JOIN, hub_url)
        assert r.returncode != 0, f"join code took over {name}: {r.stdout}"
    assert h.agent_by_token(tok["Boboe 3"]) == "Boboe 3", "existing agent kept its token"
    import base64, urllib.request, urllib.error
    req = urllib.request.Request(hub_url + "/api/board", headers={
        "Authorization": "Basic " + base64.b64encode(f"jack:{JOIN}".encode()).decode()})
    try:
        urllib.request.urlopen(req); raise AssertionError("join code opened the dashboard")
    except urllib.error.HTTPError as e:
        assert e.code == 401, e.code

    # a team agent whose Muse login the hub holds gets its work pushed into its fleet chat, like a Boboe
    h.accounts = {"Dara Muse": "x"}
    hub.register_accounts(h, h.accounts)        # what the hub does at startup: an entry nobody holds a token for
    r = run("join", "Dara Muse", JOIN, hub_url)
    assert r.returncode == 0 and h._agent("Dara Muse")["kind"] == "muse", (r, dict(h._agent("Dara Muse") or {}))

    # a Slack-bridged agent (dot) joining directly keeps its bridge until Jack switches it off
    h.add_agent("Slacky", "slack")
    r = run("join", "Slacky", JOIN, hub_url)
    assert r.returncode == 0, r
    assert h._agent("Slacky")["kind"] == "slack", "joining keeps the Slack bridge"
    r = run("status")
    assert r.returncode == 0, r

    # Darragh has his own dashboard login; it doesn't work as a claim code, and the wrong user/password pair fails
    def board(user, pw):
        req = urllib.request.Request(hub_url + "/api/board", headers={
            "Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    assert board("darragh", "d-pass") == 200 and board("jack", "d-pass") == 401 and board("darragh", "nope") == 401
    assert run("join", "Sneaky", "d-pass", hub_url).returncode != 0, "a dashboard login isn't a join code"

    # a message sent from the dashboard is from whoever is logged in; Claude's scripted sends say so
    def send(user, pw, body):
        req = urllib.request.Request(hub_url + "/api/jack/send", data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()})
        return json.load(urllib.request.urlopen(req))["id"]
    assert h.item(send("darragh", "d-pass", {"to": "Boboe 3", "text": "hi from D"}))["frm"] == "darragh"
    assert h.item(send("jack", PASSWORD, {"to": "Boboe 3", "text": "hi from J"}))["frm"] == "jack"
    assert h.item(send("jack", PASSWORD, {"to": "Boboe 3", "text": "test", "as": "claude"}))["frm"] == "claude"

    # Jack's own code still re-claims a Boboe (VM replaced), but never a board member or dot
    r = run("join", "Boboe 3", PASSWORD, hub_url)
    assert r.returncode == 0, r
    for name in ("darragh", "jack", "dot"):
        assert run("join", name, PASSWORD, hub_url).returncode != 0, f"Jack's code re-claimed {name}"
    srv.shutdown()
    print("join OK")


def delegate():
    """brutus, 2026-10-12: an agent that acts on a request by asking someone else is working, not unresponsive.
    The answer reaches it while the request is still open, and only real silence marks an agent unresponsive."""
    h, srv, port, tok = start()
    muse, clock, home = h.transport, h.clock, tempfile.mkdtemp()
    h.add_agent("Pat", "muse")
    state = lambda n: h._agent(n)["state"]
    a = h.ask("dot", "Boboe 3", "build the pet-portrait style sheet")
    h.tick()
    clock.go(120)
    r = fleet(port, tok["Boboe 3"], "ask", "Pat", "which style should the samples use?", home=home)
    assert r.returncode == 0, r.stderr
    c = h.db.execute("select id from items where frm='Boboe 3'").fetchone()["id"]
    assert h.item(c)["parent"] == a
    h.tick()
    clock.go(1100); h.tick()                                   # 20+ min since #a, but Boboe 3 is waiting on Pat
    assert h.item(a)["status"] == "sent", f"a request waiting on a sub-question doesn't time out: {h.item(a)}"
    assert state("Boboe 3") == "active", "an agent that acted on its request is not unresponsive"
    muse.say("Pat", "use watercolour"); h.tick(); clock.go(61); h.tick(); h.tick()
    assert h.item(c)["status"] == "answered"
    assert "use watercolour" in muse.sent["Boboe 3"][-1], f"Pat's answer reaches Boboe 3 while #a is open: {muse.sent['Boboe 3'][-1]}"
    muse.say("Boboe 3", "style sheet: https://example.com/sheet.png"); h.tick(); clock.go(61); h.tick()
    assert h.item(a)["status"] == "answered", h.item(a)

    # acted, then went quiet: the request fails 20 min after its last sign of life, the agent is not called unresponsive
    b = h.ask("dot", "Boboe 3", "one more thing"); h.tick()
    clock.go(300)
    assert fleet(port, tok["Boboe 3"], "ask", "Pat", "quick check", home=home).returncode == 0
    clock.go(1000); h.tick()
    assert h.item(b)["status"] == "sent", "20 min counts from the agent's last action, not from delivery"
    muse.say("Pat", "ok"); h.tick(); clock.go(61); h.tick(); h.tick()
    clock.go(1201); h.tick()
    assert h.item(b)["status"] == "failed", h.item(b)
    assert state("Boboe 3") == "active", "it acted after #b arrived, so it isn't unresponsive"

    # real silence still counts, the machine heartbeat isn't the agent answering, and any action revives it
    h.ask("dot", "Boboe 3", "are you there?"); h.tick(); h.tick()
    clock.go(1201); h.tick()
    assert state("Boboe 3") == "unresponsive", state("Boboe 3")
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ingest", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok["Boboe 3"]})
    urllib.request.urlopen(req, timeout=10).read()
    assert state("Boboe 3") == "unresponsive", "telemetryd's heartbeat is the VM, not the agent"
    assert fleet(port, tok["Boboe 3"], "ask", "Pat", "back now", home=home).returncode == 0
    assert state("Boboe 3") == "active", "an agent acting on the hub is not unresponsive"
    # a sub-question nobody will ever pick up (a poll agent that never checks in) doesn't hold the request open forever
    e = h.ask("dot", "Boboe 3", "and the banner?"); h.tick(); h.tick()
    assert fleet(port, tok["Boboe 3"], "ask", "dot", "banner size?", home=home).returncode == 0
    clock.go(1201); h.tick()
    assert h.item(e)["status"] == "failed" and state("Boboe 3") == "active", (h.item(e), state("Boboe 3"))

    # a poll agent gets the answer to its own sub-question from `fleet inbox` while its request is still open
    h.reply("dot", h.inbox("dot")["id"], "2000x500")
    d = h.ask("Boboe 3", "dot", "draft the launch note"); assert h.inbox("dot")["id"] == d
    h.add_agent("Quin", "muse"); h.ask("dot", "Quin", "what tone?"); h.tick()
    muse.say("Quin", "warm, short"); h.tick(); clock.go(61); h.tick()
    got = h.inbox("dot")
    assert got["kind"] == "note" and "warm, short" in got["text"], got
    assert h.inbox("dot")["id"] == d, "then the open request again"
    print("delegate OK")


def stale():
    """Oct 13: Boboe 9's copied fleet.py had no `task done`, so its finished task never closed. The hub learns each
    agent's fleet version from its calls and tells one still on an old (version-less) copy how to upgrade, once a day."""
    h, srv, port, tok = start()
    h.db.execute("update agents set onboarded=1 where name='Boboe 3'")
    old = lambda: [i for i in h.db.execute("select text from items where too='Boboe 3' and text like '%old copy%'")]
    h.tick(); h.tick()
    assert len(old()) == 1, f"stale: an agent with no reported version is told to upgrade: {old()}"
    h.tick(); h.clock.go(3600); h.tick()
    assert len(old()) == 1, "stale: told once a day, not every tick"
    r = fleet(port, tok["Boboe 3"], "status", home=tempfile.mkdtemp())
    assert r.returncode == 0, r
    rev = h._agent("Boboe 3")["fleet_rev"]
    assert rev and len(rev) == 12, f"stale: the client reports its version: {rev}"
    h.clock.go(86400); h.tick()
    assert len(old()) == 1, "stale: an upgraded agent isn't told again"
    row = {x["name"]: x for x in h.board()["agents"]}["Boboe 3"]
    assert row["fleet_rev"] == hub.fleet_rev() and not row["fleet_old"], f"stale: same version as the hub → not old: {row}"
    h.db.execute("update agents set fleet_rev='0ld' where name='Boboe 3'")
    assert {x["name"]: x for x in h.board()["agents"]}["Boboe 3"]["fleet_old"], "stale: another version shows as old"
    assert h.board()["agents"][0].get("fleet_rev") is not None or any(a.get("fleet_rev") for a in h.board()["agents"])
    print("stale OK")


if __name__ == "__main__":
    {"dashboard": dashboard, "company": company, "cli": cli, "join": join, "delegate": delegate, "stale": stale}.get(sys.argv[1] if len(sys.argv) > 1 else "", poll_agent_flow)()
