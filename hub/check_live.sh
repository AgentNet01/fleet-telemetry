#!/usr/bin/env bash
# Checks against the deployed hub on Jack's PC.
#   check_live.sh deploy   startup task exists; Funnel URL needs the password; all 12 Boboes listed
#   check_live.sh live     a real message to Boboe 2 is answered within 5 min; all 12 logins renewed
set -euo pipefail
PC=ai1@ai-alienware.tail3cffa4.ts.net
URL=https://ai-alienware.tail3cffa4.ts.net
CONF=~/.config/fleet-hub
PASS=$(cat "$CONF/dashboard_password")

board() { curl -sf -u "jack:$PASS" "$URL/api/board"; }

case "${1:-}" in
deploy)
  ssh -o BatchMode=yes "$PC" 'schtasks /query /tn fleet-hub' >/dev/null || { echo "no fleet-hub startup task"; exit 1; }
  code=$(curl -s -o /dev/null -w '%{http_code}' "$URL/")
  [ "$code" = 401 ] || { echo "dashboard without password answered $code, expected 401"; exit 1; }
  board | python3 -c '
import json, sys
names = sorted(a["name"] for a in json.load(sys.stdin)["agents"] if a["name"].lower().startswith("boboe"))
assert len(names) == 12, f"expected 12 Boboes, got {names}"
print("deploy OK:", ", ".join(names))'
  ;;
live)
  TOKEN=$(cat "$CONF/jack_token")
  id=$(curl -sf -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
       -d '{"to": "Boboe 2", "text": "Hub live test from Jack'"'"'s Claude: please reply with just the word pong."}' \
       "$URL/api/ask" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')
  for _ in $(seq 1 30); do
    status=$(curl -sf -u "jack:$PASS" "$URL/api/item?id=$id" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], "pong" in (d.get("reply") or "").lower())')
    [ "$status" = "answered True" ] && break
    sleep 10
  done
  [ "$status" = "answered True" ] || { echo "item #$id not answered with pong in 5 min: $status"; exit 1; }
  board | python3 -c '
import json, sys, time
ags = [a for a in json.load(sys.stdin)["agents"] if a["name"].lower().startswith("boboe")]
late = [a["name"] for a in ags if (a.get("login_expires") or 0) < time.time() + 25 * 86400]
assert len(ags) == 12 and not late, f"logins not renewed: {late}"
print("live OK: Boboe 2 answered; 12 logins good for 25+ days")'
  ;;
*) echo "usage: $0 deploy|live"; exit 2 ;;
esac
