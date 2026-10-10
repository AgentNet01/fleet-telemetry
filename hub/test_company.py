"""Company layer: products, projects, tasks with dependencies, assignment, verify, council, org.

    python3 test_company.py          # tasks: blocked → ready → assign → done → verify → unblock
    python3 test_company.py council  # ask all → views → one labelled chair answer
"""
import os
import sys
import tempfile

import hub
from test_hub import Clock, FakeMuse


def new_hub(evidence_ok=lambda link: True):
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock(), evidence_ok=evidence_ok)
    return h, h.transport, h.clock


def answer(h, muse, clock, agent, text):
    muse.say(agent, text)
    h.tick()
    clock.go(61)
    h.tick()


def tasks():
    """blocked → ready → assigned → done (with evidence) → verified by someone else → unblocks the next."""
    h, muse, clock = new_hub()
    pid = h.add_product("Templates", brief="Etsy budgeting templates")
    prj = h.add_project(pid, "launch")
    for n, role in (("Ada", "engineer"), ("Bea", "designer")):
        h.add_agent(n, "muse")
        h.place(n, pid, role)
    t1 = h.add_task(prj, "build the sheet", role="engineer", done_def="a working .xlsx in the repo")
    t2 = h.add_task(prj, "cover image", role="designer", done_def="a 2000px PNG", blocked_by=[t1])

    h.tick()
    assert any("build the sheet" in t for t in muse.sent.get("Ada", [])), "engineer task goes to the engineer"
    assert not any("cover image" in t for t in muse.sent.get("Bea", [])), "the blocked design task is not sent"
    assert h.task(t2)["status"] == "blocked", h.task(t2)

    h.task_done("Ada", t1, "https://github.com/AgentNet01/x/commit/abc")
    assert h.task(t1)["status"] == "verifying", h.task(t1)
    h.tick()
    assert any("build the sheet" in t and "verify" in t.lower() for t in muse.sent.get("Bea", [])), \
        f"verify goes to a different agent: {muse.sent.get('Bea')}"
    h.task_verify("Bea", t1, True)
    assert h.task(t1)["status"] == "done", h.task(t1)
    h.tick()
    assert h.task(t2)["owner"] == "Bea", f"t2 unblocked and assigned once t1 is done: {h.task(t2)}"
    print("tasks OK")


def lifecycle():
    """One holder; `fleet task done` closes it; a different agent verifies; nothing is released on a timer."""
    h, muse, clock = new_hub()
    pid = h.add_product("P", brief="b"); prj = h.add_project(pid, "x")
    for n in ("Ada", "Cy"):
        h.add_agent(n, "muse"); h.place(n, pid, "engineer")
    t = h.add_task(prj, "the long job", role="engineer", done_def="works")
    h.tick()
    owner = h.task(t)["owner"]
    other = "Cy" if owner == "Ada" else "Ada"
    assert owner, h.task(t)
    try:
        h.task_done(other, t, "https://example.com/x")
        raise AssertionError("only the holder may mark a task done")
    except PermissionError:
        pass

    for _ in range(30):                                   # 30 hours of silence
        clock.go(3600); h.tick()
    assert h.task(t)["owner"] == owner and h.task(t)["status"] == "working", \
        f"a long task is never released by a timer: {h.task(t)}"
    sends = [m for m in muse.sent.get(owner, []) if "the long job" in m]
    assert len(set(sends)) == len(sends), "no message is ever sent twice word for word"

    h.task_note(owner, t, "half way, the export works")
    assert h.task(t)["status"] == "working" and "half way" in h.task(t)["progress_note"], h.task(t)

    h.task_done(owner, t, "https://example.com/evidence")
    assert h.task(t)["status"] == "verifying", h.task(t)
    h.tick()
    assert any("verify" in m.lower() and "the long job" in m for m in muse.sent.get(other, [])), muse.sent.get(other)
    try:
        h.task_verify(owner, t, True)
        raise AssertionError("the author can't verify their own task")
    except PermissionError:
        pass
    h.task_verify(other, t, False, "the totals are off by one")
    assert h.task(t)["status"] == "working" and h.task(t)["owner"] == owner, f"a failed verify goes back to its holder: {h.task(t)}"
    h.tick()
    assert any("totals are off by one" in m for m in muse.sent.get(owner, [])), "the holder is told why"
    h.task_done(owner, t, "https://example.com/evidence2")
    h.tick()
    h.task_verify(other, t, True)
    assert h.task(t)["status"] == "done", h.task(t)

    t2 = h.add_task(prj, "another", role="engineer", done_def="x")
    h.tick()
    holder = h.task(t2)["owner"]
    try:
        h.task_release(holder, t2)
        raise AssertionError("a worker can't release tasks")
    except PermissionError:
        pass
    h.task_release("jack", t2)
    assert h.task(t2)["owner"] is None and h.task(t2)["status"] == "ready", h.task(t2)
    assert not any("WAKANDA" in m for ms in muse.sent.values() for m in ms), "no done-word anywhere"
    print("lifecycle OK")


def poll():
    h, muse, clock = new_hub()
    pid = h.add_product("P", brief="b"); prj = h.add_project(pid, "x")
    h.add_agent("Pe", "poll"); h.place("Pe", pid, "engineer")
    t = h.add_task(prj, "pulled job", role="engineer", done_def="x")
    h.tick()
    assert h.task(t)["owner"] == "Pe", f"poll agent never assigned: {h.task(t)}"
    it = h.inbox("Pe")
    assert it and "pulled job" in it["text"], it
    assert h.inbox("Pe") is None, "a delivered task doesn't sit in the inbox forever"
    print("poll OK")


def placement():
    """Hold people constant: same product first, then a role switch on that product, then another product."""
    h, muse, clock = new_hub()
    a = h.add_product("A", brief="a"); b = h.add_product("B", brief="b")
    pa = h.add_project(a, "x")
    h.add_agent("Abe", "muse"); h.place("Abe", "B", "engineer")       # right role, other product
    h.add_agent("Zed", "muse"); h.place("Zed", "A", "designer")       # same product, other role
    t = h.add_task(pa, "build it", role="engineer", done_def="x")
    h.tick()
    assert not any("fleet switch" in m for m in muse.sent.get("Abe", [])), \
        f"placement: an agent on another product was switched in before one already on A: {muse.sent.get('Abe')}"
    assert any("fleet switch" in m and '"A"' in m and "engineer" in m for m in muse.sent.get("Zed", [])), \
        f"placement: the agent already on A takes a role switch: {muse.sent.get('Zed')}"

    h2, muse2, _ = new_hub()
    a2 = h2.add_product("A", brief="a"); h2.add_product("B", brief="b")
    p2 = h2.add_project(a2, "x")
    h2.add_agent("Abe", "muse"); h2.place("Abe", "B", "engineer")
    t2 = h2.add_task(p2, "build it", role="engineer", done_def="x")
    h2.tick()
    assert any("fleet switch" in m and '"A"' in m for m in muse2.sent.get("Abe", [])), \
        "placement: with nobody on A, someone from another product is switched in"
    print("placement OK")


def switch_between():
    h, muse, clock = new_hub()
    a = h.add_product("A", brief="a"); b = h.add_product("B", brief="b")
    pa, pb = h.add_project(a, "x"), h.add_project(b, "y")
    h.add_agent("Ann", "muse"); h.place("Ann", "A", "engineer")
    t = h.add_task(pa, "job on A", role="engineer", done_def="x")
    h.tick()
    assert h.task(t)["owner"] == "Ann"
    h.add_task(pb, "job on B", role="engineer", done_def="x")
    h.tick(); h.tick()
    assert not any("fleet switch" in m for m in muse.sent.get("Ann", [])), "never switched while holding a task"
    print("switch_between OK")


def org():
    h, muse, clock = new_hub()
    assert sorted(h.roles()) == ["designer", "engineer", "marketer", "optimizer"], h.roles()
    pid = h.add_product("P", brief="b"); prj = h.add_project(pid, "x")
    for n in ("Pam", "Cee", "Wes"):
        h.add_agent(n, "muse")
    h.set_pm("P", "Pam"); h.seat("ceo", "Cee")
    try:
        h.add_task(prj, "x", role="engineer", done_def="y", by="Wes")
        raise AssertionError("a worker can't create tasks")
    except PermissionError:
        pass
    for who in ("Pam", "Cee", "jack"):
        assert h.add_task(prj, f"by {who}", role="marketer", done_def="y", by=who)
    for n in ("M1", "M2"):
        h.add_agent(n, "muse"); h.place(n, "P", "marketer")
    h.tick()
    owners = {h.task(t["id"])["owner"] for pr in h.portfolio() for j in pr["projects"] for t in j["tasks"]}
    assert {"M1", "M2"} <= owners, f"several agents can hold the same role: {owners}"
    assert {p["name"]: p["pm"] for p in h.portfolio()}["P"] == "Pam"
    print("org OK")


def suggest():
    h, muse, clock = new_hub()
    pid = h.add_product("P", brief="b")
    for n in ("Opt", "Pam", "Cee", "Wes"):
        h.add_agent(n, "muse")
    h.place("Opt", "P", "optimizer"); h.set_pm("P", "Pam"); h.seat("ceo", "Cee")
    sid = h.suggest("Opt", "use bigger thumbnails")
    h.tick()
    for who in ("Pam", "Cee"):
        assert any("bigger thumbnails" in m for m in muse.sent.get(who, [])), f"{who} sees the suggestion"
    try:
        h.decide_suggestion("Wes", sid, True)
        raise AssertionError("a worker can't decide suggestions")
    except PermissionError:
        pass
    h.decide_suggestion("Pam", sid, True, "do it on the next listing")
    assert h.suggestions()[0]["status"] == "accepted", h.suggestions()
    h.tick()
    assert any("accepted" in m.lower() and "bigger thumbnails" in m for m in muse.sent.get("Opt", [])), "the optimizer hears back"
    print("suggest OK")


def seats():
    """Seats are interchangeable: an agent, Jack, or Darragh can hold the CEO seat."""
    h, muse, clock = new_hub()
    h.add_agent("darragh", "jack")
    h.add_agent("dot", "slack")
    for n in ("W1", "W2", "W3", "W4"):
        h.add_agent(n, "muse")
    h.seat("ceo", "jack")
    h.tick(); clock.go(13 * 3600); h.tick()
    assert any("W1" in n["text"] and "W4" in n["text"] for n in h.needs_jack()), \
        f"seats: with Jack as CEO the idle note lands in Needs Jack: {h.needs_jack()}"
    h.seat("ceo", "darragh")
    clock.go(13 * 3600); h.tick()
    assert any("Darragh" in n["text"] for n in h.needs_jack()), f"seats: labelled for Darragh: {h.needs_jack()}"
    h.seat("ceo", "dot")
    clock.go(13 * 3600); h.tick()
    assert any("W1" in m for m in muse.sent.get("dot", [])), f"seats: dot (over Slack) gets it: {muse.sent.get('dot')}"
    assert not any(n in muse.sent for n in ("W1", "W2", "W3", "W4")), "idle agents themselves are never pinged"
    print("seats OK")


def council():
    h, muse, clock = new_hub()
    pid = h.add_product("P", brief="b", pm="Pat")
    h.add_agent("Pat", "muse"); h.place("Pat", pid, "pm")        # chair
    h.seat("ceo", "Pat")
    for n in ("Al", "Bo", "Cj", "Dk"):                            # Dk will stay silent
        h.add_agent(n, "muse"); h.place(n, pid, "developer")

    cid = h.ask_all("Al", "what colour for the logo?")
    for n in ("Al", "Bo", "Cj", "Pat"):
        assert any("what colour" in t for t in muse.sent.get(n, [])), f"{n} got the question"
    answer(h, muse, clock, "Al", "blue")
    answer(h, muse, clock, "Bo", "blue")
    answer(h, muse, clock, "Cj", "red")
    answer(h, muse, clock, "Pat", "blue")
    c = h.council(cid)
    assert sorted(v["agent"] for v in c["views"]) == ["Al", "Bo", "Cj", "Pat"], c["views"]

    # window not closed while Dk might still answer; after 15 min it resolves without Dk
    assert c["status"] != "answered", "not resolved while a responder is outstanding"
    clock.go(16 * 60)
    h.tick()                                                      # window closes → chair gets the views
    assert any("what colour" in t and "blue" in t.lower() for t in muse.sent.get("Pat", [])), "chair gets the views"
    answer(h, muse, clock, "Pat", "go with blue, it fits the brand")
    c = h.council(cid)
    assert c["status"] == "answered", c
    assert "majority (3-1)" in c["answer"], f"labelled by the tally: {c['answer']}"
    assert "Cj" in c["answer"], f"dissent named: {c['answer']}"
    assert "Dk" in c["answer"], f"non-responder named: {c['answer']}"
    assert any("go with blue" in t for t in muse.sent.get("Al", [])), "answer relayed to the asker"
    print("council OK")


def manage():
    """The company runs itself: the CEO and PMs create products, projects and tasks and place agents."""
    h, muse, clock = new_hub()
    for n, k in (("Ada", "muse"), ("Bea", "muse"), ("dot", "slack")):
        h.add_agent(n, k)
    h.seat("ceo", "dot")

    # dot runs the company from its Slack replies: lines starting with "fleet " are commands
    answer(h, muse, clock, "dot", 'Setting up.\nfleet product add "Shop" "Etsy planner templates" "first sale"\n'
                                  'fleet pm "Shop" Ada\nfleet project add "Shop" "launch"')
    shop = h.db.execute("select * from products where name='Shop'").fetchone()
    assert shop and shop["pm"] == "Ada" and shop["metric"] == "first sale", dict(shop) if shop else None
    prj = h.db.execute("select id from projects where name='launch'").fetchone()["id"]
    clock.go(61); h.tick()
    back = "\n".join(muse.sent.get("dot", []))
    assert "product #" in back and f"project #{prj}" in back, f"dot hears what its commands did: {back[-400:]}"

    # the PM adds work to its product; the CEO staffs it
    r = h.manage("Ada", f'task add {prj} "list 3 planners" marketer "3 live listings"')
    assert "task #" in r, r
    assert "placed" in h.manage("dot", 'place Bea "Shop" marketer')
    assert h._agent("Bea")["current_product"] == "Shop"
    assert "Shop" in h.manage("Bea", "portfolio") and "list 3 planners" in h.manage("Bea", "portfolio")

    assert "unknown" in h.manage("dot", "fly away").lower()
    print("manage OK")


def loose():
    """The CEO runs the whole business (adds, changes, renames, removes), PMs run their product's tasks,
    parking agents stays with the board, and every change is logged."""
    h, muse, clock = new_hub()
    for n in ("Ada", "Bea", "Cy", "Pam"):
        h.add_agent(n, "muse")
    h.seat("ceo", "Bea")
    h.add_agent("darragh", "jack")
    m = lambda line, by="Bea": h.manage(by, line)

    assert "product #" in m('product add "Shop" "planner templates" "first sale"')
    assert "project #" in m('project add "Shop" "launch"')
    prj = h.db.execute("select id from projects where name='launch'").fetchone()["id"]
    t1 = int(m(f'task add {prj} "draw sheet" designer "a PNG"').split("#")[1].split()[0])
    t2 = int(m(f'task add {prj} "list it" marketer "live listing" {t1}').split("#")[1].split()[0])
    m(f'task set {t1} title "draw the sheet"'); m(f'task set {t1} done "a 300dpi PNG"'); m(f'task set {t1} role engineer')
    t = h.task(t1)
    assert (t["title"], t["done_def"], t["role"]) == ("draw the sheet", "a 300dpi PNG", "engineer"), t
    m(f"task remove {t1}")
    h.tick()
    assert h.task(t1)["status"] == "cancelled" and h.task(t2)["status"] != "blocked", "a removed blocker stops blocking"

    m('place Ada "Shop" marketer'); m('pm "Shop" Pam')
    assert h._agent("Ada")["current_product"] == "Shop"
    # the PM manages its product's tasks, and nothing else
    t3 = int(m(f'task add {prj} "price it" optimizer "a price"', by="Pam").split("#")[1].split()[0])
    m(f'task set {t3} title "price the sheet"', by="Pam"); m(f"task remove {t3}", by="Pam")
    for line, who in (('product add "X" "y"', "Pam"), ('project add "Shop" "x"', "Pam"), ("seat ceo Pam", "Pam"),
                      (f'task add {prj} "x" engineer "y"', "Cy"), ('product add "X" "y"', "Cy"),
                      ("park Ada", "Bea"), ("wake Ada", "Bea"), ("park Ada", "Pam")):
        try:
            m(line, by=who)
            raise AssertionError(f"{who} ran: {line}")
        except PermissionError:
            pass
    assert h._agent("Ada")["state"] == "active"
    m('role set marketer "You write listings that sell."')
    assert h.roles()["marketer"] == "You write listings that sell."
    m('project rename "Shop" "launch" "go-live"')
    m('product rename "Shop" "Planner Shop"')
    assert h._agent("Ada")["current_product"] == "Planner Shop", "agents follow a renamed product"
    assert "go-live" in m("portfolio") and "Planner Shop" in m("portfolio")
    m("park Ada", by="jack"); assert h._agent("Ada")["state"] == "parked"
    m("wake Ada", by="darragh"); assert h._agent("Ada")["state"] == "active"
    m("seat ceo Cy"); assert h._chair() == "Cy"
    m = lambda line, by="Cy": h.manage(by, line)

    m('product remove "Planner Shop"')
    assert "Planner Shop" not in m("portfolio"), "a removed product is gone from the portfolio"
    assert h._agent("Ada")["current_product"] is None, "its agents are freed"
    assert h.task(t2)["status"] == "cancelled", "its open work is cancelled"
    m('product set "Planner Shop" status active')
    assert "Planner Shop" in m("portfolio"), "and it can be brought back"

    log = h.changes()
    assert log[0]["by"] == "Cy" and "status active" in log[0]["line"], log[:2]
    assert any("product remove" in c["line"] for c in log)
    assert h.board()["changes"][0]["line"] == log[0]["line"], "the dashboard shows the change log"
    for line in ("seat ceo nobody", "fly away"):
        r = None
        try:
            r = m(line)
        except (ValueError, PermissionError):
            continue
        assert "unknown" in r.lower(), (line, r)
    print("loose OK")


def grants():
    """The CEO can lift anyone to CEO-level powers (not parking); those agents can grant too; every agent
    is told what it can do, in fleet status and in a note whenever its powers change."""
    h, muse, clock = new_hub()
    for n in ("Ada", "Bea", "Cy"):
        h.add_agent(n, "muse")
    h.seat("ceo", "Ada")
    assert "can't change the company" in h.powers("Bea"), h.powers("Bea")
    h.manage("Ada", "grant Bea ceo")
    assert "everything the CEO can" in h.powers("Bea"), h.powers("Bea")
    assert "product #" in h.manage("Bea", 'product add "Shop" "x"'), "a granted agent runs the company"
    h.manage("Bea", "grant Cy ceo")                      # and can lift others up to its own level
    try:
        h.manage("Bea", "park Cy"); raise AssertionError("granted agents still can't park")
    except PermissionError:
        pass
    h.manage("Bea", "grant Cy none")
    try:
        h.manage("Cy", 'product add "Mine" "x"'); raise AssertionError("revoked")
    except PermissionError:
        pass
    h.manage("Ada", 'pm "Shop" Cy')
    assert "tasks in Shop" in h.powers("Cy"), h.powers("Cy")
    h.tick(); clock.go(61); h.tick()
    told = "\n".join(muse.sent.get("Bea", []) + muse.sent.get("Cy", []))
    assert "fleet portfolio" in told and "CEO" in told, f"agents are told what they can now do: {told[-500:]}"
    print("grants OK")


if __name__ == "__main__":
    {"council": council, "lifecycle": lifecycle, "poll": poll, "placement": placement, "org": org, "suggest": suggest,
     "seats": seats, "manage": manage, "loose": loose, "grants": grants, "switch_between": switch_between}.get(sys.argv[1] if len(sys.argv) > 1 else "", tasks)()
