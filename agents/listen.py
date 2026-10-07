#!/usr/bin/env python3
"""listen.py -- the agent's front door.

The agent's main chat starts this with its BACKGROUND exec (muse.exec,
background=true). It waits until a Slack message lands in ~/inbox/slack
(telemetryd writes them within a second), prints them and exits -- and the
runtime turns that exit into a new main-chat turn, in seconds. Muse's own
background runs (hooks, crons) take minutes; this doesn't.

    python3 ~/workspace/telemetry/listen.py            # wait up to 6 hours
    python3 ~/workspace/telemetry/listen.py --hours 1

Only one runs at a time (a second one exits at once). A message is printed
once; it stays in the inbox until the agent moves it to done/ (or the receiver
sees the agent's reply and files it), so nothing is lost if a turn dies.
"""
import fcntl
import json
import os
import sys
import time

INBOX = os.path.expanduser("~/inbox/slack")
SEEN = os.path.join(INBOX, ".announced")
LOCK = os.path.join(INBOX, ".listen.lock")
RESTART = "python3 ~/workspace/telemetry/listen.py"
BURST = 3      # seconds to let a burst of messages land, so they wake you once
TICK = 2


def pending():
    try:
        return sorted(n for n in os.listdir(INBOX) if n.endswith(".json"))
    except OSError:
        return []


def seen():
    try:
        with open(SEEN) as f:
            return set(f.read().split())
    except OSError:
        return set()


def payload(names):
    msgs = []
    for n in names:
        try:
            with open(os.path.join(INBOX, n)) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        msgs.append({"file": n, **{k: m.get(k) for k in (
            "why", "reply_required", "channel", "channel_id", "ts", "thread_ts", "user_name",
            "text", "thread", "thread_skipped")}})
    msgs.sort(key=lambda m: float(m["ts"] or 0))
    newest = {m["thread_ts"]: id(m) for m in msgs if m.get("thread_ts")}
    for m in msgs:
        m["text"] = (m["text"] or "")[:3000]
        if not m.get("thread") or newest.get(m.get("thread_ts")) != id(m):
            m.pop("thread", None)   # thread context once, on its newest message
            m.pop("thread_skipped", None)
    return msgs


def main(hours=6.0):
    os.makedirs(INBOX, exist_ok=True)
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("FRONT DOOR: a listener is already running. Nothing to do; end your turn.")
        return
    deadline = time.time() + hours * 3600
    while time.time() < deadline:
        known, now = seen(), set(pending())
        if known - now:   # filed messages drop out, so one delivered again later still wakes you
            with open(SEEN, "w") as f:
                f.write("\n".join(sorted(known & now)))
        if now - known:
            time.sleep(BURST)
            names = pending()
            new = [n for n in names if n not in seen()]
            with open(SEEN, "w") as f:   # keep only names still in the inbox
                f.write("\n".join(sorted((seen() & set(names)) | set(new))))
            msgs = payload(new)
            if msgs:
                print("FRONT DOOR: %d new Slack message(s) for you.\n" % len(msgs))
                print(json.dumps(msgs, indent=1))
                print("\nDo now: for each reply_required=true message, read its thread and answer in it "
                      "(thread_ts, or ts if empty) unless you already have; others only if they need you. "
                      "Move each handled file to ~/inbox/slack/done/. Then restart the front door with "
                      "background exec: %s" % RESTART)
                return
        time.sleep(TICK)
    print("FRONT DOOR: no messages for %g hours. Restart it with background exec: %s" % (hours, RESTART))


if __name__ == "__main__":
    h = float(sys.argv[sys.argv.index("--hours") + 1]) if "--hours" in sys.argv else 6.0
    main(h)
