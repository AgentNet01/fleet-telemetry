# Multi-Agent Coordination Patterns — Research Brief
**Track 1 of 4: swarm coordination for the Boboe fleet (~13 agents, Linux VMs, Slack + shared git repo)**
**Researched by Boboe 4's subagent, 2026-10-07**

## Key Findings

### 1. Topologies: most production "swarms" aren't mesh — they're hub-and-spoke with a shared blackboard
Surveying real deployments (MetaGPT, Magentic-One, Claude Code worktree fleets, LangGraph supervisor patterns, AutoGen actors), the consistent winner for coding/research fleets is a **hybrid: hub-and-spoke delegation + blackboard shared memory + point-to-point allowed only for bounded handoffs**. Reasons:
- **Mesh (any-to-any)** breaks down fast: communication channels scale as O(N²) — at 13 agents that's 78 pairwise channels. Practitioners cite a hard "mesh ceiling" around 7 agents; beyond it, overlapping context produces duplicate or contradictory work and debugging becomes forensic ("what did agent B know when it decided?").
- **Pure star/hub** has a bottleneck single point of failure: all context funnels through the coordinator, which becomes the cost and latency center.
- **Hierarchical** (max 2 levels) is the practical answer for 13: 2–3 sub-coordinators under one lead coordinator, each owning a domain. This partitions context so no agent needs the full picture.
- **Blackboard / publish-subscribe shared memory** outperforms chat-based coordination in benchmarks (reported 13–57% end-to-end success gains in the literature survey). MetaGPT's core innovation was replacing agent *dialogue* with structured, schema-typed artifacts in a shared message pool — the artifact, not conversation, is the coordination mechanism. This directly kills "telephone game" error cascades.
- For Jack's setup: **Slack is the chat layer, not the coordination layer.** Coordination should live in the shared git repo (files = blackboard); Slack carries only addressed, actionable signals.

### 2. Work distribution: claim-based beats assignment beats queues — but each needs discipline
- **Direct assignment** (coordinator assigns tasks) is simplest and debuggable: one agent owns the delegation decision, so there's exactly one "throat to choke." Breaks when the coordinator's context saturates.
- **Central task queue** (agents pull) handles mixed workloads well but needs atomic claim semantics — classic distributed-systems work here: `UPDATE ... WHERE status='queued'` as the guarded claim, so only one worker wins a task.
- **Claim-based / market model** (agents self-organize around a shared board, claiming by capability) is fastest for independent parallel work (~3–5× speedup reported for fan-out patterns) but requires explicit claim-before-act plus leases.
- **Anti-duplication mechanics (production-standard):** claim-before-act with a random lease token; compare-and-set transitions (`CLAIMED → RUNNING → DONE`) so stale callbacks can't double-apply side effects; leases with expiry + renewal instead of permanent locks (prevents a dead agent holding a task forever); and **idempotency keys** on every externally-visible action so at-least-once retries are safe. For file-based setups: `git push` fails on conflict = free atomic compare-and-set for claiming tasks.

### 3. Shared state: single-writer principle, tiered by consistency need
The best-performing multi-agent setups tier their shared state:
- **Tier 1 — true coordination (locks, task claims, IDs):** must be exclusive/atomic. One writer per object; atomic transitions only.
- **Tier 2 — causal ordering (task status, dependencies):** writes need to see prior state; use optimistic concurrency (write-if-version-matches, retry on conflict).
- **Tier 3 — eventually consistent (heartbeats, logs, comments):** conflicts harmless — layout files per-agent (append-only per-agent logs) so merging never conflicts.
- CRDTs are the elegant answer for Tier 3 and even Tier 2, but for 13 agents on a shared git repo, **you don't need a CRDT library**: the file layout *is* the conflict-avoidance (per-agent directories, append-only logs). Reserve atomic operations for Tier 1. Event-sourcing (append-only event log + derived snapshots) beats mutable shared JSON because every agent can replay history, conflicts are visible, and a racing compactor produces identical results.
- **What to share vs. keep local:** Share task state, claims/leases, results-as-artifacts, and heartbeats. Keep local: working drafts, scratch exploration, full conversation context. Production guidance is explicit: pass **state deltas, not full state** between agents — token savings of 68–84% on handoffs are reported, and redundant context echo is the #1 token-cost driver in multi-agent setups (coordination can burn ~15× single-agent token volume).

### 4. Leader election: don't build Raft — rotate or appoint
At 13 nodes with a benevolent human owner, consensus is overkill. Lightweight patterns:
- **Appointed coordinator** (Jack's "Boboe 2") with a **documented failover chain** (Boboe 2 → Boboe 1 → …): if the coordinator's heartbeat is stale > N minutes, next in line announces takeover. This is how most small fleets do it; it's a human-readable standup rule, not an algorithm.
- **Rotating coordinator** by time slot (e.g., coordinator = agent whose index matches the day/hour) — no election at all, just a shared clock. Works when coordinator duties are lightweight.
- Only reach for quorum voting when two agents *must* agree on irreversible state; even then, a git push race or a "highest-lexicographic-ID claims it" rule beats implementing elections.

### 5. Conflict resolution: schemas and merge contracts, not negotiation
- MetaGPT's lesson: **schema-typed artifacts** prevent conflicts from forming — two agents can't produce incompatible outputs if both must validate against the artifact schema (JSON Schema or a required Markdown section layout).
- For genuinely parallel work on shared files: branch-per-agent worktrees (Claude Code's pattern — creator Boris Cherny calls parallel worktree-isolated sessions "the single biggest productivity unlock"), then merge checkpoints. Isolation eliminates most conflicts by construction.
- For residual conflicts: last-writer-wins with a **conflict journal** (loser's version preserved in a dated file, never silently overwritten), or a designated reviewer agent whose verdict is final. Adversarial "debate then judge" patterns measurably improve reasoning (~13%) but cost 3× agents — reserve for high-stakes calls.
- Duplicate outputs: detect via content fingerprints (hash of output) in the task ledger; reconciliation is a named step ("complete-once → reconcile") not an afterthought.

### 6. Communication discipline — directly addressing the 850 wakes/hour incident
The fleet already hit the #1 documented multi-agent failure mode. The incident literature names it explicitly: **cyclic handoff deadlocks ("infinite ping-pong")** — Agent A hands to B hands back to A — and chat-loop token burn. Every production playbook converges on the same countermeasures:
- **TTL / hop bounds on every handoff** — a handoff envelope carries `hops_remaining` (decremented per transfer, hard-stop at 0). This is the direct fix for ping-pong.
- **Circuit breakers and loop budgets:** per-agent max-iterations AND a global max-steps counter per task run. OpenAI/DevOps guidance lists bounded handoff counts first.
- **"Don't answer an answer":** reply only when (a) directly named, (b) assigned work, or (c) the human explicitly calls for speech. Acks are not conversations — one token-efficient ack ("claimed T-42", "done: summary in <link>") then silence.
- **Reply-required semantics:** a named mention = must act; everything else = FYI, do not respond. This is exactly the protocol the fleet's standing orders already encode — the incident shows it needs *mechanical* enforcement (a rate cap per agent per hour, backoff when exceeded), not just a norm.
- **Unique-participant guard:** at least 3 distinct agents in the last N handoffs — detects A↔B ping-pong deterministically.
- **Rate limits + exponential backoff** on wake triggers; batch non-urgent notifications; structured queues instead of "prompt instructions alone" to steer agents.
- **No free-form handoff text:** handoffs are typed JSON envelopes (task id, from, to, payload hash, hops_remaining, deadline). Agents parse structure, not prose — this also cuts hallucination cascades.
- **Interrupt/preemption protocol:** a coordinator HOLD/ABORT signal checked before each tool call can cut wasted tokens on invalidated runs dramatically (one harness reports 73%).

### 7. Liveness/progress tracking
- **Heartbeat pattern:** every agent writes a timestamped heartbeat to its own Tier-3 file every N minutes (git push or append). Coordinator runs a sweep: heartbeat stale > 3× interval = suspect; lease on claimed task expired with no renewal = reclaimable.
- **Task ledger + progress ledger** (Magentic-One's production pattern): the coordinator keeps two ledgers — *what must be true* (task ledger) and *what's been done and remains* (progress ledger). The progress ledger is the stuck-detection surface: a task CLAIMED but unchanged for 2× its lease = dead-worker recovery.
- **Dead-worker recovery:** on heartbeat timeout or lease expiry, coordinator marks task `ORPHANED` → requeues to `READY`. Ambiguous in-flight work is resolved explicitly, never silently replayed without idempotency.
- **Watchdog, not polling agents:** one coordinator process runs liveness checks; workers don't check each other (O(N²) gossip is the path to the looping incident).

### 8. What production coding fleets actually do
- **MetaGPT (ICLR 2024):** SOP-encoded assembly line; publish-subscribe message pool of schema-typed artifacts; no free-form chat between roles.
- **Magentic-One (Microsoft Research):** single orchestrator with outer Task Ledger + inner Progress Ledger; specialist workers (web, file, code, terminal); nested self-reflection loop before each assignment.
- **Claude Code / Devin-style fleets:** the dominant production pattern is **isolation over coordination** — parallel agents in separate worktrees/branches with tight task boundaries and merge checkpoints, not chatty mesh coordination. The field-report consensus: "tighter task boundaries and merge checkpoints, not more chat."
- **Common production checklist items:** explicit input/output schemas per agent; termination conditions reachable from every state; per-agent AND global iteration budgets; consensus mechanism for conflicting outputs; typed handoff formats; observability trace IDs on every handoff.

---

## Recommendations (specific to the Boboe fleet)

**R1. Adopt hub-and-spoke + blackboard: keep Slack for signals, put coordination in the repo.**
Designate the shared git repo as the single blackboard: `fleet/tasks.json` (task board), `fleet/claims/` (per-task claim files), `fleet/agents/<name>/heartbeat` + `log` (per-agent Tier-3 files). Slack messages are *pointers* ("T-42 done, diff in PR #7"), never the state of record. This directly attacks the fleet's two known failure modes (the duplicate-reply thread incident and the 850-wakes/hour loop) by moving coordination off chat.

**R2. Appoint Boboe 2 as coordinator with a published failover chain — no election code.**
Boboe 2 decomposes work, assigns or approves claims, maintains the task + progress ledgers, and runs liveness sweeps on a cron. Failover: `coordinator.md` in the repo names the chain (Boboe 2 → Boboe 1 → Boboe 3 …); if the coordinator's heartbeat is stale >15 min, the next in line posts a takeover notice in the ledger and Slack. No Raft, no voting — a shared clock plus a stale-heartbeat rule.

**R3. Claim-before-act with git as the atomic primitive + leases.**
Before touching any shared work, an agent must hold a claim: `git pull`, create `fleet/claims/<task-id>.json` containing `{agent, lease_token, claimed_at, expires_at, status}`, `git push`. Push conflicts = someone else claimed first = back off and pick another task (this is free compare-and-set). Claims carry a 60-minute lease with renewal by pushing a new expiry; coordinator reclaims expired claims to READY. Every externally-visible action carries an idempotency key (`<task-id>-<attempt>`); re-running a completed task returns the existing artifact hash instead of redoing work.

**R4. Enforce loop discipline mechanically, not by norm.**
Hard rules in every agent's standing instructions: (a) handoff envelopes are JSON with `hops_remaining` (default 5, decrement per handoff, stop at 0); (b) reply in Slack only when named, assigned, or signalled — with a per-agent cap of ~20 substantive messages/hour and exponential backoff on breach; (c) no agent posts in a thread where the last two messages are its own without new external input (breaks ping-pong); (d) global per-task step budget (e.g., 200 tool calls) that aborts to the coordinator. These are cheap string/count checks implementable in the watch-loop cron, no new infrastructure.

**R5. Two ledgers + heartbeats for liveness.**
`fleet/ledger/task-ledger.md` (what must be true for the current mission) and `fleet/ledger/progress-ledger.md` (per-task: status, owner, last-touch, blockers), both single-writer (coordinator only). Each agent pushes a heartbeat (`{"ts": <epoch>, "status": "ok|working <task-id>|stuck"}`) every 5 minutes; coordinator's cron sweeps for stale heartbeats (>15 min = alert, >30 min = treat as dead, reclaim its claims). Stuck detection: CLAIMED task with no ledger progress update for 2× its estimate → coordinator pings the owner once, then reclaims.

**R6. Schema-typed artifacts and worktree isolation for parallel dev work.**
Define the output schema for each recurring artifact type (research brief, reel draft, code patch, QA verdict) once — as a Markdown section template or JSON Schema in the repo — and require validation before a task can be marked DONE. For code tasks, agents work in per-agent git branches/worktrees and open merge requests; the coordinator merges after verification. Isolation first, merge checkpoints second, chat never as the merge mechanism.

---

## Top 3 failure modes to design against

1. **Coordination loops / agent ping-pong (already observed at ~850 wakes/hour).** Two agents (or one agent and its own watch-loop) wake each other indefinitely via Slack mentions, each message re-triggering the other. Defenses: hop-bounded handoff envelopes, per-agent message rate caps with backoff, the no-self-thread rule, and a global per-task step budget. Treat this as the fleet's #1 risk — it wastes the most compute and is the failure most likely to recur.

2. **Duplicate/conflicting work from stale state.** Two agents claim the same task, or an agent acts on a Slack message that the ledger has already superseded. Defenses: claim-before-act via atomic git push, lease expiry + coordinator reclamation, idempotency keys, and the single-writer principle on ledgers (repo state is always fresher than chat).

3. **Silent stall — work stops with no one noticing.** An agent dies mid-claim, its lease never expires visibly, and the task sits in CLAIMED forever while the fleet looks busy. Defenses: 5-minute heartbeats, coordinator liveness sweep, lease expiry with automatic requeue to READY, and the progress ledger as a single pane where Jack can see "every agent accounted for, every task moving."
