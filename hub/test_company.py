"""Company layer: products, projects, tasks with dependencies, assignment, verify, council, org.

    python3 test_company.py          # tasks: blocked → ready → assign → done → verify → unblock
    python3 test_company.py council  # ask all → views → one labelled chair answer
"""
import os
import sys
import tempfile
import time

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


def resubmit():
    """Jack, Oct 15: Pericles handed in #874 with the same listing URL twice; each rejection reached him as a queued FYI
    he hadn't read yet. Handing in the evidence that was just rejected is refused on the spot, with the checker's reason."""
    h, muse, clock = new_hub()
    pid = h.add_product("P", brief="b"); prj = h.add_project(pid, "x")
    for n in ("Ada", "Cy"):
        h.add_agent(n, "muse"); h.place(n, pid, "engineer")
    t = h.add_task(prj, "coupon", role="engineer", done_def="coupon verified in the dashboard", owner="Ada")
    h.tick()
    h.task_done("Ada", t, "https://www.etsy.com/listing/1")
    h.task_verify("Cy", t, False, "only the listing page; show the coupon")
    h.tick()
    assert h.task(t)["owner"] == "Ada" and h.task(t)["status"] == "working", h.task(t)
    try:
        h.task_done("Ada", t, "https://www.etsy.com/listing/1")
        raise AssertionError("resubmit: the same rejected evidence is refused")
    except ValueError as e:
        assert "show the coupon" in str(e), f"resubmit: the refusal carries the checker's reason: {e}"
    h.task_done("Ada", t, "https://muse.ai/files/1/2/x/coupon.png")
    assert h.task(t)["status"] == "verifying", "resubmit: new evidence goes through"
    print("resubmit OK")


def lifecycle():
    """One holder; `fleet task done` closes it; a different agent verifies. Silence alone never releases it — only
    TASK_CAP does (Jack, Oct 15; test_autonomy overdue), switched off here."""
    hub.TASK_CAP = 10 ** 9
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
    assert any("carry it out" in i["text"] and "bigger thumbnails" in i["text"] for i in h.items_for("Cee")), \
        "accepting isn't the end: the CEO is told to carry it out"
    before = len(muse.sent.get("Cee", []))
    sid2 = h.suggest("Opt", "drop the price"); h.tick(); before = len(muse.sent.get("Cee", []))
    h.decide_suggestion("Cee", sid2, True); h.tick()
    assert not any("carry it out" in m for m in muse.sent.get("Cee", [])[before:]), "the CEO who accepted it isn't told twice"

    # the PM suggests; the CEO hears, talks it over with the PM, decides, does it and logs it — no board needed
    before = len(muse.sent.get("Cee", []))
    sid3 = h.suggest("Pam", "move Wes to the designer team"); h.tick()
    assert h.suggestions()[0]["product"] == "P", "a PM's suggestion belongs to the product it runs"
    got = "\n".join(muse.sent.get("Cee", [])[before:])
    assert "move Wes" in got and "Talk it over with Pam" in got and f"fleet suggestion accept {sid3}" in got, got
    assert any(f"#{sid3}" in m and "Cee" in m for m in muse.sent.get("Pam", [])), "the suggester knows who decides it"
    assert not any("Talk it over with Pam" in m for m in muse.sent.get("Pam", [])), "the PM isn't asked to decide its own idea"
    h.manage("Cee", "team Wes designer")
    out = h.manage("Cee", f'suggestion accept {sid3} "agreed with Pam; Wes is on designer now"')
    sg = h.suggestions()[0]
    assert sg["status"] == "accepted" and sg["decided_by"] == "Cee" and "Wes is on designer" in sg["note"], (out, sg)
    assert any(f"suggestion accept {sid3}" in c["line"] for c in h.changes()), "the decision is in the change log"
    try:
        h.manage("Wes", f"suggestion reject {sid3}"); raise AssertionError("a worker decided a suggestion")
    except PermissionError:
        pass
    assert "suggestion accept" in h.MANAGE_HELP
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
    # Jack, Oct 13: a PM's company-level change goes to the CEO for review instead of being refused
    for line in ('product add "X" "y"', 'project add "Shop" "x"'):
        assert "review" in m(line, by="Pam"), line
    assert not h.db.execute("select 1 from products where name='X'").fetchone(), "not done before the review"
    for line, who in (("seat ceo Pam", "Pam"),
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

    m('product remove "Planner Shop"', by="jack")
    assert "Planner Shop" not in m("portfolio"), "a removed product is gone from the portfolio"
    assert h._agent("Ada")["current_product"] is None, "its agents are freed"
    assert h.task(t2)["status"] == "cancelled", "its open work is cancelled"
    m('product set "Planner Shop" status active', by="darragh")
    assert "Planner Shop" in m("portfolio"), "and it can be brought back"

    log = h.changes()
    assert log[0]["by"] == "darragh" and "status active" in log[0]["line"], log[:2]
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


def timeline():
    """An agent's page reads like a conversation: each message says who sent it, and a failure
    repeated on every retry shows once with a count instead of flooding the page."""
    h, muse, clock = new_hub()
    h.add_agent("Ada", "muse")
    for i in range(5):
        h._log(None, "Ada", "err", f"#{700 + i} no slack-bot-token in the vault")
        clock.go(15)
    h.ask("jack", "Ada", "how's the shop?")
    h.tick()
    tl = h.timeline("Ada")
    errs = [e for e in tl if e["dir"] == "err"]
    assert len(errs) == 1 and errs[0]["count"] == 5, errs
    sent = [e for e in tl if e["dir"] == "in"]
    assert sent and sent[-1]["frm"] == "jack", sent
    assert sent[-1]["item_text"] == "how's the shop?" and sent[-1]["kind"] == "request", "the page shows what Jack wrote, not the envelope"
    assert sent[-1]["item_status"] == "sent", "and whether it's still waiting for a reply"
    h._log(None, "Ada", "err", "recovered")              # once the agent is reachable again, the old failures go away
    assert not [e for e in h.timeline("Ada") if e["dir"] == "err"], h.timeline("Ada")
    h._log(None, "Ada", "err", "#800 connection refused")  # a new failure after that does show
    assert [e["text"] for e in h.timeline("Ada") if e["dir"] == "err"] == ["#800 connection refused"]
    print("timeline OK")


def send_now():
    """Jack's message goes out the moment he sends it, not on the next loop; a slow send racing the
    loop still goes out exactly once."""
    import threading, time as _t
    h, muse, clock = new_hub()
    h.add_agent("Ada", "muse")
    real = muse.deliver
    def slow(agent, text):
        _t.sleep(0.3)
        return real(agent, text)
    muse.deliver = slow
    h.ask("jack", "Ada", "hi there")
    h.deliver_now("Ada")
    racer = threading.Thread(target=h.tick); racer.start()
    for _ in range(50):
        if muse.sent.get("Ada"):
            break
        _t.sleep(0.05)
    racer.join()
    for th in threading.enumerate():
        if th is not threading.current_thread() and th.daemon:
            th.join(timeout=2)
    assert len([t for t in muse.sent.get("Ada", []) if "hi there" in t]) == 1, muse.sent

    # the reply is picked up within seconds, without waiting for the loop, and logged once
    h.REPLY_WATCH = (0.05, 3)
    h.ask("jack", "Ada", "second question")
    muse.deliver = real
    h.deliver_now("Ada")
    _t.sleep(0.2)
    muse.say("Ada", "second answer")
    for _ in range(60):
        if any(e["text"] == "second answer" for e in h.timeline("Ada")):
            break
        _t.sleep(0.05)
    h.tick()
    assert [e["text"] for e in h.timeline("Ada") if e["dir"] == "out"].count("second answer") == 1, h.timeline("Ada")
    print("send_now OK")


def dry():
    """A product with no work left asks its PM (or the CEO when it has none) to plan the next tasks,
    at most every 12 hours; a product with work in flight is left alone."""
    h, muse, clock = new_hub()
    for n in ("Ada", "dot", "Pam"):
        h.add_agent(n, "muse")
    h.seat("ceo", "dot")
    shop = h.add_product("Shop", brief="planners")
    h.add_product("Stickers", brief="stickers", pm="Pam")
    prj = h.add_project(shop, "launch")
    h.tick(); clock.go(61); h.tick()
    told = lambda who: [t for t in muse.sent.get(who, []) if "no work lined up" in t]
    assert len(told("dot")) == 1 and "Shop" in told("dot")[0], muse.sent.get("dot")
    assert len(told("Pam")) == 1 and "Stickers" in told("Pam")[0], muse.sent.get("Pam")
    clock.go(3600); h.tick(); clock.go(61); h.tick()
    assert len(told("dot")) == 1, "not again within 12 hours"
    h.add_task(prj, "draw a planner", role="designer", done_def="a PNG")
    h.tick()
    assert len(told("dot")) == 1, "a product with work waiting to be picked up isn't nagged"
    clock.go(13 * 3600); h.tick(); clock.go(61); h.tick()
    # Jack, Oct 13: work in progress isn't enough while agents sit free — once the queue is empty, plan more
    assert len(told("dot")) == 2, "its work all taken and agents still free: Shop is planned again"
    assert len(told("Pam")) == 2, "Stickers is still dry after 12 h, so Pam hears again"
    h.manage("jack", 'product set "Stickers" status paused')
    clock.go(13 * 3600); h.tick(); clock.go(61); h.tick()
    assert len(told("Pam")) == 2, "a paused product isn't nagged"
    print("dry OK")


def activity():
    """One feed of everything the company did in a window: messages both ways, task moves, changes and
    failures, newest first, with per-agent counts and messages-per-hour for the last day."""
    h, muse, clock = new_hub()
    for n in ("Ada", "Bea", "dot"):
        h.add_agent(n, "muse")
    h.seat("ceo", "dot")
    h.ask("jack", "Ada", "status?"); h.tick()
    muse.say("Ada", "all good"); h.tick(); clock.go(61); h.tick()
    h.manage("dot", 'product add "Shop" "x"')
    h._log(None, "Bea", "err", "#9 connection refused")
    clock.go(2 * 3600)
    h.ask("jack", "Bea", "you there?"); h.tick()
    a = h.activity(since=clock() - 3600)
    texts = [e["text"] for e in a["feed"]]
    assert any("you there?" in t for t in texts) and not any("status?" in t for t in texts), "the window is respected"
    day = h.activity(since=clock() - 24 * 3600)
    kinds = {e["type"] for e in day["feed"]}
    assert {"sent", "reply", "change", "error"} <= kinds, kinds
    assert day["feed"][0]["at"] >= day["feed"][-1]["at"], "newest first"
    sent = [e for e in day["feed"] if e["type"] == "sent" and e["agent"] == "Ada"][0]
    assert sent["from"] == "jack" and sent["text"] == "status?", sent
    assert day["counts"]["reply"] == 1 and day["counts"]["change"] == 1 and day["counts"]["error"] == 1, day["counts"]
    ada = day["agents"]["Ada"]
    assert ada["reply"] == 1 and ada["sent"] >= 1 and ada["last_said"], ada
    assert len(day["per_hour"]) == 24 and sum(day["per_hour"]) >= 3, day["per_hour"]
    # a failure the next try fixed is marked, so a Muse blip doesn't read like a broken agent
    h.db.execute("insert into events(agent, dir, text, at) values('Ada','err','#1 boom',?)", (clock(),))
    clock.go(5)
    h.db.execute("insert into events(agent, dir, text, at) values('Ada','err','recovered',?)", (clock(),))
    clock.go(5)
    h.db.execute("insert into events(agent, dir, text, at) values('Bea','err','#2 still down',?)", (clock(),))
    errs = {e["agent"]: e for e in h.activity(since=clock() - 60)["feed"] if e["type"] == "error"}
    assert errs["Ada"]["recovered"] and not errs["Bea"]["recovered"], errs
    w = h.activity(since=clock() - 60)
    assert w["counts"]["error"] == 1 and sum(b["error"] for b in w["buckets"]) == 1, "only the unresolved failure counts"

    # the real cause survives: muse-cli's last line, not the middle of its traceback
    import muse
    t = muse.MuseTransport([sys.executable, "-c", "import sys; sys.stderr.write('Traceback\\n  File x\\n' + 'y'*400 + "
                            "'\\ncurl_cffi.curl.CurlError: Failed to perform, curl: (28) Operation timed out'); sys.exit(1)"], {"Ada": "/tmp"})
    try:
        t._run("Ada", "raw"); raise AssertionError("no error raised")
    except RuntimeError as e:
        assert "(28) Operation timed out" in str(e)[:160], str(e)
    print("activity OK")


def observe():
    """Jack can see the company working: what each agent's machine says it's doing (kept as history, not just
    the latest snapshot), every step of every task, who sent each message, any time window, per agent."""
    h, muse, clock = new_hub(evidence_ok=lambda link: True)
    for n in ("Ada", "Bea"):
        h.add_agent(n, "muse")
    h.add_agent("darragh", "jack")
    t0 = clock()
    iso = lambda t: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))
    blob = {"activity": {"current": "drafting a response", "entries": [
        {"timestamp": iso(t0 - 60), "activity_type": "goal", "status": "success", "title": "Checked the Etsy listing",
         "subtitle": "3 views today", "message_id": "m1"},
        {"timestamp": iso(t0 - 30), "activity_type": "tool", "status": "running", "title": "Writing listing copy", "message_id": "m2"}]}}
    h.ingest("Ada", blob); h.ingest("Ada", blob)                      # the same snapshot twice is kept once
    pid = h.add_product("Shop", brief="b"); prj = h.add_project(pid, "launch")
    h.place("Ada", "Shop", "marketer"); h.place("Bea", "Shop", "marketer")
    tid = h.add_task(prj, "write the listing", role="marketer", done_def="live listing")
    h.tick()
    holder = h.task(tid)["owner"]; other = "Bea" if holder == "Ada" else "Ada"
    h.task_note(holder, tid, "first draft done")
    h.task_done(holder, tid, "https://etsy.com/listing/1")
    h.tick()
    h.task_verify(other, tid, True)
    h.ask("darragh", "Bea", "how's it going?")
    a = h.activity(since=t0 - 3600)
    work = [e for e in a["feed"] if e["type"] == "work" and e["agent"] == "Ada"]
    assert [e["text"] for e in work] == ["Writing listing copy", "Checked the Etsy listing"], work
    steps = [e["what"] for e in a["feed"] if e["type"] == "task"][::-1]
    assert steps == ["assigned", "note", "done", "verify", "verified"], steps
    assert any(e["type"] == "sent" and e["from"] == "darragh" for e in a["feed"]), "the sender is whoever sent it"
    assert [t["id"] for t in a["tasks"]["finished"]] == [tid], a["tasks"]
    assert a["counts"]["work"] == 2 and a["counts"]["task"] == 5, a["counts"]
    only = h.activity(since=t0 - 3600, agent="Bea")
    assert only["feed"] and all(e["agent"] == "Bea" for e in only["feed"]), only["feed"]
    early = h.activity(since=t0 - 3600, until=t0 - 45)
    assert [e["text"] for e in early["feed"]] == ["Checked the Etsy listing"], early["feed"]
    assert len(a["buckets"]) == 24 and sum(b["work"] for b in a["buckets"]) == 2, a["buckets"][-3:]
    print("observe OK")


def teams():
    """Agents carry a standing team (a role, or generalist), not a product. A task goes to someone whose team
    fits it — specialists before generalists — and the product's context is switched in per task."""
    h, muse, clock = new_hub()
    for n in ("Des", "Gen", "Mar", "dot"):
        h.add_agent(n, "muse")
    h.seat("ceo", "dot")
    h.manage("dot", "team Des designer"); h.manage("dot", "team Mar marketer"); h.manage("dot", "team Gen generalist")
    assert h._agent("Mar")["team"] == "marketer"
    pid = h.add_product("Etsy", brief="planners"); prj = h.add_project(pid, "launch")
    switched = lambda n: [m for m in muse.sent.get(n, []) if "fleet switch" in m]

    h.add_task(prj, "write listing copy", role="marketer", done_def="copy in the doc")
    for _ in range(3): h.tick()
    assert switched("Mar") and not switched("Des") and not switched("Gen"), "the marketer, not a designer or the generalist"
    h.add_task(prj, "price the bundle", role="optimizer", done_def="a price")
    for _ in range(3): h.tick()
    assert switched("Gen") and not switched("Des"), "nobody on the optimizer team: the generalist covers it, never the designer"

    # an agent can join a team itself; anyone else's team is the CEO's call
    h.add_agent("Neo", "muse")
    assert "marketer" in h.manage("Neo", "team me marketer") and h._agent("Neo")["team"] == "marketer"
    try:
        h.manage("Neo", "team Des marketer"); raise AssertionError("Neo moved someone else")
    except PermissionError:
        pass
    h.manage("dot", 'role set researcher "You dig up facts and sources."')      # new roles are just new teams
    h.manage("dot", "team Des researcher")
    assert h._agent("Des")["team"] == "researcher"
    assert "team" in h.powers("Neo") and "fleet team me" in h.powers("Neo"), h.powers("Neo")
    assert {a["name"]: a["team"] for a in h.org()["agents"]}["Mar"] == "marketer", "the Org page shows each team"
    print("teams OK")


def pin():
    """The CEO can give a task to one named agent: only that agent gets it, whatever its team, and the
    agent holding it now hands it over. "owner none" lets the hub route it again."""
    h, muse, clock = new_hub()
    for n in ("Mar", "Per", "dot"):
        h.add_agent(n, "muse")
    h.seat("ceo", "dot")
    h.manage("dot", "team Mar marketer"); h.manage("dot", "team Per designer")
    pid = h.add_product("Etsy", brief="planners"); prj = h.add_project(pid, "launch")
    h.place("Mar", "Etsy", "marketer")
    t = h.add_task(prj, "publish listing", role="marketer", done_def="live on Etsy")
    h.tick()
    assert h.task(t)["owner"] == "Mar"
    assert "Per" in h.manage("dot", f"task set {t} owner Per")
    assert h.task(t)["owner"] is None and h.task(t)["pin"] == "Per", "Mar hands it over"
    for _ in range(3): h.tick()
    assert h.task(t)["owner"] == "Per" and any("fleet switch" in m for m in muse.sent.get("Per", [])), \
        "only Per gets it, moved into the task's context at once even though Per is a designer and hasn't run the switch"
    h.manage("dot", f"task release {t}")
    h.tick()
    assert h.task(t)["owner"] == "Per", "a released pinned task goes back to its agent, not to Mar"
    h.manage("dot", f"task set {t} owner none"); h.manage("dot", f"task release {t}")
    h.place("Per", "Etsy", "designer")
    h.tick()
    assert h.task(t)["owner"] == "Mar", "unpinned: normal routing again"
    for bad in ("nobody", "jack"):
        try:
            h.manage("dot", f"task set {t} owner {bad}"); raise AssertionError(f"pinned to {bad}")
        except (ValueError, PermissionError):
            pass
    h.add_agent("Neo", "muse")
    try:
        h.manage("Neo", f"task set {t} owner Neo"); raise AssertionError("a plain agent pinned a task")
    except PermissionError:
        pass
    assert "owner" in h.MANAGE_HELP
    h._run_lines("dot", 'fleet ask Per "can you publish today?"')
    h.tick()
    assert any("can you publish today?" in m for m in muse.sent.get("Per", [])), "dot reaches an agent with a fleet ask line"
    print("pin OK")


def stuck():
    """A ready task nobody can take: a stale switch record never blocks a switch, and when no switch can fill it
    the product's PM (else the CEO) is told once why and how to fix it."""
    h, muse, clock = new_hub()
    for n in ("Mar", "Per", "dot", "Pam"):
        h.add_agent(n, "muse")
    h.seat("ceo", "dot")
    h.manage("dot", "team Mar marketer"); h.manage("dot", "team Per marketer")
    h.manage("dot", "team Pam designer"); h.manage("dot", "team dot designer")    # no generalists free
    pid = h.add_product("Etsy", brief="planners"); prj = h.add_project(pid, "launch")
    h.issue_switch("Mar", "Etsy", "marketer")              # Mar never reports the switch back: it stays 'issued'
    t1 = h.add_task(prj, "publish listing", role="marketer", done_def="live")
    h.tick()
    assert h.task(t1)["owner"] == "Mar"
    t2 = h.add_task(prj, "social posts", role="marketer", done_def="posted")
    h.manage("dot", f"task set {t2} owner Per")
    for _ in range(3): h.tick()
    assert h.task(t2)["owner"] == "Per", "Mar's stale switch to Etsy/marketer doesn't stop Per being switched in"

    t3 = h.add_task(prj, "reply to buyers", role="marketer", done_def="answered")
    h.manage("dot", f"task set {t3} owner Mar")             # Mar is busy on t1
    for _ in range(3): h.tick()
    told = [m for m in muse.sent.get("dot", []) if f"#{t3}" in m and "can't be filled" in m]
    assert len(told) == 1, f"the CEO (no PM yet) is told once: {muse.sent.get('dot')}"
    assert "Mar" in told[0] and f"#{t1}" in told[0] and f"fleet task set {t3} owner" in told[0], told[0]

    h.set_pm("Etsy", "Pam")
    t4 = h.add_task(prj, "price check", role="optimizer", done_def="a price")   # no optimizer, no generalist free
    for _ in range(3): h.tick()
    told = [m for m in muse.sent.get("Pam", []) if f"#{t4}" in m and "can't be filled" in m]
    assert len(told) == 1 and "optimizer" in told[0], f"the PM is told: {muse.sent.get('Pam')}"
    print("stuck OK")


def handoff():
    """A finished task tells everyone else holding a task in the same project (and the PM) where its result is,
    so agents waiting on it informally don't sit idle."""
    h, muse, clock = new_hub()
    for n in ("Eng", "Mar", "Des", "Pam", "Out"):
        h.add_agent(n, "muse")
    pid = h.add_product("Shop", brief="b", pm="Pam"); prj = h.add_project(pid, "launch"); other = h.add_project(pid, "later")
    t1 = h.add_task(prj, "build template", role="engineer", done_def="zip")
    t2 = h.add_task(prj, "copy pack", role="marketer", done_def="doc")
    t3 = h.add_task(other, "next idea", role="designer", done_def="png")
    for n, r in (("Eng", "engineer"), ("Mar", "marketer"), ("Out", "designer")):
        h.manage("jack", f"team {n} {r}"); h.place(n, "Shop", r)
    h.tick()
    assert [h.task(t)["owner"] for t in (t1, t2, t3)] == ["Eng", "Mar", "Out"]
    before = {n: len(muse.sent.get(n, [])) for n in ("Eng", "Mar", "Out", "Pam")}
    h.task_done("Eng", t1, "https://example.com/v1.zip")
    h.tick(); clock.go(61); h.tick()
    new = lambda n: "\n".join(muse.sent.get(n, [])[before[n]:])
    assert "build template" in new("Mar") and "https://example.com/v1.zip" in new("Mar"), new("Mar")
    assert "https://example.com/v1.zip" in new("Pam"), "the PM hears too"
    assert "v1.zip" not in new("Out"), "another project's people aren't pinged"
    assert "v1.zip" not in new("Eng"), "not told about its own work"
    print("handoff OK")


def links():
    """muse.ai posts a link on its own line as a separate external_link event; the reply keeps it, in place."""
    import muse
    t = muse.MuseTransport(["true"], {"Ada": "/tmp"})
    url = "https://muse.ai/files/1/2/abc/creatives.zip"
    t._events = lambda name, limit: [
        {"seq": 10, "event_name": "message.user", "display_text": "send the link"},
        {"seq": 11, "event_name": "message.assistant", "display_text": "Evidence link:"},
        {"seq": 12, "event_name": "delta.presentation", "display_text": url,
         "payload": {"kind": "external_link", "data": {"url": url, "fallback_text": url}}},
        {"seq": 13, "event_name": "message.assistant", "display_text": "Expires Oct 12."},
        {"seq": 14, "event_name": "delta.presentation", "payload": {"kind": "something_else", "data": {}}},
    ]
    got = t.replies("Ada", 10)
    assert [x[1] for x in got] == ["Evidence link:", url, "Expires Oct 12."], got
    print("links OK")


if __name__ == "__main__":
    {"council": council, "resubmit": resubmit, "lifecycle": lifecycle, "poll": poll, "placement": placement, "org": org, "suggest": suggest,
     "seats": seats, "manage": manage, "loose": loose, "grants": grants, "timeline": timeline, "send_now": send_now, "dry": dry, "activity": activity, "observe": observe, "teams": teams, "pin": pin, "handoff": handoff, "links": links, "switch_between": switch_between, "stuck": stuck}.get(sys.argv[1] if len(sys.argv) > 1 else "", tasks)()
