# Lane 3 — Specialization models for the Boboe fleet
Researched 2026-10-07 by Boboe 1. Draft for the noon recommendations doc. Sources linked inline.

Jack's open question this lane answers: "I don't know how to specialize you guys."
Context: 12 agents (Boboe Prime + Boboes 1–11) sharing #all-agentnet, Slack mention routing via the Muse Wall, 5-min slack-watch backstops, telemetry daemons, the fleet-telemetry repo, and cross-org coordination with Darragh Buckley's agents (Neo, Dash, dot).

## The overnight lesson (fleet evidence)

Fixed roles with no leases failed silently tonight. Boboe 2 owned lane 1 and went quiet 00:35–09:02 EDT (~7.5h); Boboe 4 owned lane 5 and produced nothing new between ~04:36 and 09:19 EDT (~5h). Both owned it honestly when Jack asked at 09:02. So: **fixed specialization without heartbeat-and-reclaim works fine until it silently doesn't.** Any model we pick has to survive a Boboe going dark mid-lane.

## The five models, judged against this fleet

### 1. Fixed role specialization (the current default)
One agent owns one domain ("lane 3 is Boboe 1"). Mirrors the claim board's one-owner-per-lane rule.
- Wins: Jack can name who does what; deep context accumulates; accountability is legible.
- Loses: the overnight gaps. Idle capacity sits elsewhere while the owner is dark; single point of failure per lane.
- Verdict: keep as the **default assignment**, but a fixed role must come with a lease (see §6).

### 2. Supervisor / worker (hierarchical)
One coordinator decomposes the mission, dispatches subtasks, integrates results; workers execute. The org-chart model — hierarchical control spreads the coordination burden across layers and scales well for long, multi-stage work (one survey of production systems notes hybrid designs win in practice). Research frameworks show hierarchical planning handling harder tasks gracefully (e.g. AgentOrchestra's hierarchical planner, 82.42% on GAIA).
- Wins: dynamic decomposition at runtime; clear integration point; Boboe Prime is already cast in this role.
- Loses: the supervisor is the funnel — every byte of context flows through it, making it the bottleneck, cost center, and single point of failure (breakpoint analysis from a recent multi-agent orchestration write-up).
- Verdict: use for missions, but **never let the supervisor hold state only in its context** — state goes on the blackboard so a crashed supervisor's mission is resumable by anyone.

### 3. Specialist-as-tool + handoffs (the OpenAI Agents SDK split)
Two distinct primitives: use **agents-as-tools** when a specialist should handle a bounded subtask but must not take over the flow (manager stays in control, owns the final answer); use **handoffs** when the specialist should own the remainder of the turn and respond directly. They compose: triage → handoff to specialist → specialist calls others as tools for narrow subtasks. The SDK's guidance: have specialized agents that excel in one task rather than a general-purpose agent expected to be good at anything.
(https://github.com/openai/openai-agents-python/blob/HEAD/docs/multi_agent.md)
- Wins: no new runtime needed — maps directly onto the typed-envelope handoff format lane 1 is defining; keeps conversations focused; one owner per subtask result.
- Loses: discipline-dependent — free-text handoffs degrade; needs the envelope contract to be real.
- Verdict: **adopt as the delegation grammar.** Every cross-Boboe ask uses the typed envelope `{task_id, to, context, prior_results, heartbeat_at, state}`; the caller owns integration.

### 4. Dynamic claiming with leases (market model)
Tasks posted to a shared registry; any qualified agent claims with an atomic lease + TTL; missed heartbeat → task re-enters the queue automatically. This is the BullMQ worker pattern and the Redis `SET NX EX` + heartbeat recipe already surveyed for the fleet (see the companion harness report, §4). Also matches the "dynamic role allocation / capability-based selection" pattern: systems keep a registry of agent capabilities and match task to agent, with load balancing across available workers.
- Wins: directly answers Jack's "every agent accounted for every 10 minutes" rule; idle Boboes absorb stalled work; no lane ever silently dies.
- Loses: needs the claim registry built; claim races need atomicity (the Redis recipe handles it).
- Verdict: **adopt as the resilience layer.** This is what would have caught the 7.5h lane-1 gap: the lease expires, the task re-queues, someone else picks it up, Jack gets a note.

### 5. Skill-based specialization (specialization lives in artifacts, not identities)
Don't specialize the agents — specialize versioned **Skills**. Every fleet capability (Slack triage, telemetry install, lane playbooks, the 10-min nudge) ships as a Claude Code Skill in a private plugin marketplace: one `/plugin install` updates all 12 Boboes identically, and any Boboe can wear any hat by installing the skill. (Claude Code skills + plugin marketplaces, surveyed in the companion harness report §2.)
- Wins: capability rollout becomes `git pull` + install, not 12 prompt edits; new Boboes onboard by installing the skill set + role card; specialization evolves without re-staffing.
- Loses: skill hygiene becomes the job (versioning, testing); someone owns the marketplace.
- Verdict: **adopt as the primary specialization mechanism.** This is the literal answer to "how do I specialize you": he doesn't — he ships skills, and the claim registry routes them to whoever's awake.

### What the literature says about mixing
Pure centralized or pure decentralized designs rarely satisfy every requirement; most real systems end up hybrid — a hierarchical planning layer sets goals while lower-level agents collaborate through decentralized protocols, or independent agents report periodically to a central aggregator. Also worth stealing: **reviewer–creator pairs** (one agent generates, a second critiques until a quality bar is met) for high-stakes outputs, and **specialization evolution** (periodically promote frequently-needed patterns into skills/new roles).

## Recommendation: hybrid, in this fleet's terms

1. **Named roles stay** (accountability, Jack-addressable), but every role card carries a lease: heartbeat every ≤10 min, miss → role work becomes claimable. Role card = role + goal + tools/skills + escalation path + lease terms.
2. **Claim registry with leases** (fleet-telemetry, Redis-backed): typed envelope per task, atomic claims, TTL requeue. Lane 1's protocol is the contract; the registry is the machine.
3. **Skills marketplace** as the unit of specialization: every capability is a versioned skill; onboarding = install + role card. Assign one lane (or a standing Boboe) a weekly "ecosystem scout" pass to surface new orchestration/observability patterns from the Claude Code ecosystem.
4. **Agent cards (A2A-lite)**: one machine-readable capability card per Boboe — and one per Dara-side agent — so routing works across orgs without Slack archaeology.
5. **Reviewer–creator pairs** for anything Jack will read (decks, the noon doc, outbound messages).
6. **No-go list**: supervisor-only (Prime bottleneck), peer-to-peer-only (coordination overhead, un-debuggable loops), static-roles-only (the overnight gaps, proven).

## Concrete next steps (Phase 0 order)
1. Write the role-card template + fill it for all 12 Boboes (one owner, Prime).
2. Stand up the claim registry in fleet-telemetry (Redis on the Mac; heartbeat keys `agent:heartbeat:<name>`).
3. Publish the first three skills (slack-triage, telemetry-install, lane-playbook) to the private marketplace.
4. Post agent cards for the fleet; request Dara-side cards for Neo/Dash/dot.
5. Weekly ecosystem scout cron.

## Caveats
- Web sources are surveys/roundups (2025–2026), not controlled studies; framework benchmark numbers are self-reported.
- Fleet evidence (the overnight gaps) is n=1 from one night of Slack/email history — real, but anecdotal.
- Decisions D1–D14 and the §5 build order still need Jack's rulings (per Boboe 4's reconciliation); this writeup feeds but does not replace them.
