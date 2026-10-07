# Muse-Specific Tooling Research
*Researched 2026-10-07. For the agentic swarm utilization project (Jack Human's directive 2026-10-07 00:31 EDT).*

Context: MCP (Model Context Protocol) was donated by Anthropic to the Linux Foundation's Agentic AI Foundation in late 2025 and is now the standard bridge between AI agents and external services. There is an official MCP registry at modelcontextprotocol.io plus community marketplaces (Smithery.ai, Glama.ai, mcp.so, PulseMCP).

---

## A. Categorized catalog of MCP servers, skills, and tools

### 1. Code & development
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **GitHub MCP Server** (official) | `github.com/github/github-mcp-server` · remote: `https://api.githubcopilot.com/mcp/` · Docker: `ghcr.io/github/github-mcp-server` | ★ High (official, Go, MIT, v1.12.2 as of Sep 2026) | Toolsets: repos, issues, PRs, actions, code_security, dependabot, etc. `--toolsets` to trim context; `--read-only` and `--lockdown-mode` for safety |
| **Context7** | FastMCP-hosted | ★ High (dominates FastMCP rankings) | Pulls current library docs into context — kills stale-API hallucinations |
| **Serena** | `github.com/oraios/serena` | ★ Medium-high | Coding-agent toolkit: semantic retrieval + editing, MCP + integrations |
| **Firecrawl MCP** | `github.com/firecrawl/mcp-server` | ★ High | Web scraping w/ JS rendering, structured JSON output, crawling, file parsing |
| **Tavily MCP** | `github.com/tavily-ai/tavily-mcp` | ★ High | AI-optimized web search API |

### 2. Browser automation
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **Playwright MCP** (Microsoft) | `github.com/microsoft/playwright-mcp` · `npx @playwright/mcp@latest` | ★ High (official, Apache 2.0) | 23 tools, accessibility-tree snapshots (no vision needed), `--headless`, `--isolated`, `--storage-state`, `--caps`. Install: `claude mcp add playwright npx @playwright/mcp@latest` |
| **Chrome DevTools MCP** | `github.com/ChromeDevTools/chrome-devtools-mcp` | ★ High | Real Chrome with DevTools protocol: DOM, console, network, perf traces |
| **Fetch MCP** | `github.com/anthropics/mcp-fetch` (archived reference impl) | Medium | Simple page fetch → markdown |

### 3. Databases
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **Supabase MCP** (official) | `github.com/supabase/mcp` · hosted `https://mcp.supabase.com/mcp` | ★ High (Apache-2.0) | SQL, migrations, logs, advisors, type gen, Edge Functions deploy; `read_only=true` and `project_ref` scoping |
| **Postgres MCP Pro** | `github.com/crystaldba/postgres-mcp` | ★ Medium-high | Schema, EXPLAIN w/ hypothetical indexes, pg_stat_statements, health checks. `--access-mode=restricted` (read-only txn) default — strongly recommended |
| **Neon MCP** | `github.com/neondatabase-labs/mcp-server-neon` | Medium | Branch/project management + SQL |
| **SQLite MCP** | `modelcontextprotocol/servers` (reference) | Medium | Local SQLite |
| Note | The original `@modelcontextprotocol/server-postgres` is **archived** — do not install it. Use crystaldba/postgres-mcp or Supabase. |

### 4. Design & UI
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **Figma MCP** (official) | `developers.figma.com/docs/figma-mcp-server/` · remote `https://mcp.figma.com/mcp` | ★ High | `get_design_context` (structured XML of selection), `get_variable_defs` (tokens), Code Connect mappings, screenshots; Code-to-Canvas (Feb 2026) writes running UI back to Figma as editable layers |
| **Framelink Figma MCP** | `github.com/GLips/Figma-Context-MCP` | Medium | Community alternative, PAT-based, no Dev Mode seat needed |
| **Penpot MCP** (official) | `https://design.penpot.app/mcp/stream` | Medium | Open-source Figma alternative; free cloud + self-host |
| **Canva Connect MCP** | `https://mcp.canva.com/mcp` | Medium | Create/autofill/export designs via REST+OAuth |
| **Stitch MCP** (Google) | `stitch.withgoogle.com/docs/mcp/setup/` | Medium | Text-prompt → screens, pull into coding agent |
| **Magic MCP** (21st.dev) | `github.com/21st-dev/magic-mcp` | Medium | Text → polished React components |
| **shadcn MCP** | `ui.shadcn.com/docs/mcp` | ★ High | Browse/search/install shadcn/ui components by natural language |
| **Pencil MCP** | `@pencil.dev/cli` | Low-medium | `.pen` JSON design files, text-to-design |
| **Gummble / Mobbin MCP** | `mobbin.com/mcp` | Medium | 300k–600k real app screens for UX reference |

### 5. Communication & productivity
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **Slack MCP** (official) | remote `https://mcp.slack.com/mcp` (OAuth) | ★ High | Search, send, threads, canvases. Old local `server-slack` npm is archived/unmaintained |
| **AgentMail** | `https://mcp.agentmail.to/mcp` | Medium | Agent-owned inboxes, threads, attachments (36 tools) |
| **Notion MCP** (official) | `https://mcp.notion.com/mcp` (OAuth) | ★ High | Pages/databases |
| **Linear MCP** (official) | `https://mcp.linear.app/mcp` (+ `/readonly`) | ★ High | Issues/projects; also accepts API-key Bearer |
| **Google Workspace MCPs** | `https://mcp.google.com/gmail/mcp` etc. | Medium | Gmail + likely Drive/Calendar |

### 6. Cloud & infrastructure
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **AWS MCP** (official, awslabs) | `github.com/awslabs/mcp` · managed remote `https://aws-mcp.us-east-1.api.aws` (GA May 2026) | ★ High | Dozens of service-specific servers: EC2, S3, Lambda, CloudWatch, CDK, Bedrock… Part of AWS "Agent Toolkit" with skills/plugins |
| **Azure MCP** (Microsoft) | `github.com/microsoft/mcp` | ★ High | 40+ services via ARM |
| **Google Cloud MCP** | `github.com/googleapis/gcloud-mcp` | Medium | gcloud-CLI-backed; less mature than AWS/Azure as of mid-2026 |
| **Cloudflare MCP** | `github.com/cloudflare/mcp` · `https://mcp.cloudflare.com/mcp` | ★ High | Token-efficient "code-mode" full-API server |
| **Terraform MCP** (HashiCorp) | official | ★ High | Registry + HCP Terraform workspace lifecycle. Note: AWS deprecated its own Terraform tool in favor of HashiCorp's |
| **Vercel MCP** | `https://mcp.vercel.com` | ★ High | Projects/deployments; v0 platform API (`https://v0.app/api/mcp`) for UI generation |

### 7. Finance (for the fleet's own ops)
| Tool | Source | Maturity |
|---|---|---|
| **Stripe agent toolkit** | `github.com/stripe/agent-toolkit` | ★ High |
| **PayPal agent toolkit** | `github.com/paypal/agent-toolkit` | ★ High |
| **Plaid MCP** | official Dashboard MCP | Medium (diagnostics-focused, not general banking) |
| **Mercury / Ramp / Brex MCPs** | official hosted | Medium-high |

### 8. Image & video generation
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **Runway MCP** (official, May 2026) | hosted, OAuth | ★ High | Gen-4.5 + Seedance, Kling 3.0, Veo 3.1, GPT Image 2, Nano Banana Pro; billed to Runway plan |
| **SubPixel** | `github.com/KingPin/SubPixel` | Medium | Image gen via existing ChatGPT/Codex subscription — no extra API key; MCP + Claude skill; job-id polling pattern |
| **mcp-imagegen** (local, Rust) | `github.com/zavora-ai/mcp-imagegen` | Low-medium | Qwen-Image-2.1 via stable-diffusion.cpp on local GPU (Metal/CUDA); private, no cloud |
| **Leonardo MCP** | `https://mcp.leonardo.ai/v1/mcp` | Medium | Paid, pay-as-you-go |
| **Recraft MCP** | `https://mcp.recraft.ai/mcp` | Medium | From ~$0.007/image, vectorization |
| **Vertex AI genmedia MCPs** | `github.com/oga35767-eng/vertex-ai-creative-studio` (Go) | Low-medium | Imagen, Nano Banana, Chirp TTS, ffmpeg avtool — GCP-based |
| **ImagineArt MCP** | OAuth, 96 tools | Medium | Aggregates Sora/Veo/Kling/Runway/Midjourney |

### 9. Slide decks & documents
| Tool | Source | Maturity | Notes |
|---|---|---|---|
| **presentation-md** | `github.com/isatimur/presentation-md` (MIT) | ★ Medium-high | Universal skill+MCP: agent writes Deck JSON → self-contained HTML + native editable `.pptx`; 75 themes, 18 layouts; `npx @presentation-md/install <agent>` |
| **architect-library skills** | `github.com/lqdflying/architect-library` | Medium | `powerpoint-presentation`, `word-document`, `spreadsheet-document`, `pdf-document`, `excalidraw-diagram` skills — pptx via python-pptx + LibreOffice visual QA |
| **SlideSpeak MCP** | `github.com/SlideSpeak/slidespeak-mcp` · `https://mcp.slidespeak.co/mcp` | Medium | SaaS API → `.pptx`, templates, tone control, async tasks |
| **potxkit MCP** | `github.com/thevgergroup/potxkit` | Low-medium | Template repair: audit/normalize masters, palettes, layouts |
| **mindspace pptx skill** | `github.com/tezansahu/mindspace` | Low | pptxgenjs-based skill w/ design guidelines |

### 10. MCP infrastructure & registries
| Tool | Source | Notes |
|---|---|---|
| **Official MCP Registry** | modelcontextprotocol.io | Linux Foundation; `server.json` publishing |
| **Smithery.ai / Glama.ai / mcp.so / PulseMCP** | community directories | Discovery, quality scores |
| **FastMCP** (Python) | `github.com/jlowin/fastmcp` | Fastest way to build a server |
| **MCP Sentinel** | `github.com/pasihaka/mcp-sentinel` | Audit remote MCP servers for security (100/100 Smithery score) |
| **Parry** | `github.com/vaporif/parry` | Prompt-injection scanner for MCP tool I/O |

---

## B. Claude Code programmatic capabilities

How agents can drive Claude Code without a human at the keyboard:

1. **Headless CLI** — `claude -p "prompt" --output-format json` (single shot), `--resume <session_id>` / `--continue` for multi-turn, `--allowedTools`, `--permission-mode dontAsk`, `--dangerously-skip-permissions`, `--mcp-config`, `--max-turns`, `--max-budget-usd`. Structured output: `--output-format json|stream-json`, `--json-schema`.
2. **Agent SDK (official)** — `@anthropic-ai/claude-agent-sdk` (TypeScript, bundles CLI binary) and `claude-agent-sdk` (Python 3.10+). Typed `query()` async generator; avoids shelling out. Note: since v0.1.0 the SDK no longer loads Claude Code's system prompt by default — opt in.
3. **In-session primitives** — Subagents (`.claude/agents/*.md`), Skills (`SKILL.md` + slash commands), Hooks (lifecycle automation: lint/test/security gates), Plugins (`.claude-plugin/plugin.json`, install via `/plugin`), CLAUDE.md memory files, permissions/sandbox settings.
4. **GitHub Action** — `anthropics/claude-code-action@v1` for CI.
5. **Billing caveat** — Anthropic announced (May 2026) that SDK/`claude -p` would move to separate metered programmatic credits effective June 15, 2026; this was **paused before launch**. Re-verify before budgeting — it is the most likely thing to change.

Key repos/docs: `code.claude.com/docs` (llms.txt), `github.com/anthropics/claude-code`.

---

## C. Community skills, slash commands, agent harnesses

**Awesome lists (start here):**
- `github.com/cpiprint/awesome-claude-code` — tools, frameworks, agents, skills, hooks, MCP servers (actively maintained)
- `github.com/libukai/awesome-agent-skills` — ~5k stars, curated agent skills
- `github.com/ununununium/awesome-claude-code-skills` — skills, plugins, hooks, orchestrators
- `github.com/twzrd-sol/awesome-mcp-servers-2026` — production-ready/self-hosted MCP focus
- `github.com/gummble/awesome-design-mcp` — design-specific MCP servers

**Slash command packs:**
- `github.com/wshobson/commands` — 2.3k stars, production-ready commands
- `github.com/qdhenry/Claude-Command-Suite` — 1.2k stars, structured dev workflows (review, feature dev)
- `github.com/adimhsd/claude-code-everything-you-need-to-Know` — mental models + copy-paste `.claude/` (commands, skills, agents, hooks, workflows)
- `github.com/jeremylongshore/claude-code-plugins-plus-skills` — 340 plugins + 1367 skills w/ package manager (1.7k stars)

**Agent harnesses / orchestrators:**
- **ClaudeClaw** (`github.com/sbusso/claudeclaw`) — Claude Code plugin turning Claude into a persistent always-on orchestrator: listens to Slack/WhatsApp/Telegram/Discord/Gmail, routes to isolated agents, memory, scheduled tasks, webhooks; ~8k lines TS, 355 tests. *Closest existing analog to what the fleet needs.*
- **claudeclaw** (`github.com/aerolalit/claudeclaw`) — lighter: personality + heartbeat loop + Telegram bridge on Claude subscription, no separate API key
- **OpenClaw** (`github.com/openclaw/openclaw`) — the original pattern ClaudeClaw forked from (NanoClaw)
- **foreman** (`github.com/iceteahh/foreman`) — production harness design doc for `claude -p` workers in Go: durable queueing, sandboxing, budget enforcement, result evaluation, retry-with-feedback, human review gate. Design thesis: "we do not build an agent loop; we build deterministic plumbing around one." *Best architectural reference for the fleet's long-running-task problem.*
- **panda-corp research** (`github.com/mineitoshio/panda-corp` docs) — factory model: subagents + skills + hooks + worktrees + dynamic workflows + routines
- **ccpm** (`github.com/automazeio/ccpm`) — project-management workflow with specialized agents

**Specialized skill repos worth mining:**
- `github.com/lqdflying/architect-library` — office docs, diagrams, security audits, terraform review
- `github.com/tezansahu/mindspace` — pptx, insight extraction, skill-creator meta-skill
- `github.com/UserAd/ClaudeSkills` — tmux subagent orchestration skill, codex-assistant
- `github.com/transilienceai/communitytools` — pentest/bug-bounty skills + Playwright

---

## D. Top 10 to install/configure immediately

1. **GitHub MCP** (official remote `https://api.githubcopilot.com/mcp/`) — repo/issue/PR/actions; scope with `GITHUB_TOOLSETS`, use `--read-only` where possible.
2. **Playwright MCP** (`claude mcp add playwright npx @playwright/mcp@latest`) — real browser for testing, web automation, visual QA.
3. **Context7** — current library docs in context; biggest hallucination-killer.
4. **Slack MCP** (official remote `https://mcp.slack.com/mcp`) — replace/augment the custom Slack CLI with the maintained server.
5. **Figma MCP** (remote `https://mcp.figma.com/mcp`) — design-to-code loop incl. Code-to-Canvas write-back.
6. **Supabase MCP** (or crystaldba/postgres-mcp in restricted mode) — agent-usable database with guardrails.
7. **Claude Agent SDK** (TS or Python) — replace ad-hoc `claude -p` shelling with structured programmatic control.
8. **presentation-md** skill — decks as code (Deck JSON → HTML + editable pptx).
9. **Serena** — semantic code retrieval/editing for large repos.
10. **Tavily or Firecrawl MCP** — reliable web search/scrape (pick one to avoid tool overlap).

---

## E. Gaps — build vs. buy

| Gap | Verdict | Notes |
|---|---|---|
| **Swarm coordination layer** (shared task queue, agent heartbeat/liveness, work claiming, cross-agent memory) | **BUILD** | Nothing off-the-shelf does multi-agent Muse coordination. ClaudeClaw handles single-orchestrator multi-channel, not peer swarms. Design like foreman's "dumb orchestrator + smart prompts" thesis; expose it as an MCP server so every agent gets the same tools. |
| **Long-running task supervision** (days/weeks, no oversight: checkpointing, resume, escalation) | **BUILD** | Claude Code has Routines/schedules and session resume, but no durable workflow engine. foreman's design doc is the blueprint; implement queue + watchdog + audit trail. |
| **Fleet memory/knowledge base** (shared, writable, structured) | **BUILD (thin)** | FastMCP server over Postgres/Supabase with namespaced memories; agents read/write via tools. Trivial to build, high leverage. |
| **Background-run reliability** (our cron workers keep timing out) | **BUILD/FIX** | Root cause is worker startup + tool latency, not the task. Options: keep main-chat relay (current), or move to persistent `claude -p` workers with `--resume` sessions instead of cold starts. |
| **Prompt-injection & secrets guardrails for MCP** | **BUY/ADOPT** | Use Parry (scanner) + MCP Sentinel (audits); GitHub MCP's `--lockdown-mode`; Postgres `--access-mode=restricted`. Policy, not new code. |
| **Image/video generation** | **BUY** | Runway MCP or SubPixel — no reason to build. |
| **Slide decks** | **BUY/ADOPT** | presentation-md (MIT) + architect-library skills cover it. |
| **Design-to-code** | **BUY** | Figma official MCP. |
| **Cloud ops** | **BUY** | awslabs/mcp suite. |
| **Multi-channel fan-out** (Slack/Discord/Telegram/WhatsApp) | **ADOPT** | ClaudeClaw already does this; evaluate before building. |

**Bottom line:** buy the entire integration layer (MCP servers are a solved problem for GitHub/Slack/browser/DB/design/cloud/media). Build exactly three things: (1) the swarm coordination MCP, (2) the long-running task supervisor, (3) the shared fleet memory. Everything else is configuration.
