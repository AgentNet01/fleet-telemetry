# Long-Running Autonomous Agent Systems — Research Report

**Date:** 2026-10-07
**Scope:** Proven patterns for running AI agents autonomously for days to weeks with no human oversight — staying on task, recovering from failures, making steady progress.
**Sources:** Web research across durable-execution platforms, production agent postmortems, and real-world systems (Devin, Lindy, Replit Agent, open-source projects). Links inline.

---

## Executive summary

The industry has converged on a boring but effective answer: **long-running agents are a state-management and recovery problem, not a reasoning problem.** The systems that survive days-to-weeks runs share the same skeleton:

1. **Durable execution substrate** — completed steps are recorded; on crash the engine replays from the log instead of re-executing (Temporal, Inngest, Trigger.dev, Restate).
2. **Externalized state** — the goal, plan, and findings live in files/databases the agent re-reads, not only in conversation history (plan.md / findings.md / progress.md pattern; todo-list recitation).
3. **Supervisor + watchdog** — one coordinator owns routing (free peer chat creates loops); a zero-LLM watchdog detects stalls, loops, and drift and restarts or escalates.
4. **Classified failure handling** — transient → retry with backoff; persistent → bounded retries then dead-letter queue; non-retryable → fail fast.
5. **Observability by default** — structured logs with job/trace IDs, heartbeats, alerts on stuck jobs.

Everything below is a concrete elaboration of these five.

---

## 1. Architecture blueprint (days → weeks of autonomy)

### 1.1 Durable execution substrate

Split work into two function types (the Temporal model):

- **Workflow (orchestration logic)** — must be *deterministic*: no direct I/O, no `random()`, no wall-clock reads inside it. The engine re-runs it from the start on recovery, feeding back recorded results, so it fast-forwards to where it left off.
- **Activity (side-effecting step)** — one model call, one tool call, one DB write. The engine runs each *once*, persists the result, and on replay hands back the recorded result instead of re-running. Attach retry policies with exponential backoff + jitter per activity.

Consequences: a crash after step 29 of 30 resumes at step 30 — you never re-pay for or re-execute steps 1–29. Durable timers let a workflow "sleep 3 days" without consuming resources; signals/queries let you poke a running workflow.

Pragmatic alternative if Temporal is too heavy: **cron + inbox + file checkpoints** (poll a durable inbox, checkpoint after each unit of work, coalesce overlapping runs). This works but has sharp edges — a run that always burns its full timeout starves the cadence, and overlapping workers race into duplicate side effects. If you go this route, add idempotency keys and make "no work found" exit in seconds.

### 1.2 State management — three tiers, one rule

**The rule:** maintain an explicit *structured* state object (file counts, record IDs, confirmation tokens, balances) updated only by *verified tool output*, never by model paraphrase. The model reads this object each turn instead of re-deriving it from context. Memory may be lossy (narrative continuity); belief about the world may not be.

**Tier 1 — Durable workflow state.** Checkpoint after every graph node / workflow step (LangGraph checkpointer to SQLite/Postgres/Redis; Temporal event history). Supports pause/resume across days and replay for debugging.

**Tier 2 — Working files (the three-file pattern).** Minimum viable cognitive scaffolding:
- `plan.md` — goal, decomposition, current hypothesis, "I am here", key decisions. Re-read before any significant decision. Antidote to attention decay.
- `findings.md` — evidence and discoveries from the environment. Separates signal from ephemeral tool output.
- `progress.md` — chronological action log (what was read, run, observed). Episodic memory for session restarts.
- Principle: **one fact lives in one file.** Status in plan.md, findings in findings.md, actions in progress.md. Multiple sources of truth confuse the agent.

**Tier 3 — Long-term memory.** Vector/semantic store (pgvector, Mem0-style) for cross-session knowledge: profiles, facts, playbooks. Recalled into the system prompt, not kept in the hot window.

**Context engineering mechanisms that beat overflow and goal loss:**
- **Compaction with custom instructions** — summarization is a named, testable operation; test that summaries preserve the facts downstream plans depend on.
- **Todo-state recitation** — rewrite a `todo.md` every few turns; re-reading pushes the plan into recent attention (Manus pattern; Claude Code's todo list; Deep Agents' `write_todos`). Worth the token cost on long multi-step tasks, less capable models.
- **Keep standing context short** — reloadable context files (CLAUDE.md-style) under ~200 lines; each reload is a fixed attention tax.
- **Sub-agent decomposition** — fan out bounded sub-tasks with fresh contexts rather than growing one mega-session.

### 1.3 Scheduling layer

Match the tool to the job:

| Need | Tool |
|---|---|
| Multi-step, crash-safe, days-long processes | Durable execution engine (Temporal / Inngest / Trigger.dev / Restate) |
| Periodic checks ("every N minutes") | Cron with run-coalescing; worker must exit fast when idle |
| React to external events (webhook, message) | Event-driven functions (Inngest events, queue consumers) |
| "Wake me in 3 days unless X" | Durable timers / sleeps, not a DB table + cron + state machine |
| 1–2 step jobs safe to repeat | Plain queue (SQS, BullMQ, QStash) — don't buy a workflow DSL you don't need |

For a VM-based swarm: a **durable inbox per agent** (append-only files or a queue table) + a **scheduler that rehydrates on boot** (persist job list; on restart, restore in-flight jobs and re-enqueue) is the minimal viable backbone. Pair with per-agent **heartbeat files** (timestamp written every cycle); a watchdog flags agents silent past a threshold.

### 1.4 Supervision & watchdog layer

- **Supervisor pattern over peer chat.** One coordinator decomposes the goal, assigns subtasks, collects results. Free agent-to-agent chat degrades into untracked side channels and loops. Peer/mesh setups need a much stronger message contract to stay sane.
- **Zero-LLM stall watchdog.** A cheap deterministic process (not a model call) watches heartbeats and phase timeouts; on stall it re-enqueues the work and pages. No LLM needed to notice "nothing happened for 10 minutes."
- **Loop detection.** Maintain a hash set of `MD5(tool_name + canonical_arguments)`; if an identical action repeats, terminate. Enforce a hard turn/step ceiling per task.
- **Intermediate-state evaluation.** Put a lightweight grader *between* pipeline stages (a small local model is enough): "does this handoff look sane?" — binary, fast. Halts garbage before the next node builds on it. Catches the "200 OK with semantically garbage payload" failure class.
- **Drift monitor with restart.** Research finding: checking trajectory adherence ~75% through a run and restarting the worst-drifting third lifted success +8.8pp — no model changes, just detecting off-track runs and fresh-starting before drift compounds. Runtime monitors beat init-time prompt engineering for drift that accumulates *during* execution.
- **Human-in-the-loop gates (calibrated).** Require approval for irreversible actions (payments, deletions, production changes), low-confidence output, compliance steps. Track the **intervention rate** (share of output a human still touches) and widen autonomy as it falls — ~74% of teams run HITL for the first 60–90 days. Every human correction is labeled training/eval data.

### 1.5 Failure handling — classify, then act

Split every failure into three classes:

1. **Transient** (API timeout, rate limit, brief network blip) → retry with exponential backoff + jitter.
2. **Persistent** (downstream outage longer than the retry window) → stop after a bounded count; park in a **dead-letter queue** with payload, error class, retry history, lease timestamps, idempotency key. Operators inspect before replaying — the DLQ is for inspection, not disappearance.
3. **Non-retryable** (invalid input, schema violation, missing permission) → fail fast, never requeue.

Additional rules:
- **Idempotency keys on every side-effecting step.** Steps can rarely run twice; anything with real-world effects (send, charge, write) must be safe to repeat.
- **Re-fetch before consequential actions.** Fresh read immediately before a write/payment/delete — the agent equivalent of optimistic locking.
- **Bound loop depth against unverified assumptions.** N iterations without a ground-truth checkpoint → force re-grounding or escalate.
- **Per-phase timeouts** (e.g., 120s) with failover, not just global timeouts.

### 1.6 Drift prevention (keeping the mission over long horizons)

1. Goal as mutable artifact (plan.md / todo.md), re-read before decisions and rewritten frequently so it stays in recent attention.
2. Structured note-taking outside the window; reload after every compaction/restart.
3. Planner–critic separation: one pass proposes, a second pass (or cheap model) validates the plan before execution; plan-then-execute with explicit termination criteria.
4. Periodic self-review: the agent scores its own trajectory against the plan; watchdog restarts drifted runs.
5. Forced-compression tests: after any summarization, verify the agent can still state the goal and next step — the most dangerous failure is an agent that "completes" a task it doesn't understand.

### 1.7 Observability (non-negotiable)

- Structured logging with `job_id` + `trace_id` on every tool call, model response, retry.
- OpenTelemetry traces; replayable traces (LangSmith / Langfuse / Arize style).
- Metrics: queue depth, job age, retry count, lease-expiry recoveries, duplicate executions, step latency, DLQ volume, stuck-job time vs. SLO.
- Alerts on: old in-progress jobs, growing DLQ, workers missing heartbeats.
- Transition log: every state-machine transition recorded — the audit trail that makes postmortems possible.

### 1.8 Reference topology

```
                    ┌─────────────────────────────────────┐
                    │        DURABLE EXECUTION ENGINE     │
                    │  (Temporal / Inngest / Trigger.dev) │
                    │  workflows (deterministic) +        │
                    │  activities (retry policies)        │
                    └──────────────┬──────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        │                          │                          │
┌───────▼────────┐      ┌──────────▼─────────┐     ┌──────────▼─────────┐
│  SCHEDULER     │      │   SUPERVISOR AGENT │     │  WATCHDOG (no LLM) │
│  cron + events │─────▶│  plan.md / tasks   │◀────│  heartbeats,       │
│  durable timers│      │  assigns subtasks  │     │  stall/loop detect│
└────────────────┘      └─────────┬──────────┘     └──────────────────┘
                                  │ fan-out
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ WORKER 1 │ │ WORKER 2 │ │ WORKER 3 │  ← fresh context per task
              │ sandbox  │ │ sandbox  │ │ sandbox  │    checkpoint after
              └────┬─────┘ └────┬─────┘ └────┬─────┘    each unit of work
                   │            │            │
                   └────────────┼────────────┘
                                ▼
                    ┌───────────────────────┐
                    │ INTERMEDIATE GRADER   │──▶ DLQ (inspect → replay)
                    │ (small model, binary) │
                    └───────────────────────┘

STATE (three tiers): workflow checkpoints (Postgres/SQLite) │ plan/findings/progress files │ vector long-term memory
OBSERVABILITY: structured logs + traces + metrics + alerts on stuck jobs / missed heartbeats
GATES: HITL on irreversible actions; intervention-rate metric drives autonomy expansion
```

---

## 2. Technologies (with links)

### 2.1 Durable execution / orchestration

- **Temporal** — the heavyweight: workflows-as-code with deterministic replay, durable timers, signals/queries, polyglot SDKs (Go, Java, TS, Python, .NET). Self-host (MIT) or Temporal Cloud. Choose when workflows are genuinely complex, long-lived, multi-language. Operational overhead is real (cluster + workers). Background: https://runtimewire.com/article/temporal-raises-550m-12-55b-ai-durable-execution · Agent guide: https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal · Skill reference: https://github.com/bendourthe/nexus-hub/blob/HEAD/catalog/skills/orchestration/temporal-orchestration/SKILL.md · Curriculum: https://github.com/ai-engineering-curriculum/agentic-ai-engineer-learning/blob/HEAD/lessons/mod-207-productionizing-agents/02-durable-execution.md
- **Inngest** — serverless-first, event-driven durable functions (`step.run`, `sleep`, `waitForEvent`); code lives in your existing app, Inngest orchestrates over HTTP. Shortest path from a Next.js/serverless app. Comparison: https://github.com/inngest/website/blob/HEAD/content/blog/best-job-queue-alternatives.mdx · Alternatives roundup: https://hookdeck.com/webhooks/platforms/inngest-alternatives
- **Trigger.dev** — open-source (Apache 2.0), TypeScript-first; tasks run on managed compute with no serverless timeout — good for long compute-heavy agent steps. 2026 comparison: https://appstackbuilder.com/blog/inngest-vs-trigger-dev-vs-temporal-2026 · vs table: https://github.com/lilienblum/tako/blob/HEAD/website/src/content/blog/tako-vs-inngest-and-trigger.md
- **Restate** — lightweight durable execution, single binary, durable handlers + virtual objects (stateful entities keyed by ID). Less ceremony than Temporal.
- **AWS Step Functions / Azure Durable Functions** — if already deep in that cloud; JSON state machines are verbose.
- Quick decision rule (2026 consensus): existing serverless app → **Inngest**; long-running compute-heavy agent jobs → **Trigger.dev**; polyglot enterprise at scale → **Temporal**; single-step repeatable jobs → plain queue. Sources: https://github.com/davidbijl/ctoc/blob/HEAD/skills/saas/inngest-jobs/SKILL.md · https://github.com/invictusprime7/unison-tasks-official/blob/HEAD/WORKFLOW_ORCHESTRATION_COMPARISON.md

### 2.2 Agent frameworks (stateful)

- **LangGraph** — the default for stateful, long-running agents as directed graphs; cyclic graphs allow self-correction loops; built-in checkpointing (SQLite/Postgres/Redis) with pause/resume and time-travel debugging; interrupts for human approval. Overview: https://opendatascience.com/ai-agent-orchestration-frameworks-github/ · Deep audit: https://github.com/samjuniors/samjuniorsos/blob/HEAD/doc/AUDIT%2003%20—%20Open-Source%20Reference%20Lab.md
- **Pydantic AI + Temporal** — type-validated agents wrapped for durable execution in one wrapper (`TemporalAgent`): https://temporal.io/blog/build-durable-ai-agents-pydantic-ai-and-temporal
- **OpenHands** — open-source software-agent SDK/runtime (sandboxed); pairs with LangGraph for orchestration. Example stack: https://github.com/ohama/langgraph_openhands
- **omni-agent** — example production-style stack: LangGraph routing + Temporal durable execution + LiteLLM 6-tier model cascade + Mem0/pgvector memory: https://github.com/rajhodedara/omni-agent

### 2.3 State & memory

- **PostgreSQL / SQLite / Redis** — checkpoint stores (LangGraph pluggable checkpointers; Temporal backing store).
- **pgvector (Supabase)** — episodic vector storage for long-term memory.
- **Mem0** — semantic/conversational memory layer.
- **LiteLLM** — model gateway with failover cascades across providers (cost + resilience); also standardizes the agent↔model interface.

### 2.4 Queues & scheduling

- **BullMQ / SQS / Sidekiq / QStash / Cloudflare Queues** — for simple 1–2 step repeatable jobs.
- **Cron with coalescing** — for periodic checks; ensure idle runs exit in seconds and overlapping runs coalesce rather than race.
- **Durable timers/sleeps** (Temporal/Inngest/Trigger.dev) — replace "DB table + cron + state machine" for future wakes.

### 2.5 Observability

- **LangSmith / Langfuse / Arize** — trace-level agent observability, replay.
- **OpenTelemetry** — traces across queue/worker/tool boundaries.
- Metrics to track: queue depth, job age, retry count, DLQ volume, stuck-job time vs. SLO, heartbeat gaps, duplicate executions, intervention rate.

### 2.6 Model strategy

- Large model for planning/supervision, small fast model for classification and intermediate grading (cost control).
- Fallback chains across providers (Claude ↔ GPT ↔ Gemini) via LiteLLM.
- Keep per-task tool count small (5 focused tools beat 20).

---

## 3. Failure modes & mitigations

| # | Failure mode | What it looks like | Mitigation |
|---|---|---|---|
| 1 | Cascading errors | One bad tool call poisons the next 10 steps; agent builds confidently on a wrong answer | Step-level validators; confidence thresholds; rollback to last-known-good; intermediate grader between stages |
| 2 | Context window decay | Agent "forgets" early constraints after ~20 steps; lost-in-the-middle | plan.md/todo.md recitation; compaction with tested summaries; sub-agent decomposition; keep standing context <200 lines |
| 3 | Cyclic loops | Two tools return conflicting errors; agent flip-flops 80 turns | Action-hash set (terminate on repeat); hard turn ceilings; bounded retries then DLQ |
| 4 | Tool misuse | Right tool wrong args, or wrong tool entirely | Strict JSON schemas; narrow per-task tool scoping (5 tools, not 20); tool-use evals |
| 5 | Prompt injection | Untrusted doc/web content hijacks instructions | Treat all tool-sourced content as data; instruction hierarchy; sanitization; isolated per-source execution |
| 6 | Non-idempotent side effects | Same email/payment sent twice after crash retry | Idempotency keys on every side-effecting step; re-fetch state before consequential actions |
| 7 | Silent stalls | Agent quietly stuck; nobody notices for hours/days | Heartbeats + zero-LLM watchdog; alerts on old in-progress jobs and missed heartbeats |
| 8 | Goal drift | Trajectory veers; agent "completes" the wrong thing | Mutable goal artifacts; runtime drift monitor with restart; forced-compression tests; planner–critic split |
| 9 | State corruption on recovery | Replay breaks (non-deterministic workflow code) | Deterministic workflows only (no `datetime.now()`/`uuid()` inside); versioning for safe code updates |
| 10 | Observability gaps | Failure undetected for days; no reproduction | Structured logs with job/trace IDs; replayable traces; transition log as audit trail |
| 11 | Duplicate side effects from races | Cron + hook + retry all answer the same mention | Single ownership per action; idempotency; coalesce overlapping runs; check-before-act (read thread before replying) |
| 12 | Over-engineering under autonomy | Eager agent builds abstractions nobody asked for | Smallest thing the spec forces; small reversible testable changes; surface ≠ build |

Sources: https://www.metacto.com/blogs/ai-agent-failures-and-how-to-avoid-them · https://github.com/dip4k/senior-engineer-to-ai-engineer-roadmap/blob/HEAD/use-cases/use-case-04-failure-modes-defense.md · http://dev.to/aiexplore369zoho/ai-agents-dont-fail-at-reasoning-they-fail-at-state-1dbl · https://dev.to/imversion_tech/long-running-ai-agents-efficient-asynchronous-workflow-strategies-4ihp · https://www.codelevate.com/blog/context-engineering-for-ai-agents-why-your-agent-fails-in-production

---

## 4. Real-world examples — what works

### Devin (Cognition)
Sandboxed autonomous agent: each instance gets its own cloud VM with shell, browser, code editor. Loop: read task → draft interactive plan → read code, edit, run, browse docs, run tests, push branch, open PR, respond to review. Dispatches specialist sub-agents and reconciles results. v3 added dynamic re-planning when stalled. ~67% PR merge rate (up from 34% in year 1). Best at well-scoped, verifiable work (migrations, upgrades, flaky-test hunts); struggles with ambiguity and mid-task scope changes. Cross-session knowledge via human-written **playbooks**; codebase + docs serve as external memory. Sources: https://github.com/jexp/agentic-engineering/blob/HEAD/research/coding-agents/devin.md · https://www.turingpost.com/p/cognition · https://github.com/keith-vs-kev/masterplan/blob/HEAD/research/07-ai-factory-patterns.md

### Lindy
Trigger → Actions → Memory structure. 4,000+ integrations; agents react to events (email arrives, lead added, keyword mentioned, schedule, webhook). Built for supervised business workflows with explicit approval gates on external impact. Lesson: **narrow use cases + explicit operating rules + least-privilege tool scoping** beat vague "handle my inbox" agents. Sources: https://github.com/avinashvagh/vibe-coding-tools-2026/blob/HEAD/04-ai-agent-builders.md · https://www.therundown.ai/tools/lindy

### Replit Agent
Plan artifact → hypothesis-driven file search → code edits → in-browser test harness → **checkpoint** → deploy. Checkpoints capture workspace files, agent context, tasks (optionally DB) and double as rollback + billing unit. Task system with Draft/Active/Ready/Done states; parallel subagents in isolated copies with AI-assisted conflict resolution on merge; `replit.md` as the always-loaded agent config. Lesson: **checkpoints as first-class objects** (trust rail + recovery + metering in one). Sources: https://github.com/iwanhk/apie/blob/HEAD/products/AI/Replit.md · https://www.therundown.ai/tools/replit-agent · https://github.com/himanshu11827/nexus/blob/HEAD/docs/research/LOOP_RESEARCH_EXPANDED_REPORT.md

### Open-source patterns
- **LangGraph-based stacks** (largest ecosystem, ~38k+ stars): stateful graphs + pluggable checkpointers + interrupts; example long-running setup with OpenHands SDK: https://github.com/ohama/langgraph_openhands
- **omni-agent**: Temporal + LangGraph + LiteLLM cascade + dual memory — a credible open-source reference for durable multi-day agents: https://github.com/rajhodedara/omni-agent
- **autonomous-ai-agency** (strikersam): FIFO queue + supervisor stall-watchdog + Mongo/SQLite step checkpointing + durable scheduler rehydrated on boot: https://github.com/strikersam/autonomous-ai-agency/commit/3a3a45c7f0ef2107561818c05711bb92c91d4917

### Cross-cutting lessons from production
- The agents that work are the **boring** ones: good error handling, clear boundaries, explicit state management. (https://medium.com/@theagentthatcould/5-architecture-patterns-for-production-ai-agents-that-actually-work-ffab3cfb37f3)
- Start with HITL checkpoints (~74% of teams, first 60–90 days), track intervention rate, expand autonomy as it falls. (https://medium.com/@abhi_dabas/agentic-ai-in-production-5-patterns-that-work-81501a8f995c)
- Read/write tools separated; write actions run through one controlled function after approval. (https://logicproviders.ca/blog/production-ready-multi-agent-ai-system-guide-2026)
- Watchdog between nodes > end-of-chain eval for multi-agent pipelines. (https://towardsdatascience.com/why-most-multi-agent-systems-fail-even-when-evaluation-passes/)

---

## 5. Anti-patterns to avoid

1. **Free-for-all peer agent chat.** Agents messaging each other without a supervisor creates loops and untracked side channels. One coordinator owns routing; peers communicate through a contract.
2. **One ever-growing session.** Context decays; constraints get lost. Bound sessions, compact with tested summaries, restart fresh for new phases.
3. **Unbounded retries on the same step.** Twenty minutes retrying a broken step burns tokens and does nothing. Bounded retries → DLQ → human.
4. **Prose as state.** Beliefs paraphrased by the model are not state. Structured state object, updated only by verified tool output.
5. **20 tools per agent.** Decision paralysis. 5 focused, well-described tools win; scope per task; read/write separated.
6. **Side effects without idempotency.** If a step can run twice, it will. Idempotency keys everywhere.
7. **No heartbeats / no watchdog.** "It'll finish eventually" is how you discover a 3-day stall on Friday.
8. **Silent cron/hook races.** Two triggers answering the same event = duplicate replies. Single ownership, check-before-act, coalesce overlapping runs.
9. **Non-determinism in durable code.** `datetime.now()` or `uuid()` inside a workflow breaks replay recovery.
10. **Over-agentification.** An LLM deciding DAG order when a programmatic DAG is 100× faster and 100% reliable.
11. **Bloated standing context.** Every reload taxes attention; keep it short or the agent stops reading it.
12. **"It runs" = "it's safe."** AI-generated code needs a security-reviewer pass, secret scanning, and least-privilege credentials — especially after incidents.
13. **No termination criteria.** Every task needs max turns, max budget, and a definition of done the agent can check.
14. **Skipping the boring stack.** Redis for sessions, Postgres for data, S3 for artifacts, full tool-call logging, unit-tested tools, integration-tested loops. The unglamorous layer is where reliability comes from.

---

## 6. Recommended starting stack (pragmatic, VM-based swarm)

For a fleet of agents on VMs doing days-to-weeks autonomous work:

1. **Orchestration:** LangGraph (stateful graphs + checkpointers + interrupts) for agent logic; add **Temporal** when you need true multi-day durable workflows with crash recovery. Start with LangGraph + SQLite/Postgres checkpointer; graduate to Temporal.
2. **Scheduling:** cron (5-min backstop, fast idle exit, coalescing) + durable inbox per agent + event-driven triggers; durable timers for future wakes.
3. **State:** plan.md / findings.md / progress.md per mission + Postgres checkpointer + pgvector long-term memory.
4. **Supervision:** supervisor agent per mission; zero-LLM watchdog on heartbeats (flag silence >10 min); action-hash loop detection; small-model grader between stages.
5. **Comms:** keep one coordination channel with strict norms (assignments top-level, replies in threads); prefer a supervisor-mediated task queue over free chat for machine-to-machine work.
6. **Failure handling:** transient/persistent/non-retryable classification; exponential backoff + jitter; DLQ with full context; idempotency keys; per-phase timeouts.
7. **Observability:** structured JSON logs (job_id, trace_id), OpenTelemetry, heartbeat dashboard, alerts on stuck jobs + missed heartbeats + DLQ growth; transition log per mission.
8. **Gates:** HITL on irreversible actions from day one; track intervention rate; expand autonomy as it drops.
9. **Model routing:** LiteLLM gateway; big model for planning, small/fast for classification and grading; fallback chains.

---

*End of report. Saved to `~/workspace/goals/agentic-swarm-utilization-research/hidden_files/long-running-research.md`.*
