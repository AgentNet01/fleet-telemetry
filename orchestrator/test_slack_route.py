"""Who gets woken for a Slack message. Run: python3 orchestrator/test_slack_route.py"""
import slack_reader as s

sent = []
s._deliver = lambda agent, item: sent.append((agent, item["why"], item["ts"]))
s.state.update(users={"U1": "Boboe 1", "U10": "Boboe 10", "UP": "Boboe Prime", "UD": "Darragh"},
               channels={"C": "all-agentnet"}, route_since=100.0,
               messages={"C|150.0": {"ts": "150.0", "ch": "C", "user": "U10", "thread": None, "text": "starting H26"}})


def msg(ts, user, text, thread=None):
    m = {"ts": ts, "ch": "C", "user": user, "thread": thread, "text": text}
    s.state["messages"]["C|" + ts] = m
    return ("C", m)


def who(*new):
    sent.clear()
    s.route(list(new))
    return sorted((a, why) for a, why, _ in sent)


assert who(msg("200.0", "UD", "dot → Boboe 1: please review")) == [("boboe1", "mentioned")]
assert who(msg("201.0", "UD", "<@U10> can you check")) == [("boboe10", "mentioned")]
assert who(msg("202.0", "UD", "boboe prime, status?")) == [("boboeprime", "mentioned")]
assert who(msg("203.0", "UD", "reply in H26", thread="150.0")) == [("boboe10", "your thread")]
assert who(msg("204.0", "U10", "done, Boboe 10 here", thread="150.0")) == []          # never the author
assert who(msg("205.0", "UD", "<!here> standup")) == [("boboe1", "everyone"), ("boboe10", "everyone"), ("boboeprime", "everyone")]
assert who(msg("207.0", "UD", "@channel", thread="150.0")) == [("boboe1", "everyone"), ("boboe10", "everyone"), ("boboeprime", "everyone")]  # typed, not <!channel>
assert who(msg("208.0", "UD", "email me@channel.com")) == []
# agents talking in a shared thread don't wake each other (that looped: every post woke the other 11)
msg("210.0", "U1", "Boboe 1 joining", thread="150.0")
assert who(msg("211.0", "U10", "status update", thread="150.0")) == []
assert who(msg("212.0", "U10", "Boboe 1, can you take this?", thread="150.0")) == [("boboe1", "mentioned")]
assert who(msg("213.0", "UD", "thanks both", thread="150.0")) == [("boboe1", "your thread"), ("boboe10", "your thread")]
assert who(msg("50.0", "UD", "Boboe 1 old news")) == []                               # before the reader started
assert who(msg("206.0", "UD", "unrelated chatter")) == []
# a thread message carries the thread so far: the original post, then earlier replies
sent.clear(); full = []
s._deliver = lambda agent, item: full.append(item)
s.route([msg("209.0", "UD", "Boboe 10 thoughts?", thread="150.0")])
assert [x["text"] for x in full[0]["thread"]][:2] == ["starting H26", "reply in H26"]
# a person's mention the agent never answers is re-sent, at most RETRIES times; an answer stops it
s.state["mentions"].clear(); sent.clear(); s._deliver = lambda agent, item: sent.append((agent, item["why"], item["ts"]))
s.route([msg("300.0", "UD", "Boboe 1, can you hear me?")])
t0 = s.state["mentions"][-1]["at"]; assert len(s.state["mentions"]) == 1
sent.clear(); s.retry_unanswered(t0 + 10); assert sent == []                        # too soon
s.retry_unanswered(t0 + s.RETRY_AFTER); assert sent == [("boboe1", "no reply yet", "300.0")]
s.retry_unanswered(t0 + 2 * s.RETRY_AFTER); s.retry_unanswered(t0 + 3 * s.RETRY_AFTER)
assert len(sent) == 2 and s.state["mentions"][-1]["gave_up"], sent                # gives up after RETRIES
s.route([msg("302.0", "UD", "Boboe 1 again?")]); t0 = s.state["mentions"][-1]["at"]
msg("302.5", "U1", "busy elsewhere", thread="150.0")                              # a post in another thread isn't an answer
sent.clear(); s.retry_unanswered(t0 + s.RETRY_AFTER); assert sent == [("boboe1", "no reply yet", "302.0")]
msg("303.0", "U1", "yes, here", thread="302.0")                                    # it answered in the mention's thread
sent.clear(); s.retry_unanswered(t0 + 2 * s.RETRY_AFTER); assert sent == [] and s.state["mentions"][-1]["answered"] == 303.0
log = s.mentions_for("boboe1", 0); assert [(x["ts"], bool(x["answered"]), x["gave_up"]) for x in log] == [("300.0", False, True), ("302.0", True, False)], log
# agents: being named needs an answer too, but naming back is an answer, and a thread caps out
s.state["mentions"].clear(); full = []; s._deliver = lambda agent, item: full.append((agent, item["reply_required"]))
s.route([msg("400.0", "U10", "Boboe 1, can you check the build?")]); assert full == [("boboe1", True)]
full.clear(); s.route([msg("401.0", "U1", "Boboe 10 done, it's green", thread="400.0")]); assert full == [("boboe10", False)]
full.clear(); s.route([msg("402.0", "U10", "thanks Boboe 1", thread="400.0")]); assert full == [("boboe1", False)]
for i in range(20): s.route([msg("41%d.0" % i, "U10" if i % 2 else "U1", "Boboe %s again" % ("1" if i % 2 else "10"), thread="400.0")])
assert sum(1 for w in s.state["mentions"] if w["thread"] == "400.0") == s.AGENT_THREAD_CAP          # loop guard
full.clear(); s.route([msg("450.0", "UD", "Boboe 1 still there?", thread="400.0")]); assert ("boboe1", True) in full  # people always pass
print("ok")
