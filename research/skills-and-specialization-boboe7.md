# Agent Skills, Tools & Specialization — Swarm Research Report

**Lane:** AGENT SKILLS, TOOLS, AND SPECIALIZATION · **Date:** 2026-10-07 · **Author:** Boboe 7
**Fleet context:** Boboe Prime + Boboes 1–11 (12 agents) on Linux VMs, Slack-coordinated (#all-agentnet), GitHub org `AgentNet01`, repo `AgentNet01/fleet-telemetry`, cron+hook runtime already live.

---

## 0. TL;DR — the opinionated bottom line

1. **Don't adopt an agent framework.** The fleet already *is* the orchestrator (Slack + cron + hooks + subagents). It needs **substrate, not another orchestrator**: the Claude Agent SDK as the canonical agent loop, MCP as the tool bus, SKILL.md as the package format.
2. **Specialize by tool-access, not identity.** Roles are hats with different tool allowlists (researcher = web tools, builder = code+shell, reviewer = read-only+comment, coordinator = queue+merge). Any agent can be re-hatted; this keeps all 12 fungible.
3. **Writes are single-threaded; reads and reviews parallelize.** The strongest finding in the field (Anthropic + Cognition converge on this): let many agents research and review concurrently, but exactly one agent mutates any artifact at a time, on a branch, in a worktree.
4. **The single cheapest quality lever is a clean-context reviewer.** A reviewer that never saw the build session catches ~2 bugs per PR. Add it before adding more builders.
5. **Governance = deterministic gates, not prose.** Hooks (deny-lists, fail-closed) + sandboxing + default-deny egress are non-negotiable and model-independent. Three approval tiers (autonomous / audit / control) let the fleet move fast without a human in every loop.
6. **The issue tracker is the database.** GitHub issues with label state machines (`ready → in-progress → pr-open → done`, plus `needs-human`/`blocked`/`error`) make the orchestrator kill-safe. Files are memory; the context window is a cache.
7. **Humans get exceptions and digests, nothing else.** Heartbeat every 15–30 min; Slack posts only for escalations (with options + recommendation) and a periodic digest. Jack should never be a progress monitor.

---

## 1. Findings

### 1.1 Specialization patterns

**Anthropic's orchestrator-worker is the production reference.** Anthropic's engineering writeup of its multi-agent research system describes a Lead (Opus-class) that plans, spawns parallel specialist subagents (Sonnet-class, each with its own context window and tools), then synthesizes, ending with a citation-verification pass. Multi-agent beat single-agent Opus 4 by **90.2%** on their internal research eval; token volume alone explains ~80% of benchmark variance — multi-agent is "a token-spending machine" that parallelizes reasoning across context windows. Cost: ~15× single-chat tokens.

**Five composable patterns** (Anthropic, "Building Effective Agents"): prompt chaining, routing, parallelization (sectioning / voting), orchestrator-workers, evaluator-optimizer. Governing rule: **workflows (predefined code paths) beat agents (model-directed) unless the task genuinely needs open-ended steps.**

**Dynamic Workflows (Claude Code, May 2026, research preview):** Claude writes a JavaScript script per task that plans and fans out across **up to 1,000 subagents (16 concurrent)**, with adversarial cross-checking until answers converge. The plan lives in script variables, not context. Progress is saved; interrupted runs resume. This is the closest thing to a fleet-orchestration primitive built by Anthropic itself — worth watching, and a strong argument for keeping our orchestration in code (JS/Python scripts) rather than in prompts.

**The counter-case (Cognition, "Don't Build Multi-Agents"):** parallel subagents share only messages, not full context/traces, so conflicting *implicit* decisions produce incoherent results no merger can rescue. Reconciliation, which even Anthropic endorses: **multi-agent wins for read-only parallelizable exploration (research); single-thread wins for writes with interdependent decisions (coding).**

**Fixed-specialist reference (Microsoft Magentic-One):** Orchestrator + four specialists (WebSurfer, FileSurfer, Coder, ComputerTerminal) with a shared Task Ledger and Progress Ledger and a re-plan-on-error loop. Lesson: fixed specialists work when they touch **distinct tools/domains** and write to a **common record**.

**Role frameworks:** CrewAI = roles-first (role/goal/backstory + toolset; fastest to prototype); AutoGen/AG2 = conversation-first (group-chat deliberation); LangGraph = state-first (checkpointable state graphs — what production teams converge on for debuggability). For us: role-based decomposition for speed, but persist state in files/issues so any run is debuggable and resumable.

**Dynamic role assignment in practice = task auctions + capability registries**, not leader-election theater. For a Claude-on-VM fleet, the right weight is a **central work queue with claim semantics** (labels as mutual-exclusion locks), not Raft.

**When specialization beats generalists — the decision rule:**
- Specialization wins when work parallelizes with low interdependency, subtasks need different tools/access, or aggregate information exceeds one context window.
- Generalists/single-thread win when every step depends on prior decisions, consistency of judgment matters more than throughput, or tasks are small enough that coordination overhead dominates (three 90%-reliable agents in series ≈ 73% pipeline reliability).

**Failure modes:** vague delegation → duplicated work (fix: every delegation needs objective + output format + tool boundaries + budget); over-spawning (fix: scale effort to complexity); conflicting implicit decisions on shared artifacts (fix: git worktrees for true isolation); chatter cost (fix: typed handoff artifacts, not free-form chat).

### 1.2 Skills & tooling ecosystems

**SKILL.md is the package format.** The Agent Skills open standard (SKILL.md + YAML frontmatter: `name`, `description`, optional `allowed-tools`/`disallowed-tools`/`model`/`context: fork`) works across Claude Code, Codex, Cursor, Gemini CLI. Key insight from the ecosystem: `context: fork` turns a skill into a subagent task — skills and subagents are two ends of the same mechanism. Keep the fleet's skill count to **~10–20**; bulk-installing 200-skill bundles adds baseline token overhead (~80 tokens metadata each) and activation is LLM-reasoned, not deterministic.

**Official reference:** `anthropics/skills` (17 official: docx/pdf/pptx/xlsx generation, frontend-design, webapp-testing, mcp-builder, skill-creator, slack-gif-creator) and `anthropics/claude-plugins-official` (managed plugin marketplace). **Distribution:** `vercel-labs/skills` (`npx skills add <repo>`) installs skills across 35+ agents — skills are becoming as installable as npm packages.

**Dev tooling that actually moves the needle:**
- **oraios/serena** (ADOPT) — LSP-based semantic code toolkit as MCP: symbol-level find-references/definitions, structural editing in one atomic call instead of grep-crawls. 100% local.
- **ast-grep** (ADOPT) — AST-aware search/codemods; grep is the wrong tool for agents, this is the right one.
- **yamadashy/repomix** (ADOPT) — packs a repo into one AI-friendly file (~70% token savings via tree-sitter compression); cheapest whole-repo context.
- **trailofbits/skills** (ADOPT) — 29 security skills (static analysis, differential review, supply-chain audit); the most credible security-agent pack.
- **Pullfrog / official Claude Code GitHub Action** (ADOPT) — `@claude` on issues/PRs, agent runs inside Actions; advisory-only reviews that never block merges are the safe default.
- **ccusage** (ADOPT) — token analytics across 15+ agent CLIs; you cannot run a fleet without cost visibility.

**Design/media agents can drive:**
- **Presenton** (ADOPT) — self-hosted, Apache-2.0, REST API + MCP server → editable PPTX from a prompt/outline. Kills the screenshot-of-slides hack.
- **Marp CLI** (ADOPT) — Markdown → PPTX/PDF/HTML with CSS themes; simplest reliable agent deck pipeline.
- **python-pptx** (ADOPT) — when Marp layouts aren't enough; pixel control.
- **fal.ai** (ADOPT) — single API key across FLUX/Recraft/Kling/Seedance/Veo; the de-facto agent-facing image/video API. Replicate as complement.
- **Mermaid CLI + D2** (ADOPT) — deterministic, editable, diffable diagrams; "always render, never return just source."
- **Remotion + FFmpeg + TTS** (ADOPT for explainers) — code-driven video is deterministic and cheap; generative scenes are cost-per-clip.
- **obra/superpowers** (ADOPT the pattern) — plugin that *enforces* brainstorming/planning/TDD/review into every session. "Process as installable plugin" is how you enforce conventions on agents.

**Data work:**
- **Exa (discover) + Firecrawl (extract)** is the canonical combo; **Tavily** as the single default is fine too (pick one for cost); **Jina Reader** (`r.jina.ai/<url>`) as the zero-friction fallback.
- **text2sql-mcp pattern** (ADOPT) — one `execute_sql` tool, agent explores schema and self-corrects; cleanest DB interface.
- **papermill** (ADOPT) — parameterized headless notebooks as the agent↔data contract.

**Comms integrations:**
- **claude-code-slack-bot** (kkhfiles fork) — Socket Mode + thread-mapped persistent sessions + Slack-button approvals. Adopt the *pattern* for any agent↔human surface.
- **jeremylongshore/claude-code-slack-channel** — steal the defense-in-depth ideas (inbound/outbound gates, hash-chained audit journal, exfiltration guard).
- **Composio** (ADOPT with caveats) — 1,000+ toolkits with managed OAuth; solves the per-integration auth problem. Caveats: cloud credential storage, no key rotation alerting — keep secrets management separate.

**Agent-relevant APIs:** Stripe (read-first, hard approval gate on writes), OpenTable/Duffel booking via dedicated skills (not raw browsing), native geocoding before wiring Mapbox/Google.

### 1.3 Agent harnesses

**The ecosystem converged on:** thin tool loops with hooks and permission callbacks (not heavy frameworks); file-based memory instead of vector DBs; MCP as the tool-integration standard; long-poll/event daemons for chat bridges and cron for scheduled wakes, with durable-workflow engines (Temporal) emerging for crash-critical jobs.

**Adopt:**
- **Claude Agent SDK** (`anthropics/claude-agent-sdk-python` / `-typescript`) — the exact loop Claude Code runs, exposed as a library: custom tools as in-process MCP servers, hierarchical subagents with per-subagent tool restrictions and model selection, hooks (PreToolUse), permission callbacks, Skills, session resume by ID. This is the substrate the fleet should standardize on; it is maintained by Anthropic instead of hand-rolled subprocess scraping.
- **MCP** — the fleet's tool bus. Anything an agent needs (Slack, GitHub, telemetry) should be an MCP server, not bespoke code per agent.
- **mini-swe-agent** — the 100-line bash-loop from the SWE-agent team; closest existing thing to how the fleet already works. Steal its packaging as the canonical single-agent loop shape.
- **E2B** — Firecracker microVMs, Apache-2.0, sub-200ms cold starts, for any agent executing untrusted/LLM-authored code. (Daytona went private June 2026 — skip; evaluate the Nightona fork only if you need AGPL self-hosting.)

**Steal ideas from:** SWE-agent (ACI design — interface design matters as much as the model; trajectory logging), OpenHands (append-only event stream — the fleet's telemetry could be built exactly this way; SDK packaging), Aider (git-checkpoint every mutation, test-output-as-ground-truth repair loops, token thrift), Agentless (deterministic pipelines beat agents 10:1 on cost for decomposable bulk work), CrewAI (role decomposition; Crew-vs-Flow duality = autonomous crews for fuzzy work + event-driven flows for the deterministic backbone — exactly our agent-vs-cron split), AG2 (tool-driven handoffs between agents), LangGraph (checkpointing + interrupts for resumable/approval-gated cron jobs), Cyrus (per-task git worktrees + stream activity back into the spawning thread — closes our Slack observability gap), OpenClaw (channels normalize to internal events; one gateway daemon owns scheduling/policy/sessions; memory = files with hybrid search), oh-my-claudecode (staged plan→exec→verify→fix pipeline with evidence-based completion), OpenCode (AST-scoped bash permissions, hook lifecycle, LSP-diagnostics-as-feedback).

**Skip:** SuperAGI (dead), full-framework adoption of CrewAI/AutoGen/LangGraph (the fleet already *is* the orchestrator), kitchen-sink skill bundles, "AI slide SaaS" without APIs.

**Temporal** for durable scheduled work when plain cron isn't enough (multi-hour rollouts, approval-gated pipelines) — adopt when the fleet outgrows cron, not before.

### 1.4 Rules & governance for autonomous fleets

**Deterministic gates beat prose by a wide margin.** Measured: CLAUDE.md-style instructions followed ~70% of the time; hooks enforce at 100%. Three layered gates (Claude Code model, portable to any harness): (1) **permissions** — allow/ask/deny rules, first match wins; (2) **OS-level sandboxing** of shell — holds even if prompt injection bypasses model judgment; (3) **hooks** — PreToolUse can deny (exit 2), inject context, or rewrite the call, and holds even in bypass mode. Hooks can tighten but never loosen a deny. Treat AGENTS.md/skills/hooks as code — they are prompt-injection attack surface (malicious SessionStart hooks were a real 2025–2026 CVE class via npm/PyPI worms).

**Approval tiers — the industry 80/20 pattern:**
- **Tier 1 — Autonomous (~80%):** research, drafts, tests, internal reporting. No review.
- **Tier 2 — Audit (~15%):** PRs, content drafts, lead updates. Async spot checks within a defined window.
- **Tier 3 — Control (~5%):** deploys, money movement, credential changes, external comms. Mandatory synchronous approval.
New capabilities start at the lowest tier they're proven at; promotions are evidence-based. Human-in-the-loop vs human-on-the-loop set from the cost of being wrong.

**Devin's production model proves "autonomous for days":** each session gets an isolated Linux VM; the agent plans, executes, tests, reviews, and proposes a PR — **oversight happens at the PR stage, not per step.** 67% of Devin PRs merged (Nov 2025); 4–8-hour clearly-scoped tasks, verify the PR, scale horizontally. Cursor Background Agents converge on the same model (sandboxed VM → branch → PR; risk-classified PRs: low-risk auto-approvable, high-risk to humans).

**Cost controls:** per-task token/step/wall-clock budgets with hard kills; tokens-per-minute rate limits (catches runaway loops before the invoice); model routing (frontier for planning, small for extraction — and a more expensive lead model can *cut* session cost ~46% by delegating earlier and writing clearer briefs); prompt caching on stabilized prefixes; cost-per-completed-task as the metric, not cost-per-token. Alert at 50/80/100%.

**Audit trails:** agent registry (owner, scope, permission set); append-only decision journal (action, tool, args-hash, outcome, cost); per-run execution traces. Review by exception — sampled digests, not a feed of every action.

**Safety rails that preserve autonomy:** sandbox + default-deny egress + artifact handoff (agents produce artifacts inside sandboxes; publication goes through a gated pipeline). Circuit breakers (stop after N failures), iteration caps (~15–25 steps), wall-clock timeouts, loop detection (three near-identical tool calls = stuck), final tool-free synthesis call so capped runs still return something.

**#1 production failure: runaway loops** — no clear success/failure signal, agent retries "the same fix, slightly reworded" indefinitely. Shows up as a bill, not a bug (one documented deadlock: 25M tokens / ~$1,200 in 14 minutes). Fix: hop counters with hard ceilings in every cross-agent envelope.

### 1.5 Managing long-running tasks

**The issue tracker is the database.** `addyosmani/factory`, `coleam00/ai-software-factory`, `ghswarm`: GitHub issues in, merged PRs out. The purest form: **"GitHub already is that database"** — labels are a mutex, the issue body is a state blob (next_action/branch/PR/retries in hidden HTML comments), checkboxes are the task queue; the orchestrator is a stateless CLI you can `kill -9` and resume with zero reconciliation. Working label taxonomy: `ready-for-agent` → `agent-in-progress` → `pr-open` → `agent-done`, with `agent-skipped`, `agent-error`, `needs-human`, `blocked` as terminal/side states. Non-negotiable rules: never auto-merge, never push to main, one branch per task, skip ambiguous/risky tasks.

**Files are memory; the window is a cache.** Treat compaction as total amnesia: plan file, TODO ledger, findings log, handoff doc — written continuously, git-committed. Session start = read MEMORY.md + open tasks + recent daily log. A fresh agent must resume from tracker + repo alone. (Note: per-agent memory is siloed — cross-agent knowledge needs the shared tracker/ledger, not per-agent files.)

**Layered memory taxonomy:** working context → session scratchpad → project memory (AGENTS.md) → episodic ("tried X, failed because Y") → semantic (distilled facts) → procedural (skills). Don't make the model remember history — make the system preserve the state the model actually needs.

**Heartbeats:** cron-triggered heartbeat every 15–30 min with three jobs: check signals (new qualifying work?), check progress (claimed task with no state change across 2 beats = stuck → nudge/escalate), check budgets (over 80%?). Output to structured log; Slack only on exceptions. AWS AgentWatch's **Notify** pattern (parameterized monitoring report every 15 min) and **Question** pattern (post when uncertain whether to remediate or escalate) are the right reporting shapes.

**Escalation as a state transition, not a cry for help:** max attempts → auto-park with failure summary; loop detection → circuit break; `needs-human` label → Slack question with context, options, and default action if no response within SLA. Report by exception with a fixed digest: escalations needing decisions (options + recommendation), completions since last digest (task, artifact, cost), anomalies.

**Entry gate:** a task is claimable only with scope, done-criteria, and a risk tier. Ambiguous tasks get `needs-human` before any agent touches them.

---

## 2. Ranked recommendations: ADOPT vs BUILD vs STEAL

### ADOPT now (concrete, working, wire in this week)

| # | Item | What it is | Why |
|---|------|-----------|-----|
| 1 | **Claude Agent SDK** | Anthropic's official agent loop as a library (Python/TS): tools as in-process MCP, hierarchical subagents, hooks, permission callbacks, Skills, session resume | The fleet's hand-rolled loop reimplements this; standardize on the maintained substrate |
| 2 | **MCP as the tool bus** | Model Context Protocol; everything an agent needs becomes an MCP server | Ends bespoke per-agent tooling; tools become reusable by other people's agents too |
| 3 | **SKILL.md format + `npx skills add` distribution** | Open skill standard; vercel-labs/skills installer | Skills as installable packages; ~10–20 curated skills, not 200 |
| 4 | **serena MCP** | LSP-based semantic code toolkit | Replaces grep-crawls with atomic symbol operations |
| 5 | **ast-grep** | AST-aware search/codemods | Correct search primitive for agents |
| 6 | **repomix** | Whole-repo context packing (~70% token savings) | Cheapest way to onboard an agent onto a codebase |
| 7 | **trailofbits/skills** | 29 security skills (static analysis, supply-chain audit) | Credible security review before anything ships |
| 8 | **Marp CLI + brand theme** | Markdown → PPTX/PDF decks | Deck pipeline for agents; Presenton when outlines need AI layout |
| 9 | **fal.ai API key** | Image/video generation gateway | De-facto agent media API |
| 10 | **Exa + Firecrawl** (or Tavily alone) | Discover + extract web stack | Canonical retrieval pair; Jina Reader as zero-friction fallback |
| 11 | **ccusage** | Token analytics across agent CLIs | Cost visibility before budgets mean anything |
| 12 | **Mermaid CLI / D2** | Diagram-as-code rendering | Deterministic, diffable diagrams in every doc |
| 13 | **papermill** | Parameterized headless notebooks | Cleanest agent↔data contract |
| 14 | **GitHub issue-queue with label state machine** | `ready-for-agent` → `in-progress` → `pr-open` → `done` + `needs-human`/`blocked`/`error` | The fleet's single source of truth; kill-safe orchestration |
| 15 | **obra/superpowers pattern** | Enforced workflow plugin (plan→TDD→review) | "Process as installable plugin" — conventions enforced, not suggested |

### STEAL IDEAS (borrow patterns, don't clone)

- mini-swe-agent's 100-line bash-loop packaging; Aider's git-discipline (commit every mutation, test-output repair loops); OpenCode's AST-scoped bash permissions and hook lifecycle; OpenHands' append-only event stream (model for fleet telemetry v2); Cyrus's per-task git worktrees + streaming activity back into the spawning Slack thread; OpenClaw's gateway architecture (channels → normalized events → one scheduler); oh-my-claudecode's staged plan→exec→verify→fix gates; LangGraph's checkpointing/interrupts for durable cron jobs; GitHub Agentic Workflows' safe-outputs pattern; jeremylongshore's audit-journal + exfiltration-guard for Slack surfaces.

### BUILD (fleet-specific, no good off-the-shelf exists)

1. **Fleet coordinator service** — the OpenClaw-style gateway: normalizes Slack/cron/webhook events, owns the issue queue, assigns by capability tags, enforces approval tiers, runs the heartbeat. (Our current cron+hook+receiver stack is v0 of this; promote it deliberately.)
2. **Approval-tier pipeline** — Tier 1/2/3 classification at task creation, async audit sampling, blocking approvals for Tier 3 with Slack buttons.
3. **Budget enforcement** — per-task token/step/time budgets, tokens-per-minute runaway detection, 50/80/100% alerts, cost-per-completed-task dashboard (extends ccusage data).
4. **Exception-only reporting digest** — heartbeat → structured log; Slack digest every 15 min (AgentWatch Notify pattern); escalations with options + recommendation (Question pattern).
5. **Clean-context reviewer role** — a reviewer subagent/hat that reads diffs cold on every PR. (Pattern exists; the fleet-specific wiring is ours to build.)
6. **Fleet skill pack** — internal SKILL.md files for fleet ops: `fleet-deploy` (rollout procedure), `slack-reply` (reply norms), `pr-review` (review checklist), `incident-triage`. Distributed via `npx skills add` from our own repo.

### SKIP

SuperAGI (dead), Daytona (went private), full CrewAI/AutoGen/LangGraph framework adoption (we already are the orchestrator), kitchen-sink skill bundles (token overhead), self-hosted Firecrawl/search (until the bill hurts), custom vector-DB memory (files + issue tracker win).

---

## 3. Proposal: specializing OUR fleet

### 3.1 Role architecture — hats, not identities

Roles are **capability + tool-allowlist bundles**, not permanent identities. Any agent can be re-hatted by the coordinator, which keeps all 12 fungible and eliminates single points of failure. Each hat has: a tool allowlist, a work source (queue labels), output format, and a budget tier default.

| Hat | Tool scope | Queue labels | Output |
|-----|-----------|--------------|--------|
| **Coordinator** | Queue (read/write), Slack, merge decisions; no code writes | all | assignments, escalations, digests |
| **Architect** | Read-only code + docs; writes plan files only | `plan-needed` | plan file + task breakdown with done-criteria |
| **Builder** | Code + shell + tests, one task at a time, own worktree | `ready-for-agent` | branch + PR |
| **Reviewer** | Read-only + comments; never the builder's context | `pr-open` | review verdict + findings |
| **Researcher** | Web/search/extraction, no repo writes | `research` | findings doc with citations |
| **Scout** | Web/search + eval sandboxes, writes eval notes | `tooling-eval` | adopt/steal/skip verdict |
| **Ops** | Infra repos, cron/hook configs, telemetry | `ops` | deployed change + health check |

**The two hard rules:** (1) many agents may research/review in parallel; exactly one agent mutates an artifact at a time, on a branch, in a worktree. (2) Every delegation carries objective + done-criteria + output format + tool boundaries + budget; every completion returns a typed artifact (file path, test results, PR link).

### 3.2 Concrete assignments (starting point; coordinator re-hats as load shifts)

- **Boboe 1 — Coordinator.** Already the fleet onboarding lead and rollout tracker. Owns the issue queue, assigns work by capability tags, runs the heartbeat, writes the digest, escalates to Jack. Never takes build tasks.
- **Boboe Prime — Architect.** Plans and task breakdowns; approves designs before builders start; owns the fleet repo's technical direction.
- **Boboes 3, 5, 6, 8, 9, 11 — Builders (pool of 6).** Claim `ready-for-agent` tasks one at a time. Each works in a per-task git worktree, commits like Aider (every mutation checkpointed), opens PRs, never merges.
- **Boboe 4 — Reviewer.** Clean-context review on every `pr-open`: reads the diff cold, runs trailofbits security skills on it, posts verdict. Highest-ROI role in the fleet.
- **Boboe 10 — Researcher.** Owns the `research` queue: deep investigations with citations (this swarm-research initiative is the template).
- **Boboe 7 (me) — Scout + Comms.** Tooling evaluations (`tooling-eval` queue: install, test, verdict), plus Slack-facing comms and incident response. Keeps the fleet's skill pack current.
- **Boboe 2 — Ops.** Already coordinating rollouts. Owns telemetry, cron/hook health, daemon upgrades, the fleet-telemetry repo's agent infrastructure.

Coordinator keeps a visible roster (pinned Slack message or repo file) showing current hat per agent; re-hats are announced in one line.

### 3.3 Skills to install (fleet-wide baseline + per-hat)

**Baseline on every box** (`npx skills add` from pinned repos):
1. `fleet-ops` (build: rollout/deploy/incident procedure)
2. `slack-reply` (build: reply norms, loop guards, done-file discipline)
3. `pr-review-checklist` (build from trailofbits + repo conventions)
4. `web-research` (Exa/Tavily + Firecrawl + Jina fallback chain)
5. `deck` (Marp CLI + brand theme)
6. `diagram` (Mermaid/D2 render-always)

**Per-hat additions:**
- Builders: serena MCP, ast-grep, repomix, `tdd` (superpowers pattern), language toolchains per repo
- Reviewer: trailofbits/skills (full pack)
- Researcher/Scout: `deep-research` pattern (lead → parallel specialists → synthesis → citation verify)
- Ops: `telemetry` (fleet-telemetry repo runbook), `sandbox` (E2B usage)
- Coordinator: `queue-ops` (label state machine runbook), `digest` (report format)

**MCP servers fleet-wide:** GitHub (official), Slack (official or self-hosted bridge), serena, Firecrawl, Exa. Composio only if OAuth sprawl becomes painful.

### 3.4 Rules to adopt (standing orders additions)

1. **Approval tiers on every task:** Tier 1 autonomous (research, drafts, tests) · Tier 2 audit (PRs — async spot check) · Tier 3 control (deploys, credentials, external messages, money — blocking approval). Task labeled at creation; promotions evidence-based. (Jack's existing 4 carve-outs map to Tier 3.)
2. **Single-writer rule:** one agent per artifact, one branch per task, never push to main, never auto-merge.
3. **Deterministic gates:** PreToolUse-style deny-lists for destructive/secret-exfiltrating actions (fail-closed), file-boundary allowlists per task, default-deny egress on sandboxes. Prose rules are advisory; gates are law.
4. **Budgets on every run:** max steps (~25), max wall-clock, max tokens, tokens-per-minute runaway kill. Alert at 50/80/100%. Cost tracked per completed task.
5. **Write-as-you-go:** plan file, TODO ledger, findings log — committed continuously. Compaction is treated as total amnesia.
6. **Report by exception:** heartbeat 15–30 min; humans see escalations (with options + recommendation) and a periodic digest (completions, anomalies, costs). No routine pings.
7. **Escalation is a state transition:** max attempts → auto-park with failure summary; loop detection → circuit break; `needs-human` → Slack question with context, options, default action on SLA expiry.
8. **Entry gate:** task claimable only with scope + done-criteria + risk tier. Ambiguous tasks get `needs-human` first.

### 3.5 Infra changes

1. **Promote the receiver+cron+hook stack into a coordinator service** (OpenClaw-gateway pattern): normalize Slack/cron/webhook → internal events; own scheduling, policy, sessions. Current stack is v0 — keep it running, refactor deliberately.
2. **GitHub issue queue on `AgentNet01/fleet-telemetry`** (or a new `fleet-ops` repo) with the label state machine; machine state in issue bodies; orchestrator kill-safe.
3. **Per-task git worktrees** for builders (Cyrus pattern); stream agent activity back into the spawning Slack thread (closes the observability gap).
4. **Budget enforcement + cost dashboard** (ccusage data → per-task attribution → 50/80/100% alerts).
5. **Migrate agent loops to the Claude Agent SDK** over time (hooks, permission callbacks, subagents, session resume come free).
6. **E2B sandboxes** for any agent executing untrusted/LLM-authored code; keep trusted fleet-ops work on the existing VMs.

### 3.6 Rollout sequence (first 2 weeks)

1. **Week 1, days 1–2:** Stand up the issue queue with labels; write the queue runbook skill; Boboe 1 starts assigning from it. Install baseline skills fleet-wide via `npx skills add`.
2. **Week 1, days 3–4:** Boboe 4 starts clean-context review on every PR; add trailofbits skills to the reviewer box. Add the 8 rules to standing orders.
3. **Week 1, day 5:** Per-task budgets + ccusage dashboard; first cost report.
4. **Week 2:** Per-task worktrees for builders; heartbeat digest (replacing ad-hoc Slack posts); first Tier-2 audit sampling. Scout (Boboe 7) evaluates Claude Agent SDK migration path and E2B for sandboxing.

**Success looks like:** Jack sees only escalations and a 15-min digest; every task is traceable issue → branch → PR → reviewed merge; cost per completed task is known and falling; any agent can be replaced mid-task with zero reconciliation.

---

## 4. Key sources

- Anthropic, "How we built our multi-agent research system" — anthropic.com/engineering/multi-agent-research-system
- Anthropic, "Building Effective Agents" — anthropic.com/engineering/building-effective-agents
- Cognition, "Don't Build Multi-Agents" — cognition.ai/blog/dont-build-multi-agents
- Wang et al., "Mixture-of-Agents" — arxiv.org/abs/2406.04692 · Microsoft, Magentic-One — arxiv.org/abs/2411.04468 · MemoryAgentBench — arxiv.org/abs/2507.05257
- anthropics/skills · anthropics/claude-plugins-official · anthropics/claude-agent-sdk-python · vercel-labs/skills · obra/superpowers
- oraios/serena · ast-grep/ast-grep · yamadashy/repomix · trailofbits/skills · pullfrog/pullfrog · ccusage/ccusage
- SWE-agent/mini-swe-agent · OpenHands/OpenHands · Aider-AI/aider · crewAIInc/crewAI · ag2ai/ag2 · langchain-ai/langgraph · Significant-Gravitas/AutoGPT
- sst/opencode · ceedaragents/cyrus · openclaw/openclaw · temporalio/temporal · e2b-dev/E2B
- addyosmani/factory · coleam00/ai-software-factory · matteogiaquinto/ai-nightshift (label taxonomy)
- Dev.to "Cloud Computers for AI Agents in 2026" (dev.to/saptadev27/...) · Upstash "AI Agent Sandboxes Compared" (upstash.com/blog/...) · agentmail.to "Best MCP servers for AI agents in 2026"

---
*End of report. Raw subagent research notes available on request.*
