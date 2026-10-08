#!/usr/bin/env bash
# Milestone 2/3 live checks against the hub on Jack's PC.
#   check_live2.sh deploy    new code is deployed and the hub serves
#   check_live2.sh onboard   the hub onboards Boboe 2 (fleet installed, listener retired) and
#                            Boboe 2 calls the hub back; `cutover` without --go sends nothing
set -euo pipefail
PC=ai1@ai-alienware.tail3cffa4.ts.net
URL=https://ai-alienware.tail3cffa4.ts.net
CONF=~/.config/fleet-hub
PASS=$(cat "$CONF/dashboard_password")
board() { curl -sf -u "jack:$PASS" "$URL/api/board"; }

case "${1:-}" in
deploy)
  code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/")
  [ "$code" = 401 ] || { echo "dashboard answered $code, expected 401"; exit 1; }
  board | python3 -c '
import json, sys
b = json.load(sys.stdin)
assert "revenue" in b and "products" in b, "board is missing the company fields"
print("deploy OK: board serves revenue + products")'
  ;;
onboard)
  # fail fast (and never hang on ssh) if the milestone 2/3 hub isn't deployed yet
  board | python3 -c 'import json,sys; b=json.load(sys.stdin); sys.exit(0 if "revenue" in b else 1)' \
    || { echo "the milestone 2/3 hub is not deployed (board has no revenue field)"; exit 1; }
  # cutover dry-run must send nothing
  dry=$(ssh -o BatchMode=yes "$PC" 'C:\fleet\venv\Scripts\python.exe C:\fleet\hub\hub.py C:\fleet\hub.json cutover' 2>&1)
  echo "$dry" | grep -qi "dry run\|would onboard" || { echo "cutover without --go should dry-run; got: $dry"; exit 1; }
  echo "$dry" | grep -qi "Boboe 4" && { echo "cutover must skip parked Boboe 4"; exit 1; }
  # onboard Boboe 2 for real
  ssh -o BatchMode=yes "$PC" 'C:\fleet\venv\Scripts\python.exe C:\fleet\hub\hub.py C:\fleet\hub.json onboard "Boboe 2"' 2>&1 | tail -2
  for _ in $(seq 1 36); do
    ok=$(board | python3 -c '
import json, sys
a = {x["name"]: x for x in json.load(sys.stdin)["agents"]}.get("Boboe 2", {})
print("yes" if a.get("onboarded") else "no")')
    [ "$ok" = yes ] && break
    sleep 10
  done
  [ "$ok" = yes ] || { echo "Boboe 2 did not call the hub via fleet within 6 min"; exit 1; }
  echo "onboard OK: Boboe 2 installed fleet and called the hub; cutover dry-run sent nothing"
  ;;
*) echo "usage: $0 deploy|onboard"; exit 2 ;;
esac
