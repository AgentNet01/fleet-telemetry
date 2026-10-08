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
COUNCIL_WINDOW = 15 * 60
HERE = os.path.dirname(os.path.abspath(__file__))


def _evidence_ok(link):
    """A piece of evidence counts if its URL answers (HTTP < 400). Real check; override in tests."""
    import urllib.request
    try:
        req = urllib.request.Request(link, method="HEAD", headers={"User-Agent": "fleet-hub"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status < 400
    except Exception:
        return False


def _wakanda_link(reply):
    import re
    for line in reply.splitlines():
        if "WAKANDA" in line:
            m = re.search(r"https?://\S+", line)
            if m:
                return m.group(0).rstrip(".,)")
    return None


def _tally(views, chair_text):
    """Label the council outcome from the views and the chair's own answer."""
    from collections import Counter
    norm = lambda s: s.strip().lower()
    counts = Counter(norm(v["view"]) for v in views)
    if not counts:
        return "chair's call", []
    ranked = counts.most_common()
    top_text, top_n = ranked[0]
    dissent = [(v["agent"], v["view"]) for v in views if norm(v["view"]) != top_text]
    if norm(chair_text) and top_text not in norm(chair_text) and norm(chair_text) not in top_text:
        return "chair's call", dissent
    if len(ranked) == 1:
        return "consensus", []
    return f"majority ({top_n}-{ranked[1][1]})", dissent

SCHEMA = """
create table if not exists agents(
  name text primary key, kind text, token_hash text, state text default 'active',
  login_expires real, last_in real, last_out real,
  current_product text, current_role text, onboarded real, seen_seq integer default 0);
create table if not exists items(
  id integer primary key, kind text, frm text, too text, text text, parent integer, depth integer,
  status text, created real, sent_at real, tries integer default 0, mark integer,
  nreplies integer default 0, last_reply real, reply text, key text, council integer, ref integer,
  unique(frm, key));
create table if not exists events(id integer primary key, item integer, agent text, dir text, text text, at real);
create table if not exists needs_jack(id integer primary key, text text, at real, done integer default 0);
create table if not exists products(
  id integer primary key, name text unique, brief text, pm text, metric text,
  budget real, kill_date text, status text default 'active');
create table if not exists projects(
  id integer primary key, product integer, name text, status text default 'active');
create table if not exists tasks(
  id integer primary key, project integer, title text, role text, done_def text,
  blocked_by text, owner text, status text default 'open', progress_note text,
  evidence text, verified_by text, created real, touched real);
create table if not exists roles(name text primary key, soul text);
create table if not exists seats(role text primary key, agent text);
create table if not exists councils(
  id integer primary key, question text, frm text, chair text, status text default 'open',
  answer text, created real, notified real, ckey text);
create table if not exists council_views(council integer, agent text, view text, at real);
create table if not exists secrets(
  name text primary key, scope text, value text, created_by text, updated real);
create table if not exists secret_reads(id integer primary key, secret text, agent text, at real);
create table if not exists sales(
  id integer primary key, source text, external_id text, product text, amount real,
  currency text, at real, unique(source, external_id));
create table if not exists switches(
  agent text primary key, product text, role text, expect text, issued real, status text);
create table if not exists telemetry(agent text primary key, blob text, at real);
"""
# Columns added to agents/items after milestone 1; harmless on a fresh DB, needed on the PC's.
MIGRATIONS = [
    "alter table agents add column current_product text",
    "alter table agents add column current_role text",
    "alter table agents add column onboarded real",
    "alter table agents add column seen_seq integer default 0",
    "alter table items add column council integer",
    "alter table items add column ref integer",
    "alter table councils add column ckey text",
    "create table if not exists telemetry(agent text primary key, blob text, at real)",
]


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class Hub:
    def __init__(self, db_path, transport, clock=time.time, evidence_ok=None):
        self.db_path, self.transport, self.clock = db_path, transport, clock
        self.evidence_ok = evidence_ok or _evidence_ok
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self._fails = {}                 # agent -> consecutive servicing failures (transient blips don't page Jack)
        self.db.executescript(SCHEMA)
        for m in MIGRATIONS:
            try:
                self.db.execute(m)
            except sqlite3.OperationalError:
                pass                     # column already there
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
        with self.lock:
            row = self.db.execute("select name from agents where token_hash=?", (_hash(token or ""),)).fetchone()
            return row["name"] if row else None

    def note_onboarded(self, name):
        with self.lock:
            self.db.execute("update agents set onboarded=? where name=? and onboarded is null", (self.clock(), name))

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

    def _needs_jack_once(self, text):
        # don't re-add an open item with the same text (e.g. a bad account failing every tick)
        if not self.db.execute("select 1 from needs_jack where done=0 and text=?", (text,)).fetchone():
            self._needs_jack(text)

    def _inflight(self, agent):
        return self.db.execute("select * from items where too=? and status='sent' order by sent_at limit 1", (agent,)).fetchone()

    def _next(self, agent):
        return self.db.execute("select * from items where too=? and status='queued' "
                               "order by kind='note', created, id limit 1", (agent,)).fetchone()

    def _format(self, it, resent=False):
        head = "(resent: no reply seen) " if resent else ""
        kind, iid, body = it["kind"], it["id"], it["text"]
        if kind == "note":
            first, _, rest = body.partition("\n")
            return f"{head}[fleet #{iid} · {first}]\n{rest}\n— No reply needed."
        if kind == "task":
            return (f"{head}[fleet #{iid} · task]\n{body}\n"
                    f"— Work on it, then reply. Finish with a line `WAKANDA <link>` whose link is the "
                    f"evidence (a commit, file or URL). No link yet? Reply your progress so far.")
        if kind == "verify":
            return (f"{head}[fleet #{iid} · verify]\n{body}\n"
                    f"— Check it yourself against the definition of done. Reply `pass` or `fail: <reason>`.")
        if kind == "question":
            return (f"{head}[fleet #{iid} · the fleet is being asked]\n{body}\n"
                    f"— Reply with your own view in a sentence or two. One answer will be chosen from everyone's.")
        if kind == "chair":
            return (f"{head}[fleet #{iid} · you are the chair]\n{body}\n"
                    f"— Read the views and reply with one answer for the fleet.")
        return (f"{head}[fleet #{iid} · request from {it['frm']}]\n{body}\n"
                f"— Reply here in plain text; your reply goes back to {it['frm']}.")

    def _log(self, item, agent, direction, text):
        self.db.execute("insert into events(item, agent, dir, text, at) values(?,?,?,?,?)",
                        (item, agent, direction, text, self.clock()))
        self._set("agents", agent, **{"last_in" if direction == "in" else "last_out": self.clock()})

    def _send(self, it, resent=False):
        text = self._format(it, resent)
        mark = self.transport.deliver(it["too"], text)          # muse-cli I/O — never under the lock
        with self.lock:
            self._set("items", it["id"], status="sent", sent_at=self.clock(), tries=it["tries"] + 1, mark=mark)
            self._log(it["id"], it["too"], "in", text)
            if it["kind"] == "note":
                self._set("items", it["id"], status="answered")  # notes need no reply; don't hold the slot

    def _answered(self, it, reply):
        self._set("items", it["id"], status="answered", reply=reply)
        self._set("agents", it["too"], state="active")
        kind = it["kind"]
        if kind == "request" and it["frm"] != "hub":
            self._note(it["frm"], f"reply from {it['too']} to your #{it['id']}", reply)
        elif kind == "task":
            self._on_task_reply(it, reply)
        elif kind == "verify":
            self._on_verify_reply(it, reply)
        elif kind == "question":
            self._add_view(it["council"], it["too"], reply)
        elif kind == "chair":
            self._resolve_council(it["council"], reply)

    def tick(self):
        now = self.clock()
        with self.lock:
            # plan first (DB only), so newly-assigned task items are visible to the agents below
            self._assign_tasks()
            self._switch_to_fill()
            self._close_councils()
            agents = [dict(a) for a in self.db.execute(
                "select * from agents where kind in ('muse','poll') and state != 'parked' order by name")]
        # Two passes so cross-agent effects (a reply that queues a note for someone else) land in
        # the same tick regardless of agent order. One bad account can't starve the rest — each
        # agent is serviced independently and the muse-cli I/O runs outside the lock, so a slow or
        # hanging account can't stall the whole fleet.
        for a in agents:
            self._guarded(a["name"], lambda a=a: self._poll_agent(a, now))
        for a in agents:
            self._guarded(a["name"], lambda a=a: self._deliver_agent(a["name"], a["kind"], now))

    FAIL_ESCALATE = 5                    # consecutive failures before an agent's trouble reaches Jack

    def _guarded(self, name, fn):
        try:
            fn()
            if self._fails.pop(name, 0):     # it was failing and just recovered
                with self.lock:
                    self.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)",
                                    (name, "recovered", self.clock()))
        except Exception as e:
            n = self._fails[name] = self._fails.get(name, 0) + 1
            try:
                with self.lock:
                    # every error is logged for transparency; only sustained failure pages Jack, and
                    # the headline is stable per agent so a stuck account files exactly one open item.
                    self.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)",
                                    (name, f"#{n} {str(e)[:160]}", self.clock()))
                    if n >= self.FAIL_ESCALATE:
                        self._needs_jack_once(f"{name} keeps failing to service — check the agent/login")
            except Exception:
                pass

    def _poll_agent(self, a, now):
        if a["kind"] != "muse":
            return
        name = a["name"]
        with self.lock:
            it = self._inflight(name)
            seen = a["seen_seq"] or 0
            it_mark = it["mark"] if it else None
        fresh = self.transport.replies(name, seen)                   # I/O, no lock
        rep = self.transport.replies(name, it_mark) if (fresh and it_mark is not None) else None
        with self.lock:
            it = self._inflight(name)
            if fresh:
                for _, text in fresh:
                    self._log(it["id"] if it else None, name, "out", text)
                self._set("agents", name, seen_seq=max(s for s, _ in fresh), state="active")
                if it and rep is not None:
                    self._set("items", it["id"], nreplies=len(rep), last_reply=now,
                              reply="\n\n".join(t for _, t in rep))
                    it = self.item(it["id"])
            if it and it["last_reply"] and now - it["last_reply"] >= QUIET:
                self._answered(it, it["reply"])

    def _deliver_agent(self, name, kind, now):
        with self.lock:
            it = self._inflight(name)
            resend = nextitem = None
            if it and not it["last_reply"]:
                waited = now - it["sent_at"]
                if kind == "muse" and it["tries"] < 2 and waited >= RESEND:
                    resend = it
                elif waited >= (RESEND if kind == "muse" else 2 * RESEND):
                    self._fail_item(it, name)
                    it = None
            if not it and kind == "muse" and resend is None:
                nextitem = self._next(name)
        if resend is not None:
            self._send(resend, resent=True)
        elif nextitem is not None:
            self._send(nextitem)

    def _fail_item(self, it, name):
        self._set("items", it["id"], status="failed")
        self._set("agents", name, state="unresponsive")
        kind = it["kind"]
        if kind == "request" and it["frm"] != "hub":
            self._note(it["frm"], f"{name} didn't reply to your #{it['id']}", it["text"])
        elif kind == "task" and it["ref"]:
            self._set("tasks", it["ref"], owner=None, status="ready",
                      progress_note=f"{name} went unresponsive; released", touched=self.clock())
        elif kind == "verify" and it["ref"]:
            self._set("tasks", it["ref"], owner=None, status="ready",
                      progress_note=f"verifier {name} went unresponsive; re-open", touched=self.clock())
        elif kind == "chair" and it["council"]:
            self._resolve_council(it["council"], "(the chair didn't respond — please decide)")

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

    # ---- company: products, projects, tasks ---------------------------------------------
    def place(self, agent, product, role):
        with self.lock:
            self._set("agents", agent, current_product=self._product_name(product), current_role=role)

    def _product_name(self, product):
        if isinstance(product, int):
            r = self.db.execute("select name from products where id=?", (product,)).fetchone()
            return r["name"] if r else str(product)
        return product

    def set_role(self, name, soul):
        with self.lock:
            self.db.execute("insert into roles(name, soul) values(?,?) on conflict(name) do update set soul=excluded.soul", (name, soul))

    def seat(self, role, agent):
        with self.lock:
            self.db.execute("insert into seats(role, agent) values(?,?) on conflict(role) do update set agent=excluded.agent", (role, agent))

    def add_product(self, name, brief="", pm=None, metric=None, budget=None, kill_date=None):
        with self.lock:
            return self.db.execute("insert into products(name, brief, pm, metric, budget, kill_date) values(?,?,?,?,?,?)",
                                   (name, brief, pm, metric, budget, kill_date)).lastrowid

    def add_project(self, product_id, name):
        with self.lock:
            return self.db.execute("insert into projects(product, name) values(?,?)", (product_id, name)).lastrowid

    def add_task(self, project_id, title, role, done_def, blocked_by=(), owner=None):
        with self.lock:
            tid = self.db.execute(
                "insert into tasks(project, title, role, done_def, blocked_by, owner, status, created, touched) "
                "values(?,?,?,?,?,?,?,?,?)",
                (project_id, title, role, done_def, json.dumps(list(blocked_by)), owner,
                 "blocked" if blocked_by else "open", self.clock(), self.clock())).lastrowid
            return tid

    def task(self, tid):
      with self.lock:
        r = self.db.execute("select * from tasks where id=?", (tid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["blocked_by"] = json.loads(d["blocked_by"] or "[]")
        d["product"] = self._task_product(tid)
        return d

    def _task_product(self, tid):
        r = self.db.execute("select p.name from tasks t join projects pr on t.project=pr.id "
                            "join products p on pr.product=p.id where t.id=?", (tid,)).fetchone()
        return r["name"] if r else None

    def _blockers_done(self, task_row):
        for b in json.loads(task_row["blocked_by"] or "[]"):
            r = self.db.execute("select status from tasks where id=?", (b,)).fetchone()
            if not r or r["status"] != "done":
                return False
        return True

    def _idle(self, product=None, role=None):
        """An active, un-parked agent with nothing in flight and nothing queued, optionally in a given brain."""
        for a in self.db.execute("select * from agents where kind='muse' and state='active'").fetchall():
            if self._inflight(a["name"]) or self._next(a["name"]):
                continue
            if product and a["current_product"] != product:
                continue
            if role and a["current_role"] != role:
                continue
            yield a["name"]

    def _assign_tasks(self):
        # a task becomes ready once its blockers are done; ready+unowned tasks go to a matching idle agent
        for t in self.db.execute("select * from tasks where status in ('open','blocked','ready')").fetchall():
            ready = self._blockers_done(t)
            if ready and not t["owner"]:
                self._set("tasks", t["id"], status="ready")
            elif not ready:
                self._set("tasks", t["id"], status="blocked")
            if not ready or t["owner"]:
                continue
            product = self._task_product(t["id"])
            owner = next(self._idle(product, t["role"]), None)
            if owner:
                self._set("tasks", t["id"], owner=owner, status="working", touched=self.clock())
                self.db.execute(
                    "insert into items(kind, frm, too, text, ref, depth, status, created) values('task','hub',?,?,?,0,'queued',?)",
                    (owner, f"{t['title']} — {product}, as {t['role']}.\nDone when: {t['done_def']}", t["id"], self.clock()))

    def _on_task_reply(self, it, reply):
        tid = it["ref"]
        t = self.db.execute("select * from tasks where id=?", (tid,)).fetchone()
        if not t:
            return
        link = _wakanda_link(reply)
        if link and self.evidence_ok(link):
            self._set("tasks", tid, status="verifying", evidence=link, touched=self.clock())
            verifier = next((n for n in self._idle() if n != t["owner"]), None)
            if verifier:
                self.db.execute(
                    "insert into items(kind, frm, too, text, ref, depth, status, created) values('verify','hub',?,?,?,0,'queued',?)",
                    (verifier, f"{t['title']} — {self._task_product(tid)}.\nDone when: {t['done_def']}\nEvidence: {link}", tid, self.clock()))
            else:
                self._set("tasks", tid, verified_by="(no verifier available)", status="done")
        elif link:
            self._set("tasks", tid, progress_note="evidence didn't check out: " + link, touched=self.clock())
        else:
            # ponytail: a progress note just updates the task; no auto-continue (no loop, nothing to nudge).
            self._set("tasks", tid, progress_note=reply, touched=self.clock())

    def _on_verify_reply(self, it, reply):
        tid = it["ref"]
        t = self.db.execute("select * from tasks where id=?", (tid,)).fetchone()
        if not t:
            return
        if "fail" in reply.lower():
            self._set("tasks", tid, status="ready", owner=None, progress_note="verify failed: " + reply, touched=self.clock())
        else:
            self._set("tasks", tid, status="done", verified_by=it["too"], touched=self.clock())

    # ---- council ------------------------------------------------------------------------
    def _responders(self):
        return [a["name"] for a in self.db.execute(
            "select name from agents where kind in ('muse','poll') and state='active'").fetchall()]

    def ask_all(self, frm, question, chair=None, key=None):
        with self.lock:
            if key:
                old = self.db.execute("select id from councils where frm=? and ckey=?", (frm, key)).fetchone()
                if old:
                    return old["id"]                 # idempotent: an outbox replay doesn't make a 2nd council
            chair = chair or self._chair()
            cid = self.db.execute("insert into councils(question, frm, chair, status, created, ckey) values(?,?,?,?,?,?)",
                                  (question, frm, chair, "open", self.clock(), key)).lastrowid
            items = []
            for name in self._responders():
                iid = self.db.execute(
                    "insert into items(kind, frm, too, text, council, depth, status, created) values('question','hub',?,?,?,0,'queued',?)",
                    (name, question, cid, self.clock())).lastrowid
                items.append(iid)
        for iid in items:                            # deliver just these items (I/O outside the lock), not a full tick
            self._send(self.item(iid))
        return cid

    def _chair(self):
        r = self.db.execute("select agent from seats where role='ceo'").fetchone()
        return r["agent"] if r else None

    def _add_view(self, cid, agent, view):
        self.db.execute("insert into council_views(council, agent, view, at) values(?,?,?,?)", (cid, agent, view, self.clock()))

    def _close_councils(self):
        for c in self.db.execute("select * from councils where status='open'").fetchall():
            voted = {r["agent"] for r in self.db.execute("select agent from council_views where council=?", (c["id"],))}
            responders = set(self._responders())
            if responders - voted and self.clock() - c["created"] < COUNCIL_WINDOW:
                continue                                       # still waiting, window open
            self._set("councils", c["id"], status="chairing")
            views = self.db.execute("select agent, view from council_views where council=?", (c["id"],)).fetchall()
            summary = "\n".join(f"- {v['agent']}: {v['view']}" for v in views)
            missing = sorted(responders - voted)
            chair = c["chair"]
            if chair and self._agent(chair):
                self.db.execute(
                    "insert into items(kind, frm, too, text, council, depth, status, created) values('chair','hub',?,?,?,0,'queued',?)",
                    (chair, f"Question: {c['question']}\n\nViews:\n{summary}" + (f"\n\nNo reply: {', '.join(missing)}" if missing else ""),
                     c["id"], self.clock()))
            else:
                self._resolve_council(c["id"], "(no chair set — please decide)", chair_text_is_answer=False)

    def _resolve_council(self, cid, chair_text, chair_text_is_answer=True):
        c = self.db.execute("select * from councils where id=?", (cid,)).fetchone()
        views = [dict(v) for v in self.db.execute("select agent, view from council_views where council=?", (cid,))]
        label, dissent = _tally(views, chair_text)
        missing = sorted(set(self._responders()) - {v["agent"] for v in views})
        answer = f"{label}: {chair_text}"
        if dissent:
            answer += "\ndissent: " + "; ".join(f"{a} ({v})" for a, v in dissent)
        if missing:
            answer += "\nno reply: " + ", ".join(missing)
        self._set("councils", cid, status="answered", answer=answer)
        if c and c["frm"] and self._agent(c["frm"]):
            self._note(c["frm"], f"answer to your question", answer)

    def council(self, cid):
        with self.lock:
            c = self.db.execute("select * from councils where id=?", (cid,)).fetchone()
            if not c:
                return None
            d = dict(c)
            d["views"] = [dict(v) for v in self.db.execute("select agent, view, at from council_views where council=?", (cid,))]
            return d

    def councils(self):
        with self.lock:
            return [self.council(r["id"]) for r in self.db.execute("select id from councils order by id desc")]

    # ---- brain switch -------------------------------------------------------------------
    def brain_for(self, agent):
        with self.lock:
            sw = self.db.execute("select * from switches where agent=?", (agent,)).fetchone()
            if not sw:
                return None
            soul = (self.db.execute("select soul from roles where name=?", (sw["role"],)).fetchone() or {"soul": ""})["soul"]
            prod = self.db.execute("select brief from products where name=?", (sw["product"],)).fetchone()
            memory = f"# MEMORY.md (product: {sw['product']})\n{prod['brief'] if prod else ''}"
            return {"product": sw["product"], "role": sw["role"], "soul": soul, "memory": memory}

    def issue_switch(self, agent, product, role):
        with self.lock:
            soul = (self.db.execute("select soul from roles where name=?", (role,)).fetchone() or {"soul": ""})["soul"]
            prod = self.db.execute("select brief from products where name=?", (product,)).fetchone()
            memory = f"# MEMORY.md (product: {product})\n{prod['brief'] if prod else ''}"
            expect = hashlib.sha256((soul + "\n" + memory).encode()).hexdigest()
            self.db.execute("insert into switches(agent, product, role, expect, issued, status) values(?,?,?,?,?,'issued') "
                            "on conflict(agent) do update set product=excluded.product, role=excluded.role, expect=excluded.expect, issued=excluded.issued, status='issued'",
                            (agent, product, role, expect, self.clock()))
            self.db.execute(
                "insert into items(kind, frm, too, text, depth, status, created) values('note','hub',?,?,0,'queued',?)",
                (agent, f"brain switch\nYour next task is in {product} as {role}. Run: fleet switch \"{product}\" \"{role}\"\n"
                        f"It saves your current brain to ~/fleet-brains, loads {product}, and reports back. This is the fleet's normal hand-off.",
                 self.clock()))

    def record_switch(self, agent, product, role, got_hash):
        with self.lock:
            sw = self.db.execute("select * from switches where agent=?", (agent,)).fetchone()
            if sw and sw["expect"] == got_hash and sw["product"] == product and sw["role"] == role:
                self._set("agents", agent, current_product=product, current_role=role)
                self.db.execute("update switches set status='done' where agent=?", (agent,))
                return True
            self.db.execute("update switches set status='mismatch' where agent=?", (agent,))
            self._needs_jack(f"{agent}'s brain switch to {product}/{role} reported a hash that didn't match what the hub issued.")
            return False

    def _switch_to_fill(self):
        # a ready, unowned task with no matching idle agent, but an idle agent exists → switch one to fill it
        for t in self.db.execute("select * from tasks where status='ready' and owner is null").fetchall():
            product = self._task_product(t["id"])
            if next(self._idle(product, t["role"]), None):
                continue                                       # someone already fits; _assign_tasks will take it
            cand = next((n for n in self._idle()
                         if self.db.execute("select status from switches where agent=?", (n,)).fetchone() is None
                         or self.db.execute("select status from switches where agent=?", (n,)).fetchone()["status"] != "issued"), None)
            if cand:
                self.issue_switch(cand, product, t["role"])

    # ---- vault --------------------------------------------------------------------------
    def secret_put(self, name, value, scope, by):
        with self.lock:
            self.db.execute("insert into secrets(name, scope, value, created_by, updated) values(?,?,?,?,?) "
                            "on conflict(name) do update set value=excluded.value, scope=excluded.scope, updated=excluded.updated",
                            (name, scope, value, by, self.clock()))

    def _may_read(self, agent, scope):
        if scope == "fleet":
            return True
        if scope == f"agent:{agent}":
            return True
        a = self._agent(agent)
        return bool(a) and scope == f"product:{a['current_product']}"

    def secret_get(self, name, agent):
        with self.lock:
            r = self.db.execute("select scope, value from secrets where name=?", (name,)).fetchone()
            if not r:
                return None
            if not self._may_read(agent, r["scope"]):
                raise PermissionError(f"{agent} may not read {name}")
            self.db.execute("insert into secret_reads(secret, agent, at) values(?,?,?)", (name, agent, self.clock()))
            return r["value"]

    def secret_reads(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select secret, agent, at from secret_reads order by id desc limit 200")]

    def secret_names(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select name, scope, created_by, updated from secrets order by name")]

    # ---- revenue ------------------------------------------------------------------------
    def pull_revenue(self, fetch):
        with self.lock:
            for s in fetch():
                self.db.execute("insert or ignore into sales(source, external_id, product, amount, currency, at) "
                                "values(?,?,?,?,?,?)",
                                (s["source"], s["external_id"], s.get("product"), s["amount"], s.get("currency", "usd"), s.get("at", self.clock())))

    def revenue(self):
        with self.lock:
            total = self.db.execute("select coalesce(sum(amount),0) t from sales").fetchone()["t"]
            by = {r["product"]: r["s"] for r in self.db.execute("select product, sum(amount) s from sales group by product")}
            return {"total": total, "by_product": by}

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
        with self.lock:
            r = self.db.execute("select * from items where id=?", (iid,)).fetchone()
            return dict(r) if r else None

    def items_for(self, agent):
        with self.lock:
            return [dict(r) for r in self.db.execute("select * from items where too=? order by id", (agent,))]

    def timeline(self, agent, limit=200):
        with self.lock:
            evs = [dict(r) for r in self.db.execute(
                "select * from (select * from events where agent=? order by id desc limit ?) order by id", (agent, limit))]
            waiting = [{"item": r["id"], "agent": agent, "dir": "waiting", "text": f"from {r['frm']}: {r['text']}", "at": r["created"]}
                       for r in self.db.execute("select * from items where too=? and status='queued' order by id", (agent,))]
            asked = [{"item": r["id"], "agent": agent, "dir": "asked", "text": f"to {r['too']}: {r['text']}", "at": r["created"]}
                     for r in self.db.execute("select * from items where frm=? and kind in ('request','question') order by id", (agent,))]
            return sorted(evs + waiting + asked, key=lambda e: e["at"] or 0)

    def needs_jack(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select * from needs_jack where done=0 order by id desc")]

    def resolve_need(self, nid):
        with self.lock:
            self.db.execute("update needs_jack set done=1 where id=?", (nid,))

    # ---- telemetry (machine heartbeat from each agent's telemetryd) ---------------------
    def ingest(self, name, blob):
        with self.lock:
            self.db.execute("insert into telemetry(agent, blob, at) values(?,?,?) "
                            "on conflict(agent) do update set blob=excluded.blob, at=excluded.at",
                            (name, json.dumps(blob), self.clock()))

    def telemetry(self, name):
        with self.lock:
            r = self.db.execute("select blob, at from telemetry where agent=?", (name,)).fetchone()
            if not r:
                return None
            d = json.loads(r["blob"]); d["_at"] = r["at"]; return d

    def _focus(self, name):
        """What an agent is doing right now: its active task, and its live activity title if reporting."""
        t = self.db.execute("select id, title from tasks where owner=? and status in ('working','verifying') "
                            "order by touched desc limit 1", (name,)).fetchone()
        r = self.db.execute("select blob, at from telemetry where agent=?", (name,)).fetchone()
        doing, fresh = None, False
        if r:
            b = json.loads(r["blob"])
            act = b.get("activity") or {}
            doing = act.get("current") if isinstance(act, dict) else None
            fresh = (self.clock() - (r["at"] or 0)) < 120
        return {"task": ({"id": t["id"], "title": t["title"]} if t else None), "doing": doing, "reporting": fresh}

    def board(self):
        with self.lock:
            out = []
            for a in self.db.execute("select * from agents where kind!='jack' order by name"):
                cur = self._inflight(a["name"])
                queue = self.db.execute("select count(*) from items where too=? and status='queued'", (a["name"],)).fetchone()[0]
                out.append({"name": a["name"], "kind": a["kind"], "state": a["state"], "queue": queue,
                            "current": {"id": cur["id"], "text": cur["text"][:200], "sent_at": cur["sent_at"]} if cur else None,
                            "last_in": a["last_in"], "last_out": a["last_out"], "login_expires": a["login_expires"],
                            "product": a["current_product"], "role": a["current_role"], "onboarded": a["onboarded"],
                            "focus": self._focus(a["name"])})
            return {"now": self.clock(), "agents": out, "needs_jack": self.needs_jack(),
                    "revenue": self.revenue(), "products": self.portfolio()}

    def portfolio(self):
        with self.lock:
            out = []
            for p in self.db.execute("select * from products order by id"):
                projects = []
                for pr in self.db.execute("select * from projects where product=? order by id", (p["id"],)):
                    tasks = [self.task(t["id"]) for t in self.db.execute("select id from tasks where project=? order by id", (pr["id"],))]
                    projects.append({"id": pr["id"], "name": pr["name"], "tasks": tasks})
                rev = self.db.execute("select coalesce(sum(amount),0) s from sales where product=?", (p["name"],)).fetchone()["s"]
                out.append({"id": p["id"], "name": p["name"], "brief": p["brief"], "pm": p["pm"], "metric": p["metric"],
                            "budget": p["budget"], "kill_date": p["kill_date"], "status": p["status"],
                            "revenue": rev, "projects": projects})
            return out


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
            tok = auth[7:] if auth.startswith("Bearer ") else self.headers.get("X-Agent-Token", "")
            name = hub.agent_by_token(tok) if tok else None
            if not name:
                self._json(401, {"error": "401: bad or missing token"})
            else:
                hub.note_onboarded(name)       # a token call proves fleet is installed and reaching the hub
            return name

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path in ("/fleet.py", "/telemetryd.py", "/setup.py"):   # agent code (self-serve); not secret
                    src = os.path.join(HERE, u.path.lstrip("/"))
                    if not os.path.exists(src):
                        src = os.path.join(HERE, "..", "agents", u.path.lstrip("/"))
                    body = open(src, "rb").read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/x-python; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif u.path in ("/", "/index.html"):
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
                elif u.path == "/api/telemetry":
                    self._jack() and self._json(200, hub.telemetry(q.get("agent", "")) or {})
                elif u.path == "/api/item":
                    self._jack() and self._json(200, hub.item(int(q.get("id", 0))) or {})
                elif u.path == "/api/inbox":
                    name = self._agent()
                    name and self._json(200, {"item": hub.inbox(name)})
                elif u.path == "/api/status":
                    name = self._agent()
                    if name:
                        a = hub._agent(name)
                        self._json(200, {"agent": name, "product": a["current_product"], "role": a["current_role"],
                            "queue": [{k: i[k] for k in ("id", "frm", "text", "status")}
                                      for i in hub.items_for(name) if i["status"] in ("queued", "sent")]})
                elif u.path == "/api/secret":
                    name = self._agent()
                    if name:
                        try:
                            self._json(200, {"value": hub.secret_get(q.get("name", ""), name)})
                        except PermissionError as e:
                            self._json(403, {"error": str(e)})
                elif u.path == "/api/brain":
                    name = self._agent()
                    name and self._json(200, hub.brain_for(name) or {})
                elif u.path == "/api/vault":
                    self._jack() and self._json(200, {"reads": hub.secret_reads(), "secrets": hub.secret_names()})
                elif u.path == "/api/council":
                    self._jack() and self._json(200, hub.council(int(q.get("id", 0))) or {})
                elif u.path == "/api/councils":
                    self._jack() and self._json(200, {"councils": hub.councils()})
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
                        if b["to"] == "all":
                            self._json(200, {"council": hub.ask_all(name, b["text"], key=b.get("key"))})
                        else:
                            self._json(200, {"id": hub.ask(name, b["to"], b["text"], b.get("key"))})
                elif u.path == "/api/reply":
                    name = self._agent()
                    if name:
                        b = self._body()
                        hub.reply(name, int(b["item"]), b["text"])
                        self._json(200, {"ok": True})
                elif u.path == "/api/secret":
                    name = self._agent()
                    if name:
                        b = self._body()
                        scope = {"agent": f"agent:{name}", "product": f"product:{hub._agent(name)['current_product']}",
                                 "fleet": "fleet"}.get(b.get("scope", "agent"), b["scope"])
                        hub.secret_put(b["name"], b["value"], scope, by=name)
                        self._json(200, {"ok": True})
                elif u.path == "/api/switched":
                    name = self._agent()
                    if name:
                        b = self._body()
                        self._json(200, {"ok": hub.record_switch(name, b["product"], b["role"], b["hash"])})
                elif u.path == "/api/ingest":              # an agent's telemetryd pushes its machine heartbeat
                    name = self._agent()
                    if name:
                        hub.ingest(name, self._body())
                        self._json(200, {"ok": True})
                elif u.path == "/api/claim":                # an agent registers itself (Jack's code), no hub push
                    b = self._body()
                    if hmac.compare_digest(b.get("code", ""), password):
                        self._json(200, {"token": hub.add_agent(b["name"], "muse")})
                    else:
                        self._json(403, {"error": "bad claim code"})
                elif u.path == "/api/jack/send":           # Jack messages an agent straight from the dashboard
                    if self._jack():
                        b = self._body()
                        a = hub._agent(b.get("to", ""))
                        if not a or a["state"] == "parked":
                            self._json(400, {"error": "unknown or parked agent"})
                        else:
                            self._json(200, {"id": hub.ask("jack", b["to"], b["text"])})
                elif u.path == "/api/jack/secret":
                    if self._jack():
                        b = self._body()
                        hub.secret_put(b["name"], b["value"], b.get("scope", "fleet"), by="jack")
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/dismiss":
                    if self._jack():
                        hub.resolve_need(int(self._body()["id"]))
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/task":
                    if self._jack():
                        b = self._body()
                        self._json(200, {"id": hub.add_task(int(b["project"]), b["title"], b.get("role", "developer"),
                                                            b.get("done_def", ""), blocked_by=b.get("blocked_by") or [])})
                elif u.path == "/api/jack/product":
                    if self._jack():
                        b = self._body()
                        self._json(200, {"id": hub.add_product(b["name"], brief=b.get("brief", ""),
                                                               metric=b.get("metric") or None, pm=b.get("pm") or None)})
                elif u.path == "/api/jack/project":
                    if self._jack():
                        b = self._body()
                        self._json(200, {"id": hub.add_project(int(b["product"]), b["name"])})
                elif u.path == "/api/jack/ask":            # Jack asks the whole fleet a question (council)
                    if self._jack():
                        b = self._body()
                        self._json(200, {"council": hub.ask_all("jack", b["question"], chair=b.get("chair") or None)})
                else:
                    self._json(404, {"error": "not found"})
            except (ValueError, KeyError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})

    return ThreadingHTTPServer((host, port), H)


def _onboard_message(h, cfg, name):
    """Build the trusted install the hub sends into an agent's fleet side chat.
    The agent downloads fleet.py from the hub (short, inspectable) rather than a pasted blob."""
    token = h.add_agent(name, "muse")                     # a fresh token for this agent
    url = cfg["public_url"]
    return (
        "[trusted: your fleet hub] You're joining the fleet bus; this replaces the Slack listener.\n"
        "Run exactly this, then reply with the final line it prints:\n\n"
        f"mkdir -p ~/.fleet && curl -fsS {url}/fleet.py -o ~/.fleet/fleet.py && "
        f"curl -fsS {url}/telemetryd.py -o ~/.fleet/telemetryd.py && "
        f"printf '%s' '{token}' > ~/.fleet/token && printf '%s' '{url}' > ~/.fleet/hub && "
        f"printf '%s' '{name}' > ~/.fleet/agent && chmod 600 ~/.fleet/token && "
        "( crontab -l 2>/dev/null | grep -vi slack-watch | crontab - ) 2>/dev/null; "
        "pkill -f telemetryd.py 2>/dev/null; nohup python3 ~/.fleet/telemetryd.py >/dev/null 2>&1 & "
        "sleep 2; python3 ~/.fleet/fleet.py status\n\n"
        "Feel free to read either file first — small stdlib scripts that talk to me over HTTPS. "
        "fleet.py is the message bus; telemetryd.py reports your machine health to the dashboard. "
        "From now on I reach you here, not through Slack, so you no longer need to run listen.py.")


def _revenue_fetch(h, cfg):
    """Pull sales from whatever payment keys are in the vault. Empty until Jack adds them."""
    import muse  # noqa
    rows = []
    try:
        sk = h.db.execute("select value from secrets where name='stripe-key'").fetchone()
        if sk:
            import urllib.request
            req = urllib.request.Request("https://api.stripe.com/v1/charges?limit=100",
                                         headers={"Authorization": "Bearer " + sk["value"]})
            with urllib.request.urlopen(req, timeout=20) as r:
                for c in json.load(r).get("data", []):
                    if c.get("paid") and not c.get("refunded"):
                        rows.append({"source": "stripe", "external_id": c["id"], "amount": c["amount"] / 100.0,
                                     "currency": c.get("currency", "usd"),
                                     "product": (c.get("metadata") or {}).get("product"), "at": c["created"]})
    except Exception:
        pass
    # Etsy: receipts need shop id + OAuth token in the vault (names etsy-shop, etsy-token); wired when added.
    return rows


def main(cfg_path, *args):
    cfg = json.load(open(cfg_path))
    import muse
    accounts = cfg["accounts"]
    parked = set(cfg.get("parked", []))
    transport = muse.MuseTransport(cfg["muse_cli"], accounts)
    h = Hub(cfg["db"], transport)
    for name in accounts:
        if not h._agent(name):
            h.add_agent(name, "muse")
    for name in parked:
        if h._agent(name):
            h._set("agents", name, state="parked")

    cmd = args[0] if args else None
    if cmd == "token":
        print(h.add_agent(args[1], cfg.get("kinds", {}).get(args[1], "poll")))
        return
    if cmd == "onboard":
        name = args[1]
        transport.deliver(name, _onboard_message(h, cfg, name))
        print(f"sent onboarding to {name}; it will install fleet and call the hub back")
        return
    if cmd == "cutover":
        go = "--go" in args
        targets = [n for n in accounts if n not in parked]
        if not go:
            print(f"DRY RUN — would onboard {len(targets)} agents (parked agents are skipped). Add --go to send.")
            return
        for name in targets:
            transport.deliver(name, _onboard_message(h, cfg, name))
            print(f"onboarded {name}")
        return
    if cmd in ("product", "project", "task", "seat", "role", "place", "park", "wake", "secret"):
        _admin(h, cmd, args[1:])
        return

    log = open(cfg.get("log", os.path.join(os.path.dirname(cfg["db"]), "hub.log")), "a", buffering=1)

    def loop():
        last_renew = last_rev = 0
        while True:
            try:
                if time.time() - last_renew > 86400:
                    h.renew_logins(accounts)
                    last_renew = time.time()
                if time.time() - last_rev > 3600:
                    h.pull_revenue(lambda: _revenue_fetch(h, cfg))
                    last_rev = time.time()
                h.tick()
            except Exception:
                log.write(time.strftime("%F %T ") + traceback.format_exc())
            time.sleep(15)

    threading.Thread(target=loop, daemon=True).start()
    log.write(time.strftime("%F %T ") + f"hub up on {cfg.get('host', '127.0.0.1')}:{cfg['port']}\n")
    serve(h, cfg.get("host", "127.0.0.1"), cfg["port"], cfg["password"]).serve_forever()


def _admin(h, cmd, a):
    if cmd == "product":
        print(h.add_product(a[0], brief=a[1] if len(a) > 1 else "", metric=a[2] if len(a) > 2 else None))
    elif cmd == "project":
        print(h.add_project(int(a[0]), a[1]))
    elif cmd == "task":
        print(h.add_task(int(a[0]), a[1], role=a[2], done_def=a[3],
                         blocked_by=[int(x) for x in a[4].split(",")] if len(a) > 4 and a[4] else ()))
    elif cmd == "seat":
        h.seat(a[0], a[1])
    elif cmd == "role":
        h.set_role(a[0], sys.stdin.read().strip() if len(a) < 2 else a[1])
    elif cmd == "place":
        h.place(a[0], a[1], a[2])
    elif cmd == "park":
        h._set("agents", a[0], state="parked")
    elif cmd == "wake":
        h._set("agents", a[0], state="active")
    elif cmd == "secret":
        h.secret_put(a[0], sys.stdin.read().strip(), a[1], by="jack")
    print("ok")


if __name__ == "__main__":
    main(*sys.argv[1:])
