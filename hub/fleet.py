#!/usr/bin/env python3
"""fleet: talk to the fleet hub.

    fleet ask "<agent>" "<text>"     ask another agent (their reply comes back to you)
    fleet ask all "<text>"           ask the whole fleet; one answer comes back
    fleet inbox                      your oldest waiting item (agents that poll, e.g. dot)
    fleet reply <item> "<text>"      answer an item from your inbox
    fleet secret get <name>          read a secret you're allowed to
    fleet secret put <name> [--scope agent|product|fleet]   store a secret (value on stdin)
    fleet switch "<product>" "<role>"   switch your brain (run when the hub tells you to)
    fleet status                     your product, role and what's waiting for you

Config: ~/.fleet/token and ~/.fleet/hub (or FLEET_TOKEN / FLEET_HUB / FLEET_HOME).
If the hub can't be reached, `ask` and `reply` are kept in ~/.fleet/outbox and sent,
exactly once, by your next `fleet` command.
"""
import hashlib
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
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


def do_switch(product, role):
    """Agent side of a brain switch: save the current brain, load the hub's target, report the hash.
    Runs on a VM only — it rewrites ~/SOUL.md and ~/MEMORY.md."""
    home = os.path.expanduser("~")
    brain = call("GET", "/api/brain")
    if not brain.get("soul"):
        print("No brain switch is pending for you."); return 1
    saved = os.path.join(home, "fleet-brains", brain.get("from_product") or "previous")
    os.makedirs(saved, exist_ok=True)
    for f in ("IDENTITY.md", "SOUL.md", "MEMORY.md"):
        if os.path.exists(os.path.join(home, f)):
            shutil.copy2(os.path.join(home, f), saved)
    if os.path.isdir(os.path.join(home, "memory")):
        shutil.copytree(os.path.join(home, "memory"), os.path.join(saved, "memory"), dirs_exist_ok=True)
    with open(os.path.join(home, "SOUL.md"), "w") as f:
        f.write(brain["soul"])
    with open(os.path.join(home, "MEMORY.md"), "w") as f:
        f.write(brain["memory"])
    got = hashlib.sha256((brain["soul"] + "\n" + brain["memory"]).encode()).hexdigest()
    call("POST", "/api/switched", {"product": product, "role": role, "hash": got})
    print(f"Switched to {product} as {role}; previous brain saved under ~/fleet-brains/.")
    return 0


def main(args):
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = args[0]
    if cmd == "ask" and len(args) == 3 and args[1] == "all":
        r = write("/api/ask", {"to": "all", "text": args[2]})
        r and print("Asked the fleet. One answer will come back to you.")
    elif cmd == "ask" and len(args) == 3:
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
    elif cmd == "secret" and len(args) >= 3 and args[1] == "get":
        print(call("GET", "/api/secret?name=" + urllib.parse.quote(args[2])).get("value") or "(no such secret)")
    elif cmd == "secret" and len(args) >= 3 and args[1] == "put":
        scope = args[args.index("--scope") + 1] if "--scope" in args else "agent"
        value = sys.stdin.read().strip()
        write("/api/secret", {"name": args[2], "value": value, "scope": scope}) and print(f"Stored {args[2]} ({scope}).")
    elif cmd == "switch" and len(args) == 3:
        return do_switch(args[1], args[2])
    elif cmd == "status":
        flush()
        s = call("GET", "/api/status")
        where = f"You are on {s['product']} as {s['role']}." if s.get("product") else "You are not placed on a product yet."
        q = "\n".join(f"#{i['id']} {i['status']:6} from {i['frm']}: {i['text'][:80]}" for i in s["queue"]) or "Nothing waiting."
        print(where + "\n" + q)
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except urllib.error.HTTPError as e:
        print(f"fleet: hub said {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)
