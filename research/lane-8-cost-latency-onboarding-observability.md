# Lane 8 — Cost / Latency / Onboarding / Observability

Research findings for the agentic-swarm utilization project. Boboe 3 (telemetry owner), 2026-10-07.
Grounded in the live fleet: 12 agents (Boboe Prime + 1–11), #all-agentnet (C0C6MQMSLFL),
fleet-telemetry repo, telemetryd v13 (auto health shipping), 5-min slack-watch backstop,
Jack's 10-minute accountability rule, standing orders 7–9 (WAKANDA / answer-when-named / no-health-posts).

## 1. Cost / latency

Observed industry pattern (multi-agent swarms, 2026): coordination tokens dominate —
inter-agent communication alone can be ~45% of total token spend, and a swarm can
consume ~15x a single agent's tokens for the same outcome. Budget 3–5x the naive
token estimate per task. Apply controls in this order, stopping when the target is hit:

1. **Prompt caching** — zero code changes; static prefixes (standing orders, channel
   norms, skill prompts) sit at the prompt head so provider caching engages
   (Anthropic: 5-min default, 1-hour option). Independent agent-task measurements
   show 41–80% lower API cost on cache-friendly workloads.
2. **Hard limits = circuit breakers** — per agent, per session: max iterations
   (2–3x expected), max token spend (3x P95 of the task class), max wall-clock time.
   This is the blast-radius cap for a runaway loop: a broken loop making 10,000
   calls hits the budget and stops before the invoice arrives. Fits Jack's standing
   grant — budgets are guardrails, not approval gates.
3. **Output token control** — hard max_tokens per call class; "respond concisely"
   in agent prompts cuts output 15–25% with no quality loss on operational traffic.
4. **Tool output masking** — strip headers/metadata from high-volume tool
   responses (Slack reads, hook logs); 60–80% reduction on those calls.
5. **Model routing** — tier by difficulty: cheap/fast models for triage and
   ack-style replies, frontier models for judgment calls. Cost-based routing
   literature reports 40–70% inference savings on the routable majority.
6. **Semantic caching** — for repeated fleet questions ("what's the daemon version?",
   "summarize the thread"), embedding-similarity caches eliminate 20–40% of calls
   entirely. Start with the claim-board and standing-orders FAQs.
7. **Context compression** — rolling summaries past ~10 turns; raise RAG
   relevance thresholds (0.7 → 0.8) to cut retrieval noise 40–60%.

Concrete fleet proposal: telemetryd ships a daily per-agent cost rollup
(input+output tokens, cache-hit rate, avg latency) into fleet-telemetry; Jack sees
spend per agent on his dashboard without any Slack noise.

## 2. Observability

Current state is strong on liveness (v13 ships post/mailbox ok-fail counts, last
error, daemon start time, per-hook runs/wakes/errors every push) but blind on work:
no trace of what any agent *did*, how long it took, or what it cost. Add, in order:

1. **Token/latency counters per task** — extend telemetryd's push payload:
   model calls with input/output tokens, latency, cache hit/miss. Cheap, synchronous,
   no new infra. Highest-leverage step.
2. **Session → trace → span conventions** — OpenTelemetry-style hierarchy for agent
   work (session = task, trace = agent workflow, span = LLM call / tool call),
   emitted with consistent attributes so any viewer (Langfuse, Arize Phoenix,
   SigNoz) can consume them. Multi-agent failures are path-dependent; flat logs
   cannot explain them — parent-child spans are the fix.
3. **Eval tiers, cheapest first** — (a) step-level schema validation on tool calls
   (catches malformed arguments before they touch state); (b) trajectory replay of
   historical traces against prompt/model changes to catch drift; (c) LLM-as-judge
   sampling for quality. Tier (a) alone removes the most common failure mode.
4. **Alert thresholds, not Slack posts** — throughput, error rate, latency
   distribution, cost-per-query alerting belongs on Jack's dashboard and in
   telemetry (standing order 9: no health posts in Slack — honor it).
5. **Trust ladder** — per-agent reliability metrics decide autonomy levels
   (Jack's "agents accounted for every 10 minutes" becomes a heartbeat metric,
   not a chat message). New agents start supervised, graduate on evidence.

## 3. Onboarding

Split onboarding into one-time join vs. ongoing runtime, mirroring proven
agent-guild-style patterns:

**One-time join (fleet ONBOARDING.md):**
1. Read standing orders (all 9 — the 2026-10-07 divergence showed a truncated
   v2 circulating; the doc must be canonical and versioned).
2. Channel norms: #all-agentnet top-level assignments with @-tags, replies in
   thread, no canvases, dead-thread discipline, no health posts, WAKANDA.
3. Claim a lane on the claim board (one owner per lane); register id, Slack id,
   lanes, capabilities in the fleet registry (idempotent).
4. Closed-loop test: answer a test mention in-thread, move inbox file to done/.
5. If it can't follow the doc, that's a capability signal — surface it.

**Ongoing runtime (identity + presence):**
- Stable agent/device id, registered once, validated before real work; unexpected
  or over-cap workers exit before spending tokens.
- Heartbeat: the 10-min accountability check is a metric (last_seen in registry),
  enforced by cron, not by chat.
- **Handoff pattern** for cross-lane work: explicit trigger ("this crosses into
  X, bringing in Y"), identity announcement, context carried over (no re-asking),
  one clear owner at a time.

## Concrete changes proposed (for the 24h rollup)

- [ ] telemetryd v14: per-task token/latency/caching counters + daily per-agent
      cost rollup in the push payload (Boboe 3 owns; no Slack output).
- [ ] fleet-telemetry `research/` gains `observability-spans.md` with the
      session→trace→span attribute schema; first emitter is the slack-watch cron.
- [ ] Per-agent token budgets in cron definitions (3x P95 per task class) as the
      runaway-loop circuit breaker.
- [ ] Canonical `ONBOARDING.md` in fleet-telemetry pinning all 9 standing orders
      with version + effective dates; registry.json for agent ids/lanes/last_seen.
- [ ] Heartbeat metric replaces "are you there" chat traffic for the 10-min rule.

## Sources (research, 2026-10-07)

- Observability practices: dev.to AI-agent observability guides (distributed
  tracing, continuous eval, real-time alerting), techtarget enterprise agent
  observability, futureagi multi-agent observability guide, LinkedIn production
  readiness checklist (OTel-first, span schema contracts, trajectory caps).
- Cost control: neuraltrust.ai AI-gateway cost optimization (routing 40–70%,
  semantic caching 20–40%, token budgets), agent-swarm advanced-topics cost
  deep-dive (6x verbosity, 15x consumption, 45% coordination tokens,
  optimization priority order), sybil-swarm multi-agent frameworks research
  (model tiering, context caching), awesome-llm-gateway catalog,
  aiplusinfo prompt-caching guide (41–80% measured savings).
- Onboarding/identity: agent-commons/agent-guild ONBOARDING.md + SKILL.md
  (one-time join vs runtime skill, registry.json, closed-loop trigger test),
  conversational-ai-patterns multi-agent handoff (explicit trigger, identity
  announcement, context continuity, clear ownership), MachineID.io fleet identity
  templates (unique deviceId, register, validate-before-work, cap enforcement),
  agent-did RFC-001 (identity registration/verification/revocation flow).
