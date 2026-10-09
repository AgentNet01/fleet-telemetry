"""An agent's very first switch (no product yet) keeps the memory it already had, once, in
~/fleet-brains/_original; a later unplaced switch never overwrites it.

    python3 test_first_switch.py
"""
from test_switch import agent_home


def main():
    h, srv, home, files, switch, read = agent_home()
    h.place("Ace", None, None)
    switch("B", "marketer")
    assert read("fleet-brains", "_original", "MEMORY.md") == files["MEMORY.md"], "pre-fleet memory kept"
    assert read("fleet-brains", "_original", "memory", "a-notes.md") == "A notes\n", "pre-fleet memory folder kept"
    open(f"{home}/MEMORY.md", "w").write("B work\n")
    h.place("Ace", None, None)                   # Jack clears its product, then it switches again
    switch("A", "engineer")
    assert read("fleet-brains", "_original", "MEMORY.md") == files["MEMORY.md"], "_original is never overwritten"
    srv.shutdown()
    print("first_switch OK")


if __name__ == "__main__":
    main()
