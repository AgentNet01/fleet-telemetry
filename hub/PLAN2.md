# Fleet hub, milestones 2–3: company layer, vault, revenue, council, onboarding

## Goal
On top of milestone 1's bus, the hub runs the fleet as a company, unattended for weeks:
products → projects → tasks with `blocked_by` dependencies that become ready when their
blockers are done and are offered to an idle agent in the task's role; a **brain switch** that
moves an agent's SOUL/IDENTITY/MEMORY to `~/fleet-brains` and loads the target product+role,
verified by hash (proven live on Boboe 2); a **vault** where agents read only their own, their
product's and fleet-wide secrets, every read logged; **revenue** from Stripe and Etsy pulled
hourly and shown as one number; **council** answers (ask all → one chair answer, labelled, with
dissent). The dashboard shows all of it on a phone. Agent onboarding is built and **proven live
on Boboe 2**; the fleet-wide cutover of the other 10 is staged as one command, not run.

## Context
- Built on milestone 1 (committed `b9eadfa`): `hub/hub.py` (SQLite + rules + HTTP), `hub/muse.py`
  (transport + login renewal), `hub/fleet.py` (agent CLI), `hub/dashboard.html`, tests.
- Design: `hub_plan.md` v4 §2–§12, plus its Oct 8 lessons (one fleet side chat per agent;
  muse-cli needs `--wait 8`; muse.ai rotates a session only once it's hours old).
- PC: `ai1@ai-alienware.tail3cffa4.ts.net`, hub at `C:\fleet\hub`, startup task `fleet-hub`,
  accounts in `C:\fleet\accounts\<id>`, Funnel at `https://ai-alienware.tail3cffa4.ts.net`.
  Dashboard password + Jack token in `~/.config/fleet-hub/` on the Mac.
- Match: stdlib-only Python; plain-`assert` test scripts; the existing hub method/endpoint style.
- Decision (safety): **do not mass-message the other 10 agents unattended.** Onboarding is built
  and proven on Boboe 2 only; a `cutover` command dry-runs and prints the plan for all 11 but
  sends nothing without `--go`, which Jack runs when awake. Boboe 2 showed an agent can spiral.
- Decision: **Boboe 4 is never contacted** — it's `parked`; a guard also skips any `parked` agent.
- Decision: **revenue** is built against an injectable fetcher; real Stripe/Etsy keys are added by
  Jack into the vault later, so it shows $0 until then. No key is committed or requested in chat.
- Decision: **vault** stores secrets in the hub DB, which is already readable only by `ai1` +
  SYSTEM (same protection as the cookie files). ponytail: ACL-protected, not encrypted at rest;
  note the upgrade path (DPAPI/age) if the threat model ever needs it.
- Decision: **brain switch** is agent-run: `fleet switch <product> <role>` fetches the role soul
  and product brief from the hub, saves the current brain to `~/fleet-brains/<current>`, loads the
  target (from `~/fleet-brains/<target>` or the hub's template), reindexes, and POSTs the new file
  hashes back; the hub compares to what it issued and flags a mismatch to Needs Jack.
- Decision: **council** reuses items — `ask all` fans out one question item per active agent;
  each reply is a view; when all are in or 15 min pass, the chair (product PM, else CEO seat,
  else Jack) gets the views and returns one answer the hub relays to the asker.

## Must Not Change
- Milestone 1 behaviour: `cd hub && python3 test_hub.py && python3 test_hub.py timing && python3 test_fleet.py && python3 test_muse.py` stay green.
- Boboe 4 is never messaged; no agent but Boboe 2 is messaged live by this work.
- The 10 non-Boboe-2 agents' Slack setup is not retired unattended (the `cutover --go` is Jack's).
- Cookie files and the hub DB never leave the PC and are never printed or logged.
- `muse-wall/` and the Mac's `~/.muse-cli-test`.

## Steps
- [x] Step 1: Write each Done When example's test with `f01-test-driven-development`:
  `hub/test_company.py` (products/projects/tasks, blocked_by→ready, role assignment, done+verify,
  council), `hub/test_switch.py` (brain switch + hash verify + one-chat guard, against the fake
  transport), `hub/test_vault.py` (scopes + refusal + read log), `hub/test_revenue.py` (Stripe+Etsy
  stub, dedup, product map), extend `hub/test_fleet.py` for the new CLI verbs and dashboard
  sections, `hub/check_live2.sh` (onboarding proven on Boboe 2; deploy checks).
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/PLAN2.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Company core in `hub.py`: schema (products, projects, tasks, councils, council_views;
  agents gain current_product/current_role) and methods — create product/project/task, `ready`
  (a task whose blockers are all done), assign a ready task to an idle agent whose role matches,
  task reply → progress note or `WAKANDA <link>` → evidence check → verify item to a different
  agent; council fan-out and chair resolution. Wire into `tick`.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py`
  - on fail: the assert names the broken rule; fix it in `hub.py`, redo Step 2.
- [x] Step 3: Company CLI + API: `fleet task claim|done|checkpoint`, `fleet ask all`, and
  orchestrator verbs (`fleet product|project|task new`, `assign`, `park`, `wake`); `/api/*` for each,
  `fleet status` shows my product, role and current task.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py company`
  - on fail: fix the endpoint or CLI the assert names, redo Step 3.
- [x] Step 4: Brain switch: `fleet switch <product> <role>` in `fleet.py`; `/api/brain` (role soul +
  product brief) and `/api/switched` (receives hashes) in `hub.py`; `tick` issues a switch when a
  ready task needs a product/role the agent isn't in; hash mismatch or a second live side chat →
  Needs Jack.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_switch.py`
  - on fail: the assert names the broken part; fix it, redo Step 4.
- [x] Step 5: Vault: `secrets` + `secret_reads` tables; `get`/`put` scoped to agent|product:<p>|fleet;
  `fleet secret get|put`; `/api/secret`; a read outside scope is refused and a read in scope is
  logged.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_vault.py`
  - on fail: fix the scope check or logging the assert names, redo Step 5.
- [x] Step 6: Revenue: `sales` table; `pull_revenue(fetch)` with an injectable fetcher; dedup on
  `(source, external_id)`; map each sale to a product; the hourly loop calls it; `board` exposes the
  total and per-product.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_revenue.py`
  - on fail: fix the dedup or mapping the assert names, redo Step 6.
- [x] Step 7: Dashboard: revenue big number (total + per product), portfolio board
  (products → projects → tasks with their blockers and state), per-agent brain (product + role) on
  the agent row and timeline, vault read log tab, council views + answer. Phone width 375.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py dashboard`
  - on fail: fix the page or route the assert names, redo Step 7.
- [x] Step 8: Deploy to the PC (copy `hub/`, restart `fleet-hub`) and confirm it serves.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live2.sh deploy`
  - on fail: read `C:\fleet\hub.log` over SSH, fix, redo Step 8.
- [ ] Step 9: Onboarding proven on Boboe 2: the hub installs `fleet` + a token on Boboe 2 and
  retires its Slack listener; Boboe 2 then runs `fleet status` successfully against the hub. Build
  the `cutover` command that would do this for all 11 but only prints the plan without `--go`.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live2.sh onboard`
  - on fail: read Boboe 2's fleet chat on the PC, fix the onboarding message/script, redo Step 9.
- [ ] Step 10: Retire the Mac's Slack coordination code (git rm `orchestrator/slack_reader.py`,
  `orchestrator/test_slack_route.py`, `agents/listen.py`, `agents/test_listen.py`,
  `agents/slack_cron.txt`); the receiver keeps only telemetry.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry && test ! -f orchestrator/slack_reader.py && test ! -f agents/listen.py && python3 -c "import ast; ast.parse(open('orchestrator/fleet_receiver.py').read())"`
  - on fail: restore what the receiver still imports, redo Step 10.

## Done When
- example: a task blocked by an unfinished task is not assigned; when the blocker is marked done with evidence, the task becomes ready and is offered to an idle agent whose role matches; done requires evidence that checks out, and a different agent gets the verify.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py`
  - fails with: "evidence_ok"
- example: ask-all makes each active agent's reply a view; when all are in (or 15 min pass) the chair returns one answer labelled consensus / majority (n–m) / chair's call, names non-responders, and every view stays inspectable; the answer is relayed to the asker.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_company.py council`
  - fails with: "evidence_ok"
- example: switching an agent to a product+role moves its SOUL/IDENTITY/MEMORY/memory into ~/fleet-brains (nothing deleted), loads the target, the hub verifies by hash, and a hash mismatch raises Needs Jack; the agent keeps exactly one fleet side chat.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_switch.py`
  - fails with: "set_role"
- example: an agent reads a secret in its product scope and the read is logged; a secret outside its scope is refused; the dashboard shows the read log.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_vault.py`
  - fails with: "place"
- example: one Stripe and one Etsy sale each count once toward the total; a repeated external_id doesn't double-count; each sale maps to its product; the board shows the total and per-product.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_revenue.py`
  - fails with: "add_product"
- example: the full fleet CLI (task claim/done/checkpoint, ask all, secret get/put, switch) works against a live hub, a bad token is refused, and an offline write replays exactly once.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_fleet.py company`
  - fails with: "add_product"
- example: the hub onboards Boboe 2 — installs `fleet` + token, retires its Slack listener — and Boboe 2 runs `fleet status` back to the hub; the `cutover` command without `--go` prints the 11-agent plan and sends nothing.
  - check: `bash /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/check_live2.sh onboard`
  - fails with: "not deployed"
- example: on a 375 px screenshot, the dashboard shows the revenue number, a portfolio board with a task and its blocker, a per-agent product+role, a vault read-log entry, and a council question with its views and answer.
  - criterion: PASS if a phone-width screenshot tour shows all five — revenue big number, portfolio board with a task showing its blocker, an agent's product+role, a vault read-log row, and a council question with views and a labelled answer; FAIL if any is missing or unreadable.
- suite: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_hub.py && python3 test_hub.py timing && python3 test_fleet.py && python3 test_muse.py && python3 test_company.py && python3 test_switch.py && python3 test_vault.py && python3 test_revenue.py`
- limit: 6 attempts
