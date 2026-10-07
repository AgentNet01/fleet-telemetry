# Agent Swarm Research Report — for Jack's Boboe Fleet
Researched 2026-10-07. All links verified via web search/fetch. Nothing installed or changed.

## The 5 highest-leverage steals (read these first)

1. **Ralph loops for long tasks.** Run multi-hour/day missions as a bash loop spawning a fresh `claude -p` per iteration, state on disk, idle watchdog, `<promise>DONE</promise>` exit — instead of one long-lived session that accumulates context and stalls. (Geoffrey Huntley pattern; plugin: https://github.com/fasalzein/ralph-loop)
2. **Redis blackboard + heartbeats.** One Redis on the Mac: `agent:heartbeat:<name>` SETEX keys refreshed by each Boboe's cron, mission state as hashes, pub/sub for change events. Watchdog detects expired heartbeats → reassigns. This is the "every agent accounted for every 10 minutes" answer. (Recipe: https://dev.to/fooooorrest/redis-powered-multi-agent-ai-workflow-orchestrating-claude-code-instances-for-concurrent-software-dbh)
3. **Skills as the fleet's unit of rollout.** Package every capability (Slack triage, telemetry, role playbooks) as versioned Claude Code Skills in a private plugin marketplace — one `/plugin install` updates all 11 Boboes identically. (https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more)
4. **Typed handoffs + agent cards (A2A-lite).** Replace free-form @-mentions with a structured handoff format `{task_id, to, context, prior_results, heartbeat_at, state}` and a machine-readable capability card per Boboe. Any agent can claim/inherit any task. (https://github.com/a2aproject/A2A)
5. **Durable missions, not fragile sessions.** Wrap week-long objectives as durable workflows (DBOS-on-Postgres is cheapest; Temporal is the heavy-duty option) so a VM reboot resumes mid-mission instead of restarting from scratch. (https://github.com/dbos-inc/durable-swarm)

---

## 1. Multi-agent orchestration frameworks (open source)

### LangGraph — https://github.com/langchain-ai/langgraph
Stateful multi-agent systems as cyclic graphs; supervisor→workers or explicit handoffs between agent nodes. Checkpoint savers (Postgres) persist state after every step; crash → resume from exact checkpoint; human-in-the-loop interrupts.
Steal this idea: checkpoint fleet state after every completed task so a dead Boboe respawns with its exact in-progress context.

### Microsoft Agent Framework (AutoGen successor) — https://github.com/microsoft/agent-framework
AutoGen (~59k★, now maintenance mode: https://github.com/microsoft/autogen) merged with Semantic Kernel; GA 1.0 April 2026. Event-driven actor runtime with pub/sub topics; GroupChat speaker routing; Magentic-One orchestrator pattern.
Steal this idea: run fleet coordination as an event bus where Boboes subscribe to task topics instead of being @-mentioned, so any live Boboe picks up work when the assignee goes silent.

### CrewAI — https://github.com/crewAIInc/crewAI
Role-playing agent teams (role, goal, backstory, tools) with sequential/parallel/hierarchical processes; behind LangGraph on durable state, ahead on ease of use.
Steal this idea: give each Boboe a written role card (role + goal + tools + escalation path) with hierarchical fallback — a stuck worker delegates up to the coordinator instead of stalling.

### OpenAI Agents SDK — https://github.com/openai/openai-agents-python
Successor to the archived Swarm experiment. Minimal primitives: handoffs (transfer whole conversation to another agent) or agents-as-tools (specialist does bounded subtask, returns value).
Steal this idea: use an explicit handoff message format in Slack (destination + full context + prior results) instead of free-form @-mentions.

### MetaGPT — https://github.com/FoundationAgents/MetaGPT
Simulates a software company via SOPs: agents publish structured Message objects to a shared environment and subscribe by type; artifacts (PRD, diffs) are the medium, cutting cascading hallucination.
Steal this idea: make Boboes pass structured artifacts (briefs, result summaries, status files in a shared dir) instead of relying on Slack chat history as the handoff medium.

### Ruflo (formerly claude-flow) — https://github.com/ruvnet/claude-flow
Closest existing art to the Boboe fleet: MCP-based swarm over Claude Code, 16 specialized agent roles, queen/worker topologies, shared SQLite blackboard (`.swarm/memory.db`), consensus voting, plugin packaging (`/plugin marketplace add ruvnet/ruflo`).
Steal this idea: copy its file-based shared-memory convention as the standard handoff format between Boboes; study its hooks-based task routing before designing fleet dispatch.

## 2. Claude-specific tooling

### Claude Code Skills + plugin marketplaces — https://claude.com/blog/steering-claude-code-skills-hooks-rules-subagents-and-more
Skills = folders with SKILL.md (name + description lazy-loaded, body on invocation); plugins bundle skills, commands, subagents, MCP tools; private marketplaces via `/plugin marketplace add`.
Steal this idea: ship every fleet behavior as a versioned Skill so capability rollout is `git pull` + one install, not prompt edits on 11 VMs.

### awesome-claude-code — https://github.com/hesreallyhim/awesome-claude-code
~55k★ curated catalog: skills, hooks, orchestrators, plugins, observability, with Agent Orchestration and Ralph Wiggum sections and a machine-readable CSV.
Steal this idea: assign one Boboe a weekly "ecosystem scout" pass over Recently Added to surface new orchestration/observability patterns.

### awesome-claude-skills (Composio) — https://github.com/ComposioHQ/awesome-claude-skills
~76k★, 1,000+ production skills plus a `connect-apps` plugin giving real actions via Composio's MCP gateway (Slack, Gmail, GitHub, 1000+ apps) with managed auth.
Steal this idea: pull 2–3 skills straight into the fleet repo and evaluate the Composio gateway as a single-auth replacement for per-VM tokens.

### claude-code-templates — https://github.com/srtcot/claude-code-templates
`npx claude-code-templates@latest` stamps batteries-included components (agents, commands, MCPs, hooks, skills, **Loops** — autonomous workflows with goal + interval + stop condition) onto a Claude Code install.
Steal this idea: model fleet VM bootstrap on its component-catalog pattern — one idempotent installer instead of ad-hoc shell scripts.

### Ralph loop (plugin) — https://github.com/fasalzein/ralph-loop
Bash driver spawns a fresh `claude` process per iteration with clean context; state on disk (`.ralph/`: spec, state.json, progress.log); exits on completion promise; idle watchdog kills stuck iterations; zero parent-session token cost per iteration.
Steal this idea: template all unattended multi-hour Boboe work on this — fresh context per iteration beats one 6-hour session every time.

### claude-code-guardrails — https://github.com/dmitry-strugovshchikov/claude-code-guardrails
Dependency-free Python hooks: Stop-hook blocks false "done" declarations, PreToolUse blocks secret leaks and runaway bash retries, fail-open on parse errors.
Steal this idea: install a fleet-standard hooks.json on every VM — PreToolUse blocks on destructive commands/secret reads, and a Stop-hook that only accepts WAKANDA when the completion checklist is actually satisfied.

## 3. Capability skills & tools

### Aider — https://github.com/Aider-AI/aider
Terminal AI pair programmer (~49k★) with git integration and top SWE-bench scores; runs headless: `aider --message "..." ` auto-commits every edit.
Steal this idea: wrap Aider as a skill for code-touching Boboes so edits arrive as git commits with a test loop, not raw diffs.

### Figma MCP (official) — https://mcp.figma.com/mcp
Figma's own MCP server: agents pull frames/tokens/auto-layout and generate code from designs (headless agents use PAT-based community servers).
Steal this idea: give the design Boboe Figma MCP so a wireframe becomes React/Tailwind directly, no screenshots.

### Satori — https://github.com/vercel/satori
HTML/CSS→SVG layout engine, no browser needed; powers Vercel OG images. `satori` + `@resvg/resvg-js` = deterministic PNGs from JSX templates.
Steal this idea: standardize all agent-generated visuals on Satori templates — brand-consistent, deterministic, zero browser flakiness.

### python-pptx — https://github.com/scanny/python-pptx
Canonical Python .pptx builder (OpenXML, no PowerPoint needed); native charts, tables, speaker notes; fill a branded template's placeholders.
Steal this idea: build a "deck skill" — markdown outline + brand template in, editable .pptx out.

### gpt-image-1 API — https://platform.openai.com/docs/api-reference/images
OpenAI's current image model with accurate text rendering; plain REST/SDK call returning base64 PNG.
Steal this idea: one tiny `gen_image.py` wrapper (prompt → saved PNG) so any Boboe can produce real AI imagery from the shell.

### Stagehand — https://github.com/browserbase/stagehand
AI browser-automation SDK: natural-language `act()` + schema-validated `extract()` + self-healing action cache; runs against local Chromium with just a model key.
Steal this idea: give agents Stagehand primitives instead of raw Playwright — web tasks survive redesigns and return structured data.

## 4. Coordination beyond chat

### Redis leases + heartbeats (BullMQ pattern)
BullMQ workers claim jobs via atomic Lua scripts; the claim is a lock that must be renewed — missed renewal → job flagged stalled → requeued; `maxStalledCount` → dead-letter. (BullMQ: https://github.com/taskforcesh/bullmq)
Steal this idea: wrap every dispatched agent task in a lease with TTL; a crashed Boboe's tasks re-enter the queue automatically.

### Redis pub/sub multi-agent recipe (built for Claude Code) — https://dev.to/fooooorrest/redis-powered-multi-agent-ai-workflow-orchestrating-claude-code-instances-for-concurrent-software-dbh
Tasks claimed with `SET NX EX`, completions on pub/sub, health in hashes, heartbeats via `SETEX heartbeat:agent:001 30 "alive"`; orchestrator reassigns on TTL expiry; <100ms claims at 50+ agents.
Steal this idea: Redis on the Mac with heartbeat keys + `agent:events` channel is the cheapest presence system that actually works.

### DBOS DurableSwarm — https://github.com/dbos-inc/durable-swarm
Postgres-journaled durable workflows; each model/tool call a checkpointed `@DBOS.step()`; crash replays from DB instead of re-executing (no duplicate tokens/tool effects); Conductor UI to visualize/cancel/fork.
Steal this idea: skip the Temporal cluster — Postgres-backed durability turns week-long autonomy into a logging problem.

### Temporal — https://temporal.io/blog/introducing-temporal-and-agentic-sandboxes-openai-agents-sdk
Deterministic workflows (replayed from event log after crash) + exactly-once activities; durable timers pause workflows for months at zero cost.
Steal this idea: when a mission outgrows DBOS, model it as one Temporal workflow per objective with each agent leg as an activity.

### Blackboard pattern — https://github.com/joona-t/blitz-swarm/blob/HEAD/Memory%20architecture%20for%20a%20parallel%20AI%20agent%20swarm.md
Hearsay-II classic: agents never call each other — they read/write a shared surface (Redis hashes + pub/sub notifications); 2025 papers show 13–57% better task success and lower token spend vs orchestrator chat.
Steal this idea: mission hash per objective with `findings:`/`decisions:`/`handoff:` keys; Slack becomes the notification feed, not the state of record.

### A2A agent cards — https://github.com/a2aproject/A2A
Linux Foundation standard: agents publish cards at `/.well-known/agent.json`, tasks move through `submitted → working → input-required → completed/failed` with streaming + push webhooks.
Steal this idea: post a machine-readable capability card per Boboe once, and standardize task posts to `{task_id, claim_by, heartbeat_at, state}`.

### Internal MCP server for fleet tooling
MCP (https://temperature2.com/p/2026-09-11-guide-what-is-mcp/) decouples tools from agents: write a server once, every compliant agent uses it (10k+ public servers by 2026).
Steal this idea: put fleet capabilities (Slack poster, telemetry pusher, blackboard R/W, cron registrar) behind one internal MCP server — identical versioned tooling on every Boboe instead of hand-rolled glue per VM.

## Caveats
- Star counts/statuses come from crawled pages and roundups (mid-2026), not live API checks — treat as approximate.
- Two subagent links were search-text-only (Slack MCP server lineage, some secondary citations) — flagged in their reports; everything above was verified.
- Recommendation: steal patterns (Ralph loops, blackboard, leases, agent cards, Skills packaging), not frameworks wholesale — the fleet runs Muse + Slack + crons, not Python agent runtimes.
