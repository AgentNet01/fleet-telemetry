#!/usr/bin/env python3
"""
fleet_receiver.py -- telemetry receiver + dashboard for the Boboe fleet.

Your Mac side of the bridge. Each agent pushes a JSON telemetry payload every
~30s over your Tailscale network; this script stores it and serves a live
dashboard (dashboard.html, next to this file -- edits show on browser reload,
no restart needed).

Setup:
  1. BIND_IP below defaults to your Mac's Tailscale IP (`tailscale ip -4`);
     override with FLEET_BIND_IP.
  2. Put the shared secret in token.txt next to this file (or FLEET_TOKEN).
  3. Run:  python3 fleet_receiver.py
  4. Open:  http://<your-tailscale-ip>:8787

Endpoints:
  POST /ingest              agents push heartbeats here (X-Agent-Token)
  POST /api/burst           dashboard asks an agent for live tail (X-Token)
  GET  /api/agents          fleet summary (light; polled by the wall view)
  GET  /api/agents/<name>   one machine in full (detail view), incl. the last
                            7 days of Slack messages (slack_reader.py)
  POST /api/fetch           dashboard asks a machine for one file (X-Token)
  POST /upload              agent sends that file back (X-Agent-Token)
  GET  /api/fetch/<id>      request status;  GET /api/file/<id>  the file
  GET  /api/wait?agent=&after=  an agent's open line: returns items queued for
                            it (held up to 25s when none) (X-Agent-Token)

Payload schema each agent sends (daemon v8; all read passively, nothing
agent-written; older daemons may lack the * fields or add self-reports,
which are ignored):
  {"agent": "boboe2", "daemon": 8, "ts": 1728..., "boot_id": "...",
   "cpu": {"count": 2, "load1": 0.2, "load5": 0.18, "load15": 0.15},
   "mem": {"top": [...], "all": [["hatch", 412.0, 1.5*, 731*], ...],
           "unit": "MB", "cpu_total": 0.8*},      # rows: name, MB, cpu%, pid
   "disk": {"total_gb": 100, "used_gb": 0.13, "path": "/home/hatch"},
   "uptime_s": 9690,
   "files": {"count": 42, "mb": 3.1,
             "entries": [["report.md", 12.3, 1728...*], ...]},  # path, KB, mtime
   "activity": {"current": "Editing code",
                "entries": [{"timestamp":..., "activity_type":...,
                             "status":..., "title":..., "status_title":...,
                             "subtitle":...}]},
   "observed": {"working": true, "signals": ["2 files changed in last 5m"],
                "recent": [["README.md", 1728...]]*},
   "system": {...}, "capabilities": {...}}   # OS/CPU/network; static manifest
"""

import hmac
import json
import mimetypes
import os
import secrets
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

import slack_reader

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------- config ----------------
BIND_IP = os.environ.get("FLEET_BIND_IP", "100.97.2.40")  # Mac's Tailscale IP
PORT = int(os.environ.get("FLEET_PORT", "8787"))


# Shared secret the agents use to authenticate. NEVER commit this to git.
# Put it in a file named "token.txt" next to this script, or set FLEET_TOKEN.
def read_token():
    env = os.environ.get("FLEET_TOKEN")
    if env and env.strip():
        return env.strip()
    with open(os.path.join(HERE, "token.txt")) as f:
        return f.read().strip()


TOKEN = read_token()
# ----------------------------------------

DATA_FILE = os.path.join(HERE, "fleet_telemetry.json")
DASHBOARD_FILE = os.path.join(HERE, "dashboard.html")
MAX_HISTORY = 360      # heartbeats kept per agent (~3h at 30s; less in live tail)
SUMMARY_HISTORY = 60   # points per agent in the fleet summary (sparklines)
MAX_CRON_HISTORY = 100
MAX_FEED = 1000       # activity-feed items kept per agent (the AI's own record of its work)
SAVE_EVERY = 10        # seconds; caps disk writes as the fleet grows
FILE_CACHE = os.path.join(HERE, "file_cache")   # files Jack opened (cleared on start)
UPLOAD_MAX = 10 * 1024 * 1024
MAX_FETCHES = 50       # older viewed files are deleted from the cache

MAILBOX_FILE = os.path.join(HERE, "mailbox.json")
LISTENER_GRACE = 180   # seconds without a running listener before an agent's front door counts as down
HOLD = 25              # seconds an agent's /api/wait is held open when nothing is queued
MAX_QUEUE = 500        # undelivered items kept per agent
MAX_DELIVERED = 300    # delivery records kept per agent (shown on the dashboard)

store = {}   # agent -> {"latest","history","cron_history","first_seen","last_seen"}
bursts = {}  # agent -> epoch until which fast pushes were requested (live tail)
fetches = {}  # id -> {"agent","path","ts","status","error","size"} (file viewing)
lock = threading.Lock()
_last_save = 0.0


def load():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE) as f:
                for agent, rec in json.load(f).items():
                    rec.setdefault("cron_history", [])
                    store[agent] = rec
        except Exception as e:
            print("note: could not load %s (%s), starting fresh" % (DATA_FILE, e))


def save(force=False):
    """Caller holds the lock."""
    global _last_save
    now = time.time()
    if not force and now - _last_save < SAVE_EVERY:
        return
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.replace(tmp, DATA_FILE)
    _last_save = now


# ---- mailbox: what this Mac sends each agent ----
# Agents can't be called, so each keeps a request open (/api/wait). Items get
# increasing ids; an agent asking for "after N" has stored everything up to N,
# which is when an item counts as delivered.
mail = {"next": 1, "queue": {}, "delivered": {}}
mail_cv = threading.Condition()


def mail_load():
    try:
        with open(MAILBOX_FILE) as f:
            mail.update(json.load(f))
    except (OSError, ValueError):
        pass
    for log in mail["delivered"].values():
        for i in log:
            i.pop("thread", None)


def mail_save():
    """Caller holds mail_cv."""
    tmp = MAILBOX_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(mail, f)
    os.replace(tmp, MAILBOX_FILE)


def deliver(agent, item):
    """Queue one item for an agent and wake its open /api/wait."""
    with mail_cv:
        q = mail["queue"].setdefault(agent, [])
        q.append(dict(item, id=mail["next"], queued=time.time()))
        mail["next"] += 1
        del q[:-MAX_QUEUE]
        mail_save()
        mail_cv.notify_all()


def mail_wait(agent, after):
    """Ack everything up to `after`, then return newer items, waiting up to HOLD."""
    deadline = time.time() + HOLD
    with mail_cv:
        if after >= mail["next"]:
            after = 0   # the agent's cursor predates a lost mailbox file
        q = mail["queue"].get(agent, [])
        done = [i for i in q if i["id"] <= after]
        if done:
            now = time.time()
            mail["queue"][agent] = [i for i in q if i["id"] > after]
            log = mail["delivered"].setdefault(agent, [])
            # the thread copy is 90% of a record and nothing reads it after delivery;
            # keeping it made every save rewrite ~50 MB while all agents waited on the lock
            log.extend({**{k: v for k, v in i.items() if k != "thread"}, "delivered": now} for i in done)
            del log[:-MAX_DELIVERED]
            mail_save()
        while True:
            items = [i for i in mail["queue"].get(agent, []) if i["id"] > after]
            left = deadline - time.time()
            if items or left <= 0:
                return after, items[:50]
            mail_cv.wait(left)


def history_point(now, payload):
    """One graphable sample: detected state, CPU, memory, top processes."""
    act = payload.get("activity") or {}
    obs = payload.get("observed") or {}
    mem = payload.get("mem") or {}
    rows = mem.get("all") or mem.get("top") or []
    by_name = {}
    for r in rows:
        name, mb = str(r[0]), r[1] or 0
        cpu = r[2] if len(r) > 2 else None
        cur = by_name.setdefault(name, [0.0, None])
        cur[0] += mb
        if cpu is not None:
            cur[1] = (cur[1] or 0) + cpu
    top = sorted(by_name.items(), key=lambda kv: -kv[1][0])[:12]
    return {"ts": now,
            "app": act.get("current"),
            "obs": obs.get("working"),
            "v": payload.get("daemon"),         # v1's "obs" counts its own writes
            "sig": (obs.get("signals") or [None])[0],
            "cpu": mem.get("cpu_total"),
            "load": (payload.get("cpu") or {}).get("load1"),
            "mem": round(sum(v[0] for v in by_name.values()), 1),
            "procs": {k: [round(v[0], 1), v[1]] for k, v in top}}


def merge_feed(rec, entries):
    """Keep every activity-feed item ever seen. Agents send only their latest
    few each heartbeat; an item that changes later (pending -> success) is
    updated in place. Keyed by message_id, which stays put when the item
    finishes; its timestamp doesn't (it is finish-or-created time). Daemons
    before v9 don't send message_id, so those fall back to time|type|title."""
    if not isinstance(entries, list):
        return
    feed = rec.setdefault("feed", {})
    for e in entries:
        if isinstance(e, dict) and e.get("timestamp"):
            old = "%s|%s|%s" % (e.get("timestamp"), e.get("activity_type"), e.get("title"))
            key = e.get("message_id") or old
            if key != old:
                feed.pop(old, None)   # same item stored by a pre-v9 daemon
            feed[key] = {k: e.get(k) for k in ("timestamp", "activity_type", "status", "title",
                                               "status_title", "subtitle", "task_label", "message_id")}
    if len(feed) > MAX_FEED:
        for k in sorted(feed, key=lambda k: feed[k]["timestamp"])[:-MAX_FEED]:
            del feed[k]


def summary(name, rec):
    """Fleet-view record: latest payload minus the heavy lists."""
    p = dict(rec.get("latest") or {})
    mem = dict(p.get("mem") or {})
    mem.pop("all", None)
    files = dict(p.get("files") or {})
    files.pop("entries", None)
    p["mem"], p["files"] = mem, files
    # people who named this agent in the last day and never got an answer (after re-sends)
    p["missed_mentions"] = sum(1 for w in slack_reader.mentions_for(name, time.time() - 86400) if w["gave_up"])
    for k in ("status", "crons", "active_work", "capabilities"):
        p.pop(k, None)   # self-reports (unused) and static text: keep the wall light
    hist = [{k: h.get(k) for k in ("ts", "app", "obs", "v", "cpu", "load", "mem")}
            for h in rec.get("history", [])[-SUMMARY_HISTORY:]]
    return {"name": name, "latest": p, "last_seen": rec.get("last_seen"),
            "first_seen": rec.get("first_seen"),
            "burst_until": bursts.get(name, 0), "history": hist}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # quiet

    def _send(self, code, body, ctype="application/json", headers=None):
        raw = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(raw)

    def _json_body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))

    def do_POST(self):
        if self.path == "/api/burst":
            return self.do_POST_burst()
        if self.path == "/api/fetch":
            return self.do_POST_fetch()
        if self.path == "/upload":
            return self.do_POST_upload()
        if self.path != "/ingest":
            return self._send(404, '{"error":"not found"}')
        if not hmac.compare_digest(self.headers.get("X-Agent-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        try:
            payload = self._json_body()
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        agent = payload.get("agent") if isinstance(payload, dict) else None
        if not isinstance(agent, str) or not agent.strip():
            # a test ping or broken config must not create a phantom machine
            return self._send(400, '{"error":"payload needs an agent name"}')
        now = time.time()
        with lock:
            rec = store.get(agent, {"history": [], "cron_history": [],
                                    "first_seen": now})
            rec["latest"] = payload
            rec["last_seen"] = now
            if (payload.get("health") or {}).get("listener"):
                rec["listener_seen"] = now
            rec["history"].append(history_point(now, payload))
            rec["history"] = rec["history"][-MAX_HISTORY:]
            merge_feed(rec, (payload.get("activity") or {}).get("entries"))
            crons = payload.get("crons", [])
            last_c = (rec["cron_history"][-1]["crons"]
                      if rec["cron_history"] else None)
            if crons != last_c:
                rec["cron_history"].append({"ts": now, "crons": crons})
                rec["cron_history"] = rec["cron_history"][-MAX_CRON_HISTORY:]
            store[agent] = rec
            save()
            # live tail: if Jack asked for faster pushes from this agent, tell
            # it via the ingest response (the only channel the agent listens
            # on). The agent enforces its own caps (>=2s interval, <=5min).
            until = bursts.get(agent, 0)
            # file viewing rides the same reply: re-sent until the agent answers
            want = [{"id": i, "path": f["path"]} for i, f in fetches.items()
                    if f["agent"] == agent and f["status"] == "pending"][:3]
        cmd = ({"burst": True, "interval": 2, "until": until}
               if until > time.time() else {})
        if want:
            cmd["fetch"] = want
        self._send(200, json.dumps({"ok": True, "cmd": cmd}))

    def do_POST_burst(self):
        if not hmac.compare_digest(self.headers.get("X-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        try:
            body = self._json_body()
        except Exception:
            return self._send(400, '{"error":"bad json"}')
        agent = str(body.get("agent", ""))
        try:
            duration = max(0, min(300, int(body.get("duration", 120))))
        except (TypeError, ValueError):
            return self._send(400, '{"error":"bad duration"}')
        with lock:
            if duration > 0:
                bursts[agent] = time.time() + duration
            else:
                bursts.pop(agent, None)
            until = bursts.get(agent, 0)
        self._send(200, json.dumps({"ok": True, "burst_until": until}))

    def do_POST_fetch(self):
        if not hmac.compare_digest(self.headers.get("X-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        try:
            body = self._json_body()
            agent, path = str(body["agent"]), str(body["path"])
        except Exception:
            return self._send(400, '{"error":"bad request"}')
        fid = secrets.token_hex(8)
        with lock:
            fetches[fid] = {"agent": agent, "path": path, "ts": time.time(),
                            "status": "pending", "error": None, "size": None}
            for old in sorted(fetches, key=lambda k: fetches[k]["ts"])[:-MAX_FETCHES]:
                fetches.pop(old)
                try:
                    os.remove(os.path.join(FILE_CACHE, old))
                except OSError:
                    pass
        self._send(200, json.dumps({"id": fid}))

    def do_POST_upload(self):
        if not hmac.compare_digest(self.headers.get("X-Agent-Token", ""), TOKEN):
            return self._send(403, '{"error":"bad token"}')
        fid = self.headers.get("X-Fetch-Id", "")
        size = int(self.headers.get("Content-Length", 0) or 0)
        with lock:
            f = fetches.get(fid)
        if not f or f["agent"] != self.headers.get("X-Agent"):
            return self._send(404, '{"error":"no such request"}')
        if size > UPLOAD_MAX:
            return self._send(413, '{"error":"too large"}')
        data = self.rfile.read(size)
        err = self.headers.get("X-Fetch-Error")
        if not err:
            # the cache name is our random id, never anything the agent chose
            with open(os.path.join(FILE_CACHE, fid), "wb") as out:
                out.write(data)
        with lock:
            f.update(status="error" if err else "done", error=err, size=len(data))
        self._send(200, '{"ok":true}')

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/wait":
            if not hmac.compare_digest(self.headers.get("X-Agent-Token", ""), TOKEN):
                return self._send(403, '{"error":"bad token"}')
            q = parse_qs(urlsplit(self.path).query)
            agent = (q.get("agent") or [""])[0]
            try:
                after = int((q.get("after") or ["0"])[0])
            except ValueError:
                return self._send(400, '{"error":"bad after"}')
            if not agent:
                return self._send(400, '{"error":"agent required"}')
            after, items = mail_wait(agent, after)
            return self._send(200, json.dumps({"after": after, "items": items}))
        if path == "/api/agents":
            with lock:
                out = [summary(a, r) for a, r in store.items()]
            return self._send(200, json.dumps({"now": time.time(), "agents": out}))
        if path.startswith("/api/agents/"):
            name = unquote(path[len("/api/agents/"):])
            # every agent watches the same channels today; per-agent channel
            # lists come when that stops being true
            slack = slack_reader.messages_since(time.time() - 7 * 86400)
            mentions = slack_reader.mentions_for(name, time.time() - 7 * 86400)
            with lock:
                r = store.get(name)
                out = r and {"name": name, "latest": r.get("latest"),
                             "last_seen": r.get("last_seen"),
                             "first_seen": r.get("first_seen"),
                             "burst_until": bursts.get(name, 0),
                             "history": r.get("history", []),
                             "cron_history": r.get("cron_history", []),
                             "feed": sorted((r.get("feed") or {}).values(),
                                            key=lambda e: e["timestamp"], reverse=True)}
                if out:
                    out["slack"] = slack
                    out["mentions"] = mentions
                    with mail_cv:
                        out["delivered"] = mail["delivered"].get(name, [])[-MAX_DELIVERED:]
                        out["queued"] = mail["queue"].get(name, [])
                body = json.dumps({"now": time.time(), "agent": out})
            return self._send(200 if out else 404, body)
        if path.startswith("/api/fetch/"):
            with lock:
                f = fetches.get(path[len("/api/fetch/"):])
                out = f and {k: f[k] for k in ("path", "status", "error", "size")}
            return self._send(200 if out else 404, json.dumps(out or {"error": "not found"}))
        if path.startswith("/api/file/"):
            fid = path[len("/api/file/"):]
            with lock:
                f = fetches.get(fid)
            if not f or f["status"] != "done":
                return self._send(404, "not found", "text/plain")
            with open(os.path.join(FILE_CACHE, fid), "rb") as fh:
                data = fh.read()
            name = os.path.basename(f["path"])
            plain = "".join(c for c in name if 32 <= ord(c) < 127 and c not in '"\\') or "file"
            mode = "attachment" if "download" in urlsplit(self.path).query else "inline"
            # agent files are untrusted: sandbox them so an HTML/SVG file can't
            # run script on the dashboard's origin
            return self._send(200, data, mimetypes.guess_type(name)[0] or "application/octet-stream",
                              {"Content-Security-Policy": "sandbox",
                               "X-Content-Type-Options": "nosniff",
                               "Content-Disposition": "%s; filename=\"%s\"; filename*=UTF-8''%s"
                                                      % (mode, plain, quote(name))})
        if path in ("/", "/index.html"):
            with open(DASHBOARD_FILE) as f:
                page = f.read().replace("%%TOKEN%%", TOKEN)
            return self._send(200, page, "text/html; charset=utf-8")
        return self._send(404, "not found", "text/plain")


if __name__ == "__main__":
    load()
    shutil.rmtree(FILE_CACHE, ignore_errors=True)
    os.makedirs(FILE_CACHE)
    srv = ThreadingHTTPServer((BIND_IP, PORT), Handler)
    mail_load()
    slack_reader.DATA_FILE = os.path.join(HERE, "slack_messages.json")

    def listener_up(agent):
        # the listener exits on purpose each time it wakes the agent and is restarted at the end
        # of that turn, so only a gap longer than a turn means the front door is really down
        with lock:
            r = store.get(agent) or {}
            return time.time() - r.get("listener_seen", 0) < LISTENER_GRACE
    slack_reader.listener_up = listener_up   # beside this receiver's other data
    print("slack reader: %s" % ("on" if slack_reader.start(deliver) else "off (no SLACK_BOT_TOKEN in .env)"))
    print("fleet receiver listening on http://%s:%d  (dashboard + ingest)" % (BIND_IP, PORT))
    print("waiting for agents... (Ctrl-C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        with lock:
            save(force=True)
        print("\nstopped.")
