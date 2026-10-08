"""Fleet hub: delivers messages between agents, reads replies itself, retries, never loops.

    python hub.py hub.json              run (HTTP API + dashboard + delivery loop + daily login renewal)
    python hub.py hub.json token NAME   print a new token for an agent (replaces its old one)

Rules (hub_plan.md §5/§7): one item in flight per agent; a reply is every genuine message after
ours, closed after 60 s of quiet; no reply in 10 min → resend once; 10 more → unresponsive and
the asker is told. Replies close items and never open them (only `ask` does), and a request
made while handling another is one level deeper; deeper than 5 goes to Needs Jack.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

QUIET, RESEND, MAX_DEPTH = 60, 600, 5
HERE = os.path.dirname(os.path.abspath(__file__))

SCHEMA = """
create table if not exists agents(
  name text primary key, kind text, token_hash text, state text default 'active',
  login_expires real, last_in real, last_out real);
create table if not exists items(
  id integer primary key, kind text, frm text, too text, text text, parent integer, depth integer,
  status text, created real, sent_at real, tries integer default 0, mark integer,
  nreplies integer default 0, last_reply real, reply text, key text, unique(frm, key));
create table if not exists events(id integer primary key, item integer, agent text, dir text, text text, at real);
create table if not exists needs_jack(id integer primary key, text text, at real, done integer default 0);
"""


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Hub:
    def __init__(self, db_path, transport, clock=time.time):
        self.db_path, self.transport, self.clock = db_path, transport, clock
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        # ponytail: one lock around everything, including muse-cli calls in tick(); API calls can
        # wait a few seconds behind a slow tick. Split I/O out of the lock if that ever matters.
        self.lock = threading.RLock()

    # ---- agents -------------------------------------------------------------------------
    def add_agent(self, name, kind):
        token = secrets.token_urlsafe(24)
        with self.lock:
            self.db.execute("insert into agents(name, kind, token_hash) values(?,?,?) on conflict(name) "
                            "do update set kind=excluded.kind, token_hash=excluded.token_hash",
                            (name, kind, _hash(token)))
        return token

    def agent_by_token(self, token):
        row = self.db.execute("select name from agents where token_hash=?", (_hash(token or ""),)).fetchone()
        return row["name"] if row else None

    def _agent(self, name):
        return self.db.execute("select * from agents where name=?", (name,)).fetchone()

    def _set(self, table, key, **cols):
        sets = ", ".join(f"{c}=?" for c in cols)
        col = "name" if table == "agents" else "id"
        self.db.execute(f"update {table} set {sets} where {col}=?", (*cols.values(), key))

    # ---- items --------------------------------------------------------------------------
    def ask(self, frm, to, text, key=None):
        with self.lock:
            if key:
                old = self.db.execute("select id from items where frm=? and key=?", (frm, key)).fetchone()
                if old:
                    return old["id"]
            if not self._agent(to):
                raise ValueError(f"unknown agent: {to}")
            parent = self._inflight(frm)
            depth = parent["depth"] + 1 if parent else 0
            status = "held" if depth > MAX_DEPTH else "queued"
            iid = self.db.execute(
                "insert into items(kind, frm, too, text, parent, depth, status, created, key) values(?,?,?,?,?,?,?,?,?)",
                ("request", frm, to, text, parent["id"] if parent else None, depth, status, self.clock(), key)).lastrowid
            if status == "held":
                self._needs_jack(f"#{iid}: {frm} → {to} is {depth} requests deep, so it was held, not sent: {text[:200]}")
            return iid

    def _note(self, to, headline, text):
        if self._agent(to) and self._agent(to)["kind"] != "jack":
            self.db.execute("insert into items(kind, frm, too, text, depth, status, created) values('note','hub',?,?,0,'queued',?)",
                            (to, f"{headline}\n{text}", self.clock()))

    def _needs_jack(self, text):
        self.db.execute("insert into needs_jack(text, at) values(?,?)", (text, self.clock()))

    def _inflight(self, agent):
        return self.db.execute("select * from items where too=? and status='sent' order by sent_at limit 1", (agent,)).fetchone()

    def _next(self, agent):
        return self.db.execute("select * from items where too=? and status='queued' "
                               "order by kind='note', created, id limit 1", (agent,)).fetchone()

    def _format(self, it, resent=False):
        head = "(resent: no reply seen) " if resent else ""
        if it["kind"] == "note":
            first, _, body = it["text"].partition("\n")
            return f"{head}[fleet #{it['id']} · {first}]\n{body}\n— No reply needed."
        return (f"{head}[fleet #{it['id']} · request from {it['frm']}]\n{it['text']}\n"
                f"— Reply here in plain text; your reply goes back to {it['frm']}.")

    def _log(self, item, agent, direction, text):
        self.db.execute("insert into events(item, agent, dir, text, at) values(?,?,?,?,?)",
                        (item, agent, direction, text, self.clock()))
        self._set("agents", agent, **{"last_in" if direction == "in" else "last_out": self.clock()})

    def _send(self, it, resent=False):
        text = self._format(it, resent)
        mark = self.transport.deliver(it["too"], text)
        self._set("items", it["id"], status="sent", sent_at=self.clock(), tries=it["tries"] + 1, mark=mark)
        self._log(it["id"], it["too"], "in", text)

    def _answered(self, it, reply):
        self._set("items", it["id"], status="answered", reply=reply)
        self._set("agents", it["too"], state="active")
        if it["kind"] == "request" and it["frm"] != "hub":
            self._note(it["frm"], f"reply from {it['too']} to your #{it['id']}", reply)

    def tick(self):
        with self.lock:
            now = self.clock()
            for a in self.db.execute("select * from agents where kind in ('muse','poll') and state != 'parked'").fetchall():
                it = self._inflight(a["name"])
                if it and a["kind"] == "muse":
                    got = self.transport.replies(a["name"], it["mark"])
                    if len(got) > it["nreplies"]:
                        for _, text in got[it["nreplies"]:]:
                            self._log(it["id"], a["name"], "out", text)
                        self._set("items", it["id"], nreplies=len(got), last_reply=now,
                                  reply="\n\n".join(t for _, t in got))
                        self._set("agents", a["name"], state="active")
                        it = self.item(it["id"])
                    if it["last_reply"] and now - it["last_reply"] >= QUIET:
                        self._answered(it, it["reply"])
                        it = None
                if it and not it["last_reply"]:
                    waited = now - it["sent_at"]
                    if a["kind"] == "muse" and it["tries"] < 2 and waited >= RESEND:
                        self._send(it, resent=True)
                    elif waited >= (RESEND if a["kind"] == "muse" else 2 * RESEND):
                        self._set("items", it["id"], status="failed")
                        self._set("agents", a["name"], state="unresponsive")
                        if it["kind"] == "request" and it["frm"] != "hub":
                            self._note(it["frm"], f"{a['name']} didn't reply to your #{it['id']}", it["text"])
                        it = None
                if not it and a["kind"] == "muse":
                    nxt = self._next(a["name"])
                    if nxt:
                        self._send(nxt)

    # ---- poll agents --------------------------------------------------------------------
    def inbox(self, agent):
        with self.lock:
            it = self._inflight(agent)
            if not it:
                it = self._next(agent)
                if not it:
                    return None
                self._set("items", it["id"], status="sent", sent_at=self.clock(), tries=1)
                self._log(it["id"], agent, "in", self._format(it))
            return {"id": it["id"], "kind": it["kind"], "from": it["frm"], "text": it["text"]}

    def reply(self, agent, item_id, text):
        with self.lock:
            it = self.item(item_id)
            if not it or it["too"] != agent:
                raise ValueError(f"#{item_id} isn't yours")
            if it["status"] in ("answered", "failed"):
                return                                  # a retried reply is a no-op
            self._log(item_id, agent, "out", text)
            self._answered(it, text)

    # ---- logins -------------------------------------------------------------------------
    def renew_logins(self, accounts, post=None):
        import muse
        for name, account_dir in accounts.items():
            try:
                exp = muse.renew(account_dir, post, now=self.clock())
                with self.lock:
                    a = self._agent(name)
                    self._set("agents", name, login_expires=exp,
                              state="active" if a and a["state"] == "login" else (a["state"] if a else "active"))
                    self.db.execute("update needs_jack set done=1 where done=0 and text like ?", (f"{name}'s Muse login%",))
            except Exception as e:
                with self.lock:
                    self._set("agents", name, state="login")
                    self._needs_jack(f"{name}'s Muse login couldn't be renewed ({str(e)[:120]}). Sign it in again.")

    # ---- reads --------------------------------------------------------------------------
    def item(self, iid):
        r = self.db.execute("select * from items where id=?", (iid,)).fetchone()
        return dict(r) if r else None

    def items_for(self, agent):
        return [dict(r) for r in self.db.execute("select * from items where too=? order by id", (agent,))]

    def timeline(self, agent, limit=200):
        evs = [dict(r) for r in self.db.execute(
            "select * from (select * from events where agent=? order by id desc limit ?) order by id", (agent, limit))]
        waiting = [{"item": r["id"], "agent": agent, "dir": "waiting", "text": f"from {r['frm']}: {r['text']}", "at": r["created"]}
                   for r in self.db.execute("select * from items where too=? and status='queued' order by id", (agent,))]
        return evs + waiting

    def needs_jack(self):
        return [dict(r) for r in self.db.execute("select * from needs_jack where done=0 order by id desc")]

    def board(self):
        with self.lock:
            out = []
            for a in self.db.execute("select * from agents where kind!='jack' order by name"):
                cur = self._inflight(a["name"])
                queue = self.db.execute("select count(*) from items where too=? and status='queued'", (a["name"],)).fetchone()[0]
                out.append({"name": a["name"], "kind": a["kind"], "state": a["state"], "queue": queue,
                            "current": {"id": cur["id"], "text": cur["text"][:200], "sent_at": cur["sent_at"]} if cur else None,
                            "last_in": a["last_in"], "last_out": a["last_out"], "login_expires": a["login_expires"]})
            return {"now": self.clock(), "agents": out, "needs_jack": self.needs_jack()}


# ---- HTTP ---------------------------------------------------------------------------------
def serve(hub, host, port, password):
    page_path = os.path.join(HERE, "dashboard.html")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, obj):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _jack(self):
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    _, pw = base64.b64decode(auth[6:]).decode().split(":", 1)
                    if hmac.compare_digest(pw, password):
                        return True
                except Exception:
                    pass
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="fleet hub"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def _agent(self):
            auth = self.headers.get("Authorization", "")
            name = hub.agent_by_token(auth[7:]) if auth.startswith("Bearer ") else None
            if not name:
                self._json(401, {"error": "401: bad or missing token"})
            return name

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/", "/index.html"):
                    if self._jack():
                        body = open(page_path, "rb").read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                elif u.path == "/api/board":
                    self._jack() and self._json(200, hub.board())
                elif u.path == "/api/timeline":
                    self._jack() and self._json(200, hub.timeline(q.get("agent", "")))
                elif u.path == "/api/item":
                    self._jack() and self._json(200, hub.item(int(q.get("id", 0))) or {})
                elif u.path == "/api/inbox":
                    name = self._agent()
                    name and self._json(200, {"item": hub.inbox(name)})
                elif u.path == "/api/status":
                    name = self._agent()
                    name and self._json(200, {"agent": name, "queue": [
                        {k: i[k] for k in ("id", "frm", "text", "status")}
                        for i in hub.items_for(name) if i["status"] in ("queued", "sent")]})
                else:
                    self._json(404, {"error": "not found"})
            except Exception as e:
                self._json(500, {"error": str(e)})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/api/ask":
                    name = self._agent()
                    if name:
                        b = self._body()
                        self._json(200, {"id": hub.ask(name, b["to"], b["text"], b.get("key"))})
                elif u.path == "/api/reply":
                    name = self._agent()
                    if name:
                        b = self._body()
                        hub.reply(name, int(b["item"]), b["text"])
                        self._json(200, {"ok": True})
                else:
                    self._json(404, {"error": "not found"})
            except (ValueError, KeyError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})

    return ThreadingHTTPServer((host, port), H)


def main(cfg_path, *args):
    cfg = json.load(open(cfg_path))
    import muse
    accounts = cfg["accounts"]
    transport = muse.MuseTransport(cfg["muse_cli"], accounts)
    h = Hub(cfg["db"], transport)
    if args[:1] == ("token",):
        print(h.add_agent(args[1], cfg.get("kinds", {}).get(args[1], "poll")))
        return
    for name in accounts:
        if not h._agent(name):
            h.add_agent(name, "muse")
    log = open(cfg.get("log", os.path.join(os.path.dirname(cfg["db"]), "hub.log")), "a", buffering=1)

    def loop():
        last_renew = 0
        while True:
            try:
                if time.time() - last_renew > 86400:
                    h.renew_logins(accounts)
                    last_renew = time.time()
                h.tick()
            except Exception:
                log.write(time.strftime("%F %T ") + traceback.format_exc())
            time.sleep(15)

    threading.Thread(target=loop, daemon=True).start()
    log.write(time.strftime("%F %T ") + f"hub up on {cfg.get('host', '127.0.0.1')}:{cfg['port']}\n")
    serve(h, cfg.get("host", "127.0.0.1"), cfg["port"], cfg["password"]).serve_forever()


if __name__ == "__main__":
    main(*sys.argv[1:])
