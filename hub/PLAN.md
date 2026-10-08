# Fleet hub, milestone 1: the bus

## Goal
A hub runs on Jack's PC (`ai-alienware`) at boot. It delivers every message to the right agent, one at a time per agent: Muse agents get it in their "fleet" side chat via `muse-cli`, and poll agents fetch it with `fleet inbox`. It reads each reply itself and relays it to the asker. It resends once after 10 min and marks an agent unresponsive after 20. It never loops: replies close items and never open them, and requests nested deeper than 5 go to Needs Jack. It renews all 12 Muse logins daily by saving the rotated cookies. It shows agents, a per-agent timeline and Needs Jack on a password-protected page at `https://ai-alienware.tail3cffa4.ts.net`.

## Context
- `hub_plan.md` v4 §4, §5, §7, §9, §12, §13 is the design; this is its first slice.
- PC: Windows 11, SSH `ai1@ai-alienware.tail3cffa4.ts.net`, Python 3.12, `C:\fleet\venv` has `muse-cli` 0.3.2, logins in `C:\fleet\accounts\<id>\.config\muse-cli\cookies.txt` (ACL: ai1 + SYSTEM). `muse-cli` picks the account from `USERPROFILE`/`HOME`.
- Muse facts (tested): side-chat send → reply in ~18 s; genuine reply = assistant message with empty `reply_to_message_id`; no "turn done" event, so poll history; `/api/auth/check` returns rotated `hatch_sess` (30 d) + `hatch_gw` (1 y) that `muse-cli` doesn't save.
- Match: stdlib-only Python like `orchestrator/fleet_receiver.py`; plain-`assert` test scripts like `orchestrator/test_slack_route.py`.
- Files: `hub/hub.py` (SQLite, rules, loop, HTTP API, serves the page), `hub/muse.py` (muse transport + login renewal), `hub/fleet.py` (agent CLI, stdlib, one file), `hub/dashboard.html`, tests `hub/test_hub.py`, `hub/test_fleet.py`, `hub/test_muse.py`.
- Decision: the muse transport shells out to `muse-cli` per call (separate account per `USERPROFILE`), not a long-lived gateway. That's simplest, and the rate is small (≤12 polls / 15 s). Upgrade path: in-process `Gateway` per account.
- Decision: the hub runs as a Task Scheduler task at startup as SYSTEM (no stored password; SYSTEM can read the cookie files). The dashboard uses HTTP Basic auth over Funnel's HTTPS; agents use per-agent bearer tokens stored hashed.
- Decision: a reply = all genuine assistant messages after ours, closed after 60 s of quiet; one item in flight per agent; queue order = requests/questions before plain messages, oldest first.
- Decision: the clock is injectable so retry and timeout rules are tested without waiting.

## Must Not Change
- The Mac's receiver, Slack routing, telemetryd and the agents' current setup (the cutover is milestone 2): `git diff --quiet -- orchestrator agents`.
- `muse-wall/` and the Mac's `~/.muse-cli-test`.
- Only Boboe 2 is messaged (the live test); no other agent is contacted.
- Cookie files never leave `C:\fleet\accounts` and are never printed or logged.

## Steps
- [x] Step 1: Write each Done When example's test with `f01-test-driven-development`: `hub/test_hub.py` (rules, against a fake transport and clock), `hub/test_fleet.py` (CLI against a hub on a temp port), `hub/test_muse.py` (transport against a fake `muse-cli` script, renewal against a stub sign-in check), `hub/check_live.sh` (deployed checks over SSH/HTTPS).
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/PLAN.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: `hub.py` core: schema (agents, items, events, needs_jack), `ask`, `tick` (deliver one item per free agent, collect replies, relay, resend, unresponsive, depth limit), injectable transport and clock.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py`
  - on fail: the assert names the broken rule; fix that rule in `hub.py`, redo Step 2.
- [x] Step 3: HTTP API in `hub.py` (`/api/ask`, `/api/inbox`, `/api/reply`, `/api/status`, `/api/board`; bearer tokens; idempotency keys) and `fleet.py` (ask, inbox, reply, status, `~/.fleet/outbox` replay).
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py`
  - on fail: fix the endpoint or CLI the assert names, redo Step 3.
- [x] Step 4: `muse.py`: `ensure_session` (create/find the "fleet" side chat), `send`, `replies_since`, and `renew` (POST `/api/auth/check`, write rotated cookies atomically, report expiry) for each account.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_muse.py`
  - on fail: compare the fake `muse-cli` output with real `muse-cli history` JSON on Boboe 2; fix the parser, redo Step 4.
- [x] Step 5: `dashboard.html`: Needs Jack at the top, one row per agent (state, current item, queue, last in/out with ages), click → timeline of events; phone width 375 px; served at `/` behind Basic auth.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py dashboard`
  - on fail: fix the page or route the assert names, redo Step 5.
- [x] Step 6: Deploy: copy `hub/` to `C:\fleet\hub`, write `C:\fleet\hub.json` (agents, accounts, dashboard password, token hashes), register the startup task as SYSTEM, `tailscale funnel --bg` to the hub port.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live.sh deploy`
  - on fail: read the task's last result (`schtasks /query /v`) and the hub log on the PC, fix, redo Step 6.
- [x] Step 7: Live: the hub delivers one message to Boboe 2's fleet side chat and records its reply; renewal runs once for all 12.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live.sh live`
  - on fail: `muse-cli history --thread <fleet session>` for Boboe 2 on the PC; fix `muse.py`, redo Step 4.

## Done When
- example: Boboe 7 runs `fleet ask "Boboe 3" "price?"` → Boboe 3's fleet chat gets it once; its reply is relayed to Boboe 7; Boboe 7's reply to that relay is logged and routed nowhere; a request made while handling another at depth 6 goes to Needs Jack instead of being sent.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py`
  - fails with: "No module named 'hub'"
- example: an agent is silent → the item is resent once at 10 min ("resent: no reply seen"), the agent is marked unresponsive at 20 min, and a second item for it waits until the first is answered.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py timing`
  - fails with: "No module named 'hub'"
- example: dot (a poll agent) runs `fleet inbox` and gets its oldest item, then `fleet reply`; a wrong token gets 401; with the hub down, `fleet ask` goes to the outbox and is sent exactly once when the hub is back.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py`
  - fails with: "No module named 'hub'"
- example: renewal against a server returning rotated cookies rewrites that account's cookie file with the new values and records the new expiry; a 401 marks the account `login` and adds a Needs Jack entry.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_muse.py`
  - fails with: "No module named 'hub'"
- example: on the PC, the startup task exists, the Funnel URL answers 401 without the password and 200 with it, and the page lists all 12 agents.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live.sh deploy`
  - fails with: "No such file or directory"
- example: the deployed hub delivers a message to Boboe 2 and records its reply within 5 minutes; all 12 logins renewed.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live.sh live`
  - fails with: "No such file or directory"
- example: on a phone-width screenshot of the dashboard, Needs Jack is the first section, every agent shows a state and how long ago it last replied, and tapping an agent shows its timeline.
  - criterion: PASS if a 375 px wide screenshot shows Needs Jack above the agent list, all 12 agents each with a state and an age, and a second screenshot after tapping Boboe 2 shows its timeline with the live test's message and reply; FAIL otherwise.
- suite: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry && git diff --quiet -- orchestrator agents && python3 orchestrator/test_slack_route.py`
- limit: 4 attempts
