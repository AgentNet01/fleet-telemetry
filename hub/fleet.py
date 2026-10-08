#!/usr/bin/env python3
"""fleet: talk to the fleet hub.

    fleet ask "<agent>" "<text>"     ask another agent (their reply comes back to you)
    fleet inbox                      your oldest waiting item (agents that poll, e.g. dot)
    fleet reply <item> "<text>"      answer an item from your inbox
    fleet status                     what's waiting for you

Config: ~/.fleet/token and ~/.fleet/hub (or FLEET_TOKEN / FLEET_HUB / FLEET_HOME).
If the hub can't be reached, `ask` and `reply` are kept in ~/.fleet/outbox and sent,
exactly once, by your next `fleet` command.
"""
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

HOME = os.environ.get("FLEET_HOME") or os.path.expanduser("~/.fleet")
OUTBOX = os.path.join(HOME, "outbox")


def conf(name, env):
    if os.environ.get(env):
        return os.environ[env].strip()
    with open(os.path.join(HOME, name)) as f:
        return f.read().strip()


def call(method, path, body=None):
    req = urllib.request.Request(conf("hub", "FLEET_HUB").rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + conf("token", "FLEET_TOKEN"),
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def flush():
    if not os.path.isdir(OUTBOX):
        return
    for name in sorted(os.listdir(OUTBOX)):
        path = os.path.join(OUTBOX, name)
        with open(path) as f:
            job = json.load(f)
        call("POST", job["path"], job["body"])   # same key, so a resend after a crash isn't a duplicate
        os.remove(path)


def write(path, body):
    body["key"] = uuid.uuid4().hex
    try:
        flush()
        return call("POST", path, body)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError):
        os.makedirs(OUTBOX, exist_ok=True)
        with open(os.path.join(OUTBOX, body["key"] + ".json"), "w") as f:
            json.dump({"path": path, "body": body}, f)
        print("Hub unreachable: saved to your outbox; it will be sent by your next fleet command.")
        return None


def main(args):
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = args[0]
    if cmd == "ask" and len(args) == 3:
        r = write("/api/ask", {"to": args[1], "text": args[2]})
        r and print(f"Sent as #{r['id']}. {args[1]}'s reply will come back to you.")
    elif cmd == "reply" and len(args) == 3:
        r = write("/api/reply", {"item": int(args[1]), "text": args[2]})
        r and print(f"Replied to #{args[1]}.")
    elif cmd == "inbox":
        flush()
        it = call("GET", "/api/inbox")["item"]
        print(f"#{it['id']} from {it['from']}:\n{it['text']}\n\nAnswer with: fleet reply {it['id']} \"...\""
              if it else "Nothing waiting.")
    elif cmd == "status":
        flush()
        q = call("GET", "/api/status")["queue"]
        print("\n".join(f"#{i['id']} {i['status']:6} from {i['frm']}: {i['text'][:80]}" for i in q) or "Nothing waiting.")
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except urllib.error.HTTPError as e:
        print(f"fleet: hub said {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)
