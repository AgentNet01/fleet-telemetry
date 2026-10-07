# Cost & Latency — Lane 8 annex (Boboe 8)

**Date:** 2026-10-07 · **Lane:** 8 (cost/latency, onboarding, observability) — this file covers cost/latency only. Observability is covered by `observability-dashboard.md` (Boboe 9); onboarding remains open.
**Companion:** `research/swarm-research-boboe8.md` (commit 9e419f3) — this annex fills the cost/latency gap in that push.

## 1. Measured quantities (this fleet, this week — grounded)

- 12 agents (Prime + 1–11), each on its own Linux VM. Telemetry heartbeats every **15 s** → **2,880 heartbeats/hour** fleet-wide, **69,120/day**. Heartbeats are daemon-level metric pushes (post/mailbox ok-fail counts, last error, daemon start time, per-hook runs/wakes/errors) — network + receiver CPU, not model tokens.
- Jack's accountability requirement: every agent accounted for every **~10 min**.
- Incident (pre-fix): an agent wake loop generated **~850 wakes/hour** fleet-wide plus **~54 MB mailbox saves** (later fixed to ~4 MB saves; per-agent posts no longer wake thread-mates).
- Background worker runs on this VM: empty run **~99 s**, runs carrying a message time out at **240 s**; 1-minute cron coalesces to every **4–5 min**.
- Anti-loop caps in force: an agent naming back someone who just named it is filed as the answer (no re-wake); max **12 agent-to-agent mentions per thread per hour**.
- From the research survey: hierarchical supervisor patterns add **~30% token overhead** (CrewAI hierarchical); uncapped multi-agent conversations document **2x+ token multipliers**.

## 2. Cost model: what actually burns money

LLM spend in this fleet is **∝ agent runs × tokens per run**, not heartbeats. Runs are driven by: Slack wake events (mentions, thread activity), cron ticks (5-min slack-watch backstop), hook invocations (slack-inbox — now retired — telemetry-watchdog), and main-chat turns. Two multipliers dominate:

1. **Wake multiplier.** A healthy fleet wakes agents only on real mentions/tasks. The wake-loop incident showed the failure mode: ~850 wakes/hour where each wake can trigger a worker run. At the measured 99–240 s per run, sustained wake storms are the single biggest cost risk — bigger than any model-choice decision.
2. **Conversation multiplier.** Free-text threads with no caps produce ~50% spam/off-topic ("Interaction Theater", 2026 arXiv, cited in companion file). Every off-topic round-trip is tokens with zero decision value. The 12-mentions/thread/hour cap and the typed-envelope recommendation (companion §3/R4) directly attack this.

Rough order-of-magnitude envelope (explicit assumptions): if each agent averages one substantive worker run per 15 min at ~8k input + ~2k output tokens, the fleet burns ~12 × 4 × 24 × 10k ≈ **11.5M tokens/day** — before any wake storm. Dollar figures depend on Jack's provider pricing (unknown to me; not in repo) — the model to plug numbers into is `daily_cost = runs/day × (in×p_in + out×p_out) × wake_multiplier × convo_multiplier`.

**Levers that move the number:** (a) kill wake loops at the source (done this week — per-agent posts no longer re-wake threads); (b) duty-based heartbeats so "alive" isn't conflated with "working" (companion R2); (c) keep substantive coordination out of free-text threads — task board with claim semantics (companion R1) converts N chatter rounds into 1 claim + 1 result; (d) fixed roles + a critic (companion R3) instead of all-to-all deliberation; (e) don't add a supervisor layer unless its replanning value beats its ~30% token tax.

## 3. Latency budget for the 10-minute accountability window

| Stage | Budget | Basis |
|---|---|---|
| Heartbeat interval | 15 s | telemetryd v13 (measured) |
| Missed-heartbeat → UNHEALTHY | 3 misses ≈ 45 s | convention |
| UNHEALTHY → restart attempt | ~1–2 min | receiver-side scan cadence |
| Restart → escalate (page Jack/dot, one Slack post) | ≤ 10 min total | Jack's requirement |

Slow-path reality check: a mention handled by a background worker costs 99–240 s plus up to ~5 min cron coalescing; a mention answered in main chat costs seconds. That is the measured argument for Boboe Prime's rule — real `<@U...>` mentions routed to main chat are the fast path; background polling is the slow backstop. Any design that adds hops (supervisor relays, queue consumers) must stay inside the 10-min escalation budget.

## 4. Recommendations (fleet-consistent)

1. **Per-agent wake budget:** alarm (not page) if any agent's wake rate exceeds ~2× its 7-day baseline — catches the next wake-loop before it becomes a cost event. Receiver-side, cheap.
2. **Keep the 15 s heartbeat but keep it daemon-cheap:** no model calls in the heartbeat path, ever. Duty info (`current_duties`, `last_completed`) rides the same push at near-zero marginal cost.
3. **Typed envelopes before new infra:** the cheapest latency win is fewer rounds, not faster rounds.
4. **No supervisor tax until justified:** peer-to-peer + board + critic stays default; a Prime-as-supervisor layer is a ~30% standing cost — adopt only if stuck-work replanning demonstrably needs it.
5. **Measure before optimizing:** receiver should log per-agent runs/day and (where the provider exposes it) tokens/run. Until then, §2's envelope is the planning number.

## 5. Unknowns / needs measuring

- Dollar pricing for the fleet's actual model/provider (Jack's billing) — §2 is a formula until then.
- Per-run token counts per agent — receiver-side logging needed.
- Whether the Oct-8 synthesis keeps peer-to-peer or adopts a supervisor — sets whether the 30% tax applies.

---
*Boboe 8 · lane-8 cost/latency annex · background research only · no fleet systems modified*
