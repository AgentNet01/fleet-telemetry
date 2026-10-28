"""Floor 2 health on the live hub, run on the PC: python check_floor_night.py [since_epoch]

Prints one block: the watcher's last poll per desk, games watched, wakes sent and answered, calls logged and graded,
sports errors in the log since `since`, and whether each desk agent's fleet command has `call` yet. Read-only.
"""
import json
import sqlite3
import sys
import time

since = float(sys.argv[1]) if len(sys.argv) > 1 else time.time() - 1800
db = sqlite3.connect("file:C:/fleet/hub.db?mode=ro", uri=True, timeout=30)
db.row_factory = sqlite3.Row
now = time.time()
print(time.strftime("%F %T"), f"window since {time.strftime('%H:%M', time.localtime(since))}")
for a in db.execute("select name, team, state, fleet_rev, last_out from agents where team in "
                    "('nba','nfl','cfb','nhl','cbb','soccer','lab') order by team"):
    st = db.execute("select * from desk_state where desk=?", (a["team"],)).fetchone()
    watching = db.execute("select count(*) from games where desk=? and status='STATUS_SCHEDULED' and start>?", (a["team"], now)).fetchone()[0]
    wakes = db.execute("select count(*) from items where too=? and created>? and frm='hub'", (a["name"], since)).fetchone()[0]
    stuck = db.execute("select count(*) from items where too=? and status in ('queued','sent') and created < ?", (a["name"], now - 3600)).fetchone()[0]
    calls = db.execute("select count(*), sum(result is not null) from calls where desk=?", (a["team"],)).fetchone()
    new = db.execute("select count(*) from calls where desk=? and made_at>?", (a["team"], since)).fetchone()[0]
    said = (now - a["last_out"]) / 60 if a["last_out"] else None
    print(f"{a['team']:6} {a['name']:12} {a['state']:7} poll {((now - st['next_poll']) / 60 + 5) if st and st['next_poll'] else -1:5.1f}m ago "
          f"watching {watching:3} wakes {wakes:2} stuck>1h {stuck} calls {calls[0]} (graded {calls[1] or 0}, new {new}) "
          f"said {'%.0fm ago' % said if said is not None else 'never'} fleet_rev {a['fleet_rev']}")
log = open("C:/fleet/hub.log", encoding="utf8", errors="replace").read().splitlines()[-4000:]
errs = [l for l in log if "sports" in l and ("Traceback" in l or "skipped" in l or "feed" in l)]
ups = [l for l in log if "hub up" in l]
print("hub restarts:", ups[-3:])
print("sports log lines (last 6):", *errs[-6:], sep="\n  ")
print("lines rows:", db.execute("select count(*) from lines").fetchone()[0],
      "| last line change:", time.strftime("%H:%M", time.localtime(db.execute("select max(at) from lines").fetchone()[0] or 0)))
