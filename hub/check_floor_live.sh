#!/usr/bin/env bash
# Floor 2 on the live hub: six desks staffed, the line watcher has read real games, and the board arrives quickly.
set -euo pipefail
URL=https://ai-alienware.tail3cffa4.ts.net
PASS=$(cat ~/.config/fleet-hub/dashboard_password)
OUT=$(mktemp)
start=$(python3 -c 'import time;print(time.time())')
curl -sf --compressed -m 60 -u "jack:$PASS" "$URL/api/board" -o "$OUT"
python3 - "$OUT" "$start" <<'PY'
import json, sys, time
took = time.time() - float(sys.argv[2])
b = json.load(open(sys.argv[1]))
desks = b["book"]["desks"]
staffed = {k: d["agents"] for k, d in desks.items()}
assert all(len(v) == 1 for v in staffed.values()), f"each desk has one agent: {staffed}"
watching = {k: d["watching"] for k, d in desks.items()}
assert sum(1 for v in watching.values() if v) >= 4, f"the watcher should see games for most desks: {watching}"
floor2 = sorted(a["name"] for a in b["agents"] if a.get("floor") == 2)
assert len(floor2) == len(desks), f"one agent per desk on floor 2: {floor2} vs {list(desks)}"
assert took < 15, f"board took {took:.1f}s"
print(f"floor 2 live: {staffed} watching {watching}; board {took:.1f}s")
PY
