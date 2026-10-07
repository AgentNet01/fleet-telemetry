# Lane 2: Long-running Supervision + 10-min Accountability — Findings (Boboe Prime)

Date: 2026-10-07. Owner: Boboe Prime. Syncing: Boboes 7, 9, 10.

## 1. The problem

Jack wants agents running days/weeks-long tasks with zero oversight, while guaranteeing no agent "falls away" — every agent accounted for roughly every 10 minutes. Two distinct needs:

- **Liveness**: is the agent's process alive and its loop turning?
- **Progress**: is it actually advancing its task, or stuck/spinning/drifted?

Today's fleet has liveness (telemetryd pushes every 15s) but no real progress accountability. The 5-min cron "safety net" timed out on most runs; hook workers often never ran. Nobody would notice a stuck agent for hours.

## 2. Proposed design: three layers

**Layer 1 — Automatic liveness (no agent effort).**
- telemetryd already pushes every 15s with daemon start time (v11+). The receiver/dashboard flags any agent with no push in >2 min as "dark." This is free and already works. No changes needed.

**Layer 2 — Progress heartbeat (~10 min, cheap).**
- Each agent's cron (or daemon) appends a one-line status to its push or a local status file every 10 min: `current task | progress | blockers | next milestone`.
- The 10-min cadence matches Jack's ask. It must be generatable in <30s — a single-line template, not a report.
- The coordinator (or Jack's dashboard) reads these, not Slack threads.

**Layer 3 — Supervision (watching the watchers).**
- One supervisor role (rotating or fixed — recommend Boboe Prime as fixed supervisor, since coordination is already centralized) aggregates heartbeats.
- Rules:
  - Missed 1 heartbeat (10 min): note, no action.
  - Missed 2 (20 min): nudge the agent directly (Slack @mention).
  - Missed 3 (30 min) or blocker flagged twice: escalate to Jack.
  - Progress regression (agent reports less progress than 30 min ago): flag for review.
- Supervision itself must be observable: the supervisor's own heartbeat includes "agents checked: 12/12, flags: 0."

## 3. Anti-patterns from today (do not repeat)

1. **Status in Slack threads.** 331 messages in one thread, mostly noise. Progress goes to the dashboard/status file, never to chat, unless it's a blocker needing a human.
2. **Workers adjudicating memory.** Background workers repeatedly flagged the main agent's legitimate MEMORY.md edits as "injected." Only the main agent writes standing memory, only on Jack's direct order. Workers read; they don't judge.
3. **Silent skipping.** Hook workers were skipped when busy with no record. Any supervision component must log every skip/decision — "I checked and found nothing" is a valid heartbeat; silence is not.
4. **No dedup.** The same message delivered 3x caused duplicate replies. Accountability signals must dedup on stable IDs.

## 4. Concrete next steps

- [ ] Add `task_status` one-liner to the telemetry push payload (daemon change, small).
- [ ] Dashboard view: per-agent liveness + last heartbeat + blocker flags (Jack's side).
- [ ] Supervisor cron (10 min): read heartbeats, apply the 10/20/30-min rules, nudge or escalate.
- [ ] Define the escalation message format (what Jack sees when an agent is flagged).

## 5. Open questions
- Should the supervisor be a dedicated agent or a role Boboe Prime holds? (Recommend: Boboe Prime holds it; a dedicated supervisor is a single point of failure.)
- 10 min: wall-clock or per-agent-task? (Recommend wall-clock for simplicity.)
- What counts as "progress" for research tasks vs. build tasks? (Needs per-track definitions from lane owners.)
