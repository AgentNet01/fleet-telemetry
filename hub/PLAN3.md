# Fleet company: build out company_spec.md

## Goal
Every acceptance criterion in `company_spec.md` (G1–G8) passes: tasks have one holder who closes
them with `fleet task done`, task holders are nudged every 12 h with rotating wording and idle agents
never are, the CEO is told when more than three agents sit idle over 12 h, the org is CEO → PM per
product → designer/engineer/marketer/optimizer with optimizer suggestions, the hub talks only in each
agent's fleet side chat, brain switches keep identity and the soul core and restore per-product
memory, the telemetry daemon changes route by itself when its route keeps failing, and Jack runs all
of it from the dashboard. Deployed to ai-alienware; the loop is turned on only after Jack's go.

## Context
- Spec: `company_spec.md` (G0–G8, with Jack's words). Design history: `hub_plan.md`.
- Code: `hub/hub.py` (Hub class: schema, tick, items, company, switch, vault, HTTP), `hub/fleet.py`
  (agent CLI), `hub/muse.py` (side-chat transport), `hub/dashboard.html`, `agents/telemetryd.py`,
  `agents/setup.py`, `agents/telemetry_hook.sh`.
- Match: plain-`assert` test scripts with modes (`python3 test_company.py council`), `FakeMuse` +
  `Clock` from `test_hub.py`, `start()`/`get()` HTTP helpers in `test_fleet.py`, the Docker VM
  stand-in `test/vm_setup.sh`; stdlib-only Python; one-file dashboard, no build step.
- Live state (read Oct 9): no queued items; 1 product, 0 tasks; roles designer/developer/marketing/
  pm/sales; seat ceo=dot (dot not registered); `loop: false`; 5 active agents reporting telemetry.
- Decision: tasks are leases tracked on the task row, not on chat items. A task item is delivered
  once (like a note); the holder answers with `fleet task note|done`; nothing releases a task on a
  timer (only `fleet task release` by Jack/PM/CEO). Verify is the same: `fleet task verify <id>
  pass|fail <reason>`. `WAKANDA` and the verbatim 10-minute resend are removed.
- Decision: requests/questions/chair items keep their reply flow (chat reply or `fleet reply`) but
  never resend the same text; unanswered after 20 min they fail as today.
- Decision: nudge = a note to the task holder after 12 h without a `fleet` call on that task; four
  phrasings in a fixed list, picked as (last index + 1) mod 4 per agent; each lists all open tasks.
- Decision: CEO note when > 3 active non-parked agents have held no task for > 12 h; re-sent only if
  that set of agents changes or 12 h pass. CEO = `seats.ceo`; if that agent isn't registered or is
  parked, the note goes to Needs Jack instead.
- Decision: roles become exactly designer, engineer, marketer, optimizer (soul text per role in the
  `roles` table, editable from the dashboard); PM is `products.pm`; CEO is `seats.ceo`. Old role
  rows are deleted on deploy (no tasks reference them).
- Decision: brain storage stays on the VM in `~/fleet-brains/<product>/` (home survives VM
  replacement — `~/.fleet` survived Boboe 6's). `SOUL.md` keeps everything outside
  `<!-- fleet-role -->…<!-- /fleet-role -->`; only that block changes. `IDENTITY.md` is never written.
- Decision: delivery opens a fresh fleet side chat per agent (the old one was renamed "Refuse
  malicious code…" by the agents) whose first message is the intro; Jack sends each agent a short
  main-chat heads-up himself before the loop is turned on.
- Decision (Jack, Oct 9): seats are interchangeable. Any seat (CEO, a product's PM) can be held by
  an agent or by a board member. Jack and Darragh are the board (kind `jack`); anything the hub
  would send a board member lands in Needs Jack, labelled with their name. The dashboard Org view
  sets every seat.
- Decision (Jack, Oct 9): hold people constant. A ready task goes to an idle agent already on that
  product in that role; then one on that product in another role (a role-only switch, cheap); a
  cross-product switch only when no agent on the product is free.
- Decision (Jack, Oct 9): dot is proxied through the hub over Slack until Darragh connects it.
  Agent kind `slack`: deliver = DM via `chat.postMessage`, replies = that DM's later messages, using
  the bot token from the vault (`slack-bot-token`, needs chat:write, im:write, im:history,
  users:read). Without the token the hub files one Needs Jack item and keeps dot's items queued.
  The Fleet Reader token was deleted with `orchestrator/` and was read-only, so Jack must add one.
- Decision: telemetryd keeps a list of routes from setup (`~/.fleet/routes.json`); after 5
  consecutive failed pushes it moves to the next route that answers, and records it.
- Decision: setup installs `fleet` as `~/.fleet/fleet` (a copy of `hub/fleet.py`) plus a symlink in
  `~/.local/bin` when that directory is on PATH; the prompt tells agents to call `~/.fleet/fleet`.

## Must Not Change
- Parked agents (1, 2, 3, 4, 7, 10, 11) are never contacted; no message ever goes to a main chat or
  through the Muse Wall.
- Vault, revenue, council and telemetry behaviour (their existing tests stay green).
- `muse-wall/` is not touched.
- Live hub data: `C:\fleet\hub.db` is backed up to `C:\fleet\hub.db.bak-<date>` before the new
  code first runs against it.
- The loop is not switched on, and no live agent is messaged, until Jack says go in chat.

## Steps
- [x] Step 1: Write each Done When example's test with `f01-test-driven-development`: new modes in
  `hub/test_company.py` (lifecycle, poll, org, suggest, switch_between), new `hub/test_nudge.py`
  (cadence, rotate, content, idle_silent, reset, ceo_threshold, ceo_once, ceo_only, ceo_parked), new
  modes in `hub/test_switch.py` (identity, core, roundtrip), `hub/test_muse.py` (side_chat_only,
  intro), `hub/test_fleet.py` (cli, dashboard extended), `agents/test_telemetryd.py` route failover,
  new `hub/test_ui.py` (Playwright: create product → project → blocked task in the UI; agent cards;
  375 px), and `fleet status` + route failover added to `test/vm_setup.sh`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/PLAN3.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Task lifecycle (G1), and placement that holds people constant: `task_note`, `task_done`, `task_verify`, `task_release` in
  `hub.py` + `/api/task/*` + `fleet task note|done|verify|release`; task/verify items delivered once;
  remove `_wakanda_link`, resend-same-text and timer release of tasks; `_idle` includes `poll`.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py lifecycle && python3 test_company.py poll && python3 test_company.py placement && python3 test_company.py && python3 test_fleet.py cli`
  - on fail: the assert names the rule; fix `hub.py`/`fleet.py`, redo Step 2.
- [x] Step 3: Nudges and CEO escalation (G2, G3): `_nudge()` and `_ceo_idle()` called from `tick`,
  state in a `nudges` table (agent, last_at, last_idx) and `ceo_notes` (agents_key, at).
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_nudge.py`
  - on fail: the assert names the rule; fix it in `hub.py`, redo Step 3.
- [x] Step 4: Org (G4): PM per product (`products.pm`), CEO seat, the four roles with souls,
  `suggest`/`decide_suggestion` + `fleet suggest` / `fleet suggestion accept|reject`, task create/
  release limited to Jack, the product's PM and the CEO.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py org && python3 test_company.py suggest`
  - on fail: fix the permission or flow the assert names, redo Step 4.
- [x] Step 5: Delivery (G5): transport only ever targets the fleet side chat; a new session starts
  with the intro text; `MuseTransport.reset(name)` to open the fresh chat; `SlackTransport` and a
  kind router so `slack` agents (dot) are pushed to like `muse` ones; seats held by board members
  go to Needs Jack.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_muse.py side_chat_only && python3 test_muse.py intro && python3 test_muse.py slack && python3 test_muse.py && python3 test_company.py seats`
  - on fail: fix `muse.py`, redo Step 5.
- [x] Step 6: Brain switch (G6): `fleet switch` saves `MEMORY.md` + `memory/` to
  `~/fleet-brains/<current product>/`, restores `~/fleet-brains/<target>/` if present else the
  hub's brief, rewrites only the fleet-role block of `SOUL.md`, never writes `IDENTITY.md`; the hub
  hashes only what it issues (role block + memory when new); switches only between tasks.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_switch.py identity && python3 test_switch.py core && python3 test_switch.py roundtrip && python3 test_switch.py && python3 test_company.py switch_between`
  - on fail: fix `fleet.py` or `hub.py` per the assert, redo Step 6.
- [x] Step 7: Reliability (G7): setup writes `~/.fleet/routes.json` (every route that answered,
  best first) and installs `~/.fleet/fleet`; telemetryd fails over after 5 straight failures.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry && (cd agents && python3 test_telemetryd.py) && FLEET_CLAIM=$(cat ~/.config/fleet-hub/dashboard_password) bash test/vm_setup.sh`
  - on fail: read the FAIL line; fix `telemetryd.py`/`setup.py`, redo Step 7.
- [x] Step 8: Dashboard (G8): product form takes a PM; task form takes role, done-when, blockers
  (pick from the product's tasks); agent cards show product, role, held task, time since activity,
  idle > 12 h badge; timeline shows nudges and CEO notes; Suggestions list with accept/reject; Org
  view (CEO seat, PM per product, role souls editable). Phone width 375.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py dashboard && python3 test_ui.py`
  - on fail: open the screenshot the test saves, fix `dashboard.html`/the endpoint, redo Step 8.
- [x] Step 9: Deploy (loop still off): back up `hub.db`, copy `hub/` to `C:\fleet\hub`, replace the
  old roles with the four new ones, restart `fleet-hub`, confirm it serves and the board loads.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live3.sh deploy`
  - on fail: read `C:\fleet\hub.log` over SSH, fix, redo Step 9.
- [ ] Step 10: Go live, only after Jack says go: Jack sends each active agent the main-chat heads-up;
  then open fresh fleet side chats, set `loop: true`, restart, and confirm each of the five got the
  intro and nothing reached a parked agent or a main chat.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live3.sh live`
  - on fail: set `loop: false` and restart first, then read the hub log and the agents' fleet chats.

## Done When
- example: an agent finishes with `fleet task done <id> <link>` → the task goes to verifying and a different agent gets the verify; a task held 30 h is never released by a timer; `WAKANDA` is gone.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py lifecycle`
  - fails with: "task_done"
- example: the five live agents (kind poll/muse alike) are eligible for tasks.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py poll`
  - fails with: "poll agent never assigned"
- example: a ready task goes to an idle agent already on that product before anyone is switched in from another product.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py placement`
  - fails with: "placement"
- example: Jack puts himself in the CEO seat → CEO notes land in Needs Jack; puts dot back → they go to dot over Slack.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py seats && python3 test_muse.py slack`
  - fails with: "seats"
- example: a task holder silent for 12 h gets one nudge, worded differently from the last, listing its tasks; an agent with no task never gets one.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_nudge.py`
  - fails with: "nudge:"
- example: 4 agents idle > 12 h → one note to the CEO; 3 → none; no repeat for the same idle set.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_nudge.py ceo_threshold`
  - fails with: "CEO:"
- example: an optimizer's `fleet suggest` reaches its PM and the CEO, either can accept/reject, and only Jack, the PM or the CEO can create tasks in a product.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py suggest && python3 test_company.py org`
  - fails with: "suggest"
- example: the hub only ever posts in each agent's fleet side chat, and a new fleet chat opens with the intro.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_muse.py intro`
  - fails with: "intro"
- example: switching A → B → A keeps IDENTITY.md and the soul core byte-identical and brings back A's memory exactly.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_switch.py roundtrip`
  - fails with: "fleet-brains"
- example: the daemon whose route starts failing moves to another working route on its own.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/agents && python3 test_telemetryd.py`
  - fails with: "routes"
- example: in a real browser Jack creates a product with a PM, a project, and a task blocked by another; the board shows it blocked; agent cards show product, role, held task and idle time.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_ui.py`
  - fails with: "suggest"
- example: on a 375 px and a 1440 px screenshot of the seeded dashboard, every section is readable and usable.
  - criterion: PASS if the screenshots saved by `test_ui.py` show Overview (agent cards with product, role, task, idle time), Portfolio with a blocked task and its blocker, Org (CEO, PM per product, roles), Suggestions, Council and Vault, with no clipped or overlapping text at either width; FAIL otherwise.
- suite: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py && python3 test_hub.py timing && python3 test_fleet.py && python3 test_muse.py && python3 test_company.py && python3 test_company.py council && python3 test_switch.py && python3 test_vault.py && python3 test_revenue.py && python3 test_reliability.py && python3 test_telemetry.py && cd ../agents && python3 test_telemetryd.py`
- limit: 6 attempts
