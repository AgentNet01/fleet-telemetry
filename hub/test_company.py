"""Company layer: products, projects, tasks with dependencies, assignment, verify, council.

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
    h, muse, clock = new_hub()
    pid = h.add_product("Templates", brief="Etsy budgeting templates")
    prj = h.add_project(pid, "launch")
    for n, role in (("Ada", "developer"), ("Bea", "designer")):
        h.add_agent(n, "muse")
        h.place(n, pid, role)
    t1 = h.add_task(prj, "build the sheet", role="developer", done_def="a working .xlsx in the repo")
    t2 = h.add_task(prj, "cover image", role="designer", done_def="a 2000px PNG", blocked_by=[t1])

    h.tick()
    assert any("build the sheet" in t for t in muse.sent.get("Ada", [])), "developer task goes to the developer"
    assert "Bea" not in muse.sent, "the blocked design task is not sent"
    assert h.task(t2)["status"] == "blocked", h.task(t2)

    # Ada finishes with evidence; a different agent gets the verify
    answer(h, muse, clock, "Ada", "done. WAKANDA https://github.com/AgentNet01/x/commit/abc")
    assert h.task(t1)["status"] == "verifying", h.task(t1)
    h.tick()
    assert any("verify" in t.lower() and "build the sheet" in t for t in muse.sent.get("Bea", [])), f"verify to a different agent: {muse.sent.get('Bea')}"

    # Bea verifies it passes → t1 done, t2 now ready and assigned to Bea (designer, idle)
    answer(h, muse, clock, "Bea", "checked it against the definition of done — looks right, passes")
    assert h.task(t1)["status"] == "done", h.task(t1)
    h.tick()
    assert any("cover image" in t for t in muse.sent.get("Bea", [])), f"t2 unblocked and assigned once t1 is done: {muse.sent.get('Bea')}"
    assert h.task(t2)["owner"] == "Bea", h.task(t2)

    # a failed verify reopens the task with the reason
    h2, muse2, clock2 = new_hub()
    p = h2.add_product("P", brief="b"); pr = h2.add_project(p, "x")
    for n in ("Cy", "Di"):
        h2.add_agent(n, "muse"); h2.place(n, p, "developer")
    t = h2.add_task(pr, "thing", role="developer", done_def="works")
    h2.tick()
    owner = h2.task(t)["owner"]
    other = "Di" if owner == "Cy" else "Cy"
    answer(h2, muse2, clock2, owner, "WAKANDA https://example.com/evidence")
    h2.tick()
    answer(h2, muse2, clock2, other, "this fails — the numbers don't add up")
    assert h2.task(t)["status"] in ("ready", "open"), f"a failed verify reopens the task: {h2.task(t)}"
    assert "numbers don't add up" in (h2.task(t)["progress_note"] or ""), h2.task(t)
    print("tasks OK")


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


if __name__ == "__main__":
    {"council": council}.get(sys.argv[1] if len(sys.argv) > 1 else "", tasks)()
