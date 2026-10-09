"""Brain switch driven by the hub: issue → agent fetches → agent reports hashes → verify.

The real file moves were proven live on Boboe 2 (hub_plan.md §6). Here we pin the hub side:
it issues a switch when a ready task needs a product/role the agent isn't in, serves the target
brain, verifies the reported hash, and raises Needs Jack on a mismatch.

    python3 test_switch.py                       # hub side: issue, serve, verify, mismatch
    python3 test_switch.py identity|core|roundtrip   # agent side: the real `fleet switch` on a temp home
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


CORE = "# Soul\nYou serve the fleet. Your role and product memory switch between tasks; nothing is deleted.\n"


def agent_home():
    """A live hub, and an agent home on product A as engineer with its own identity, soul, memory."""
    import test_fleet
    h, srv, port, tok = test_fleet.start()
    h.set_role("engineer", "You are the engineer. Build it.")
    h.set_role("marketer", "You are the marketer. Reach people.")
    h.add_product("A", brief="A starter brief"); h.add_product("B", brief="B starter brief")
    tok["Ace"] = h.add_agent("Ace", "muse"); h.place("Ace", "A", "engineer")
    home = tempfile.mkdtemp()
    files = {"IDENTITY.md": "# Ace\nname: Ace\n", "SOUL.md": CORE, "MEMORY.md": "A: buyers like green\n"}
    for f, text in files.items():
        open(os.path.join(home, f), "w").write(text)
    os.makedirs(os.path.join(home, "memory")); open(os.path.join(home, "memory", "a-notes.md"), "w").write("A notes\n")

    def switch(product, role):
        import subprocess, sys
        h.issue_switch("Ace", product, role)
        env = dict(os.environ, HOME=home, FLEET_HUB=f"http://127.0.0.1:{port}", FLEET_TOKEN=tok["Ace"],
                   FLEET_HOME=os.path.join(home, ".fleet"))
        r = subprocess.run([sys.executable, os.path.join(os.path.dirname(hub.__file__), "fleet.py"), "switch", product, role],
                           env=env, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r
        return r
    read = lambda *p: open(os.path.join(home, *p)).read()
    return h, srv, home, files, switch, read


def identity():
    h, srv, home, files, switch, read = agent_home()
    switch("B", "marketer"); switch("A", "engineer")
    assert read("IDENTITY.md") == files["IDENTITY.md"], "IDENTITY.md never changes"
    srv.shutdown(); print("identity OK")


def core():
    h, srv, home, files, switch, read = agent_home()
    switch("B", "marketer")
    soul = read("SOUL.md")
    assert soul.startswith(CORE), f"the soul core is kept as is: {soul!r}"
    assert "You are the marketer" in soul and "engineer" not in soul, f"only the role block changes: {soul!r}"
    switch("A", "engineer")
    soul = read("SOUL.md")
    assert soul.startswith(CORE) and soul.count("<!-- fleet-role -->") == 1, f"one role block, core intact: {soul!r}"
    assert "You are the engineer" in soul and "marketer" not in soul, soul
    srv.shutdown(); print("core OK")


def roundtrip():
    h, srv, home, files, switch, read = agent_home()
    switch("B", "marketer")
    assert os.path.exists(os.path.join(home, "fleet-brains", "A", "MEMORY.md")), "A's memory saved under ~/fleet-brains/A"
    assert read("fleet-brains", "A", "MEMORY.md") == files["MEMORY.md"]
    assert "B starter brief" in read("MEMORY.md"), "first time on B: the starter brief"
    assert not os.path.exists(os.path.join(home, "memory", "a-notes.md")), "A's notes don't leak into B"
    open(os.path.join(home, "MEMORY.md"), "w").write("B: ship on Fridays\n")
    switch("A", "engineer")
    assert read("MEMORY.md") == files["MEMORY.md"], f"back on A, A's memory exactly: {read('MEMORY.md')!r}"
    assert read("memory", "a-notes.md") == "A notes\n", "A's memory folder comes back"
    assert read("fleet-brains", "B", "MEMORY.md") == "B: ship on Fridays\n", "B's memory kept for next time"
    agent = {a["name"]: a for a in h.board()["agents"]}["Ace"]
    assert agent["product"] == "A" and agent["role"] == "engineer" and not h.needs_jack(), (agent, h.needs_jack())
    srv.shutdown(); print("roundtrip OK")


if __name__ == "__main__":
    import sys
    {"identity": identity, "core": core, "roundtrip": roundtrip}.get(sys.argv[1] if len(sys.argv) > 1 else "", main)()
