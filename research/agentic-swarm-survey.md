# Running a 12-Agent Claude Swarm Autonomously for Days/Weeks

Research date: 2026-10-07. Sources marked `verified live` were read in full in the browser; `index` means search-result/API-text read.

## Summary

The fleet should **not** be rebuilt inside a framework like LangGraph/CrewAI — all evidence says Claude Code-class agents are best run as standalone CLIs coordinated by purpose-built infrastructure (exactly the fleet's current shape: VMs + shell + hooks). The 2026 consensus architecture for this shape is:

1. **A typed agent bus with task claims and leases** (not Slack) — the single biggest upgrade. Best candidate: `agent-communication-system` (qagent): one SQLite file, durable mail, tasks with atomic claims/deps/path-leases/review gates, MCP server, wake-ups. MIT, v0.2.0 (2026-09-30).
2. **An external watchdog + lease-based liveness** — heartbeats claimed from the loop (never the LLM's self-report), task leases with expiry, behavioral progress detection, escalation ladder nudge → restart-with-summary → park.
3. **Anthropic's harness patterns** — initializer/worker, `feature_list.json` with `passes` flags, one-feature-at-a-time, `claude-progress.txt` + git as recovery substrate, external skeptical evaluator, review loops capped at 2–3, sprint contracts.
4. **Durable scheduling** — move fleet cadence off bare cron onto Inngest (fastest) or Temporal (strongest), with idempotency keys and per-step checkpoints.
5. **A curated internal skill/plugin registry** — Superpowers, pluginpool, presentation-builder, Remotion video toolkit, duckdb-data, Playwright MCP, Context7, Serena — version-pinned and mirrored to all 12 VMs.

---

## 1. Multi-agent swarm orchestration frameworks

### 1a. General frameworks

**LangGraph** — https://github.com/langchain-ai/langgraph (`index`)
Stateful agent workflows as cyclic graphs with deterministic, code-pinned control flow, checkpointers (in-memory/Postgres), and human-in-the-loop interrupts; used by Replit, Uber, LinkedIn, GitLab. The 2026 consensus "production" choice: led complex-task benchmarks (~62% success vs CrewAI ~54%) and is the most token-efficient because it avoids re-feeding full chat history. Where it breaks at 10+ agents: shared state becomes the bug farm (memory poisoning, ordering, write contention), orchestrator graph complexity explodes, and distribution requires LangGraph Server.
**Verdict:** Don't reimplement the Claude fleet inside it. Steal its patterns (state graph routing, per-step checkpointer) and use its A2A connector so a coordinator can call Claude CLIs as remote agents.

**CrewAI** — Python, role-based crews (`Agent(role, goal, backstory)`), Sequential/Hierarchical processes (`index`; source: https://dev.to/agdex_ai/crewai-vs-autogen-vs-langgraph-which-multi-agent-framework-in-2026-51m6)
Fastest time-to-demo; LLM-manager routing. Breaks at scale: weakest determinism of the majors, manager-LLM routing cost amplifies, chatty history.
**Verdict:** skip for the fleet; copy its role abstraction as static role prompts.

**AutoGen / AG2** — in maintenance mode; Microsoft steers new work to Microsoft Agent Framework (`index`; same source). Conversational GroupChat with speaker selection; slow, token-hungry consensus loops.
**Verdict:** avoid for new builds.

**Microsoft Agent Framework** — successor to AutoGen + Semantic Kernel; .NET + Python; built-in orchestration patterns (sequential, concurrent, handoff, group chat, Magentic) (`index`).
**Verdict:** relevant only if the fleet standardizes on Microsoft/Azure.

**OpenAI Swarm → OpenAI Agents SDK** — `Agent(instructions, tools)`, handoffs via tool-returned Agent, tracing/guardrails first-class, 26.9k+ stars, MIT (`index`; source: https://aitoolsobserver.com/hub/the-complete-guide-to-agentic-ai-tools-in-2026-top-frameworks-platforms-and-agents/)
**Verdict:** no — Claude-based fleet; LLM-routed handoffs don't transfer.

**Google ADK + A2A protocol** (`index`; sources: https://aitoolsobserver.com/hub/the-complete-guide-to-agentic-ai-tools-in-2026-top-frameworks-platforms-and-agents/ · https://turion.ai/blog/google-adk-vs-openai-claude-agent-sdk-2026/ · https://dev.to/alex_aslam/your-agents-cant-collaborate-if-they-only-speak-tool-calls-the-a2a-protocol-that-fixes-peer-4o0d)
Hierarchical agent trees; the strategically important piece is **A2A**, an open standard (Linux Foundation, v1.2 shipped Mar 2026, 150+ orgs in production): JSON-RPC 2.0 over SSE, agent cards at `/.well-known/agent.json`, typed task delegation. "MCP connects agents to tools; A2A connects agents to agents." LangGraph, CrewAI, LlamaIndex, Semantic Kernel all support it.
**Verdict:** don't adopt ADK (Gemini-optimized); DO adopt A2A as the typed inter-VM delegation protocol.

**AgentScope** (Alibaba, Apache-2.0) — https://arxiv.org/html/2402.14034v2 (`index`)
Actor-model multi-agent platform (actors = agents, automatic parallel optimization), hybrid local/distributed deployment, Agent Service with cron scheduling and per-agent workspace isolation, A2A/AG-UI protocol adapters. Actor + supervisor is the closest thing to Erlang-style fault tolerance in agent frameworks.
**Verdict:** study for design ideas (actor mailboxes, MsgHub); don't adopt wholesale (Python-centric, doesn't run Claude Code CLIs natively).

### 1b. Harnesses built specifically for Claude/Codex-style coding agents

**claude_code_agent_farm** — https://github.com/Dicklesworthstone/claude_code_agent_farm (`index`)
Runs 20–50 parallel Claude Code sessions with lock-based coordination (prevents file conflicts), tmux monitoring, heartbeat tracking, auto-restart with adaptive idle timeout, git commits with rich diff summaries.
**Verdict:** high-value reference for lock-based coordination + heartbeats + auto-recovery. Study, don't lift (single-machine tmux).

**Overstory** — npm `@os-eco/overstory-cli`, MIT (`index`; source result text)
Spawns workers in git worktrees via tmux, coordinates through a custom SQLite mail system, merges back with tiered conflict resolution, pluggable `AgentRuntime` (Claude Code, Pi, Copilot, Codex). Ships a STEELMAN.md risk analysis: compounding error rates, cost amplification, merge conflicts are the normal case.
**Verdict:** closest existing analog to "fleet on worktrees + SQLite mail"; good design reference for conflict-resolution tiers.

**multi-agent-cli-orchestration-fleet** — https://github.com/aiscorpio/multi-agent-cli-orchestration-fleet (`index`)
A Claude Code *skill* that turns Claude into orchestrator + QA gate for heterogeneous external CLI agents (codex/kimi/opencode/claude) over a plain file-based task queue; no-LLM QA floor; capacity-aware scheduling; detached long-job tracking; no server/database/broker.
**Verdict:** read its QA-gate and capacity-scheduling design; its file queue is exactly what a real bus (qagent) improves on.

**agentctl / swarmboard** — https://github.com/michaelxu2288/agentctl (`index`, Go, POC)
Terminal-native control plane: master coordinator (scheduler · router · failure detector) dispatches over an internal gossip bus; each worker = git worktree + PTY/tmux; live kanban TUI; heartbeats.
**Verdict:** good architectural sketch (master + gossip bus + kanban); POC-stage — steal ideas, don't adopt.

**open-multi-agent** — https://github.com/moshbbab/open-multi-agent/blob/HEAD/AGENTS.md (`index`, TypeScript)
TaskQueue with DAG dependency resolution; scheduler strategies (dependency-first, round-robin, least-busy, capability-match); MessageBus (p2p + broadcast); SharedMemory; per-agent loop detector; `AgentBackend` seam so an agent runs on an LLM runner *or* an external CLI process.
**Verdict:** best reference for scheduler-strategy design and the backend-seam idea (Claude CLI as one backend among many).

**Claude Code Projects relaunch (Sep 17, 2026)** — https://www.aichatdaily.com/ai-tools/anthropic-relaunches-claude-code-projects-orchestrate-multiple-agents (`index`)
Parallel cloud threads on branched repos, shared memory/goals/artifacts, coordinator resolving conflicts as pull requests.
**Verdict:** first-party direction — mirror it on your own infra: one branch/worktree per task, PR-based conflict resolution.

### 1c. Meta-lesson
Every framework is the same four primitives — agent (function of prompt+tools), handoff (function call), shared state (the *only* stateful thing, where all bugs live), orchestrator (scheduler). Source: https://github.com/zephyrex21/ai-engineering-roadmap/blob/HEAD/phases/16-multi-agent-and-swarms/04-primitive-model/docs/en.md (`index`). Design questions that matter at 10+: pin routing in code vs trust the LLM (pin it), full-history vs projected shared state (project it — task board, not chat log), who may modify whose prompts.

---

## 2. Long-running autonomy (days/weeks, no oversight)

### Proven harness patterns (Anthropic, verified live)

**"Effective harnesses for long-running agents" (Nov 26, 2025)** — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents (`verified live`)
- Initializer agent (one run: `init.sh`, `claude-progress.txt`, feature list, initial git commit) + coding agents (every session: read progress + git log, run smoke test, do ONE feature, commit, update progress).
- `feature_list.json` with 200+ features, each `{description, steps, passes: false}`; agents may only flip `passes`; "unacceptable to remove or edit tests"; JSON over Markdown (model less likely to mangle it).
- One-feature-at-a-time prevents one-shotting and half-implemented features; failing flags prevent premature "done".
- End-of-session "clean state": mergeable code, descriptive commits, progress notes — git is the recovery substrate.
- Puppeteer/Playwright MCP browser testing "as a human user would" catches bugs code review misses.
**Verdict:** implement as the fleet's standard session protocol.

**"Harness design for long-running application development" (Mar 2026)** — https://www.anthropic.com/engineering/harness-design-long-running-apps (`verified live`)
- Planner → Generator → Evaluator (GAN-inspired). Planner expands a 1–4 sentence prompt into a spec but stays high-level (granular planner specs cascade errors). Generator works in sprints, self-evaluates per sprint. Evaluator is a *separate* agent, tuned to be skeptical (few-shot calibration), using Playwright MCP to click through the app; hard thresholds; sprint fails → generator gets feedback.
- Sprint contracts: generator + evaluator negotiate "done" *before* code is written.
- Self-evaluation is unreliable; separating worker from judge is "a strong lever". Make review stages conditional on difficulty. Repair gains concentrate in the first 2 rounds → cap review iterations at 2–3.
- Context resets (fresh agent + structured handoff artifact) beat compaction for coherence ("context anxiety"), at the cost of orchestration complexity.
- Cross-agent communication via files.
**Verdict:** adopt planner/generator/evaluator as role templates; sprint contracts; 2–3 review cap; external QA agent with browser automation.

**Harness checklist additions** (research synthesis, `index`; https://github.com/lokeshrana9999/shipyard/blob/HEAD/plugins/shipyard-delivery/docs/sources/build-workflow-research.md):
honest-failure schemas (first-class `blocked` / `flag_for_human` exits), blocked-twice escalation rule, pre-flight health check at each agent start, verify-after-land, never-edit-tests, restart-own-process rule. Countermeasures for "fake green" (models editing tests to pass — ImpossibleBench 2025): read-only tests, explicit flag-for-human exit.
**Verdict:** adopt verbatim.

### Self-healing loop components

**self-healing-agent** (hailports) — https://github.com/hailports/self-healing-agent (`index`, pure-stdlib Python): retry w/ exponential backoff + jitter; circuit breaker (trip → reroute → tell the agent); per-step watchdog deadline; checkpoint every step + resume from disk; budget governor (steps/time/tokens); structured event log.
**Verdict:** adopt the checklist in the fleet's agent-loop wrapper.

**External watchdog design** — http://dev.to/yureki_lab/how-i-built-a-watchdog-that-stops-my-ai-coding-agent-from-looping-forever-61h (`index`): (1) measure *progress*, not effort; (2) the agent can't be its own watchdog — external behavioral observer; (3) normalize fingerprints before comparing (strip digits/whitespace); (4) killing is the worst first response — ladder: **nudge** (keeps context) → **restart** (keeps summary) → **park** (for human); (5) false positives cheaper than missed loops.
**Verdict:** design the fleet supervisor exactly this way.

### Detecting and recovering from stalled workers
Converged recipe (`index`; sources: https://dev.to/imversion_tech/long-running-ai-agents-efficient-asynchronous-workflow-strategies-4ihp · https://thetshaped.dev/p/5-resilience-patterns-for-ai-agents-retries-checkpoints-idempotency):
- Every run = durable job: `job_id, idempotency_key, retry_count, priority, deadline, input_payload_ref`.
- Workers **claim with a lease** (SQS-style visibility timeout); crash/hang/no-heartbeat → lease expires → another worker reclaims. **This is the anti-silent-failure primitive.**
- At-least-once delivery is normal → **idempotent execution** via per-step keys (`job_id + step_name + attempt_group`); check-before-rerun, reuse stored results.
- Heartbeats + leases + idempotency together = claim safely, renew while active, reassign after failure, resume without corruption.
- Checkpoint after every step; checkpoint around side effects (before *and* after); durable state in Postgres/Temporal, short-lived coordination in Redis.
- Durable-execution options compared: **Temporal** (history replay; workflow code must be deterministic), **DBOS** (workflow log in your Postgres, transactional steps), **Inngest** (re-invokes function, injects saved step results), **LangGraph** (checkpoints; use sync mode). "A crash costs you whatever you did not wrap." Source: https://hackernoon.com/durable-execution-for-ai-agents-langgraph-dbos-inngest-and-temporal-compared
- Research frontier: IBM STRATUS (explicit undo-and-retry, +150% on AIOps benchmarks, NeurIPS 2025); AgentRewind (aligned context+env checkpoints); Planarian (cross-system statepoints); ChronoMem (versioned memory, natural-language undo). Source: https://www.webpronews.com/why-ai-agents-demand-more-than-prevention-the-case-for-built-in-recovery/
**Verdict:** lease-based claims + heartbeats + idempotency keys + per-step checkpoints are the implement-now set; undo/rewind are watch-list.

---

## 3. Agent specialization

**Role taxonomy** (converged, `index`; sources: https://www.analyticsinsight.net/photo/multi-agent-architecture-explained-building-reliable-ai-systems-with-orchestration-and-guardrails · https://playbook.think.ke/books/agentic-ai-implementation-playbook/page/multi-agent-design/export/pdf):
planner/orchestrator · researcher · coder/executor · reviewer/evaluator (independent) · tester · sentinel/guardrail · finance/budget · audit.

**Orchestration patterns** (`index`; https://github.com/jasonaden/agent-toolkit/blob/HEAD/agents/agent-builder/docs/AGENT_ORCHESTRATION_PATTERNS.md):
- Sequential pipeline (Spec → Architect → Implementer → Reviewer → Tester) for linear deps.
- Parallel fan-out (+ aggregator) for independent perspectives — 40–60% latency reduction.
- Hierarchical manager/worker (manager on stronger model, workers on faster/cheaper).
- Planner-executor (dynamic), blackboard/shared-memory.
- Accountability: structured JSON outputs, validator/judge agents, token/latency/error metrics.

**Routing/dispatch:** scheduler strategies dependency-first (default), round-robin, least-busy, capability-match (open-multi-agent); capability declarations per agent (`capabilities, tools, maxConcurrentTasks, responseTimeEstimate`; jasonaden/agent-toolkit) — pairs with A2A agent cards; DAG dependency resolution with auto-unblock.

**Static vs dynamic:** "Start with a simple linear orchestration and evolve into dynamic planning once you trust the system's reasoning reliability" (Jen Anderson, Medium, `index`). Anthropic (Jun 2025): multi-agent costs ~15x chat tokens; suits breadth-first work, not tightly-coupled coding — the coordination tax is real. Meta-principle from notdp/hive: "the harness became cattle" (harness itself must be restartable) and retire dead-weight workarounds models no longer need.
**Verdict:** static-by-default (fixed roles, code-pinned routing, dependency-first + capability-match scheduling), dynamic-by-exception (planner routing, conditional review near the capability edge). Suggested split for 12 VMs: 1 coordinator, 2 planners, 4 builders, 2 researchers, 2 evaluators/QA, 1 infra/tools — reassignable via task claims, not LLM whim.

---

## 4. Communication alternatives to Slack

**agent-communication-system (qagent)** — https://github.com/anon5376/agent-communication-system (`index`; README: https://github.com/anon5376/agent-communication-system/blob/HEAD/README.md; CHANGELOG: https://github.com/anon5376/agent-communication-system/blob/HEAD/CHANGELOG.md)
v0.2.0 (2026-09-30), MIT. "One SQLite file to coordinate every coding agent on your machine — no daemon, no cloud." Agent-shaped primitives the fleet's file-inbox lacks: verified per-agent token identities; addressed/multi-recipient/broadcast durable mail with threads, acks, typed messages; task lifecycle create → assign → claim → submit → review → release with dependencies, **atomic claims, path leases (no file collisions), claim expiry/requeue**, progress notes, **independent review gates**; full event log. Stdio MCP server (14 agent tools) so Claude Code uses the bus as tools; harness adapters for Claude Code/Codex/Gemini/Kimi/OpenCode; optional supervisor wakes CLIs; localhost dashboard with SSE; signal-file wake-ups.
**Verdict:** HIGHEST-LEVERAGE adoption. Host the bus DB on the coordinator VM (SQLite over NFS is fragile — access via MCP/CLI), keep Slack only as a human-facing mirror. Explicitly designed for "the mailbox and task board underneath the standalone CLIs you already run."

**Message buses / event logs** (`index`; https://github.com/faresrafat3/crew-research-council/blob/HEAD/RESEARCH-COUNCIL/OUTPUT/communication-protocols.md):
Redis Streams (consumer groups, at-least-once) for prototype → Kafka for production; BullMQ (Redis) with retries/DLQ/idempotency; NATS JetStream. Pattern: agents emit `task_completed` / `needs_review` / `spawning_subtask`; orchestrator keeps the global state machine; Redis MULTI/EXEC prevents races. Target metrics: delivery >99.9%, duplicates <0.1%, queue depth <10/agent, DLQ depth 0.
**Verdict:** graduate here when single-node SQLite is outgrown — Redis Streams + BullMQ is the proven next step. Don't start here.

**Git-based coordination:** keep git as the *artifact/state* substrate (feature_list.json + claude-progress.txt + commits; one worktree per task; PR-based merges — Anthropic's Claude Code Projects model), not the *messaging* layer (no push/wake, claim races).
**Verdict:** keep, but don't confuse with messaging.

**CRDTs (Automerge/Yjs):** elegant concurrent shared state, but operationally heavier than needed when tasks are claimable units.
**Verdict:** skip.

**Layered target:** (1) bus — mail/tasks/claims/review gates/event log; (2) git — artifact state, worktrees, PRs; (3) A2A — typed cross-agent delegation; (4) MCP — tool access; (5) Slack — demoted to human-readable mirror/alerts.

---

## 5. Agent skills and tooling

**Distribution** (`index`; https://github.com/yoselabs/insights-trail/blob/HEAD/data/2026-04-11/agent-skills/briefing.md):
Official Anthropic plugin marketplace + Customize hub; MCP Registry (registry.modelcontextprotocol.io). Aggregators: claudemarketplaces.com (2,500+ marketplaces), TokRepo (500+), CCPI (`ccpi search/install`, 340 plugins + 1367 skills), SkillsMP (200k+ claim), buildwithclaude.com (400+). Constraint: context bloat — keep <10 MCP servers, <30 tools per project; MCP Tool Search lazy-loads (~95% overhead reduction).

**Curated collections worth adopting** (`index`):
- **Superpowers** (obra/superpowers): 60 agents, 228 skills, 75 commands — TDD, security scanning, code review, systematic debugging; a full dev methodology. → adopt for builders.
- **pluginpool** (mturac/pluginpool): 10 dev-hygiene plugins — commit-narrator, pr-storyteller, test-gap, deps-doctor, env-lint, secret-guard, flaky-detector, changelog-forge, standup-gen, todo-harvest; MIT, 89 hermetic tests. → adopt.
- **get-shit-done** (gsd-build): spec-driven Questions→Research→Requirements→Roadmap→execute→audit, 100+ commands.
- **awesome-claude-code** (hesreallyhim): the selectively-reviewed canonical list. **awesome-claude-code-toolkit** (rohitg00): 135 agents, 176+ plugins, 20 hooks.

**By capability** (`index`):
- Dev core: **Serena** (semantic code nav) + **Context7** (live version-specific docs, 37.5k+ downloads) + **Sequential Thinking MCP** — the cited "power trio". **bouncer** (buildingopen/bouncer: independent Gemini quality gate). **brooks-lint**. **agento-patronum** (sensitive-file security layer).
- Design: **UI/UX Pro Max** (nextlevelbuilder/ui-ux-pro-max-skill); Anthropic's frontend-design skill.
- Slides: **automated-presentation-builder** (https://github.com/shruti2212-ctrl/automated-presentation-builder — python-pptx from scratch, brand extraction, visual QA) → adopt; pm-claude-skills slide-deck; shaharsha presentation-generator (AI-rendered 16:9 slides); Anthropic official pptx skill.
- Video: **Claude-Code-Video-Toolkit** (https://github.com/wilwaldon/Claude-Code-Video-Toolkit — Remotion, Manim, FFmpeg, Playwright screen recording, YouTube clipper) → adopt; digitalsamba video toolkit; Yusuke710/manim-skill; VideoDB skills.
- Image: shaharsha image-generation skill (gpt-image-2); deapi-ai/claude-code-skills (Flux, TTS, OCR, bg removal); Picsart GenAI CLI (140+ models).
- Data: **duckdb-data** skill (SQL analytics over DuckDB) → adopt; D3.js visualization skill.
- Browser automation: **Playwright MCP** (Anthropic's own QA choice; `--save-video` for screen recording) → adopt; agent-browser CLI (CDP).
- Audio: ElevenLabs/TTS skills, moltdj, claude-ai-music-skills.

**Verdict:** don't install the world (context bloat). Curate ONE internal marketplace (git repo with `.claude-plugin/marketplace.json`): Superpowers, pluginpool, automated-presentation-builder, Claude-Code-Video-Toolkit, ui-ux-pro-max-skill, duckdb-data, Playwright MCP, Context7, Serena, bouncer. Mirror version-pinned to all 12 VMs; audit quarterly. Write fleet-specific SKILL.md files for internal conventions (bus protocol, session protocol, escalation) — skills are the cheapest way to align 12 agents.

---

## 6. Scheduling and cron setups for agent fleets

**Durable execution platforms** (`index`):
- **Temporal** — history-replay durable execution, cron workflows, worker task-queue polling. $550M Series E (Sep 2026) at $12.55B valuation; $250M+ ARR; customers incl. OpenAI, NVIDIA. The 2026 "reliability layer" bet. Strongest guarantees, most ops. Source: https://www.metirai.com/blog/temporal-550-million-durable-execution-ai-agent-infrastructure-2026
- **Inngest** — event-driven durable execution, `step.run()` checkpoints, cron triggers; self-hostable; fastest path from cron to durable. Source: https://github.com/myselfnandha/zerogravity/blob/HEAD/.agents/plugins/antigravity-awesome-skills/skills/workflow-automation/SKILL.md
- **DBOS** — workflow log in your own Postgres; steps commit in the same transaction as the rows they wrote; best if the fleet is Postgres-centric.
- **LangGraph** — checkpointers + LangGraph Server (use sync checkpoint mode).
- Comparison: https://hackernoon.com/durable-execution-for-ai-agents-langgraph-dbos-inngest-and-temporal-compared
- **BullMQ** (Redis) — delayed/retried/cron jobs, DLQ, idempotency; the pragmatic middle ground.

**Agent-native patterns** (`index`): heartbeat loops (OpenClaw/SwarmClaw) for liveness + scheduled recurring work; Claude Code hooks (Ralph Wiggum-style hook loops) for continuous iteration; AgentScope Agent Service cron with stateful/stateless sessions persisting across restarts.

**Verdict:** centralize fleet cadence on the coordinator VM with Inngest (least ops) or Temporal (strongest semantics); all recurring jobs registered with retries, timeouts, DLQ, overlap protection (singleton/lease); every job writes results to the event log. Keep per-VM cron only for node hygiene and as a fallback that re-registers with the central scheduler. Keep agent-local heartbeat loops/hooks for liveness.

---

## Could not verify / open questions
- Whether `agent-communication-system` works over 12 VMs: it is single-machine SQLite by design; the multi-VM story (host DB on coordinator, SSH/MCP access) is my inference from its docs, not a documented deployment. Needs a spike.
- Performance/cost numbers in comparisons (LangGraph 62% vs CrewAI 54%, "15x chat tokens", "40% faster to production") come from secondary 2026 benchmark roundups, not primary papers — treat as directional.
- No page instructions were encountered that attempted to redirect the mission; all sources were treated as evidence only.

## Sources
- Notes: `notes/q1-frameworks.md`, `notes/q2-autonomy.md`, `notes/q3-specialization.md`, `notes/q4-communication.md`, `notes/q5-skills.md`, `notes/q6-scheduling.md` (each with URLs + read dates).
- Verified live: https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents ; https://www.anthropic.com/engineering/harness-design-long-running-apps
- Index: all other URLs listed inline above.

---

## Prioritized top-10 recommendation list

1. **Adopt `agent-communication-system` (qagent) as the coordination bus** — replaces Slack + file-inbox long-poll with durable mail, atomic task claims, path leases, review gates, MCP tools, and wake-ups. Host the SQLite DB on the coordinator VM; demote Slack to human mirror. (https://github.com/anon5376/agent-communication-system)
2. **Build an external supervisor with lease-based liveness** — heartbeat from the loop, task leases with expiry, behavioral progress detection (normalized fingerprints), escalation ladder nudge → restart-with-summary → park. The agent must never be its own watchdog. (Pattern: dev.to watchdog post; hailports/self-healing-agent)
3. **Implement Anthropic's session protocol fleet-wide** — initializer/worker split, `feature_list.json` with `passes` flags (tests never edited), one-feature-at-a-time, `claude-progress.txt` + git commits, mandatory session-start orientation (pwd → progress → git log → feature list → smoke test), Playwright MCP e2e verification. (https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
4. **Split planner / generator / evaluator roles** — planner stays high-level; evaluator is a separate skeptical agent with hard thresholds and sprint contracts; cap review loops at 2–3; make review conditional on difficulty. (https://www.anthropic.com/engineering/harness-design-long-running-apps)
5. **Move fleet scheduling to durable execution** — Inngest (fastest) or Temporal (strongest) on the coordinator VM; retries, timeouts, DLQ, overlap protection; idempotency keys and per-step checkpoints on all side-effecting work. Keep per-VM cron only for node hygiene.
6. **Static roles, deterministic routing** — 1 coordinator / 2 planners / 4 builders / 2 researchers / 2 evaluators / 1 infra; dependency-first + capability-match scheduling; capability registry on the bus (A2A-style agent cards). No LLM-driven reassignment by default.
7. **Git worktrees + PR-based merging per task** — one worktree per claimed task, path leases to prevent collisions, PR/conflict-resolution tiers on merge (Claude Code Projects / Overstory model).
8. **Curate one internal plugin/skill marketplace** — Superpowers, pluginpool, automated-presentation-builder, Claude-Code-Video-Toolkit, ui-ux-pro-max-skill, duckdb-data, Playwright MCP, Context7, Serena, bouncer; version-pinned, mirrored to all 12 VMs; plus fleet-written SKILL.md files encoding bus/session/escalation conventions.
9. **Central observability + budget governance** — one structured event log (the bus's), a dashboard, per-agent budget governors (steps/time/tokens; ccusage), circuit breakers on failing dependencies.
10. **Adopt A2A for typed inter-agent delegation** — agent cards + JSON-RPC task interface for VM-to-VM calls that don't fit the bus's mail/task model; MCP stays the tool layer. (A2A spec via Linux Foundation)
