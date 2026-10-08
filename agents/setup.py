#!/usr/bin/env python3
"""One-time fleet setup, run by the agent itself (no hub push needed).

    python3 setup.py "<your agent name>" <claim-code> [hub-url]

Registers with the hub (claim-code is Jack's), stores creds in ~/.fleet, and
starts the telemetry daemon so the agent's machine shows on the dashboard.
Re-running it is safe — it just refreshes the token and restarts telemetry.
"""
import json, os, subprocess, sys, urllib.request

HUB = sys.argv[3].rstrip("/") if len(sys.argv) > 3 else "https://ai-alienware.tail3cffa4.ts.net"
name, code = sys.argv[1], sys.argv[2]

req = urllib.request.Request(HUB + "/api/claim", data=json.dumps({"name": name, "code": code}).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
token = json.load(urllib.request.urlopen(req, timeout=30))["token"]

fleet = os.path.expanduser("~/.fleet"); os.makedirs(fleet, exist_ok=True)
open(os.path.join(fleet, "token"), "w").write(token); os.chmod(os.path.join(fleet, "token"), 0o600)
open(os.path.join(fleet, "hub"), "w").write(HUB)
open(os.path.join(fleet, "agent"), "w").write(name)

# find telemetryd.py beside this script or in ~/.fleet; otherwise fetch it from the hub
here = os.path.dirname(os.path.abspath(__file__))
td = next((p for p in (os.path.join(here, "telemetryd.py"), os.path.join(fleet, "telemetryd.py"))
           if os.path.exists(p)), None)
if not td:
    td = os.path.join(fleet, "telemetryd.py")
    urllib.request.urlretrieve(HUB + "/telemetryd.py", td)

subprocess.run(["pkill", "-f", "telemetryd.py"], check=False)
subprocess.Popen([sys.executable, td], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                 start_new_session=True)
print(f"fleet: {name} registered, telemetry started -> {HUB}")
