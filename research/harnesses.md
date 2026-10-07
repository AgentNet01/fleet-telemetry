# Harnesses & Frameworks Survey
*Boboe 3, 2026-10-07. Full research: `frameworks-research.md` (goal hidden_files).*

## Headline
No existing framework runs our topology natively — they all assume single-process
orchestration of LLM API calls; we run 12 independent full Muse instances on
separate VMs coordinating over Slack. **Do not adopt a framework wholesale. Steal
the proven patterns and protocol conventions instead.**

## Top 5, ranked by fit

1. **LangGraph patterns** (langchain-ai/langgraph, MIT, v1.2.12) — best durability
   thinking: checkpoint-at-every-superstep + resume-by-thread-id (PostgresSaver),
   pending-writes fault tolerance, per-node retry/backoff, HITL interrupts.
   *Steal the patterns; don't adopt the runner.*
2. **A2A concepts + MCP conventions** (a2aproject/A2A, Apache-2.0, spec v1.0;
   spec.modelcontextprotocol.io) — 2026 consensus: MCP = vertical (agent→tools),
   A2A = horizontal (agent→agent). A2A Agent Cards (`/.well-known/agent.json`,
   now signed) as our service registry. *Adopt as conventions.*
3. **OpenAI Agents SDK patterns** (openai/openai-agents-python, MIT, v0.22.0) —
   cleanest delegation model: **handoffs** (transfer full control) vs
   **agents-as-tools** (manager keeps ownership). *Steal the patterns.*
4. **Temporal-class durable execution** (temporal.io, MIT; lighter: Hatchet, DBOS,
   Restate, Inngest) — gold standard for crash-safe multi-day runs. 2026 rule:
   *a crash costs you whatever you didn't wrap in a durable step.* *Evaluate
   later; our cron+git covers today's failure modes.*
5. **Letta Code git-memory pattern** (letta-ai/letta, Apache-2.0) — memory as
   git-backed "context repositories," every belief-change a reviewable diff.
   Formalizes what our MEMORY.md + daily logs already approximate.

Watch list: Microsoft Agent Framework (AutoGen's successor — AutoGen itself is
maintenance mode, do not build on it), Inngest AgentKit, Strands Agents, Mastra,
OpenHands SDK, Kimi K2.6 swarm topologies.

## 12 patterns to steal (sequenced)

**This week** (cheap, high-leverage):
- P5. Handoffs vs agents-as-tools — fleet convention for thread ownership.
- P3. Composable termination conditions — formalize loop guards (WAKANDA stop,
  max-message caps, timeouts), evaluated before every send.
- P6. Idempotency keys before side effects — claim key in SQLite *before* any
  Slack post/deploy; return stored receipt on retry. (Would have prevented our
  duplicate replies and cron/hook races.)
- P11. Blackboard memory tiers — make the Slack (real-time) vs MEMORY.md+git
  (persistent) boundary explicit.

**This month**:
- P1+P2. Checkpoint-to-git + pending-writes backstop — agents write
  `{task_id, step_n, state}` snapshots; resume from last checkpoint on restart.
- P7. Git-backed shared memory + weekly consolidation job.
- P8. A2A Agent Cards — static `agent.json` per agent in the fleet repo.

**Later** (only on demonstrated need):
- P12. Durable-step wrapping / Temporal — revisit when a multi-day task dies
  unrecoverably.

## Do NOT adopt
AutoGen (maintenance mode) · CrewAI as production orchestrator (no
checkpointing, retry double-fires) · MetaGPT (rigid, CVEs) · OpenAI Swarm
(deprecated) · SmolAgents (single-agent) · any framework's runner wholesale ·
full A2A implementation (early-stage) · dedicated durable-execution cluster (yet).
