#!/usr/bin/env python3
"""
telemetryd -- push this agent's telemetry to Jack's fleet receiver over Tailscale.

Runs on the agent's VM as a persistent daemon (see install.sh). Every INTERVAL
seconds it collects lightweight stats and POSTs them as JSON to the receiver.
If the receiver is unreachable, payloads are spooled to disk and retried.

Identity and destination come from ~/workspace/telemetry/config.json
({"agent": "boboe2", "receiver_url": "http://<ip>:8787/ingest"}), written by
install.sh -- the script itself is identical across the fleet.

Config lives in ~/workspace/telemetry/:
  .token       shared secret (0600) -- written by install.sh, never logged
  proxy.conf   tunnel proxy URL, e.g. http://<host>:3130 -- written by install.sh

Everything reported is read passively from data that already exists (the
app's activity feed, files, processes, system stats). The agent is never
asked to write anything for the dashboard.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

# ---- config: loaded from ~/workspace/telemetry/config.json (written by install.sh) ----
# {"agent": "boboe2", "receiver_url": "http://RECEIVER_IP:8787/ingest"}
INTERVAL = 15             # seconds between routine pushes (base cadence)
POLL_TICK = 2          # seconds between cheap activity checks
CHANGE_DEBOUNCE = 5    # min seconds between change-triggered pushes
# ----------------------------------------------------------------------------------

HOME = os.path.expanduser("~")
# TDIR is the directory containing this script (~/workspace/telemetry).
# Resolved from the script path, NOT from $HOME: the daemon may run as a
# different user (e.g. root) than the agent who installed it.
TDIR = os.path.dirname(os.path.abspath(__file__))
# Agent home = parent of workspace (TDIR is <home>/workspace/telemetry).
HOME = os.path.dirname(os.path.dirname(TDIR))
CONFIG_FILE = os.path.join(TDIR, "config.json")

# set from config.json at startup (see main())
AGENT = None
RECEIVER_URL = None
TOKEN_FILE = os.path.join(TDIR, ".token")
PROXY_FILE = os.path.join(TDIR, "proxy.conf")
SPOOL_DIR = os.path.join(TDIR, "spool")
BOOTID_FILE = os.path.join(TDIR, ".boot_id")
LOG = os.path.join(TDIR, "telemetryd.log")


# Connection health, shipped with every push so a flaky link shows on the
# dashboard instead of only in this box's log.
HEALTH = {"started": time.time(), "post": {"ok": 0, "fail": 0}, "mailbox": {"ok": 0, "fail": 0},
          "last_error": None}


def note(kind, err=None):
    h = HEALTH[kind]
    if err is None:
        h["ok"] += 1
        h["last_ok"] = time.time()
    else:
        h["fail"] += 1
        HEALTH["last_error"] = {"where": kind, "text": str(err)[:300], "ts": time.time()}


HOOK_LOGS = os.path.join(HOME, "hooks", "logs")


def listener_alive():
    """Is the agent's front door (listen.py, started from its main chat) waiting right now?"""
    for pid in os.listdir("/proc") if os.path.isdir("/proc") else []:
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                if b"listen.py" in f.read():
                    return True
        except OSError:
            continue
    return False


def hook_stats(now, window=3600):
    """Per hook, from the runtime's own run logs: runs/wakes/other outcomes in
    the last hour, plus the newest non-silent result."""
    out = {}
    try:
        names = [n for n in os.listdir(HOOK_LOGS) if n.endswith(".jsonl")]
    except OSError:
        return out
    for n in names:
        s = {"runs": 0, "wakes": 0, "errors": 0, "last_run": None, "last_event": None}
        try:
            with open(os.path.join(HOOK_LOGS, n), "rb") as f:
                f.seek(0, 2)
                f.seek(max(0, f.tell() - 512 * 1024))   # ponytail: last 512 KB covers an hour at 5s polls
                lines = f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                e = json.loads(line)
                t = (e.get("started_at_ms") or 0) / 1000
            except (ValueError, AttributeError):
                continue
            if t < now - window:
                continue
            s["runs"] += 1
            s["last_run"] = max(s["last_run"] or 0, t)
            outcome = e.get("outcome")
            if outcome == "wake":
                s["wakes"] += 1
            elif outcome != "silent":
                s["errors"] += 1
            if outcome != "silent":
                s["last_event"] = {"ts": t, "outcome": outcome, "reason": str(e.get("reason") or "")[:200]}
        out[n[:-len(".jsonl")]] = s
    return out


def log(msg):
    line = "%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a") as f:
            f.write(line)
    except Exception:
        pass


def read_token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def opener():
    with open(PROXY_FILE) as f:
        proxy = f.read().strip()          # e.g. http://10.0.0.5:3130
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy}))


def cpu():
    try:
        l1, l5, l15 = os.getloadavg()
    except Exception:
        l1 = l5 = l15 = None
    return {"count": os.cpu_count(), "load1": l1, "load5": l5, "load15": l15}


CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_prev_ticks = {}   # pid -> cpu ticks at the previous sample
_prev_wall = None


def read_proc_stats():
    """[(pid, name, rss_mb, cpu_ticks)] from /proc -- container-scoped."""
    out = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % pid) as f:
                stat = f.read()
        except OSError:
            continue
        # comm sits in parens and may contain spaces; fields follow the last ')'
        name = stat[stat.find("(") + 1:stat.rfind(")")][:32]
        rest = stat[stat.rfind(")") + 2:].split()
        ticks = int(rest[11]) + int(rest[12])          # utime + stime
        out.append((int(pid), name, int(rest[21]) * PAGE / 1048576, ticks))
    return out


def cpu_percents(samples, prev, dt):
    """Per-pid CPU % over the last interval, top-style (100 = one core).

    Pure logic, unit-testable. None when there is no baseline yet (first
    sample after start). A pid absent from prev started during the interval.
    """
    if not prev or not dt or dt <= 0:
        return {pid: None for pid, _, _, _ in samples}
    return {pid: round(max(0, ticks - prev.get(pid, 0)) / CLK_TCK / dt * 100, 1)
            for pid, _, _, ticks in samples}


def procs():
    """Process list with memory and live CPU %.

    all/top rows are [name, rss_mb, cpu_pct, pid] (first two fields unchanged
    from v1). cpu_total is % of the whole machine (all cores).
    """
    global _prev_ticks, _prev_wall
    try:
        samples = read_proc_stats()
    except Exception:
        return {"top": [], "all": [], "unit": "MB", "cpu_total": None}
    now = time.time()
    pct = cpu_percents(samples, _prev_ticks,
                       now - _prev_wall if _prev_wall else None)
    _prev_ticks = {pid: ticks for pid, _, _, ticks in samples}
    _prev_wall = now
    allp = sorted(([name, round(rss, 1), pct[pid], pid]
                   for pid, name, rss, _ in samples), key=lambda r: -r[1])
    known = [r[2] for r in allp if r[2] is not None]
    total = (round(sum(known) / (os.cpu_count() or 1), 1)
             if known else None)
    return {"top": allp[:8], "all": allp, "unit": "MB", "cpu_total": total}


def disk():
    try:
        total, used, _ = shutil.disk_usage(HOME)
        return {"total_gb": round(total / 1e9, 1),
                "used_gb": round(used / 1e9, 2),
                "path": HOME}
    except Exception:
        return {}


def uptime_s():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return None


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except Exception:
        return None


# ---- machine info (read-only) ----
_prev_net = None          # (rx_bytes, tx_bytes, wall) at the previous sample
_ts_ip = (0.0, None)      # (checked_at, tailscale ipv4) -- refreshed every 5 min


def first_match(path, pattern):
    try:
        with open(path) as f:
            m = re.search(pattern, f.read(), re.M)
        return m.group(1).strip().strip('"') if m else None
    except OSError:
        return None


def read_cgroup_mb(name):
    try:
        with open("/sys/fs/cgroup/" + name) as f:
            v = f.read().strip()
        return None if v == "max" else round(int(v) / 1048576)
    except (OSError, ValueError):
        return None


def net_bytes():
    """Total (rx, tx) bytes over every interface except loopback."""
    rx = tx = 0
    with open("/proc/net/dev") as f:
        for line in f.readlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip() != "lo":
                cols = data.split()
                rx, tx = rx + int(cols[0]), tx + int(cols[8])
    return rx, tx


def system(now):
    """What this computer is. Memory figures from /proc/meminfo are the SHARED
    HOST's (every agent container on it draws from the same pool); limit_mb is
    this container's own cap, if one is set."""
    global _prev_net, _ts_ip
    u = os.uname()
    info = {"hostname": u.nodename, "kernel": u.release, "cores": os.cpu_count(),
            "os": first_match("/etc/os-release", r"^PRETTY_NAME=(.*)$"),
            "cpu_model": first_match("/proc/cpuinfo", r"^model name\s*:\s*(.*)$"),
            "host_mem_total_mb": None, "host_mem_available_mb": None,
            "limit_mb": read_cgroup_mb("memory.max"),
            "net_rx_bps": None, "net_tx_bps": None, "tailscale_ip": _ts_ip[1]}
    total = first_match("/proc/meminfo", r"^MemTotal:\s*(\d+)")
    avail = first_match("/proc/meminfo", r"^MemAvailable:\s*(\d+)")
    if total:
        info["host_mem_total_mb"] = round(int(total) / 1024)
    if avail:
        info["host_mem_available_mb"] = round(int(avail) / 1024)
    try:
        rx, tx = net_bytes()
        if _prev_net and now > _prev_net[2]:
            dt = now - _prev_net[2]
            info["net_rx_bps"] = round(max(0, rx - _prev_net[0]) / dt)
            info["net_tx_bps"] = round(max(0, tx - _prev_net[1]) / dt)
        _prev_net = (rx, tx, now)
    except (OSError, ValueError, IndexError):
        pass
    if now - _ts_ip[0] > 300:
        ip = None
        try:
            # note: some wrappers (e.g. this container's) don't accept "-4",
            # so take the first IPv4-looking line instead.
            out = subprocess.run(["tailscale", "ip"], capture_output=True,
                                 text=True, timeout=3).stdout.split()
            ip = next((l for l in out if "." in l and ":" not in l), None)
        except Exception:
            pass
        _ts_ip = (now, ip)
        info["tailscale_ip"] = ip
    return info


# ---- file viewing: Jack clicks a file, the receiver asks for it here ----
FETCH_MAX = 10 * 1024 * 1024
SECRETISH = re.compile(r"token|secret|credential|passw|private|\.env$|\.pem$|"
                       r"\.key$|\.p12$|id_rsa|id_ed25519", re.I)


def resolve_fetch(rel):
    """Map a requested workspace-relative path to a real file, or raise
    ValueError(reason). Pure apart from the filesystem, unit-testable.

    Only regular files under ~/workspace, at most 10 MB, never hidden files or
    secret-looking names -- checked on the path *after* symlinks resolve, so a
    link can't smuggle out something the rules would refuse."""
    root = os.path.realpath(os.path.join(HOME, "workspace"))
    if not isinstance(rel, str) or not rel or rel.startswith("/") or "\x00" in rel:
        raise ValueError("not a workspace path")
    full = os.path.realpath(os.path.join(root, rel))
    if not full.startswith(root + os.sep):
        raise ValueError("outside the workspace")
    parts = os.path.relpath(full, root).split(os.sep)
    if any(p.startswith(".") for p in parts):
        raise ValueError("hidden files aren't shared")
    if SECRETISH.search(parts[-1]):
        raise ValueError("the name looks like a secret, so it isn't shared")
    if not os.path.isfile(full):
        raise ValueError("the file no longer exists")
    if os.path.getsize(full) > FETCH_MAX:
        raise ValueError("it's larger than 10 MB")
    return full


def send_fetches(op, token, reqs):
    """Upload each requested file (or the reason it was refused)."""
    if not isinstance(reqs, list):
        return
    for r in reqs[:3]:
        if not isinstance(r, dict):
            continue
        body, err = b"", ""
        try:
            with open(resolve_fetch(r.get("path")), "rb") as f:
                body = f.read(FETCH_MAX + 1)[:FETCH_MAX]
        except ValueError as e:
            err = str(e)
        except OSError:
            err = "the file couldn't be read"
        headers = {"X-Agent-Token": token, "X-Agent": AGENT,
                   "X-Fetch-Id": str(r.get("id", ""))[:64],
                   "Content-Type": "application/octet-stream"}
        if err:
            headers["X-Fetch-Error"] = err
        req = urllib.request.Request(RECEIVER_URL.rsplit("/ingest", 1)[0] + "/upload",
                                     data=body, headers=headers, method="POST")
        try:
            op.open(req, timeout=60).read()
            log("file request %s: %s" % (r.get("path"), err or "%d bytes sent" % len(body)))
        except Exception as e:
            log("file upload failed: %s" % e)


def walk_workspace():
    """[(relpath, size_bytes, mtime)] for every file under ~/workspace."""
    root = os.path.join(HOME, "workspace")
    entries = []
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # skip the telemetry spool itself to avoid feedback loops
            if "spool" in dirnames and dirpath == os.path.join(root, "telemetry"):
                dirnames.remove("spool")
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                entries.append((os.path.relpath(p, root), st.st_size,
                                st.st_mtime))
    except Exception:
        pass
    return entries


def files(walked):
    """Workspace inventory: names, sizes and modified times (never contents).

    entries rows are [relpath, kb, mtime] (first two fields unchanged from v1).
    """
    entries = sorted(walked, key=lambda e: -e[1])
    return {"count": len(entries),
            "mb": round(sum(e[1] for e in entries) / 1e6, 1),
            "entries": [[rel, round(sz / 1024, 1), int(mt)]
                        for rel, sz, mt in entries[:500]]}


def _fetch_entries():
    """Raw entries from the agent activity feed socket (read-only).

    Same feed behind the app's sidebar and status indicators. Documented,
    sanctioned read path: ~/subscriptions/activity_feed/subscription.md.
    Raises on failure; callers handle it.
    """
    sock_path = os.environ.get("JARVIS_SANDBOX_API_SOCK",
                               "/run/hatch/sandbox-api/api.sock")
    import socket as _socket
    s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    s.settimeout(5)
    s.connect(sock_path)
    s.sendall(b"GET /activity/recent?limit=8 HTTP/1.0\r\n"
              b"Host: localhost\r\n\r\n")
    raw = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        raw += chunk
    s.close()
    body = raw.split(b"\r\n\r\n", 1)[1]
    return json.loads(body).get("result", {}).get("entries", [])


def peek_activity():
    """Cheap check: current activity status string only, for change detection.

    Same socket as activity() but minimal parse -- safe to call every few
    seconds. Returns None when idle or on any failure (failures never count
    as a "change", to avoid churn).
    """
    try:
        for e in _fetch_entries():
            if e.get("status") == "pending":
                return e.get("status_title") or e.get("title")
    except Exception:
        pass
    return None


def activity():
    """Read the agent activity feed from the daemon sandbox API (read-only).

    This is the same feed behind the app's sidebar and status indicators
    ("working", "drafting a response", ...). Documented, sanctioned read path:
    ~/subscriptions/activity_feed/subscription.md. No auth needed -- the socket
    is world-accessible by design for sandboxed agents.
    """
    try:
        entries = _fetch_entries()
        current = None
        for e in entries:
            if e.get("status") == "pending":
                current = e.get("status_title") or e.get("title")
                break
        slim = [{k: e.get(k) for k in ("timestamp", "activity_type", "status",
                                      "title", "status_title", "subtitle",
                                      "task_label", "message_id")}
                for e in entries]
        return {"current": current, "entries": slim}
    except Exception as e:
        return {"current": None, "entries": [], "error": str(e)[:120]}


def observed(walked, plist, now, self_pid):
    """Heuristic working detection from local evidence. Pure, unit-testable.

    Machine evidence only (files, CPU) -- shown as context on the dashboard,
    never as the agent's status. Signals are labeled so the dashboard can show
    what changed.

    The daemon's own directory and process are excluded: it rewrites its log
    and .boot_id every cycle, which used to make every agent look "working".
    """
    own = os.path.relpath(TDIR, os.path.join(HOME, "workspace")) + os.sep
    changed = sorted((e for e in walked
                      if now - e[2] < 300 and not e[0].startswith(own)),
                     key=lambda e: -e[2])
    busy = sorted((p for p in plist
                   if p[2] is not None and p[2] > 5.0 and p[3] != self_pid),
                  key=lambda p: -p[2])
    signals = []
    if changed:
        signals.append("%d file%s changed in last 5m"
                       % (len(changed), "" if len(changed) == 1 else "s"))
    if busy:
        signals.append("%s at %.0f%% cpu" % (busy[0][0][:24], busy[0][2]))
    if any("chrome" in p[0].lower() for p in plist):
        signals.append("browser running")   # context only, not "working"
    return {"working": bool(changed or busy), "signals": signals[:4],
            "recent": [[rel, int(mt)] for rel, _, mt in changed[:8]]}


# ---- capabilities + active work (for the dashboard's "what can it do" view) ----
# CAPABILITIES is the condensed, machine-readable version of
# docs/systems-overview.md. Bump the payload "daemon" version when it changes
# meaningfully so the dashboard can flag stale ones.
CAPABILITIES = {
    "execution": [
        "main chat (conversation with Jack)",
        "side chats (separate persistent conversations)",
        "subagents (background child agents, parallel, one nesting level)",
        "browser tasks (live Chromium: logins, forms, JS)",
        "crons (scheduled agent runs)", "hooks (event-driven)",
        "systemd services (e.g. this daemon)"],
    "compute": [
        "bash shell", "file read/write/edit", "code: write/run/test/debug",
        "artifacts: docs, web apps, PDFs, decks, spreadsheets",
        "media: image/video generation, TTS, podcast audio",
        "reusable skills (playbooks)"],
    "web": ["search + page fetch", "live browser automation",
            "deep research delegation"],
    "accounts": ["gmail", "slack (agentnet swarm)", "google drive/docs/sheets/slides/forms",
                 "github (Boboe2 user)", "instagram DMs", "spotify", "healthkit"],
    "coordination": ["group chats", "swarm autonomy inside Jack's boundaries",
                     "goals + tracked commitments"],
    "memory": ["long-term memory", "daily logs", "people/groups maps",
               "feed + ideas"],
    "limits": ["no inbound network (push-only)", "no GPU",
               "write actions need approval",
               "money / data deletion / outside contact / credential changes need Jack",
               "one app status line"],
}

def build_payload(token_note_replaced=False):
    bid = boot_id()
    vm_replaced = False
    try:
        if os.path.exists(BOOTID_FILE):
            with open(BOOTID_FILE) as f:
                if f.read().strip() != bid:
                    vm_replaced = True
        with open(BOOTID_FILE, "w") as f:
            f.write(bid or "")
    except Exception:
        pass
    mem = procs()
    walked = walk_workspace()
    now = time.time()
    return {
        "agent": AGENT,
        "daemon": 14,              # payload version; dashboard flags older ones
        "ts": now,
        "boot_id": bid,
        "vm_replaced": vm_replaced,
        "cpu": cpu(),
        "mem": mem,
        "disk": disk(),
        "uptime_s": uptime_s(),
        "files": files(walked),
        "activity": activity(),   # app's activity feed (same source as sidebar)
        # heuristic working detection (local evidence)
        "observed": observed(walked, mem["all"], now, os.getpid()),
        "system": system(now),    # OS, CPU, shared-host memory, network, IP
        "capabilities": CAPABILITIES,   # static: what this agent can do
        "health": dict(HEALTH, hooks=hook_stats(now), listener=listener_alive()),
    }


def post(op, token, payload):
    """POST telemetry. Returns (ok, cmd) where cmd is the receiver's optional
    command dict, e.g. {"burst": True, "interval": 2, "until": <epoch>}.
    The receiver can only *request* a faster push; hard caps below apply."""
    req = urllib.request.Request(
        RECEIVER_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "X-Agent-Token": token},
        method="POST")
    with op.open(req, timeout=15) as resp:
        cmd = {}
        if resp.status == 200:
            try:
                cmd = json.loads(resp.read()).get("cmd", {}) or {}
            except Exception:
                pass
        return resp.status == 200, cmd


# ---- burst mode (live tail) ----
# The dashboard's "Live tail" button asks the receiver for faster pushes.
# Safety caps, enforced here no matter what the receiver asks for:
BURST_MIN_INTERVAL = 2     # never push faster than every 2s
BURST_MAX_DURATION = 300   # never burst longer than 5 minutes per command
BURST_DEFAULT_INTERVAL = 2

_burst_until = 0.0
_burst_interval = INTERVAL


def handle_cmd(cmd, now):
    """Apply a receiver command. Pure logic, unit-testable.
    Returns (interval, until) for the burst state."""
    global _burst_until, _burst_interval
    if not isinstance(cmd, dict) or not cmd.get("burst"):
        return _burst_interval, _burst_until
    try:
        want_interval = max(BURST_MIN_INTERVAL,
                            int(cmd.get("interval", BURST_DEFAULT_INTERVAL)))
        want_until = min(now + BURST_MAX_DURATION,
                         float(cmd.get("until", 0)))
    except (TypeError, ValueError):
        return _burst_interval, _burst_until
    if want_until > now:
        _burst_until = want_until
        _burst_interval = want_interval
        log("burst mode: every %ss until %s"
            % (_burst_interval,
               time.strftime("%H:%M:%S", time.localtime(_burst_until))))
    return _burst_interval, _burst_until


def burst_state(now):
    """Current effective push interval and whether burst is active."""
    global _burst_until
    if _burst_until and now >= _burst_until:
        _burst_until = 0.0
        log("burst mode ended")
    if _burst_until:
        return _burst_interval, True
    return INTERVAL, False


def spool(payload):
    try:
        os.makedirs(SPOOL_DIR, exist_ok=True)
        # cap the spool so a long outage can't fill the disk
        existing = sorted(os.listdir(SPOOL_DIR))
        for old in existing[:-100]:
            os.remove(os.path.join(SPOOL_DIR, old))
        with open(os.path.join(SPOOL_DIR, "%d.json" % time.time()), "w") as f:
            json.dump(payload, f)
    except Exception as e:
        log("spool write failed: %s" % e)


def flush_spool(op, token):
    try:
        files_ = sorted(os.listdir(SPOOL_DIR))
    except Exception:
        return
    for fn in files_[:20]:
        p = os.path.join(SPOOL_DIR, fn)
        try:
            with open(p) as f:
                payload = json.load(f)
        except (OSError, ValueError):
            # a half-written file (crash mid-write) used to block the queue forever
            log("spool: dropping unreadable %s" % fn)
            try:
                os.remove(p)
            except OSError:
                pass
            continue
        try:
            ok, _cmd = post(op, token, payload)
            if ok:
                os.remove(p)
            else:
                break
        except Exception:
            break


def read_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


# ---- mailbox: things Jack's Mac sends this machine (v10) ----
# The VM can't accept connections, so it keeps one open to the receiver: the
# receiver answers as soon as something is queued for this agent, or after
# ~25s with nothing, and the daemon asks again. Slack messages for this agent
# land in INBOX, where the slack hook (agents/slack_hook.sh) picks them up.
INBOX = os.path.join(HOME, "inbox", "slack")
CURSOR_FILE = os.path.join(TDIR, ".mailbox_cursor")


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def inbox_name(it):
    # one file per Slack message: delivering it again replaces it instead of adding a copy
    return "%s-%s.json" % (it.get("channel_id") or "c", it.get("ts"))


def handle_mail(it):
    kind = it.get("kind")
    if kind == "slack":
        os.makedirs(INBOX, exist_ok=True)
        write_atomic(os.path.join(INBOX, inbox_name(it)), json.dumps(it))
    elif kind == "answered":   # the receiver saw this agent's reply in Slack: nothing left to do
        src = os.path.join(INBOX, inbox_name(it))
        if os.path.exists(src):
            os.makedirs(os.path.join(INBOX, "done"), exist_ok=True)
            os.replace(src, os.path.join(INBOX, "done", inbox_name(it)))


def mailbox_loop(token):
    op = opener()
    base = RECEIVER_URL.rsplit("/ingest", 1)[0]
    try:
        with open(CURSOR_FILE) as f:
            after = int(f.read().strip() or 0)
    except (OSError, ValueError):
        after = 0
    backoff = 1
    while True:
        try:
            url = "%s/api/wait?%s" % (base, urllib.parse.urlencode({"agent": AGENT, "after": after}))
            req = urllib.request.Request(url, headers={"X-Agent-Token": token})
            with op.open(req, timeout=60) as r:
                reply = json.loads(r.read())
            items = reply.get("items") or []
            after = int(reply.get("after", after))   # receiver may reset a stale cursor
            for it in items:
                handle_mail(it)
                after = max(after, int(it["id"]))
            # saved only after the files are written: a crash re-fetches, never skips
            write_atomic(CURSOR_FILE, str(after))
            note("mailbox")
            backoff = 1
        except Exception as e:
            note("mailbox", e)
            log("mailbox: %s" % e)
            time.sleep(backoff)
            backoff = min(30, backoff * 2)


def main():
    global AGENT, RECEIVER_URL
    os.makedirs(TDIR, exist_ok=True)
    cfg = read_config()
    AGENT, RECEIVER_URL = cfg["agent"], cfg["receiver_url"]
    token = read_token()
    op = opener()
    log("telemetryd starting for %s -> %s" % (AGENT, RECEIVER_URL))
    threading.Thread(target=mailbox_loop, args=(token,), daemon=True).start()
    last_push = 0.0
    last_activity = None
    while True:
        try:
            now = time.time()
            interval, bursting = burst_state(now)
            # Cheap 2s tick: only the activity string. A full (expensive)
            # payload goes out on schedule, in burst mode, or immediately
            # when the activity changes (debounced) -- so the dashboard's
            # live status reacts in seconds, not on the next heartbeat.
            # Commands from the receiver still ride the next push's reply:
            # worst-case latency is now one 15s interval, not 30s.
            cur = peek_activity()
            changed = cur is not None and cur != last_activity
            if cur is not None:
                last_activity = cur
            due = (now - last_push) >= interval
            fresh_change = changed and (now - last_push) >= CHANGE_DEBOUNCE
            if due or fresh_change:
                payload = build_payload()
                payload["burst"] = bursting
                try:
                    ok, cmd = post(op, token, payload)
                    note("post", None if ok else "HTTP not 200")
                    if ok:
                        handle_cmd(cmd, time.time())
                        send_fetches(op, token, cmd.get("fetch") if isinstance(cmd, dict) else None)
                        flush_spool(op, token)
                    else:
                        spool(payload)
                except Exception as e:
                    note("post", e)
                    log("post failed: %s" % e)
                    spool(payload)
                last_push = time.time()
        except Exception as e:
            log("cycle failed: %s" % e)
        time.sleep(POLL_TICK)


if __name__ == "__main__":
    main()
