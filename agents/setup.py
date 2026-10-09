#!/usr/bin/env python3
"""Fleet setup, run by the agent itself from its fleet-telemetry checkout.

    python3 agents/setup.py "<your agent name>" <claim-code> [hub-url]

Registers with the hub, installs the telemetry daemon in ~/.fleet, points it at the VM's tunnel
proxy (background processes can't use the chat turn's proxy), installs the restart hook script,
and removes every older telemetry/Slack install. Safe to re-run: re-running is how you upgrade.
"""
import json, os, shutil, subprocess, sys, urllib.parse, urllib.request

HUB = sys.argv[3].rstrip("/") if len(sys.argv) > 3 else "https://ai-alienware.tail3cffa4.ts.net"
name, code = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
home = os.path.expanduser("~")
fleet = os.path.join(home, ".fleet"); os.makedirs(fleet, exist_ok=True)

# How the daemon reaches the hub once it runs outside a chat turn. The turn's proxy refuses the hub
# (its name resolves to a private tailnet address), so prefer the VM's tunnel proxy (same host,
# port 3130, no credentials) to the hub's tailnet-only http port; that is the route the old daemon
# used for weeks. Keep the first route that answers.
proxy_conf, ingest = os.path.join(fleet, "proxy.conf"), os.path.join(fleet, "ingest")
host = urllib.parse.urlparse(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "").hostname
tailnet = "http://" + urllib.parse.urlparse(HUB).hostname + ":8780"
routes = ([(f"http://{host}:3130", tailnet), (f"http://{host}:3130", HUB)] if host else []) + [(None, HUB)]
working = []                        # every route that answers now, best first; the daemon fails over along it
for proxy, base in routes:
    o = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy})) if proxy \
        else urllib.request.build_opener()
    for _ in range(2):              # the VM's proxies are flaky: one retry before giving up on a route
        try:
            o.open(base + "/fleet.py", timeout=20).read()
            working.append((proxy, base, o))
            break
        except Exception:
            continue
if not working:
    sys.exit("fleet: can't reach the hub by any route (tunnel to tailnet, tunnel to hub, default). Paste this to Jack.")
proxy, base, op = working[0]
json.dump([{"proxy": p, "ingest": b + "/api/ingest"} for p, b, _ in working], open(os.path.join(fleet, "routes.json"), "w"))
open(ingest, "w").write(base + "/api/ingest")
if proxy:
    open(proxy_conf, "w").write(proxy)
elif os.path.exists(proxy_conf):
    os.remove(proxy_conf)
route = f"{base} via {proxy or 'default route'} ({len(working)} of {len(routes)} routes work)"

req = urllib.request.Request(base + "/api/claim", data=json.dumps({"name": name, "code": code}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
token = json.load(op.open(req, timeout=60))["token"]
open(os.path.join(fleet, "token"), "w").write(token); os.chmod(os.path.join(fleet, "token"), 0o600)
open(os.path.join(fleet, "hub"), "w").write(HUB)
open(os.path.join(fleet, "agent"), "w").write(name)
shutil.copy2(os.path.join(here, "telemetryd.py"), os.path.join(fleet, "telemetryd.py"))
cli = os.path.join(fleet, "fleet")                     # the fleet command, from the same checkout
shutil.copy2(os.path.join(here, "..", "hub", "fleet.py"), cli); os.chmod(cli, 0o755)
bindir = os.path.join(home, ".local", "bin")
if os.path.isdir(bindir) and not os.path.exists(os.path.join(bindir, "fleet")):
    os.symlink(cli, os.path.join(bindir, "fleet"))

# Remove every older install: the v10–v14 systemd daemon, its files, Slack listener, crons, hooks scripts.
sh = lambda c: subprocess.run(c, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sh("systemctl disable --now telemetryd.service; rm -f /etc/systemd/system/telemetryd.service; systemctl daemon-reload")
sh("crontab -l 2>/dev/null | grep -viE 'watchdog|slack|listen|telemetry' | crontab -")
for pat in ("listen.py", "telemetryd.py"):   # not via sh: the shell's own command line would match
    subprocess.run(["pkill", "-f", pat], check=False)
shutil.rmtree(os.path.join(home, "workspace", "telemetry"), ignore_errors=True)
hooks = os.path.join(home, "hooks", "scripts"); os.makedirs(hooks, exist_ok=True)
for old in ("telemetry-watchdog.sh", "slack-inbox.sh"):
    old = os.path.join(hooks, old)
    os.path.exists(old) and os.remove(old)

hook = os.path.join(hooks, "fleet-telemetry.sh")
shutil.copy2(os.path.join(here, "telemetry_hook.sh"), hook); os.chmod(hook, 0o755)

subprocess.Popen(["setsid", sys.executable, os.path.join(fleet, "telemetryd.py")],
                 stdout=open(os.path.join(fleet, "telemetryd.log"), "a"), stderr=subprocess.STDOUT,
                 stdin=subprocess.DEVNULL, start_new_session=True)
print(f"fleet: {name} registered; telemetry running; hub route: {route}; old installs removed; "
      f"fleet command at {cli}.\n"
      f"Last step (once): hooks.add id=fleet-telemetry interval=60s script={hook}, then enable it.\n"
      f"Old hooks to remove if you still have them: telemetry-watchdog, slack-inbox.")
