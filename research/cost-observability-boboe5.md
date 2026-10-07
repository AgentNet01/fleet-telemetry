# Swarm cost & observability lane — Boboe 5 research

**Lane:** 8 — cost/latency, onboarding, observability for long-running autonomous swarm operation (12 agents: Boboe Prime + Boboe 1–11).
**Repo state researched:** AgentNet01/fleet-telemetry @ 838247e. **Date:** 2026-10-07.
**Constraint honored:** research only — no Slack posts, no config changes.

Related lanes (not duplicated here): Boboe 5 lane 6 (cron/repo/tooling — the task ledger, roll-call, and budget-envelope proposals this report builds on), Boboe 2 lane 1 (comms/coordination). This report stays on cost tracking, observability design, and resource usage; scheduling mechanics live in lane 6.

---

## 1. Current-state inventory (as of 838247e)

### 1.1 What we already ship

| Signal | Source | Cadence | Where it lands |
|---|---|---|---|
| Liveness (`last_seen`) | daemon push | 15s | receiver per-agent record |
| `health` block (post/mailbox ok-fail, last error, daemon start) | `telemetryd.py` | 15s | receiver history |
| Per-hook runs/wakes/errors (last hour) | `~/hooks/logs/*.jsonl` | 15s | receiver history |
| Compute (cpu, mem, disk) | daemon payload | 15s | receiver history |
| `missed_mentions` | receiver-computed | on push | receiver record |
| Dashboard | `orchestrator/dashboard.html` | read-only | Jack's screen |

### 1.2 What we do NOT have (the gaps)

- **Zero cost visibility.** No token counts, no per-task spend, no budgets. Nobody can answer "what did last night cost?"
- **No task-success signal.** The dashboard shows alive/dead. It cannot distinguish "working productively" from "spinning" — the lane-6 finding that silent stalls beat crashes.
- **No anomaly detection.** Only raw numbers; nothing computes baselines or flags deviations.
- **No resource-growth tracking.** Spool files, `~/hooks/logs/*.jsonl`, `~/inbox/slack/done/` grow unbounded; nothing measures or prunes them automatically (lane 6 proposed a hygiene cron; this report adds the *measurement* side).
- **No cost governance.** Even if we could see spend, nothing enforces limits.

**The honest constraint on cost tracking:** these agents run on the Muse platform, where per-model-call token usage is not directly visible to the agent itself. We cannot do what Langfuse/Helicone do (wrap every LLM call and count tokens). Our cost model must therefore be **proxy-based**: count the things we *can* see (worker runs, tool calls, cron executions, wall-clock time) and map them to cost estimates. This is less precise than true token metering, but it is the correct architecture for our position in the stack — and proxies are sufficient for budgets, spike detection, and routing decisions.

---

## 2. Cost tracking — what to measure and how

### 2.1 The proxy cost model

Since we cannot meter tokens directly, define cost in **observable units**:

| Unit | What it proxies | Measurable how |
|---|---|---|
| **Worker run** | one agent-session of work (the dominant cost driver) | cron/hook spawn counts + wall-clock duration |
| **Tool call** | API/model invocations inside a run | hook logs, daemon-tracked exec counts |
| **Cron execution** | scheduled background work | cron runtime (already exists per run) |
| **Task iteration** | one unit of long-task progress | `tasks/` ledger `progress.json` iteration counter (lane 6) |

**Cost formula (v1, deliberately simple):**
```
task_cost ≈ iterations × avg_cost_per_iteration(agent)
```
where `avg_cost_per_iteration` is calibrated per agent from historical data (wall-clock time × a platform cost rate Jack sets once). This will not match the invoice to the cent. It does not need to — it needs to support *budgets, comparisons, and spike detection*, which only require consistent relative measurement.

**What not to do:** do not build a fake-precise token estimator. False precision is worse than honest proxies; it invites gaming and distrust. Report proxy costs with the unit labeled ("~42 worker-runs", not "$3.17").

### 2.2 Per-agent and per-task attribution

- **Per-agent:** the daemon already ships a per-agent payload every 15s. Add a `work` block: `worker_runs_1h`, `tool_calls_1h`, `cron_runs_1h`, `task_iterations_1h` (read from local counters the daemon maintains). The receiver aggregates into per-agent daily/weekly summaries. This gives Jack "Boboe 7 did 3× the work of Boboe 3 this week" — the first-order cost question.
- **Per-task:** the lane-6 `tasks/` ledger already has `progress.json` with an iteration counter. Add `cost_proxy: {worker_runs, wall_clock_s}` updated each iteration. Task cost = sum over iterations. When Boboe 2 rolls up the mission, each lane's report can carry its measured cost — "lane 6 research: 14 iterations, ~6 worker-hours."
- **Dimensions to slice by** (from the fleet-observability literature): agent, task, time window, and — once it exists — model tier (see §2.4).

### 2.3 Budget alerts and throttles (observability vs governance)

The industry has learned a sharp distinction (AgentCost, 2026): **observability shows what happened; governance prevents what is allowed to happen.** Dashboards cannot stop a runaway loop. We need both layers:

**Layer 1 — Observability (alerts, reactive):**
- **Cost spike alert:** per-agent proxy cost >3× its 24h rolling average for 10+ minutes → dashboard badge + Wall mention to Jack. (This is the standard `rate(cost[5m]) / rate(cost[24h]) > 3` pattern from the Prometheus/AI-observability literature.)
- **Budget burn alert:** task at >80% of its `SPEC.md` budget envelope → amber; at 100% → red + auto-pause (already proposed in lane 6 §6.3; this is the enforcement hook).
- **Idle-spend alert:** agent with high worker-run counts but zero task-ledger heartbeats → "spinning, not producing" (the silent-stall detector, cost-flavored).

**Layer 2 — Governance (hard limits, proactive):**
- **Iteration caps are hard stops, not suggestions.** Lane 6 proposed budget envelopes in `SPEC.md` (max iterations, max wall-clock days). The task-sweep enforces them mechanically: cap reached → task auto-pauses, no new workers spawn. This is the single highest-leverage cost control: it bounds the worst case for every long task.
- **Cron backoff on repeated failure.** A cron that fails 3 consecutive runs backs off (5min → 15min → 1h) until a success resets it. Tonight's evidence: the old Slack-watch cron hit 26 consecutive timeouts, each burning a full worker run. Backoff would have cut that waste by ~80%.
- **No unbounded loops, ever.** Ralph's iron law, made mechanical: every loop (cron, worker-spawn, retry) declares its stop condition and max iterations in its definition. A `test/` lint checks cron bodies for unbounded constructs (lane 6 §5.2 S5 extends naturally to cost).

**Design principle:** alerts go to the dashboard (Jack's screen), not to Slack #all-agentnet. Cost chatter in the coordination channel is noise; cost *state* on the dashboard is signal. This matches the lane-6 roll-call alerting rules (state-change only, digest not drip).

### 2.4 Cost-efficient model routing

The literature consensus (FrugalGPT pattern, 2026 surveys): most agent workloads are a mix of trivial and hard work served by one expensive model. Routing cuts spend 40–80% with no perceived quality loss. Two patterns:

1. **Router (pick tier up-front):** a cheap classifier picks small/medium/frontier per request. One model call, low latency. Best when task types are known.
2. **Cascade (try cheap first, escalate on low confidence):** try the small model; if confidence is below threshold, escalate. Corrects misroutes; very high savings on easy traffic.

**Tier map for our fleet:**

| Tier | Use for | Examples of our work |
|---|---|---|
| Small / cheap | Classification, ack replies, format fixing, inbox triage, log rotation | Slack backstop triage, hygiene cron, mention filing |
| Medium | Summarization, extraction, routine research legs | Single-lane research drafts |
| Frontier | Multi-step reasoning, ambiguous tasks, roll-ups, novel problems | Boboe 2's synthesis, Jack-facing decisions |

**Concrete application to our fleet:** the 5-minute `slack-watch` backstop and the hourly `task-sweep` are *triage* workloads — small-tier appropriate. Lane research and roll-up synthesis are *reasoning* workloads — frontier-appropriate. Today everything runs at whatever tier the platform defaults to. **Proposal:** label each cron/hook with its intended tier (`tier: small` in the cron definition); when the platform supports tier selection, the mapping is already declared. Until then, the label documents intent and lets Jack audit "are we spending frontier on triage?"

**Quality floor rule** (from the routing literature): always establish a quality floor before routing down. Routing without measurement is cost-cutting, not optimization. For us: the verifier pattern (lane 6 §6.2) *is* the quality floor — a cheaper tier's output still passes independent verification before it counts as done.

**What not to do:** do not build a dynamic router now. Static tier labels on crons + the verifier as quality gate capture most of the value with none of the complexity. Add dynamic routing only when measured data shows the static map is wrong.

---

## 3. Observability — what matters for a swarm

### 3.1 The three questions a fleet dashboard must answer

From the agent-fleet observability literature (AI Builders Network, 2026): a useful fleet dashboard answers three questions fast — **are agents healthy, are they correct, and what are they costing?** Our current dashboard answers only the first.

**Proposed dashboard sections (in priority order):**

1. **Task success (new).** Per-task status from the `tasks/` ledger: on-track / stalled / blocked / done-verified. This is the top of the dashboard because *uptime tells you the agent responded, not that it helped* — a fleet can be 100% available and still failing the actual job.
2. **Agent liveness (exists).** The current 12-tile wall: alive / quiet / dark with the lane-6 roll-call thresholds (3min amber, 10min red).
3. **Cost (new).** Per-agent proxy cost (worker-runs/day, task-iterations/day) next to per-agent task completions — **cost per successful task per agent**. The literature is emphatic: cost and quality must be on the same screen, because they trade off. An agent that got cheaper by getting worse must be visible; so must the one worth its premium.
4. **Anomalies (new).** Not raw numbers — *deviations*: cost spikes, stall detections, version drift, hook disappearances. One digest line per anomaly class, not a drip of events.

### 3.2 Metrics that matter (beyond uptime)

| Metric | Why it matters | Source |
|---|---|---|
| Task success rate (verified completions / tasks) | The actual job; uptime is a prerequisite, not the goal | `tasks/` ledger + verifier signatures |
| Cost per successful task (proxy units) | Efficiency; spots the expensive way of being right | ledger `cost_proxy` ÷ verified completions |
| Stall rate (tasks hitting `stale_count≥2` / week) | Silent-stall frequency — the top long-horizon failure mode | task-sweep |
| Verifier rejection rate | Quality signal; a lane with 40% rejections has a spec problem, not a worker problem | verifier signatures |
| Daemon version drift (agents not on latest) | Rollout health; tonight's 8-deploy evening showed this matters | payload `daemon` version (exists) |
| Hook coverage (expected vs present hooks) | Catches accidental disables (lane 6 §5.2 S4) | payload hook stats (exists) |
| Spool/log growth rate (MB/day/box) | Storage exhaustion is a slow crash | daemon disk stats (exists) + new per-dir sizes |

### 3.3 Anomaly detection (not just failures)

Failures are easy; the dangerous states are silent. Detection rules, all receiver-side (no new agent code beyond the `work` block in §2.2):

- **Cost spike:** `rate(proxy_cost[5m]) / rate(proxy_cost[24h]) > 3` for 10m → warn. Catches runaway loops before the invoice.
- **Behavioral drift:** per-agent task-success rate drops >20 points week-over-week → investigate. Agents degrade with no code change (provider updates, tool API shifts, prompt drift).
- **Load imbalance:** one agent doing >40% of fleet worker-runs while others idle → rebalance or investigate (the "Agent-5 does everything" pattern).
- **Silent quality decay:** verifier rejection rate rising while task completion rate holds → the fleet is "succeeding" at worse work.
- **Version drift:** any agent >2 daemon versions behind latest for >48h → nudge (dashboard badge, not a page).

**Alerting rules (shared with lane 6):** state-change only (fire on transitions, never repeat); dashboard first, Wall mention to Jack for red; digest, not drip; hysteresis on clear; deploy-quiet suppression. Cost alerts follow the same discipline as liveness alerts — one system, not two.

### 3.4 Traces: what "drill-down" means for us

The literature says a fleet view that cannot drill into a single run is just a status page. For our architecture, drill-down is:

**Fleet view → agent → task → iteration → evidence.**

- Fleet view: 12 agents, task states, cost digest (dashboard).
- Agent: per-agent history (receiver already stores full per-agent history — expose it).
- Task: `tasks/<id>/` directory — SPEC.md, progress.json, findings.jsonl, log.jsonl (lane 6; already machine-readable).
- Iteration: git log for the task branch + the worker's commit messages.
- Evidence: the actual files, not a reconstructed narrative.

We do not need a separate tracing system (Jaeger, Langfuse). **Git + the task ledger + the receiver history ARE our trace.** The requirement is only that the dashboard *links* down this chain — every aggregate clickable to the underlying files. This is a dashboard feature, not new infrastructure.

---

## 4. Resource usage — compute, quotas, storage

### 4.1 Compute (mostly covered)

The daemon already ships CPU, memory, and disk stats every 15s. Gaps to close:

- **Per-cron CPU attribution:** which cron/hook is burning cycles? Add `top -bn1` snapshot (top 3 processes by CPU) to the daemon's compute block once per hour, not every push (cheap, sufficient).
- **No new infrastructure needed.** The data exists; the dashboard needs a "resources" tab.

### 4.2 API quotas (the invisible cliff)

Three quota surfaces the fleet touches:

| Surface | Limit class | Failure mode tonight | Mitigation |
|---|---|---|---|
| Slack API | rate limits per workspace | none observed, but 12 agents posting could hit it | centralize: agents never post health; only Jack-facing replies go through Slack |
| GitHub API | 5,000 req/hr per token | none observed | `git pull` in daily hygiene is cheap; avoid API polling loops |
| Model provider | concurrency / TPM limits | not directly visible | backoff on retry (see §2.3); cascade patterns reduce peak demand |

**Rule:** no agent polls any API on a loop tighter than 60s without Jack's explicit approval. Polling loops are how fleets DDoS their own tooling.

### 4.3 Storage growth (the slow crash)

Observed growth vectors on each box:

| Path | Growth rate (observed) | Current mitigation | Proposed |
|---|---|---|---|
| `~/hooks/logs/*.jsonl` | unbounded (every hook run appends) | none | rotate past 10k lines in daily hygiene cron (lane 6 P-D) |
| `~/inbox/slack/done/` | ~1 file per mention handled | none | prune >7 days in hygiene cron (lane 6 P-D) |
| Telemetry spool (`~/telemetry/spool/`) | spikes during receiver outages (observed 764KB / 7 files on one box) | retry with flush | alert at >10MB (dashboard badge); auto-purge >50MB oldest-first (data already on Jack's dashboard if it ever flushed) |
| `~/workspace` (task workdirs, research) | grows with activity | none | per-task `du` in task-sweep; flag tasks >1GB |
| Receiver-side history | 15s × 12 agents × forever | none observed | downsample: full resolution 7d, hourly rollups 90d, daily beyond (receiver-side, Jack's Mac has the disk) |

**Measurement first:** add per-directory sizes (`du -sb` on the five paths above) to the daemon's hourly compute snapshot. You cannot manage what you do not measure; this is one line of shell.

---

## 5. Onboarding (lane 8's third leg)

Lane 8 as chartered includes onboarding. The lane-6 report proposed `agents/fleet_setup_prompt.md` (exists) and `docs/SECURITY.md` (proposed). Additions specific to cost/observability onboarding:

- **Every new agent gets a cost identity on day one:** its daemon ships the `work` block from its first push; the receiver creates its cost baseline after 24h. No agent is ever "unmeasured."
- **Onboarding checklist** (add to `fleet_setup_prompt.md`): (1) install daemon, (2) verify first push on dashboard, (3) confirm tier labels on its crons, (4) read the task-ledger convention, (5) know the budget-envelope rule. Five items; the dashboard verifies 1–2 automatically.
- **The dashboard is the onboarding document.** A new agent (or Jack, reviewing) should be able to answer "what does this fleet do, how healthy is it, what does it cost?" from the dashboard alone. Every metric in §3.2 that is not on the dashboard is a documentation gap.

---

## 6. Highest-leverage improvements (ranked)

1. **Proxy cost model + `work` block in daemon payload** (§2.1–2.2). ~30 lines of daemon code. Unlocks per-agent cost, per-task attribution, and every alert below. Nothing else works without measurement.
2. **Hard budget envelopes + iteration caps enforced by task-sweep** (§2.3, lane 6 §6.3). Bounds the worst case for every long task. This is governance, not observability — it *prevents* the runaway, not just reports it.
3. **Cron backoff on repeated failure** (§2.3). ~15 lines in the cron wrapper. Tonight's 26-timeout cron would have cost 80% less.
4. **Dashboard: task-success + cost-per-task sections** (§3.1). Receiver/dashboard-side only; no agent changes. Turns the dashboard from a status page into a management tool.
5. **Storage measurement + hygiene cron** (§4.3, lane 6 P-D). One `du` line + the already-proposed prune cron. Prevents the slow crash.
6. **Static tier labels on crons** (§2.4). Documentation today, routing substrate tomorrow. Zero runtime cost.

---

## 7. Concrete proposals (deployable; exact steps)

### P-A. `work` block in daemon payload (agent-side; each box)

1. In `agents/telemetryd.py` `build_payload()`: add `"work": {"worker_runs_1h": N, "tool_calls_1h": N, "cron_runs_1h": N, "task_iterations_1h": N}`. Counters maintained in `~/telemetry/work_counters.json`, incremented by a 5-line wrapper each cron/hook sources (or by parsing `~/hooks/logs/*.jsonl` — already structured).
2. Bump payload `"daemon"` version int (receiver labels, never rejects).
3. Receiver: aggregate into per-agent daily summaries (`cost_proxy_daily`); expose on dashboard.
4. Verify: confirm the `work` block appears in the next push; check the receiver stores it.

### P-B. Budget envelopes enforced (task-sweep; pairs with lane 6 P-B)

1. `tasks/<id>/SPEC.md` declares `budget: {max_iterations: N, max_wallclock_days: D}` (lane 6 format; this proposal adds enforcement).
2. Hourly `task-sweep` (lane 6 S2): if `iteration > max_iterations` or `now - created > max_days`: set `status: paused-budget`, stop spawning workers, Wall-mention Jack with the ledger summary (iterations, cost proxy, last findings).
3. Cost-spike check in the same sweep: per-task `rate(cost_proxy[1h])` vs task lifetime average; >3× → flag `anomaly: cost-spike` in `progress.json` (dashboard surfaces it).
4. Verify: canary task with `max_iterations: 3`; confirm auto-pause after 3.

### P-C. Cron backoff wrapper (agent-side; 15 lines)

1. New `agents/cron_backoff.sh`: wraps any cron body; on failure increments `~/telemetry/cron_fail_count/<cron-id>`; on success resets to 0. Sleep schedule: 0 fails → run now; 1 → +5min; 2 → +15min; ≥3 → +60min (skip runs until backoff elapses).
2. Apply to `slack-watch` and `task-sweep` first (the two crons with observed failure modes).
3. The daemon's `work` block reports `cron_runs_1h` *and* `cron_skipped_backoff_1h` — skipped-by-backoff is visible, not silent.
4. Verify: force 3 failures on a canary cron; confirm backoff engages and the dashboard shows skips.

### P-D. Dashboard cost + task sections (receiver-side; Jack's Mac)

1. `orchestrator/dashboard.html`: add two tabs — "Tasks" (from `tasks/` ledger via a new receiver endpoint; states: on-track/stalled/blocked/done-verified) and "Cost" (per-agent proxy cost/day, cost per verified task, 7-day trend sparkline).
2. Every aggregate links down the drill chain: agent → history → task dir → git log (§3.4).
3. New receiver endpoint `/api/tasks` serving the ledger summary (reads the fleet repo's `tasks/` — the receiver runs on Jack's Mac where the repo lives).
4. Verify: with one canary task in the ledger, confirm it renders with cost and drill-down links.

### P-E. Storage measurement (daemon-side; one line)

1. Hourly (not every push): `du -sb ~/hooks/logs ~/inbox/slack/done ~/telemetry/spool ~/workspace` → add to compute block as `dir_sizes`.
2. Receiver: alert (dashboard badge) when any box's spool >10MB or total workspace >5GB.
3. Pairs with lane 6 P-D (hygiene cron does the pruning; this proposal does the measuring).
4. Verify: confirm `dir_sizes` appears in hourly payload; check dashboard badge fires on a synthetic large spool.

### P-F. Tier labels (convention; zero code)

1. Every cron definition and hook gets a header comment: `# tier: small|medium|frontier` (intended model tier for the work).
2. Initial mapping: `slack-watch` → small; `task-sweep` → small; `fleet-hygiene` → small; lane research workers → medium; roll-up synthesis → frontier.
3. `research/INDEX.md` documents the tier map and the quality-floor rule (§2.4).
4. No enforcement today; when the platform supports tier selection, the labels become the routing table.

---

## 8. Open questions

1. **Platform cost rate:** the proxy-to-dollar conversion needs one number from Jack (or the platform): cost per worker-run-hour. Without it, we report proxy units only — sufficient for budgets and comparisons, insufficient for invoices.
2. **Who owns the receiver-side work?** P-D (dashboard) and the anomaly-detection rules run on Jack's Mac. Either Jack implements, or he grants a lane owner SSH/deploy access to the orchestrator. This is a Jack decision.
3. **True token metering:** if the platform ever exposes per-call usage to the agent, replace the proxy model with real token counts (the `work` block schema should carry a `unit: proxy|tokens` field from day one to allow the migration).
4. **Cross-lane cost attribution:** when Boboe 2's roll-up synthesizes 8 lanes, whose budget does the synthesis cost hit? Proposal: the *requesting* task's budget (the roll-up is part of the mission task), not the synthesizing agent's personal tally.

---

## 9. Sources

- Anthropic, "Effective harnesses for long-running agents" (2025-11-26): https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- AgentCost, "AI Agent Budget Bounds, Not Dashboards" (observability vs governance): https://github.com/agentcostin/agentcost/blob/HEAD/docs/blog/posts/ai-agent-budget-bounds-not-dashboards.md
- AWS Builders, "Per-Agent Cost Tracking for Multi-Agent AI" (trace-span cost attribution): https://dev.to/aws-builders/per-agent-cost-tracking-for-multi-agent-ai-on-aws-10eg
- Model routing cascade skill (router vs cascade patterns, tier maps): https://github.com/swapnilpopat/ai-assistant-skills/blob/HEAD/skills/engineer/engineer-toolkit/model-routing-cascade/SKILL.md
- DevOps-Daily, "Knowing What Your AI Feature Costs Before Finance Does" (wrapper metering, Helicone/Langfuse/Portkey tagging): https://devops-daily.com/posts/ai-feature-cost-before-finance-does
- Brainforge, "Why AI observability is the layer your agents cannot skip" (Langfuse v4 evals, cost-on-observation): https://brainforge.ai/blog/why-ai-observability-is-the-layer-your-agents-cannot-skip/
- AI Builders Network, "What Belongs On An Agent Fleet Observability Dashboard" (task success first, cost next to quality): https://aibuildersnetwork.org/api/expert-insights/what-belongs-on-an-agent-fleet-observability-dashboard/export-pdf
- Prefactor, "How to Monitor AI Agents in Production" (5-step monitoring, per-agent alerts, eval feedback loop): https://prefactor.tech/learn/agent-monitoring
- Dev.to, "AI Agent Security: 4 Failure Modes That Are Not Prompt Injection" (Denial-of-Wallet, retry-loop cost): https://dev.to/markfulton/ai-agent-security-4-failure-modes-that-are-not-prompt-injection-56h2
- DevToolLab, "Best LLM Observability Tools 2026" (Langfuse/Helicone/Braintrust/Phoenix/LangSmith comparison): https://devtoollab.com/blog/best-llm-observability-tools
- Fleet repo (private): AgentNet01/fleet-telemetry @ 838247e — `agents/telemetryd.py`, `orchestrator/fleet_receiver.py`, `orchestrator/dashboard.html`
