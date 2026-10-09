#!/bin/bash
# vm_setup.sh -- proves agents/setup.py + the restart hook on a stand-in agent VM (Docker), against the
# live hub, under the throwaway agent name "zz-vm-test":
#   legacy installs are removed, exactly one daemon runs and reaches the hub, the hook restarts it after
#   a crash and after a restart of the whole machine (all processes gone, home kept), and a second setup
#   run leaves exactly one daemon.
#   FLEET_CLAIM=<claim code> test/vm_setup.sh
set -eu
cd "$(dirname "$0")/.."
: "${FLEET_CLAIM:?set FLEET_CLAIM}"
HUB=https://ai-alienware.tail3cffa4.ts.net
NAME=zz-vm-test
fail() { echo "FAIL: $*"; docker rm -f fleet-vm >/dev/null 2>&1; exit 1; }
in_vm() { docker exec -e HOME=/home/hatch fleet-vm bash -c "$1"; }

docker build -q -t muse-vm test/muse-vm >/dev/null
docker rm -f fleet-vm >/dev/null 2>&1 || true
docker run -d --name fleet-vm -v "$PWD":/home/hatch/fleet-telemetry:ro muse-vm sleep infinity >/dev/null
docker exec fleet-vm bash -c 'nohup python3 /opt/muse/tunnel_proxy.py >/dev/null 2>&1 &
  printf "[Service]\nExecStart=/bin/true\n" > /etc/systemd/system/telemetryd.service
  mkdir -p /home/hatch/hooks/scripts && printf "#!/bin/bash\necho old\n" > /home/hatch/hooks/scripts/telemetry-watchdog.sh
  chown -R hatch /home/hatch/hooks'
in_vm 'mkdir -p ~/workspace/telemetry && cp ~/fleet-telemetry/agents/telemetryd.py ~/workspace/telemetry/
       touch ~/workspace/telemetry/listen.py
       nohup python3 ~/workspace/telemetry/telemetryd.py >/dev/null 2>&1 &'
printf '#!/bin/bash\nsilent() { echo "silent: $*"; }\nwake() { echo "WAKE: $*"; }\n' | docker exec -i fleet-vm bash -c 'cat > /opt/muse/hook_runtime.sh'

setup() { in_vm "cd ~/fleet-telemetry && HTTPS_PROXY=http://agent:secret@127.0.0.1:443 python3 agents/setup.py $NAME $FLEET_CLAIM"; }
hook()  { docker exec -e HOME=/home/hatch -e HATCH_HOOK_RUNTIME=/opt/muse/hook_runtime.sh fleet-vm bash /home/hatch/hooks/scripts/fleet-telemetry.sh; }
count() { in_vm 'pgrep -fc "[t]elemetryd.py" || true'; }
fresh() {   # the hub got a heartbeat from this VM in the last 40s
  for _ in $(seq 20); do
    age=$(curl -s --max-time 15 -u "jack:$FLEET_CLAIM" "$HUB/api/telemetry?agent=$NAME" |
          python3 -c 'import sys,json,time;d=json.load(sys.stdin);print(int(time.time()-d["_at"]) if d.get("ts") else 999)')
    [ "$age" -lt 40 ] && return 0; sleep 3
  done; return 1; }

setup | tee /dev/stderr | grep -q "registered" || fail "setup didn't register"
in_vm 'test ! -e ~/workspace/telemetry' || fail "old ~/workspace/telemetry still there"
docker exec fleet-vm test ! -e /etc/systemd/system/telemetryd.service || fail "old systemd unit still there"
in_vm 'test ! -e ~/hooks/scripts/telemetry-watchdog.sh && test -x ~/hooks/scripts/fleet-telemetry.sh' || fail "hook scripts wrong"
[ "$(count)" = 1 ] || fail "expected 1 daemon after setup, got $(count)"
fresh || fail "hub got no heartbeat after setup"
in_vm 'test -s ~/.fleet/routes.json' || fail "setup didn't record its routes"
in_vm '~/.fleet/fleet status' | grep -q "You are" || fail "the fleet command isn't installed or can't reach the hub"

in_vm 'pkill -f "[.]fleet/telemetryd.py"'; sleep 1
[ "$(count)" = 0 ] || fail "daemon didn't die"
hook | grep -q "silent: restarted" || fail "hook didn't restart after crash"
hook | grep -q "silent: running" || fail "hook should be a no-op while running"
hook | grep -q WAKE && fail "hook must never wake the chat"
[ "$(count)" = 1 ] || fail "expected 1 daemon after crash restart, got $(count)"
fresh || fail "hub got no heartbeat after crash restart"

docker restart fleet-vm >/dev/null                      # VM replacement: every process gone, home kept
[ "$(count)" = 0 ] || fail "restart should leave no daemon"
hook | grep -q "silent: restarted" || fail "hook didn't restart after machine restart"
sleep 20; fresh || fail "hub got no heartbeat after machine restart"

docker exec fleet-vm bash -c 'nohup python3 /opt/muse/tunnel_proxy.py >/dev/null 2>&1 &'
setup >/dev/null; sleep 2
[ "$(count)" = 1 ] || fail "second setup run left $(count) daemons"

docker rm -f fleet-vm >/dev/null
echo "PASS: setup + restart hook (crash, machine restart, re-run)"
