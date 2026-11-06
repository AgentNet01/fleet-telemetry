"""Live check for PLAN11: every sport desk has at least one early and one game-day agent, every Muse agent but
pericles williams is on floor 2, and no floor-2 agent still holds a floor-1 task. Reads the hub DB over ssh; exit 0 = pass.

    python3 check_pairs_live.py
"""
import json
import subprocess
import sys

PC = "ai1@ai-alienware.tail3cffa4.ts.net"
PROBE = r"""
import json, sqlite3
db = sqlite3.connect(r'C:\fleet\hub.db')
cols = [r[1] for r in db.execute('pragma table_info(agents)')]
st = 'strategy' if 'strategy' in cols else 'null'
agents = [dict(zip(('name', 'team', 'strategy'), r)) for r in
          db.execute(f"select name, team, {st} from agents where kind='muse' and state != 'parked'")]
held = [r[0] for r in db.execute("select owner from tasks where status='working' and owner is not null "
                                 "union all select verifier from tasks where status='verifying' and verifier is not null")]
print(json.dumps({'agents': agents, 'held': held}))
"""
SPORTS = ("nba", "nfl", "cfb", "nhl", "cbb", "soccer")
DESKS = SPORTS + ("lab",)

out = subprocess.run(["ssh", PC, r"C:\fleet\venv\Scripts\python.exe -"], input=PROBE, capture_output=True, text=True, timeout=60)
if out.returncode:
    sys.exit(f"probe failed: {out.stderr.strip()[-300:]}")
d = json.loads(out.stdout.strip().splitlines()[-1])
bad = []
for s in SPORTS:
    have = [a["strategy"] for a in d["agents"] if a["team"] == s]
    if "early" not in have or "gameday" not in have:
        bad.append(f"{s}: want 1 early + 1 gameday, have {have}")
for a in d["agents"]:
    if a["name"] != "pericles williams" and a["team"] not in DESKS:
        bad.append(f"{a['name']} is still on floor 1 (team {a['team']})")
    if a["name"] == "pericles williams" and a["team"] in DESKS:
        bad.append("pericles williams moved off floor 1")
desk = {a["name"] for a in d["agents"] if a["team"] in DESKS}
bad += [f"{n} (floor 2) still holds a floor-1 task" for n in sorted(set(d["held"]) & desk)]
print("\n".join(bad) or "pairs live OK")
sys.exit(1 if bad else 0)
