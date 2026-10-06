"""Stand-in for the Muse sandbox API socket (the read-only activity feed).

Serves GET /activity/recent?limit=N over /run/hatch/sandbox-api/api.sock in the
same shape the real socket returns: {"result": {"entries": [...]}}, newest
first. Entries come from /home/hatch/feed.json -- edit it (or use
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
            limit = int(urllib.parse.parse_qs(url.query).get("limit", ["8"])[0])
            try:
                with open(FEED) as f:
                    entries = json.load(f)
            except (OSError, ValueError):
                entries = []
            code, body = "200 OK", json.dumps({"result": {"entries": entries[:limit]}})
        else:
            code, body = "404 Not Found", '{"error": "not found"}'
        raw = body.encode()
        self.wfile.write(b"HTTP/1.0 " + code.encode() + b"\r\nContent-Type: application/json\r\n"
                         b"Content-Length: " + str(len(raw)).encode() + b"\r\n\r\n" + raw)


if os.path.exists(SOCK):
    os.remove(SOCK)
server = socketserver.ThreadingUnixStreamServer(SOCK, Handler)
os.chmod(SOCK, 0o666)   # world-accessible, like the real one
server.serve_forever()
