"""Autonomy: the hub sees what agents really do, tasks tell the truth, and work never runs dry.

    python3 test_autonomy.py activity   # Muse mid-turn / last action → board, and it counts as acting
    python3 test_autonomy.py truth      # blocked work frees its holder; owned work starts when it can
    python3 test_autonomy.py planning   # PM asked, then an idle agent plans, its task gets taken
    python3 test_autonomy.py standin    # a silent CEO is stood in for, and gets the seat back by acting
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
    hub.TASK_CAP = 10 ** 9        # its tasks sit held for hours by design; the cap is tested in overdue
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


def auto_approve():
    """Jack, Oct 13: auto-approve lived in the Muse wall on his Mac, so nothing was allowed while it slept.
    The hub allows every pop-up itself, around the clock, with the broadest allow Muse offers, and logs it."""
    h, muse, clock = new_hub("Boboe 3", "Neo")
    h.auto_approve = True
    muse.pending["Boboe 3"] = [{"id": "a1", "label": "Shell command", "detail": "endpoint cas-server.xethub.hf.co:443",
                                "options": ["allow_once", "allow_always", "deny"], "expires": clock() + 600}]
    muse.pending["Neo"] = [{"id": "a2", "label": "Upload a file and create a public link", "detail": "",
                            "options": ["allow_once", "deny"], "expires": clock() + 600}]
    h.scan_approvals()
    assert sorted(muse.decided) == [("Boboe 3", "a1", "allow_always"), ("Neo", "a2", "allow_once")], muse.decided
    assert h.board()["approvals"] == [], "auto_approve: nothing left waiting"
    assert any(c["by"] == "hub" and "Shell command" in c["line"] for c in h.changes(5)), "auto_approve: logged as the hub's"
    print("auto_approve OK")


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


def overdue():
    """Jack, Oct 15: Boboe 6 held "Hats Etsy Ads test launch" 5h35m and Boboe 8 a "7-day monitoring log" 5h, each posting
    "still blocked" notes, so no nudge ever fired. A task held past TASK_CAP is parked for its PM and its holder is freed."""
    h, muse, clock = new_hub("Ada", "Bo", "Pam")
    pid = h.add_product("Hats", brief="hats")
    h.db.execute("update products set pm='Pam' where id=?", (pid,))
    pa = h.add_project(pid, "launch")
    ads = h.add_task(pa, "Hats Etsy Ads test launch", "marketer", "campaign live", owner="Ada")
    h.tick(); h.tick()
    assert h.task(ads)["status"] == "working", h.task(ads)
    for _ in range(int(hub.TASK_CAP // 1800) - 1):       # busy-looking: a note every half hour
        clock.go(1800)
        h.task_note("Ada", ads, "still blocked on ad budget")
        h.tick()
    h.task_note("Ada", ads, "Jack declined the $34.80 test order, so ads wait on a new plan")   # Oct 16: this note crashed every tick
    assert h.task(ads)["status"] == "working", "overdue: not parked before the cap"
    clock.go(1800)
    h.tick(); h.tick()
    t = h.task(ads)
    assert t["status"] == "blocked" and t["owner"] is None and t["waiting_on"] == "Pam", f"overdue: parked for the PM: {t}"
    assert any(f"#{ads}" in s and "Stop work on it" in s for s in muse.sent.get("Ada", [])), "overdue: the holder knows to stop"
    told = [s for s in muse.sent.get("Pam", []) if f"#{ads}" in s]
    assert told and "Jack declined" in told[-1] and "split" in told[-1], f"overdue: the PM hears why and what to do: {told}"
    clock.go(4 * 3600); h.tick(); h.tick()
    assert sum(f"#{ads}" in s and "Hats Etsy Ads" in s for s in muse.sent.get("Pam", [])) == 1, "overdue: told once"
    print("overdue OK")


def ask_up():
    """Jack, Oct 15: "Can we also not have side chats?" One agent's `fleet ask all` reached ~25 agents and every answer
    then queued on the CEO as chair. An agent's question for everyone goes to its PM (a PM's to the CEO), once."""
    h, muse, clock = new_hub("Ada", "Bo", "Cy", "Pam", "Ceo")
    h.seat("ceo", "Ceo")
    pid = h.add_product("Hats", brief="hats")
    h.set_pm("Hats", "Pam")
    h.place("Ada", pid, "marketer")
    h.ask_up("Ada", "how do I reactivate the listing?")
    h.ask_up("Pam", "who owns the ads budget?")
    h.tick(); h.tick()
    assert not h.db.execute("select count(*) from councils").fetchone()[0], "ask_up: no fleet-wide council"
    assert not any("reactivate" in s for n in ("Bo", "Cy", "Ceo") for s in muse.sent.get(n, [])), "ask_up: nobody else is asked"
    assert any("reactivate" in s for s in muse.sent.get("Pam", [])), f"ask_up: Ada's PM gets it: {muse.sent.get('Pam')}"
    assert any("ads budget" in s for s in muse.sent.get("Ceo", [])), "ask_up: a PM's question goes to the CEO"
    print("ask_up OK")


def wait():
    """Jack, Oct 13: Boboe 4 sat on #5 for hours "awaiting Gate 1 / Darragh's release", nudged hourly, taking nothing
    else. An agent waiting on someone parks the task and takes any product's work; the task comes back to it later."""
    h, muse, clock = new_hub("Ada", "Bo")
    pa = h.add_project(h.add_product("Pets", brief="portraits"), "launch")
    pb = h.add_project(h.add_product("Books", brief="storybooks"), "launch")
    posts = h.add_task(pa, "launch posts", "marketer", "posted", owner="Ada")
    h.tick(); h.tick()
    assert h.task(posts)["owner"] == "Ada" and h.task(posts)["status"] == "working", h.task(posts)

    h.task_wait("Ada", posts, "jack", "publish OK for the listing")
    h.tick(); h.tick()
    t = h.task(posts)
    assert t["status"] == "blocked" and t["owner"] is None and t["pin"] == "Ada", f"wait: on hold, kept for Ada: {t}"
    need = [n for n in h.needs_jack() if f"#{posts}" in n["text"]]
    assert need and "publish OK" in need[0]["text"], f"wait: Jack sees what it's waiting on: {h.needs_jack()}"
    other = h.add_task(pb, "story drafts", "marketer", "drafted")
    h.tick(); h.tick(); h.tick()
    assert h.task(other)["owner"] == "Ada" or h.task(other)["owner"] == "Bo", h.task(other)
    clock.go(6 * 3600); h.tick()
    assert not any("No progress posted" in s and "launch posts" in s for s in muse.sent.get("Ada", [])), \
        "wait: no nudges about a task on hold"

    h.resolve_need(need[0]["id"])                      # Jack clicks done on his list
    for _ in range(3):
        h.tick()
    t = h.task(posts)
    assert t["waiting_on"] is None and (t["owner"] == "Ada" or t["pin"] == "Ada"), f"wait: cleared, back to Ada: {t}"
    assert t["owner"] in (None, "Ada"), "wait: never handed to someone else"

    # waiting on another agent: that agent is asked; the waiter (or the asked agent) resumes it
    h.db.execute("update tasks set status='done' where id=?", (other,))
    for _ in range(3):
        h.tick()
    assert h.task(posts)["owner"] == "Ada", h.task(posts)
    h.task_wait("Ada", posts, "Bo", "the final caption")
    h.tick(); h.tick()
    assert any("final caption" in s for s in muse.sent.get("Bo", [])), f"wait: Bo is asked: {muse.sent.get('Bo')}"
    h.task_resume("Bo", posts)
    for _ in range(3):
        h.tick()
    assert h.task(posts)["owner"] == "Ada" and h.task(posts)["status"] == "working", h.task(posts)
    try:
        h.task_wait("Bo", posts, "jack", "x")
        raise AssertionError("wait: only the holder parks its task")
    except PermissionError:
        pass
    h.task_wait("Ada", posts, "jack", "sign-off")
    t = h.task(posts)
    assert t["status"] == "blocked" and t["owner"] is None, f"wait: freed at once, not next tick: {t}"
    try:
        h.task_done("Ada", posts, "https://x")
        raise AssertionError("wait: a parked task can't be marked done by its old holder")
    except PermissionError:
        pass
    h.manage("jack", f"task release {posts}")
    assert h.task(posts)["waiting_on"] is None and not [n for n in h.needs_jack() if "sign-off" in n["text"]], \
        "wait: released → the wait and Jack's row end"
    print("wait OK")


def pause_frees():
    """A paused product's held task goes on hold and frees its holder; resumed, it comes back to the same agent."""
    h, muse, clock = new_hub("Ada")
    prj = h.add_project(h.add_product("Templates", brief="budget"), "launch")
    t = h.add_task(prj, "posts", "marketer", "posted", owner="Ada")
    h.tick(); h.tick()
    assert h.task(t)["owner"] == "Ada"
    h.manage("jack", 'product set "Templates" status paused')
    h.tick()
    assert h.task(t)["owner"] is None and h.task(t)["pin"] == "Ada", f"pause: holder freed, task kept for it: {h.task(t)}"
    assert any("paused" in s.lower() and "posts" in s for s in muse.sent.get("Ada", [])), "pause: the holder is told why"
    h.manage("jack", 'product set "Templates" status active')
    h.tick(); h.tick()
    assert h.task(t)["owner"] == "Ada" and h.task(t)["status"] == "working", h.task(t)
    print("pause_frees OK")


def switch_edit():
    """Oct 13 live: a role's text was edited between a switch being issued and the agent loading it; the agent loaded
    exactly what the hub served, yet it was flagged as a bad switch on Jack's list."""
    import hashlib
    h, muse, clock = new_hub("Ada")
    h.add_product("Cups", brief="cups")
    h.issue_switch("Ada", "Cups", "designer")
    h.db.execute("update roles set soul = soul || ' Images are the deliverable.' where name='designer'")
    b = h.brain_for("Ada")
    got = hashlib.sha256((b["soul"] + "\n" + b["memory"]).encode()).hexdigest()
    assert h.record_switch("Ada", "Cups", "designer", got), "switch: what the hub served counts as a good load"
    assert not h.needs_jack(), f"switch: nothing for Jack: {h.needs_jack()}"
    h.issue_switch("Ada", "Cups", "marketer")
    assert not h.record_switch("Ada", "Cups", "marketer", "bad"), "switch: a real mismatch is still caught"
    print("switch_edit OK")


def unjoined():
    """Oct 14 live: Boboe 13's login was on the hub but it hadn't joined; it was handed a verify and a switch, and
    refused both (no fleet CLI on its machine). Work waits for an agent that has joined."""
    h, muse, clock = new_hub("Ada")
    h.db.execute("insert or ignore into agents(name, kind) values('Boboe 13', 'muse')")
    assert list(h._idle()) == ["Ada"], list(h._idle())
    print("unjoined OK")


def chain():
    """Oct 13 live: each product was one chain (scan → concept → designs → package); with only the current step
    takeable, most agents sat free and no planning ran because the chain's later steps counted as queued."""
    h, muse, clock = new_hub("Pm", "Ada", "Bo", "Cy")
    prj = h.add_project(h.add_product("Cups", brief="cups", pm="Pm"), "launch")
    scan = h.add_task(prj, "scan", "optimizer", "doc", owner="Ada")
    h.add_task(prj, "concept", "marketer", "doc", blocked_by=[scan])
    h.tick(); h.tick()
    assert any("no work lined up" in m for m in muse.sent.get("Pm", [])), \
        f"chain: only blocked work left + free agents → the PM is asked for parallel work: {muse.sent.get('Pm')}"
    print("chain OK")


def live_done():
    """Jack, Oct 20: every product with a live listing was planned again every 2 h, so agents filled them with docs,
    audits and Pinterest batch 31. A live listing gets one ask to start a NEW product, and never an acting planner."""
    h, muse, clock = new_hub("Pm", "Ada", "Bo")
    pid = h.add_product("Cups", brief="cups", pm="Pm")
    h.add_project(pid, "launch")
    h.db.execute("update products set listing_state='active', link='https://www.etsy.com/listing/1' where id=?", (pid,))
    h.tick(); h.tick()
    told = muse.sent.get("Pm", [])
    assert any("is live on Etsy" in m and "NEW product" in m for m in told), f"live: the PM is pointed at new products: {told}"
    assert not any("no work lined up" in m for m in told), f"live: no ask to plan more for it: {told}"
    clock.go(3 * 3600); h.tick(); h.tick()
    assert not any("acting planner" in m for n in ("Ada", "Bo") for m in muse.sent.get(n, [])), "live: no acting planner"
    assert len(muse.sent.get("Pm", [])) == len(told), "live: asked once per round, not every tick"
    # taken down: one ask to get it live again, still no acting planner; a shared tool is never planned
    h.db.execute("update products set listing_state='inactive' where id=?", (pid,))
    h.db.execute("delete from dry_notes")
    tool = h.add_product("Fulfillment", brief="ship orders", pm="Pm")
    h.add_project(tool, "ops")
    h.db.execute("update products set kind='tool' where id=?", (tool,))
    h.tick(); h.tick()
    assert any("is inactive" in m and "live again" in m for m in muse.sent.get("Pm", [])), f"live: taken down: {muse.sent.get('Pm')}"
    clock.go(3 * 3600); h.tick(); h.tick()
    assert not any("acting planner" in m for n in ("Ada", "Bo") for m in muse.sent.get(n, [])), "taken down: no acting planner"
    assert not [m for m in muse.sent.get("Pm", []) if "Fulfillment" in m and ("no work lined up" in m or "is live" in m)], \
        f"a shared tool isn't planned on its own: {[m[:120] for m in muse.sent.get('Pm', []) if 'Fulfillment' in m]}"
    print("live_done OK")


def scout():
    """Jack, Oct 20: "if they're blocked like that why don't they go research and discover new products?" A free
    agent with nothing to take is sent to find and post one, once per PLAN_WAIT; a busy agent and the chair aren't."""
    h, muse, clock = new_hub("Cee", "Ada", "Bo")
    h.seat("ceo", "Cee")
    prj = h.add_project(h.add_product("Cups", brief="cups", pm="Cee"), "launch")
    h.add_task(prj, "busy", "engineer", "x", owner="Bo")
    h.tick()
    scouts = lambda n: [m for m in muse.sent.get(n, []) if hub.Hub.SCOUT in m]
    assert not scouts("Ada"), "scout: not the moment an agent goes free"
    clock.go(hub.SCOUT_AFTER + 1); h.tick(); h.tick()
    assert len(scouts("Ada")) == 1 and "Cups" in scouts("Ada")[0] and "under $10" in scouts("Ada")[0], muse.sent.get("Ada")
    assert not scouts("Bo"), "scout: a busy agent keeps its task"
    clock.go(3600); h.tick()
    assert len(scouts("Ada")) == 1, "scout: once per PLAN_WAIT, not every tick"
    clock.go(hub.PLAN_WAIT); h.tick(); h.tick()
    assert len(scouts("Ada")) == 2, "scout: again while it stays free"
    print("scout OK")


def desk():
    """Jack, Oct 26: six agents become sports research pods (NBA, NFL, college football), walled off from the Etsy
    company. An agent on a desk is never handed a task, sent scouting, counted idle or asked to vote; the rest work as usual."""
    h, muse, clock = new_hub("Cee", "Ada", "Nb")
    h.seat("ceo", "Cee")
    assert "nba" in h.manage("Cee", "team Nb nba") and h._agent("Nb")["team"] == "nba"
    prj = h.add_project(h.add_product("Cups", brief="cups", pm="Cee"), "launch")
    t1 = h.add_task(prj, "mockups", "designer", "x")
    clock.go(hub.ANY_FIT_AFTER + 1); h.tick(); h.tick()
    owner = lambda t: h.db.execute("select owner from tasks where id=?", (t,)).fetchone()["owner"]
    assert owner(t1) == "Ada", f"desk: the Etsy agent takes the task, got {owner(t1)}"
    t2 = h.add_task(prj, "copy", "marketer", "x")
    clock.go(hub.SCOUT_AFTER + hub.ANY_FIT_AFTER + 1); h.tick(); h.tick()
    assert owner(t2) != "Nb", "desk: a desk agent is never handed Etsy work, even with nobody else free"
    assert not [m for m in muse.sent.get("Nb", []) if hub.Hub.SCOUT in m or "no work lined up" in m], muse.sent.get("Nb")
    assert "Nb" not in h._responders(), "desk: a desk agent doesn't vote on company councils"
    print("desk OK")


def board_shared():
    """Oct 26: a board build outlasted the dashboard's 10 s poll, requests queued without end and every page went
    blank. Viewers asking at once share one build; a fresh one comes only after BOARD_TTL."""
    import threading, time as _t
    h, muse, clock = new_hub("Ada")
    builds, real = [], h.board
    def slow():
        builds.append(1); _t.sleep(0.3); return real()
    h.board = slow
    ts = [threading.Thread(target=h.board_shared) for _ in range(5)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(builds) == 1, f"board_shared: 5 viewers at once, {len(builds)} builds"
    h.board_shared()
    assert len(builds) == 1, "board_shared: reused within BOARD_TTL"
    clock.go(hub.BOARD_TTL + 1); h.board_shared()
    assert len(builds) == 2, "board_shared: rebuilt after BOARD_TTL"
    print("board_shared OK")


if __name__ == "__main__":
    {"activity": activity, "truth": truth, "planning": planning, "standin": standin,
     "planner_not_asker": planner_not_asker, "pm_review": pm_review, "powers_told": powers_told, "approvals": approvals, "auto_approve": auto_approve, "paused": paused, "planner_silent": planner_silent, "pause_board_only": pause_board_only, "wait": wait, "ask_up": ask_up, "overdue": overdue, "pause_frees": pause_frees, "switch_edit": switch_edit, "chain": chain, "unjoined": unjoined, "live_done": live_done, "scout": scout, "desk": desk, "board_shared": board_shared}[sys.argv[1]]()
