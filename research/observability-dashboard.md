# Fleet Dashboard & Observability — Research Report
**Date:** 2026-10-07 · **Lane:** Dashboard/Observability (accountability/heartbeat lane owned by Boboes 7, 10, 5 — not covered here except where the dashboard must surface their data)
**Fleet:** 12 agents (Boboe Prime + Boboes 1–11), one Linux VM each, Python `telemetryd` daemon pushing to a central receiver + `dashboard.html`, Slack as the human coordination channel.

---

## 0. Key findings (the short version)

1. **The industry has converged on what to measure.** The seven metrics worth tracking first: task success rate, human escalation rate, **cost per successful run**, p95 latency, tool error rate by tool, retry/loop count per run, quality score trend. If we track only these well, we're ahead of most agent teams. (Anna Jey, Apr 2026)
2. **Cost per outcome is the headline metric, not token counts.** Raw token counts are noise; cost-per-resolved-task collapses spend, retries, and model choice into one health signal. Our current telemetry collects **zero cost data** — this is the single biggest gap. (AI Builders Network, fleet-dashboard guidance)
3. **"Spinning" is detectable with cheap heuristics — no ML required.** The proven signals: identical tool-call repetition (hash `(tool, args)`, 3× in a 12-call window), no-progress windows (no file changes/commits/replies while marked working), same-error-signature thrash (≥2 consecutive), and token-velocity-without-progress. These all run server-side on data we mostly already collect.
4. **Trace, don't just log.** Every dashboard number should drill into a trace (tool calls, token breakdown, errors per step). A number you can't click into is a dead end during an incident. Observability for agents is tracing-first, dashboards-second.
5. **Tag every span by agent identity.** Stamp all telemetry with agent id, version, session. Untagged telemetry at fleet scale is unsearchable — the dimension you forgot to tag is the one you'll need in the incident.
6. **OpenTelemetry's GenAI semantic conventions are the stable contract.** `gen_ai.*` spans (`create_agent`, `invoke_agent`, `execute_tool`, `chat`) with standard usage attributes. Emit once via OTLP, route to any backend later — no vendor lock-in.
7. **Our current setup is a good skeleton.** telemetryd (15s pushes, spool-on-failure, connection health) + dashboard.html (machine rail, activity feed, Slack-mention answered/missed tracking) is further along than most day-one fleets. What's missing is the *semantic* layer: cost, task progress, and spin detection.

---

## 1. What the dashboard should show (12 agents)

### Screen 1 — Fleet health strip (the 10-second glance)
The first screen must answer **"is the fleet healthy, expensive, or wrong"** in one glance. A 12-cell grid, one cell per agent:

| Field | Source | Why |
|---|---|---|
| Status badge: `working` / `idle` / `stuck?` / `stale` / `down` | Derived (see §3) | The single most-looked-at element |
| Current task (one line) | New: agent-written `~/workspace/current_task.md` or task field in push | Without this, "working" is meaningless |
| Last progress marker (e.g. "commit 2h ago", "replied 5m ago") | Derived from file changes / commits / Slack replies | Distinguishes working from spinning |
| Last push age | Already have | Dead-man visibility (mechanism is the accountability lane's job; the dashboard surfaces it) |
| Cost today | New: token usage × pricing | The "expensive" in "healthy, expensive, or wrong" |
| Spin flag | Derived (§3) | Loud badge, not a subtle icon |

### Screen 2 — Per-agent detail (drill-down)
- **Task progress:** checklist state. Convention: each agent keeps `~/workspace/tasks/<task-id>/` with `TASK.md` + `PLAN_AND_PROGRESS.md` (numbered checklist with status markers) + `FINDINGS.md`. This is the proven pattern from real Claude fleets (LinkedIn "one Claude agent to a fleet" write-up; Anthropic's own harness uses `claude-progress.txt`). The daemon ships the checklist summary; the dashboard renders progress bars.
- **Activity timeline:** what the agent did (we have "Everything the AI did" — keep it, add tool-call counts per hour).
- **Cost trajectory:** tokens/hour and $/day charts, with per-task attribution when possible.
- **Slack accountability:** we already track "Named in Slack: answered/missed within 30 min" — keep, and add response-time distribution.

### Screen 3 — Alerts feed (append-only, newest first)
- Agent stale (no push > N min) — data from accountability lane
- Spin detected (heuristic fired — §3)
- Cost spike (agent's $/hour > 3× its 7-day baseline)
- Error burst (tool error rate spike)
- Missed Slack mention (no answer within 30 min — we have this)
Each alert links to the agent's detail screen. Alerts are *derived server-side* in the receiver, not computed in the browser.

### What NOT to put on the dashboard
- Raw log tails at 15s cadence (noise; keep logs queryable, not displayed)
- Per-keystroke or per-file-change firehoses (sample: "recently changed files, last 5 min" is fine — we have it)
- Duplicate views of the same data in three places (our dashboard.html is 1135 lines; audit for redundancy before adding)

---

## 2. Telemetry: signal vs noise

### Collect (signal)
| Signal | Cadence | Why it matters |
|---|---|---|
| Liveness ping (agent id, ts, daemon uptime) | 15s (keep) | Dead-man foundation; tiny payload |
| Connection health (post/mailbox ok-fail, last error) | 15s (keep — already have) | Distinguishes "agent dead" from "link dead" |
| Token usage in/out per window | 60s aggregate | **The missing metric.** Enables cost-per-outcome, budget alerts, spin-via-cost-velocity |
| Tool-call counts by tool name + error count | 60s aggregate | Separates model issues from integration issues; feeds repetition detection |
| Current task id + checklist summary | 60s (on change) | Makes "working" meaningful |
| Last-meaningful-output timestamps (last file change, last commit, last Slack reply) | 60s | Core input to spin detection |
| Context window occupancy % | 60s | Predicts coherence decay; triggers fresh-start recommendations (Anthropic: compaction alone is insufficient — deliberate harness artifacts needed) |
| Hook/cron run stats | 60s (keep — already have) | We have this; keep |

### Don't collect at push cadence (noise)
- Full file listings every 15s → sample every 5 min or on-demand ("browse files" we already have)
- Raw stdout/stderr streams → keep local, ship on alert or on drill-down
- Per-message Slack payloads → the receiver already routes these; dashboard needs aggregates (answered/missed counts), not content

### Alert on (not just display)
1. **Staleness:** no push in 3× interval → `stale`; 10 min → `down` (thresholds are the accountability lane's call; dashboard renders)
2. **Spin:** any §3 heuristic fires → `stuck?` badge + alert-feed entry
3. **Cost:** $/hour > 3× baseline, or daily budget % consumed (budgets need Jack to set per-agent $/day caps — recommend starting here)
4. **Missed mention:** named in Slack, no answer in 30 min (already tracked — promote to alert feed)
5. **Error burst:** tool error rate > threshold over 15 min window

### The hard lesson from production incidents
A 4-agent loop burned **$47,000 over 11 days** because the team had logging and monitoring but **no hard spend ceiling**. A separate incident had an agent spin up duplicate cloud stacks on every retry ($6,531/day). The consensus fix is **pre-call admission control / hard kill-switches, not after-the-fact alerting**. Translation for us: per-agent daily $ budgets with a hard stop (daemon refuses to start new work / pages Jack) matter more than any dashboard panel. Dashboard shows the burn; the budget enforces it.

---

## 3. Spinning vs working: concrete detection heuristics

"Spinning" = busy but unproductive. All of these are implementable **server-side in the receiver** from telemetry we have or can add cheaply. None require ML.

### Heuristic 1 — Tool-call repetition (cheapest, highest precision)
Hash each tool call as `(tool_name, canonicalized_args)`; keep a rolling window of the last 12 calls. **3 identical hashes in the window → flag.** Escalation: 6× → stronger flag. (Source: the `mcode` agent-loop spec — "thrash detection: repeat_limit=3, window=12; the mechanism is the design, the numbers are calibration.")
*Needs:* tool-call stream from the agent. Currently NOT collected — add lightweight tool-call counters (tool name + arg hash, not full args) to the daemon's 60s aggregate.

### Heuristic 2 — No-progress window
Agent marked `working` but **no file changes, no commits, no Slack replies, no checklist advance for N minutes** (N=30 suggested) → `stuck?` flag.
*Needs:* last-output timestamps (we have file-change times; add commit times + checklist state). This is the single most useful spin signal and it's almost free.

### Heuristic 3 — Error thrash
**≥2 consecutive failures with the same error signature** (same tool + same error class) → flag. (Source: `histore/agent-skills` tiebreaker skill: "Build/Test Thrashing".)
*Needs:* tool error counts by signature — add to the 60s aggregate.

### Heuristic 4 — Oscillation / flapping
File content reverted to a previous state within N minutes, or the agent switches between two opposing approaches (detectable via commit diffs undoing each other). → flag.
*Needs:* git-aware daemon (we're a git repo fleet — `git log --stat` per agent box is cheap).

### Heuristic 5 — Cost velocity without progress
Tokens/minute above threshold **while** Heuristic 2's no-progress condition holds → loud flag + budget-check. This is the $47k-incident detector.

### Heuristic 6 — Semantic stagnation (v2, needs embeddings)
Cosine similarity of consecutive plan/status summaries > 0.95 for 2+ steps → stuck. (Source: dev.to circuit-breaker write-up.) Cheap variant already available: **gram-containment** — a stuck agent restates the previous step's material and appends a sentence; containment of the smaller gram set catches it where Jaccard similarity wouldn't. (Source: `argszero/cordis-plugin-thinking-loop-guard`.) Defer to v2; heuristics 1–5 cover 90%.

### What "stuck?" triggers
Dashboard badge + alert feed entry. **Not** an automatic kill — Jack (or a supervisor agent) decides. But the flag must be loud and must link to the evidence (the repeated calls, the idle window). "Can you reconstruct what the agent intended, what it did, why it diverged, within five minutes? If yes, you have observability. If no, you have logging."

### The exit-condition principle
"Raising the max iteration count doesn't solve a retry loop — it only makes the loop more expensive. The exit needs to be based on **progress**." Every long task needs a machine-checkable definition of done and a progress signal (tests passing, checklist advancing, files changed). The dashboard's job is to show progress-or-absence; the harness's job is to stop on absence.

---

## 4. Concrete tools/repos (exist today)

| Tool | Link | What / verdict |
|---|---|---|
| **Langfuse** | https://github.com/langfuse/langfuse (MIT) | Open-source trace + eval + prompt-management + cost tracking; OTel-native; **self-hosts via docker-compose** (Postgres + ClickHouse). **ADOPT** — the strongest open default for trace-level fleet observability. Run on one VM; point OTLP at it. |
| **OpenTelemetry GenAI semconv** | https://opentelemetry.io/docs/specs/semconv/gen-ai/ | The emerging standard: `gen_ai.*` spans (`invoke_agent`, `execute_tool`, `chat`), standard usage attributes. **ADOPT as the telemetry contract** — emit from the daemon via OTLP; stay backend-agnostic. |
| **agent-trace pattern** | https://github.com/Siddhant-K-code/agent-trace | Hooks → local NDJSON journal → OTLP export, with secret redaction; includes an MCP server letting a debugging agent query its own history. **STEAL** — zero-dependency Python, exactly our stack. |
| **Arize Phoenix** | https://github.com/Arize-ai/phoenix | OSS trace viewer, OTLP-native, single-container. **Sidecar** next to Langfuse for trace visualization / drift analysis. |
| **Claude Agent SDK hooks** | https://github.com/anthropics/anthropic-cookbook (claude_agent_sdk) | The sanctioned capture points: SessionStart, PreToolUse, PostToolUse, Stop. **STEAL** the hook model for our own daemon instrumentation. |
| **Grafana** | https://grafana.com/oss/ | The default self-hosted metrics dashboard. Our custom `dashboard.html` is fine for the fleet-specific view; use Grafana if we outgrow it or want standard PromQL alerting. **Defer** unless needed. |
| **Helicone proxy pattern** | https://github.com/Helicone/helicone | LLM gateway proxy: swap one URL, get logging + cost tracking with ~zero code changes. **STEAL the idea** — a logging proxy in front of model APIs is the fastest fleet-wide cost capture if per-agent instrumentation lags. |
| **LangSmith / AgentOps / Braintrust** | SaaS | Best-in-class UIs but SaaS-only or enterprise-gated self-host. **SKIP** — we own our VMs; Langfuse covers it. |

**Do not adopt:** full agent frameworks (LangGraph/CrewAI/AutoGen) for observability alone — we're a fleet of independent agents, not a single graph; steal their *patterns* (checkpointer model, guardrails-as-tripwires) without the framework weight.

---

## 5. What to change in our current setup

### telemetryd (agents/telemetryd.py, ~787 lines)
1. **Add token usage + cost (highest priority).** Per-60s aggregate: `tokens_in`, `tokens_out`, estimated USD (pricing table in config). Without this, cost-per-outcome and budget enforcement are impossible. If per-agent API metering is hard, deploy the Helicone-style logging proxy as the interim capture point.
2. **Add tool-call telemetry.** Per-60s: counts by `(tool_name, arg_hash)` + error counts by signature. Feeds Heuristics 1 & 3. Ship hashes, not full args (keeps payloads small, avoids secret leakage).
3. **Add current-task + checklist state.** Read `~/workspace/tasks/<id>/PLAN_AND_PROGRESS.md` (or a `current_task.json` the agent maintains); ship `{task_id, done/total, last_update}`. Makes "working" meaningful on the dashboard.
4. **Add context occupancy %.** If instrumentable, else estimate from session token counts.
5. **Split the payload:** tiny liveness ping @15s (id, ts, uptime, connection health); rich aggregate @60s (everything above). Keeps the 15s path cheap and the dashboard fresh.
6. **Emit OTel `gen_ai.*` spans via OTLP** (alongside the existing JSON push) — one code path, backend-agnostic future.

### dashboard.html (orchestrator/, ~1135 lines)
1. **Add the fleet health strip** (§1, Screen 1): 12 cells with status badge / current task / last progress / cost today / spin flag. This is the missing "10-second glance."
2. **Add cost-per-outcome panel:** $/day per agent + $/resolved-task. Depends on telemetryd change #1.
3. **Add spin flags** as first-class badges (not buried in a sub-tab). Derived server-side.
4. **Add alert feed** (§1, Screen 3): stale, spin, cost spike, error burst, missed mention — append-only, each linking to agent detail.
5. **Keep:** machine rail, activity feed, "Named in Slack" answered/missed tracking, connection & hooks panel, file browser. These are good.
6. **Audit for redundancy** before adding — 1135 lines is already large; new panels should replace or consolidate, not just accrete.

### fleet_receiver.py (orchestrator/, ~475 lines)
1. **Compute derived signals server-side:** staleness, spin-heuristic flags (§3), cost aggregates, baselines for spike detection. The dashboard stays a dumb renderer; the receiver owns the logic (testable, versioned).
2. **Persist an append-only event log** (JSONL per day): every push summary + every derived flag + every alert. This is the audit trail ("what did the fleet do Tuesday?") and the replay source. Cheap, `grep`-able, matches our Python style.
3. **Add a `/alerts` endpoint** feeding the dashboard alert feed.

### Don't change
- The 15s push + spool-on-failure transport — it works.
- The Slack-mention answered/missed tracking — it's a genuinely useful accountability signal; promote it, don't replace it.
- Don't rebuild the dashboard in Grafana yet — extend `dashboard.html` until it demonstrably outgrows custom code.

---

## 6. What to build first (ranked by value/effort)

1. **Token/cost telemetry in telemetryd + cost-per-outcome dashboard panel.** *Why:* you can't manage what you don't measure; every production incident write-up centers on cost surprise. *Effort:* low-medium. **Do this first.**
2. **Spin-detector heuristics 1–3 in the receiver** (tool repetition, no-progress window, error thrash) surfaced as dashboard badges + alert feed. *Why:* "spinning" is the failure mode Jack names most; detection is cheap. *Effort:* low (mostly aggregate counters we should already ship).
3. **Task-progress convention + dashboard rendering** (`tasks/<id>/TASK.md` + `PLAN_AND_PROGRESS.md` checklist; daemon ships summary). *Why:* turns "working" from a vibe into a fact; it's also the durability story (Anthropic's harness: progress files are what let a fresh context resume). *Effort:* low (convention + file read).
4. **Per-agent daily $ budgets with hard stop.** *Why:* the $47k lesson — alerting without enforcement is decoration. *Effort:* medium (needs #1, plus a daemon-side gate).
5. **Langfuse self-hosted pilot** (one VM, docker-compose) + OTLP emission from the daemon. *Why:* trace-level debugging ("why did it touch 47 files") without SaaS. *Effort:* medium. Defer until #1–3 are live — don't buy the telescope before reading the gauges.
6. **Append-only fleet event log in the receiver** (JSONL/day). *Why:* auditability and replay; nearly free. *Effort:* low — fold into #2's receiver work.

---

## Sources (primary)
- Anthropic, "Effective harnesses for long-running agents" — https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents
- Anthropic, "Effective context engineering for AI agents" — https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- OpenTelemetry GenAI semantic conventions — https://opentelemetry.io/docs/specs/semconv/gen-ai/
- metacto, "AI Agent Failures: Failure Modes, Causes & Fixes (2026)" — https://www.metacto.com/blogs/ai-agent-failures-and-how-to-avoid-them
- Anna Jey, "AI Agent Observability" (seven metrics) — https://medium.com/@arvisionlab/ai-agent-observability-how-to-trace-debug-and-control-agents-in-production-f98bab5f4a4e
- AI Builders Network, "Which Three Metrics Belong on a Fleet Dashboard" — https://aibuildersnetwork.org/api/expert-insights/which-three-metrics-belong-on-an-agent-fleet-dashboard/export-pdf
- tacavar, "A Company Run on Coordinated Claude Code Sessions" (kanban dispatcher, heartbeat governor) — https://tacavar.com/blog/running-company-coordinated-claude-code-sessions/
- Sergii Makarevych, "From one Claude agent to a fleet — in five small steps" (task-folder pattern) — https://www.linkedin.com/pulse/from-one-claude-agent-fleet-five-small-steps-sergii-makarevych-uruif
- immutex/mcode agent-loop spec (thrash detection: repeat_limit=3, window=12) — https://github.com/immutex/mcode/blob/HEAD/docs/04-agent-loop.md
- argszero/cordis-plugin-thinking-loop-guard (gram-containment loop guard) — https://github.com/argszero/cordis-plugin-thinking-loop-guard/blob/HEAD/README.md
- histore/agent-skills tiebreaker SKILL.md (loop/deadlock detection heuristics) — https://github.com/histore/agent-skills/blob/HEAD/skills/la-tiebreaker/SKILL.md
- prethiv/agentic-ai-case-studies, case 07 (agentic observability patterns, APM vs semantic telemetry) — https://github.com/prethiv/agentic-ai-case-studies/blob/HEAD/case-studies/07-agentic-observability-patterns/README.md
- Companion tools survey (frameworks, Langfuse, MCP servers, harnesses) — [~/workspace/research/agent-infrastructure-survey-2026-10.md](sandbox://workspace/research/agent-infrastructure-survey-2026-10.md)
