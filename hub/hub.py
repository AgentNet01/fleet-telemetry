"""Fleet hub: delivers messages between agents, reads replies itself, retries, never loops.

    python hub.py hub.json              run (HTTP API + dashboard + delivery loop + daily login renewal)
    python hub.py hub.json token NAME   print a new token for an agent (replaces its old one)

Rules (company_spec.md; hub_plan.md §5/§7): the hub only writes in each agent's fleet side chat.
Tasks, verifies and notes are delivered once; the work is tracked on the task row and moved by the
holder's `fleet task …` commands, never by a timer. A request/question is one item in flight per
agent; a reply is every genuine message after ours, closed after 60 s of quiet; unanswered after
20 min it fails and the asker is told (the same text is never sent twice). Replies close items and
never open them (only `ask` does); a request made while handling another is one level deeper;
deeper than 5 goes to Needs Jack. Holders of an open task get a rotating nudge after 12 h without
progress; idle agents are never woken — the CEO hears when more than three sit idle over 12 h.
"""
import base64
import calendar
import hashlib
import hmac
import html
import json
import os
import re
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
FLEET_REPO = "https://github.com/AgentNet01/fleet-telemetry.git"   # public: every agent can clone it, no GitHub login


def fleet_rev():
    """The version fleet.py reports (sha256 of the file): agents on another one are behind the hub."""
    with open(os.path.join(HERE, "fleet.py"), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def _evidence_ok(link):
    """A piece of evidence counts if its URL answers (HTTP < 400). Real check; override in tests."""
    import urllib.request
    try:
        req = urllib.request.Request(link, method="HEAD", headers={"User-Agent": "fleet-hub"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status < 400
    except urllib.error.HTTPError as e:
        return e.code in (401, 403, 405, 429)    # the page is there but walls off bots (Etsy answers 403); 404 still fails
    except Exception:
        return False


def doc_source_ok(url):
    """The doc viewer fetches agents' Muse files and nothing else (it runs on Jack's machine)."""
    u = urlparse(url)
    return u.scheme == "https" and u.hostname == "muse.ai" and not u.username and u.path.startswith("/files/")


def doc_page(url, text):
    """A Markdown file shown as a page instead of downloaded. Agents write these, so the HTML is sanitised."""
    data = json.dumps(text).replace("<", "\\u003c")            # the text can't close the script it sits in
    name = html.escape(url.rsplit("/", 1)[-1])
    return (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><title>{name}</title>"
            "<style>:root{color-scheme:light dark}body{font:16px/1.6 system-ui;max-width:860px;margin:0 auto;padding:24px 16px;"
            "background:Canvas;color:CanvasText}pre,code{background:color-mix(in srgb,CanvasText 8%,Canvas);border-radius:4px}"
            "pre{padding:12px;overflow:auto}code{padding:1px 4px}table{border-collapse:collapse}td,th{border:1px solid "
            "color-mix(in srgb,CanvasText 25%,Canvas);padding:4px 8px}img{max-width:100%}.src{font-size:13px;opacity:.7}</style>"
            f"<p class=src>{name} · <a href='{html.escape(url)}'>download</a></p><main id=doc></main>"
            f"<script type=application/json id=md>{data}</script>"
            "<script src='https://cdn.jsdelivr.net/npm/marked@12/marked.min.js'></script>"
            "<script src='https://cdn.jsdelivr.net/npm/dompurify@3/dist/purify.min.js'></script>"
            "<script>const t=JSON.parse(document.getElementById('md').textContent);"
            "document.getElementById('doc').innerHTML=DOMPurify.sanitize(marked.parse(t));"
            "document.querySelectorAll('#doc a').forEach(a=>{a.target='_blank';a.rel='noopener'});</script>")


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
  current_product text, current_role text, onboarded real, seen_seq integer default 0, free_since real);
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
  evidence text, verified_by text, created real, touched real, verifier text);
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
create table if not exists suggestions(
  id integer primary key, frm text, product text, text text, status text default 'open',
  decided_by text, note text, at real, decided_at real);
create table if not exists nudges(agent text primary key, last_at real, idx integer default -1);
create table if not exists ceo_notes(id integer primary key, agents text, at real);
create table if not exists work(agent text, key text, at real, kind text, title text, status text, detail text,
  primary key(agent, key));
create table if not exists task_events(id integer primary key, task integer, agent text, what text, text text, at real);
create table if not exists dry_notes(product integer primary key, at real);
create table if not exists grants(agent text primary key, level text, by text, at real);
create table if not exists changes(id integer primary key, by text, line text, result text, at real);
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
    "alter table tasks add column verifier text",
    "alter table agents add column free_since real",
    "alter table agents add column team text",            # standing role (or 'generalist'); product comes per task
    "alter table tasks add column pin text",              # the one agent this task may go to, whatever its team
    "alter table switches add column from_product text",
    "alter table nudges add column streak integer default 0",   # reminders since the holder's last progress
    "alter table agents add column last_act real",        # the agent itself last did something: chat, reply or any fleet command
    "alter table items add column closed real",           # when it was answered or failed
    "alter table agents add column busy integer",         # Muse: a turn is running right now
    "alter table agents add column doing text",           # Muse: one line on what it's doing or last did
    "alter table agents add column doing_at real",        # Muse: when it last acted itself
    "alter table dry_notes add column stage text",        # planning round: 'pm' asked, then 'planner' asked
    "alter table dry_notes add column planner text",
    "alter table suggestions add column line text",
    "alter table agents add column powers_told text",
    "alter table tasks add column waiting_on text",       # who a parked task waits on: jack|darragh|<agent>|outside
    "alter table tasks add column waiting_for text",
    "alter table needs_jack add column task integer",     # a wait on Jack/Darragh: done on his list clears it
    "alter table agents add column fleet_rev text",       # version of the fleet command it last called with
    "alter table agents add column fleet_told real",
    "alter table needs_jack add column agent text",       # who raised it: Jack's reply goes to them
    "alter table products add column kind text default 'product'",   # 'tool': shared by every product, not sold
    "create table if not exists approvals(id text primary key, agent text, label text, detail text, options text, expires real)",     # the powers text this agent was last told       # a PM's company command waiting on the CEO's review
]
WORKERS = ("muse", "poll")            # kinds that take tasks; 'slack' (dot) and 'jack' (the board) don't
PUSH = ("muse", "slack")              # kinds the hub sends to; 'poll' agents fetch with `fleet inbox`
ONE_SHOT = ("note", "task", "verify", "nudge", "plan")
# Jack, Oct 13: "I don't want the agents coming to us unless they're literally blocked"
OPERATOR_ONLY = ("Go to an operator (Jack or Darragh) only when you're truly blocked on something that needs a real person: "
                 "their ID, SSN or tax details, a phone number or 2FA code, a payment or purchase, or an account only they "
                 "can open. Everything else — choices, sign-offs, which option to take — decide yourself or with your PM; "
                 "don't send it to them.")
NUDGE_AFTER = 3600                     # a task holder silent this long is reminded, then its PM an hour later
IDLE_AFTER = 12 * 3600
STANDIN_AFTER = 3 * 3600              # a CEO silent this long is stood in for by seat ceo_backup
# tasks in an active product: a paused (or removed) product is kept, but nobody is handed its work
LIVE_TASKS = "from tasks t join projects j on t.project=j.id join products p on j.product=p.id where p.status='active'"
REVIEW_WAIT = 2 * 3600                # a PM's company change the CEO hasn't answered goes ahead after this
PLAN_WAIT = 2 * 3600                  # a PM silent this long on an unplanned product: a free agent plans it
CEO_IDLE_COUNT = 3                    # more than this many idle workers → the CEO hears about it
NUDGES = (                            # same meaning, different words: agents tune out a repeated message
    "Checking in on your open fleet task — how's it going?",
    "Quick nudge: this task is still open on your plate.",
    "Still on this one? A short progress note helps the team plan around you.",
    "Reminder — this fleet task is waiting on you.",
)  # delivered once; the work itself is tracked on the task row
SMART_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
DEFAULT_ROLES = {
    "designer": "You are the product designer for this product: how it looks, reads and feels to a buyer. "
                "Show your work as files or links, never just a description.",
    "engineer": "You are the engineer for this product: you build and automate what it needs. "
                "Prove it works with something a reviewer can run or open.",
    "marketer": "You are the marketer for this product: you find buyers and write what reaches them "
                "(listings, posts, emails). Measure what you can.",
    "optimizer": "You are the optimizer for this product: study what's working and what isn't, and send "
                 "concrete suggestions to the PM and CEO with `fleet suggest`. They decide; you don't change "
                 "the workflow yourself.",
}


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


class NeedsReview(PermissionError):
    """A PM's company-level command: allowed, once the CEO has had a chance to say no."""


class Hub:
    def __init__(self, db_path, transport, clock=time.time, evidence_ok=None):
        self.db_path, self.transport, self.clock = db_path, transport, clock
        self.evidence_ok = evidence_ok or _evidence_ok
        self.db = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self._polling = {}               # agent -> lock held while its chat is being read
        self._sending = {}               # agent -> lock held while a message to it is going out
        self._fails = {}                 # agent -> consecutive servicing failures (transient blips don't page Jack)
        self.db.executescript(SCHEMA)
        for m in MIGRATIONS:
            try:
                self.db.execute(m)
            except sqlite3.OperationalError:
                pass                     # column already there
        if not self.db.execute("select 1 from roles limit 1").fetchone():
            for name, soul in DEFAULT_ROLES.items():
                self.db.execute("insert into roles(name, soul) values(?,?)", (name, soul))
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

    def note_onboarded(self, name, rev=None):
        with self.lock:
            self.db.execute("update agents set onboarded=? where name=? and onboarded is null", (self.clock(), name))
            if rev:
                self.db.execute("update agents set fleet_rev=? where name=? and fleet_rev is not ?", (rev, name, rev))

    def acted(self, name):
        with self.lock:
            self._acted(name)

    def _acted(self, name, at=None):
        # "unresponsive" means the agent isn't acting at all; anything it does itself disproves that
        self.db.execute("update agents set last_act=?, state=case when state='unresponsive' then 'active' else state end "
                        "where name=?", (self.clock() if at is None else at, name))

    OBSERVE_EVERY = 120                  # Muse activity is read on its own thread, so delivery never waits on it

    def observe(self):
        """Read what Muse shows each agent doing — mid-turn, its own last action — beyond its fleet chat."""
        with self.lock:
            names = [r["name"] for r in self.db.execute("select name from agents where kind='muse' and state!='parked'")]
        for name in names:
            try:
                d = self.transport.activity(name)                   # muse-cli I/O, never under the lock
            except Exception:
                continue                                            # ponytail: keep the last reading; delivery errors already page Jack
            if not d:
                continue
            with self.lock:
                self._set("agents", name, busy=int(bool(d["busy"])), doing=d.get("line"), doing_at=d.get("line_at", d.get("at")))
                seen = self.clock() if d["busy"] else d.get("at")
                if seen and seen > (self._agent(name)["last_act"] or 0):
                    if self.clock() - seen <= 2 * RESEND:
                        self._acted(name, seen)             # recent: it's acting, so not unresponsive
                    else:
                        self._set("agents", name, last_act=seen)   # old news: on record, revives nobody

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

    def _note(self, to, headline, text, ref=None):
        if self._agent(to) and self._agent(to)["kind"] != "jack":
            self.db.execute("insert into items(kind, frm, too, text, depth, status, created, ref) values('note','hub',?,?,0,'queued',?,?)",
                            (to, f"{headline}\n{text}", self.clock(), ref))

    def _sub_answer(self, agent, it):
        """The answer to a question the agent asked while working on `it`: it needs that to finish `it`, so it can't wait behind it."""
        return self.db.execute("select n.* from items n join items c on n.ref=c.id where n.too=? and n.kind='note' "
                               "and n.status='queued' and c.parent=? order by n.id limit 1", (agent, it["id"])).fetchone()

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
        if kind == "nudge":
            return body
        if kind == "note":
            first, _, rest = body.partition("\n")
            asked = it["ref"] and self.db.execute("select parent from items where id=?", (it["ref"],)).fetchone()
            if asked and asked["parent"] and self.item(asked["parent"])["status"] == "sent":
                # this text lands while that request is still open, so any reply goes to its sender: say so
                return (f"{head}[fleet #{iid} · {first}]\n{rest}\n— This is for your open #{asked['parent']}. "
                        f"Don't acknowledge it; reply when #{asked['parent']} is done, with the result.")
            return f"{head}[fleet #{iid} · {first}]\n{rest}\n— No reply needed."
        if kind == "task":
            t = it["ref"]
            return (f"{head}[fleet · task #{t}]\n{body}\n"
                    f"— It's yours until it's done. Post progress with `fleet task note {t} \"...\"`; when it's "
                    f"finished run `fleet task done {t} <link>` with a link to the evidence (commit, file or URL). "
                    f"{OPERATOR_ONLY} When you hit one, put it on their list at once: "
                    f"`fleet task operator {t} \"<what to do, why, link>\"`.")
        if kind == "verify":
            t = it["ref"]
            return (f"{head}[fleet · verify task #{t}]\n{body}\n"
                    f"— Check it yourself against the definition of done, then run `fleet task verify {t} pass` "
                    f"or `fleet task verify {t} fail \"<reason>\"`. Also fail it if it's blocked on something only an "
                    f"operator can provide (ID, SSN or tax details, a phone number or 2FA, a payment, an account only they "
                    f"can open) that isn't on their list yet, or if it put a choice on their list that an agent should have "
                    f"made (`fleet task show {t}` shows the list).")
        if kind == "plan":
            return f"{head}[fleet #{iid} · planner]\n{body}"
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
        if direction == "out":
            self._acted(agent)

    def _send(self, it, resent=False):
        text = self._format(it, resent)
        mark = self.transport.deliver(it["too"], text)          # muse-cli I/O — never under the lock
        with self.lock:
            self._set("items", it["id"], status="sent", sent_at=self.clock(), tries=it["tries"] + 1, mark=mark)
            self._log(it["id"], it["too"], "in", text)
            if it["kind"] in ONE_SHOT:
                self._set("items", it["id"], status="answered")  # no reply expected; don't hold the slot

    def _answered(self, it, reply):
        self._set("items", it["id"], status="answered", reply=reply, closed=self.clock())
        self._set("agents", it["too"], state="active")
        kind = it["kind"]
        if kind == "request" and it["frm"] != "hub":
            self._note(it["frm"], f"reply from {it['too']} to your #{it['id']}", reply, ref=it["id"])
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
            self._assign_verifiers()
            self._track_free()
            self._nudge()
            self._ceo_idle()
            self._watch_chair()
            self._watch_powers()
            self._watch_fleet()
            self._watch_jobs()
            self._reviews()
            self._dry()
            agents = [dict(a) for a in self.db.execute(
                "select * from agents where kind in ('muse','poll','slack') and state != 'parked' order by name")]
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
            if self._fails.pop(name, 0):     # it was failing and just recovered: say so, clear its alert
                with self.lock:
                    self.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)",
                                    (name, "recovered", self.clock()))
                    self.db.execute("update needs_jack set done=1 where done=0 and text like ?",
                                    (f"{name} keeps failing to service%",))
        except Exception as e:
            n = self._fails[name] = self._fails.get(name, 0) + 1
            try:
                with self.lock:
                    # every error is logged for transparency; only sustained failure pages Jack, and
                    # the headline is stable per agent so a stuck account files exactly one open item.
                    self.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)",
                                    (name, f"#{n} {str(e)[:160]}", self.clock()))
                    head = f"{name} keeps failing to service"
                    if n >= self.FAIL_ESCALATE and not self.db.execute(
                            "select 1 from needs_jack where done=0 and text like ?", (head + "%",)).fetchone():
                        self._needs_jack(f"{head}: {str(e)[:200]}")
            except Exception:
                pass

    def _poll_agent(self, a, now):
        if a["kind"] not in PUSH:
            return
        lk = self._polling.setdefault(a["name"], threading.Lock())
        if not lk.acquire(blocking=False):          # someone is already reading this agent's chat
            return
        try:
            self._poll_one(a, now)
        finally:
            lk.release()

    def _poll_one(self, a, now):
        name = a["name"]
        with self.lock:
            it = self._inflight(name)
            seen = self._agent(name)["seen_seq"] or 0      # fresh: the reply watcher may have moved it
            it_mark = it["mark"] if it else None
        fresh = self.transport.replies(name, seen)                   # I/O, no lock
        rep = self.transport.replies(name, it_mark) if (fresh and it_mark is not None) else None
        with self.lock:
            it = self._inflight(name)
            if fresh:
                for _, text in fresh:
                    self._log(it["id"] if it else None, name, "out", text)
                    if a["kind"] == "slack":
                        self._run_lines(name, text)
                self._set("agents", name, seen_seq=max(s for s, _ in fresh), state="active")
                if it and rep is not None:
                    self._set("items", it["id"], nreplies=len(rep), last_reply=now,
                              reply="\n\n".join(t for _, t in rep))
                    it = self.item(it["id"])
            if it and it["last_reply"] and now - it["last_reply"] >= QUIET:
                self._answered(it, it["reply"])

    REPLY_WATCH = (5, 120)               # after Jack sends: check that agent for a reply every 5 s for 2 min

    def deliver_now(self, name):
        """Send what's waiting for this agent right away, then watch for its reply, in the background."""
        a = self._agent(name)
        if not (a and a["kind"] in PUSH and a["state"] != "parked"):
            return

        def run():
            self._guarded(name, lambda: self._deliver_agent(name, a["kind"], self.clock()))
            every, total = self.REPLY_WATCH
            end = time.time() + total
            while time.time() < end:
                time.sleep(every)
                self._guarded(name, lambda: self._poll_agent(dict(self._agent(name)), self.clock()))
                it = self._inflight(name)
                if not it or it["last_reply"]:
                    break
        threading.Thread(target=run, daemon=True).start()

    def _deliver_agent(self, name, kind, now):
        # one send at a time per agent: the loop and a Send click never both deliver the same message
        lk = self._sending.setdefault(name, threading.Lock())
        if not lk.acquire(blocking=False):
            return
        try:
            self._deliver_one(name, kind, now)
        finally:
            lk.release()

    def _deliver_one(self, name, kind, now):
        with self.lock:
            it = self._inflight(name)
            nextitem = None
            # never resend the same text: an unanswered request/question fails after 20 min with no sign of
            # life — counted from the agent's last action or the last answer to a question it asked about it,
            # and never while such a question is still open (that agent is working, waiting on someone else)
            if it and not it["last_reply"]:
                # only a question actually with a serviced agent counts: one queued, or sent to a parked agent or the
                # board, may never move, and its own 20-min clock is what keeps this one bounded
                asking = self.db.execute("select 1 from items c join agents a on a.name=c.too where c.parent=? and c.status='sent' "
                                         "and a.kind in ('muse','poll','slack') and a.state!='parked'", (it["id"],)).fetchone()
                answered = self.db.execute("select max(closed) from items where parent=?", (it["id"],)).fetchone()[0]
                alive = max(it["sent_at"], self._agent(name)["last_act"] or 0, answered or 0)
                if not asking and now - alive >= 2 * RESEND:
                    self._fail_item(it, name)
                    it = None
            if kind in PUSH:
                nextitem = self._sub_answer(name, it) if it else self._next(name)
        if nextitem is not None:
            self._send(nextitem)

    def _fail_item(self, it, name):
        self._set("items", it["id"], status="failed", closed=self.clock())
        if (self._agent(name)["last_act"] or 0) < it["sent_at"]:     # did nothing at all since it arrived
            self._set("agents", name, state="unresponsive")
        kind = it["kind"]
        if kind == "request" and it["frm"] != "hub":
            self._note(it["frm"], f"{name} didn't reply to your #{it['id']}", it["text"], ref=it["id"])
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
            sub = self._sub_answer(agent, it) if it else None
            if sub:
                self._set("items", sub["id"], status="answered", sent_at=self.clock(), tries=1)
                self._log(sub["id"], agent, "in", self._format(sub))
                it = sub
            if not it:
                it = self._next(agent)
                if not it:
                    return None
                self._set("items", it["id"], status="answered" if it["kind"] in ONE_SHOT else "sent",
                          sent_at=self.clock(), tries=1)
                self._log(it["id"], agent, "in", self._format(it))
            return {"id": it["id"], "kind": it["kind"], "from": it["frm"], "text": it["text"]}

    def status(self, name):
        a = self._agent(name)
        tasks = [self.task(t["id"]) for t in self._open_tasks(name)]
        mine = self.secrets_for(name)
        # ponytail: listed in status so agents on an older fleet.py find their logins with no update
        logins = (f"\nYour logins and keys in the vault: {', '.join(mine)}. Read one with: fleet secret get <name> "
                  "(JSON with the email, password and username).") if mine else ""
        return {"agent": name, "product": a["current_product"], "role": a["current_role"], "can": self.powers(name) + logins,
                "tasks": [{k: t[k] for k in ("id", "title", "status", "product", "role")} for t in tasks],
                "queue": [{k: i[k] for k in ("id", "frm", "text", "status")}
                          for i in self.items_for(name) if i["status"] in ("queued", "sent")]}

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

    def add_task(self, project_id, title, role, done_def, blocked_by=(), owner=None, by=None):
        with self.lock:
            if by is not None:
                pr = self.db.execute("select p.name from projects j join products p on j.product=p.id where j.id=?",
                                     (project_id,)).fetchone()
                if not self.may_manage(by, pr["name"] if pr else None):
                    raise PermissionError("only Jack, Darragh, the CEO or this product's PM can add its tasks")
            st = self.db.execute("select p.name, p.status from projects j join products p on j.product=p.id where j.id=?",
                                 (project_id,)).fetchone()
            if st and st["status"] != "active":
                raise ValueError(f"{st['name']} is {st['status']}: no new tasks (set it active first)")
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
            if not r or r["status"] not in ("done", "cancelled"):
                return False
        return True

    def _idle(self, product=None, role=None, pin=None):
        """An active, un-parked agent with nothing in flight and nothing queued, optionally in a given brain.
        A pinned task skips team routing: only the named agent counts."""
        for a in self.db.execute(f"select * from agents where kind in {WORKERS} and state='active' order by name").fetchall():
            if self._open_tasks(a["name"]):
                continue                             # only holding a task makes an agent busy; a pending question doesn't
            if pin and a["name"] != pin:
                continue
            if product and a["current_product"] != product:
                continue
            if role and (a["current_role"] != role or not (pin or self._fits(a, role))):
                continue
            yield a["name"]

    @staticmethod
    def _fits(a, role):
        """Skill routing: a task's role goes to that team, or to a generalist (an unset team counts as one)."""
        return a["team"] in (None, "", "generalist", role)

    def _assign_tasks(self):
        # status follows the blockers both ways: work whose blocker reopened goes back to 'blocked' and frees its
        # holder; a task created for someone starts with them once it can; ready+unowned goes to an idle agent
        for t in self.db.execute("select t.*, p.status as product_status from tasks t join projects j on t.project=j.id "
                                 "join products p on j.product=p.id where p.status != 'removed' "
                                 "and t.status in ('open','blocked','ready','working')").fetchall():
            why = ("its product is paused" if t["product_status"] != "active" else
                   None if t["waiting_on"] else
                   "a task it depends on isn't done any more" if not self._blockers_done(t) else "")
            if why is None or why:
                if t["status"] != "blocked":
                    # on hold: back to the same holder once it can move (pin), and the holder is told, not left guessing
                    self._set("tasks", t["id"], status="blocked", owner=None, pin=t["pin"] or t["owner"], touched=self.clock())
                    if t["owner"]:
                        self._task_event(t["id"], t["owner"], "blocked", f"{why or 'waiting on ' + t['waiting_on']}; holder freed")
                        self.db.execute("update items set status='dropped', closed=? where kind='task' and ref=? and status='queued'",
                                        (self.clock(), t["id"]))
                        if why:                          # a wait was the holder's own call: nothing to tell it
                            self._note(t["owner"], f"task #{t['id']} “{t['title']}” is on hold",
                                       f"{why[0].upper() + why[1:]}, so it's on hold and you're free for other work. "
                                       "It comes back to you once it can move.")
                continue
            if t["status"] == "working":
                continue
            product = self._task_product(t["id"])
            pin = t["pin"] or t["owner"]             # named for someone but not started: theirs, through the normal switch
            self._set("tasks", t["id"], status="ready", owner=None, pin=pin)
            owner = next(self._idle(product, t["role"], pin), None)
            if owner:
                self._set("tasks", t["id"], owner=owner, status="working", touched=self.clock())
                self._task_event(t["id"], owner, "assigned")
                self.db.execute(
                    "insert into items(kind, frm, too, text, ref, depth, status, created) values('task','hub',?,?,?,0,'queued',?)",
                    (owner, f"{t['title']} — {product}, as {t['role']}.\nDone when: {t['done_def']}", t["id"], self.clock()))

    # ---- task lifecycle: one holder; `fleet task note|done|verify|release` move it ----------
    def _open_tasks(self, agent):
        return self.db.execute("select * from tasks where (owner=? and status='working') "
                               "or (verifier=? and status='verifying') order by id", (agent, agent)).fetchall()

    def _task_row(self, tid):
        t = self.db.execute("select * from tasks where id=?", (tid,)).fetchone()
        if not t:
            raise ValueError(f"no task #{tid}")
        return t

    def is_board(self, who):
        a = self._agent(who) if who else None
        return who == "jack" or bool(a and a["kind"] == "jack")

    def _ceo_level(self, who):
        return bool(who) and (who == self._chair() or bool(
            self.db.execute("select 1 from grants where agent=? and level='ceo'", (who,)).fetchone()))

    def may_manage(self, who, product=None):
        """Tasks in a product: the board, the CEO (and anyone granted CEO level), and that product's PM."""
        if self.is_board(who) or self._ceo_level(who):
            return True
        p = self.db.execute("select pm from products where name=?", (product,)).fetchone() if product else None
        return bool(who and p and (p["pm"] == who or self.db.execute(
            "select 1 from grants where agent=? and level=?", (who, "plan:" + product)).fetchone()))

    def _task_event(self, tid, agent, what, text=""):
        self.db.execute("insert into task_events(task, agent, what, text, at) values(?,?,?,?,?)",
                        (tid, agent, what, text, self.clock()))

    def task_note(self, agent, tid, text):
        with self.lock:
            t = self._task_row(tid)
            if t["owner"] != agent or t["status"] != "working":
                raise PermissionError(f"#{tid} isn't a task you're working on")
            self._set("tasks", tid, progress_note=text, touched=self.clock())
            self._log(None, agent, "out", f"task #{tid} note: {text}")
            self._task_event(tid, agent, "note", text)

    def task_for_jack(self, agent, tid, text):
        """A step only Jack/Darragh can do, put on their list with the task it came from; the task keeps going."""
        with self.lock:
            t = self._task_row(tid)
            if t["owner"] != agent or t["status"] != "working":
                raise PermissionError(f"#{tid} isn't a task you're working on")
            self.db.execute("insert into needs_jack(text, at, task, agent) values(?,?,?,?)",
                            (f"From task #{tid} “{t['title']}” ({agent}): {text.strip()}", self.clock(), tid, agent))
            self._task_event(tid, agent, "for jack", text)

    def operator_items(self, tid):
        with self.lock:
            return [{"text": r["text"], "done": bool(r["done"])}
                    for r in self.db.execute("select text, done from needs_jack where task=? order by id", (tid,))]

    def task_done(self, agent, tid, link):
        with self.lock:
            t = self._task_row(tid)
            if t["owner"] != agent or t["status"] != "working":
                raise PermissionError(f"#{tid} isn't a task you're working on")
            # ponytail: a name match, not intent (verifiers catch the rest); a task that names the operators but needs
            # nothing from them files one "nothing to do" step
            if re.search(r"\b(jack|darragh|operators?)\b", f"{t['title']} {t['done_def']}", re.I) and \
                    not self.db.execute("select 1 from needs_jack where task=?", (tid,)).fetchone():
                raise ValueError(f"#{tid} is work for an operator (Jack or Darragh), and nothing from it is on their list. "
                                 f"Put each step they must do there first, one per step, in plain words with the link:\n"
                                 f"  fleet task operator {tid} \"<what to do, why, link>\"\nthen run task done again.")
        if not self.evidence_ok(link):                                  # network check, outside the lock
            raise ValueError(f"the evidence link doesn't open: {link}")
        with self.lock:
            self._set("tasks", tid, status="verifying", evidence=link, verifier=None, touched=self.clock())
            self._log(None, agent, "out", f"task #{tid} done: {link}")
            self._task_event(tid, agent, "done", link)
            # work often waits on a task without a formal blocker: tell the project's other holders and its PM
            pm = self.db.execute("select p.pm from projects j join products p on j.product=p.id where j.id=?",
                                 (t["project"],)).fetchone()
            peers = [r["owner"] for r in self.db.execute(
                "select distinct owner from tasks where project=? and status='working' and owner is not null", (t["project"],))]
            for who in dict.fromkeys(peers + [pm["pm"] if pm else None]):
                if who and who != agent:
                    self._note(who, f"{agent} finished task #{tid} \"{t['title']}\"",
                               f"Result: {link}\nIf your work was waiting on this, carry on. — No reply needed.")
            self._assign_verifiers()

    def task_verify(self, agent, tid, ok, reason=""):
        with self.lock:
            t = self._task_row(tid)
            if t["status"] != "verifying" or t["verifier"] != agent:
                raise PermissionError(f"#{tid} isn't waiting on your verification")
            self._log(None, agent, "out", f"task #{tid} verify: {'pass' if ok else 'fail — ' + reason}")
            self._task_event(tid, agent, "verified" if ok else "sent back", reason)
            if ok:
                self._set("tasks", tid, status="done", verified_by=agent, touched=self.clock())
            else:
                self._set("tasks", tid, status="working", verifier=None, touched=self.clock(),
                          progress_note=f"verify failed ({agent}): {reason}")
                self._note(t["owner"], f"task #{tid} didn't pass verification",
                           f"{t['title']}\n{agent}: {reason}\nFix it, then `fleet task done {tid} <link>` again.")

    def task_wait(self, agent, tid, who, what):
        """The holder can't move until someone else acts: the task is parked for it (pin) and it takes other work.
        Jack/Darragh see it on their list; another agent is asked; anything else ('outside') the holder resumes."""
        with self.lock:
            t = self._task_row(tid)
            if t["owner"] != agent or t["status"] != "working":
                raise PermissionError(f"#{tid} isn't a task you're working on")
            who = (who or "outside").strip()
            board = who.lower() in ("jack", "darragh", "board", "operator")
            if not board and who != "outside" and not self.db.execute("select 1 from agents where name=?", (who,)).fetchone():
                raise ValueError(f"no agent {who}: wait on operator (Jack or Darragh), an agent's name, or outside")
            note = f"waiting on {who}: {what}"
            self._set("tasks", tid, waiting_on=who, waiting_for=what, progress_note=note, touched=self.clock(),
                      status="blocked", owner=None, pin=agent)          # freed now, not at the next tick
            self.db.execute("update items set status='dropped', closed=? where kind='task' and ref=? and status='queued'",
                            (self.clock(), tid))
            self._task_event(tid, agent, "waiting", note)
            self._log(None, agent, "out", f"task #{tid} {note}")
            if board:
                self.db.execute("insert into needs_jack(text, at, task, agent) values(?,?,?,?)",
                                (f"Task #{tid} “{t['title']}” ({agent}) is waiting on you: {what}. "
                                 "Reply, or mark this done when it's sorted, and the task goes back to them.", self.clock(), tid, agent))
            elif who != "outside":
                self.db.execute("insert into items(kind, frm, too, text, depth, status, created) values('note',?,?,?,0,'queued',?)",
                                (agent, who, f"Task #{tid} “{t['title']}” is waiting on you: {what}\n"
                                 f"When you've done it, run: fleet task resume {tid}", self.clock()))

    def task_resume(self, by, tid):
        """A wait is over: the holder it was parked for, whoever it waited on, the PM/CEO or the board clears it."""
        with self.lock:
            t = self._task_row(tid)
            if not t["waiting_on"]:
                raise ValueError(f"#{tid} isn't waiting on anyone")
            if by not in (t["pin"], t["owner"], t["waiting_on"]) and not self.may_manage(by, self._task_product(tid)):
                raise PermissionError(f"only {t['pin']}, {t['waiting_on']}, the PM, the CEO or the board can resume #{tid}")
            self._resume(t, by)

    def _end_waits(self, where, args):
        """A task released, reassigned or removed stops waiting, and Jack's row for it closes."""
        self.db.execute(f"update needs_jack set done=1 where done=0 and task in (select id from tasks where {where})", args)
        self.db.execute(f"update tasks set waiting_on=null, waiting_for=null where waiting_on is not null and {where}", args)

    def _resume(self, t, by):
        self._set("tasks", t["id"], waiting_on=None, waiting_for=None, progress_note=f"resumed by {by}", touched=self.clock())
        self._task_event(t["id"], by, "resumed")
        self.db.execute("update needs_jack set done=1 where task=? and done=0", (t["id"],))

    def task_release(self, by, tid):
        with self.lock:
            t = self._task_row(tid)
            if not self.may_manage(by, self._task_product(tid)):
                raise PermissionError("only Jack, Darragh, the CEO or this product's PM can release a task")
            self._end_waits("id=?", (tid,))
            self._set("tasks", tid, owner=None, verifier=None, status="ready", touched=self.clock(),
                      progress_note=f"released by {by}")
            self._task_event(tid, by, "released")

    def _assign_verifiers(self):
        for t in self.db.execute("select * from tasks where status='verifying' and verifier is null").fetchall():
            product = self._task_product(t["id"])
            free = [n for n in self._idle() if n != t["owner"]]
            same = [n for n in free if self._agent(n)["current_product"] == product]
            who = (same or free or [None])[0]
            if who:
                self._set("tasks", t["id"], verifier=who)
                self._task_event(t["id"], who, "verify")
                self.db.execute(
                    "insert into items(kind, frm, too, text, ref, depth, status, created) values('verify','hub',?,?,?,0,'queued',?)",
                    (who, f"{t['title']} — {product}, done by {t['owner']}.\nDone when: {t['done_def']}\n"
                          f"Evidence: {t['evidence']}", t["id"], self.clock()))

    # ---- keeping work moving -------------------------------------------------------------
    def _track_free(self):
        """free_since = when a worker last stopped holding a task (None while it holds one)."""
        for a in self.db.execute(f"select * from agents where kind in {WORKERS} and state='active'").fetchall():
            if self._open_tasks(a["name"]):
                if a["free_since"] is not None:
                    self._set("agents", a["name"], free_since=None)
            elif a["free_since"] is None:
                self._set("agents", a["name"], free_since=self.clock())

    def _nudge(self):
        """A holder with no progress for an hour gets a nudge, worded differently each time; the clock
        restarts on any `fleet task` call (it updates `touched`). Still silent at the second nudge: its PM (or the
        CEO) is told once for that stretch. Agents without a task are left alone."""
        now = self.clock()
        for a in self.db.execute("select * from agents where state='active'").fetchall():
            ts = self._open_tasks(a["name"])
            if not ts or now - max(t["touched"] or 0 for t in ts) < NUDGE_AFTER:
                continue
            n = self.db.execute("select * from nudges where agent=?", (a["name"],)).fetchone()
            if n and now - n["last_at"] < NUDGE_AFTER:
                continue
            idx = ((n["idx"] if n else -1) + 1) % len(NUDGES)
            last_progress = max(t["touched"] or 0 for t in ts)
            streak = (n["streak"] or 0) + 1 if n and n["last_at"] > last_progress else 1
            lines = []
            for t in ts:
                prod = self._task_product(t["id"])
                if t["status"] == "verifying":
                    lines.append(f"#{t['id']} verify “{t['title']}” — {prod}: `fleet task verify {t['id']} pass` "
                                 f"or `fleet task verify {t['id']} fail \"<reason>\"`")
                else:
                    lines.append(f"#{t['id']} “{t['title']}” — {prod}, as {t['role']}: progress with "
                                 f"`fleet task note {t['id']} \"...\"`, finished with `fleet task done {t['id']} <link>`, "
                                 f"or if you're waiting on someone, park it and take other work: "
                                 f"`fleet task wait {t['id']} <operator|agent|outside> \"<what you need>\"`")
            self.db.execute("insert into items(kind, frm, too, text, depth, status, created) values('nudge','hub',?,?,0,'queued',?)",
                            (a["name"], NUDGES[idx] + f"\nNo progress posted for {int((now - last_progress) // 3600)}h.\n"
                             + "\n".join(lines), now))
            self.db.execute("insert into nudges(agent, last_at, idx, streak) values(?,?,?,?) on conflict(agent) "
                            "do update set last_at=excluded.last_at, idx=excluded.idx, streak=excluded.streak",
                            (a["name"], now, idx, streak))
            if streak == 2:
                for t in ts:
                    pm = self.db.execute("select pm from products where name=?", (self._task_product(t["id"]),)).fetchone()
                    boss = (pm["pm"] if pm and pm["pm"] != a["name"] else None) or self._chair()
                    if boss and boss != a["name"]:
                        self._note(boss, f"{a['name']} has been silent on task #{t['id']} “{t['title']}” for "
                                         f"{int((now - last_progress) // 3600)}h",
                                   "It was reminded and still hasn't posted progress. It may be stuck on a permission "
                                   "pop-up, blocked, or done without closing the task. Check in with it, or reassign: "
                                   f"fleet task set {t['id']} owner <agent>.")

    def _ceo_idle(self):
        """More than three workers free for over 12 h → one note to whoever holds the CEO seat. Again only
        when that set of agents changes or another 12 h pass. Idle agents themselves are never messaged."""
        now, ceo = self.clock(), self._chair()
        idle = [a for a in self.db.execute(f"select * from agents where kind in {WORKERS} and state='active' "
                                           "and free_since is not null order by name").fetchall()
                if a["name"] != ceo and now - a["free_since"] > IDLE_AFTER]
        if len(idle) <= CEO_IDLE_COUNT:
            return
        key = ",".join(a["name"] for a in idle)
        last = self.db.execute("select * from ceo_notes order by id desc limit 1").fetchone()
        # again only when someone new is idle (the set shrinking as work lands is good news, not a reason) or 12 h pass
        if last and set(key.split(",")) <= set(last["agents"].split(",")) and now - last["at"] < IDLE_AFTER:
            return
        self.db.execute("insert into ceo_notes(agents, at) values(?,?)", (key, now))
        who = "\n".join(f"- {a['name']} ({a['current_product'] or 'no product'} · {a['current_role'] or 'no role'}), "
                        f"free {int((now - a['free_since']) // 3600)}h" for a in idle)
        pms = "\n".join(f"- {p['name']}: PM {p['pm'] or '(none)'}" for p in
                        self.db.execute("select name, pm from products where status='active' order by id"))
        self._deliver_to(ceo, f"{len(idle)} agents have had no task for over 12 hours",
                         f"{who}\n\nProducts and PMs:\n{pms or '- (no products yet)'}\n"
                         "Ask the PMs for work these agents can take, or add tasks yourself.")

    def _dry(self):
        """A product with nothing waiting to be picked up while agents sit idle gets planned, by rounds: its PM
        (or the chair) is asked first; if no task lands within PLAN_WAIT, one idle agent is made acting planner
        — it may `task add` in that product — and the PM is told and can remove what it adds. A round ends when
        new work has landed and been taken; the next starts then, or after IDLE_AFTER with nothing at all."""
        now = self.clock()
        idle = list(self._idle())
        for p in self.db.execute("select * from products where status='active'").fetchall():
            in_product = "from tasks t join projects j on t.project=j.id where j.product=?"
            # only work someone can pick up now counts: a chain waiting on its current step leaves free agents idle
            queued = self.db.execute(f"select 1 {in_product} and t.status in ('open','ready')", (p["id"],)).fetchone()
            row = self.db.execute("select * from dry_notes where product=?", (p["id"],)).fetchone()
            landed = row and self.db.execute(f"select 1 {in_product} and t.created > ?", (p["id"], row["at"])).fetchone()
            if row and row["planner"] and landed and not queued:      # the planner's round is over: its rights end
                self.db.execute("delete from grants where agent=? and level=?", (row["planner"], "plan:" + p["name"]))
            if queued or not idle:
                continue
            if row and not landed:
                if row["stage"] == "pm" and now - row["at"] >= PLAN_WAIT:
                    asked = p["pm"] or self._chair()
                    self._plan_by_agent(p, [n for n in idle if n != asked], row)
                if now - row["at"] < (2 * PLAN_WAIT if row["stage"] == "planner" else IDLE_AFTER):
                    continue
            who = p["pm"] or self._chair()
            if not who:
                continue
            if row and row["planner"]:
                self.db.execute("delete from grants where agent=? and level=?", (row["planner"], "plan:" + p["name"]))
            self.db.execute("insert or replace into dry_notes(product, at, stage, planner) values(?,?,'pm',null)", (p["id"], now))
            self._deliver_to(who, f"{p['name']} has no work lined up and {len(idle)} agents are free",
                             f"Goal: {p['metric'] or '(none set)'}. {p['brief'] or ''}\nProjects: {self._projects_line(p['id'])}\n"
                             "Plan the next steps, especially work that can run alongside what's in progress or waiting, "
                             "and add them: fleet task add <project id> \"<title>\" <role> \"<done when>\" "
                             "(fleet project add first if it needs a new one). Every agent can take any product's task. "
                             f"If nothing is added within {PLAN_WAIT // 3600} h, a free agent is asked to plan it instead.")

    def _projects_line(self, pid):
        return ", ".join(f"#{j['id']} {j['name']}" for j in self.db.execute(
            "select * from projects where product=? and status != 'removed'", (pid,))) or "none yet"

    def _plan_by_agent(self, p, idle, row):
        taken = {r["agent"] for r in self.db.execute("select agent from grants")}
        planner = next((n for n in idle if n not in taken), None)
        if not planner:
            return
        self.db.execute("insert into grants(agent, level, by, at) values(?,?,'hub',?)", (planner, "plan:" + p["name"], self.clock()))
        self.db.execute("update dry_notes set stage='planner', planner=? where product=?", (planner, p["id"]))
        done = "\n".join(f"- {t['title']}" for t in self.db.execute(
            "select t.title from tasks t join projects j on t.project=j.id where j.product=? and t.status='done' "
            "order by t.id desc limit 8", (p["id"],))) or "- (nothing yet)"
        self.db.execute("insert into items(kind, frm, too, text, depth, status, created) values('plan','hub',?,?,0,'queued',?)",
                        (planner, f"You're the acting planner for {p['name']}: nothing is queued, agents are free, and its "
                                  f"PM didn't add work in {PLAN_WAIT // 3600} h.\nGoal: {p['metric'] or '(none set)'}. {p['brief'] or ''}\n"
                                  f"Projects: {self._projects_line(p['id'])}\nDone so far:\n{done}\n"
                                  "Add 3-8 concrete next tasks that move the goal, each one agent can finish and prove: "
                                  "fleet task add <project id> \"<title>\" <designer|engineer|marketer|optimizer> \"<done when>\". "
                                  "Free agents pick them up straight away.", self.clock()))
        if p["pm"]:
            self._note(p["pm"], f"{planner} is planning {p['name']}",
                       f"No tasks were added in {PLAN_WAIT // 3600} h while agents were free, so {planner} is planning the "
                       "next steps. Remove any you disagree with: fleet task remove <id>.")

    # ---- seats, PMs, roles, suggestions -------------------------------------------------
    def set_pm(self, product, who):
        with self.lock:
            self.db.execute("update products set pm=? where name=? or id=?", (who or None, product, product))

    MANAGE_HELP = ("fleet portfolio | fleet changes | fleet ask \"<agent>\" \"<message>\" | "
                   'fleet product add "<name>" "<brief>" ["<goal>"] | fleet product set "<product>" brief|metric "<value>" | '
                   'fleet product rename "<product>" "<new name>" | '
                   'fleet project add|remove "<product>" "<project>" | fleet project rename "<product>" "<project>" "<new name>" | '
                   'fleet task add <project id> "<title>" <role> "<done when>" [<blocker ids,>] | '
                   'fleet task set <id> title|role|done|blocked "<value>" | fleet task set <id> owner <agent>|none | fleet task remove <id> | fleet task release <id> | '
                   'fleet pm "<product>" <agent>|none | fleet team <agent>|me <role>|generalist | fleet seat ceo <agent> | '
                   'fleet role set <role> "<soul text>" | fleet suggestion accept|reject <id> "<what you decided>" | fleet grant <agent> ceo|none | fleet powers | fleet park|wake <agent>, fleet product set "<product>" status, fleet product remove (Jack/Darragh)')

    def manage(self, by, line):
        """One company command from an agent (the fleet CLI, or a "fleet ..." line in dot's Slack reply).
        Every agent runs the business; each change is written to the change log the dashboard shows."""
        import shlex
        a = shlex.split(line)
        with self.lock:
            if a in (["powers"],):
                return self.powers(by)
            if a in (["portfolio"], ["changes"]):
                return self._portfolio() if a == ["portfolio"] else "\n".join(
                    f"{time.strftime('%m-%d %H:%M', time.localtime(c['at']))} {c['by']}: {c['line']} → {c['result']}"
                    for c in self.changes(30)) or "(no changes yet)"
            if a[0] == "ask" and len(a) >= 3:              # dot (Slack) has no CLI; this is its way to message an agent
                iid = self.ask(by, a[1], " ".join(a[2:]))
                return f"sent to {a[1]} (#{iid}); the reply comes back to you"
            if a[:2] in (["suggestion", "accept"], ["suggestion", "reject"]) and len(a) >= 3:
                self.decide_suggestion(by, int(a[2]), a[1] == "accept", " ".join(a[3:]))   # checks who may decide
                result = f"suggestion #{a[2]} {a[1]}ed"
                self.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)", (by, line, result, self.clock()))
                return result
            try:
                self._may_run(by, a)
            except NeedsReview:
                return self._propose(by, line)
            before = {n: self.powers(n) for n in self._names()}
            result = self._manage(a, by)
            if not result.startswith("unknown command"):
                self.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)", (by, line, result, self.clock()))
                for n in self._names():                  # anyone whose powers changed is told what they can do now
                    if before.get(n) != self.powers(n) and n != by:
                        self._tell_powers(n)
            return result

    def _propose(self, by, line):
        ceo = self._chair()
        sid = self.db.execute("insert into suggestions(frm, product, text, at, line) values(?,?,?,?,?)",
                              (by, None, f"run: fleet {line}", self.clock(), line)).lastrowid
        self._deliver_to(ceo, f"review #{sid}: {by} wants to run `fleet {line}`",
                         f"Accept: fleet suggestion accept {sid}\nReject: fleet suggestion reject {sid} \"why\"\n"
                         f"With no answer in {REVIEW_WAIT // 3600} h it goes ahead.")
        self.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)",
                        (by, line, f"sent to {ceo} for review (#{sid})", self.clock()))
        return f"sent to {ceo} for review as #{sid}; it goes ahead in {REVIEW_WAIT // 3600} h unless rejected"

    def _apply_line(self, frm, line, why):
        import shlex
        try:
            result = self._manage(shlex.split(line), frm)
        except Exception as e:
            result = f"failed: {e}"
        self.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)", (frm, line, f"{result} ({why})", self.clock()))
        self._note(frm, f"your change `fleet {line}` {why}", result)
        return result

    def _reviews(self):
        """A PM's change the CEO hasn't answered in REVIEW_WAIT goes ahead; the CEO is told."""
        for sg in self.db.execute("select * from suggestions where status='open' and line is not null and at <= ?",
                                  (self.clock() - REVIEW_WAIT,)).fetchall():
            self.db.execute("update suggestions set status='accepted', decided_by='hub', note=?, decided_at=? where id=?",
                            (f"no answer in {REVIEW_WAIT // 3600} h", self.clock(), sg["id"]))
            result = self._apply_line(sg["frm"], sg["line"], f"went ahead: no answer in {REVIEW_WAIT // 3600} h")
            ceo = self.db.execute("select agent from seats where role='ceo'").fetchone()
            if ceo and ceo["agent"] != sg["frm"]:
                self._deliver_to(ceo["agent"], f"review #{sg['id']} went ahead without an answer",
                                 f"{sg['frm']} ran `fleet {sg['line']}` → {result}")

    def _watch_chair(self):
        """Tell a stand-in it's in charge when it takes over; when the CEO is back, tell it what changed."""
        chair = self._chair()
        ceo = (self.db.execute("select agent from seats where role='ceo'").fetchone() or {"agent": None})["agent"]
        row = self.db.execute("select agent from seats where role='acting'").fetchone()
        was = row["agent"] if row else None
        if chair == was:
            return
        self.db.execute("insert or replace into seats(role, agent) values('acting', ?)", (chair,))
        if not chair:
            return
        if chair != ceo:
            self.db.execute("insert into changes(by, line, result, at) values('hub', ?, ?, ?)",
                            (f"stand-in {chair}", f"{chair} stands in for {ceo}", self.clock()))
            self._deliver_to(chair, f"you're standing in as CEO — {ceo} has done nothing for {STANDIN_AFTER // 3600} h",
                             "Run the company directly now: products, projects, tasks, PMs, teams, placement (fleet powers). "
                             f"Use your judgement; {ceo} gets a summary of what you changed when it's back.")
        elif was and was != ceo:
            since = self.db.execute("select max(at) from changes where by='hub' and line=?", (f"stand-in {was}",)).fetchone()[0] or 0
            done = [f"- {c['line']} → {c['result']}" for c in self.db.execute(
                "select * from changes where by=? and at>=? order by id", (was, since))]
            self._deliver_to(ceo, f"while you were away, {was} stood in as CEO",
                             ("What changed:\n" + "\n".join(done)) if done else "Nothing was changed.")

    def _tell_powers(self, n):
        p = self.powers(n)
        self._set("agents", n, powers_told=p)
        self._note(n, "what you can do on the hub changed", p)

    def _watch_powers(self):
        """Powers change for more reasons than a command — a stand-in taking over or handing back, a hub update.
        Whoever's changed is told once; a plain worker the first time round has nothing new to hear."""
        worker = "You do tasks you're given"
        for n in self._names():
            a, p = self._agent(n), self.powers(n)
            if a["powers_told"] == p:
                continue
            if a["powers_told"] is None and p.startswith(worker):
                self._set("agents", n, powers_told=p)
                continue
            self._tell_powers(n)

    def _watch_fleet(self):
        """An agent whose fleet command never reports a version is on an old copy from before it updated itself
        from GitHub (Oct 13: one lacked `task done`, so a finished task could never close). Told daily until fixed."""
        for a in self.db.execute("select * from agents where kind='muse' and state='active' and onboarded is not null "
                                 "and fleet_rev is null and coalesce(fleet_told, 0) < ?", (self.clock() - 86400,)).fetchall():
            self._set("agents", a["name"], fleet_told=self.clock())
            self._note(a["name"], "your fleet command is an old copy: update it once",
                       "It was copied in when you joined and never updates, so it's missing newer commands "
                       "(one agent's had no `fleet task done` and couldn't close a finished task). Update with two commands "
                       "(public repo, no GitHub login; your token and setup are untouched):\n"
                       f"  git clone --depth 1 {FLEET_REPO} ~/.fleet/repo   (already there? git -C ~/.fleet/repo pull)\n"
                       "  cp ~/.fleet/repo/agents/fleet ~/.fleet/fleet && chmod +x ~/.fleet/fleet\n"
                       "If `command -v fleet` isn't ~/.fleet/fleet, point that one at it too: ln -sf ~/.fleet/fleet \"$(command -v fleet)\". "
                       "Check: fleet --help lists `fleet task wait`. After that it updates itself. If anything fails, reply to Jack with the error.")

    APPROVALS_EVERY = 15                 # agents retry an upload the moment a request lapses: look often

    def scan_approvals(self):
        """Read every agent's pending Muse permission pop-ups (its own thread, one agent at a time)."""
        with self.lock:
            names = [r["name"] for r in self.db.execute("select name from agents where kind='muse' and state!='parked'")]
        for name in names:
            try:
                pend = self.transport.approvals(name)               # muse-cli I/O, never under the lock
            except Exception:
                continue                                            # unreadable this round: keep what we had
            with self.lock:
                self.db.execute("delete from approvals where agent=?", (name,))
                for x in pend:
                    self.db.execute("insert or replace into approvals values(?,?,?,?,?,?)",
                                    (x["id"], name, x["label"], x["detail"], json.dumps(x["options"]), x["expires"]))

    def approvals(self):
        """Muse permission pop-ups the agents are waiting on, soonest to expire first."""
        with self.lock:
            return [dict(r, options=json.loads(r["options"])) for r in self.db.execute(
                "select * from approvals where expires > ? order by expires", (self.clock(),))]

    def decide_approval(self, by, agent, approval_id, decision):
        with self.lock:
            r = self.db.execute("select * from approvals where id=? and agent=?", (approval_id, agent)).fetchone()
            if not r or r["expires"] <= self.clock():
                raise ValueError("that request is gone — already decided or expired")
            if decision not in json.loads(r["options"]):
                raise ValueError(f"{decision!r} isn't one of the choices Muse offered: {', '.join(json.loads(r['options']))}")
        self.transport.decide(agent, approval_id, decision)          # muse-cli I/O, never under the lock
        with self.lock:
            self.db.execute("delete from approvals where id=?", (approval_id,))
            self.db.execute("insert into changes(by, line, result, at) values(?,?,?,?)",
                            (by, f"approve {agent}: {r['label']}", decision, self.clock()))

    def _names(self):
        return [r["name"] for r in self.db.execute("select name from agents where kind in ('muse','poll','slack') and state='active'")]

    def powers(self, who):
        """Plain words for what this agent may do, and the commands for it."""
        pm_of = [r["name"] for r in self.db.execute("select name from products where pm=? and status != 'removed'", (who,))]
        a = self._agent(who)
        team = (a["team"] if a else None) or "generalist"
        base = (f"Your team: {team}. Tasks for your team's role come to you for any product; the hub switches your "
                "product context per task. Pick your own team with fleet team me <role|generalist> (roles: "
                f"{', '.join(self.roles())}).\n"
                "Everyone: fleet status, fleet inbox, fleet portfolio, fleet changes, fleet ask, fleet reply, "
                "fleet task note|done on tasks you hold, fleet task wait <id> <operator|agent|outside> \"<what>\" "
                "when you're waiting on someone (you're freed for other work; fleet task resume <id> when it's sorted), "
                "fleet task verify when asked, fleet suggest \"<idea>\". "
                "fleet task show <id> gives any task's status, holder and result link — look it up there, don't ask for it. "
                f"{OPERATOR_ONLY} When you hit one: fleet task operator <id> \"<what to do, "
                "why, and the link>\" — one plain step each, written for someone who hasn't read your work; they can reply "
                "to you from it. To stop until they act, use fleet task wait <id> operator \"<what>\". Tools (marked tool in fleet portfolio) are shared "
                "by every product: use them, and put tool work in the tool, not in your product.")
        if self._ceo_level(who):
            ceo = (self.db.execute("select agent from seats where role='ceo'").fetchone() or {"agent": None})["agent"]
            seat = ("You hold the CEO seat" if who == ceo else f"You're standing in as CEO while {ceo} is silent"
                    if who == self._chair() else "You have CEO-level powers (granted)")
            review = (f"PMs' company changes come to the CEO for review (fleet suggestion accept|reject <id>); one with "
                      f"no answer in {REVIEW_WAIT // 3600} h goes ahead. ")
            return (f"{seat}: you can do everything the CEO can — add, change, rename and remove products and projects; "
                    "add, edit, remove and release tasks; name PMs; put agents on teams (fleet team <agent> <role>|generalist); hand over the CEO "
                    "seat; rewrite what each role is told; decide suggestions; and grant or revoke CEO-level powers for "
                    "other agents (fleet grant <agent> ceo|none). Only Jack and Darragh park or wake agents, or pause, resume or remove a product. "
                    + review + "Every change is logged on the dashboard. Commands: fleet help.\n" + base)
        if pm_of:
            return (f"You are PM of {', '.join(pm_of)}: you manage the tasks in {', '.join(pm_of)} — fleet task add, "
                    "task set, task remove, task release — and decide suggestions for it. You can also change the "
                    "rest of the company (new products and projects, PMs, teams, placement): run the command and it "
                    f"goes to the CEO for review, and goes ahead if there's no answer in {REVIEW_WAIT // 3600} h. When "
                    "the CEO has been silent for hours you may be its stand-in and act directly. Parking agents, pausing or "
                    "removing products, and granting CEO level stay with the board and the CEO.\n" + base)
        return "You do tasks you're given; you can't change the company yourself. Ask the CEO or your PM.\n" + base

    def _may_run(self, by, a):
        """The CEO runs the whole company except parking agents; a PM runs its own product's tasks;
        parking and waking agents is the board's. Nobody else changes the company."""
        if a[:1] == ["team"] and len(a) == 3 and a[1] in ("me", by):
            return                                       # anyone can pick their own team
        if a[:1] in (["park"], ["wake"]):
            if not self.is_board(by):
                raise PermissionError("only Jack or Darragh can park or wake agents")
            return
        if a[:2] == ["product", "remove"] or (a[:2] == ["product", "set"] and len(a) > 3 and a[3] == "status"):
            if not self.is_board(by):                    # Jack, Oct 13: a PM paused 2 of 3 products and the fleet sat idle
                raise PermissionError("only Jack or Darragh can pause, resume or remove a product")
            return
        if self.is_board(by) or self._ceo_level(by):
            return
        if a[:1] == ["task"] and len(a) >= 3:
            if a[1] == "add":
                prod = self.db.execute("select p.name from projects j join products p on j.product=p.id where j.id=?",
                                       (int(a[2]),)).fetchone()
            else:
                prod = {"name": self._task_product(self._task_row(int(a[2]))["id"])}
            if prod and self.may_manage(by, prod["name"]):
                return
            raise PermissionError("only Jack, Darragh, the CEO or this product's PM can manage its tasks")
        if a[:1] not in (["grant"], ["seat"]) and self.db.execute(
                "select 1 from products where pm=? and status='active'", (by,)).fetchone():
            raise NeedsReview(a)
        raise PermissionError("only Jack, Darragh, the CEO or an agent granted CEO level can change the company")

    def changes(self, n=100):
        return [dict(r) for r in self.db.execute("select * from changes order by id desc limit ?", (n,))]

    def _manage(self, a, by_name=None):
        def product(ref):
            r = self.db.execute("select * from products where name=? or cast(id as text)=?", (ref, ref)).fetchone()
            if not r:
                raise ValueError(f"no product {ref!r}")
            return r

        def project(prod, ref):
            r = self.db.execute("select * from projects where product=? and (name=? or cast(id as text)=?) and status != 'removed'",
                                (prod["id"], ref, ref)).fetchone()
            if not r:
                raise ValueError(f"no project {ref!r} in {prod['name']}")
            return r

        def agent(name, board_ok=False):
            g = self._agent(name)
            if not g or (g["kind"] == "jack" and not board_ok):
                raise ValueError(f"no agent {name!r}")
            return g

        def role(r):
            if r not in self.roles():
                raise ValueError(f"role must be one of {', '.join(self.roles())}")
            return r

        def cancel(where, args):
            self._end_waits(where, args)
            self.db.execute(f"update tasks set status='cancelled', owner=null, verifier=null, touched=? "
                            f"where status != 'done' and {where}", (self.clock(), *args))

        verb = a[:2]
        if verb == ["product", "add"] and len(a) in (4, 5):
            return f"product #{self.add_product(a[2], brief=a[3], metric=a[4] if len(a) == 5 else None)} {a[2]} created"
        if verb == ["product", "set"] and len(a) == 5 and a[3] in ("brief", "metric", "status", "kind"):
            p = product(a[2])
            if a[3] == "kind" and a[4] not in ("product", "tool"):
                raise ValueError("kind is product or tool")
            self._set("products", p["id"], **{a[3]: a[4]})
            return f"{p['name']}: {a[3]} set"
        if verb == ["product", "rename"] and len(a) == 4:
            p = product(a[2])
            self._set("products", p["id"], name=a[3])
            self.db.execute("update agents set current_product=? where current_product=?", (a[3], p["name"]))
            self.db.execute("update suggestions set product=? where product=?", (a[3], p["name"]))
            return f"{p['name']} renamed to {a[3]}"
        if verb == ["product", "remove"] and len(a) == 3:
            p = product(a[2])
            self._set("products", p["id"], status="removed")
            cancel("project in (select id from projects where product=?)", (p["id"],))
            self.db.execute("update agents set current_product=null, current_role=null where current_product=?", (p["name"],))
            return f"{p['name']} removed: open tasks cancelled, its agents freed (bring it back with product set ... status active)"
        if verb == ["project", "add"] and len(a) == 4:
            p = product(a[2])
            return f"project #{self.add_project(p['id'], a[3])} {a[3]} added to {p['name']}"
        if verb == ["project", "rename"] and len(a) == 5:
            j = project(product(a[2]), a[3])
            self._set("projects", j["id"], name=a[4])
            return f"project {a[3]} renamed to {a[4]}"
        if verb == ["project", "remove"] and len(a) == 4:
            j = project(product(a[2]), a[3])
            self._set("projects", j["id"], status="removed")
            cancel("project=?", (j["id"],))
            return f"project {j['name']} removed, its open tasks cancelled"
        if verb == ["task", "add"] and len(a) in (6, 7):
            role(a[4])
            blk = [int(x) for x in a[6].split(",") if x] if len(a) == 7 else ()
            return f"task #{self.add_task(int(a[2]), a[3], a[4], a[5], blocked_by=blk)} {a[3]} added"
        if verb == ["task", "set"] and len(a) == 5 and a[3] in ("title", "role", "done", "blocked"):
            t = self._task_row(int(a[2]))
            col = {"title": "title", "role": "role", "done": "done_def", "blocked": "blocked_by"}[a[3]]
            val = role(a[4]) if a[3] == "role" else json.dumps([int(x) for x in a[4].split(",") if x]) if a[3] == "blocked" else a[4]
            self._set("tasks", t["id"], **{col: val})
            return f"task #{t['id']}: {a[3]} set"
        if verb == ["task", "set"] and len(a) == 5 and a[3] == "owner":
            t = self._task_row(int(a[2]))
            who = None if a[4] == "none" else agent(a[4])["name"]
            if t["status"] in ("done", "cancelled"):
                raise ValueError(f"task #{t['id']} is {t['status']}")
            self._end_waits("id=?", (t["id"],))           # handed on: a wait was the old holder's
            if who and t["owner"] != who and t["status"] in ("working", "verifying"):
                self._set("tasks", t["id"], owner=None, verifier=None, status="ready", touched=self.clock())
                self._task_event(t["id"], t["owner"], "released", f"handed to {who}")
            self._set("tasks", t["id"], pin=who)
            return f"task #{t['id']} goes to {who}" if who else f"task #{t['id']} goes to whoever fits"
        if verb == ["task", "remove"] and len(a) == 3:
            t = self._task_row(int(a[2]))
            cancel("id=?", (t["id"],))
            return f"task #{t['id']} removed"
        if verb == ["task", "release"] and len(a) == 3:
            self._end_waits("id=?", (int(a[2]),))
            self._set("tasks", int(a[2]), owner=None, verifier=None, status="ready", touched=self.clock())
            return f"task #{a[2]} released"
        if a[0] == "pm" and len(a) == 3:
            p = product(a[1])
            who = None if a[2] == "none" else agent(a[2])["name"]
            self.set_pm(p["id"], who)
            return f"{who or 'nobody'} is PM of {p['name']}"
        if a[0] == "place" and len(a) == 4:
            g = agent(a[1])
            if a[2] == "none":
                self.place(g["name"], None, None)
                return f"{g['name']} is off all products"
            self.place(g["name"], product(a[2])["name"], role(a[3]))
            return f"{g['name']} placed on {a[2]} as {a[3]}"
        if verb == ["seat", "ceo"] and len(a) == 3:
            self.seat("ceo", agent(a[2], board_ok=True)["name"] if a[2] != "jack" else "jack")
            return f"{a[2]} holds the CEO seat"
        if verb == ["role", "set"] and len(a) == 4:
            self.set_role(a[2], a[3])
            return f"role {a[2]} updated"
        if a[0] == "team" and len(a) == 3:
            g = agent(by_name if a[1] == "me" else a[1])
            team = None if a[2] == "none" else a[2] if a[2] == "generalist" else role(a[2])
            self._set("agents", g["name"], team=team)
            return f"{g['name']} is on the {team or 'generalist'} team"
        if a[0] == "grant" and len(a) == 3 and a[2] in ("ceo", "none"):
            g = agent(a[1])
            if a[2] == "ceo":
                self.db.execute("insert or replace into grants(agent, level, at) values(?,?,?)", (g["name"], "ceo", self.clock()))
            else:
                self.db.execute("delete from grants where agent=?", (g["name"],))
            return f"{g['name']} {'has CEO-level powers' if a[2] == 'ceo' else 'no longer has CEO-level powers'}"
        if a[0] in ("park", "wake") and len(a) == 2:
            g = agent(a[1])
            self._set("agents", g["name"], state="parked" if a[0] == "park" else "active")
            return f"{g['name']} {'parked (the hub stops messaging it)' if a[0] == 'park' else 'is active again'}"
        return "unknown command. Use: " + self.MANAGE_HELP

    def _run_lines(self, name, text):
        done = []
        for ln in text.splitlines():
            ln = html.unescape(ln).translate(SMART_QUOTES).strip().strip("`").strip()
            if ln.startswith("fleet "):
                try:
                    done.append(f"{ln}\n→ {self.manage(name, ln[6:])}")
                except (PermissionError, ValueError) as e:
                    done.append(f"{ln}\n→ refused: {e}")
        if done:
            self._note(name, "your fleet commands", "\n\n".join(done))

    def _portfolio(self):
        out = []
        for p in self.db.execute("select * from products where status != 'removed' order by id"):
            out.append(f"{p['kind'] or 'product'} #{p['id']} {p['name']} ({p['status']}) PM {p['pm'] or '(none)'} · goal {p['metric'] or '-'}\n  {p['brief'] or ''}")
            for j in self.db.execute("select * from projects where product=? and status != 'removed' order by id", (p["id"],)):
                out.append(f"  project #{j['id']} {j['name']}")
                for t in self.db.execute("select * from tasks where project=? and status != 'done' order by id", (j["id"],)):
                    out.append(f"    task #{t['id']} {t['status']} {t['title']} ({t['role']}) {('· ' + t['owner']) if t['owner'] else ''}")
        out.append("agents:")
        for g in self.db.execute("select * from agents where kind in ('muse','poll') and state != 'parked' order by name"):
            out.append(f"  {g['name']}: {g['current_product'] or 'no product'} · {g['current_role'] or 'no role'}")
        return "\n".join(out) or "(no products yet)"

    def roles(self):
        with self.lock:
            return {r["name"]: r["soul"] for r in self.db.execute("select * from roles order by name")}

    def _deliver_to(self, who, headline, text):
        """A message for a seat holder: an agent gets it in its fleet chat; a board member (or nobody,
        or a parked agent) gets it in Needs Jack, labelled with their name."""
        a = self._agent(who) if who else None
        if a and a["kind"] != "jack" and a["state"] != "parked":
            self._note(who, headline, text)
        else:
            self._needs_jack(f"For {(who or 'the board').title()}: {headline}\n{text}")

    def suggest(self, agent, text):
        with self.lock:
            a = self._agent(agent)
            runs = [r["name"] for r in self.db.execute("select name from products where pm=? and status != 'removed'", (agent,))]
            product = (a["current_product"] if a else None) or (runs[0] if len(runs) == 1 else None)
            sid = self.db.execute("insert into suggestions(frm, product, text, at) values(?,?,?,?)",
                                  (agent, product, text, self.clock())).lastrowid
            pm = self.db.execute("select pm from products where name=?", (product,)).fetchone()
            body = (f"From {agent} ({product or 'no product'}): {text}\n"
                    f"Talk it over with {agent} (fleet ask \"{agent}\" ...), decide what to do, if anything, and make the "
                    f"changes. Then log the decision: fleet suggestion accept {sid} \"what you decided and did\" or "
                    f"fleet suggestion reject {sid} \"why\".")
            deciders = [w for w in dict.fromkeys(((pm["pm"] if pm else None), self._chair())) if w and w != agent]
            for who in deciders:
                self._deliver_to(who, f"suggestion #{sid}", body)
            if deciders:
                self._note(agent, f"your suggestion #{sid} went to {', '.join(deciders)}",
                           f"{text}\n{' and '.join(deciders)} will talk it over with you, decide and log the decision.")
            return sid

    def decide_suggestion(self, by, sid, accept, note=""):
        with self.lock:
            sg = self.db.execute("select * from suggestions where id=?", (sid,)).fetchone()
            if not sg:
                raise ValueError(f"no suggestion #{sid}")
            if not self.may_manage(by, sg["product"]):
                raise PermissionError("only Jack, Darragh, the CEO or this product's PM decide suggestions")
            if sg["line"] and by == sg["frm"]:
                raise PermissionError("someone else reviews your own change")
            status = "accepted" if accept else "rejected"
            self.db.execute("update suggestions set status=?, decided_by=?, note=?, decided_at=? where id=?",
                            (status, by, note, self.clock(), sid))
            self._note(sg["frm"], f"your suggestion #{sid} was {status} by {by}", f"{sg['text']}" + (f"\n{note}" if note else ""))
            if accept and sg["line"]:
                self._apply_line(sg["frm"], sg["line"], f"approved by {by}")
                return
            chair = self._chair()
            if accept and chair and chair not in (by, sg["frm"]):
                # accepting only records the decision; someone with the power to change things has to do it
                self._note(chair, f"suggestion #{sid} from {sg['frm']} was accepted by {by}: carry it out",
                           f"{sg['text']}" + (f"\n{by}: {note}" if note else "") +
                           "\nMake the changes it needs with fleet commands (fleet team, fleet task, fleet role set...).")

    def suggestions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select * from suggestions order by id desc")]

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
            names = self._responders()
            for name in names:
                self.db.execute(
                    "insert into items(kind, frm, too, text, council, depth, status, created) values('question','hub',?,?,?,0,'queued',?)",
                    (name, question, cid, self.clock()))
        # through the normal gate (one item in flight, one sender per agent), not straight out: a question sent on
        # top of an open item, or by two senders at once, was answered once and the leftover marked the agent unresponsive
        for name in names:
            self._guarded(name, lambda n=name: self._deliver_agent(n, self._agent(n)["kind"], self.clock()))
        return cid

    def _asked(self, cid):
        return {r["too"] for r in self.db.execute("select too from items where council=? and kind='question'", (cid,))}

    def _chair(self):
        """The CEO — or its stand-in (seat 'ceo_backup') while the CEO is parked or has done nothing for
        STANDIN_AFTER; the CEO takes the seat back by acting at all."""
        seat = {r["role"]: r["agent"] for r in self.db.execute("select * from seats where role in ('ceo','ceo_backup')")}
        ceo, backup = seat.get("ceo"), seat.get("ceo_backup")
        b = self._agent(backup) if backup else None
        if not (b and b["state"] != "parked" and backup != ceo):
            return ceo
        a = self._agent(ceo) if ceo else None
        silent = not a or a["state"] == "parked" or self.clock() - max(a["last_act"] or 0, a["last_out"] or 0) >= STANDIN_AFTER
        return backup if silent else ceo

    def _add_view(self, cid, agent, view):
        self.db.execute("insert into council_views(council, agent, view, at) values(?,?,?,?)", (cid, agent, view, self.clock()))

    def _close_councils(self):
        for c in self.db.execute("select * from councils where status='open'").fetchall():
            voted = {r["agent"] for r in self.db.execute("select agent from council_views where council=?", (c["id"],))}
            asked = self._asked(c["id"])
            waiting = self.db.execute("select 1 from items where council=? and kind='question' and status in ('queued','sent')",
                                      (c["id"],)).fetchone()
            if waiting and self.clock() - c["created"] < COUNCIL_WINDOW:
                continue                                       # still waiting, window open
            self._set("councils", c["id"], status="chairing")
            # a question still waiting behind someone's open item is moot now; don't hand it over late
            self.db.execute("update items set status='dropped', closed=? where council=? and kind='question' and status='queued'",
                            (self.clock(), c["id"]))
            views = self.db.execute("select agent, view from council_views where council=?", (c["id"],)).fetchall()
            summary = "\n".join(f"- {v['agent']}: {v['view']}" for v in views)
            missing = sorted(asked - voted)
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
        missing = sorted(self._asked(cid) - {v["agent"] for v in views})
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
            sw = self.db.execute("select * from switches where agent=? and status='issued'", (agent,)).fetchone()
            if not sw:
                return None
            soul = (self.db.execute("select soul from roles where name=?", (sw["role"],)).fetchone() or {"soul": ""})["soul"]
            prod = self.db.execute("select brief from products where name=?", (sw["product"],)).fetchone()
            memory = f"# MEMORY.md (product: {sw['product']})\n{prod['brief'] if prod else ''}"
            return {"product": sw["product"], "role": sw["role"], "soul": soul, "memory": memory,
                    "from_product": sw["from_product"]}

    def issue_switch(self, agent, product, role):
        with self.lock:
            soul = (self.db.execute("select soul from roles where name=?", (role,)).fetchone() or {"soul": ""})["soul"]
            prod = self.db.execute("select brief from products where name=?", (product,)).fetchone()
            memory = f"# MEMORY.md (product: {product})\n{prod['brief'] if prod else ''}"
            expect = hashlib.sha256((soul + "\n" + memory).encode()).hexdigest()
            # the move takes effect now: the agent loading its brain files follows, it doesn't gate the work
            was = self._agent(agent)["current_product"]
            self.db.execute("insert into switches(agent, product, role, expect, issued, status, from_product) values(?,?,?,?,?,'issued',?) "
                            "on conflict(agent) do update set product=excluded.product, role=excluded.role, expect=excluded.expect, "
                            "issued=excluded.issued, status='issued', from_product=excluded.from_product",
                            (agent, product, role, expect, self.clock(), was))
            self._set("agents", agent, current_product=product, current_role=role)
            self.db.execute(
                "insert into items(kind, frm, too, text, depth, status, created) values('note','hub',?,?,0,'queued',?)",
                (agent, f"switch to {product} as {role}\nYou've been moved to {product} as {role}; your next task follows. Load that context now: fleet switch \"{product}\" \"{role}\"\n"
                        f"It changes only the role section of SOUL.md and, if the product changes, saves your current "
                        f"product's memory to ~/fleet-brains/ (it comes back when you return) and loads {product}'s. "
                        "IDENTITY.md never changes. This is the fleet's normal hand-off between tasks.",
                 self.clock()))

    def record_switch(self, agent, product, role, got_hash):
        with self.lock:
            sw = self.db.execute("select * from switches where agent=?", (agent,)).fetchone()
            # brain_for serves the role/brief as they are now; an edit after the switch was issued isn't a bad load
            now = self.brain_for(agent) if sw and sw["status"] == "issued" else None
            served = now and hashlib.sha256((now["soul"] + "\n" + now["memory"]).encode()).hexdigest()
            if sw and got_hash in (sw["expect"], served) and sw["product"] == product and sw["role"] == role:
                self._set("agents", agent, current_product=product, current_role=role)
                self.db.execute("update switches set status='done' where agent=?", (agent,))
                return True
            self.db.execute("update switches set status='mismatch' where agent=?", (agent,))
            self._needs_jack(f"{agent}'s brain switch to {product}/{role} reported a hash that didn't match what the hub issued.")
            return False

    def _switch_to_fill(self):
        # a ready, unowned task with no matching idle agent, but an idle agent exists → switch one to fill it.
        # issue_switch moves the agent at once, so _idle already sees anyone switched on an earlier tick; a
        # switch's 'issued' status only tracks the agent loading its brain files, which may never be reported.
        switched = set()                                       # this tick's picks, so one agent isn't sent two ways
        for t in self.db.execute(f"select t.* {LIVE_TASKS} and t.status='ready' and t.owner is null").fetchall():
            product = self._task_product(t["id"])
            if next(self._idle(product, t["role"], t["pin"]), None):
                continue                                       # someone already fits; _assign_tasks will take it
            free = [self._agent(n) for n in self._idle() if n not in switched]
            free = [a for a in free if (a["name"] == t["pin"] if t["pin"] else self._fits(a, t["role"]))]
            # specialists before generalists; then hold people constant — files and programs on a VM don't move
            # with a switch, so prefer someone whose loaded context is already this product, then none, then another
            loaded = lambda a: 0 if a["current_product"] == product else 1 if not a["current_product"] else 2
            ranked = sorted(free, key=lambda a: (0 if a["team"] == t["role"] else 1, loaded(a)))
            if ranked:
                switched.add(ranked[0]["name"])
                self.issue_switch(ranked[0]["name"], product, t["role"])
            else:
                self._stuck(t, product)

    def _stuck(self, t, product):
        """No one can take a ready task: tell the product's PM (else the CEO) why and how to fix it, once per reason."""
        pin = t["pin"] and self._agent(t["pin"])
        if pin and pin["state"] == "active":
            busy = ", ".join(f"#{o['id']}" for o in self._open_tasks(pin["name"]))
            why = f"it's pinned to {pin['name']}, who is busy on {busy}" if busy else f"it's pinned to {pin['name']}"
        elif t["pin"]:
            why = f"it's pinned to {t['pin']}, who isn't active"
        else:
            why = f"no {t['role']} or generalist is free"
        last = self.db.execute("select text from task_events where task=? and what='stuck' order by id desc limit 1",
                               (t["id"],)).fetchone()
        if last and last["text"] == why:
            return
        self._task_event(t["id"], None, "stuck", why)
        pm = self.db.execute("select pm from products where name=?", (product,)).fetchone()
        boss = (pm and pm["pm"]) or self._chair()
        head = f"Task #{t['id']} “{t['title']}” ({product}, {t['role']}) is ready but can't be filled: {why}."
        fix = (f"Give it to someone: fleet task set {t['id']} owner <agent> (they're moved onto {product} for it), "
               f"or let anyone who fits take it: fleet task set {t['id']} owner none. "
               f"To grow the {t['role']} team: fleet team <agent> {t['role']}.")
        if boss:
            self._note(boss, head, fix)
        else:
            self._needs_jack_once(head + " " + fix)

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

    def secrets_for(self, agent):
        with self.lock:
            return [r["name"] for r in self.db.execute("select name, scope from secrets order by name")
                    if self._may_read(agent, r["scope"])]

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
            except muse.LoginError as e:              # muse.ai refused the login: only Jack can fix that
                with self.lock:
                    self._set("agents", name, state="login")
                    if not self.db.execute("select 1 from needs_jack where done=0 and text like ?",
                                           (f"{name}'s Muse login%",)).fetchone():
                        self._needs_jack(f"{name}'s Muse login couldn't be renewed ({str(e)[:120]}). Sign it in again.")
            except Exception as e:                    # network blip: log it, retry on the next renewal
                with self.lock:
                    self.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)",
                                    (name, f"login renewal: {str(e)[:160]}", self.clock()))

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
            evs = []
            for r in self.db.execute("select * from (select e.*, i.frm, i.kind, i.text as item_text, i.status as item_status from events e left join items i on e.item=i.id "
                                     "where e.agent=? order by e.id desc limit ?) order by id", (agent, limit)):
                e = dict(r)
                # the same failure retried every tick shows once, with how many times and when it last happened
                key = re.sub(r"^#\d+ ", "", e["text"] or "")
                if e["dir"] == "err" and evs and evs[-1]["dir"] == "err" and evs[-1]["_key"] == key:
                    evs[-1].update(count=evs[-1]["count"] + 1, at=e["at"])
                    continue
                evs.append(dict(e, _key=key, count=1))
            # a "recovered" marker clears every failure before it: only errors still unresolved show
            last_ok = max((i for i, e in enumerate(evs) if e["dir"] == "err" and e["_key"] == "recovered"), default=-1)
            evs = [e for i, e in enumerate(evs) if not (e["dir"] == "err" and i <= last_ok)]
            for e in evs:
                e.pop("_key")
            waiting = [{"item": r["id"], "agent": agent, "dir": "waiting", "text": f"from {r['frm']}: {r['text']}", "at": r["created"],
                        "frm": r["frm"], "kind": r["kind"], "item_text": r["text"], "item_status": "queued"}
                       for r in self.db.execute("select * from items where too=? and status='queued' order by id", (agent,))]
            asked = [{"item": r["id"], "agent": agent, "dir": "asked", "text": f"to {r['too']}: {r['text']}", "at": r["created"]}
                     for r in self.db.execute("select * from items where frm=? and kind in ('request','question') order by id", (agent,))]
            return sorted(evs + waiting + asked, key=lambda e: e["at"] or 0)

    def _failing(self, a):
        """Still failing: its latest delivery error came after its last recovery and its last reply."""
        r = self.db.execute("select max(case when text != 'recovered' then at end) bad, max(case when text = 'recovered' "
                            "then at end) ok from events where agent=? and dir='err'", (a["name"],)).fetchone()
        return bool(r["bad"]) and r["bad"] > max(r["ok"] or 0, a["last_out"] or 0)

    def activity(self, since, until=None, agent=None):
        """What the company did in [since, until], newest first, optionally for one agent: messages both ways
        (with who sent them), every task step, what each agent's machine reported doing, changes and failures.
        Plus counts, 24 time buckets across the window, task progress, and who is working right now."""
        with self.lock:
            now = self.clock()
            until = until or now
            win, feed = (since, until), []
            who = (" and agent=?", (agent,)) if agent else ("", ())
            for r in self.db.execute("select e.agent, e.dir, e.text, e.at, i.frm, i.kind, i.text as item_text from events e "
                                     "left join items i on e.item=i.id where e.at between ? and ?" + who[0].replace("agent", "e.agent") +
                                     " order by e.at desc, e.id desc limit 500", (*win, *who[1])):
                if r["dir"] == "in":
                    kind = r["kind"] or ""
                    if kind in ("task", "verify"):
                        continue                                  # shown as task steps instead
                    typ = "sent" if kind in ("request", "question") else "notice"
                    feed.append({"type": typ, "agent": r["agent"], "from": r["frm"] or "hub", "kind": kind,
                                 "text": r["item_text"] or r["text"], "at": r["at"]})
                elif r["dir"] == "out":
                    if re.match(r"task #\d+ (note|done|verify):", r["text"] or ""):
                        continue                                  # the task step says it better
                    feed.append({"type": "reply", "agent": r["agent"], "text": r["text"], "at": r["at"]})
                elif r["dir"] == "err" and (r["text"] or "") != "recovered":
                    ok = self.db.execute("select 1 from events where agent=? and dir='err' and text='recovered' and at>=? limit 1",
                                         (r["agent"], r["at"])).fetchone()
                    feed.append({"type": "error", "agent": r["agent"], "text": re.sub(r"^#\d+ ", "", r["text"] or ""), "at": r["at"],
                                 "recovered": bool(ok)})
            for r in self.db.execute("select * from items where status='queued' and kind in ('request','question') "
                                     "and created between ? and ?" + who[0].replace("agent", "too"), (*win, *who[1])):
                feed.append({"type": "sent", "agent": r["too"], "from": r["frm"], "kind": r["kind"], "text": r["text"],
                             "at": r["created"], "queued": True})
            for w in self.db.execute("select * from work where at between ? and ?" + who[0] + " order by at desc limit 500", (*win, *who[1])):
                feed.append({"type": "work", "agent": w["agent"], "text": w["title"], "detail": w["detail"],
                             "status": w["status"], "kind": w["kind"], "at": w["at"]})
            for e in self.db.execute("select e.*, t.title from task_events e left join tasks t on e.task=t.id "
                                     "where e.at between ? and ?" + who[0].replace("agent", "e.agent") + " order by e.at desc, e.id desc limit 300", (*win, *who[1])):
                feed.append({"type": "task", "agent": e["agent"], "what": e["what"], "task": e["task"], "title": e["title"],
                             "text": e["text"] or "", "product": self._task_product(e["task"]), "at": e["at"]})
            for c in self.db.execute("select * from changes where at between ? and ?" + who[0].replace("agent", "by") +
                                     " order by at desc limit 200", (*win, *who[1])):
                feed.append({"type": "change", "agent": c["by"], "text": c["line"], "result": c["result"], "at": c["at"]})
            feed.sort(key=lambda e: -e["at"])
            types = ("sent", "reply", "work", "task", "notice", "change", "error")
            counts = {t: sum(1 for e in feed if e["type"] == t and not e.get("recovered")) for t in types}
            step = (until - since) / 24 or 1
            buckets = [dict({t: 0 for t in types}, start=since + i * step) for i in range(24)]
            for e in feed:
                if not e.get("recovered"):             # a blip the retry fixed isn't a red bar
                    buckets[min(23, max(0, int((e["at"] - since) // step)))][e["type"]] += 1
            done_ids = [e["task"] for e in feed if e["type"] == "task" and e["what"] == "verified"]
            tasks = {"finished": [self.task(i) for i in dict.fromkeys(done_ids)],
                     "in_progress": [self.task(r["id"]) for r in self.db.execute(
                         "select id from tasks where status in ('working','verifying') order by touched desc")],
                     "waiting": self.db.execute("select count(*) from tasks where status in ('open','ready','blocked')").fetchone()[0]}
            agents, live = {}, []
            for a in self.db.execute("select * from agents where kind in ('muse','poll','slack') order by name"):
                mine = [e for e in feed if e["agent"] == a["name"]]
                agents[a["name"]] = {"sent": sum(e["type"] in ("sent", "notice") for e in mine),
                                     "reply": sum(e["type"] == "reply" for e in mine),
                                     "work": sum(e["type"] == "work" for e in mine),
                                     "tasks": sum(e["type"] == "task" for e in mine),
                                     "error": sum(e["type"] == "error" for e in mine),
                                     "failing": self._failing(a),
                                     "last_said": a["last_out"], "state": a["state"],
                                     "product": a["current_product"], "role": a["current_role"]}
                held = self._open_tasks(a["name"])
                last = self.db.execute("select * from work where agent=? order by at desc limit 1", (a["name"],)).fetchone()
                if held or (last and now - last["at"] < 600):
                    live.append({"agent": a["name"], "task": ({"id": held[0]["id"], "title": held[0]["title"]} if held else None),
                                 "doing": last["title"] if last else None, "since": (held[0]["touched"] if held else last["at"])})
            return {"now": now, "since": since, "until": until, "feed": feed[:400], "counts": counts, "buckets": buckets,
                    "tasks": tasks, "agents": agents, "live": live,
                    "per_hour": [sum(b[t] for t in ("sent", "reply")) for b in buckets]}

    # ---- tools: agents' code run on this machine by tools_runner.py, as an account that can't touch the hub ----
    jobs_dir = None                      # hub.json "jobs_dir"; unset = no tools on this hub

    def tool_run(self, by, tool, args=(), timeout=None):
        import tools_runner
        if not self.jobs_dir:
            raise ValueError("tools aren't set up on this hub")
        if not tools_runner.TOOL.match(tool or ""):
            raise ValueError("a tool name is lowercase letters, digits, - and _ (its folder under tools/ in the repo)")
        with self.lock:
            jid = max(int(self.clock() * 1000), getattr(self, "_last_job", 0) + 1)
            self._last_job = jid
            os.makedirs(os.path.join(self.jobs_dir, "queue"), exist_ok=True)
            tools_runner.write_json(os.path.join(self.jobs_dir, "queue", f"{jid}.json"),
                                    {"id": jid, "tool": tool, "args": [str(a) for a in args], "by": by, "timeout": timeout})
            self._log(None, by, "out", f"tool {tool} job {jid} {' '.join(map(str, args))}"[:300])
        return jid

    def tool_job(self, jid):
        d = os.path.join(self.jobs_dir or "", str(int(jid)))
        qf = os.path.join(self.jobs_dir or "", "queue", f"{int(jid)}.json")
        if os.path.isfile(qf):
            ahead = len([f for f in os.listdir(os.path.dirname(qf)) if f < os.path.basename(qf)])
            return {**json.load(open(qf)), "status": "queued", "ahead": ahead}
        if not os.path.isfile(os.path.join(d, "status.json")):
            return None
        out = {**json.load(open(os.path.join(d, "job.json"))), **json.load(open(os.path.join(d, "status.json")))}
        try:
            with open(os.path.join(d, "log.txt"), "rb") as f:
                f.seek(max(0, os.path.getsize(f.name) - 4000))
                out["log"] = f.read().decode("utf-8", "replace")
        except OSError:
            out["log"] = ""
        root = os.path.join(d, "out")
        out["files"] = [{"path": os.path.relpath(os.path.join(w, n), root).replace(os.sep, "/"), "size": os.path.getsize(os.path.join(w, n))}
                        for w, _, ns in os.walk(root) for n in ns][:200]
        return out

    def recent_jobs(self, n=12):
        """The newest jobs, queued or not, for the dashboard."""
        q = os.path.join(self.jobs_dir or "", "queue")
        if not self.jobs_dir or not os.path.isdir(q):
            return []
        ids = [int(f) for f in os.listdir(self.jobs_dir) if f.isdigit()] + \
              [int(f[:-5]) for f in os.listdir(q) if f.endswith(".json") and f[:-5].isdigit()]
        out = []
        for j in filter(None, map(self.tool_job, sorted(set(ids), reverse=True)[:n])):
            out.append({**{k: j.get(k) for k in ("id", "tool", "by", "args", "status", "started", "ended", "note")},
                        "files": len(j.get("files", []))})
        return out

    def tool_file(self, jid, rel):
        """A file a job made, by its path under the job's out folder; nothing outside it."""
        root = os.path.realpath(os.path.join(self.jobs_dir or "", str(int(jid)), "out"))
        p = os.path.realpath(os.path.join(root, rel))
        if not p.startswith(root + os.sep) or not os.path.isfile(p):
            raise ValueError(f"job {jid} has no file {rel}")
        return p

    def tools(self):
        try:
            return json.load(open(os.path.join(self.jobs_dir, "tools.json")))
        except (OSError, TypeError, ValueError):
            return []

    def _watch_jobs(self):
        """A finished job is told to the agent that ran it, once."""
        if not self.jobs_dir or not os.path.isdir(self.jobs_dir):
            return
        for f in os.listdir(self.jobs_dir):
            d = os.path.join(self.jobs_dir, f)
            if not f.isdigit() or os.path.exists(os.path.join(d, "told")) or not os.path.isfile(os.path.join(d, "status.json")):
                continue
            st = json.load(open(os.path.join(d, "status.json")))
            if st.get("status") in (None, "running"):
                continue
            job = json.load(open(os.path.join(d, "job.json")))
            open(os.path.join(d, "told"), "w").close()
            if self._agent(job["by"]):
                self._note(job["by"], f"tool {job['tool']} job {f} {st['status']}",
                           f"{st.get('note') or ''}\nSee it: fleet tool job {f}   ·   files: fleet tool get {f} <file>\n— No reply needed.")

    def needs_jack(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("select * from needs_jack where done=0 order by id desc")]

    def reply_need(self, nid, by, text):
        """Jack answers an item on his list: it goes to the agent who raised it, and the item is done."""
        with self.lock:
            n = self.db.execute("select * from needs_jack where id=?", (nid,)).fetchone()
            if not n or not n["agent"]:
                raise ValueError("no agent raised this, so there's nobody to reply to")
            if not text.strip():
                raise ValueError("the reply is empty")
            head = n["text"].split("\n")[0][:300]
        self.ask(by, n["agent"], f"{by.title()} answered your item on their list:\n“{head}”\n\n{text}")
        self.resolve_need(nid)
        return n["agent"]

    def resolve_need(self, nid):
        with self.lock:
            self.db.execute("update needs_jack set done=1 where id=?", (nid,))
            n = self.db.execute("select task from needs_jack where id=?", (nid,)).fetchone()
            t = n and n["task"] and self.db.execute("select * from tasks where id=?", (n["task"],)).fetchone()
            if t and t["waiting_on"]:
                self._resume(t, "jack")

    # ---- telemetry (machine heartbeat from each agent's telemetryd) ---------------------
    def ingest(self, name, blob):
        with self.lock:
            for e in ((blob.get("activity") or {}).get("entries") or [])[:50]:
                try:
                    at = calendar.timegm(time.strptime(str(e.get("timestamp"))[:19], "%Y-%m-%dT%H:%M:%S"))
                except (ValueError, TypeError):
                    continue
                key = e.get("message_id") or f"{e.get('timestamp')}|{e.get('title')}"
                self.db.execute("insert into work(agent, key, at, kind, title, status, detail) values(?,?,?,?,?,?,?) "
                                "on conflict(agent, key) do update set status=excluded.status, title=excluded.title, detail=excluded.detail",
                                (name, key, at, e.get("activity_type"), e.get("title") or e.get("status_title") or "",
                                 e.get("status"), e.get("subtitle") or e.get("status_title") or ""))
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
        current_rev = fleet_rev()
        with self.lock:
            out = []
            for a in self.db.execute("select * from agents where kind!='jack' order by name"):
                cur = self._inflight(a["name"])
                queue = self.db.execute("select count(*) from items where too=? and status='queued'", (a["name"],)).fetchone()[0]
                out.append({"name": a["name"], "kind": a["kind"], "state": a["state"], "queue": queue,
                            "current": {"id": cur["id"], "text": cur["text"][:200], "sent_at": cur["sent_at"]} if cur else None,
                            "last_in": a["last_in"], "last_out": a["last_out"], "login_expires": a["login_expires"],
                            "product": a["current_product"], "role": a["current_role"], "onboarded": a["onboarded"], "team": a["team"] or "generalist",
                            "focus": self._focus(a["name"]), "free_since": a["free_since"], "fleet_rev": a["fleet_rev"],
                            "fleet_old": a["kind"] == "muse" and a["fleet_rev"] != current_rev,
                            "doing": {"busy": bool(a["busy"]), "line": a["doing"], "at": a["doing_at"]}
                                     if a["doing"] is not None or a["busy"] else None,
                            "last_work": (lambda w: {"title": w["title"], "at": w["at"]} if w else None)(self.db.execute(
                                "select title, at from work where agent=? order by at desc limit 1", (a["name"],)).fetchone()),
                            "task": next(({"id": t["id"], "title": t["title"], "status": t["status"],
                                           "product": self._task_product(t["id"])} for t in self._open_tasks(a["name"])), None)})
            return {"now": self.clock(), "agents": out, "needs_jack": self.needs_jack(), "changes": self.changes(30),
                    "approvals": self.approvals(), "tools": self.tools(), "jobs": self.recent_jobs(),
                    "revenue": self.revenue(), "products": self.portfolio()}

    def org(self):
        with self.lock:
            return {"ceo": self._chair(),
                    "board": sorted({"jack"} | {r["name"] for r in self.db.execute("select name from agents where kind='jack'")}),
                    "pms": {p["name"]: p["pm"] for p in self.db.execute("select name, pm from products where status != 'removed' order by id")},
                    "roles": self.roles(),
                    "agents": [{"name": a["name"], "kind": a["kind"], "team": a["team"] or "generalist",
                                "product": a["current_product"], "role": a["current_role"]}
                               for a in self.db.execute("select * from agents where kind!='jack' and state!='parked' order by name")]}

    def portfolio(self):
        with self.lock:
            out = []
            for p in self.db.execute("select * from products where status != 'removed' order by id"):
                projects = []
                for pr in self.db.execute("select * from projects where product=? and status != 'removed' order by id", (p["id"],)):
                    tasks = [self.task(t["id"]) for t in self.db.execute("select id from tasks where project=? order by id", (pr["id"],))]
                    projects.append({"id": pr["id"], "name": pr["name"], "tasks": tasks})
                rev = self.db.execute("select coalesce(sum(amount),0) s from sales where product=?", (p["name"],)).fetchone()["s"]
                out.append({"id": p["id"], "name": p["name"], "brief": p["brief"], "pm": p["pm"], "metric": p["metric"],
                            "budget": p["budget"], "kill_date": p["kill_date"], "status": p["status"], "kind": p["kind"] or "product",
                            "revenue": rev, "projects": projects})
            return out


# ---- HTTP ---------------------------------------------------------------------------------
def serve(hub, host, port, password, join_code=None, logins=None):
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

        def _page(self, code, text):
            import html as _h
            body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'>"
                    f"<body style='font:16px system-ui;background:#0d1117;color:#e6edf3;padding:32px'>"
                    f"<p>{_h.escape(text)}</p><p><a style='color:#58a6ff' href='/'>Back to the dashboard</a></p>").encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _jack(self):
            auth = self.headers.get("Authorization", "")
            if auth.startswith("Basic "):
                try:
                    user, pw = base64.b64decode(auth[6:]).decode().split(":", 1)
                    # Jack's password (any user name, as before), or a board member's own login from hub.json "logins"
                    if user in (logins or {}) and hmac.compare_digest(pw, logins[user]):
                        self.who = user                    # a board member's own login: messages are from them
                        return True
                    if hmac.compare_digest(pw, password):
                        self.who = "jack"
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
                hub.note_onboarded(name, self.headers.get("X-Fleet-Rev"))   # a token call proves fleet is installed
                # a POST is the agent itself doing something; telemetryd's heartbeat is only its VM being up
                if self.command == "POST" and urlparse(self.path).path != "/api/ingest":
                    hub.acted(name)
            return name

        def _base(self):
            host = self.headers.get("Host", "")
            return ("http://" if host.startswith(("127.0.0.1", "localhost")) else "https://") + host

        def _html(self, code, text):
            body = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _form(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode() if n else ""
            if "json" in self.headers.get("Content-Type", ""):
                return json.loads(raw or "{}")
            return {k: v[0] for k, v in parse_qs(raw).items()}

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
                elif u.path == "/doc":                     # an agent's Markdown file, rendered instead of downloaded
                    if self._jack():
                        src = q.get("u", "")
                        if not doc_source_ok(src):
                            self._page(400, "Only Muse file links open here.")
                        else:
                            import urllib.request
                            try:
                                with urllib.request.urlopen(src, timeout=15) as r:
                                    text = r.read(3_000_000).decode("utf-8", "replace")
                                body = doc_page(src, text).encode()
                                self.send_response(200)
                                self.send_header("Content-Type", "text/html; charset=utf-8")
                                self.send_header("Content-Length", str(len(body)))
                                self.end_headers()
                                self.wfile.write(body)
                            except OSError as e:
                                self._page(502, f"Couldn't fetch that file: {e}")
                elif u.path in ("/", "/index.html"):
                    if self._jack():
                        body = open(page_path, "rb").read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                elif u.path in ("/office.js", "/office3d.js", "/office3d-vox.js", "/office3d-world.js", "/office3d-people.js", "/office3d-look.js", "/three.module.min.js"):
                    if self._jack():                                   # the Overview's office (2D, and the 3D view's modules), kept out of dashboard.html
                        body = open(os.path.join(HERE, u.path.lstrip("/")), "rb").read()
                        self.send_response(200)
                        self.send_header("Content-Type", "text/javascript; charset=utf-8")
                        self.send_header("Content-Length", str(len(body)))
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        self.wfile.write(body)
                elif u.path.startswith("/.well-known/oauth-protected-resource"):   # the ChatGPT connector (mcp.py)
                    import mcp
                    self._json(200, mcp.resource_meta(self._base()))
                elif u.path in ("/.well-known/oauth-authorization-server", "/.well-known/openid-configuration"):
                    import mcp
                    self._json(200, mcp.server_meta(self._base()))
                elif u.path == "/oauth/authorize":
                    if self._jack():
                        import mcp
                        try:
                            self._html(200, mcp.authorize_page(hub, q, self.who))
                        except ValueError as e:
                            self._page(400, f"Can't connect: {e}")
                elif u.path == "/mcp":
                    self.send_response(405)
                    self.send_header("Allow", "POST")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif u.path == "/api/jack/approvals":
                    if self._jack():
                        self._json(200, {"approvals": hub.approvals()})
                elif u.path == "/api/board":
                    if self._jack():
                        import etsy
                        self._json(200, dict(hub.board(), etsy=etsy.shops(hub), you=self.who))
                elif u.path in ("/etsy/connect", "/etsy/callback"):   # linking an Etsy shop (board login only)
                    if self._jack():
                        import etsy
                        host = self.headers.get("Host", "")
                        cb = ("http://" if host.startswith(("127.0.0.1", "localhost")) else "https://") + host + "/etsy/callback"
                        try:
                            if u.path == "/etsy/connect":
                                to = etsy.start(hub, q.get("product") or None, cb)
                                self.send_response(302)
                                self.send_header("Location", to)
                                self.send_header("Content-Length", "0")
                                self.end_headers()
                            else:
                                rec = etsy.finish(hub, q.get("state", ""), q.get("code", ""), cb)
                                self._page(200, f"Linked the Etsy shop {rec['shop_name']} to {rec['product'] or 'no product'}. "
                                                "Sales show up within the hour.")
                        except (ValueError, RuntimeError) as e:
                            self._page(400, f"Etsy link didn't work: {e}")
                elif u.path == "/api/timeline":
                    self._jack() and self._json(200, hub.timeline(q.get("agent", "")))
                elif u.path == "/api/telemetry":
                    self._jack() and self._json(200, hub.telemetry(q.get("agent", "")) or {})
                elif u.path == "/api/item":
                    self._jack() and self._json(200, hub.item(int(q.get("id", 0))) or {})
                elif u.path == "/api/inbox":
                    name = self._agent()
                    name and self._json(200, {"item": hub.inbox(name)})
                elif u.path == "/api/tools":                # tools the fleet built, run on this machine
                    name = self._agent()
                    name and self._json(200, {"tools": hub.tools()})
                elif u.path == "/api/tool/job":
                    name = self._agent()
                    name and self._json(200, hub.tool_job(int(q.get("id", 0))) or {})
                elif u.path == "/api/tool/file":
                    name = self._agent()
                    if name:
                        body = open(hub.tool_file(int(q.get("job", 0)), q.get("path", "")), "rb").read()
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                elif u.path == "/api/task":                 # any task's state and result link, so agents look it up instead of asking
                    name = self._agent()
                    t = name and hub.task(int(q.get("id", 0)))
                    name and self._json(200, t and {**t, "operator": hub.operator_items(t["id"])} or {})
                elif u.path == "/api/status":
                    name = self._agent()
                    name and self._json(200, hub.status(name))
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
                elif u.path == "/api/activity":
                    if self._jack():
                        until = float(q["until"]) if q.get("until") else None
                        since = float(q["since"]) if q.get("since") else (until or hub.clock()) - float(q.get("hours", 1)) * 3600
                        self._json(200, hub.activity(since, until, q.get("agent") or None))
                elif u.path == "/api/org":
                    self._jack() and self._json(200, hub.org())
                elif u.path == "/api/suggestions":
                    self._jack() and self._json(200, {"suggestions": hub.suggestions()})
                elif u.path == "/api/councils":
                    self._jack() and self._json(200, {"councils": hub.councils()})
                else:
                    self._json(404, {"error": "not found"})
            except Exception as e:
                self._json(500, {"error": str(e)})

        def do_POST(self):
            u = urlparse(self.path)
            try:
                if u.path == "/mcp":
                    import mcp
                    tok = self.headers.get("Authorization", "")
                    name = hub.agent_by_token(tok[7:]) if tok.startswith("Bearer ") else None
                    if not name:
                        meta = self._base() + "/.well-known/oauth-protected-resource"
                        body = b'{"error": "invalid_token"}'
                        self.send_response(401)
                        self.send_header("WWW-Authenticate", f'Bearer resource_metadata="{meta}"')
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    else:
                        hub.note_onboarded(name)
                        out = mcp.rpc(hub, name, self._body())
                        if out is None:
                            self.send_response(202)
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                        else:
                            self._json(200, out)
                elif u.path == "/oauth/register":
                    import mcp
                    try:
                        self._json(201, mcp.register(self._body()))
                    except ValueError as e:
                        self._json(400, {"error": "invalid_redirect_uri", "error_description": str(e)})
                elif u.path == "/oauth/authorize":
                    if self._jack():
                        import mcp
                        try:
                            to = mcp.approve(hub, self._form(), self.who)
                            self.send_response(302)
                            self.send_header("Location", to)
                            self.send_header("Content-Length", "0")
                            self.end_headers()
                        except ValueError as e:
                            self._page(400, f"Can't connect: {e}")
                elif u.path == "/oauth/token":
                    import mcp
                    try:
                        self._json(200, mcp.token(hub, self._form()))
                    except ValueError as e:
                        self._json(400, {"error": str(e) if str(e) in ("invalid_grant", "unsupported_grant_type") else "invalid_request"})
                elif u.path == "/api/ask":
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
                elif u.path.startswith("/api/task/"):        # an agent moves a task: note | done | verify | release
                    name = self._agent()
                    if name:
                        b, verb = self._body(), u.path.rsplit("/", 1)[1]
                        tid = int(b["task"])
                        if verb == "note":
                            hub.task_note(name, tid, b["text"])
                        elif verb == "done":
                            hub.task_done(name, tid, b["link"])
                        elif verb == "verify":
                            hub.task_verify(name, tid, bool(b["ok"]), b.get("reason", ""))
                        elif verb == "release":
                            hub.task_release(name, tid)
                        elif verb == "wait":
                            hub.task_wait(name, tid, b.get("who"), b.get("what", ""))
                        elif verb == "resume":
                            hub.task_resume(name, tid)
                        elif verb in ("operator", "jack"):
                            hub.task_for_jack(name, tid, b["text"])
                        else:
                            raise ValueError(f"unknown task action {verb}")
                        self._json(200, {"ok": True, "task": hub.task(tid)["status"]})
                elif u.path == "/api/tool/run":
                    name = self._agent()
                    if name:
                        b = self._body()
                        self._json(200, {"job": hub.tool_run(name, b["tool"], b.get("args") or [], b.get("timeout"))})
                elif u.path == "/api/manage":                # CEO / PM run the company: products, projects, tasks, placement
                    name = self._agent()
                    name and self._json(200, {"result": hub.manage(name, self._body()["line"])})
                elif u.path == "/api/suggest":
                    name = self._agent()
                    name and self._json(200, {"id": hub.suggest(name, self._body()["text"])})
                elif u.path == "/api/suggestion":
                    name = self._agent()
                    if name:
                        b = self._body()
                        hub.decide_suggestion(name, int(b["id"]), bool(b["accept"]), b.get("note", ""))
                        self._json(200, {"ok": True})
                elif u.path == "/api/ingest":              # an agent's telemetryd pushes its machine heartbeat
                    name = self._agent()
                    if name:
                        hub.ingest(name, self._body())
                        self._json(200, {"ok": True})
                elif u.path == "/api/claim":                # an agent registers itself with a code, no hub push
                    b = self._body()
                    code, name = b.get("code", ""), str(b.get("name", "")).strip()
                    jacks = hmac.compare_digest(code, password)
                    joins = bool(join_code) and hmac.compare_digest(code, join_code)
                    old = hub._agent(name) if name else None
                    if not (jacks or joins):
                        self._json(403, {"error": "bad claim code"})
                    elif not name or name.lower() == "jack" or (old and old["token_hash"] and old["kind"] != "slack" and (joins or old["kind"] != "muse")):
                        # the join code makes new agents, or gives a Slack-bridged agent (dot) direct access while
                        # its bridge keeps working; Jack's code also re-claims a Boboe whose VM was replaced.
                        # Neither can take over a board member or another hub agent.
                        self._json(409, {"error": f"the name {name!r} is taken or reserved; pick another"})
                    else:
                        # agents the hub holds a Muse login for get pushed to; anyone else fetches its own work
                        kind = "muse" if name in getattr(hub, "accounts", {}) else (old["kind"] if old else "poll")
                        self._json(200, {"token": hub.add_agent(name, kind)})
                elif u.path == "/api/jack/send":           # Jack messages an agent straight from the dashboard
                    if self._jack():
                        b = self._body()
                        a = hub._agent(b.get("to", ""))
                        if not a or a["state"] == "parked":
                            self._json(400, {"error": "unknown or parked agent"})
                        else:
                            # whoever is logged in sends it; Claude's scripted checks are labelled as Claude's
                            iid = hub.ask("claude" if b.get("as") == "claude" else self.who, b["to"], b["text"])
                            hub.deliver_now(b["to"])
                            self._json(200, {"id": iid})
                elif u.path == "/api/jack/secret":
                    if self._jack():
                        b = self._body()
                        hub.secret_put(b["name"], b["value"], b.get("scope", "fleet"), by="jack")
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/etsy/app":
                    if self._jack():
                        import etsy
                        b = self._body()
                        etsy.set_app(hub, b["key"], b["secret"])
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/approve":         # allow/deny a Muse permission pop-up an agent is stuck on
                    if self._jack():
                        b = self._body()
                        try:
                            hub.decide_approval(self.who, b["agent"], b["id"], b["decision"])
                            self._json(200, {"ok": True})
                        except ValueError as e:
                            self._json(400, {"error": str(e)})
                elif u.path == "/api/jack/reply":          # Jack answers an item on his list; it goes to whoever raised it
                    if self._jack():
                        b = self._body()
                        try:
                            hub.deliver_now(hub.reply_need(int(b["id"]), self.who, str(b["text"]).strip()))
                            self._json(200, {"ok": True})
                        except ValueError as e:
                            self._json(400, {"error": str(e)})
                elif u.path == "/api/jack/dismiss":
                    if self._jack():
                        hub.resolve_need(int(self._body()["id"]))
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/task":
                    if self._jack():
                        b = self._body()
                        self._json(200, {"id": hub.add_task(int(b["project"]), b["title"], b.get("role", "engineer"),
                                                            b.get("done_def", ""), blocked_by=[int(x) for x in b.get("blocked_by") or []],
                                                            by="jack")})
                elif u.path == "/api/jack/seat":           # any seat can be held by an agent, Jack or Darragh
                    if self._jack():
                        b = self._body()
                        hub.seat(b["role"], b.get("who") or None)
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/pm":
                    if self._jack():
                        b = self._body()
                        hub.set_pm(b["product"], b.get("who") or None)
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/role":
                    if self._jack():
                        b = self._body()
                        hub.set_role(b["name"].strip(), b["soul"])
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/team":            # board puts an agent on a team; logged like any change
                    if self._jack():
                        import shlex
                        b = self._body()
                        self._json(200, {"result": hub.manage(self.who, shlex.join(["team", b["agent"], b["team"]]))})
                elif u.path == "/api/jack/place":           # put an agent on a product in a role (no file moves)
                    if self._jack():
                        b = self._body()
                        hub.place(b["agent"], b.get("product") or None, b.get("role") or None)
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/suggestion":
                    if self._jack():
                        b = self._body()
                        hub.decide_suggestion("jack", int(b["id"]), bool(b["accept"]), b.get("note", ""))
                        self._json(200, {"ok": True})
                elif u.path == "/api/jack/release":
                    if self._jack():
                        hub.task_release("jack", int(self._body()["task"]))
                        self._json(200, {"ok": True})
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
            except PermissionError as e:
                self._json(403, {"error": str(e)})
            except (ValueError, KeyError) as e:
                self._json(400, {"error": str(e)})
            except Exception as e:
                self._json(500, {"error": str(e)})

    return ThreadingHTTPServer((host, port), H)


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
    import etsy                                   # every shop linked on the dashboard (Vault → Etsy)
    return rows + etsy.sales(h)


def register_accounts(h, accounts):
    """A Muse login the hub holds becomes an agent entry with no token; whoever joins under that name claims it."""
    with h.lock:
        for name in accounts:
            h.db.execute("insert or ignore into agents(name, kind) values(?, 'muse')", (name,))


def main(cfg_path, *args):
    cfg = json.load(open(cfg_path))
    import muse
    accounts = cfg["accounts"]
    parked = set(cfg.get("parked", []))
    muse_t = muse.MuseTransport(cfg["muse_cli"], accounts)
    h = Hub(cfg["db"], None)
    h.jobs_dir = cfg.get("jobs_dir")
    vault = lambda name: (h.db.execute("select value from secrets where name=?", (name,)).fetchone() or {"value": None})["value"]
    slack_t = muse.SlackTransport(token=lambda: (vault("slack-bot-token") or "").strip() or None,
                                  users=cfg.get("slack_users", {}), state_dir=os.path.dirname(cfg["db"]))
    h.transport = muse.KindRouter(lambda n: h._agent(n)["kind"], muse=muse_t, slack=slack_t)
    h.accounts = accounts
    register_accounts(h, accounts)
    for name in parked:
        if h._agent(name):
            h._set("agents", name, state="parked")

    cmd = args[0] if args else None
    if cmd == "token":
        print(h.add_agent(args[1], cfg.get("kinds", {}).get(args[1], "poll")))
        return
    if cmd == "reset-chat":                  # open fresh fleet side chats (each starts with the intro)
        for name in args[1:] or [n for n in accounts if n not in parked]:
            muse_t.reset(name)
            muse_t.session(name)                 # opens it now, with the intro as its first message
            print(f"{name}: new fleet side chat opened with the intro")
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
                    h.renew_logins({n: d for n, d in accounts.items() if n not in parked})
                    last_renew = time.time()
                if time.time() - last_rev > 3600:
                    h.pull_revenue(lambda: _revenue_fetch(h, cfg))
                    last_rev = time.time()
                h.tick()
            except Exception:
                log.write(time.strftime("%F %T ") + traceback.format_exc())
            time.sleep(15)

    sys.stdout = sys.stderr = log           # never block on a dead console (hidden window / service with no stdout)
    def watch():
        while True:
            try:
                h.observe()
            except Exception:
                log.write(time.strftime("%F %T ") + traceback.format_exc())
            time.sleep(h.OBSERVE_EVERY)

    if cfg.get("loop", True):               # assigns, nudges and delivers to fleet side chats; off = pure server
        threading.Thread(target=loop, daemon=True).start()
        threading.Thread(target=watch, daemon=True).start()

        def approvals():
            while True:
                try:
                    h.scan_approvals()
                except Exception:
                    log.write(time.strftime("%F %T ") + traceback.format_exc())
                time.sleep(h.APPROVALS_EVERY)
        threading.Thread(target=approvals, daemon=True).start()
    log.write(time.strftime("%F %T ") + f"hub up on {cfg.get('host', '127.0.0.1')}:{cfg['port']}\n")
    serve(h, cfg.get("host", "127.0.0.1"), cfg["port"], cfg["password"], cfg.get("join_code"), cfg.get("logins")).serve_forever()


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
