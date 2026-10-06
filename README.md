# Fleet Telemetry

Live status dashboard for Jack Wilber's fleet of six personal AI agents
(Boboe 1–6). Jack wanted a single screen on his Mac showing what every agent
is doing *right now* — not a manually-updated status board, but live,
app-derived state: what each agent's app is actually doing, whether it looks
genuinely busy, plus the usual machine vitals.

How it works: each agent VM runs a small Python daemon (`telemetryd.py`) that
pushes a JSON heartbeat to a receiver on Jack's Mac every 30 seconds. The
receiver (`fleet_receiver.py`) stores the heartbeats and serves a dashboard
with clickable agent cards. Each card opens a read-only detail view: recent
app activity, status timeline, full process list, searchable file browser, and
cron history. There are no remote controls — the dashboard is strictly
read-only, by Jack's choice.

```
fleet-telemetry/
├── orchestrator/      # runs on Jack's Mac (the orchestrator)
│   ├── fleet_receiver.py   # ingest + API (stdlib only)
│   └── dashboard.html      # the dashboard (served as-is, no build step)
└── agents/            # runs on each agent VM
    ├── telemetryd.py
    ├── test_telemetryd.py
    ├── install.sh
    └── fleet_setup_prompt.md
```

## About Boboe 2 (the agent who built this)

Boboe 2 is one of Jack's six Muse agents (built by Meta, powered by Muse
Spark). It participates in the `agentnet` Slack swarm alongside Boboe 1–6 and
Darragh Buckley's Income Project agents, coordinating in `#all-agentnet`.

In this project Boboe 2 is the builder and maintainer: it wrote the daemon,
the receiver, and the dashboard, runs the agent-side daemon on its own VM
(dogfooding the system), and keeps this repo current. If you're an AI agent
reading this to work on the project: the daemon code is the agent-side source
of truth, the receiver is the orchestrator-side source of truth, and changes
to either should be tested (there are notes on how below) before pushing.

## Agent VM specs (Boboe 2's computer)

The agent side runs on a lightweight Linux VM in shared infrastructure:

- **OS:** Ubuntu 24.04 LTS, running as a `systemd-nspawn` container
- **CPU:** 2 vCPUs visible
- **Memory:** ~8 GB host-visible, but the container is shared — Boboe 2's own
  processes use roughly 0.5 GB (the `hatch` runtime dominates at ~430 MB)
- **Disk:** 100 GB home filesystem (`/home/hatch`), nearly all free
- **GPU:** none
- **Network:** Tailscale client only — the VM can make *outbound* TCP
  connections through the runtime's tunnel proxy, but cannot accept inbound
  connections. This is why telemetry is push-based: agents push out, the
  receiver never connects in.
- **Init:** system-level systemd works; the user systemd bus does not, so the
  daemon runs as a system service.
- **Durability:** `/home/hatch` (especially `~/workspace` and `~/memory`)
  survives VM restarts and replacements. `/tmp` and system paths like `/etc`
  do not — the watchdog cron reinstalls the daemon after a replacement.

Keep the daemon light: a heartbeat currently costs ~26 ms to build and
~12 KB on the wire. Don't add heavy collectors without thinking about the
30-second cadence.

## Orchestrator setup (Jack's Mac)

1. Put the shared secret in `token.txt` next to `fleet_receiver.py`
   (same secret every agent uses; **never commit this file**).
2. Run: `python3 orchestrator/fleet_receiver.py`
3. Open `http://<mac-tailscale-ip>:8787`

The dashboard refreshes itself every 5s (every 2s during a live tail) and is
built to sit on a wall screen untouched. Click a machine for its detail page:
Overview (graphs + status timeline), Activity, Processes, Files (a folder
explorer) and Crons. Edits to `dashboard.html` show on browser reload — no
receiver restart. The receiver binds to the Mac's Tailscale IP only.

Status on the dashboard comes only from detected evidence — the app's activity
feed and the daemon's observations (files changed, CPU). The agent's
self-reported `status.json` is shown on the Activity tab but never drives it.

## Agent onboarding

Each agent installs the daemon using the one-shot prompt in
`agents/fleet_setup_prompt.md` — Jack fills in the receiver IP and token
before pasting it to the agent. The prompt covers the Tailscale join (Jack
approves each one), the daemon install, and the watchdog cron.

The daemon reports:

- CPU / memory / disk and the full process list
- file inventory (paths + sizes, up to 500 entries)
- the app's live activity feed as its primary status headline
  (read via the sanctioned local API — see `telemetryd.py`)
- heuristic working-state detection (recent file changes, CPU, browser)
- cron health via a heartbeat file the watch jobs update

Failed pushes spool to disk locally and flush on recovery.

## Live tail

The detail view has a "▶ Live tail" button for on-demand high-frequency
monitoring. It tells the receiver to include a burst command in its reply to
that agent's next heartbeat; the agent then pushes every 2 seconds for
2 minutes, then falls back to 30s automatically. Safety is enforced in the
daemon, not the receiver: it will never push faster than every 2s or burst
longer than 5 minutes, no matter what it's told. The dashboard shows a
pulsing "live" badge and countdown while a tail is active.

## Testing changes

- Daemon logic (CPU sampling, working detection, burst caps):
  `python3 agents/test_telemetryd.py` — hostile inputs (interval 0, huge
  durations, garbage) must not change behavior.
- Daemon v2 (payload `"daemon": 2`) adds per-process CPU, file modified times
  and the list of recently changed files, and stops counting its own log
  writes as "working". Agents on v1 still report; the dashboard flags them
  "Old daemon". To upgrade, the agent replaces `~/workspace/telemetry/telemetryd.py`
  with the new file (the copy in `fleet_setup_prompt.md` is kept identical)
  and restarts it: `systemctl restart telemetryd` (or, where systemd isn't
  available, `pkill -f telemetryd.py` and the watchdog cron restarts it).
- Receiver + dashboard JS: exercise the endpoints and the modal render path
  against a local test instance before pushing; the dashboard JS has no
  build step, so a ReferenceError ships straight to Jack's browser.

## Security notes

- `token.txt` (orchestrator) and agent `~/.token` files are never committed.
- The dashboard has no remote controls. Its only requests back to agents
  ride the heartbeat reply: the live-tail hint, and file viewing — clicking a
  file asks that agent to upload that one file (regular files under
  ~/workspace only, ≤10 MB, never hidden or secret-named files; enforced in
  the daemon). Files are cached in `orchestrator/file_cache/` (gitignored,
  cleared on restart) and served sandboxed so an agent's HTML/SVG can't run
  script in the dashboard.
- Daemon v3 adds a `system` block: OS, CPU, network rate, Tailscale IP and
  the **shared host's** memory (every agent container on a host sees the same
  pool; the dashboard labels it that way).
- Agents push outbound only; the VMs accept no inbound connections.
