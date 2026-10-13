# Fleet autonomy: real agent status, and work that never runs dry

## Goal
The hub knows what each Muse agent is really doing (mid-turn, last real action, latest line) and
shows it on the dashboard and in the office; a request or task never says "working" while it is
blocked; a product with nothing queued gets planned without anyone typing — its PM first, then an
idle agent acting as planner — and a silent CEO is stood in for by Pericles. Deployed to ai-alienware
and audited on live data.

## Context
- Code: `hub/hub.py` (tick, `_assign_tasks`, `_dry`, `_ceo_idle`, `_chair`, `may_manage`, board),
  `hub/muse.py` (`MuseTransport`, `SlackTransport`), `hub/dashboard.html`, `hub/office.js`
  (built from scratchpad parts `of/*.js`).
- Match: plain-`assert` test modes, `FakeMuse` + `Clock` from `test_hub.py`, `start()`/`fleet()` from
  `test_fleet.py`; stdlib only.
- Audit (read-only subagent + live DB, Oct 13): 6 tasks ever; 11 of 16 workers free 70–95 h; only the
  CEO/PM can create tasks and nothing escalates past a silent CEO; `_dry` is suppressed by any
  non-done task (task #5 'working' kept it quiet 71 h); a 'working' task is never re-checked against
  its blockers; an owned task created blocked never starts; the hub reads only side-chat text.
- Muse probe (Oct 13): `sessions.list` gives each chat's `status` (running/completed/interrupted),
  `updated_at_ms`, `snippet`; `activity.list` gives the agent's own actions (file_updated,
  web_search, task_running, …) with timestamps. ~1.8 s per call per agent.
- Decision (Jack): planning = PM first; if no task appears within 2 h, one idle agent is made acting
  planner for that product (may `task add` there) and its tasks go live; the PM is told and can cancel.
- Decision (Jack): when dot has done nothing for 3 h, Pericles stands in as chair (CEO notes,
  councils, fallbacks) until dot acts again.
- Decision (Jack): every agent can take every product's task; the switch handles context. Unplaced
  agents stay unplaced and are filled by `_switch_to_fill`.
- Decision: Muse activity is read on its own thread every 2 min, outside the tick, so the 15 s
  delivery loop isn't slowed; an agent action seen there counts as acting (`_acted`).
- Decision: a task whose blockers reopen goes back to 'blocked' and frees its holder; a pin brings it
  back to the same agent once ready.

## Must Not Change
- One item in flight per agent; side-chat-only delivery; parked agents never contacted.
- Jack's rules: no automatic messages to main chats, no idle check-ins except the planner item.
- `hub.db` data (deploy backs it up first).

## Steps
- [x] Step 1: Write each Done When example's test with `f01-test-driven-development` in
  `test_autonomy.py` (modes activity, truth, planning, standin, slack200).
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/PLAN4.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Muse activity: `MuseTransport.activity(name)` → busy/at/line; hub `observe()` thread
  stores it on the agent, calls `_acted` for new actions; board exposes it.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py activity`
  - on fail: read the assertion; fix the transport parsing or the hub write, redo Step 2.
- [x] Step 3: Task truth in `_assign_tasks`: re-check 'working' tasks' blockers; start owned tasks
  once unblocked.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py truth`
  - on fail: fix `_assign_tasks`, redo Step 3.
- [x] Step 4: Planning: `_dry` fires when a product has nothing queued and idle workers exist; after
  2 h without a new task an idle agent gets a planner item and a `plan:<product>` grant.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py planning`
  - on fail: fix `_dry`/`may_manage`, redo Step 4.
- [x] Step 5: Stand-in chair: `_chair()` returns the backup when the CEO's last action is 3 h old.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py standin`
  - on fail: fix `_chair`, redo Step 5.
- [x] Step 6: Slack thread past 200 messages is still read.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py slack200`
  - on fail: fix `SlackTransport.replies`, redo Step 6.
- [x] Step 7: Dashboard + office show the activity line and busy state.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py dashboard && node --check office.js`
  - on fail: fix the render code, redo Step 7.
- [x] Step 8: Deploy (backup db + files, restart), set the stand-in seat, then live audit.
  - check: `curl -sf -u "jack:$(cat ~/.config/fleet-hub/dashboard_password)" https://ai-alienware.tail3cffa4.ts.net/api/board | python3 -c "import json,sys; b=json.load(sys.stdin); assert sum(1 for a in b['agents'] if a.get('doing')) >= 10, 'activity missing'"`
  - on fail: read `C:\fleet\hub.log`, fix, redeploy.

## Done When
- example: a Muse agent mid-turn with a fresh file edit → board shows it busy with its latest line, and an 'unresponsive' agent seen acting becomes active.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py activity`
  - fails with: "activity"
- example: a 'working' task whose blocker reopens → 'blocked', holder free; an owned task created blocked → 'working' once its blocker is done.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py truth`
  - fails with: "blocked"
- example: a product with only a 'working' task and idle agents → its PM gets a plan item; 2 h later with no new task an idle agent gets a planner item, adds a task with `fleet task add`, the PM is told, and an unplaced agent is switched onto it.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py planning`
  - fails with: "plan"
- example: dot silent 3 h → the CEO idle note goes to Pericles; dot acts → dot is chair again.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py standin`
  - fails with: "stand"
- example: dot's Slack thread has 250 messages and dot's newest reply is #250 → the hub reads it.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_autonomy.py slack200`
  - fails with: "250"
- example: on the live hub after deploy, every active Muse agent's board row shows a real "doing" line matching its newest Muse activity, and no agent is labelled not answering while Muse shows it acting in the last 30 min.
  - criterion: PASS if a fresh check of `sessions.list`/`activity.list` for 3 sampled agents matches what the board shows for them and the live audit lists no contradiction; FAIL otherwise.
- suite: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py && python3 test_hub.py timing && python3 test_hub.py council_queue && python3 test_company.py && python3 test_company.py stuck && python3 test_company.py switch_between && python3 test_nudge.py && python3 test_fleet.py && python3 test_fleet.py delegate && python3 test_fleet.py cli && python3 test_muse.py && python3 test_reliability.py`
- limit: 4 attempts
