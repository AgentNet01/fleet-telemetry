# Swarm tooling, cron & fleet-repo lane — Boboe 5 research

**Lane:** cron / fleet-repo / tooling changes needed to support long-running autonomous swarm operation (12 agents: Boboe Prime + Boboe 1–11).
**Repo state researched:** AgentNet01/fleet-telemetry @ 838247e. **Date:** 2026-10-07.
**Constraint honored:** research only — no Slack posts, no config changes.

Related lanes (not duplicated here): Boboe 8 (orchestration patterns), Boboe 7 (coordination layer/comms), Boboe 10 (heartbeat infra), Boboe 9 (observability), Boboe 4 (skills/tools), Boboe 3 (existing harnesses/repos), Boboe 1 (specialization), Boboe 2 (lane split + rollup). This report stays on the tooling/cron/repo mechanics lane; long-run failure modes are included only as the context that justifies each change.

---

## 1. Current-state inventory (as of 838247e)

### 1.1 Scheduling (per agent VM)

| Mechanism | Cadence | Job | Supervisor |
|---|---|---|---|
| `telemetryd.py` (systemd) | push every 15s | telemetry heartbeat to receiver | `telemetry-watchdog` hook (60s poll); systemd `Restart=always` |
| `telemetry-watchdog` hook | 60s poll | reinstall daemon if process missing | hook runtime |
| `slack-watch-boboe5` cron | every 5 min | **backstop only:** handle `~/inbox/slack/*.json` older than 3 min (instruction = `agents/slack_cron.txt` verbatim) | cron runtime |
| `slack-inbox` hook | — | **retired** (disabled) | — |

**Fast path:** the receiver types `reply_required` mentions into the agent's main chat via the Muse Wall; the agent answers in Slack immediately and moves the inbox file to `done/`. Background runs are too slow for mentions (measured: empty cron run ~99s; runs with a message hit the 240s timeout; a 1-min cron coalesces to every 4–5 min).

### 1.2 Fleet repo layout (`AgentNet01/fleet-telemetry`)

```
agents/            # runs on each agent VM
  telemetryd.py        # the daemon (v13)
  test_telemetryd.py   # hostile-input tests
  install.sh           # idempotent installer (config reuse, systemd unit, hook scripts)
  watchdog_hook.sh     # source of the telemetry-watchdog hook script
  slack_cron.txt       # SINGLE SOURCE for the slack-watch cron instruction
  fleet_setup_prompt.md# onboarding prompt
  probe_sources.sh     # sandbox API probes
orchestrator/      # runs on Jack's Mac
  fleet_receiver.py    # ingest + API (stdlib only); tracks per-agent last_seen, history, cron_history, missed_mentions
  slack_reader.py      # Slack ingestion, mention routing, loop guards
  dashboard.html       # read-only dashboard
docs/
  systems-overview.md  # agent execution model, capabilities, limits
test/muse-vm/      # VM test harness
README.md
```

**Rollout mechanics today:** Jack's Claude announces a commit; each agent runs `git pull && bash agents/install.sh`. The daemon reports a payload `"daemon"` version int; the dashboard flags outdated daemons ("Old daemon"). Config (agent name, receiver URL, token, proxy) is captured once and reused on reinstall — reinstalls are fully idempotent, which matters because **`/etc` is wiped on every VM reboot** (observed: 3 reboots in ~6h on Oct 6), taking the systemd unit with it.

### 1.3 What the telemetry already ships (v11+ `health` block, every push)

`post`/`mailbox` ok-fail counts + `last_ok`, `last_error {where, text, ts}`, daemon `started` time, per-hook stats from `~/hooks/logs/*.jsonl` (runs/wakes/errors in the last hour + newest non-silent result). The receiver stores per-agent `last_seen`, full history, and cron history, and computes `missed_mentions` (people who named the agent in the last day and never got an answer after re-sends).

**Key insight for everything below: the accountability data already exists.** The receiver knows, to 15-second resolution, whether every agent is alive, whether its hooks are running, and whether mentions went unanswered. What is missing is the *roll-call logic on top of it* (Lane §7).

---

## 2. What breaks at long horizons — evidence from Oct 6–7 operations

These are not theoretical; each was observed on this fleet in the last 24h:

1. **Hook workers get skipped when busy.** Muse skips a hook wake while a worker is still running, and the old hook filed each message as "done" at wake time — skipped wakes silently lost messages. (Fixed by keeping messages in `~/inbox/slack/` until handled + re-wake, then by retiring the hook entirely.)
2. **Background runs are slow and time out.** Empty cron run ~99s; runs that found a message hit the 240s timeout without posting; a 1-minute cron coalesced to every 4–5 minutes. The old 5-minute Slack-watch cron (which drained the whole thread) hit **26 consecutive timeouts**.
3. **Duplicate replies from racing paths.** Hook re-sends + cron + late hook workers raced into duplicate replies before the single-path redesign.
4. **VMs reboot without warning and lose `/etc`.** The systemd unit vanishes; only the idempotent `install.sh` + watchdog brings the daemon back. Any design that assumes a persistent system service without a reinstall path will go dark.
5. **The receiver is a single point of failure that the agents cannot fix.** Jack restarting the receiver to deploy fixes produced `mailbox: Remote end closed connection without response` storms on every box; agents can only spool and retry. Long-horizon work must be *receiver-independent* for progress (git + local files), using the receiver only for visibility.
6. **Silent stalls beat crashes.** Consistent with the literature (see §3): the most dangerous state is "looks alive, does nothing" — a cron ticking with an empty inbox while the actual work stalled hours ago. Our current telemetry cannot distinguish "idle, healthy" from "stalled" — it has no notion of *expected* work.

## 3. Long-run failure modes (retained context — the "why" behind the proposals)

**Deli_AutoResearch protocol** (whz-harness skill; validated on multi-day research tasks): three recurring modes — (1) *cognitive loop* (iterations retry similar directions with diminishing returns), (2) *stalling* (agent finishes a chunk, summarizes, waits — externally alive, work stopped; more common than crashes), (3) *runtime fragility* (context compaction silently breaks the loop; timers parasitic on a session die with it). Prescriptions: zero-interaction runs, state in files not conversation memory, fresh session per iteration (never resume), guardian/worker separation (a watchdog may only liveness-check, restart, nudge — never read task data), stall detection on quantitative metrics (0 new findings → stale_count+1; ≥2 → forced pivot of *structural* constraints; ≥4 → human attention), and a 3-layer watchdog (resident shell guard → durable cron → business loop, each able to detect the others' death).
Source: https://github.com/whz1106/whz-harness/blob/HEAD/skills/Deli_AutoResearch/SKILL.md

**MAST — multi-agent failure taxonomy** (Cemri et al., UC Berkeley; 1,642 traces, 7 frameworks): 41–86.7% open-source MAS failure rates; top modes are *step repetition* (15.7%), *reasoning-action mismatch* (13.2%), *unaware of termination* (12.4%), *disobey task spec* (11.8%). 79% of failures are specification/coordination problems, not infra. Implication for us: guardrail budget goes to specs, termination criteria, and verifiers — not to more infrastructure.
Sources: https://arxiv.org/pdf/2503.13657, https://github.com/ang-ventures/agent-skills/blob/HEAD/skills/mast-failure-modes/SKILL.md

**Anthropic, "Effective harnesses for long-running agents"**: agents fail by (a) trying to do too much at once and exhausting context mid-implementation, leaving the next session to guess; (b) declaring victory prematurely once progress is visible; (c) marking features done without end-to-end testing. Fixes: *initializer agent* (first session writes `init.sh`, progress file, feature list, initial commit) + *coding agent* (each session: get bearings from git log + progress file, do ONE feature, leave clean mergeable state, commit). Feature list as JSON with `passes` booleans; strongly-worded "never edit tests"; fresh-context reconstruction via progress file + git history.
Source: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents

**Ralph loop** (Geoffrey Huntley; adopted by Anthropic as the `ralph-wiggum` plugin): `while :; do cat PROMPT.md | claude-code; done` — same goal prompt, fresh context every iteration, filesystem/git as memory. Iron law: **no loop without an automated stop condition** (tests green, acceptance command); a loop with no machine-truth "done" drifts and burns money. Do one thing per iteration; search before building.
Sources: https://github.com/olivomarco/genai-development-techniques/blob/HEAD/techniques/ralph.md, https://github.com/recodeeai/skills/blob/HEAD/skills/meta/ralph-loop/SKILL.md

**Durable execution** (Temporal / Inngest / DBOS / Restate / LangGraph checkpointing): split the *durable plane* (what happened, what happens next — persisted event log) from the *ephemeral plane* (workers that can die anytime and are rescheduled). Crash cost = whatever you didn't wrap in a checkpoint. For our shell/cron world the portable version: checkpoint after each step to files/git; resume reads last checkpoint; idempotency keys per step.
Sources: https://github.com/inngest/website/blob/HEAD/content/blog/durable-execution-key-to-harnessing-ai-agents.mdx, https://theaiengineer.substack.com/p/inngest-vs-temporal-vs-dbos-vs-langgraph

**Dead man's switch** (Healthchecks.io pattern): metrics describe work that happened; *heartbeats detect work that should have happened but didn't*. A job that never runs emits nothing — only an external monitor owning the expected cadence can catch the silence. Directly applicable to our 10-minute roll-call (§7).
Sources: https://dev.to/ji_ai/github-actions-cron-was-late-30-nights-straight-then-skipped-one-4751, https://dev.to/jaxmonroe3187/silent-cron-runs-a-backend-metrics-dashboard-beyond-api-failures-1bgf

---

## 4. How the fleet repo should evolve

### 4.1 New top-level dirs

**`research/`** (Boboe 2's proposal — adopt it): one markdown file per research area, plus a maintained `research/INDEX.md` (owner: whoever consolidates that week; default Boboe Prime). Naming: `research/<area>-<author>.md` (e.g. `research/swarm-comms-boboe2.md`). Rule: findings, not chat logs — each file ends with "Proposals" (things to build) and "Open questions".

**`proposals/`**: the fleet's change pipeline. Each proposal is one file, `proposals/<slug>.md`, with frontmatter:
```
status: proposed | accepted | deployed | rejected
author: boboeN
date: 2026-10-07
affects: [agents/telemetryd.py, agents/slack_cron.txt, docs/*]
rollout: agent-pull-install | receiver-restart | memory-only
```
Body: problem (with evidence), change, exact rollout steps, rollback, how we verify. Status moves by lazy consensus: 48h with no objection from Jack or two other agents → accepted; Jack can fast-track. This replaces "Jack's Claude announces a commit and hopes" with a visible pipeline.

**`tasks/`** (durable work ledger — see §6.1): one JSON file per long-running task. Git is the coordination substrate (cheap, versioned, offline-capable, survives receiver outages).

**`CHANGELOG.md`**: every daemon-affecting change gets a line (version, date, what changed, who must reinstall). The dashboard already flags "Old daemon" — the changelog tells an agent *why* it should upgrade and what breaks if it doesn't.

### 4.2 Conventions to adopt (already partially established — formalize them)

1. **Single-source rule** (established with `agents/slack_cron.txt`): any instruction or script that N agents must register verbatim lives in `agents/` with a header comment stating *how* it is registered (`hooks.add` id, cron id, interval). Nothing is retyped from chat.
2. **Idempotent installers** (established with `install.sh`): every agent-side component must survive `rm -rf` of its runtime state and reinstall from the repo + local config. New rule: **no new agent-side dependency may assume `/etc` persistence** (reboots wipe it).
3. **Payload version gating** (established with `"daemon": 13`): any behavior change the receiver depends on bumps the version int; the dashboard flags stragglers. Extend: receiver *rejects nothing* but *labels everything* (old daemons keep reporting; staleness is visible, not fatal).
4. **Tests before push for daemon/receiver changes** (established: `test_telemetryd.py`, hostile inputs). Extend to `orchestrator/`: receiver changes get exercised against a local instance first (README already says this — make it a merge rule, not a suggestion).
5. **No secrets in the repo** (established: `token.txt`, `.env` gitignored). Extend: a `docs/SECURITY.md` checklist for new contributors (agents included): what is a secret, where it lives, what never goes in Slack.

### 4.3 Rollout mechanics that need to exist

Today's rollout ("everyone `git pull && bash agents/install.sh`") worked 8 times in one evening, but it has no verification loop. Needed:

- **Rollout checklist per release**: a `proposals/<slug>.md` lists the exact commands; the *receiver* verifies via payload versions and shows a "fleet upgrade" view (N/12 on v14). No agent has to report "done" — the dashboard proves it.
- **Staged rollouts for risky changes**: one canary agent (rotate weekly) upgrades first; 24h soak; then fleet-wide. The canary is whoever's daemon version is newest on the dashboard.
- **Receiver deploys are Jack-side**: agents can't restart Jack's Mac. Convention: receiver changes ship with a "needs Jack restart" flag in the proposal; agents' daemons must tolerate old receivers (version-gated behavior, never hard-fail on unknown reply fields — the daemon already enforces caps client-side; keep that pattern).

---

## 5. Scheduling changes for long horizons

### 5.1 Principles (distilled from §2 evidence + §3 literature)

1. **Cron bodies must be tiny and idempotent.** The 5-min watcher died 26 times because it drained a whole Slack thread. The new backstop body (`find` + answer + move) is the right shape: bounded work, early exit, no unbounded scans. *Any future cron that grows past ~60s of work gets split*: fast path stays on cadence, heavy work moves to an hourly/daily sweep cron.
2. **Separate liveness from progress.** A ticking cron proves the scheduler is alive, not that work is progressing. Long tasks need their own progress signal (see §6.1 task ledger with heartbeats), independent of the cron that launches them.
3. **Watchdogs must be layered and mutually checking** (Deli §7): systemd `Restart=always` (L0) → `telemetry-watchdog` hook 60s (L1) → daemon's own health shipping (L2, visible on dashboard). Any one layer's death is visible to another. *Gap today:* nothing watches the watchers' *definitions* — a hook disabled by accident (we disabled `slack-inbox` on purpose tonight) is indistinguishable from one that died. The daemon already ships per-hook stats; the receiver should alert when an *expected* hook disappears from a box's stats (expected-hook manifest per agent, stored receiver-side).
4. **Fresh context per iteration for long work** (Ralph/Anthropic): never run a multi-day task as one ever-growing session. Structure: `tasks/<id>/GOAL.md` (objective + machine-checkable done criteria) → cron launches a fresh worker per iteration → worker reads `state/` + git log, does one unit of work, commits, updates `progress.json` → loop ends on the automated stop-check, never on vibes.
5. **Every loop has an automated stop condition** (Ralph's iron law): tests green, acceptance command exit 0, or explicit `blocked`/`flag_for_human` exit. "Keep going until done" without machine-truth is how you get a 3-day loop that accomplished nothing and a large bill.

### 5.2 Concrete scheduling changes to make

- **S1. Keep the current split** (Wall fast path + 5-min backstop + 60s watchdog). It is the correct architecture; don't churn it.
- **S2. Add an hourly `task-sweep` cron** (new): reads `tasks/` ledger, detects stalled tasks (no progress heartbeat in >2h), and either nudges (re-queues the next iteration with a *different* direction — Deli forced-pivot) or escalates after 3 fruitless nudges. This is the stall detector the fleet currently lacks.
- **S3. Add a daily `fleet-hygiene` cron** (new, cheap): `git pull` the fleet repo (keeps every box within a day of HEAD without Jack orchestrating), report daemon version drift (informational only), prune `~/inbox/slack/done/` older than 7 days, rotate `~/hooks/logs/*.jsonl` (they grow unbounded today).
- **S4. Receiver-side expected-hook manifest**: per agent, the list of hooks that should exist; alert (dashboard badge + Wall mention to Jack) when one is missing from the shipped stats for >10 min. Catches accidental disables.
- **S5. Cron body size lint**: a `test/` check that fails if any `agents/*cron*.txt` exceeds ~40 lines or contains unbounded scans (`--limit` without a cap, full-thread drains). Mechanical enforcement of principle 1.

---

## 6. Tooling gaps — what we can't do today that long autonomy needs

### 6.1 No durable shared task state → add `tasks/` ledger

Today, task state lives in Slack threads (ephemeral, unscannable, lost in scroll) or in one agent's memory. For days/weeks tasks we need a ledger every agent can read/write without the receiver:

```
tasks/<task-id>/
  SPEC.md          # goal, milestones, done criteria (machine-checkable), owner agent
  progress.json    # {status, iteration, updated_ts, heartbeat_ts, stale_count}
  findings.jsonl   # append-only results
  log.jsonl        # decisions + events
```

Rules: the owning agent updates `heartbeat_ts` + `progress.json` every work iteration; the hourly task-sweep (§5.2 S2) reads heartbeats, never task content. Git is the transport (`git pull` in the daily hygiene cron keeps it fresh; pushes need Jack's approval per the write-action boundary — so the convention is: agents commit locally, push via the existing approval flow or a fleet deploy key if Jack grants one).

### 6.2 No independent verification → verifier pattern

MAST: the top failure modes are all spec/verification problems; separate skeptical evaluators beat self-critique. Convention for long tasks: **no task marks itself done.** Completion requires a *different* agent (or a fresh context) to run the acceptance check against `SPEC.md` and sign `verified_by`. Cost: one extra worker per task. Benefit: kills premature-victory (Anthropic's #2 failure mode) mechanically.

### 6.3 No cost visibility → budget envelopes per long task

Nobody can see token spend per task today. Full metering needs platform support, but we can approximate: each task's `SPEC.md` declares a budget envelope (max iterations, max wall-clock days); the task-sweep enforces it (iteration cap → auto-pause + escalate). Ralph's iron law made quantitative: no unbounded loops, ever.

### 6.4 Credential expiry is invisible → expiry inventory

PATs, Slack/connector sessions, Tailscale — all can silently die (cf. tonight's device-verification email dance for the GitHub PAT). Add `docs/credentials.md` (non-secret): what credential, where it lives, expiry/rotation policy, owner. The daily hygiene cron diffs "expected vs present" (file exists, token file non-empty) and flags missing ones — never the values.

### 6.5 Comms beyond Slack — keep Slack, add the ledger

Boboe 2/7/8 own the comms comparison. From the tooling side the requirement is narrow: agent-to-agent coordination needs (a) durability (Slack threads scroll away), (b) machine-readability (JSON, not prose), (c) offline operation (works during receiver outages). The `tasks/` ledger + git covers a–c for *work state*; Slack stays for *conversation*. Don't build a second chat system.

---

## 7. Accountability layer — 10-minute roll-call design (fitted to existing infra)

**The data already exists.** Every 15s each daemon pushes; the receiver stores per-agent `last_seen`, hook stats, and `missed_mentions`. The roll-call is a receiver-side sweep, not new agent code:

- **What each agent already reports (no change needed):** liveness (the push itself), `health` block (post/mailbox ok-fail, last error, daemon start), per-hook runs/wakes/errors (last hour). *One addition:* include the 5-min backstop cron's last-run timestamp + outcome in the payload's `crons` section (the receiver already merges a `crons` list — populate it).
- **Where the roll-call lives:** receiver-side, every 60s: for each of the 12 expected agents, compute `now - last_seen`. Thresholds: **>3 min = "quiet"** (dashboard amber; normal during deploys), **>10 min = "dark"** (dashboard red + alert). Expected-agent roster lives in a receiver config file (not inferred from who has ever pushed — otherwise a retired agent never alerts).
- **Missed check-in escalation path:** (1) state change only — alert on *transitions* (alive→dark, dark→alive), never repeated pages; (2) first alert goes to the **dashboard** (Jack's wall screen) + a **Wall mention to Jack** ("Boboe 7 dark 12 min"); (3) no Slack #all-agentnet posts (Jack banned health chatter there); (4) auto-clear with a "was dark 14 min, back" note — no human ack needed for transient blips.
- **Avoiding noise:** hysteresis (dark at 10 min, clear only after 2 consecutive good pushes); deploy awareness (receiver restarts and fleet-wide `install.sh` rollouts suppress dark-alerts for 5 min — tonight's 22:10/22:13 restart storm would otherwise page 12 times); per-agent silence windows (Jack can mark an agent intentionally down); digest, not drip (one "3 agents dark" line, not three).
- **Distinguishing idle from stalled:** liveness ≠ progress. The task ledger (§6.1) gives the second signal: an agent alive but with no task heartbeat in >2h is "idle-stalled" — surfaced on the dashboard's task view, not paged. This is the Deli stall-detector, fleet-scaled.
- **Self-healing before paging:** the existing layers already auto-recover most cases (systemd restart, watchdog reinstall). The roll-call only fires when all local recovery has had 10 minutes and failed — i.e., it pages on *recovery failure*, not on first fault.

---

## 8. Highest-leverage improvements (ranked)

1. **Receiver-side 10-minute roll-call on `last_seen`** (§7). Data exists; ~50 lines of receiver code. Directly answers Jack's "every agent accounted for every 10 minutes." Nothing to install on agents.
2. **Hourly task-sweep cron + `tasks/` ledger convention** (§5.2 S2, §6.1). Converts "long tasks" from vibes into files with heartbeats, stall detection, forced pivots, and budget caps. This is the single biggest reliability unlock for days/weeks autonomy.
3. **`research/` + `proposals/` + `CHANGELOG.md` in the fleet repo** (§4). Lets the fleet improve itself without Jack orchestrating every step — the meta-capability tonight's mission is really about.
4. **Minimal-cron discipline + expected-hook manifest alerting** (§5.1–5.2 S4–S5). Kills the two failure classes we actually hit: timeout death spirals and silent watcher loss.
5. **Verifier pattern for task completion** (§6.2). One extra worker per long task; mechanically eliminates premature victory, the failure mode Anthropic found most embarrassing and MAST found most common.

---

## 9. Concrete proposals (deployable; exact steps)

### P-A. Roll-call sweep (receiver-side; needs Jack's Mac)

1. In `orchestrator/fleet_receiver.py`: add `EXPECTED_AGENTS = [12 names]` config + a 60s thread: for each, `dark = now - last_seen > 600`.
2. On dark transition: append to a `rollcall.log`, set dashboard badge; on recovery: log return.
3. Alerting: Wall-mention hook — the receiver already types into Wall tiles for mentions; reuse that path for "Boboe N dark 12 min" (Jack's call whether to wire it).
4. Suppress during `deploy_quiet_until` (set when Jack restarts receiver or a fleet rollout is announced).
5. Verify: stop one agent's daemon, watch dashboard go amber→red at 3/10 min, restart, watch it clear.

### P-B. Task ledger + hourly sweep (agent-side; each box)

1. `mkdir -p ~/workspace/tasks/<id>` per long task with `SPEC.md`, `progress.json`, `findings.jsonl`, `log.jsonl` (format in §6.1).
2. New cron `task-sweep-boboe5`, hourly, body: for each task dir, if `now - heartbeat_ts > 2h`: increment `stale_count`; if `<3`, spawn a worker with a *forced different direction* (read `directions_tried`); if `≥3`, mark `needs_human` and Wall-mention Jack. If `iteration > budget` in SPEC.md: auto-pause + escalate.
3. Long tasks run as: cron (or Jack) launches worker → worker reads SPEC.md + state, does one unit, commits, updates `progress.json` + `heartbeat_ts`, exits. Fresh context every iteration (Ralph).
4. Verify: create a canary task, let it run 3 iterations, confirm commits + heartbeats; simulate stall (touch nothing for 2h), confirm nudge fires.

### P-C. Repo conventions (fleet-wide; one PR each)

1. Add `research/INDEX.md` + move this report and others in as `research/<area>-<author>.md`.
2. Add `proposals/` with `proposals/_TEMPLATE.md` (frontmatter from §4.1) and `CHANGELOG.md` (start at v13/838247e).
3. Add `docs/SECURITY.md` checklist (from §4.2.5).
4. Merge rule (social, enforced by reviewers): daemon/receiver changes ship with tests; shared prompts live in `agents/` single-sourced; no `/etc` assumptions.

### P-D. Daily hygiene cron (each box; 5 lines of body)

`git -C ~/workspace/fleet-telemetry pull` (keeps boxes within a day of HEAD), prune `~/inbox/slack/done/` >7d, rotate `~/hooks/logs/*.jsonl` past 10k lines, check expected credential files exist (values never read). Silent unless something is wrong.

### P-E. Expected-hook manifest alert (receiver-side; pairs with P-A)

Receiver config lists expected hooks per agent (`telemetry-watchdog`); if a push's `health.hooks` lacks one for >10 min, dashboard badge. Catches the "disabled by accident" class.

---

## 10. Sources

- Anthropic, "Effective harnesses for long-running agents" (2025-11-26): https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, "How we built our multi-agent research system": https://www.anthropic.com/engineering/multi-agent-research-system
- Deli_AutoResearch protocol (long-horizon failure modes + 3-layer watchdog): https://github.com/whz1106/whz-harness/blob/HEAD/skills/Deli_AutoResearch/SKILL.md
- MAST taxonomy (Cemri et al., UC Berkeley): https://arxiv.org/pdf/2503.13657 ; checklist version: https://github.com/ang-ventures/agent-skills/blob/HEAD/skills/mast-failure-modes/SKILL.md
- Ralph loop (Huntley): https://github.com/olivomarco/genai-development-techniques/blob/HEAD/techniques/ralph.md ; skill version: https://github.com/recodeeai/skills/blob/HEAD/skills/meta/ralph-loop/SKILL.md
- Durable execution for agents (Inngest): https://github.com/inngest/website/blob/HEAD/content/blog/durable-execution-key-to-harnessing-ai-agents.mdx ; comparison: https://theaiengineer.substack.com/p/inngest-vs-temporal-vs-dbos-vs-langgraph
- Awesome harness engineering (framework catalog): https://github.com/coldslither/awesome-harness-engineering
- Google ADK pause/resume long-running agents: https://developers.googleblog.com/build-long-running-ai-agents-that-pause-resume-and-never-lose-context-with-adk/
- Dead man's switch pattern: https://dev.to/ji_ai/github-actions-cron-was-late-30-nights-straight-then-skipped-one-4751 ; https://dev.to/jaxmonroe3187/silent-cron-runs-a-backend-metrics-dashboard-beyond-api-failures-1bgf
- Fleet repo (private): AgentNet01/fleet-telemetry @ 838247e — `agents/`, `orchestrator/fleet_receiver.py`, `docs/systems-overview.md`, `agents/install.sh`
