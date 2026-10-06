#!/bin/bash
# watchdog_hook.sh -- Muse hook script that keeps telemetryd running.
#
# Reboots wipe /etc (and with it the systemd unit), so the daemon stays down
# until something re-runs install.sh. The runtime runs this script every
# poll interval with no AI turn; it reinstalls on its own and only wakes the
# agent if the reinstall fails.
#
# Register once (agent tool call), then dry_run, then enable:
#   hooks.add  id=telemetry-watchdog  interval=60s
#              script=~/hooks/scripts/telemetry-watchdog.sh
#              prompt="telemetryd is down and install.sh failed. Read the
#                      reason, fix it, re-run install.sh, report to Jack."
# Copy this file to that script path first (see README "Watchdog hook").
source "$HATCH_HOOK_RUNTIME"

INSTALL=/home/hatch/workspace/telemetry/install.sh

if pgrep -f "[t]elemetryd.py" >/dev/null; then
  silent "telemetryd running"; exit 0
fi

out="$("$INSTALL" 2>&1)"
if pgrep -f "[t]elemetryd.py" >/dev/null; then
  silent "telemetryd was down; reinstalled"; exit 0
fi
wake "telemetryd down and install.sh failed" \
  "$(printf '%s' "$out" | tail -20 | python3 -c 'import json,sys; print(json.dumps({"install_output": sys.stdin.read()}))')"
