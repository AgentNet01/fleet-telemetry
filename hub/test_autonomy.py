"""Autonomy: the hub sees what agents really do, tasks tell the truth, and work never runs dry.

    python3 test_autonomy.py activity   # Muse mid-turn / last action → board, and it counts as acting
    python3 test_autonomy.py truth      # blocked work frees its holder; owned work starts when it can
    python3 test_autonomy.py planning   # PM asked, then an idle agent plans, its task gets taken
    python3 test_autonomy.py standin    # a silent CEO is stood in for, and gets the seat back by acting
    python3 test_autonomy.py slack200   # a Slack thread past 200 messages is still read
"""
import os
import re
import sys
import tempfile

import hub
from test_hub import Clock, FakeMuse
from hub import PLAN_WAIT


class ActiveMuse(FakeMuse):
    """FakeMuse plus what Muse reports about an agent outside the fleet chat."""
    def __init__(self):
        super().__init__()
        self.acts, self.pending, self.decided = {}, {}, []

    def activity(self, agent):
        return self.acts.get(agent)

    def approvals(self, agent):
        return list(self.pending.get(agent, []))

    def decide(self, agent, aid, decision):
        self.decided.append((agent, aid, decision))
        self.pending[agent] = [a for a in self.pending.get(agent, []) if a["id"] != aid]


def new_hub(*agents):
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), ActiveMuse(), Clock(), evidence_ok=lambda link: True)
    for n in agents:
        h.add_agent(n, "muse")
    return h, h.transport, h.clock


def row(h, name):
    return {a["name"]: a for a in h.board()["agents"]}[name]


def activity():
    h, muse, clock = new_hub("Ada", "Bo")
    assert hasattr(h, "observe"), "activity: the hub has no observe() reading Muse activity"
    muse.acts["Ada"] = {"busy": True, "at": clock() - 30, "line": "Updated pet-portrait-drafts.md"}
    muse.acts["Bo"] = {"busy": False, "at": clock() - 7200, "line": "Searched: etsy pet portrait prices"}
    h.observe()
    a, b = row(h, "Ada"), row(h, "Bo")
    assert a["doing"] == {"busy": True, "line": "Updated pet-portrait-drafts.md", "at": clock() - 30}, a["doing"]
    assert b["doing"]["busy"] is False and b["doing"]["line"].startswith("Searched"), b["doing"]

    # an agent marked unresponsive but seen acting in Muse is not unresponsive
    h.db.execute("update agents set state='unresponsive' where name='Bo'")
    clock.go(600)
    muse.acts["Bo"] = {"busy": False, "at": clock() - 10, "line": "Created launch-plan.md"}
    h.observe()
    assert h._agent("Bo")["state"] == "active", "seen acting in Muse → active"
    assert h._agent("Bo")["last_act"] == clock() - 10, h._agent("Bo")["last_act"]
    # an old action doesn't revive anyone
    h.db.execute("update agents set state='unresponsive' where name='Bo'")
    clock.go(600); h.observe()
    assert h._agent("Bo")["state"] == "unresponsive", "nothing new since → still unresponsive"
    # a parked agent is never read
    h.db.execute("update agents set state='parked' where name='Ada'")
    muse.acts["Ada"] = None
    h.observe()
    print("activity OK")


def truth():
    h, muse, clock = new_hub("Ada", "Bo", "Cy", "Dee")
    pid = h.add_product("P", brief="b"); prj = h.add_project(pid, "x")
    for n in ("Ada", "Bo", "Cy", "Dee"):
        h.place(n, pid, "engineer")
    blocker = h.add_task(prj, "spec", "engineer", "a spec")
    work = h.add_task(prj, "build", "engineer", "built", blocked_by=[blocker])
    h.tick()
    first = h.task(blocker)["owner"]
    h.task_done(first, blocker, "https://x/1"); h.tick()
    other = "Bo" if first == "Ada" else "Ada"
    h.task_verify(other, blocker, True); h.tick()
    holder = h.task(work)["owner"]
    assert h.task(work)["status"] == "working" and holder, h.task(work)
    # the blocker is reopened (e.g. Jack sends it back): the dependent stops claiming to be in progress
    h.db.execute("update tasks set status='ready', owner=null where id=?", (blocker,))
    h.tick()
    t = h.task(work)
    assert t["status"] == "blocked" and not t["owner"], f"blocked, holder freed: {t}"
    assert not h._open_tasks(holder) or h._open_tasks(holder)[0]["id"] == blocker, "the holder is free for other work"
    assert t["pin"] == holder and any("on hold" in s for s in muse.sent.get(holder, [])) or \
        any("on hold" in i["text"] for i in h.items_for(holder)), "the holder is told, and gets it back later"
    clock.go(3600)
    h.db.execute("update agents set state='unresponsive' where name='Bo'")
    muse.acts["Bo"] = {"busy": False, "at": clock() - 7200, "line": "Edited old.md"}
    h.observe()
    assert h._agent("Bo")["state"] == "unresponsive", "an action two hours old doesn't clear 'not answering'"

    # a task created for a named (free) owner starts with that owner, now or once its blocker is done
    h.db.execute("update tasks set status='cancelled' where status in ('ready','working','blocked')"); h.tick()
    gate = h.add_task(prj, "gate", "engineer", "g")
    mine = h.add_task(prj, "mine", "engineer", "m", owner="Cy")
    later = h.add_task(prj, "later", "engineer", "l", blocked_by=[gate], owner="Dee")
    h.tick()
    assert h.task(mine)["status"] == "working" and h.task(mine)["owner"] == "Cy", f"owned task starts: {h.task(mine)}"
    assert any("mine" in s for s in muse.sent.get("Cy", [])), "and Cy is told"
    h.db.execute("update tasks set status='done' where id=?", (gate,)); h.tick()
    assert h.task(later)["status"] == "working" and h.task(later)["owner"] == "Dee", f"blocked owned task starts once free: {h.task(later)}"
    print("truth OK")


def planning():
    h, muse, clock = new_hub("Pat", "Ada", "Bo", "Cy")
    pid = h.add_product("Gifts", brief="personalized pet portraits on Etsy", metric="first sale")
    prj = h.add_project(pid, "launch")
    h.set_pm("Gifts", "Pat")
    h.place("Pat", pid, "marketer"); h.place("Ada", pid, "marketer")
    busy = h.add_task(prj, "posts", "marketer", "posted", owner="Ada")
    h.tick()
    assert h.task(busy)["status"] == "working", f"plan setup: a task created for Ada starts with Ada: {h.task(busy)}"
    # nothing queued, Bo and Cy idle (and unplaced): the PM is asked to plan
    h.tick()
    assert any("no work lined up" in s.lower() or "plan" in s.lower() for s in muse.sent.get("Pat", [])), \
        f"plan: the PM is asked when nothing is queued and agents are idle: {muse.sent.get('Pat')}"
    asked = len(muse.sent["Pat"])
    clock.go(3600); h.tick()
    assert len(muse.sent["Pat"]) == asked, "asked once, not every tick"
    # two hours, no task: an idle agent becomes acting planner
    clock.go(3601); h.tick(); h.tick()
    planners = [n for n in ("Bo", "Cy") if any("planner" in s.lower() for s in muse.sent.get(n, []))]
    assert len(planners) == 1, f"one idle agent gets the planner item: { {n: muse.sent.get(n) for n in ('Bo', 'Cy')} }"
    p = planners[0]
    assert any(p in s and "planning" in s.lower() for s in muse.sent["Pat"]), "the PM is told who is planning"
    out = h.manage(p, f'task add {prj} "Draft 5 portrait styles" designer "5 style samples in a shared folder"')
    tid = int(next(w for w in out.replace("#", " ").split() if w.isdigit()))
    h.tick(); h.tick()
    t = h.task(tid)
    assert t["status"] == "working" and t["owner"] != "Ada", f"the planned task is taken by a free agent (PMs too): {t}"
    # its work taken and the queue empty again: a new round goes to the PM, and the planner's rights end
    h.tick()
    assert len(muse.sent["Pat"]) > asked + 1, "plan: the PM is asked again for the next round"
    try:
        h.manage(p, f'task add {prj} "extra" designer "x"')
        raise AssertionError("plan: the acting planner's rights end when the next round starts")
    except PermissionError:
        pass
    print("planning OK")


def standin():
    h, muse, clock = new_hub("Pericles", "A1", "A2", "A3", "A4", "A5")
    h.add_agent("dot", "slack")
    h.db.execute("insert or replace into seats(role, agent) values('ceo','dot')")
    h.db.execute("insert or replace into seats(role, agent) values('ceo_backup','Pericles')")
    h.tick()                                     # the five workers start counting as free
    h.acted("dot")
    assert h._chair() == "dot"
    clock.go(3 * 3600 + 1)
    assert h._chair() == "Pericles", f"stand: a CEO silent 3 h is stood in for: {h._chair()}"
    clock.go(hub.IDLE_AFTER); h.tick()
    assert any("no task" in i["text"] for i in h.items_for("Pericles")), "the idle note goes to the stand-in"
    h.acted("dot")
    assert h._chair() == "dot", "dot acting takes the seat back"
    print("standin OK")


def slack200():
    import muse
    thread = [{"ts": "1000.000000", "user": "UBOT", "text": "intro"}] + \
             [{"ts": f"{1000 + i}.000000", "user": "UDOT" if i == 250 else "UBOT", "text": f"m{i}"} for i in range(1, 251)]

    def api(method, **p):
        if method == "chat.postMessage":
            return {"ts": "1000.000000"}
        old = float(p.get("oldest") or 0)
        after = [m for m in thread[1:] if float(m["ts"]) > old]
        page = after[:200]
        return {"ok": True, "messages": [thread[0]] + page, "has_more": len(after) > 200}

    t = muse.SlackTransport(lambda: "tok", {"dot": {"user": "UDOT", "channel": "C1"}}, api=api)
    t.READ_EVERY = 0
    t._ts = {"dot": "1000.000000"}
    got = []
    for _ in range(3):
        got = t.replies("dot", 0)
    assert got and got[-1][1] == "m250", f"250: dot's reply past the first 200 messages is read: {got[-3:]}"
    print("slack200 OK")


def planner_not_asker():
    """A product with no PM asks the chair first; when the chair stays silent, someone else plans — not the chair."""
    h, muse, clock = new_hub("Cee", "W1", "W2")
    h.seat("ceo", "Cee")
    h.add_project(h.add_product("Shop", brief="planners"), "launch")
    h.tick(); clock.go(PLAN_WAIT + 1); h.tick()
    planner = [n for n in ("Cee", "W1", "W2") if any("acting planner" in s for s in muse.sent.get(n, []))]
    assert planner and planner != ["Cee"], f"plan: the silent chair isn't its own fallback: {planner}"
    print("planner_not_asker OK")


def pm_review():
    """Jack, Oct 13: a PM can run the company too — new products and the rest. With the CEO around, a company-level
    change goes to the CEO for review and goes ahead if nobody answers in 2 h; while standing in, the PM just acts,
    and the CEO is told what changed when it's back. Board powers (park/wake, granting CEO level) stay out of reach."""
    h, muse, clock = new_hub("Pericles", "Ada")
    h.add_agent("dot", "slack")
    h.seat("ceo", "dot")
    h.db.execute("insert or replace into seats(role, agent) values('ceo_backup','Pericles')")
    h.add_product("Etsy", brief="templates", pm="Pericles")
    h.acted("dot")
    review = lambda: [m for m in muse.sent.get("dot", []) if "review" in m.lower()]
    product = lambda n: h.db.execute("select 1 from products where name=?", (n,)).fetchone()

    out = h.manage("Pericles", 'product add "Pet portraits" "custom pet portraits on Etsy"')
    assert not product("Pet portraits") and "review" in out.lower(), f"review: goes to the CEO first: {out}"
    h.tick()
    assert review() and "Pet portraits" in review()[-1], f"review: dot is asked: {muse.sent.get('dot')}"
    sid = int(re.search(r"#(\d+)", out).group(1))
    h.manage("dot", f"suggestion accept {sid} go")
    assert product("Pet portraits"), "accepted → done"

    out = h.manage("Pericles", 'product add "Mugs" "custom mugs"')
    rej = int(re.search(r"#(\d+)", out).group(1))
    h.manage("dot", f"suggestion reject {rej} not now")
    out = h.manage("Pericles", 'product add "Stickers" "sticker packs"')
    clock.go(2 * 3600 + 1); h.acted("dot"); h.tick()
    assert product("Stickers"), "no answer in 2 h → goes ahead"
    assert not product("Mugs"), "rejected stays rejected"

    try:
        h.manage("Pericles", "grant Ada ceo")
        raise AssertionError("review: a PM can't grant itself or others CEO level")
    except PermissionError:
        pass

    clock.go(3 * 3600 + 1); h.tick()
    told = lambda who, s: [i["text"] for i in h.items_for(who) if s in i["text"].lower()]
    assert told("Pericles", "standing in"), "the stand-in is told it's in charge"
    h.manage("Pericles", 'product add "Prints" "art prints"')
    assert product("Prints"), "standing in: acts directly"
    h.acted("dot"); h.tick()
    back = told("dot", "while you were away")
    assert back and "Prints" in back[-1], f"dot hears what changed: {back}"
    print("pm_review OK")


def powers_told():
    """Whoever's powers change is told what they can do now — whatever changed them (a command, a stand-in
    taking over, a hub update); plain workers whose powers didn't change hear nothing."""
    h, muse, clock = new_hub("Pericles", "Ada")
    h.add_agent("dot", "slack")
    h.seat("ceo", "dot")
    h.db.execute("insert or replace into seats(role, agent) values('ceo_backup','Pericles')")
    h.add_product("Etsy", brief="templates", pm="Pericles")
    h.acted("dot")
    told = lambda who: [i["text"] for i in h.items_for(who) if "what you can do" in i["text"]]
    h.tick(); h.tick()
    assert len(told("Pericles")) == 1 and "review" in told("Pericles")[0], f"powers: the PM learns the review rule: {told('Pericles')}"
    assert len(told("dot")) == 1 and "review" in told("dot")[0], f"powers: the CEO learns it reviews PM changes: {told('dot')}"
    assert not told("Ada"), "a plain worker isn't messaged"
    clock.go(3 * 3600 + 1); h.tick()
    assert len(told("Pericles")) == 2 and "standing in" in told("Pericles")[-1].lower(), told("Pericles")
    h.acted("dot"); h.tick()
    assert len(told("Pericles")) == 3, "and told again when it hands back"
    h.tick()
    assert len(told("Pericles")) == 3, "nothing new, nothing sent"
    print("powers_told OK")


def approvals():
    """Jack, Oct 13: an agent waiting on a Muse permission pop-up froze for 2 h. The hub sees every agent's
    pending approvals, lists them in one place, and Jack allows or denies each with one click."""
    h, muse, clock = new_hub("brutus", "Ada")
    soon = clock() + 3000
    muse.pending["brutus"] = [{"id": "connector-1", "label": "Upload a file and create a public link",
                               "detail": "File: pet-portrait-style-sheet-v2.png", "options": ["allow_once", "deny"], "expires": soon}]
    h.scan_approvals()
    got = h.board()["approvals"]
    assert [(a["agent"], a["id"], a["label"]) for a in got] == [("brutus", "connector-1", "Upload a file and create a public link")], \
        f"approvals: the board lists brutus's pending approval: {got}"
    try:
        h.decide_approval("jack", "brutus", "connector-1", "allow_always")
        raise AssertionError("approvals: only the options Muse offered")
    except ValueError:
        pass
    h.decide_approval("jack", "brutus", "connector-1", "allow_once")
    assert muse.decided == [("brutus", "connector-1", "allow_once")], muse.decided
    assert h.board()["approvals"] == [], "decided → gone"
    assert any("allow_once" in c["result"] or "allowed" in c["result"] for c in h.changes(5)), "logged"
    muse.pending["Ada"] = [{"id": "x", "label": "Open a site", "detail": "", "options": ["allow_once", "deny"], "expires": clock() + 60}]
    h.scan_approvals(); clock.go(61)
    assert h.board()["approvals"] == [], "an expired request isn't shown"
    print("approvals OK")


def paused():
    """Jack, Oct 13: a paused product is kept, but nobody takes its tasks and no new ones can be added."""
    h, muse, clock = new_hub("Ada", "Bo")
    old = h.add_product("Templates", brief="budget templates")
    prj = h.add_project(old, "launch")
    waiting = h.add_task(prj, "extra polish", "engineer", "polished")
    h.manage("jack", 'product set "Templates" status paused')
    h.tick(); h.tick()
    assert h.task(waiting)["owner"] is None and h.task(waiting)["status"] != "working", f"paused: nobody takes its task: {h.task(waiting)}"
    assert not any("extra polish" in s for n in ("Ada", "Bo") for s in muse.sent.get(n, [])), "paused: no switch or task item for it"
    try:
        h.manage("jack", f'task add {prj} "more" engineer "x"')
        raise AssertionError("paused: no new tasks can be added")
    except (ValueError, PermissionError):
        pass
    h.manage("jack", 'product set "Templates" status active')
    h.tick(); h.tick()
    assert h.task(waiting)["status"] == "working", "active again: work flows"
    print("paused OK")


def planner_silent():
    """Oct 13 live: Boboe 1 was made planner for Kids' storybooks, added nothing, and 10+ agents sat idle for
    hours because the next round only came 12 h after the PM was asked. A silent planner gets PLAN_WAIT too."""
    h, muse, clock = new_hub("Pm", "W1", "W2", "W3")
    h.add_project(h.add_product("Shop", brief="planners", pm="Pm"), "launch")
    h.tick(); clock.go(PLAN_WAIT + 1); h.tick()
    asked = lambda: sum("no work lined up" in s for s in muse.sent.get("Pm", []))
    first = asked()
    clock.go(PLAN_WAIT + 1); h.tick(); h.tick()
    assert asked() > first, f"plan: a silent planner's round ends after PLAN_WAIT and the PM is asked again: {muse.sent.get('Pm')}"
    print("planner_silent OK")


def pause_board_only():
    """Jack, Oct 13: only Jack or Darragh pause, resume or remove a product — Pericles paused 2 of 3 and the fleet idled."""
    h, muse, clock = new_hub("Pericles", "Ada")
    h.add_agent("dot", "slack")
    h.seat("ceo", "dot")
    h.add_product("Pets", brief="portraits", pm="Pericles")
    h.add_product("Books", brief="storybooks")
    status = lambda n: h.db.execute("select status from products where name=?", (n,)).fetchone()["status"]
    for who in ("Pericles", "dot"):
        for line in ('product set "Pets" status paused', 'product remove "Books"'):
            try:
                h.manage(who, line)
                raise AssertionError(f"pause: {who} ran {line}")
            except PermissionError:
                pass
    assert status("Pets") == status("Books") == "active", "pause: nothing changed"
    assert not h.db.execute("select 1 from suggestions where line like '%status%' or line like '%remove%'").fetchone(), \
        "pause: not queued for review either"
    assert "review" in h.manage("Pericles", 'product set "Pets" brief "new brief"').lower(), "pause: other edits still go to review"
    h.manage("jack", 'product set "Pets" status paused')
    assert status("Pets") == "paused", "pause: Jack can"
    print("pause_board_only OK")


if __name__ == "__main__":
    {"activity": activity, "truth": truth, "planning": planning, "standin": standin,
     "slack200": slack200, "planner_not_asker": planner_not_asker, "pm_review": pm_review, "powers_told": powers_told, "approvals": approvals, "paused": paused, "planner_silent": planner_silent, "pause_board_only": pause_board_only}[sys.argv[1]]()
