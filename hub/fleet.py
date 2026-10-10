#!/usr/bin/env python3
"""fleet: talk to the fleet hub.

    fleet join "<name>" <code> [<hub url>]   join the hub once (saves ~/.fleet/token); nothing else is installed
    fleet ask "<agent>" "<text>"     ask another agent (their reply comes back to you)
    fleet ask all "<text>"           ask the whole fleet; one answer comes back
    fleet inbox                      your oldest waiting item (agents that poll, e.g. dot)
    fleet reply <item> "<text>"      answer an item from your inbox
    fleet secret get <name>          read a secret you're allowed to
    fleet secret put <name> [--scope agent|product|fleet]   store a secret (value on stdin)
    fleet switch "<product>" "<role>"   switch your brain (run when the hub tells you to)
    fleet status                     your product, role, your tasks and what's waiting for you
    fleet task note <id> "<text>"    progress on a task you hold (restarts its reminder clock)
    fleet task done <id> <link>      finish a task; the link is the evidence (commit, file, URL)
    fleet task verify <id> pass      approve a task you were asked to verify
    fleet task verify <id> fail "<reason>"   send it back to its holder with the reason
    fleet task release <id>          put a task back up for grabs (CEO / the product's PM only)
    fleet suggest "<text>"           suggest a change to your PM and the CEO

  Running the company (CEO: everything; a product's PM: its projects, tasks and people):
    fleet portfolio                  every product, project, open task, and who is where
    fleet product add "<name>" "<brief>" ["<goal>"]          (CEO)
    fleet product set "<product>" brief|metric|status "<value>"
    fleet pm "<product>" <agent>     make an agent the product's PM (CEO)
    fleet project add "<product>" "<name>"
    fleet task add <project id> "<title>" <role> "<done when>" [<blocker task ids,>]
    fleet place <agent> "<product>" <role>   roles: designer engineer marketer optimizer
    fleet suggestion accept|reject <id> ["<note>"]   decide a suggestion (CEO / the product's PM)

Config: ~/.fleet/token and ~/.fleet/hub (or FLEET_TOKEN / FLEET_HUB / FLEET_HOME).
If the hub can't be reached, `ask` and `reply` are kept in ~/.fleet/outbox and sent,
exactly once, by your next `fleet` command.
"""
import hashlib
import json
import os
import re
import shutil
import sys
import time
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


def route():
    """(hub base URL, opener) — the route setup.py proved from this VM (the chat turn's own proxy
    refuses the hub's tailnet address), else ~/.fleet/hub directly."""
    if os.environ.get("FLEET_HUB"):
        return os.environ["FLEET_HUB"].rstrip("/"), urllib.request.build_opener()
    ing, pc = os.path.join(HOME, "ingest"), os.path.join(HOME, "proxy.conf")
    base = open(ing).read().strip().rsplit("/api/ingest", 1)[0] if os.path.exists(ing) else conf("hub", "FLEET_HUB").rstrip("/")
    if os.path.exists(pc):
        p = open(pc).read().strip()
        return base, urllib.request.build_opener(urllib.request.ProxyHandler({"http": p, "https": p}))
    return base, urllib.request.build_opener()


def call(method, path, body=None):
    base, op = route()
    req = urllib.request.Request(base + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + conf("token", "FLEET_TOKEN"),
                                          "Content-Type": "application/json"})
    with op.open(req, timeout=15) as r:
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


ROLE_START, ROLE_END = "<!-- fleet-role -->", "<!-- /fleet-role -->"


def _brain_dir(home, product):
    return os.path.join(home, "fleet-brains", re.sub(r"[^\w.-]+", "_", product))


def do_switch(product, role):
    """Agent side of a switch, run between tasks. IDENTITY.md is never touched. SOUL.md keeps everything
    outside the fleet-role block; only that block changes. Changing product saves this product's
    MEMORY.md + memory/ to ~/fleet-brains/<product>/ and brings back the target's (or its starter brief)."""
    home = os.path.expanduser("~")
    brain = call("GET", "/api/brain")
    if not brain.get("soul") or brain.get("product") != product or brain.get("role") != role:
        print("No switch to that product and role is pending for you."); return 1
    cur = brain.get("from_product")
    if cur != product:
        mem_file, mem_dir = os.path.join(home, "MEMORY.md"), os.path.join(home, "memory")
        # save first; nothing is removed until the copy exists (the first switch keeps the pre-fleet brain)
        dst = _brain_dir(home, cur) if cur else _brain_dir(home, "_original")
        if not cur and os.path.exists(dst):       # _original is written once; later unplaced brains get their own
            dst = _brain_dir(home, time.strftime("_unplaced-%Y%m%d-%H%M%S"))
        tmp = dst + ".saving"
        shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        if os.path.exists(mem_file):
            shutil.copy2(mem_file, tmp)
        if os.path.isdir(mem_dir):
            shutil.copytree(mem_dir, os.path.join(tmp, "memory"))
        shutil.rmtree(dst, ignore_errors=True); os.rename(tmp, dst)
        shutil.rmtree(mem_dir, ignore_errors=True)
        src = _brain_dir(home, product)
        if os.path.exists(os.path.join(src, "MEMORY.md")):
            shutil.copy2(os.path.join(src, "MEMORY.md"), mem_file)
            if os.path.isdir(os.path.join(src, "memory")):
                shutil.copytree(os.path.join(src, "memory"), mem_dir)
        else:                                     # first time on this product: its starter brief
            with open(mem_file, "w") as f:
                f.write(brain["memory"])
        os.makedirs(mem_dir, exist_ok=True)
    soul_path = os.path.join(home, "SOUL.md")
    soul = open(soul_path).read() if os.path.exists(soul_path) else ""
    block = f"{ROLE_START}\n{brain['soul']}\n{ROLE_END}\n"
    if ROLE_START in soul and ROLE_END in soul:
        soul = soul[:soul.index(ROLE_START)] + block + soul[soul.index(ROLE_END) + len(ROLE_END):].lstrip("\n")
    else:
        soul = soul + ("" if not soul or soul.endswith("\n") else "\n") + block
    with open(soul_path, "w") as f:
        f.write(soul)
    got = hashlib.sha256((brain["soul"] + "\n" + brain["memory"]).encode()).hexdigest()
    call("POST", "/api/switched", {"product": product, "role": role, "hash": got})
    where = f"{cur or 'your earlier'} memory is saved in ~/fleet-brains/ and comes back when you return; " if cur != product else ""
    print(f"Switched to {product} as {role}. {where}your identity and the rest of your soul are unchanged.")
    return 0


def main(args):
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__); return 0
    cmd = args[0]
    if cmd == "join" and len(args) in (3, 4):
        base = (args[3] if len(args) == 4 else "https://ai-alienware.tail3cffa4.ts.net").rstrip("/")
        req = urllib.request.Request(base + "/api/claim", data=json.dumps({"name": args[1], "code": args[2]}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            token = json.load(r)["token"]
        os.makedirs(HOME, exist_ok=True)
        for f, v in (("hub", base), ("token", token)):
            with open(os.path.join(HOME, f), "w") as fh:
                fh.write(v)
        os.chmod(os.path.join(HOME, "token"), 0o600)
        print(f"Joined as {args[1]}. Check for work with: fleet status   (and fleet inbox)")
        return 0
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
        tasks = "\n".join(f"task #{t['id']} {t['status']:9} {t['title']} ({t['product']}, {t['role']})"
                          for t in s.get("tasks", [])) or "No open tasks."
        q = "\n".join(f"#{i['id']} {i['status']:6} from {i['frm']}: {i['text'][:80]}" for i in s["queue"]) or "Nothing waiting."
        print(where + "\n" + tasks + "\n" + q)
    elif cmd == "task" and len(args) >= 3 and args[1] in ("note", "done", "verify", "release"):
        verb, tid = args[1], int(args[2])
        body = {"task": tid}
        if verb == "note" and len(args) == 4:
            body["text"] = args[3]
        elif verb == "done" and len(args) == 4:
            body["link"] = args[3]
        elif verb == "verify" and len(args) >= 4 and args[3] in ("pass", "fail"):
            body.update(ok=args[3] == "pass", reason=" ".join(args[4:]))
        elif verb != "release":
            print(__doc__); return 2
        call("POST", "/api/task/" + verb, body)
        print({"note": f"Noted on #{tid}.", "done": f"#{tid} is done and goes to verification.",
               "verify": f"Verification of #{tid} recorded.", "release": f"#{tid} released."}[verb])
    elif cmd in ("portfolio", "product", "project", "pm", "place") or args[:2] == ["task", "add"]:
        import shlex
        print(call("POST", "/api/manage", {"line": shlex.join(args)})["result"])
    elif cmd == "suggest" and len(args) == 2:
        r = call("POST", "/api/suggest", {"text": args[1]})
        print(f"Suggestion #{r['id']} sent to your PM and the CEO.")
    elif cmd == "suggestion" and len(args) >= 3 and args[1] in ("accept", "reject"):
        call("POST", "/api/suggestion", {"id": int(args[2]), "accept": args[1] == "accept", "note": " ".join(args[3:])})
        print(f"Suggestion #{args[2]} {args[1]}ed.")
    else:
        print(__doc__); return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except urllib.error.HTTPError as e:
        print(f"fleet: hub said {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)
