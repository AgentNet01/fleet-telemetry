"""Muse transport for the hub: each agent's "fleet" side chat, through `muse-cli`, one account each.

An account is a folder holding `.config/muse-cli/cookies.txt`; `muse-cli` finds it through
USERPROFILE/HOME. A genuine reply is a finished `message.assistant` event with an empty
`reply_to_message_id` (proactive pushes point at themselves) and a seq after ours.
"""
import json
import os
import subprocess
import time


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
            raise RuntimeError(f"muse-cli {args[0]} for {name}: {(p.stderr or p.stdout).strip()[-300:]}")
        return json.loads(p.stdout)

    def session(self, name):
        path = os.path.join(self.accounts[name], "fleet_session.txt")
        if os.path.exists(path):
            return open(path).read().strip()
        sid = self._run(name, "session-start", "--title", "fleet")["session_id"]
        with open(path, "w") as f:
            f.write(sid)
        return sid

    def _events(self, name, limit):
        r = self._run(name, "raw", "chat.history", "--body", json.dumps({"limit": limit, "session_id": self.session(name)}))
        return (r.get("result") or r).get("chat_events", [])

    def deliver(self, name, text):
        evs = self._events(name, 1)
        mark = max((int(e.get("seq") or 0) for e in evs), default=0)
        # --wait 0 hangs up straight after opening the send and muse.ai drops the message (Oct 8);
        # a few seconds lets it land, and the reply still arrives after we disconnect.
        self._run(name, "send", text, "--thread", self.session(name), "--wait", "8")
        if not any(e.get("event_name") == "message.user" and int(e.get("seq") or 0) > mark for e in self._events(name, 10)):
            raise RuntimeError(f"message to {name} didn't land in its fleet chat")
        return mark

    def replies(self, name, after):
        out = []
        for e in sorted(self._events(name, 30), key=lambda e: int(e.get("seq") or 0)):
            p = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            text = p.get("display_text") or p.get("content") or e.get("display_text")
            if (e.get("event_name") == "message.assistant" and int(e.get("seq") or 0) > (after or 0)
                    and not (e.get("reply_to_message_id") or p.get("reply_to_message_id"))
                    and e.get("display_text_ready", p.get("display_text_ready", True)) is not False and text):
                out.append((int(e["seq"]), text))
        return out


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
