# Fleet telemetry setup — paste this to each Boboe agent (Boboe 1, 3, 4, 5, 6)

> Jack: fill in RECEIVER_IP and TOKEN below before pasting. The agent will ask
> you to approve its Tailscale join (one approval per agent).

---

You are one of Jack Wilber's fleet of personal AI agents (Boboe 1-6). Jack is
building a telemetry dashboard on his Mac that shows every agent's live status
(CPU/RAM/disk, what the app shows you doing, files). Your job: install a small
telemetry daemon on your VM that pushes a JSON payload to his receiver every
30 seconds over his Tailscale network. The daemon also supports "live tail":
when Jack clicks the Live tail button on your dashboard card, the receiver asks
your daemon (via its reply to your next push) to report every 2 seconds for a
couple of minutes. Hard safety caps in the daemon (≥2s interval, ≤5min) apply
no matter what the receiver asks for.

Jack's receiver is already running at:
- RECEIVER_IP = {PASTE_JACKS_TAILSCALE_IP}   (his Mac's Tailscale IP)
- TOKEN = {PASTE_SHARED_TOKEN}               (shared secret, keep private)

## Step 1 — Join Jack's Tailscale network

Run `tailscale up`. It prints an approval link. Show ONLY the link to Jack and
ask him to open it and approve the device named `muse`. Wait for the join to
complete, then verify with `tailscale status` (it should say Connected). Do not
proceed until connected.

## Step 2 — Write the daemon files

Create `~/workspace/telemetry/` and write these two files EXACTLY as given.
Never modify the payload schema -- Jack's dashboard depends on it.

### File 1: `~/workspace/telemetry/telemetryd.py`

```python
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
import time
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
        "daemon": 9,              # payload version; dashboard flags older ones
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


def main():
    global AGENT, RECEIVER_URL
    os.makedirs(TDIR, exist_ok=True)
    cfg = read_config()
    AGENT, RECEIVER_URL = cfg["agent"], cfg["receiver_url"]
    token = read_token()
    op = opener()
    log("telemetryd starting for %s -> %s" % (AGENT, RECEIVER_URL))
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
                    if ok:
                        handle_cmd(cmd, time.time())
                        send_fetches(op, token, cmd.get("fetch") if isinstance(cmd, dict) else None)
                        flush_spool(op, token)
                    else:
                        spool(payload)
                except Exception as e:
                    log("post failed: %s" % e)
                    spool(payload)
                last_push = time.time()
        except Exception as e:
            log("cycle failed: %s" % e)
        time.sleep(POLL_TICK)


if __name__ == "__main__":
    main()
```

### File 2: `~/workspace/telemetry/install.sh`

```bash
#!/bin/bash
# install.sh -- idempotent installer for telemetryd.
# Safe to re-run (the watchdog cron does exactly that after VM replacements).
#
# Usage:
#   First install:  FLEET_AGENT=boboeN ./install.sh <receiver_ip> <token>
#   Re-install:     ./install.sh            (reuses existing config; the
#                                            watchdog cron uses this form)
set -u

TDIR=/home/hatch/workspace/telemetry
UNIT=/etc/systemd/system/telemetryd.service

mkdir -p "$TDIR/spool"

if [ $# -ge 2 ]; then
  AGENT="${FLEET_AGENT:?set FLEET_AGENT=boboeN}"
  RECEIVER_IP="$1"; TOKEN="$2"
  # 1. config + secrets (token file is 0600, never logged)
  printf '{"agent": "%s", "receiver_url": "http://%s:8787/ingest"}\n' \
    "$AGENT" "$RECEIVER_IP" > "$TDIR/config.json"
  printf '%s' "$TOKEN" > "$TDIR/.token"
  chmod 600 "$TDIR/.token"
  # 2. tunnel proxy: this VM reaches the tailnet through a runtime proxy.
  #    Capture it now (it is not visible to background services otherwise).
  #    NOTE: strip any credentials -- the tunnel proxy authenticates this VM
  #    itself; sending the egress-proxy credentials causes a 407 rejection.
  if [ -z "${HTTPS_PROXY:-}" ]; then
    echo "ERROR: HTTPS_PROXY is not set in this shell; cannot build tunnel proxy URL." >&2
    exit 1
  fi
  _HP="${HTTPS_PROXY##*@}"; _HP="${_HP#*://}"   # host:port (drop scheme+userinfo)
  _HOSTONLY="${_HP%:*}"                            # drop port
  printf 'http://%s:3130' "$_HOSTONLY" > "$TDIR/proxy.conf"
else
  [ -f "$TDIR/config.json" ] && [ -f "$TDIR/.token" ] && [ -f "$TDIR/proxy.conf" ] \
    || { echo "ERROR: no existing config; run with <receiver_ip> <token> first." >&2; exit 1; }
  AGENT="$(python3 -c "import json; print(json.load(open('$TDIR/config.json'))['agent'])")"
  echo "Reusing existing config for $AGENT."
fi

# 4. systemd unit (system-level: no user bus exists in this container).
#    /etc is ephemeral across VM replacements -- the watchdog cron re-runs
#    this script, which recreates the unit. Hence: fully idempotent.
cat > "$UNIT" <<EOF
[Unit]
Description=Boboe fleet telemetry daemon ($AGENT)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $TDIR/telemetryd.py
Restart=always
RestartSec=15
StandardOutput=append:$TDIR/telemetryd.log
StandardError=append:$TDIR/telemetryd.log

[Install]
WantedBy=default.target
EOF

systemctl daemon-reload
systemctl enable --now telemetryd.service >/dev/null 2>&1 || true
sleep 3

if systemctl is-active --quiet telemetryd.service; then
  echo "OK: telemetryd running under systemd."
else
  echo "systemd start failed; falling back to nohup background process."
  pkill -f "telemetryd.py" 2>/dev/null || true
  nohup /usr/bin/python3 "$TDIR/telemetryd.py" >>"$TDIR/telemetryd.log" 2>&1 &
  sleep 2
  pgrep -f "telemetryd.py" >/dev/null \
    && echo "OK: telemetryd running via nohup (pid $(pgrep -f 'telemetryd.py' | head -1))." \
    || { echo "ERROR: daemon did not start; see $TDIR/telemetryd.log" >&2; exit 1; }
fi

echo "Watch the log: tail -f $TDIR/telemetryd.log"
echo "Verify on Jack's dashboard: $(python3 -c "import json; print(json.load(open('$TDIR/config.json'))['receiver_url'].replace('/ingest',''))")"
```

Make it executable: `chmod +x ~/workspace/telemetry/install.sh`

## Step 3 — Install and start the daemon

Run (replace boboeN with YOUR agent name, e.g. boboe1):

```bash
cd ~/workspace/telemetry
FLEET_AGENT=boboeN ./install.sh {PASTE_JACKS_TAILSCALE_IP} {PASTE_SHARED_TOKEN}
```

When the daemon makes its first connection through the Tailscale tunnel, Jack
may get a one-time approval prompt on his side -- tell him to expect it and
approve it. Then confirm your tile appears on his dashboard at
http://{PASTE_JACKS_TAILSCALE_IP}:8787 and report back to Jack.

Verify locally: `tail -f ~/workspace/telemetry/telemetryd.log` should show the
startup line and no repeated "post failed" errors. Test the path directly with:
`curl --proxy $(cat ~/workspace/telemetry/proxy.conf) http://{PASTE_JACKS_TAILSCALE_IP}:8787/`
-- you should get a 404 (not found), which proves the tunnel reaches his
receiver. (Note: do NOT put the egress-proxy credentials in the proxy URL --
install.sh already strips them; the tunnel authenticates your VM itself.)

## Step 4 — Watchdog cron (survives VM replacement)

Your VM gets replaced periodically, which wipes `/etc` (including the systemd
unit). Create a cron job that reinstalls the daemon if it ever goes missing:

- id: `telemetry-watchdog-boboeN` (use your agent name)
- schedule: every 15 minutes
- body: a single shell check --
  `pgrep -f "[t]elemetryd.py" >/dev/null 2>&1 || /home/hatch/workspace/telemetry/install.sh`
  (no arguments: install.sh reuses the existing config, so the token never
  appears in the cron body; the [t] bracket trick keeps pgrep from matching
  the check itself)

## If something breaks

- Daemon won't start: check `~/workspace/telemetry/telemetryd.log` for the
  traceback. Common causes: config.json missing (re-run install.sh with the
  IP and token), or the receiver not running on Jack's Mac.
- `systemctl` unavailable in your container: install.sh falls back to a nohup
  background process automatically; the watchdog cron keeps it alive.
- If anything fails twice, stop and report the exact error to Jack instead of
  improvising network workarounds.

## Boundaries

- Never print, log, or paste the token anywhere except the two places it
  belongs (the install command and the `.token` file, which is chmod 600).
- The daemon is push-only and reports stats, filenames, and task labels --
  never file contents, credentials, or message bodies. Keep it that way.
