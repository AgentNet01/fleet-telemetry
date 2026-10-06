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
  status.json  {"state": "working|idle", "task": "...", "since": <ts>}
               -- updated by the agent itself whenever it starts/finishes work
  cron_heartbeat.json  {"crons": [{"id": ..., "last_run": ..., "status": ...}]}
               -- updated by the agent's cron jobs each tick (optional)
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
INTERVAL = 30             # seconds between pushes
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
STATUS_FILE = os.path.join(TDIR, "status.json")
CRON_FILE = os.path.join(TDIR, "cron_heartbeat.json")
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


def status():
    try:
        with open(STATUS_FILE) as f:
            s = json.load(f)
        return {"state": s.get("state", "idle"),
                "task": s.get("task", ""),
                "since": s.get("since")}
    except Exception:
        return {"state": "idle", "task": "", "since": None}


def crons():
    try:
        with open(CRON_FILE) as f:
            return json.load(f).get("crons", [])
    except Exception:
        return []


def activity():
    """Read the agent activity feed from the daemon sandbox API (read-only).

    This is the same feed behind the app's sidebar and status indicators
    ("working", "drafting a response", ...). Documented, sanctioned read path:
    ~/subscriptions/activity_feed/subscription.md. No auth needed -- the socket
    is world-accessible by design for sandboxed agents.
    """
    sock_path = os.environ.get("JARVIS_SANDBOX_API_SOCK",
                               "/run/hatch/sandbox-api/api.sock")
    try:
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
        entries = json.loads(body).get("result", {}).get("entries", [])
        current = None
        for e in entries:
            if e.get("status") == "pending":
                current = e.get("status_title") or e.get("title")
                break
        slim = [{k: e.get(k) for k in ("timestamp", "activity_type", "status",
                                      "title", "status_title", "subtitle")}
                for e in entries]
        return {"current": current, "entries": slim}
    except Exception as e:
        return {"current": None, "entries": [], "error": str(e)[:120]}


def observed(walked, plist, now, self_pid):
    """Heuristic working detection from local evidence. Pure, unit-testable.

    Backs up the self-reported status.json: catches real activity even when
    the agent forgot to update its status file. Signals are labeled so the
    dashboard can show WHY it thinks the agent is working.

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
               "one app status line; concurrent work is in active_work"],
}

ACTIVE_WORK_FILE = os.path.join(TDIR, "active_work.json")


def read_active_work():
    """Snapshot of what the agent is doing right now, written by a cron job
    (the daemon itself can't call agent tools). Marked stale if older than
    10 minutes."""
    try:
        with open(ACTIVE_WORK_FILE) as f:
            snap = json.load(f)
        snap["stale"] = (time.time() - snap.get("ts", 0)) > 600
        return snap
    except (OSError, ValueError):
        return {"ts": 0, "stale": True, "subagents": [], "crons": [],
                "note": "no snapshot yet"}


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
        "daemon": 4,              # payload version; dashboard flags older ones
        "ts": now,
        "boot_id": bid,
        "vm_replaced": vm_replaced,
        "cpu": cpu(),
        "mem": mem,
        "disk": disk(),
        "uptime_s": uptime_s(),
        "files": files(walked),
        "status": status(),       # self-reported by the agent (status.json)
        "activity": activity(),   # app's activity feed (same source as sidebar)
        # heuristic working detection (local evidence)
        "observed": observed(walked, mem["all"], now, os.getpid()),
        "crons": crons(),
        "system": system(now),    # OS, CPU, shared-host memory, network, IP
        "capabilities": CAPABILITIES,   # static: what this agent can do
        "active_work": read_active_work(),  # dynamic: subagents, jobs (cron-written)
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
    # default status file so the dashboard never shows a blank
    if not os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "w") as f:
            json.dump({"state": "idle", "task": "", "since": time.time()}, f)
    while True:
        try:
            interval, bursting = burst_state(time.time())
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
        except Exception as e:
            log("cycle failed: %s" % e)
        interval, _ = burst_state(time.time())
        time.sleep(interval)


if __name__ == "__main__":
    main()
