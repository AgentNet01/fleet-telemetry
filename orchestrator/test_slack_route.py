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
s.awaiting.clear(); sent.clear(); s._deliver = lambda agent, item: sent.append((agent, item["why"], item["ts"]))
s.route([msg("300.0", "UD", "Boboe 1, can you hear me?")])
s.route([msg("301.0", "U10", "Boboe 1 ping from an agent")])      # agents' mentions aren't tracked
t0 = s.awaiting[("boboe1", "C", "300.0")]["at"]
sent.clear(); s.retry_unanswered(t0 + 10); assert sent == []                        # too soon
s.retry_unanswered(t0 + s.RETRY_AFTER); assert sent == [("boboe1", "no reply yet", "300.0")]
s.retry_unanswered(t0 + 2 * s.RETRY_AFTER); s.retry_unanswered(t0 + 3 * s.RETRY_AFTER)
assert len(sent) == 2 and not s.awaiting, sent                                     # gives up after RETRIES
s.route([msg("302.0", "UD", "Boboe 1 again?")]); t0 = s.awaiting[("boboe1", "C", "302.0")]["at"]
msg("303.0", "U1", "yes, here")                                                    # it answered
sent.clear(); s.retry_unanswered(t0 + s.RETRY_AFTER); assert sent == [] and not s.awaiting
print("ok")
