"""Reliability fixes from the Oct 8 review: nothing strands on failure; ask-all is idempotent.

    python3 test_reliability.py
"""
import os
import tempfile

import hub
from test_hub import Clock, FakeMuse


def new_hub():
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    return h, h.transport, h.clock


def stranding():
    # a task whose owner goes silent isn't stranded: it's never taken away on a timer (long tasks are
    # normal — company_spec G1), the owner is nudged after 12 h, and Jack/PM/CEO can release it
    h, muse, clock = new_hub()
    p = h.add_product("P", brief="b"); pr = h.add_project(p, "x")
    h.add_agent("Zoe", "muse"); h.place("Zoe", "P", "engineer")
    t = h.add_task(pr, "build", role="engineer", done_def="works")
    h.tick()
    assert h.task(t)["owner"] == "Zoe" and h.task(t)["status"] == "working", h.task(t)
    clock.go(22 * 60); h.tick()
    assert h.task(t)["owner"] == "Zoe", f"not released after 22 min: {h.task(t)}"
    clock.go(12 * 3600); h.tick()
    assert h.task(t)["owner"] == "Zoe" and any("build" in m for m in muse.sent["Zoe"][1:]), \
        f"a silent owner is nudged, not stripped of the task: {muse.sent['Zoe']}"
    h.task_release("jack", t)
    assert h.task(t)["status"] == "ready" and h.task(t)["owner"] is None, h.task(t)

    # a chair that never answers resolves the council instead of stranding the asker
    h2, muse2, clock2 = new_hub()
    p2 = h2.add_product("Q", brief="b"); h2.place("Chip", "Q", "pm")
    h2.add_agent("Chip", "muse"); h2.seat("ceo", "Chip")
    h2.add_agent("Ava", "muse"); h2.place("Ava", "Q", "developer")
    cid = h2.ask_all("Ava", "ship?")
    def answer(agent, text):
        muse2.say(agent, text); h2.tick(); clock2.go(61); h2.tick()
    answer("Ava", "yes"); answer("Chip", "yes")      # all views in → the chair gets the chair item
    for _ in range(5):                                 # chair stays silent; resend then give up
        clock2.go(11 * 60); h2.tick()
    assert h2.council(cid)["status"] == "answered", f"a silent chair still resolves: {h2.council(cid)}"
    print("stranding OK")


def idempotent_ask_all():
    h, muse, clock = new_hub()
    h.add_agent("Al", "muse"); h.add_agent("Bo", "muse")
    first = h.ask_all("Al", "colour?", key="abc123")
    again = h.ask_all("Al", "colour?", key="abc123")      # an outbox replay with the same key
    assert first == again, "same key returns the same council"
    assert len(h.councils()) == 1, f"no duplicate council on replay: {len(h.councils())}"
    print("idempotent OK")


def transient_errors_dont_page():
    # a single network blip must not reach Jack; only sustained failure does, and only once.
    h, muse, clock = new_hub()
    open_items = lambda: h.db.execute("select text from needs_jack where done=0").fetchall()
    def boom():
        raise RuntimeError("curl_cffi perform")
    h._guarded("X", boom)
    assert not open_items(), "one transient failure must not page Jack"
    for _ in range(hub.Hub.FAIL_ESCALATE):
        h._guarded("X", boom)
    rows = open_items()
    assert len(rows) == 1 and "X" in rows[0]["text"], f"sustained failure pages once: {rows}"
    for _ in range(4):
        h._guarded("X", boom)                   # still stuck
    assert len(open_items()) == 1, "a stuck agent pages once, not every tick"
    h._guarded("X", lambda: None)               # recovers
    assert h._fails.get("X", 0) == 0, "recovery resets the counter"
    print("transient OK")


if __name__ == "__main__":
    stranding()
    idempotent_ask_all()
    transient_errors_dont_page()
