"""slack_reader.py -- keeps a copy of every Slack message in the channels the
read-only "Fleet Reader" bot has been invited to, so the dashboard can show
what the agents saw next to what they did.

Runs as a background thread inside fleet_receiver.py. Needs SLACK_BOT_TOKEN in
orchestrator/.env (or the environment); without it, it stays off.

Slack calls per cycle: one history call per channel every POLL seconds for new
top-level messages, and once a minute a re-read of the last THREAD_DAYS days
so thread replies (which don't move the channel forward) are caught, fetching
replies only for threads whose latest reply changed.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(HERE, "slack_messages.json")
POLL = 15            # seconds between checks for new messages
THREAD_EVERY = 60    # seconds between thread sweeps
THREAD_DAYS = 3      # threads with a reply this recent are watched
KEEP_DAYS = 30       # messages older than this are dropped
FIRST_DAYS = 3       # how far back to read on the very first run
THREAD_CONTEXT = 20  # earlier replies sent with a thread message (plus the original post)
# Muse's background runs (hooks, crons) take minutes and often time out without posting; the
# agent's main chat answers in seconds. So a mention that needs an answer is also typed into
# that agent's Muse Wall tile (Jack's Mac, 127.0.0.1); the cron is the backstop if the wall is shut.
WALL_CONTROL = os.path.expanduser("~/Library/Application Support/muse-wall/control.json")
_wall_lock = threading.Lock()


def to_wall(name, item):
    """Type a Slack mention into the agent's main chat via the Muse Wall. False if it couldn't."""
    th = item.get("thread_ts") or item["ts"]
    text = ("Slack: %s named you in #%s%s:\n\n%s\n\nAnswer in Slack, in that thread (channel %s, thread_ts %s). "
            "Then move ~/inbox/slack/%s-%s.json to ~/inbox/slack/done/ if it's there.") % (
        item.get("user_name"), item.get("channel"), " (in a thread)" if item.get("thread_ts") else "",
        item.get("text", "")[:3000], item["channel_id"], th, item["channel_id"], item["ts"])
    try:
        with open(WALL_CONTROL) as f:
            c = json.load(f)
        req = urllib.request.Request("http://127.0.0.1:%d/send" % c["port"], method="POST",
                                     data=json.dumps({"to": [name], "text": text, "by": "Slack"}).encode(),
                                     headers={"X-Wall-Token": c["token"], "Content-Type": "application/json"})
        with _wall_lock, urllib.request.urlopen(req, timeout=60) as r:   # one send at a time
            return all(x.get("ok") for x in json.load(r))
    except Exception as e:
        print("slack reader: wall send to %s failed: %s" % (name, e))
        return False


LATE_AFTER = 1800    # a required mention unanswered this long counts as missed on the dashboard
# Each agent's 1-minute cron answers what's in its inbox. Slack shows when it has answered,
# so the receiver logs each mention's outcome (state["mentions"]) and tells the agent's daemon
# to drop the answered message from its inbox, so no later run answers it again.
KEEP_MENTIONS = 1000
AGENT_THREAD_CAP = 12  # agent-to-agent mentions delivered per thread per hour; past it they're dropped (loop guard)

lock = threading.Lock()
state = {"messages": {}, "cursor": {}, "threads": {}, "users": {}, "channels": {}, "mentions": []}
_deliver = None   # fleet_receiver.deliver(agent, item), set by start()
AGENT_NAME = re.compile(r"^boboe ?(\d+|prime)$", re.I)
EVERYONE = re.compile(r"<!(channel|here|everyone)\b|(^|\s)@(channel|here|everyone)\b")


def token():
    t = os.environ.get("SLACK_BOT_TOKEN", "").strip()
    if t:
        return t
    try:
        with open(os.path.join(HERE, ".env")) as f:
            for line in f:
                if line.startswith("SLACK_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def api(tok, method, **params):
    url = "https://slack.com/api/%s?%s" % (method, urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                out = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:   # rate limited: Slack says how long to wait
                time.sleep(int(e.headers.get("Retry-After", "5")) + 1)
                continue
            raise
        if not out.get("ok"):
            raise RuntimeError("%s: %s" % (method, out.get("error")))
        return out
    raise RuntimeError("%s: rate limited" % method)


def pages(tok, method, key, **params):
    cursor = None
    while True:
        if cursor:
            params["cursor"] = cursor
        out = api(tok, method, limit=200, **params)
        yield from out.get(key, [])
        cursor = (out.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return


def keep(ch, m):
    """Store one message; True if it wasn't stored before. Caller holds the lock."""
    if m.get("subtype") in ("channel_join", "channel_leave"):
        return False
    new = "%s|%s" % (ch, m["ts"]) not in state["messages"]
    name = m.get("user") or (m.get("bot_profile") or {}).get("name") or m.get("username") or m.get("bot_id")
    state["messages"]["%s|%s" % (ch, m["ts"])] = {
        "ts": m["ts"], "ch": ch, "user": name,
        "thread": m.get("thread_ts") if m.get("thread_ts") != m["ts"] else None,
        "replies": m.get("reply_count", 0), "text": (m.get("text") or "")[:4000],
        "edited": bool(m.get("edited"))}
    if m.get("reply_count"):
        state["threads"].setdefault("%s|%s" % (ch, m["ts"]), None)
    return new


def agents():
    """Slack user id -> fleet agent name, e.g. U0C6TQRHRT8 -> boboe2."""
    out = {}
    for uid, name in state["users"].items():
        hit = AGENT_NAME.match(str(name or "").strip())
        if hit:
            out[uid] = "boboe" + hit.group(1).lower()
    return out


def route(new):
    """Hand each new message to the agents it's for: named (@mention or plain
    "Boboe 2"), everyone (@channel/@here), or a person (not another agent) posting in a
    thread the agent has posted in. Never the author itself, never messages from before the reader started."""
    if not _deliver:
        return
    with lock:
        who = agents()
        since = state.get("route_since", 0)
        chans = dict(state["channels"])
        names = dict(state["users"])
        threads = {}
        for m in state["messages"].values():
            if m["user"] in who:
                threads.setdefault((m["ch"], m["thread"] or m["ts"]), set()).add(who[m["user"]])
    for ch, m in new:
        if float(m["ts"]) < since:
            continue
        text = m["text"].lower()
        targets = {}
        for uid, agent in who.items():
            num = agent[len("boboe"):]
            # a person may just write "Boboe 2, ..."; agents cite each other by name all the time,
            # so from an agent only a real @mention counts
            if "<@%s>" % uid.lower() in text or (m["user"] not in who and re.search(r"\bboboe ?%s\b" % num, text)):
                targets[agent] = "mentioned"
        if EVERYONE.search(text):
            for agent in who.values():
                targets.setdefault(agent, "everyone")
        if m["user"] not in who:   # agents replying in a shared thread woke each other in a loop
            for agent in threads.get((ch, m["thread"] or m["ts"]), ()):
                targets.setdefault(agent, "your thread")
        targets.pop(who.get(m["user"]), None)
        item = {"kind": "slack", "channel": chans.get(ch, ch), "channel_id": ch, "ts": m["ts"],
                "thread_ts": m["thread"], "user": m["user"], "user_name": names.get(m["user"], m["user"]),
                "text": m["text"], "from_agent": m["user"] in who}
        if m["thread"]:
            # the thread so far, so the agent has the context without fetching it
            with lock:
                earlier = sorted((x for x in state["messages"].values() if x["ch"] == ch
                                  and (x["ts"] == m["thread"] or x["thread"] == m["thread"])
                                  and float(x["ts"]) < float(m["ts"])), key=lambda x: float(x["ts"]))
            keep_ = earlier[:1] + earlier[1:][-THREAD_CONTEXT:]
            item["thread"] = [{"user_name": names.get(x["user"], x["user"]), "ts": x["ts"],
                               "text": x["text"][:1500]} for x in keep_]
            item["thread_skipped"] = len(earlier) - len(keep_)
        author, thread, now = who.get(m["user"]), m["thread"] or m["ts"], time.time()
        agent_uid = {a: u for u, a in who.items()}   # boboe2 -> its Slack id -> "Boboe 2" (its wall tile)
        for agent, why in targets.items():
            # being named needs an answer -- from a person or an agent. Loop guards for agents:
            # naming someone who just named you in this thread is an answer (no reply needed),
            # and past AGENT_THREAD_CAP agent mentions in a thread per hour, nothing is delivered.
            required = why == "mentioned"
            if required and author:
                with lock:
                    recent = [w for w in state["mentions"] if w["ch"] == ch and w.get("thread") == thread
                              and w.get("from") and now - w["delivered"] < 3600]
                if len(recent) >= AGENT_THREAD_CAP:
                    continue
                if any(w["agent"] == author and w["from"] == agent for w in recent):
                    required = False
            _deliver(agent, dict(item, why=why, reply_required=required))
            if required:
                threading.Thread(target=to_wall, args=(names.get(agent_uid.get(agent), agent), item), daemon=True).start()
            if why == "mentioned":
                with lock:
                    state["mentions"].append({"agent": agent, "from": author, "ch": ch, "ts": m["ts"],
                                              "thread": thread, "item": dict(item, why=why, reply_required=required),
                                              "required": required, "delivered": now, "at": now, "tries": 0,
                                              "answered": None, "gave_up": False})
                    del state["mentions"][:-KEEP_MENTIONS]


def check_answered(now):
    """Log when each agent answered a mention, and clear it from that agent's inbox."""
    if not _deliver:
        return
    with lock:
        who = agents()
        # where each agent has posted: (agent, channel, thread or None for top level) -> newest ts
        posted = {}
        for m in state["messages"].values():
            a = who.get(m["user"])
            if a:
                k = (a, m["ch"], m["thread"])
                posted[k] = max(posted.get(k, 0.0), float(m["ts"]))
        opened = [w for w in state["mentions"] if not w["answered"] and now - w["delivered"] < 86400]
    for w in opened:
        agent, ch, ts = w["agent"], w["ch"], w["ts"]
        # answered = a post after it in its thread (a top-level mention: its new thread, or top level)
        th = w["item"].get("thread_ts")
        spots = [(agent, ch, th)] if th else [(agent, ch, ts), (agent, ch, None)]
        reply = max(posted.get(k, 0.0) for k in spots)
        if reply > float(ts):
            w["answered"] = reply
            _deliver(agent, {"kind": "answered", "channel_id": ch, "ts": ts})
        elif w.get("required", True) and now - w["delivered"] >= LATE_AFTER:
            w["gave_up"] = True


def mentions_for(agent, since):
    """This agent's log of people naming it: delivered, re-sent, answered or not."""
    with lock:
        return [{k: v for k, v in w.items() if k != "item"} | {"user_name": w["item"].get("user_name"),
                "text": (w["item"].get("text") or "")[:300], "thread_ts": w["item"].get("thread_ts")}
                for w in state["mentions"] if w["agent"] == agent and w["delivered"] >= since]


def refresh_names(tok):
    chans = {c["id"]: c["name"] for c in pages(tok, "conversations.list", "channels",
                                               types="public_channel,private_channel",
                                               exclude_archived="true") if c.get("is_member")}
    users = {}
    for u in pages(tok, "users.list", "members"):
        users[u["id"]] = (u.get("profile") or {}).get("display_name") or u.get("real_name") or u.get("name")
    with lock:
        state["channels"], state["users"] = chans, users


def read_new(tok, ch):
    oldest = state["cursor"].get(ch) or "%.6f" % (time.time() - FIRST_DAYS * 86400)
    msgs = list(pages(tok, "conversations.history", "messages", channel=ch, oldest=oldest))
    new = []
    with lock:
        for m in msgs:
            if keep(ch, m):
                new.append((ch, state["messages"]["%s|%s" % (ch, m["ts"])]))
        if msgs:
            state["cursor"][ch] = max(m["ts"] for m in msgs)
        else:
            state["cursor"].setdefault(ch, oldest)
    route(sorted(new, key=lambda x: float(x[1]["ts"])))


def sweep_threads(tok, ch):
    since = "%.6f" % (time.time() - THREAD_DAYS * 86400)
    for parent in pages(tok, "conversations.history", "messages", channel=ch, oldest=since):
        if not parent.get("reply_count"):
            continue
        key = "%s|%s" % (ch, parent["ts"])
        latest = parent.get("latest_reply")
        with lock:
            keep(ch, parent)
            if state["threads"].get(key) == latest:
                continue
        replies = list(pages(tok, "conversations.replies", "messages", channel=ch, ts=parent["ts"]))
        new = []
        with lock:
            for m in replies:
                if keep(ch, m):
                    new.append((ch, state["messages"]["%s|%s" % (ch, m["ts"])]))
            state["threads"][key] = latest
        route(sorted(new, key=lambda x: float(x[1]["ts"])))


def prune():
    cut = time.time() - KEEP_DAYS * 86400
    with lock:
        for k in [k for k, m in state["messages"].items() if float(m["ts"]) < cut]:
            del state["messages"][k]
        for k in [k for k in state["threads"] if float(k.split("|")[1]) < cut]:
            del state["threads"][k]


def save():
    with lock:
        data = json.dumps(state)
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write(data)
    os.replace(tmp, DATA_FILE)


def run(tok):
    last_names = last_threads = 0.0
    while True:
        try:
            now = time.time()
            if now - last_names > 3600 or not state["channels"]:
                refresh_names(tok)
                last_names = now
            for ch in list(state["channels"]):
                read_new(tok, ch)
                if now - last_threads > THREAD_EVERY:
                    sweep_threads(tok, ch)
            if now - last_threads > THREAD_EVERY:
                last_threads = now
                prune()
            check_answered(now)
            save()
        except Exception as e:
            print("slack reader: %s" % e)
        time.sleep(POLL)


def start(deliver=None):
    """Start the background reader; new messages for an agent go to
    deliver(agent, item). Returns False when no token is set."""
    global _deliver
    tok = token()
    if not tok:
        return False
    try:
        with open(DATA_FILE) as f:
            state.update(json.load(f))
    except (OSError, ValueError):
        pass
    _deliver = deliver
    state.setdefault("route_since", time.time())
    threading.Thread(target=run, args=(tok,), daemon=True).start()
    return True


def messages_since(since, limit=2000):
    """Messages newer than `since` (epoch), oldest first, with names resolved."""
    with lock:
        out = sorted((m for m in state["messages"].values() if float(m["ts"]) >= since),
                     key=lambda m: float(m["ts"]))[-limit:]
        return {"messages": out, "users": dict(state["users"]), "channels": dict(state["channels"])}
