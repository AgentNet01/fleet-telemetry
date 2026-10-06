"""Stand-in for the Muse sandbox API socket (the read-only activity feed).

Serves GET /activity/recent over /run/hatch/sandbox-api/api.sock in the shape
documented in the VM's ~/subscriptions/activity_feed/subscription.md:
{"ok": true, "result": {"entries": [...]}}, newest first. Query: limit (default
10, max 100), is_goal (true/false), activity_type. Entry fields: timestamp,
activity_type, status, title, status_title, subtitle, and optional task_label,
message_id. Entries come from /home/hatch/feed.json -- edit it (or use
`run.sh work "<title>"` / `run.sh idle`) to simulate the agent.
"""
import json
import os
import socketserver
import urllib.parse

SOCK = "/run/hatch/sandbox-api/api.sock"
FEED = "/home/hatch/feed.json"


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        request = self.rfile.readline().decode(errors="replace").split()
        while self.rfile.readline() not in (b"\r\n", b"\n", b""):
            pass
        url = urllib.parse.urlsplit(request[1] if len(request) > 1 else "/")
        if url.path == "/activity/recent":
            q = urllib.parse.parse_qs(url.query)
            limit = min(int(q.get("limit", ["10"])[0]), 100)
            try:
                with open(FEED) as f:
                    entries = json.load(f)
            except (OSError, ValueError):
                entries = []
            if "is_goal" in q:
                entries = [e for e in entries if (e.get("activity_type") == "goal") == (q["is_goal"][0] == "true")]
            if "activity_type" in q:
                entries = [e for e in entries if e.get("activity_type") == q["activity_type"][0]]
            code, body = "200 OK", json.dumps({"ok": True, "result": {"entries": entries[:limit]}})
        else:
            code, body = "404 Not Found", '{"ok": false, "error": "not found"}'
        raw = body.encode()
        self.wfile.write(b"HTTP/1.0 " + code.encode() + b"\r\nContent-Type: application/json\r\n"
                         b"Content-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw)


if os.path.exists(SOCK):
    os.remove(SOCK)
server = socketserver.ThreadingUnixStreamServer(SOCK, Handler)
os.chmod(SOCK, 0o666)   # world-accessible, like the real one
server.serve_forever()
