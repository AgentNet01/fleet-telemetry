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

# 3. default status file (the agent updates it as it works)
[ -f "$TDIR/status.json" ] || \
  printf '{"state": "idle", "task": "", "since": %s}\n' "$(date +%s)" > "$TDIR/status.json"

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
