#!/bin/bash
# probe_sources.sh -- READ-ONLY. Finds where this machine's agent runtime keeps
# cron runs, subagents and live turn state, so the telemetry daemon can read
# them passively instead of asking the agent to report.
#
# Prints locations, owners, sizes, sqlite table layouts and row counts --
# never file contents, row data or environment values.
#
# Usage: agents/probe_sources.sh        (paste the whole output to Jack)
set -u

section() { printf '\n== %s\n' "$1"; }

section "listening unix sockets"
ss -lxp 2>/dev/null | awk 'NR>1 {print $5, $NF}' | sort -u | head -40

section "listening tcp ports"
ss -ltnp 2>/dev/null | awk 'NR>1 {print $4, $NF}' | sort -u | head -40

section "runtime processes"
ps -eo pid,user,comm --sort=-rss 2>/dev/null | head -15

section "files the runtime processes have open (no system libraries)"
for pid in $(pgrep -f 'hatch' 2>/dev/null); do
  ls -l "/proc/$pid/fd" 2>/dev/null | awk '{print $NF}'
done | grep '^/' | grep -Ev '^/(dev|proc|sys|usr|lib|lib64)/' | sort -u | head -60

section "candidate data files (mtime, bytes, owner, path)"
find / -xdev \( -path /proc -o -path /sys -o -path /usr -o -path /lib -o -path /lib64 \
     -o -name node_modules -o -name .git -o -name site-packages \) -prune -o -type f \
     \( -iname '*cron*' -o -iname '*subagent*' -o -iname '*job*' -o -iname '*session*' \
        -o -iname '*turn*' -o -iname '*run*.json*' -o -iname '*.db' -o -iname '*.sqlite*' \) \
     -printf '%TY-%Tm-%Td %TH:%TM  %10s  %u  %p\n' 2>/dev/null | sort -r | head -80

section "sqlite databases: tables, columns, row counts (no rows)"
find / -xdev \( -path /proc -o -path /sys -o -path /usr \) -prune -o -type f \
     \( -iname '*.db' -o -iname '*.sqlite' -o -iname '*.sqlite3' \) -print 2>/dev/null | head -20 |
while read -r db; do
  python3 - "$db" <<'PY'
import sqlite3, sys
db = sys.argv[1]
try:
    c = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    for (t,) in c.execute("select name from sqlite_master where type='table'"):
        cols = [r[1] for r in c.execute('pragma table_info("%s")' % t)]
        n = c.execute('select count(*) from "%s"' % t).fetchone()[0]
        print("%s :: %s (%d rows): %s" % (db, t, n, ", ".join(cols)))
except Exception as e:
    print("%s :: unreadable (%s)" % (db, e))
PY
done

section "environment variable NAMES mentioning sockets/APIs (values hidden)"
env | cut -d= -f1 | grep -Ei 'sock|api|url|endpoint|host' | sort
