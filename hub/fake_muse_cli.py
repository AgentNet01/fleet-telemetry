"""Stand-in for `muse-cli`, one account per USERPROFILE/HOME, state in that folder.

Speaks the subset the hub uses, with the real JSON shapes (checked against Boboe 2, Oct 8):
  threads · session-start --title T · send TEXT --thread S --wait 0 · raw chat.history --body JSON
Behaviour switches (files in the account folder): `reply` = text the agent answers each send with.
"""
import json
import os
import sys

home = os.environ.get("USERPROFILE") or os.environ["HOME"]
state_path = os.path.join(home, "fake_state.json")
st = json.load(open(state_path)) if os.path.exists(state_path) else {"sessions": [], "events": [], "seq": 100}
if not os.path.exists(os.path.join(home, ".config", "muse-cli", "cookies.txt")):
    print("auth/check -> 401 (cookies expired? re-export)", file=sys.stderr); sys.exit(1)


def ev(name, sid, text, reply_to="", ready=True):
    st["seq"] += 1
    st["events"].append({"seq": st["seq"], "event_name": name, "reply_to_message_id": reply_to,
                         "display_text_ready": ready, "chat_context": {"chat_id": sid},
                         "payload": {"display_text": text, "session_id": sid}})


a = sys.argv[1:]
if a[0] == "threads":
    out = [{"session_id": s, "title": None, "thread": True} for s in st["sessions"]]
elif a[0] == "session-start":
    sid = f"sess-{len(st['sessions']) + 1}"
    st["sessions"].append(sid)
    out = {"created": True, "session_id": sid}
elif a[0] == "send" and a[a.index("--wait") + 1] == "0":
    out = {"sent": True}                     # real muse.ai drops it: the stream closes before it lands (Oct 8)
elif a[0] == "send":
    sid = a[a.index("--thread") + 1]
    ev("message.user", sid, a[1])
    reply = os.path.join(home, "reply")
    if os.path.exists(reply):
        ev("message.assistant", sid, "(background update)", reply_to="self")   # proactive push: not a reply
        ev("message.assistant", sid, open(reply).read())                        # the genuine reply
        ev("message.assistant", sid, "still typ", ready=False)                 # still streaming: not yet
    out = {"sent": True}
elif a[:2] == ["raw", "chat.history"]:
    body = json.loads(a[a.index("--body") + 1])
    evs = [e for e in st["events"] if e["chat_context"]["chat_id"] == body.get("session_id")]
    out = {"ok": True, "result": {"chat_events": evs[-body.get("limit", 20):]}}
else:
    print(f"fake muse-cli: unsupported {a}", file=sys.stderr); sys.exit(2)
json.dump(st, open(state_path, "w"))
print(json.dumps(out))
