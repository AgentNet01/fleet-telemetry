"""Run: python3 agents/test_telemetryd.py  (no deps, exits non-zero on failure)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telemetryd as t

t.LOG = os.devnull  # handle_cmd logs; keep the test from leaving a file behind

# cpu_percents: no baseline -> None; one core busy for the interval -> 100%
assert t.cpu_percents([(1, "a", 1.0, 500)], {}, 30) == {1: None}
tick = t.CLK_TCK
pct = t.cpu_percents([(1, "a", 1.0, 30 * tick), (2, "new", 1.0, 3 * tick)],
                     {1: 0}, 30)
assert pct == {1: 100.0, 2: 10.0}, pct
assert t.cpu_percents([(1, "a", 1.0, 5)], {1: 9}, 30) == {1: 0}  # pid reuse

# observed: the daemon's own files and process never count as "working"
now = 1_000_000
own = os.path.relpath(t.TDIR, os.path.join(t.HOME, "workspace")) + os.sep
walked = [(own + "telemetryd.log", 10, now - 5), (own + ".boot_id", 1, now - 5),
          ("notes/old.md", 10, now - 3600)]
plist = [["python3", 14.0, 80.0, 4242], ["hatch", 400.0, 1.0, 1]]
o = t.observed(walked, plist, now, self_pid=4242)
assert o["working"] is False and o["recent"] == [], o

# real evidence does count, newest file first
walked.append(("notes/plan.md", 10, now - 60))
walked.append(("README.md", 10, now - 10))
plist.append(["node", 50.0, 37.0, 7])
o = t.observed(walked, plist, now, self_pid=4242)
assert o["working"] is True, o
assert [r[0] for r in o["recent"]] == ["README.md", "notes/plan.md"], o
assert o["signals"] == ["2 files changed in last 5m", "node at 37% cpu"], o

# files(): rows keep v1 shape [path, kb] plus mtime, largest first
f = t.files([("a", 2048, 5.5), ("b", 4096, 6.0)])
assert f["entries"] == [["b", 4.0, 6], ["a", 2.0, 5]] and f["count"] == 2, f

# file viewing: only plain workspace files reach Jack -- never secrets, hidden
# files, symlink escapes or anything outside ~/workspace
import tempfile
with tempfile.TemporaryDirectory() as home:
    ws = os.path.join(home, "workspace")
    os.makedirs(os.path.join(ws, "notes"))
    os.makedirs(os.path.join(ws, "telemetry"))
    for rel, data in [("notes/plan.md", b"hi"), ("telemetry/.token", b"s3cret"),
                      ("api_token.txt", b"x"), ("big.bin", b"0" * (t.FETCH_MAX + 1))]:
        with open(os.path.join(ws, rel), "wb") as f:
            f.write(data)
    with open(os.path.join(home, "outside.txt"), "w") as f:
        f.write("nope")
    os.symlink(os.path.join(home, "outside.txt"), os.path.join(ws, "escape.txt"))
    os.symlink(os.path.join(ws, "telemetry", ".token"), os.path.join(ws, "innocent.txt"))
    t.HOME = home
    assert t.resolve_fetch("notes/plan.md").endswith("notes/plan.md")
    refused = {}
    for rel in ["telemetry/.token", "api_token.txt", "big.bin", "../outside.txt",
                "/etc/passwd", "escape.txt", "innocent.txt", "notes/gone.md", None]:
        try:
            t.resolve_fetch(rel)
        except ValueError as e:
            refused[rel] = str(e)
    assert len(refused) == 9, refused
    assert refused["innocent.txt"] == "hidden files aren't shared", refused

# hook health: last hour from the runtime's run logs; old runs and junk lines ignored
with tempfile.TemporaryDirectory() as logs:
    t.HOOK_LOGS = logs
    now = 10000.0
    rows = [{"started_at_ms": 9000e3, "outcome": "silent"}, {"started_at_ms": 9500e3, "outcome": "wake", "reason": "2 messages"},
            {"started_at_ms": 9600e3, "outcome": "error", "reason": "boom"}, {"started_at_ms": 1000e3, "outcome": "wake"}]
    with open(os.path.join(logs, "slack-inbox.jsonl"), "w") as f:
        f.write("\n".join(map(json.dumps, rows)) + "\nnot json\n")
    h = t.hook_stats(now)["slack-inbox"]
    assert (h["runs"], h["wakes"], h["errors"], h["last_run"]) == (3, 1, 1, 9600.0), h
    assert h["last_event"]["reason"] == "boom", h
t.note("mailbox", OSError("Remote end closed"))
assert t.HEALTH["mailbox"]["fail"] == 1 and "Remote end" in t.HEALTH["last_error"]["text"]

# a corrupt spool file is dropped instead of blocking everything behind it
with tempfile.TemporaryDirectory() as sp:
    t.SPOOL_DIR = sp
    open(os.path.join(sp, "1.json"), "w").close()
    with open(os.path.join(sp, "2.json"), "w") as f:
        json.dump({"n": 2}, f)
    posted = []
    real = t.post
    t.post = lambda op, tok, payload: (posted.append(payload), (True, {}))[1]
    t.flush_spool(None, "tok")
    t.post = real
    assert posted == [{"n": 2}] and os.listdir(sp) == [], (posted, os.listdir(sp))

# an agent set up by setup.py has no proxy.conf; the daemon must still start
t.PROXY_FILE = "/nonexistent/proxy.conf"
assert t.opener() is not None

# burst caps still hold against hostile input
assert t.handle_cmd({"burst": True, "interval": 0, "until": 1e12}, 100.0) == (2, 400.0)
# when the current route keeps failing, the daemon moves to another route that answers, and remembers it
import http.server, socket, threading
class _Hub(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/fleet.py" else 404); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass
live = http.server.HTTPServer(("127.0.0.1", 0), _Hub)
threading.Thread(target=live.serve_forever, daemon=True).start()
s_ = socket.socket(); s_.bind(("127.0.0.1", 0)); dead_port = s_.getsockname()[1]; s_.close()
dead, good = f"http://127.0.0.1:{dead_port}/api/ingest", f"http://127.0.0.1:{live.server_port}/api/ingest"
with tempfile.TemporaryDirectory() as fd:
    for f, v in (("hub", "https://hub.example"), ("token", "t"), ("agent", "Ada"), ("ingest", dead)):
        open(os.path.join(fd, f), "w").write(v)
    json.dump([{"proxy": None, "ingest": dead}, {"proxy": None, "ingest": good}], open(os.path.join(fd, "routes.json"), "w"))
    real_dir, t._fleet_dir = t._fleet_dir, (lambda: fd)
    assert [r["ingest"] for r in t.load_routes()] == [dead, good], t.load_routes()
    picked = t.failover(dead)
    assert picked and picked["ingest"] == good, f"routes: moved to the route that answers: {picked}"
    assert t.read_config()["receiver_url"] == good, "routes: the new route is remembered for the next start"
    assert not os.path.exists(os.path.join(fd, "proxy.conf")), "a direct route clears the proxy"
    os.remove(os.path.join(fd, "routes.json"))
    assert t.failover(good) is None, "routes: no other route known -> stay put"
    t._fleet_dir = real_dir
live.shutdown()

print("ok")
