"""Stand-in for the Muse runtime's outbound tunnel proxy on :3130.

Forwards plain-HTTP proxy requests (absolute URLs) to their target, the way
the real tunnel carries the daemon's pushes to Jack's receiver. Like the real
one, it rejects requests that carry proxy credentials with 407 -- install.sh
must strip them.
"""
import http.server
import urllib.error
import urllib.request

DROP = {"host", "proxy-connection", "proxy-authorization", "connection", "content-length"}


class Proxy(http.server.BaseHTTPRequestHandler):
    def forward(self):
        if self.headers.get("Proxy-Authorization"):
            self.send_response(407)
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        req = urllib.request.Request(self.path, data=self.rfile.read(n) if n else None, method=self.command,
                                     headers={k: v for k, v in self.headers.items() if k.lower() not in DROP})
        try:
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=60) as r:
                code, data, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            code, data, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        except Exception as e:
            code, data, ctype = 502, str(e).encode(), "text/plain"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = forward

    def log_message(self, *args):
        pass


http.server.ThreadingHTTPServer(("127.0.0.1", 3130), Proxy).serve_forever()
