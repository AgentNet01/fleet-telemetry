# Fleet telemetry setup — paste this to each Boboe agent (Boboe 1, 3, 4, 5, 6)

> Jack: fill in RECEIVER_IP and TOKEN below before pasting. The agent will ask
> you to approve its Tailscale join (one approval per agent).

---

You are one of Jack Wilber's fleet of personal AI agents (Boboe 1-6). Jack is
building a telemetry dashboard on his Mac that shows every agent's live status
(CPU/RAM/disk, current task, files, cron health). Your job: install a small
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
  status.json  {"state": "working|idle", "task": "...", "since": <ts>}
               -- updated by the agent itself whenever it starts/finishes work
  cron_heartbeat.json  {"crons": [{"id": ..., "last_run": ..., "status": ...}]}
               -- updated by the agent's cron jobs each tick (optional)
"""

import json
import os
import shutil
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
        "daemon": 2,              # payload version; dashboard flags older ones
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
  printf '{"agent": "%s", "receiver_url": "http://%s:8787/ingest"}
' \
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

# 3. default status file (the agent updates it as it works)
[ -f "$TDIR/status.json" ] || \
  printf '{"state": "idle", "task": "", "since": %s}
' "$(date +%s)" > "$TDIR/status.json"

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
echo "Verify on Jack's dashboard: $(python3 -c "import json; print(json.load(open('$TDIR/config.json'))['receiver_url'])".replace('/ingest',''))"
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

## Step 5 — Keep your status current (ongoing)

The daemon reads `~/workspace/telemetry/status.json` every 30 seconds and
reports it as your "current task". Keep it truthful:

```json
{"state": "working", "task": "short description of what you are doing", "since": 1728000000}
```

- Set `state` to `working` when you begin substantive work, back to `idle`
  (with empty `task`) when done. `since` is the unix epoch when it changed.
- Your regular cron jobs should also write
  `~/workspace/telemetry/cron_heartbeat.json` each tick:
  `{"crons": [{"id": "your-cron-id", "last_run": "2026-10-05T18:30:00-04:00", "status": "ok"}]}`

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
