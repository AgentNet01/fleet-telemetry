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


def procs():
    """Process list inside this container (honest, container-scoped).

    Returns top (for the card) and all (for the detail view).
    """
    try:
        out = subprocess.run(["ps", "-eo", "comm,rss", "--sort=-rss"],
                             capture_output=True, text=True, timeout=10).stdout
        allp = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                allp.append([parts[0][:32], round(int(parts[1]) / 1024, 1)])
        return {"top": allp[:8], "all": allp, "unit": "MB"}
    except Exception:
        return {"top": [], "all": [], "unit": "MB"}


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


def files():
    """Workspace inventory: counts, sizes, and relative paths (names only)."""
    root = os.path.join(HOME, "workspace")
    entries, total = [], 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            # skip the telemetry spool itself to avoid feedback loops
            if "spool" in dirnames and dirpath == os.path.join(root, "telemetry"):
                dirnames.remove("spool")
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(p)
                except OSError:
                    continue
                total += sz
                entries.append((os.path.relpath(p, root), sz))
    except Exception:
        pass
    entries.sort(key=lambda e: -e[1])
    return {"count": len(entries),
            "mb": round(total / 1e6, 1),
            "entries": [[rel, round(sz / 1024, 1)] for rel, sz in entries[:500]]}


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


def observed():
    """Heuristic working detection from local signals.

    Backs up the self-reported status.json: catches real activity even when
    the agent forgot to update its status file. Signals are labeled so the
    dashboard can show WHY it thinks the agent is working.
    """
    signals = []
    now = time.time()
    try:
        root = os.path.join(HOME, "workspace")
        recent = 0
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                try:
                    if now - os.path.getmtime(os.path.join(dirpath, fn)) < 300:
                        recent += 1
                except OSError:
                    pass
            if recent > 25:
                break
        if recent:
            signals.append("%d files changed in last 5m" % recent)
    except Exception:
        pass
    try:
        out = subprocess.run(["ps", "-eo", "comm,pcpu", "--sort=-pcpu"],
                             capture_output=True, text=True,
                             timeout=10).stdout
        low = out.lower()
        if "chrome" in low:
            signals.append("browser running")
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                pcpu = float(parts[1])
            except ValueError:
                continue
            name = parts[0]
            if pcpu > 5.0 and name not in ("telemetryd.py", "ps"):
                signals.append("%s at %.0f%% cpu" % (name[:24], pcpu))
                break
    except Exception:
        pass
    return {"working": bool(signals), "signals": signals[:4]}


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
    return {
        "agent": AGENT,
        "ts": time.time(),
        "boot_id": bid,
        "vm_replaced": vm_replaced,
        "cpu": cpu(),
        "mem": procs(),
        "disk": disk(),
        "uptime_s": uptime_s(),
        "files": files(),
        "status": status(),       # self-reported by the agent (status.json)
        "activity": activity(),   # app's activity feed (same source as sidebar)
        "observed": observed(),   # heuristic working detection (local signals)
        "crons": crons(),
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
