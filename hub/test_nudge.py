"""Nudges keep task holders moving without repeating themselves; the CEO owns inactivity.

    python3 test_nudge.py              # every case
    python3 test_nudge.py <case>       # cadence rotate content idle_silent reset
                                       # ceo_threshold ceo_once ceo_only ceo_parked
"""
import os
import sys
import tempfile

import hub
from test_hub import Clock, FakeMuse

H = 3600

hub.TASK_CAP = 10 ** 9        # these cases hold a task silently for hours on purpose; the cap is test_autonomy overdue


def world(workers=("Ada",)):
    clock, muse = Clock(), FakeMuse()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), muse, clock, evidence_ok=lambda link: True)
    pid = h.add_product("Shop", brief="b")
    prj = h.add_project(pid, "launch")
    for n in workers:
        h.add_agent(n, "muse"); h.place(n, "Shop", "engineer")
    return h, muse, clock, prj


def nudges(muse, agent, title):
    """Messages after the task itself that mention the task."""
    return [m for m in muse.sent.get(agent, []) if title in m][1:]


def hours(h, clock, n):
    for _ in range(n):
        clock.go(H); h.tick()


def cadence():
    h, muse, clock, prj = world()
    h.add_task(prj, "write the listing", role="engineer", done_def="x")
    h.tick()
    clock.go(55 * 60); h.tick()
    assert nudges(muse, "Ada", "write the listing") == [], "nudge: none before an hour of silence"
    clock.go(6 * 60); h.tick()
    assert len(nudges(muse, "Ada", "write the listing")) == 1, "nudge: exactly one after an hour"
    clock.go(55 * 60); h.tick()
    assert len(nudges(muse, "Ada", "write the listing")) == 1, "nudge: not again within the hour"
    clock.go(6 * 60); h.tick()
    assert len(nudges(muse, "Ada", "write the listing")) == 2, "nudge: again after another silent hour"
    print("cadence OK")


def rotate():
    h, muse, clock, prj = world()
    h.add_task(prj, "write the listing", role="engineer", done_def="x")
    h.tick()
    hours(h, clock, 5)
    got = nudges(muse, "Ada", "write the listing")
    assert len(got) == 5, f"nudge: five in 5 silent hours, got {len(got)}"
    firsts = [m.splitlines()[0] for m in got]
    assert all(a != b for a, b in zip(firsts, firsts[1:])), f"nudge: never the same wording twice in a row: {firsts}"
    assert len(set(firsts[:4])) == 4, f"nudge: four different phrasings: {firsts}"
    print("rotate OK")


def content():
    h, muse, clock, prj = world()
    t = h.add_task(prj, "write the listing", role="engineer", done_def="x")
    h.tick()
    hours(h, clock, 1)
    n = nudges(muse, "Ada", "write the listing")[0]
    for part in (f"#{t}", "write the listing", "Shop", "engineer", "fleet task"):
        assert part in n, f"nudge: missing {part!r} in {n!r}"
    print("content OK")


def idle_silent():
    h, muse, clock, prj = world()
    h.tick()
    hours(h, clock, 48)
    # Jack, Oct 20: the one thing it may get is work, the find-a-new-product item
    chatter = [m for m in muse.sent.get("Ada", []) if hub.Hub.SCOUT not in m]
    assert not chatter, f"nudge: an agent with no task is never messaged except with work: {chatter}"
    print("idle_silent OK")


def reset():
    h, muse, clock, prj = world()
    t = h.add_task(prj, "write the listing", role="engineer", done_def="x")
    h.tick()
    clock.go(50 * 60); h.tick()
    h.task_note("Ada", t, "draft done")
    clock.go(50 * 60); h.tick()
    assert nudges(muse, "Ada", "write the listing") == [], "nudge: a progress note restarts the hour"
    clock.go(15 * 60); h.tick()
    assert len(nudges(muse, "Ada", "write the listing")) == 1, "nudge: an hour after the note"
    print("reset OK")


def escalate():
    """Still silent an hour after the reminder: the PM (or the CEO when there's no PM) is told, once per stretch."""
    h, muse, clock, prj = world(workers=("Ada", "Pam", "Cee"))
    h.seat("ceo", "Cee"); h.set_pm("Shop", "Pam")
    t = h.add_task(prj, "write the listing", role="engineer", done_def="x", owner=None)
    h.manage("jack", f"task set {t} owner Ada")
    h.tick()
    pm = lambda: [m for m in muse.sent.get("Pam", []) if "write the listing" in m and "silent" in m]
    hours(h, clock, 1)
    assert pm() == [], "one silent hour: only the holder is reminded"
    hours(h, clock, 1)
    assert len(pm()) == 1 and "Ada" in pm()[0], "two silent hours: the PM hears"
    hours(h, clock, 3)
    assert len(pm()) == 1, "the PM is told once per silent stretch, not every hour"
    h.task_note("Ada", t, "back on it")
    hours(h, clock, 2)
    assert len(pm()) == 2, "a new silent stretch tells the PM again"
    h.set_pm("Shop", None)
    h.task_note("Ada", t, "still going")
    hours(h, clock, 2)
    assert any("write the listing" in m and "silent" in m for m in muse.sent.get("Cee", [])), "no PM: the CEO hears"
    print("escalate OK")


def ceo_world(n_idle, parked=0):
    h, muse, clock, prj = world(workers=())
    h.add_agent("Cee", "muse"); h.seat("ceo", "Cee")
    names = [f"W{i}" for i in range(1, n_idle + parked + 1)]
    for n in names:
        h.add_agent(n, "muse")
    for n in names[n_idle:]:
        h._set("agents", n, state="parked")
    h.tick()
    return h, muse, clock, names


def ceo_threshold():
    h, muse, clock, names = ceo_world(4)
    hours(h, clock, 13)
    notes = [m for m in muse.sent.get("Cee", []) if "no task for over" in m]
    assert len(notes) == 1 and all(n in notes[0] for n in names), f"CEO: one note naming all four idle agents: {notes}"
    h3, muse3, clock3, _ = ceo_world(3)
    hours(h3, clock3, 13)
    assert not [m for m in muse3.sent.get("Cee", []) if "no task for over" in m], f"CEO: three idle agents is not a problem yet: {muse3.sent.get('Cee')}"
    print("ceo_threshold OK")


def ceo_once():
    h, muse, clock, names = ceo_world(4)
    hours(h, clock, 13)
    hours(h, clock, 11)
    assert len([m for m in muse.sent.get("Cee", []) if "no task for over" in m]) == 1, "CEO: not re-notified about the same idle stretch"
    hours(h, clock, 1)
    assert len([m for m in muse.sent.get("Cee", []) if "no task for over" in m]) == 2, "CEO: reminded once 12 more hours pass"
    print("ceo_once OK")


def ceo_shrink():
    """Oct 13: work landing shrank the idle set every few minutes and each change re-notified the chair."""
    h, muse, clock, names = ceo_world(6)
    hours(h, clock, 13)
    h._set("agents", "W1", state="parked")              # one fewer idle: good news, no new note
    hours(h, clock, 1)
    told = [i for i in h.items_for("Cee") if "no task for over" in i["text"]]
    assert len(told) == 1, f"CEO: a shrinking idle set isn't re-sent: {[i['text'][:40] for i in told]}"
    print("ceo_shrink OK")


def ceo_only():
    h, muse, clock, names = ceo_world(5)
    hours(h, clock, 30)
    # Jack, Oct 13: no check-ins — the one thing an idle agent may get is work: the acting-planner item
    chatter = [m for n in names for m in muse.sent.get(n, []) if "acting planner" not in m and "switch to" not in m and hub.Hub.SCOUT not in m]
    assert not chatter, f"CEO: idle agents themselves are never messaged except with work: {chatter}"
    print("ceo_only OK")


def ceo_parked():
    h, muse, clock, names = ceo_world(3, parked=2)
    hours(h, clock, 13)
    assert not [m for m in muse.sent.get("Cee", []) if "no task for over" in m], "CEO: parked agents don't count as idle"
    print("ceo_parked OK")


CASES = [cadence, rotate, content, idle_silent, reset, escalate, ceo_threshold, ceo_once, ceo_shrink, ceo_only, ceo_parked]

if __name__ == "__main__":
    pick = sys.argv[1] if len(sys.argv) > 1 else None
    for case in CASES:
        if pick in (None, case.__name__):
            case()
