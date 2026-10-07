# Swarm Coordination Infrastructure — Research Report

**Fleet:** Jack's Boboe fleet (Boboe Prime + Boboes 1–11) — personal Muse agents on Linux VMs,
coordinated today via Slack #all-agentnet + cron jobs + git repo (`AgentNet01/fleet-telemetry`).
**Date:** 2026-10-07
**Author:** Boboe 7 (lane: swarm coordination infrastructure), with three parallel research lanes.

## 0. Executive summary — the opinionated version

**The one architectural mistake to fix:** we are using a human broadcast channel (Slack) as the
machine task bus. Broadcast gives you no ownership — every subscriber sees "handle it" and either
all respond (duplicate replies) or each assumes another will (lost messages). Every failure we've
hit — hook workers skipping messages while busy, cron runs coalescing under load, duplicate replies
from racing workers — is the textbook signature of this mistake.

**The fix, in one paragraph:** keep Slack for humans; move machine coordination onto a durable
substrate. Stand up a small **coordination ledger** (SQLite + ~200 lines of Python) on one host:
agents heartbeat into it every 2 minutes (dead after 10 — that's the accountability answer),
work flows through an inbox table with atomic claim-then-act, leased claims, a reaper that
returns expired claims to the pool, and idempotency keys on every side effect. Every agent runs
as a systemd unit with restart policy and an honest watchdog pet from its work loop. No wake is
ever load-bearing: hooks only append to the inbox; a sweeper owns processing. Adopt
**SuperClaude + voltagent-meta** as the shared role/skill library, run per-agent work as
**Ralph loops**, expose shared capabilities as **MCP servers**, and pilot **maw-js** only for the
interactive cross-VM session story. Graduate to **NATS JetStream** (or **Temporal**) when the
fleet outgrows the ledger — not before.

**What NOT to do:** don't adopt a heavy multi-agent framework (CrewAI/LangGraph/MetaGPT are
in-process Python frameworks, not cross-VM fleet substrates); don't run leader election (designate
the coordinator, guard the role with a lease); don't build gossip/SWIM membership for 12 agents;
don't keep choreography-by-Slack as the coordination model.

---

## 1. Findings

### 1.1 How multi-agent swarms coordinate today

Four communication patterns, each with a real job:

| Pattern | Job | Verdict for us |
|---|---|---|
| Point-to-point (@mention, DM, HTTP) | Directed handoffs | Fine for rare directed asks; terrible as the backbone (no durability — this is exactly our hook-skip bug) |
| Shared blackboard (git repo, DB, shared doc) | Slow shared state | Keep `fleet-telemetry` as this: status, registry, audit journal. Never as a signaling channel (poll latency, merge conflicts) |
| Pub/sub broadcast (Slack channel) | Announcements, alerts, observability | Right for humans; **wrong for task assignment** — broadcast has no ownership, which is why we get duplicates *and* drops |
| Shared queue, competing consumers | Task assignment | **The missing primitive.** Broker hands each task to exactly one consumer; unacked tasks redeliver; poison messages go to dead-letter |

The cross-cutting rule from production practice: **at-least-once delivery + idempotent handlers +
dead-letter queues** is the non-negotiable triad. Our current model gives at-most-once delivery
with no DLQ — that's why messages vanish.

**Orchestration vs choreography:** choreography (event-driven, no center) fails exactly the way
we've lived it — state scattered, debugging forensic, missed steps undetected ("if you can't trace
events through your system, choreography will destroy you"). **Recommendation: hierarchical
orchestration.** A human-designated coordinator (Boboe 2 already plays this role) owns the plan
and task assignment; agents execute autonomously and report back. Two refinements for
days/weeks unattended: (1) the orchestrator keeps **no state in RAM** — task list, assignments,
retries live in the durable queue + blackboard, so any agent can reconstruct them; (2) every
handoff is a **typed JSON envelope** (`task_id`, `type`, `capability_tag`, `payload`, `dedup_key`,
`max_attempts`), not free text.

**Task assignment:** planner/worker (coordinator decomposes, assigns to named agents or capability
pools) as the base; capability-based routing via a small registry so agents are replaceable;
competing-consumer queues for pool work ("anyone can do delivery checks"). Skip work-stealing
(pointless for 12 heterogeneous LLM agents), auctions/bidding (coordination overhead highest of
all patterns, bids are made-up numbers), and optimal-assignment algorithms (static; our world is
dynamic).

**Leader election: you don't need it.** Ranked options: (1) human-designated leader + lease-based
failover — Jack names the coordinator; if the role ever needs to survive a dead VM, a Redis/SQLite
lock (`SET coordinator:lease <agent> NX EX 120`, renewed every ~30s) decides who holds it; ~10
lines and correct enough, since idempotent actions make the double-leader window harmless.
(2) Bully algorithm — O(n²) election storms on flaky networks; worse than a lease. (3) Raft —
reimplementing etcd to decide who runs a cron job; overkill until 50+ agents with no human
reachable. **Designate, don't elect.**

### 1.2 Communication channels: Slack vs alternatives

The pithy version from practitioners: **state is a database · work is a queue · coordination is a
message.** Humans already learned this — a company has both a database *and* Slack because they're
different jobs. Multi-agent systems are rediscovering it on a compressed timeline.

**What breaks with Slack-as-bus at our scale:**
- **No durability / at-most-once delivery.** A message with no live consumer vanishes. (Our
  hook-skip bug, verbatim.)
- **No ownership → duplicates and drops.** Broadcast can't assign; every agent either answers or
  assumes another will. (Our duplicate-reply bug, verbatim.)
- **Delivery retries without idempotency.** Slow ack → Slack redelivers → duplicate `event_id`s.
  The fix is a delivery-ID dedup window, which we don't have.
- **Bot echo loops.** A worker's status post triggers another bot that triggers the worker —
  the ~850 wakes/hour loop we already fixed once.
- **Context pollution.** Instant messaging is a single flat timeline designed for ephemeral human
  chatter; long-running multi-step agent tasks forced into it get context contamination. (One
  practitioner response: subject-keyed task lifecycles with per-task filesystem isolation.)
- **Rate limits and threading tax.** Slack API rate limits govern request frequency; threads hide
  half the diagnostic conversation from anyone not opening each one.

**What actually works (evidence from people running agent fleets):**
- **Git as the slow blackboard wins** for shared state: already there, universal, persistent
  history, async-native, debuggable, human-readable. Downside is poll latency — which is fine for
  state, fatal for signaling. (This matches our `fleet-telemetry` repo usage.)
- **A purpose-built agent bus beats both generic brokers and chat.** The most instructive case
  found: `parf/ai-agent-bus` (github.com/parf/ai-agent-bus) — a solo builder's Go daemon giving
  Claude/Codex agents a registry, message queues, KV storage, locks, an MCP face, and a dashboard.
  Its public design notes are a gift: they evaluated **Redis Streams** (per-session inbox streams,
  consumer groups, `XAUTOCLAIM` for stuck messages, dead-letter stream) and **NATS** (accounts,
  scoped signing keys, KV, request-reply), then simplified to one daemon with at-least-once
  delivery, explicit ACK, durable dedup, dead-letter with replay, and per-record locks with TTLs.
  License is PolyForm Noncommercial and it's a one-maintainer project (1 star) — **don't adopt the
  code, steal the design**: registry + durable queues + KV + locks + MCP face + dashboard is
  exactly the component list.
- **NATS JetStream vs Redis Streams** (if we want a real broker later): NATS is one static binary
  with queue groups (competing consumers), durable streams with replay, and max-deliver +
  dead-letter advisories as first-class primitives; `nats-server -js` and you're running. Redis
  Streams gives the same semantics but you hand-manage trimming, pending-entry timeouts, and DLQ.
  Core NATS without JetStream is fire-and-forget — messages with no subscriber vanish — so
  JetStream (durable) is the only mode that counts.
- **Keep Slack, but demote it.** Slack stays as the human observability layer ("task X claimed by
  Boboe 4", "task Y → DLQ") and the human-to-fleet channel. Machine traffic moves off it.

### 1.3 Accountability: the 10-minute heartbeat

Jack's requirement: *"every agent is accounted for every 10 minutes or so so that one doesn't
fall away."* The design that satisfies it literally:

**Components:**
1. **Per-agent beater inside the work loop** — each agent POSTs `/beat` every **2 minutes** with:
   agent id, host, boot generation, current task id, queue depth, last error, software version,
   restart count. The beater lives *in the work loop* so a beat proves the agent is *working*,
   not that a side ticker is alive (a background pinger that stays healthy while work is wedged
   is false assurance — this is the systemd-watchdog lesson).
2. **The ledger (coordinator host)** — SQLite (WAL mode) + minimal HTTP service. Tables: `agents`,
   `beats`, `inbox`, `claims`, `idempotency`, `events` (append-only). Serves heartbeats,
   claim/ack, and a `/status` JSON dashboard. Load: 12 agents × 30 beats/hour — trivial.
3. **External dead-man's switch** — the ledger pings an external monitor every 2 min; 2–3 missed
   pings → alert Jack. The watcher must not share fate with the fleet (a host outside it: Jack's
   machine, a cheap VPS, or hosted healthchecks.io).
4. **Dashboard** — per-agent last-beat age color bands, in-flight claims, DLQ depth, reaper
   actions. Human- or watchdog-readable at a glance.

**The timeout ladder** (industry 3× rule: detection threshold ≥ 3× interval, cf. Eureka 30s/90s,
etcd lease keepalives):

| Event | Threshold | Meaning |
|---|---|---|
| Beat interval | 2 min | Each agent POSTs every 2 min |
| Quiet | 4 min | Dashboard amber, no action |
| Suspect | 5 min | Low-urgency alert to Jack; keep claims |
| **Dead** | **10 min** | Declare dead; reaper releases claims for re-claim; high-urgency alert |
| Tombstone retention | 20 min | Keep dead row; never delete immediately |

**Failure-detection theory worth knowing (borrow ideas, not code):**
- **Phi-accrual detectors** (Cassandra/Akka): suspicion level rises continuously from observed
  interval distributions instead of binary alive/dead — adapts to jitter. Our fixed ladder is
  simpler and auditable; switch only if jitter causes false suspects.
- **SWIM** (Consul): probe → indirect probing via random peers → suspect → dead; dead members
  kept until `Tcleanup = 2×Tfail` so late gossip can't resurrect them. Borrow the tombstone rule:
  keep dead rows 2× the dead threshold, and assign rejoining agents a new **boot generation
  number** so stale events from a previous life can't be confused with the new one.
- **Leases** (etcd-style): presence = TTL renewed by the holder; expiry decided by the ledger's
  clock alone — no clock-skew arguments.

### 1.4 Long-running autonomous operation

**Supervision: use systemd, not supervisord/PM2.** supervisord is a Python daemon that dies with
its process tree and only knows "process exists" (a deadlocked-but-running process looks
healthy); PM2 is Node-centric with the same fragility. systemd is PID 1, has cgroups, journal
logging, and is already installed. Per-agent unit sketch:

```ini
[Unit]
Description=Boboe agent %i worker
After=network-online.target
StartLimitIntervalSec=600
StartLimitBurst=5

[Service]
Type=notify
ExecStart=/home/boboe/fleet/bin/agent-loop --agent boboe-%i
Restart=on-failure
RestartSec=30
RestartMaxDelaySec=600
WatchdogSec=180
MemoryMax=2G
CPUQuota=150%
StandardOutput=journal
```

Gotchas: `StartLimitBurst` only guards bursts — a steady-state crash loop runs forever — so pair
it with backoff **and** a restart counter in the beat payload; >10 restarts/hour → coordinator
pages Jack (Erlang-style escalation up the tree). `Type=notify` kills the illusion-of-health
crash loop. The watchdog pet must come **from the work loop after a full sweep**, not a side
thread.

**Checkpointing:** a crash should cost only what was in flight, never what was confirmed.
Per-agent durable log `~/fleet/runs/<run-id>/` with `events.jsonl` (append-only, fsync'd) +
`snapshot.json` (materialized state + last applied seq). Event types: `RUN_STARTED`,
`STEP_STARTED`, `STEP_COMPLETED` (with idempotency key), `STEP_FAILED`, `RUN_FINISHED`.
Recovery: replay after `last_applied_seq`, skip completed steps, resume at first incomplete step —
the poor-man's Temporal event-history replay. Write-ahead discipline: log `STEP_STARTED` *before*
the side effect, `STEP_COMPLETED` after; recovery re-runs the interrupted step, safe because every
step is idempotent. Off-the-shelf: **`durarun`** (pip, SQLite WAL, `@step` decorator, no server)
— evaluate before hand-rolling.

**Idempotency (at-least-once + idempotent effects = the achievable target):**
1. **Claim-first, work-second** — never check-then-act. Atomic claim on SQLite:
   `BEGIN IMMEDIATE` (take the write lock up front — `SELECT … FOR UPDATE` is a silent no-op on
   SQLite) + guarded `UPDATE inbox SET status='claimed' … WHERE id=:id AND status='pending'
   AND version=:v` (loser gets 0 rows).
2. **Leased claims + reaper** — 5-min claim TTL, worker renews every ~90s; single-flight reaper
   every 2 min returns expired claims to pending; after 3 attempts → dead-letter + human alert.
3. **Idempotency keys on effects** — `slack-reply:<channel>:<msg_ts>`,
   `gh-issue-comment:<org>/<repo>:<n>:<sha8>`; insert key as `PROCESSING` before the side effect
   (unique constraint arbitrates races); `COMPLETED` replays stored result; **hash the payload and
   reject same-key-different-body**.
4. **Fencing for zombies** — a lease gives liveness, not exclusivity: a paused worker can wake
   after expiry and double-apply. Every claim carries a monotonic `generation`; the ledger rejects
   writes with stale generations. For resources that can't validate tokens (Slack), the op itself
   must be idempotent — re-check the thread immediately before posting *and* use the idempotency
   key.

**Fixes for our three observed failure modes:**
- **Hook-skip races → level-triggered, no wake is load-bearing.** The hook's only job is
  `INSERT INTO inbox` (~1ms, never "busy", idempotent on natural key). A sweeper loop owns
  processing: claim → process → ack. The hook may *poke* the sweeper as a latency optimization,
  but a dropped poke costs at most one sweep interval. (This is the Kubernetes-controller pattern:
  level-triggered reconciliation, not edge-triggered events.)
- **Cron coalescing/overlap → single-flight + watermarks + idempotency.** `flock -n` so
  overlapping runs exit immediately; never derive work from the schedule — keep a **watermark**
  and process everything since the last committed watermark (a skipped run just widens the next
  window); every effect idempotent; wrap in `timeout`; jitter per-agent schedules so twelve
  agents don't thundering-herd at :00.
- **Duplicate replies → claim-then-act + re-check + idempotency key.** Claim the inbox row
  *before* composing; re-read the thread immediately before posting (shrinks the TOCTOU window
  to milliseconds); post under idempotency key `slack-reply:<channel>:<thread_ts>` so a zombie's
  retry is suppressed; renew the claim lease during long compositions.

### 1.5 Existing harnesses and frameworks

Ranked by deployability for our fleet (12 Muse-class agents on VMs, self-hosted, days/weeks
autonomous):

1. **wshobson/agents (SuperClaude) — ADOPT.** ~33.5k stars. Not a coordinator — the in-session
   role/skill library: 80 plugins, 185 specialized agents, 153 skills, 16 multi-agent workflow
   orchestrators, three-tier model routing (Opus plans / Sonnet codes / Haiku cheap work).
   Install on every VM; stop reinventing role definitions and model-tier policy.
2. **VoltAgent/awesome-claude-code-subagents — ADOPT.** 17.1k stars, 161+ subagent markdown
   definitions including a `voltagent-meta` category for meta-orchestration agents. Zero
   dependency, auditable markdown — seed library for coordinator/overseer definitions.
3. **Ralph loop (chrismdp/ralph + subsy/ralph-tui) — ADOPT.** The minimal pattern: bash loop,
   each iteration a fresh session doing one ticket, committing, flipping status, exiting; state in
   files + git, not context. ralph-tui productionizes it (TUI, task trackers, session
   persistence, remote multi-instance management via WebSocket). **Dumb loop + good stop
   conditions beats clever orchestrators** — this is the per-agent autonomy answer.
4. **soul-brews-studio/maw-js — PILOT (with caveats).** tmux-native federation: `maw team`
   persistent teams surviving across sessions, heartbeats, pane routing, `oracle-invite` pulling
   agents on *other machines* into the team. Closest mental model to our fleet in the wild —
   but it's session/tmux-centric and our agents are headless cron-driven workers, so pilot it
   for the interactive cross-VM story, not as the worker substrate.
5. **MCP (Model Context Protocol) — ADOPT.** Anthropic's tool-sharing standard (Linux Foundation
   Agentic AI Foundation, 10k+ public servers). Every shared capability (repo, telemetry, deploy)
   should be an MCP server agents discover — not a bespoke script each Boboe reimplements.
6. **thena/swarms — BORROW IDEAS FROM.** Claude Code orchestration delivered as *skills*
   (swarm-planner, parallel-task wave execution with verification, 12-agent rolling pool). The
   delivery mechanism — orchestration as composable skills, not a framework — is the modern
   pattern; steal wave-execution and verification.
7. **ruvnet/ruflo (formerly claude-flow) — BORROW IDEAS FROM.** ~70k stars, MIT, real history
   (queen-led hive-mind swarms, AgentDB vector memory, SPARC methodology). Single-machine Claude
   Code augmentation, not a cross-VM fleet coordinator; marketing numbers self-reported. Steal
   hive-mind role topology and the AgentDB memory pattern.
8. **OpenClaw — BORROW IDEAS FROM.** Persistent gateway + cron/wakeups + ~24 messaging surfaces,
   speaks MCP/A2A/ACP, can host Claude Code as an external harness. Study its cron/wakeup and
   skill-loading design; our telemetryd + slack-watch cron is growing into this shape.
9. **A2A protocol — WATCH, adopt the cheap parts.** Google-origin, now AAIF alongside MCP:
   MCP = agent↔tool (vertical), A2A = agent↔agent task delegation (horizontal). Adopt the
   conventions without the SDK: agent cards (`agent-card.json`: identity, capabilities, endpoint)
   and the typed task lifecycle (pending → in-progress → completed/failed/canceled). Skip ANP/AGNTCY
   (cross-org identity — irrelevant for a trusted fleet).
10. **smtg-ai/claude-squad — BORROW ONE PATTERN.** 7k stars; tmux + git-worktree session manager.
    Not a coordinator — but the worktree-isolation pattern is how parallel agents share a repo
    without stepping on each other.
11. **MetaGPT / ChatDev / OpenHands / CrewAI — SKIP as systems.** Research demos or in-process
    frameworks; none runs Muse-class agents as a persistent cross-VM fleet. Borrow OpenHands'
    shared-event-stream and structured-handoff insights only.
12. **Temporal — ADOPT LATER.** The correct long-term durable orchestrator (workflows survive
    crashes, built-in retries, full replay/audit; Replit/Retool/Netflix production evidence).
    Overkill today — needs Postgres + server — but it's the graduation path when missions must
    survive days unattended and be auditable afterward.
13. **Commercial (Devin/Replit/Cursor) — SKIP.** Closed; confirms the industry pattern (isolated
    workspaces + central dashboard + human-gated merges) without giving us anything deployable.

---

## 2. Ranked recommendations: adopt vs build vs skip

### ADOPT (deploy now)
1. **Coordination ledger (SQLite + ~200 lines Python)** — heartbeats, inbox, claims, reaper,
   idempotency, `/status` dashboard. The single highest-leverage build; everything else hangs
   off it. (§3)
2. **systemd units per agent** — `Restart=on-failure`, rate limits, `Type=notify`, honest
   `WATCHDOG=1` pet from the work loop. Already on the box; just write the units.
3. **Ralph loops** — each Boboe's work loop is a dumb ticket loop with explicit stop conditions;
   state in git + files.
4. **SuperClaude (wshobson/agents) + voltagent-meta** — shared role/skill library on every VM;
   standardize the Opus/Sonnet/Haiku three-tier model policy.
5. **MCP servers** for shared capabilities (repo ops, telemetry, deploy) instead of bespoke
   per-agent scripts.
6. **External dead-man's switch** — `tend` or `pingward` self-hosted off-fleet, or hosted
   healthchecks.io — watching the coordinator. The watcher must not share fate with the fleet.
7. **A2A conventions (cheap parts)** — `agent-card.json` per agent, typed task envelopes and
   lifecycle states. No SDK needed.

### BUILD (thin, ourselves)
8. **Sweeper + claim/ack + reaper + idempotency** on the ledger — ~200 lines; the reliability
   core. (SQLite `BEGIN IMMEDIATE` + guarded updates; no broker.)
9. **`/status` dashboard** — 50-line HTML page on the ledger's JSON. Don't contort Uptime Kuma
   into fleet-state.
10. **Cron hardening** — `flock -n` single-flight, watermark-based windows, `timeout`, jittered
    schedules, idempotent effects. Keep cron as a dumb ticker in front of a reliable state
    machine.
11. **Per-run checkpointing** — evaluate `durarun` first; else the `runs/<id>/events.jsonl` +
    snapshot sketch.

### BORROW IDEAS FROM
12. ruflo hive-mind role topology + AgentDB memory pattern; thenha/swarms wave-execution and
    verification-as-skills; OpenClaw cron/wakeup design; claude-squad worktree isolation;
    parf/ai-agent-bus component list (registry + queues + KV + locks + MCP face + dashboard).

### PILOT
13. **maw-js** — 2-VM trial for interactive cross-VM sessions only.

### SKIP / WATCH
14. **Skip:** leader election, gossip/SWIM, Kafka, Celery/RabbitMQ (ops burden for 12 agents),
    LangGraph/CrewAI/AutoGen as fleet substrates, MetaGPT/ChatDev, ANP/AGNTCY, commercial closed
    systems, stale agent-farm code.
15. **Watch / graduate later:** NATS JetStream (when machine traffic outgrows the ledger or
    agents span unreliable networks — the envelope format should be broker-agnostic from day
    one), Temporal (when multi-day missions need crash-recovery + audit replay), full A2A.

### The NATS-vs-SQLite call (resolving the one real disagreement)
Two lanes disagreed: one said adopt NATS JetStream as the message substrate; the other said
build on SQLite and skip the broker. **Ruling: SQLite ledger for v1, NATS as the documented
graduation path.** Reasons: 12 agents × minute-scale tasks is trivially within SQLite/WAL's
envelope; one fewer daemon to operate, monitor, and secure; the team's existing skill set is
shell/Python/cron/systemd, not broker ops; and every primitive NATS gives us (competing
consumers, redelivery, DLQ) is reimplementable in ~200 lines on SQLite with `BEGIN IMMEDIATE`
and a reaper. Revisit when: sustained machine traffic exceeds ~100 msgs/min, agents span
unreliable networks, or we want cross-fleet fan-out — then the typed envelopes move to
JetStream subjects unchanged.

---

## 3. Proposed fleet coordination layer

### Architecture

```
                        ┌─────────────────────────────────┐
                        │  COORDINATOR HOST (one VM)       │
                        │  ledger.db (SQLite, WAL)        │
                        │  /beat  /claim  /ack  /status   │
                        │  reaper (single-flight, 2 min)  │
                        │  notifier → Slack ops / Jack DM │
                        └────────┬────────────────────────┘
                 2-min beats      │  claim/ack/renew
        ┌────────────┬───────────┴───────────┬────────────┐
   ┌────┴────┐  ┌────┴────┐             ┌────┴────┐  ┌────┴────┐
   │ Boboe 1 │  │ Boboe 2 │  …          │Boboe 11 │  │Boboe 12 │
   │systemd  │  │systemd  │             │systemd  │  │systemd  │
   │agent-   │  │agent-   │             │agent-   │  │agent-   │
   │loop     │  │loop     │             │loop     │  │loop     │
   └─────────┴──┴─────────┴─────────────┴─────────┴──┴─────────┘
        Slack #all-agentnet (humans + announcements only)
        fleet-telemetry git repo (slow blackboard: registry, audit)
        External dead-man's switch → watches coordinator
```

**Roles:** Boboe 2 (or Jack's designation) is the human-designated coordinator — owns the plan,
decomposes into typed task envelopes, posts them to capability-tagged inbox queues. Agents run
Ralph loops: beat → sweep inbox (claim → work → ack) → beat. Coordinator state lives in the
ledger, never in RAM — any agent can reconstruct it.

### The 10-minute accountability heartbeat (spec)

- **Beat:** `POST /beat` every 2 min from inside each agent's work loop: `{agent_id, host,
  boot_generation, task_id, queue_depth, last_error, version, restarts_since_boot}`.
- **Ladder:** quiet at 4 min (dashboard amber) → suspect at 5 min (low-urgency alert to Jack,
  claims kept) → **dead at 10 min** (claims released by reaper for re-claim, high-urgency alert,
  orphaned in-flight work explicitly listed) → tombstone retained 20 min; rejoining agents get a
  new boot generation.
- **Reaper:** single-flight (`flock -n`), every 2 min, on the coordinator: expires leases past
  TTL, returns claims to pending (attempts+1), dead-letters after 3 attempts, pages on orphans.
- **External watch:** ledger pings the off-fleet dead-man's switch every 2 min; 2–3 missed →
  alert Jack. This is the one alert that must never be in-fleet.
- **Slack alert routing:** suspect/dead/DLQ alerts go to a designated ops thread or Jack's DM —
  never as box-health spam in #all-agentnet (existing standing rule).

### Data model (ledger)

Tables: `agents(agent_id PK, host, boot_generation, capabilities, last_beat, status)`,
`inbox(id PK, queue, envelope JSON, status, claimed_by, claim_token, generation, lease_expires,
attempts, dedup_key UNIQUE, created_at)`, `idempotency(key PK, status, result_json,
payload_hash, created_at, expires_at)`, `events(seq PK, ts, type, payload)` (append-only audit),
`watermarks(name PK, value)` (cron windows).

Key formats: idempotency `slack-reply:<channel>:<msg_ts>`,
`gh-issue-comment:<org>/<repo>:<n>:<sha8>`; claims `claim_<agent>_<uuid8>`; all timestamps UTC
epoch; DB pragmas `journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON`.

### Task envelope (broker-agnostic, works on SQLite today / NATS tomorrow)

```json
{
  "task_id": "task_9f3a2c1e",
  "type": "delivery-check",
  "capability_tag": "slack-ops",
  "payload": {"thread_ts": "1791314066463149.000100"},
  "dedup_key": "delivery-check:1791314066463149.000100",
  "max_attempts": 3,
  "created_at": 1791347500
}
```

### Rollout order
1. **Ledger + schema + `/beat` + `/status`** on the coordinator host; agents beat every 2 min
   (2-min cron backstop until loop integration lands).
2. **External dead-man's switch** watching the coordinator — close the "who watches the watcher"
   loop before relying on any in-fleet alert.
3. **systemd units** (`Restart=on-failure`, rate limits, `Type=notify`, honest watchdog pet).
4. **Inbox + claim/ack + idempotency**; Slack hook becomes insert-only; sweeper with `flock -n`.
5. **Reaper + dead-letter + escalation notifier.**
6. **Watermark-ify every cron job**; jitter schedules; `timeout` wrappers.
7. **Per-run checkpointing** (`durarun` eval, else JSONL).
8. **Install SuperClaude + voltagent-meta** on all VMs; write `agent-card.json` per agent;
   convert shared scripts to MCP servers.

### What this fixes, mapped to our scars
| Our failure | Fix in this design |
|---|---|
| Hook worker skipped while busy → message lost | Hook is insert-only; sweeper owns processing (level-triggered). A skipped wake costs one sweep interval, never a message. |
| Cron coalescing (1-min → 4–5 min), overlapping runs race | `flock -n` single-flight; watermark windows; idempotent effects; jitter. Coalescing degrades to latency. |
| Duplicate replies from racing workers | Atomic claim-then-act; idempotency key `slack-reply:<channel>:<ts>`; re-check thread pre-post; lease renewal during long compositions. |
| ~850 wakes/hour echo loop | Machine traffic off Slack; Slack is announcements only; no worker posts trigger another worker. |
| Agent silently dies, nobody notices for hours | 2-min beats; suspect at 5, dead at 10; claims auto-released; external watcher on the coordinator. |
| Coordinator VM dies | State in ledger on disk (WAL); any agent can reconstruct; lease lets a runner-up take the role. |

---

## 4. Open questions for Jack

1. **Coordinator host:** which VM hosts the ledger? Prefer the most reliable box, ideally not one
   running a busy agent.
2. **External watcher placement:** off-fleet host for the dead-man's switch (your local machine,
   a cheap VPS, or hosted healthchecks.io) — one decision, one deploy.
3. **Heartbeat tightness:** 2-min beats / 10-min dead, or tighter (1-min / 5-min)? Don't go
   below 1-minute beats — heartbeat storms aren't worth it at this scale.
4. **Alert routing:** which channel/DM gets suspect vs dead vs dead-letter alerts?
5. **Green light to build:** the ledger + systemd units + cron hardening are ~a day of work and
   subsume the current hook/cron contraption. Proceed?

---

## 5. Sources

- Coordination patterns: shubh2016shiv/agentic-ai-multi-agent-systems (communication &
  coordination notes); connectory.ai choreography-vs-orchestration comparison;
  imdaeseong/skills agent-builder SKILL.md (typed handoff contracts); NATS vs Redis pub/sub
  decision matrix (dev.to/young_gao); ai-agent-book ch.10 (agent/OS correspondence table).
- Channels: "Why Multi-Agent Systems Need a Chat Protocol" (medium.com/@naykip — state/queue/
  message triad); "Communication Protocols for AI Agents" (dev.to — git-as-bus case study);
  "Your Multi-Agent System Doesn't Have a Memory Problem" (dev.to — shared context layer);
  parf/ai-agent-bus (GitHub — registry/queues/KV/locks/MCP-face design docs, evaluated Redis
  Streams and NATS); automater.ai Slack agent subscription failure modes (echo loops, thread
  storms, redelivery dupes); pub.towardsai.net context-pollution critique of IM transports;
  sergeiwallace/ai-cli-utils NATS setup guide for Claude Code fleet messaging.
- Accountability/ops: phi-accrual failure detectors (Hayashibara et al.); SWIM membership
  protocol; Consul/etcd lease semantics; Eureka 30s/90s convention; systemd `Restart=` /
  `WatchdogSec` / `sd_notify` semantics; Erlang/OTP supervision strategies; Temporal durable
  execution & event-history replay; LangGraph checkpointers; `durarun`; Stripe idempotency-key
  semantics; SQLite queue mechanics (`BEGIN IMMEDIATE`, guarded updates); Kubernetes
  level-triggered reconciliation.
- Harness lane: ruvnet/ruflo, soul-brews-studio/maw-js, wshobson/agents (SuperClaude),
  VoltAgent/awesome-claude-code-subagents, chrismdp/ralph, subsy/ralph-tui, thenha/swarms,
  smtg-ai/claude-squad, OpenClaw, MCP / A2A (AAIF), MetaGPT, ChatDev, OpenHands, CrewAI,
  Dicklesworthstone/claude_code_agent_farm. (Star counts / activity as of ~Sep/Oct 2026
  search snapshots; Ruflo performance claims self-reported, no independent benchmark found.)
