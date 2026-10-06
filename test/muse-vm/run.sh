#!/bin/bash
# run.sh -- a local stand-in for a Muse agent VM, to test daemon and dashboard
# changes before any real agent installs them.
#
#   test/muse-vm/run.sh up              build + boot the VM, start a test receiver,
#                                       install the daemon from this repo checkout
#   test/muse-vm/run.sh work "Writing doc"   fake agent opens a pending activity
#   test/muse-vm/run.sh idle            ...and finishes it
#   test/muse-vm/run.sh upgrade         re-run install.sh (after editing the daemon)
#   test/muse-vm/run.sh shell           a root shell inside the VM
#   test/muse-vm/run.sh down            stop everything
#
# Dashboard: http://127.0.0.1:8787  (test receiver, token "testtoken"; it keeps
# its own data and never touches the real receiver's).
#
# Known gaps vs the real VMs: no hatch runtime (so no real crons, subagents or
# app), and the activity feed only says what you tell it with work/idle.
set -eu
cd "$(dirname "$0")/../.."
REPO="$PWD"
RX="${TMPDIR:-/tmp}/muse-vm-receiver"

feed() {   # write the fake activity feed (newest first)
  docker exec -i muse-vm sh -c 'cat > /home/hatch/feed.json' <<EOF
[{"timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "activity_type": "goal", "status": "$1",
  "title": "$2", "status_title": "$2", "subtitle": "simulated by test/muse-vm/run.sh"}]
EOF
}

case "${1:-}" in
  up)
    mkdir -p "$RX"
    ln -sf "$REPO/orchestrator/fleet_receiver.py" "$REPO/orchestrator/dashboard.html" "$RX/"
    printf testtoken > "$RX/token.txt"
    [ -f "$RX/pid" ] && kill "$(cat "$RX/pid")" 2>/dev/null || true
    (cd "$RX" && FLEET_BIND_IP=127.0.0.1 FLEET_PORT=8787 nohup python3 fleet_receiver.py </dev/null >receiver.log 2>&1 & echo $! > "$RX/pid") </dev/null >/dev/null 2>&1
    docker build -q -t muse-vm test/muse-vm >/dev/null
    docker rm -f muse-vm >/dev/null 2>&1 || true
    docker run -d --name muse-vm --hostname htch-runtime --privileged --cgroupns=host \
      -v /sys/fs/cgroup:/sys/fs/cgroup:rw -v "$REPO":/home/hatch/fleet-telemetry:ro muse-vm >/dev/null
    for _ in $(seq 30); do
      docker exec muse-vm systemctl is-active --quiet muse-sandbox-api muse-tunnel-proxy 2>/dev/null && break
      sleep 1
    done
    # first install exactly as an agent does it; the fake proxy credentials
    # must be stripped by install.sh or the tunnel answers 407
    docker exec -e HTTPS_PROXY=http://agent:secret@127.0.0.1:443 -e FLEET_AGENT=muse-test muse-vm \
      /home/hatch/fleet-telemetry/agents/install.sh host.docker.internal testtoken
    echo "Dashboard: http://127.0.0.1:8787"
    ;;
  upgrade) docker exec muse-vm /home/hatch/fleet-telemetry/agents/install.sh ;;
  work)    feed pending "${2:-Working on something}" ;;
  idle)    feed success "${2:-Finished}" ;;
  shell)   docker exec -it muse-vm bash ;;
  down)
    docker rm -f muse-vm >/dev/null 2>&1 || true
    [ -f "$RX/pid" ] && kill "$(cat "$RX/pid")" 2>/dev/null || true
    rm -f "$RX/pid"
    ;;
  *) sed -n '2,18p' "$0"; exit 1 ;;
esac
