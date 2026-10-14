"""Muse transport (against fake_muse_cli.py) and daily login renewal (against a stub sign-in check).

    python3 test_muse.py                  # transport + renewal
    python3 test_muse.py side_chat_only   # every hub message goes to the agent's fleet side chat
    python3 test_muse.py intro            # a new fleet side chat opens with the hub's introduction
    python3 test_muse.py slack            # dot, proxied over Slack until Darragh connects it
"""
import json
import os
import sys
import tempfile
import time

import hub
import muse
from test_hub import Clock

HERE = os.path.dirname(os.path.abspath(__file__))


def account(root, name, cookies="hatch_sess=OLD; hatch_gw=OLDGW; datr=keep"):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, ".config", "muse-cli"))
    with open(os.path.join(d, ".config", "muse-cli", "cookies.txt"), "w") as f:
        f.write(cookies + "\n")
    return d


def cookies_of(d):
    return open(os.path.join(d, ".config", "muse-cli", "cookies.txt")).read().strip()


def transport():
    root = tempfile.mkdtemp()
    b3 = account(root, "boboe-3")
    t = muse.MuseTransport([sys.executable, os.path.join(HERE, "fake_muse_cli.py")], {"Boboe 3": b3})
    with open(os.path.join(b3, "reply"), "w") as f:
        f.write("$3.50, matte")

    mark = t.deliver("Boboe 3", "price?")
    got = t.replies("Boboe 3", mark)
    assert [text for _, text in got] == ["$3.50, matte"], f"only the genuine, finished reply: {got}"

    mark2 = t.deliver("Boboe 3", "and the size?")
    assert all(seq > mark2 for seq, _ in t.replies("Boboe 3", mark2)), "replies only after our message"
    assert len(t.replies("Boboe 3", mark2)) == 1
    assert t.session("Boboe 3") == "sess-1", "one fleet side chat, reused"
    print("transport OK")


def renewal():
    root = tempfile.mkdtemp()
    good, bad = account(root, "boboe-3"), account(root, "boboe-7")
    rotated = ["hatch_sess=; Max-Age=0; Path=/", "hatch_sess=NEW; Max-Age=2592000; Path=/; HttpOnly",
               "hatch_gw=; Max-Age=0", "hatch_gw=NEWGW; Max-Age=31536000"]
    stub = {good: (200, rotated), bad: (401, [])}
    post = lambda account_dir, cookie_header: stub[account_dir]

    expires = muse.renew(good, post, now=1_000_000)
    assert cookies_of(good) == "hatch_sess=NEW; hatch_gw=NEWGW; datr=keep", cookies_of(good)
    assert expires == 1_000_000 + 2592000, expires

    # still valid but not due for rotation: muse.ai answers 200 with no new cookies
    fresh = account(root, "boboe-9")
    stub[fresh] = (200, [])
    assert muse.renew(fresh, post, now=1_000_000) >= 1_000_000 + 25 * 86400, "a valid login isn't a failure"
    assert cookies_of(fresh) == "hatch_sess=OLD; hatch_gw=OLDGW; datr=keep", "nothing new to save"

    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), None, Clock())
    h.add_agent("Boboe 3", "muse"); h.add_agent("Boboe 7", "muse")
    h.renew_logins({"Boboe 3": good, "Boboe 7": bad}, post)
    agents = {a["name"]: a for a in h.board()["agents"]}
    assert agents["Boboe 3"]["login_expires"] > h.clock() + 25 * 86400, agents["Boboe 3"]
    assert agents["Boboe 7"]["state"] == "login", agents["Boboe 7"]
    assert any("Boboe 7" in n["text"] and "login" in n["text"].lower() for n in h.needs_jack())
    assert cookies_of(bad) == "hatch_sess=OLD; hatch_gw=OLDGW; datr=keep", "a failed renewal leaves the file alone"
    stub[bad] = (200, rotated)
    h.renew_logins({"Boboe 7": bad}, post)
    assert not any("Boboe 7" in n["text"] for n in h.needs_jack()), "a later successful renewal clears Needs Jack"
    print("renewal OK")


def fake_state(d):
    return json.load(open(os.path.join(d, "fake_state.json")))


def user_messages(d, sid):
    return [e["payload"]["display_text"] for e in fake_state(d)["events"]
            if e["event_name"] == "message.user" and e["chat_context"]["chat_id"] == sid]


def side_chat_only():
    root = tempfile.mkdtemp()
    d = account(root, "boboe-5")
    t = muse.MuseTransport([sys.executable, os.path.join(HERE, "fake_muse_cli.py")], {"Boboe 5": d})
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), t, Clock())
    h.add_agent("Boboe 5", "muse"); h.add_agent("Boboe 6", "muse")
    h.ask("Boboe 6", "Boboe 5", "can you check the price?")
    h.tick()
    sid = t.session("Boboe 5")
    every = [e for e in fake_state(d)["events"] if e["event_name"] == "message.user"]
    assert every and all(e["chat_context"]["chat_id"] == sid for e in every), "hub messages only ever go to the fleet side chat"
    assert fake_state(d)["sessions"] == [sid], "exactly one fleet side chat"
    print("side_chat_only OK")


def intro():
    root = tempfile.mkdtemp()
    d = account(root, "boboe-5")
    t = muse.MuseTransport([sys.executable, os.path.join(HERE, "fake_muse_cli.py")], {"Boboe 5": d})
    t.deliver("Boboe 5", "first real message")
    msgs = user_messages(d, t.session("Boboe 5"))
    assert len(msgs) == 2 and msgs[1] == "first real message", f"intro: the intro comes first, once: {msgs}"
    assert "fleet task" in msgs[0] and "side chat" in msgs[0].lower(), f"intro: says what this chat is for: {msgs[0]!r}"
    old = t.session("Boboe 5")
    t.reset("Boboe 5")
    t.deliver("Boboe 5", "after reset")
    assert t.session("Boboe 5") != old, "intro: reset opens a fresh fleet side chat"
    assert user_messages(d, t.session("Boboe 5"))[0] == msgs[0], "intro: the fresh chat opens with the intro too"
    print("intro OK")


def slack():
    """dot is a bot reached in a shared channel. Jack, Oct 13: messages go in the channel itself, not one thread.
    dot may answer in the channel or in a thread under the hub's message; both are its replies."""
    chan, posted, n = [], [], [0]

    def say(user, text, thread=None):
        n[0] += 1
        m = {"user": user, "ts": f"17000{n[0]:05d}.000100", "text": text}
        if thread:
            m["thread_ts"] = thread
            parent = next(x for x in chan if x["ts"] == thread)
            parent["reply_count"] = parent.get("reply_count", 0) + 1
            parent["latest_reply"] = m["ts"]
        chan.append(m)
        return m["ts"]

    def api(method, **params):
        if method == "chat.postMessage":
            posted.append(params)
            return {"ts": say("U0HUB", params["text"], params.get("thread_ts"))}
        if method == "conversations.history":            # newest first, top-level only, with reply metadata
            top = [m for m in chan if m.get("thread_ts", m["ts"]) == m["ts"]]
            return {"messages": [dict(m) for m in reversed(top)][:int(params.get("limit", 100))]}
        if method == "conversations.replies":
            return {"messages": [dict(m) for m in chan if m["ts"] == params["ts"] or m.get("thread_ts") == params["ts"]]}
        raise AssertionError(method)

    t = muse.SlackTransport(token=lambda: "xoxb-test", users={"dot": {"user": "U0DOT", "channel": "C0ALL"}}, api=api)
    t.READ_EVERY = 0
    first = t.deliver("dot", "4 agents idle over 12 h")
    assert posted[0] == {"channel": "C0ALL", "text": "<@U0DOT> 4 agents idle over 12 h"}, posted[0]
    say("U0DOT", "on it — PMs asked")                        # answered in the channel
    say("U0JACK", "a person chiming in")
    assert [x for _, x in t.replies("dot", first)] == ["on it — PMs asked"], "dot's channel message is its reply"
    second = t.deliver("dot", "which product first?")
    say("U0DOT", "pet portraits", thread=f"{second:.6f}")       # answered in a thread under the hub's message
    say("U0DOT", "late answer to the first", thread=f"{first:.6f}")
    got = []
    for _ in range(3):                                         # one thread read per pass (Slack's rate limit)
        got += t.replies("dot", second)
    assert {x for _, x in got} == {"pet portraits", "late answer to the first"}, got

    none = muse.SlackTransport(token=lambda: None, users={"dot": {"user": "U0DOT", "channel": "C0ALL"}}, api=api)
    try:
        none.deliver("dot", "x")
        raise AssertionError("no token must fail loudly, not drop the message")
    except muse.LoginError as e:
        assert "slack-bot-token" in str(e), e

    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), None, Clock())
    from test_hub import FakeMuse
    h.transport = FakeMuse()
    h.add_agent("dot", "slack"); h.add_agent("Boboe 5", "muse")
    h.ask("Boboe 5", "dot", "which product first?")
    h.tick()
    assert any("which product first?" in m for m in h.transport.sent.get("dot", [])), "the hub pushes to a slack agent like a muse one"
    print("slack OK")


def activity_privacy():
    """Status lines come from the fleet chat or the agent's own actions, never its owner's main chat;
    a turn 'running' with no output for 30+ min is reported as stuck, not busy."""
    import tempfile
    d = tempfile.mkdtemp(); open(os.path.join(d, "fleet_session.txt"), "w").write("F")
    now = time.time() * 1000
    t = muse.MuseTransport("x", {"Neo": d})
    def seen(sessions):
        t._run = lambda name, *a: ({"result": {"sessions": sessions}} if a[1] == "sessions.list"
                                   else {"result": {"days": [{"activities": []}]}})
        return t.activity("Neo")
    busy_main = seen([{"session_id": "M", "is_primary": True, "status": "running", "updated_at_ms": now, "snippet": "game's friday 7pm"}])
    assert busy_main["busy"] and "game" not in busy_main["line"], busy_main
    newer_main = seen([{"session_id": "M", "is_primary": True, "status": "completed", "updated_at_ms": now, "snippet": "private"},
                       {"session_id": "F", "status": "completed", "updated_at_ms": now - 1000, "snippet": "fleet line"}])
    assert newer_main["line"] == "fleet line", newer_main
    task_thread = seen([{"session_id": "T", "status": "running", "updated_at_ms": now, "snippet": "Uploading concept sheet"}])
    assert task_thread["line"] == "Uploading concept sheet", f"its own side chats/threads are work, shown: {task_thread}"
    hung = seen([{"session_id": "F", "status": "running", "updated_at_ms": now - 3 * 3600e3, "snippet": "x"}])
    assert not hung["busy"] and hung["line"].startswith("stuck"), hung
    print("activity_privacy OK")


if __name__ == "__main__":
    {"activity_privacy": activity_privacy, "side_chat_only": side_chat_only, "intro": intro, "slack": slack}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: (transport(), renewal()))()
