"""Brain switch driven by the hub: issue → agent fetches → agent reports hashes → verify.

The real file moves were proven live on Boboe 2 (hub_plan.md §6). Here we pin the hub side:
it issues a switch when a ready task needs a product/role the agent isn't in, serves the target
brain, verifies the reported hash, and raises Needs Jack on a mismatch.

    python3 test_switch.py
"""
import hashlib
import os
import tempfile

import hub
from test_hub import Clock, FakeMuse


def reported_hash(brain):
    return hashlib.sha256((brain["soul"] + "\n" + brain["memory"]).encode()).hexdigest()


def main():
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    muse = h.transport
    h.set_role("developer", "You are the developer. Build it and give exact evidence.")
    p = h.add_product("Stickers", brief="AI vinyl stickers on Etsy")
    prj = h.add_project(p, "launch")
    h.add_agent("Ace", "muse")
    h.place("Ace", "Idle Pool", "none")                           # not yet on Stickers/developer
    t = h.add_task(prj, "build the listing script", role="developer", done_def="script runs")

    h.tick()
    assert any("fleet switch" in t and "Stickers" in t and "developer" in t for t in muse.sent.get("Ace", [])), \
        f"a switch is issued to fill the task: {muse.sent.get('Ace')}"
    assert h.task(t)["owner"] is None, "not assigned until the switch lands"

    brain = h.brain_for("Ace")
    assert brain["product"] == "Stickers" and brain["role"] == "developer", brain
    assert "developer" in brain["soul"].lower() and "Etsy" in brain["memory"], brain
    assert h.transport.session("Ace") == h.transport.session("Ace"), "one fleet side chat per agent"

    h.record_switch("Ace", "Stickers", "developer", reported_hash(brain))
    agent = {a["name"]: a for a in h.board()["agents"]}["Ace"]
    assert agent["product"] == "Stickers" and agent["role"] == "developer", agent
    assert not h.needs_jack(), "a matching hash is a clean switch"

    h.tick()
    assert h.task(t)["owner"] == "Ace", "the task is assigned once the agent is in the right brain"

    # a mismatched hash is caught and does not change the agent's brain
    h.add_product("Pets", brief="pet portraits")
    h.set_role("marketing", "You are marketing. Reach people.")
    h.issue_switch("Ace", "Pets", "marketing")
    h.record_switch("Ace", "Pets", "marketing", "deadbeef" * 8)
    agent = {a["name"]: a for a in h.board()["agents"]}["Ace"]
    assert agent["product"] == "Stickers", f"a bad switch leaves the brain alone: {agent}"
    assert any("Ace" in n["text"] and "hash" in n["text"].lower() for n in h.needs_jack()), h.needs_jack()
    print("switch OK")


if __name__ == "__main__":
    main()
