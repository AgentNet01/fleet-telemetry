#!/bin/bash
# fleet-telemetry hook: keeps ~/.fleet/telemetryd.py running through crashes and VM replacements
# (a replacement keeps ~ and the runtime's hooks, but kills every process). The runtime runs it
# every 60s with no AI turn. It never wakes the chat: if the daemon won't stay up, the agent just
# shows dark on the dashboard.
#   hooks.add id=fleet-telemetry interval=60s script=~/hooks/scripts/fleet-telemetry.sh
source "$HATCH_HOOK_RUNTIME"

if pgrep -f "[.]fleet/telemetryd.py" >/dev/null; then
  silent "running"; exit 0
fi
setsid nohup python3 "$HOME/.fleet/telemetryd.py" >>"$HOME/.fleet/telemetryd.log" 2>&1 </dev/null &
silent "restarted"
