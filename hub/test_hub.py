"""Hub rules against a fake transport and clock.

    python3 test_hub.py          # routing, relays, no loops, depth limit
    python3 test_hub.py timing   # no resend, unresponsive after 20 min, one in flight, quiet window
"""
import os
import sys
import tempfile

import hub


class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t
    def go(self, s): self.t += s


class FakeMuse:
    """Records what each agent's side chat received; tests script the replies."""
    def __init__(self): self.sent, self.pending, self.seq = {}, {}, 0
    def deliver(self, agent, text):
        self.sent.setdefault(agent, []).append(text)
        return self.seq
    def replies(self, agent, after):
        return [(s, t) for s, t in self.pending.get(agent, []) if s > after]
    def say(self, agent, text):
        self.seq += 1
        self.pending.setdefault(agent, []).append((self.seq, text))

    def session(self, agent):
        return "fleet-" + agent                 # one stable fleet side chat per agent, like the real transport


def new_hub():
    clock, muse = Clock(), FakeMuse()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), muse, clock)
    for n in ("Boboe 3", "Boboe 7"):
        h.add_agent(n, "muse")
    h.add_agent("dot", "poll")
    return h, muse, clock


def answer(h, muse, clock, agent, text):
    """Agent replies, then 60 s of quiet closes the item."""
    muse.say(agent, text)
    h.tick()
    clock.go(61)
    h.tick()


def routing():
    h, muse, clock = new_hub()
    i = h.ask("Boboe 7", "Boboe 3", "price?")
    h.tick()
    assert len(muse.sent["Boboe 3"]) == 1, "Boboe 3 should get the request exactly once"
    assert "price?" in muse.sent["Boboe 3"][0] and "Boboe 7" in muse.sent["Boboe 3"][0], muse.sent
    h.tick()
    assert len(muse.sent["Boboe 3"]) == 1, "no duplicate delivery while it's in flight"

    answer(h, muse, clock, "Boboe 3", "$3.50")
    assert h.item(i)["status"] == "answered", h.item(i)
    h.tick()
    relay = muse.sent.get("Boboe 7", [])
    assert len(relay) == 1 and "$3.50" in relay[0] and "Boboe 3" in relay[0], f"reply not relayed: {relay}"

    # Boboe 7 answers the relay ("thanks!"): logged, routed nowhere
    before = {a: len(v) for a, v in muse.sent.items()}
    answer(h, muse, clock, "Boboe 7", "thanks!")
    for _ in range(3):
        h.tick(); clock.go(61)
    after = {a: len(v) for a, v in muse.sent.items()}
    assert after == before, f"a reply to a relay must not open anything: {before} -> {after}"
    assert any(e["text"] == "thanks!" for e in h.timeline("Boboe 7")), "the reply is still logged"

    # depth limit: a chain where each agent, while handling the request it was handed,
    # asks the next agent: dot → a1 (0) → a2 (1) → … → a6 (5) → a7 (6, held)
    h2, muse2, clock2 = new_hub()
    for n in ("a1", "a2", "a3", "a4", "a5", "a6", "a7"):
        h2.add_agent(n, "muse")
    h2.ask("dot", "a1", "start"); h2.tick()
    d1 = h2.ask("a1", "a2", "level 1"); h2.tick()
    d2 = h2.ask("a2", "a3", "level 2"); h2.tick()
    d3 = h2.ask("a3", "a4", "level 3"); h2.tick()
    d4 = h2.ask("a4", "a5", "level 4"); h2.tick()
    d5 = h2.ask("a5", "a6", "level 5"); h2.tick()
    iid = h2.ask("a6", "a7", "level 6"); h2.tick()
    assert [h2.item(x)["depth"] for x in (d1, d2, d3, d4, d5, iid)] == [1, 2, 3, 4, 5, 6]
    assert any("level 5" in t for t in muse2.sent["a6"]), "depth 5 is still sent"
    held = h2.item(iid)
    assert held["status"] == "held", f"depth 6 must not be sent: {held}"
    assert any(f"#{iid}" in n["text"] for n in h2.needs_jack()), "depth 6 goes to Needs Jack"
    assert not any("level 6" in t for v in muse2.sent.values() for t in v)

    # poll agent: inbox gives the oldest item, reply closes it and relays
    i1 = h.ask("Boboe 3", "dot", "first")
    h.ask("Boboe 3", "dot", "second")
    got = h.inbox("dot")
    assert got and got["id"] == i1 and "first" in got["text"], got
    assert h.inbox("dot")["id"] == i1, "same item until it's answered"
    h.reply("dot", i1, "on it")
    assert h.item(i1)["status"] == "answered"
    h.tick()
    assert any("on it" in t for t in muse.sent["Boboe 3"]), "poll reply relayed to the asker"
    print("routing OK")


def timing():
    h, muse, clock = new_hub()
    first = h.ask("Boboe 7", "Boboe 3", "one")
    second = h.ask("Boboe 7", "Boboe 3", "two")
    h.tick()
    assert len(muse.sent["Boboe 3"]) == 1, "one item in flight per agent"
    clock.go(1199); h.tick()
    assert len(muse.sent["Boboe 3"]) == 1, "the same text is never sent twice (company_spec: no repeats)"
    clock.go(2); h.tick()
    agent = {a["name"]: a for a in h.board()["agents"]}["Boboe 3"]
    assert agent["state"] == "unresponsive", agent
    assert h.item(first)["status"] == "failed"
    assert any("didn't reply" in t and "one" in t for t in muse.sent.get("Boboe 7", [])), "asker is told"
    h.tick()
    assert "two" in muse.sent["Boboe 3"][-1], "next item goes out once the first is closed"

    # quiet window: a reply isn't closed until 60 s with nothing new
    muse.say("Boboe 3", "part 1")
    h.tick(); clock.go(30)
    muse.say("Boboe 3", "part 2")
    h.tick(); clock.go(31); h.tick()
    assert h.item(second)["status"] == "sent", "still within 60 s of the last message"
    clock.go(30); h.tick()
    it = h.item(second)
    assert it["status"] == "answered" and "part 1" in it["reply"] and "part 2" in it["reply"], it
    agent = {a["name"]: a for a in h.board()["agents"]}["Boboe 3"]
    assert agent["state"] == "active", "a reply makes it active again"
    # a parked agent gets nothing; its items wait until it's woken
    h.add_agent("Boboe 4", "muse")
    h.db.execute("update agents set state='parked' where name='Boboe 4'")
    h.ask("Boboe 7", "Boboe 4", "are you there?")
    h.tick(); clock.go(700); h.tick()
    assert "Boboe 4" not in muse.sent, "nothing is delivered to a parked agent"
    print("timing OK")


def council_queue():
    """2026-10-12 22:09: a fleet question went straight out on top of whatever each agent already had open, so an
    agent held two at once (sometimes got one twice), answered one, and was called unresponsive for the other."""
    h, muse, clock = new_hub()
    first = h.ask("Boboe 7", "Boboe 3", "finish the cover")
    h.tick()
    cid = h.ask_all("Boboe 7", "how do we post to X?")
    h.tick()
    sent = muse.sent["Boboe 3"]
    assert len(sent) == 1 and "finish the cover" in sent[0], f"the question waits its turn: {sent}"
    answer(h, muse, clock, "Boboe 3", "cover done")
    assert h.item(first)["status"] == "answered", h.item(first)
    h.tick()
    asked = [t for t in muse.sent["Boboe 3"] if "how do we post to X?" in t]
    assert len(asked) == 1, f"delivered exactly once: {muse.sent['Boboe 3']}"
    answer(h, muse, clock, "Boboe 3", "use the API")
    q = h.db.execute("select * from items where council=? and too='Boboe 3'", (cid,)).fetchone()
    assert q["status"] == "answered", dict(q)
    assert h._agent("Boboe 3")["state"] == "active"
    # an agent still busy when the council closes isn't handed the stale question afterwards
    busy = h.ask("Boboe 7", "Boboe 3", "long job"); h.tick()
    cid2 = h.ask_all("Boboe 7", "lunch?")
    clock.go(hub.COUNCIL_WINDOW + 1); h.tick()
    muse.say("Boboe 3", "long job done"); h.tick(); clock.go(61); h.tick(); h.tick()
    assert not any("lunch?" in t for t in muse.sent["Boboe 3"]), "closed council: question dropped, not delivered late"
    print("council_queue OK")


if __name__ == "__main__":
    {"timing": timing, "council_queue": council_queue}.get(sys.argv[1] if len(sys.argv) > 1 else "", routing)()
