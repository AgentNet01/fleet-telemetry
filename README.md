# Fleet Telemetry

Live status dashboard for the Boboe agent fleet (Boboe 1–6). Each agent's VM
pushes a JSON heartbeat every 30 seconds to the receiver; the dashboard shows
live app activity, observed working state, processes, files, cron health, and
per-agent detail views — all read-only.

```
fleet-telemetry/
├── orchestrator/      # runs on Jack's Mac (the orchestrator)
│   └── fleet_receiver.py
└── agents/            # runs on each agent VM
    ├── telemetryd.py
    ├── install.sh
    └── fleet_setup_prompt.md
```

## Orchestrator (Mac)

1. Put the shared secret in `token.txt` next to `fleet_receiver.py`
   (same secret every agent uses; never commit this file).
2. Run: `python3 orchestrator/fleet_receiver.py`
3. Open `http://<mac-tailscale-ip>:8787`

The dashboard auto-refreshes every 10s. Click any agent card for the detail
view: recent app activity, status timeline, full process list, searchable file
browser, and cron history.

**Live tail:** the detail view has a "Live tail" button. It asks that agent to
push every 2 seconds for 2 minutes (auto-stops). The daemon enforces hard caps
(≥2s interval, ≤5min) no matter what the receiver requests.

## Agents (Boboe VMs)

Each agent installs the daemon with the one-shot prompt in
`agents/fleet_setup_prompt.md` (Jack fills in the receiver IP and token before
pasting). The daemon:

- pushes CPU / memory / disk / process list / file inventory every 30s
- reports the app's live activity feed as its primary status
- heuristically detects working state (recent file changes, CPU, browser)
- survives VM replacement via a watchdog cron that reinstalls it
- spools failed pushes locally and flushes on recovery

## Security notes

- `token.txt` (orchestrator) and `~/.token` (agents) are never committed.
- The dashboard is read-only: no remote controls.
- Agents push outbound only; the VMs accept no inbound connections.
