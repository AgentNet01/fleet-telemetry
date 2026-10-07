# Lane 5: Skills & Agent Tools Catalog — Boboe Fleet Agentic-Swarm Research

**Author:** Boboe 4 (lane 5 owner) · **Date:** 2026-10-07 · **For:** Jack's agentic-swarm research

---

## 1. What exists RIGHT NOW

### 1a. Bundled skills: 88 total in `/opt/hatch/skills/`

Full directory listing (verified 2026-10-07): apple-healthkit, artifacts, asana, booking, box, calendly, canva, device-data, dropbox, duffel, evernote, facebook, facebook-cli, figma, flightaware, forget, function-health, generate_podcast, ghl, github, gmail, goals, google-calendar, google-contacts, google-docs, google-drive, google-forms, google-health-connect, google-sheets, google-slides, google-tasks, granola, healthex, image-search, instagram, instagram-messages, klaviyo, linear, lovable, media-library, messenger, meta-ads, meta-threads, muse-early-access, muse-feedback, muse_db, notion, opentable, outlook-calendar, outlook-contacts, outlook-mail, peloton, philips-hue, places-search, plaid, podcast, printify, quickbooks, replit, self-awareness, share-ideas, shopify, shopping, skill-creator, slack, social-content-performance, spaces, spotify, stripe, subscription-status, tailscale, tessie, threads, threads-messages, ticketmaster, todoist, travel-planning, tts, vercel, voice-calls, voice-selector, wearables-comms, wide-research, withings, zapier, zoom.

### 1b. Workspace skills: ZERO

`~/workspace/skills/` does not exist. The fleet has built no custom skills yet. This is the single biggest lever: everything in §5 below can be built here.

### 1c. Skills with `includeInPrompt: true` (always loaded, no lookup needed)

- **shopping** — product search/compare/purchase (Meta catalog, agentic browser search, Facebook Marketplace)
- **booking** — flight/hotel/restaurant/ticket transactions (routes to duffel/opentable/ticketmaster)
- **goals** — internal playbook for user goal tracking (not an integration)
- **skill_creator** — the skill-building skill itself

---

## 2. How to build custom skills

Read: `/opt/hatch/skills/skill-creator/SKILL.md`. The workflow:

1. **Pick a narrow scope.** One clear job per skill. Split unrelated jobs into separate skills.
2. **Target path:** `~/workspace/skills/<name>/`
3. **File layout:**
   - `SKILL.md` — operational core only. Frontmatter requires `name` + `description` (the description is what triggers the skill, so write it as "what it does + when to use it").
   - `references/` — bulky docs, schemas, tutorials (only if it materially shortens SKILL.md).
   - `assets/` — templates/output assets only when the final output uses them.
   - `bin/` — helper binaries/CLIs; prefer checked-in helpers over prompt-side auth instructions.
4. **Two flavors:** tool-backed skills (`Purpose`, `Tooling`, `Auth`, `Operating Rules`) or workflow-only skills (`Purpose`, `Workflow`, `Output Contract`, `Operating Rules`).
5. **Trim aggressively.** The body tells the model what to do next, not the whole domain.
6. **Sanity check:** commands, paths, auth flows must match real runtime behavior. If you write Python CLIs, `python3 -m py_compile` them before reporting success.
7. **Connector skills:** never hand-write credential flows. Once a connector is connected, scaffold it:
   `/opt/hatch/skills/skill-creator/bin/scaffold-connector-skill --provider <provider>`
   This generates the `Tooling`/`Auth` sections with the real credential mechanics. Full authoring rules in `references/authoring_guide.md`.

**Key implication for the fleet:** any agent can mint a new skill in minutes with this workflow. Skill-building is itself a fleet capability — Boboes can build skills for each other.

---

## 3. Capability catalog (what agents can actually produce today)

### 3a. Software development
| Skill | Produces |
|---|---|
| **github** | Repo inspection (code search, files, PRs, issues); PRs/pushes with per-action approval. Auth: Muse GitHub App + owner must install app on repos. |
| **vercel** | Inspect/manage projects & deployments; read build/runtime logs; create deployments (writes need granular approval). |
| **replit** | Read, create, update, publish full Replit apps. Read-only first, scope-add for writes. |
| **lovable** | Brief → working website/prototype; edit, inspect code, publish. Same read-only-first model. |
| **spaces** | Hosted web artifacts — static HTML or TypeScript full-stack (Drizzle/Cloudflare backend) dashboards/apps built as Muse artifacts. No auth (internal). |
| **zapier** | Trigger/orchestrate workflows across thousands of apps via Zapier MCP (agentic-mode reviewed tools). |

### 3b. Slide / deck building
| Skill | Produces |
|---|---|
| **artifacts/presentation** | Real `.pptx` decks: per-slide HTML + `deck.css` + `deck.json` manifest, StylePlan theme system, render-gated, PDF/HTML export. This is the primary deck builder. |
| **google-slides** | Push artifact-built `.pptx` into the user's Google Slides (Slides-native assembly forbidden; re-upload replaces all slides). |
| **canva** | Editable Canva designs: presentations, social posts, flyers, infographics; AI image gen, background removal. Limit: `create-design` can't apply brand kits (legacy flow only); no in-place content editing — unsupported edits punt to the user in the Canva editor. |
| **figma** | Read/inspect-oriented: pull design specs, tokens, assets to implement in code; limited create/edit via gated tools. |

### 3c. Image generation
| Capability | Source |
|---|---|
| AI image generation | `media` tool namespace (built-in `media.generate` pipeline) + Canva `generate-image` + `meta-ads-cli creative generate-image` (placement-aware) |
| Reference imagery | **image-search** (web image URLs with preflight for hotlink/watermark rejection; returns locators, not files) |
| User's own photos | **media-library** (uploaded library + device galleries; read-only) |

### 3d. Video / audio
| Capability | Source |
|---|---|
| Video generation | `media` tool namespace (`media.generate_video`) — **no catalog skill documents it** (referenced only inside meta-ads). Needs proper cataloging. |
| Podcast / narrated audio | **podcast** / **generate_podcast** (identical duplicates — reference one): multi-speaker MP3s with Meta AI voices, cover art, RSS publishing, save-to-Spotify, cron-schedulable series |
| Voice notes / TTS | **tts** CLI: single-shot voice notes or full multi-speaker script synthesis → MP3 |

### 3e. Data analysis
| Skill | Produces |
|---|---|
| **google-sheets** | Full Sheets control: create, read/write/append cells, formatting, batchUpdate for structured data work |
| **artifacts/spreadsheet** | `.xlsx` workbooks as build artifacts with render verification |
| **muse_db** | Read-only SQL over Muse's own records: transcripts, agent executions, tool calls, goals, memories, scheduler state — the fleet's internal telemetry for diagnosis |
| **function-health** | Lab biomarkers + clinician notes via FHIR API (strict no-fabrication rule) |

### 3f. Web research
| Skill | Produces |
|---|---|
| **browser** (built-in) | Web search + page-text fetch |
| **wide-research** | Fan-out pattern: one manager subagent × N independent inputs → single normalized result set (the fleet's parallel-research primitive) |
| **shopping** | Product research with real prices/images/URLs; agentic browser product search |
| **image-search** | Web image sourcing (above) |

### 3g. Communication & coordination
| Skill | Produces |
|---|---|
| **slack** | Read/search channels & threads; post messages; reply in threads (mutations need approval w/ argument preview). The fleet's current coordination layer. |
| **gmail** / **outlook-mail** | Full email control: search/read/send/reply/forward/drafts/attachments |
| **google-calendar** / **outlook-calendar** | Agenda, event CRUD, freebusy, attendees |
| **zoom** | Meeting/call/recording/transcript review; summaries + action items (every tool call needs explicit approval) |
| **granola** | Search/read meeting notes & transcripts (read-only) |
| **todoist** / **linear** / **asana** | Task/issue/project tracking — all three are **user-facing** (Jack's OAuth), read-only-first, write scopes need user consent |
| **goals** | Internal user-goal tracking playbook |

### 3h. Documents & knowledge
**google-docs** (read/create/edit; build as artifact docx then convert), **artifacts/document** (real `.docx` with tracked changes/comments), **artifacts/pdf**, **notion** (pages/databases via MCP), **evernote** (notes; creation needs per-action approval), **google-drive** / **box** / **dropbox** (file stores — note: Drive is not connected in this environment).

### 3i. Built-in agent tools (not skills, always available)
`subagent` (delegation), `cron` + `hooks` (scheduling/event triggers), `artifact` (documents, web pages/apps, decks, sheets), `widget` (interactive chat cards), `media` (image/video generation), `map` (places/coordinates), `social` (social search), `browser` (web), `muse.exec` (shell), `muse.db` (internal records), `tracking` (commitments/deliveries), `user_goal` (goals), `device` (paired devices).

---

## 4. Gaps — what the fleet needs that doesn't exist

### 4a. The fleet layer (highest priority — blocks autonomous multi-day operation)
1. **No fleet task queue.** Todoist/Linear/Asana are Jack's personal task lists behind his OAuth with approval-gated writes. Nothing models *inter-agent* work queues, agent-to-agent assignment, or fleet-wide work status that agents own themselves.
2. **No shared status board / heartbeat ledger.** No lightweight agent-owned "who is doing what, what was decided" log. Docs/Notion/Evernote are per-user integrations with approval flows — wrong tool for agent-to-agent state.
3. **No escalation / nudge mechanism.** No codified pattern for an agent to ping another on a schedule, re-nudge a stuck owner, or escalate to Jack after N hours. Cron infrastructure exists at runtime but no skill encodes the SLA pattern — cross-agent accountability is ad hoc. (Directly relevant to Jack's "every 10 minutes" requirement.)
4. **No shared fleet memory schema.** `muse_db` reads Muse records and Sheets/Drive store files, but there is no canonical structured store (key-value / fleet-state DB) for agents to write and read shared state, task results, or cross-agent progress.
5. **Auth is per-user and user-gated.** Every connector needs Jack to click an OAuth link, often with granular write-scope consent (Todoist/Linear are read-only-first). If a connector lapses mid-mission with Jack unavailable, agents silently degrade to read-only. No self-recovery path — a real risk for weeks of unattended operation.

### 4b. Development & reliability
6. **No CI/CD skill.** The fleet can deploy via Vercel/Replit/Lovable but cannot run tests, linters, or pre-merge checks — no way to verify code before shipping.
7. **No sandbox execution for its own code.** No general-purpose "run this script, show output" environment, so agents can't safely execute generated or untrusted code.
8. **No monitoring/alerting skill.** Beyond Vercel build logs, nothing watches uptime, pages an agent on failure, or tracks error rates.
9. **GitHub depth is thin.** No dedicated reviewed surface for review comments, branch protection checks, or issue triage flows.

### 4c. Media & publishing
10. **No standalone video-generation skill.** `media.generate_video` exists but is undocumented in the catalog — fleet agents can't discover its parameters/costs/limits.
11. **No organic social publishing skill.** Analytics (own Instagram posts) and paid ads exist, but nothing posts organically to Instagram/TikTok/YouTube. (Pericles holds the organic-social workstream — verify whether a separate publishing capability exists before planning around it.)
12. **No brand-template enforcement.** Canva brand kits only work through a legacy flow; nothing enforces fleet-wide fonts/colors/logos/templates across Canva, Slides, and ad creative. Multi-agent output will drift visually without this.
13. **Canva can't do in-place edits.** Element-level fixes get punted to Jack in the Canva editor — breaks full autonomy for design tasks.
14. **AI creative needs a standing review step.** Meta-ads requires human inspection of generated images for likeness/logo issues; fleet agents need a codified review gate since AI images can silently include unauthorized marks.

### 4d. Dead ends & hygiene
15. **voice-calls is a dead end.** The skill dir is actually the voice-selector catalog (`voice_source.json`) — there is no phone-calling capability. Don't plan around it.
16. **podcast/ vs generate_podcast/ duplication.** Identical SKILL.md copies — fleet docs should reference one.
17. **Printify is human-finalized.** Product publishes and orders need confirmation (real charges) — agent-drafted, human-approved.

---

## 5. Recommendations — skills to build (prioritized)

Build in `~/workspace/skills/<name>/` using the skill-creator workflow (§2). Suggested build order:

### P0 — unblock autonomous fleet operation
1. **`fleet-queue`** — the fleet's own work queue. Workflow-only skill: claim/assign/complete semantics over a shared JSONL or SQLite store in the fleet repo; no OAuth, no approvals. This is the single most important missing piece.
2. **`fleet-status`** — heartbeat + status board. Each agent writes a heartbeat (what I'm doing, ETA, blockers) on a cadence; the skill defines the schema and the read path for "who is alive, who is stuck." Directly serves Jack's 10-minute accountability requirement.
3. **`fleet-nudge`** — escalation ladder as a skill: nudge owner → re-nudge after X → escalate to Jack. Codifies what is currently ad hoc.
4. **`fleet-memory`** — shared key-value/decision log with append/read semantics all agents can use without approval gates. (Could merge with fleet-status into one `fleet-state` skill if scope discipline holds — but the skill-creator guidance says one job per skill, so keep them separate.)

### P1 — reliability for long-running work
5. **`fleet-ci`** — run tests/linters/builds for fleet repo changes before deploy. Wraps the repo's own test scripts with a standard pass/fail contract.
6. **`sandbox-exec`** — safe script execution with timeouts and output capture for generated code.
7. **`fleet-monitor`** — uptime/error alerting that pages the owning agent (and escalates via fleet-nudge).

### P2 — media & publishing
8. **`video-gen`** — catalog the `media.generate_video` capability properly: parameters, costs, limits, verification steps.
9. **`brand-kit`** — fleet brand enforcement: fonts, colors, logos, templates applied across Canva/Slides/ad creative from one source of truth.
10. **`social-publish`** — organic publishing (verify the underlying capability exists first; if not, this becomes a connector-build task, not just a skill).

### P3 — hygiene
11. Dedupe `podcast/` vs `generate_podcast/` references in fleet docs.
12. Document the `voice-calls` dead end so no lane plans around it.

**Auth note:** P0 skills should be deliberately *connector-free* (local files/repo) so they work with zero OAuth and zero approval gates — that's the point. Anything needing Jack's accounts stays in the existing connector skills.

---

## 6. One-line summary for the rollup

88 bundled skills cover single-agent dev, media, research, and comms well; zero workspace skills exist; the fleet layer (shared queue, status board, nudge/escalation, shared memory) is entirely missing and must be built as local, approval-free workspace skills before days/weeks-long autonomous operation is credible.
