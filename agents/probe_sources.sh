#!/bin/bash
# probe_sources.sh -- READ-ONLY. Finds where this machine's agent runtime keeps
# cron runs, subagents and live turn state, so the telemetry daemon can read
# them passively instead of asking the agent to report.
#
# Prints locations, owners, sizes, sqlite table layouts, JSON field names,
# socket paths and endpoint names -- never file contents, row data, field
# values or any environment value other than plain socket paths.
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

section "what the runtime processes have open (files + unix socket paths)"
# exact process names: "hatch" would otherwise match any /home/hatch command line
for pid in $(pgrep -x hatch; pgrep -x hatch-execd) ; do
  echo "-- pid $pid ($(cat /proc/$pid/comm 2>/dev/null))"
  for fd in /proc/$pid/fd/*; do
    t=$(readlink "$fd" 2>/dev/null) || continue
    case "$t" in
      socket:\[*) ino=${t#socket:[}; ino=${ino%]}
                  p=$(awk -v i="$ino" '$7==i && $8!="" {print $8}' /proc/net/unix 2>/dev/null | head -1)
                  [ -n "$p" ] && echo "socket $p" ;;
      /dev/*|/proc/*|/sys/*|/usr/*|/lib*|pipe:*|anon_inode:*) ;;
      *) echo "file $t" ;;
    esac
  done | sort | uniq -c | sort -rn | head -40
done

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

section "socket paths from those variables (only values that are plain file paths)"
env | grep -E '^[A-Z_]*(SOCK|SOCKET)=/' | while IFS='=' read -r name path; do
  case "$path" in *[!A-Za-z0-9/._-]*) echo "$name = (not a plain path, hidden)"; continue ;; esac
  [ -S "$path" ] && state=socket || state=missing
  echo "$name = $path ($state)"
done

section "runtime state file: field names and types only (no values)"
for f in /var/cache/hatch/*.json; do
  [ -f "$f" ] || continue
  python3 - "$f" <<'PY'
import json, sys
def walk(v, path, depth):
    if isinstance(v, dict):
        for k, x in list(v.items())[:40]:
            kind = type(x).__name__ + ("[%d]" % len(x) if isinstance(x, (list, dict)) else "")
            print("  " * depth + "%s: %s" % (k, kind))
            if depth < 3:
                walk(x, path + [k], depth + 1)
    elif isinstance(v, list) and v and depth < 4:
        print("  " * depth + "[0]:")
        walk(v[0], path, depth + 1)
try:
    print(sys.argv[1]); walk(json.load(open(sys.argv[1])), [], 1)
except Exception as e:
    print(sys.argv[1], "unreadable:", e)
PY
done

section "what each runtime socket offers (read-only GETs; endpoint names and status codes only)"
env | grep -E '^[A-Z_]*(SOCK|SOCKET)=/' | cut -d= -f2 | sort -u | while read -r sock; do
  [ -S "$sock" ] || continue
  for path in / /openapi.json /docs /routes /health /cron /crons /cron/runs /subagents /status; do
    code=$(curl -s -o /tmp/probe_body.$$ -w '%{http_code}' --max-time 3 --unix-socket "$sock" "http://localhost$path" 2>/dev/null)
    [ "$code" = "000" ] && continue
    keys=$(python3 -c "
import json,sys
try:
    d=json.load(open(sys.argv[1]))
    if isinstance(d,dict) and 'paths' in d: print('openapi paths:', ', '.join(list(d['paths'])[:60]))
    elif isinstance(d,dict): print('json keys:', ', '.join(list(d)[:20]))
    elif isinstance(d,list): print('json list of', len(d))
except Exception: print('non-json,', __import__('os').path.getsize(sys.argv[1]), 'bytes')
" /tmp/probe_body.$$ 2>/dev/null)
    echo "$sock GET $path -> $code  $keys"
  done
done
rm -f /tmp/probe_body.$$
