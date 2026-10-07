# Area 11: Comms protocol design

## Area
Comms protocol design — Boboe 10

## Problem
Twelve autonomous agents coordinating only through free-form Slack posts cannot hold a multi-day mission together. We have already seen the failure modes live: agents post "I'll do X/Y/Z" with no shared claim registry (Jack's 2026-10-07 correction — zero actual coordination), @mention storms that trigger reply loops, duplicate replies from racing workers, dead threads that keep getting revived, and no enforced liveness — nothing stops an agent from silently "falling away." Slack is also a single point of failure: if it goes down, the fleet is blind and mute. A protocol must define message types, routing, claiming, liveness, and fallbacks — not just "post in #all-agentnet."

## Options considered
| Option | Upside | Downside |
|---|---|---|
| Do nothing / keep current (free-form Slack: top-level posts, threads, @mentions, reply_required rule, Muse Wall typing mentions into main chat) | Zero new infra; works today for human-in-the-loop bursts | Proven not to work for autonomous runs: no claim registry (duplicate/overlapping work), no liveness enforcement, one channel mixes broadcast + worklog + alerts, Slack outage = total comms loss |
| Typed protocol on Slack + git-backed state (recommended): every fleet message carries a typed envelope; claims/heartbeats/status live as files in the repo; Slack is the transport and alert surface, git is the source of truth | Auditable, mergeable, survives Slack outages; machine-checkable (a cron can verify claims, heartbeats, done-artifacts); keeps fast Slack UX | Requires agent discipline on envelope format; merge conflicts on shared registry files need a convention (one file per agent + one index) |
| Repo-first, Slack-notify-only: agents never coordinate in Slack prose at all — they read/write coordination files and Slack posts are only pointers ("see agents/claims/boboe10.md") | Maximum durability and auditability; fully decoupled from Slack availability | Slower loop (poll repo, not push); harder for Jack to skim; risks agents not checking the repo often enough without a push trigger |
| Dedicated per-workstream Slack channels (#fleet-claims, #fleet-heartbeat, #fleet-alerts) | Separates noise classes; easy to mute all but alerts | Channel sprawl; agents must watch N channels; doesn't fix claiming or liveness by itself — still needs the registry and heartbeat rules |

## Recommendation
Adopt the typed-envelope protocol with git as the source of truth and Slack as the transport/alert surface (option 2), with repo-first fallback when Slack is unreachable (borrow option 3's fallback only). Concretely:

1. **Message envelope.** Every fleet coordination post starts with a typed tag: `CLAIM`, `UPDATE`, `DONE`, `BLOCKED`, `ASK`, `FYI`, `HEARTBEAT-ROLLUP`. Format: `[TYPE] [area/lane] — one line`. Free-form discussion stays in threads; the envelope makes the post machine-skimmable and lets a cron verify protocol compliance.
2. **Claim registry.** No agent starts work without a `CLAIM` post AND a row in `research/STATUS.md` (or a per-mission claims file): area, owner, expected artifact, ETA. First claim wins; a second claim on the same area must resolve in-thread with the coordinator before proceeding. `DONE` posts must link the artifact (file path or commit hash) — a DONE without a link is not done. This directly fixes Jack's "no coordination" correction.
3. **Routing rules.** `@mention` = "you owe me a response or action" (keep the existing reply_required semantics). Top-level broadcast without mentions = FYI, no reply expected. Thread = one workstream; threads have an owner and a TTL — stale threads are archived, never revived (generalize Jack's dead-thread order). DMs = 1:1 follow-ups only, never decisions (decisions must be visible to the fleet).
4. **10-minute accountability without noise.** Twelve agents posting "still alive" every 10 minutes is 1,700+ noise posts/day — unacceptable. Instead: each agent's cron writes `agents/heartbeat/<agent>.json` (agent, ts, current task, last artifact, healthy true/false) every 10 minutes. A rotating supervisor cron reads all 12 files every 10 minutes and posts ONE compact rollup (`HEARTBEAT-ROLLUP`: 12/12 alive, or names the missing). One miss → supervisor @mentions the agent in-thread; three consecutive misses → escalate to dot/Jack. The heartbeat must be written by the agent's own cron/daemon liveness, not derived from Slack traffic — measuring chatter restarts healthy agents and misses quiet-but-dead ones.
5. **Slack-down fallback.** If the Slack API fails for >5 minutes, agents switch to repo mode: write coordination notes to `agents/inbox/<agent>-<ts>.md` and keep working; a retry poller flushes them to Slack when it recovers. Telemetry heartbeats to Jack's receiver continue regardless (separate channel, already built). Supervisor rollups also get committed to the repo so history survives.
6. **Supervisor rotation (no single point of failure).** The rollup/escalation role rotates weekly among Boboes (order in `agents/supervisor.md`); the outgoing supervisor's heartbeat file names its successor, and if the supervisor itself misses twice, the deputy (next in rotation) takes over automatically.

## What to build / change
- [ ] `agents/COMMS.md` in fleet-telemetry: the envelope spec, routing rules, thread TTL rule, claim/DONE format (one page, normative)
- [ ] `agents/heartbeat/<agent>.json` schema + per-agent 10-minute heartbeat cron writing it (extend existing `slack-watch` crons or a new `heartbeat-boboeN` cron)
- [ ] `agents/supervisor.md`: rotation order, deputy rule, escalation thresholds (1 miss = nudge, 3 misses = escalate to dot/Jack)
- [ ] Supervisor rollup cron (10 min): read 12 heartbeat files, post one `HEARTBEAT-ROLLUP` to #all-agentnet, handle misses per thresholds
- [ ] Claim registry convention: extend `research/STATUS.md` pattern to all missions (one row per claim: area, owner, artifact, ETA, status)
- [ ] Update `agents/slack_cron.txt` prompt text: add envelope + routing rules so backstop runs enforce the protocol
- [ ] `agents/inbox/` directory + retry poller for Slack-down mode
- [ ] Commit supervisor rollups to repo (`agents/heartbeat/rollups/<date>.md`) for outage-proof history

## Open questions
- Who owns the supervisor rotation schedule — Boboe 2, Prime, or Jack? Needs a named decider for disputes (e.g., two agents claiming the same area).
- Should heartbeat interval stay 10 min at fleet scale, or move to 15 to cut cron load? 10 min × 12 agents is cheap for file writes; the rollup post is the only Slack cost.
- What counts as "healthy" in a heartbeat for an LLM agent — cron ran, daemon alive, or recent artifact produced? A cron can run while the agent is stuck; need a cheap self-check definition.
- Channel split: does #all-agentnet stay the single surface, or do HEARTBEAT-ROLLUP posts deserve their own channel so Jack can mute them?
- Cross-VM clock skew: heartbeat staleness checks assume roughly synced clocks — acceptable, or do we need the supervisor to use its own clock for "last seen"?
