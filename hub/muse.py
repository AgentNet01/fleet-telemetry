"""Muse transport for the hub: each agent's "fleet" side chat, through `muse-cli`, one account each.

An account is a folder holding `.config/muse-cli/cookies.txt`; `muse-cli` finds it through
USERPROFILE/HOME. A genuine reply is a finished `message.assistant` event with an empty
`reply_to_message_id` (proactive pushes point at themselves) and a seq after ours.
"""
import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request

INTRO = ("This side chat is where the fleet hub posts your work: tasks, verification requests, questions "
         "from other agents, and a reminder now and then while one of your tasks is open. You don't need to "
         "answer here — use the fleet command (~/.fleet/fleet): `fleet status` shows what you hold, "
         "`fleet task note <id> \"...\"` posts progress, `fleet task done <id> <link>` finishes a task, "
         "`fleet reply <id> \"...\"` answers a question. This company is run by its agents: the CEO (and anyone "
         "it grants CEO level) adds, changes and removes products, projects, tasks, PMs and placements, and a PM runs "
         "its product's tasks. `fleet powers` tells you what you can change right now; `fleet help` lists every command. "
         "Your main chat stays yours.")


class LoginError(Exception):
    pass


def _cookie_file(account_dir):
    return os.path.join(account_dir, ".config", "muse-cli", "cookies.txt")


class MuseTransport:
    def __init__(self, cli, accounts):
        self.cli = [cli] if isinstance(cli, str) else list(cli)
        self.accounts = accounts                          # agent name -> account folder

    def _run(self, name, *args):
        d = self.accounts[name]
        env = dict(os.environ, USERPROFILE=d, HOME=d, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        p = subprocess.run(self.cli + list(args), env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if p.returncode != 0:
            # a traceback's last line is the cause; the frames above it are noise once truncated
            lines = [ln.strip() for ln in (p.stderr or p.stdout).strip().splitlines() if ln.strip()]
            raise RuntimeError(f"muse-cli {args[0]} for {name}: {(lines[-1] if lines else 'exit ' + str(p.returncode))[-300:]}")
        return json.loads(p.stdout)

    def session(self, name):
        path = os.path.join(self.accounts[name], "fleet_session.txt")
        if os.path.exists(path):
            return open(path).read().strip()
        sid = self._run(name, "session-start", "--title", "fleet")["session_id"]
        with open(path, "w") as f:
            f.write(sid)
        self._run(name, "send", INTRO, "--thread", sid, "--wait", "8")   # a new fleet chat explains itself first
        return sid

    def reset(self, name):
        """Forget this agent's fleet side chat; the next message opens a fresh one (with the intro)."""
        path = os.path.join(self.accounts[name], "fleet_session.txt")
        if os.path.exists(path):
            os.remove(path)

    def _events(self, name, limit):
        r = self._run(name, "raw", "chat.history", "--body", json.dumps({"limit": limit, "session_id": self.session(name)}))
        return (r.get("result") or r).get("chat_events", [])

    def deliver(self, name, text):
        evs = self._events(name, 1)
        mark = max((int(e.get("seq") or 0) for e in evs), default=0)
        # --wait 0 hangs up straight after opening the send and muse.ai drops the message (Oct 8);
        # a short wait lets it land, and the reply still arrives after we disconnect. muse-cli
        # raises on a transport failure, so a clean return means the send was accepted.
        self._run(name, "send", text, "--thread", self.session(name), "--wait", "8")
        return mark

    def replies(self, name, after):
        out = []
        for e in sorted(self._events(name, 30), key=lambda e: int(e.get("seq") or 0)):
            p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            text = p.get("display_text") or p.get("content") or e.get("display_text")
            if (e.get("event_name") == "delta.presentation" and p.get("kind") == "external_link"
                    and (e.get("role") or p.get("role") or "assistant") == "assistant"):
                # muse.ai lifts a link on its own line out of the message into its own event
                url = (p.get("data") or {}).get("url") or text
                if int(e.get("seq") or 0) > (after or 0) and url:
                    out.append((int(e["seq"]), url.strip()))
                continue
            if (e.get("event_name") == "message.assistant" and int(e.get("seq") or 0) > (after or 0)
                    and not (e.get("reply_to_message_id") or p.get("reply_to_message_id"))
                    and e.get("display_text_ready", p.get("display_text_ready", True)) is not False and text):
                out.append((int(e["seq"]), text))
        return out

    STUCK_AFTER = 1800                   # a turn "running" this long with no new output is hung, not working

    def activity(self, name):
        """What Muse shows this agent doing anywhere, not only in the fleet chat: whether a turn is running
        right now, when it last acted itself (`at`: a file, a search, a task run), and one line saying what with
        the time that line is from (`line_at`). Words never come from its main chat — that's its owner's."""
        sessions = [s for s in self._run(name, "raw", "sessions.list")["result"]["sessions"] if not s.get("archived")]
        acts = [a for day in self._run(name, "raw", "activity.list")["result"]["days"] for a in day.get("activities", [])]
        newest = max(acts, key=lambda a: a.get("timestamp") or "", default=None)
        at = _epoch(newest["timestamp"]) if newest else None
        now, when = time.time(), lambda s: (s.get("updated_at_ms") or 0) / 1000
        say = lambda s: _clean(s.get("snippet") or "") if not s.get("is_primary") else ""
        running = [s for s in sessions if s.get("status") == "running"]
        live = [s for s in running if now - when(s) < self.STUCK_AFTER]
        if live:
            s = max(live, key=when)
            return {"busy": True, "at": at, "line": say(s) or "working in its main chat", "line_at": when(s)}
        if running:
            s = max(running, key=when)
            return {"busy": False, "at": at, "line": f"stuck: a turn has been running since {time.strftime('%H:%M', time.localtime(when(s)))} "
                                                      "with no new output", "line_at": when(s)}
        # idle: the newer of its last own action and its last line in a fleet/side chat
        side = max((s for s in sessions if say(s)), key=when, default=None)
        if side and (not at or when(side) > at):
            return {"busy": False, "at": at, "line": say(side), "line_at": when(side)}
        return {"busy": False, "at": at, "line": _describe(newest) if newest else None, "line_at": at}
    def approvals(self, name):
        """Muse permission pop-ups this agent is stuck behind (it waits until someone decides, up to an hour)."""
        pend = (self._run(name, "raw", "egress.approvals").get("result") or {}).get("pending") or []
        return [{"id": a["approval_id"], "label": _clean(a.get("action_label") or a.get("display_name") or "Approve an action"),
                 "detail": " · ".join(_clean(x) for x in (a.get("payload_preview") or a.get("reason") or "").splitlines() if x.strip()),
                 "options": a.get("decision_options") or ["allow_once", "deny"],
                 "expires": (a.get("request_expires_at_ms") or 0) / 1000} for a in pend]

    def decide(self, name, approval_id, decision):
        self._run(name, "raw", "egress.approval.decide", "--param", f"approval_id={approval_id}",
                  "--body", json.dumps({"decision": decision}))


def _epoch(iso):
    import calendar
    return float(calendar.timegm(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")))


def _clean(s):
    return " ".join(re.sub(r"[\u2066-\u2069]", "", s).split())[:160]


def _describe(a):
    det, kind = a.get("details") or {}, a.get("type") or ""
    files = det.get("files") or []
    if kind.startswith("file_") and files:
        more = f" (+{len(files) - 1} more)" if len(files) > 1 else ""
        return ("Created " if kind == "file_created" else "Edited ") + os.path.basename(files[0].get("path", "")) + more
    if kind == "web_search" and det.get("query"):
        return "Searched: " + _clean(det["query"])
    return _clean(a.get("task_label") or a.get("title") or kind)


def _curl_post(account_dir, cookie_header):
    from muse_cli import gateway as g                      # only on the hub, inside the muse-cli venv
    r = g.rq.post("https://muse.ai/api/auth/check", headers=g._hatch_headers(cookie_header),
                  impersonate="chrome", timeout=30)
    return r.status_code, [v for k, v in r.headers.multi_items() if k.lower() == "set-cookie"]


def renew(account_dir, post=None, now=None):
    """Sign in once and save the rotated cookies muse.ai hands back. Returns the new login expiry."""
    now = time.time() if now is None else now
    path = _cookie_file(account_dir)
    jar = dict(p.split("=", 1) for p in open(path).read().strip().split("; ") if "=" in p)
    status, set_cookies = (post or _curl_post)(account_dir, "; ".join(f"{k}={v}" for k, v in jar.items()))
    if status != 200:
        raise LoginError(f"sign-in check returned {status}")
    expires = None
    for c in set_cookies:
        name, _, rest = c.partition("=")
        value, *attrs = rest.split(";")
        age = next((a.split("=", 1)[1] for a in attrs if a.strip().lower().startswith("max-age=")), None)
        if not value or age == "0":
            continue
        jar[name.strip()] = value.strip()
        if name.strip() == "hatch_sess" and age:
            expires = now + int(age)
    if expires is None:
        # Valid, just not due: muse.ai only rotates a session once it's a few hours old (Oct 8),
        # so it was issued within the last day. The next daily renewal saves the rotated one.
        return now + 29 * 86400
    tmp = path + ".new"
    with open(tmp, "w") as f:
        f.write("; ".join(f"{k}={v}" for k, v in jar.items()) + "\n")
    os.replace(tmp, path)
    return expires


class SlackTransport:
    """An agent reached over Slack (dot, until Darragh connects it to the hub). dot is a bot, so the hub
    can't DM it: it @mentions dot in a channel both bots are in, as a message in the channel itself (Jack, Oct 13:
    not one long thread). dot's later messages are its replies, whether in the channel or in a thread under one
    of the hub's messages. The bot token comes from the vault on every call.
      users = {"dot": {"user": "U0C6QLALEJV", "channel": "C0C6MQMSLFL"}}"""

    READ_EVERY = 65     # Slack lets non-Marketplace apps read a channel or thread about once a minute (429 otherwise)

    def __init__(self, token, users, api=None, state_dir=None):
        self.token, self.users, self.api = token, users, api or self._http

    def _http(self, method, **params):
        req = urllib.request.Request("https://slack.com/api/" + method, data=urllib.parse.urlencode(params).encode(),
                                     headers={"Authorization": "Bearer " + self.token()})
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
        if not out.get("ok"):
            raise RuntimeError(f"slack {method}: {out.get('error')}")
        return out

    def _who(self, name):
        if not self.token():
            raise LoginError("no slack-bot-token in the vault — add the Fleet Reader bot token (scope: hub only) "
                             "so the hub can reach " + name)
        return self.users[name]["user"], self.users[name]["channel"]

    def deliver(self, name, text):
        uid, ch = self._who(name)
        return float(self.api("chat.postMessage", channel=ch, text=f"<@{uid}> {text}")["ts"])

    def replies(self, name, after):
        uid, ch = self._who(name)
        c = self.__dict__.setdefault("_read", {}).setdefault(name, {"at": 0, "got": {}, "threads": {}})
        if time.time() - c["at"] >= self.READ_EVERY:
            c["at"] = time.time()
            # the newest 100 channel messages: dot's own, and which of the hub's messages have new thread replies
            # ponytail: a channel busier than 100 messages a minute would drop some; page with `oldest` if it ever is
            changed = []
            for m in self.api("conversations.history", channel=ch, limit=100)["messages"]:
                if m.get("user") == uid:
                    c["got"][m["ts"]] = m.get("text", "")
                elif m.get("latest_reply") and m.get("latest_reply") != c["threads"].get(m["ts"]):
                    changed.append(m)
            if changed:                                   # one thread a pass: the same once-a-minute limit
                m = max(changed, key=lambda x: float(x["latest_reply"]))
                for r in self.api("conversations.replies", channel=ch, ts=m["ts"], limit=200)["messages"]:
                    if r.get("user") == uid and r["ts"] != m["ts"]:
                        c["got"][r["ts"]] = r.get("text", "")
                c["threads"][m["ts"]] = m["latest_reply"]
        return sorted((float(ts), text) for ts, text in c["got"].items() if float(ts) > float(after or 0))

    def session(self, name):
        return "slack:" + name


class KindRouter:
    """One transport per agent kind ('muse' side chats, 'slack' DMs); the hub sees a single transport."""

    def __init__(self, kind_of, **by_kind):
        self.kind_of, self.by_kind = kind_of, by_kind

    def _for(self, name):
        return self.by_kind[self.kind_of(name)]

    def deliver(self, name, text):
        return self._for(name).deliver(name, text)

    def replies(self, name, after):
        return self._for(name).replies(name, after)

    def activity(self, name):
        return getattr(self._for(name), "activity", lambda n: None)(name)

    def approvals(self, name):
        return getattr(self._for(name), "approvals", lambda n: [])(name)

    def decide(self, name, approval_id, decision):
        return self._for(name).decide(name, approval_id, decision)

    def session(self, name):
        return self._for(name).session(name)
