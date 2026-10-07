# Agent Specialization & Swarm Organization — Deep Research
*Boboe 3, 2026-10-07. For the 12-agent AgentNet fleet (Boboe Prime + Boboes 1–11).*

## Executive summary

The research consensus is clear: **specialized agents with focused prompts outperform generalists**, but the coordination layer matters more than the role list. The failure mode of real multi-agent systems is almost never "wrong roles" — it is coordination breakdown (37% of production failures per Galileo research), duplicate work, and state inconsistency. The recommended design for our 12-agent fleet is:

1. **Hybrid topology** — a single orchestrator owns planning and the task registry; execution happens in small flat cells or a self-service claim pool.
2. **Role-based specialization with a flex pool** — 8 agents hold standing specialties, 4 stay generalist and claim work dynamically.
3. **A commitment ledger** (task registry) as the single source of truth — chat is for discussion, the ledger is for who-owns-what. Claims are atomic with lease expiry.

---

## 1. Specialization patterns in multi-agent systems

### 1.1 The three axes of specialization

**Role-based** (what the agent *does* in a workflow): researcher → coder → reviewer → writer. This is the dominant pattern in production frameworks (CrewAI crews, AutoGen engineer-critic pairs). A "code reviewer" agent with a review-focused system prompt measurably outperforms a generalist asked to "write and review code." Roles create a pipeline with natural quality gates.

**Capability-based** (what the agent *can do* — tools, permissions, models): e.g., one agent holds the GitHub token and merge rights, another holds browser/search tools, another has no external-write permissions. This maps to least-privilege security and cost optimization (cheap models for triage, frontier models for planning). The FuckClaw architecture documents this explicitly: different system prompts, tools, and memory retrieval patterns per role.

**Domain-based** (what the agent *knows*): finance, infra/telemetry, comms, research. Best when the fleet serves distinct long-lived domains rather than one-off tasks.

**Recommendation for our fleet:** lead with **role-based** specialization (it matches how Jack assigns work — research this, build that, review this), layer **capability-based** restrictions on top for safety (not every agent needs merge rights or credential access), and keep domain knowledge in shared memory rather than hard-coding domain agents — our domains shift too fast.

### 1.2 The role catalog that works in practice

Across CrewAI production crews, AutoGen patterns, the Hive Mind skill set, and FuckClaw's supervisor architecture, the same roles recur:

| Role | Job | Why it earns its slot |
|---|---|---|
| Orchestrator / Dispatcher | Decompose work, route tasks, resolve conflicts, synthesize | Single decision point; prevents "everyone waits for someone" |
| Researcher | Search, read, summarize, cite | Separating research from execution reduces confusion downstream |
| Builder / Coder | Implement from specs | Focused implementation without requirements-research drag |
| Reviewer / Critic | Adversarial check of outputs before they ship | Catches errors earlier; must be a *different* agent than the builder (self-verification is a known anti-pattern — the verifier re-affirms instead of verifying) |
| Planner / Architect | Task decomposition, system design | Keeps builders from thrashing on ambiguous specs |
| Tester / QA | Validation, test execution | Independent pass/fail signal |
| Writer / Synthesizer | Docs, reports, summaries | Turns parallel outputs into one coherent deliverable |
| Scout / Monitor | Watch telemetry, detect anomalies, heartbeat checks | Continuous background function, not task-driven |
| Memory / Librarian | Consolidate findings, maintain shared knowledge | Prevents re-researching solved problems |

**What doesn't work:** overspecializing into roles with no steady workload (an "optimizer" agent that sits idle), or splitting roles so finely that handoff overhead exceeds the work (the hybrid-MAS benchmark showed 6.2x token overhead when hierarchy *and* lateral sharing were both maxed out).

### 1.3 Key finding: separate generation from verification

Multiple sources converge on this: the agent that produces an output must not be the agent that approves it. Cogentic's prove-verify loop (orchestrator → provers → adversarial verification → verified ledger) produced novel results on open problems precisely because verification was structurally independent. For our fleet: **no agent marks its own work done** — the reviewer or orchestrator confirms.

---

## 2. Work routing: how tasks get to agents

### 2.1 The patterns

**Central dispatcher (orchestrator-workers).** One agent breaks work down and assigns it. Easiest to debug, clear audit trail, predictable. Cost: the dispatcher is a bottleneck and a single point of failure; every delegation adds latency. Best for: compliance-auditable work, spec-driven builds.

**Contract Net / auction.** A broker announces tasks; agents bid based on capability match and current load; highest bid wins. Theoretically optimal allocation (CBBA is the classic decentralized algorithm). Cost: highest coordination overhead of all patterns — needs a capability registry, bid scoring, negotiation rounds. Only worth it with genuinely heterogeneous agents.

**Blackboard.** Agents post/read from a shared workspace and self-select work matching their role. Low coordination cost, very resilient. Cost: no global owner — can produce conflicting decisions and it's hard to reconstruct why something happened.

**Handoff chains (Strands Swarm pattern).** Agents hand work to each other autonomously based on expertise, sharing full context. Good for exploratory work where no one knows the right sequence in advance.

**The hybrid that survives contact with reality.** The strongest empirical guidance: *"Orchestrate the must-run steps; within each phase, let agents self-organize — but don't let an agent jump tiers before the prior tier completes."* A benchmark (AdaptOrch on SWE-bench Verified) found adaptive topology selection beat the best fixed topology by 22.9%, with the router choosing hybrid 62% of the time. Microsoft's production healthcare deployment uses exactly this: central orchestrator for patient flow, autonomous specialist agents underneath.

### 2.2 Recommended routing design for our fleet

**Two-lane routing:**

- **Lane 1 — Orchestrated (big/complex work).** Boboe Prime decomposes the mission into tasks with explicit completion criteria, writes them to the task registry as PENDING, and assigns or opens them for claiming. Reviewer gates each phase before the next begins. Used for: multi-day projects, anything touching credentials/infra, anything Jack explicitly assigns.
- **Lane 2 — Claim pool (routine/standing work).** Small, well-understood tasks (Slack replies, telemetry checks, cron maintenance, doc updates) sit in the registry as PENDING with a role tag. Any agent with a matching role claims them. No dispatcher involvement. Used for: the daily operating rhythm.

**Routing rules:**
1. Every task has exactly one owner at a time (see §3).
2. Tasks carry: `id`, `title`, `role_tag`, `state`, `owner`, `claimed_at`, `lease_expires`, `completion_criteria`, `depends_on`, `idempotency_key`.
3. The orchestrator may reassign; workers may release a claim back to PENDING (never silently abandon).
4. Cross-agent requests go through the registry or a direct @-mention with a task id — never "someone should handle this" in open chat.
5. Separate *communication* (Slack discussion) from *coordination* (registry state). Chat proposes; the registry disposes.

---

## 3. Duplication prevention: the commitment ledger

### 3.1 Why chat alone fails

A Towards Data Science experiment put it sharply: when multiple coding agents talk in chat, they still duplicate work and get task order wrong. *"If an agent says 'I'll build the items file,' I record that as a commitment instead of leaving it buried in the chat."* A commitment ledger — not chat — is the coordination primitive. (Their caveat is honest and important: a ledger improves coordination state but can't force an agent to follow through. Pair it with lease expiry.)

### 3.2 The mechanism: task registry with atomic claims

Borrowed from distributed worker queues, adapted for our fleet:

**State machine:** `PENDING → CLAIMED → IN_PROGRESS → DONE`, with `FAILED → PENDING` (retry) and claim expiry `CLAIMED → PENDING` on lease timeout.

**Atomic claim** (the core anti-duplication primitive): a claim is a single atomic operation — check state is PENDING *and* set owner + lease in one step. In our implementation (file or SQLite in the fleet repo), use file locking (`flock`) or a compare-and-swap on the registry. Two agents claiming simultaneously: one wins, the other sees CLAIMED and moves on.

**Leases + heartbeats:** every claim carries `lease_expires` (e.g., 15 min for interactive work, 60 min for long builds). The owner refreshes the lease with a heartbeat. If the lease lapses, any agent may reclaim — this handles crashed/stalled workers without manual intervention. (Matches the fleet's existing 10-minute heartbeat norm; make it structural, not social.)

**Idempotency keys on external actions:** every Slack reply, every deploy, every email carries a stable key (e.g., `slack-reply:<thread_ts>:<agent>`). Before acting, check the key in the ledger: *attempted* vs *confirmed*. Timeouts trigger **verification, not blind retry** — read the thread to see if the reply landed before re-sending. (This is exactly the pattern that already prevents our duplicate Slack replies; formalize it.)

**Path reservation for code work:** when a task touches files, the claim reserves those paths. A second task needing overlapping paths is serialized, not parallelized. Merges go through a single-lane queue with automated tests; fail closed on conflict.

**Practical implementation for us** (concrete):
- `~/workspace/fleet-telemetry/tasks/registry.json` (or SQLite) — the ledger. Committed to the repo so it survives restarts and is auditable.
- Tiny CLI: `fleet task claim <id>`, `fleet task done <id> --result <summary>`, `fleet task release <id>`, `fleet task heartbeat <id>`, `fleet task list --state PENDING`.
- The orchestrator's cron (or a hook) sweeps expired leases every 5 minutes and returns them to PENDING.
- A `seen`/dedup rule: before starting *any* external action, the agent checks the ledger for a matching idempotency key.

### 3.3 What this fixes in our current operation

Our recent incidents map directly onto missing ledger pieces: duplicate Slack replies (no idempotency check before retry), cron workers racing on the same inbox files (no atomic claim), hook workers and cron both answering the same mention (two coordinators, no single owner). The Muse Wall relay + backstop-cron design already moves in this direction; the registry makes it explicit and general.

---

## 4. Team topologies: tradeoffs for 10–15 agents

| Topology | Latency | Reliability | Debuggability | Verdict for 12 |
|---|---|---|---|---|
| Centralized (hub-and-spoke) | Hub bottleneck; delegation round-trips add up | Single point of failure | High — all traffic through one point | Too brittle as the *only* structure |
| Hierarchical | Layer latency multiplies | Sub-teams autonomous; mid-coordinators can fail | Moderate — handoffs hard to trace | Good for long multi-stage work |
| Peer-to-peer / mesh | Low per-hop | No central failure; emergent failures invisible in testing | Very hard (36.94% of MAST failures are coordination-type) | Only for 2–4 agent clusters |
| Swarm (stigmergic) | — | Resilient by design | Emergent behavior hard to predict | Overkill; unpredictable for Jack's taste |
| **Hybrid** | Moderate | Best balance | Moderate | **Recommended** |

**Recommended topology for the fleet — "orchestrated cells":**

```
                    ┌─────────────┐
                    │ BOBOE PRIME │  Orchestrator: decomposes, routes,
                    │ (dispatcher)│  owns registry, final synthesis
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ BUILD CELL   │ │ RESEARCH CELL│ │  OPS / FLEX  │
   │ lead: Boboe 4│ │ lead: Boboe 2│ │  POOL        │
   │ Boboe 5      │ │ Boboe 3      │ │ Boboe 8–11   │
   │ Boboe 1 (QA) │ │ Boboe 7 (syn)│ │ Boboe 6(sct) │
   └──────────────┘ └──────────────┘ └──────────────┘
        flat/peer        flat/peer       claim-based
```

- The orchestrator plans and routes; it does not micromanage inside cells.
- Cells are flat peer groups of 2–4 (the size where peer coordination actually works).
- The flex pool self-organizes around the claim pool for routine work.
- The reviewer/QA function sits *outside* the build cell (Boboe 1 reviews build-cell output; never reviews its own).
- Deputy: Boboe 1 can assume orchestration if Prime is down (no single point of failure).

**Why not pure hierarchy?** Approval latency. Jack wants speed ("answer in Slack immediately"). Two tiers max: orchestrator → workers. No middle-management layer at 12 agents.

**Why not pure flat?** The research is blunt: beyond a small cluster, adding peer agents buys noise, not reliability; nobody owns sequencing; verification collapses into self-affirmation.

---

## 5. Real production examples

- **CrewAI role-based crews** — in production for content pipelines (research → write → edit → publish), customer support triage (classify → retrieve → respond), data analysis workflows, and code review systems. The pattern that ships: 3–5 agents, declarative roles, handoffs managed by the framework.
- **Anthropic's multi-agent research system** — orchestrator dispatching parallel researcher subagents with shared context; the reference implementation for "one planner, many parallel specialists."
- **Microsoft healthcare deployment** — hybrid in production: central orchestrator manages patient flow while specialist agents handle tasks autonomously. The template for our orchestrated-cells design.
- **AutoGen conversational agents** — agents critique each other through structured dialogue to converge on results; useful inside our cells for the builder↔reviewer loop.
- **Cogentic (proof discovery)** — orchestrator + parallel provers + adversarial verification + verified ledger; produced novel results on open problems. Direct precedent for our commitment ledger + independent verification.
- **FuckClaw supervisor architecture** — supervisor delegating to 7 roles (researcher, coder, reviewer, writer, planner, memory manager, devops), chosen for context isolation and cost optimization (cheap models for simple subtasks).
- **Devin / SWE-agent lineage** — planner-executor with tool-use loops; the "one strong planner + executor" pattern validated for long-horizon coding tasks.

---

## 6. Concrete recommendations

### (a) Recommended role structure for our 12 agents

| Agent | Standing role | Notes |
|---|---|---|
| Boboe Prime | **Orchestrator** | Owns task registry, decomposes missions, routes, synthesizes. Final say on conflicts. |
| Boboe 1 | **Reviewer / Deputy** | Adversarial QA on build output; backup orchestrator. Never reviews own work. |
| Boboe 2 | **Research lead** | Deep research, investigation, citations. Cell lead for research cell. |
| Boboe 3 | **Researcher / Verifier** | Research + independent verification of claims (fits current research assignment). |
| Boboe 4 | **Build lead** | Implementation, installs, deploys. Cell lead for build cell. |
| Boboe 5 | **Builder** | Implementation partner; pair-executes with Boboe 4 on large builds. |
| Boboe 6 | **Scout / Monitor** | Telemetry watch, anomaly detection, fleet health checks. Continuous function. |
| Boboe 7 | **Writer / Synthesizer** | Docs, reports, summaries, Feed posts. Turns parallel outputs into one deliverable. |
| Boboe 8–11 | **Flex pool** | Generalists. Claim routine tasks from the pool; temporarily attach to cells per mission. |

Rules: roles are *standing defaults, not cages* — any agent can take any task, but the role tag routes work to the right default owner. Revisit quarterly or when workload shifts.

### (b) Work-routing design

1. **Single task registry** (`tasks/registry.json` in fleet-telemetry) — the only place task ownership lives.
2. **Two lanes:** orchestrated (Prime decomposes; reviewer gates phases) for missions; claim pool (role-tagged PENDING tasks, self-service) for routine ops.
3. **Task schema:** id, title, role_tag, state, owner, lease_expires, completion_criteria, depends_on, idempotency_key.
4. **Chat proposes, registry disposes.** @-mentions reference task ids. No "someone should do X" without a registry entry.
5. **Reviewer gate:** phase outputs are approved by Boboe 1 (or Prime) before the next phase starts; builders never self-certify.

### (c) Duplication-prevention mechanism

1. **Atomic claims** via `flock`-guarded registry updates (or SQLite); exactly one owner per task.
2. **Leases + heartbeats** (15 min interactive / 60 min long tasks); expired leases auto-return to PENDING via a 5-min sweeper.
3. **Idempotency keys** on every external action; timeouts trigger verification (read the thread / check state) before retry — never blind re-send.
4. **Path reservation** for code tasks; serialized single-lane merge queue with automated tests, fail closed.
5. **Release, don't abandon:** owners return claims to PENDING explicitly; silent drops are a reviewable offense.

### Sequencing (proposed)

1. Build the registry + CLI (Boboe 4/5, ~1 day).
2. Stand up the sweeper + heartbeat convention (Boboe 6).
3. Migrate Slack-reply handling to idempotency keys (already half-done via the backstop design).
4. Pilot orchestrated-cells on the next multi-day mission; retro after.

## Sources

- Multi-agent architecture patterns & specialization: https://github.com/techmahato/claude-zero-to-hero/blob/HEAD/16-multi-agent-systems/fundamentals.md
- Hive Mind queen-worker coordination: https://github.com/aglz/agl-hostman/blob/HEAD/.claude/skills/hive-mind-advanced/SKILL.md
- FuckClaw supervisor + 7 roles: https://github.com/levilyf/fuckclaw/blob/HEAD/docs/architecture/15-multi-agent.md
- Auction/marketplace routing & hybrid production: https://medium.com/@hemachowdary1001/multi-agent-systems-the-definitive-architecture-guide-for-ml-ai-engineers-acfb6c8ea848
- Contract Net Protocol & orchestration: https://www.theprotec.com/blog/multi-agent-ai-systems-autonomous-agents-collaborate-complex-tasks/
- Commitment ledger vs chat: https://towardsdatascience.com/multi-agent-coding-isnt-enough-agents-need-a-commitment-layer/
- Production MAS failures (37% coordination): https://pub.towardsai.net/why-multi-agent-systems-fail-in-production-88146068ae05
- Topology tradeoffs & AdaptOrch: https://www.augmentcode.com/guides/multi-agent-orchestration-architecture-guide
- Hybrid that survives (orchestrate must-runs): https://medium.com/@himanshubhoir/self-organizing-multi-agent-systems-came-out-cheaper-than-orchestrated-thats-the-problem-821757656429
- Multi-worktree path reservation: https://dev.to/raylabs/handling-git-merge-conflicts-in-multi-agent-worktrees-1em8
- CrewAI production crews: https://medium.com/@aravind.tadi2000/building-intelligent-ai-teams-with-crewai-a-practical-guide-to-multi-agent-orchestration-681863ae7a9c
- AutoGen vs CrewAI patterns: https://medium.com/@yugalnandurkar5/multi-agent-systems-in-action-a-deep-dive-into-autogen-and-crewai-b29b90576f4f
