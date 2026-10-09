#!/usr/bin/env bash
# Live checks for the company build (PLAN3) against the hub on Jack's PC.
#   check_live3.sh deploy   new code serves: password-gated, the four roles, the board, dot, a DB backup
#   check_live3.sh live     loop on; each active agent's fresh fleet side chat opened with the intro;
#                           nothing reached a parked agent; telemetry still fresh; no tracebacks
set -euo pipefail
PC=ai1@ai-alienware.tail3cffa4.ts.net
URL=https://ai-alienware.tail3cffa4.ts.net
PASS=$(cat ~/.config/fleet-hub/dashboard_password)
ACTIVE='Boboe 5,Boboe 6,Boboe 8,Boboe 9,Boboe Prime'
api() { curl -sf --max-time 20 -u "jack:$PASS" "$URL$1"; }
pcpy() { scp -q -o BatchMode=yes /dev/stdin "$PC:C:/fleet/check3.py" && ssh -o BatchMode=yes "$PC" 'C:\fleet\venv\Scripts\python.exe C:\fleet\check3.py; Remove-Item C:\fleet\check3.py'; }

case "${1:-}" in
deploy)
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$URL/")" = 401 ] || { echo "dashboard must need the password"; exit 1; }
  api /api/org | python3 -c '
import json, sys
o = json.load(sys.stdin)
assert sorted(o["roles"]) == ["designer", "engineer", "marketer", "optimizer"], o["roles"]
assert "darragh" in o["board"] and "jack" in o["board"], o["board"]
assert o["ceo"] == "dot", o["ceo"]
assert any(a["name"] == "dot" and a["kind"] == "slack" for a in o["agents"]), o["agents"]'
  api /api/board | python3 -c '
import json, sys, time
b = json.load(sys.stdin)
names = {a["name"] for a in b["agents"]}
assert not any(n.startswith("zz-") for n in names), names
assert "products" in b and "revenue" in b'
  api /api/suggestions >/dev/null
  pcpy <<'EOF'
import glob; assert glob.glob(r"C:\fleet\hub.db.bak-*"), "no DB backup"
print("backup ok")
EOF
  echo "deploy OK"
  ;;
live)
  ACTIVE="$ACTIVE" pcpy <<'EOF'
import json, os, sqlite3, sys
sys.path.insert(0, r"C:\fleet\hub")
cfg = json.load(open(r"C:\fleet\hub.json"))
assert cfg.get("loop") is True, "loop is not on"
golive = float(open(r"C:\fleet\golive.txt").read())
import muse
t = muse.MuseTransport(cfg["muse_cli"], cfg["accounts"])
for name in ["Boboe 5", "Boboe 6", "Boboe 8", "Boboe 9", "Boboe Prime"]:
    p = os.path.join(cfg["accounts"][name], "fleet_session.txt")
    assert os.path.exists(p) and os.path.getmtime(p) >= golive, f"{name}: no fresh fleet side chat since go-live"
    evs = sorted(t._events(name, 30), key=lambda e: int(e.get("seq") or 0))
    users = [(e.get("payload") or {}).get("display_text", "") for e in evs if e.get("event_name") == "message.user"]
    assert users and users[0].startswith(muse.INTRO[:40]), f"{name}: the fleet chat didn't open with the intro: {users[:1]}"
d = sqlite3.connect(cfg["db"])
parked = cfg.get("parked", [])
n = d.execute(f"select count(*) from items where too in ({','.join('?'*len(parked))}) and sent_at >= ?", (*parked, golive)).fetchone()[0]
assert n == 0, f"{n} items reached a parked agent"
log = open(cfg["log"], encoding="utf-8", errors="replace").read()
tail = log[log.rindex("hub up"):]
assert "Traceback" not in tail, tail[-1500:]
print("live OK (pc side)")
EOF
  api /api/board | python3 -c '
import json, sys, time
b = json.load(sys.stdin)
for a in b["agents"]:
    if a["name"] in ("Boboe 5", "Boboe 6", "Boboe 8", "Boboe 9", "Boboe Prime"):
        assert a["state"] == "active", a
print("live OK")'
  for a in "Boboe%205" "Boboe%206" "Boboe%208" "Boboe%209" "Boboe%20Prime"; do
    api "/api/telemetry?agent=$a" | python3 -c "import sys,json,time; d=json.load(sys.stdin); age=time.time()-d['_at']; assert age<180, ('$a', age)"
  done
  echo "telemetry fresh"
  ;;
*) sed -n 2,5p "$0"; exit 2 ;;
esac
