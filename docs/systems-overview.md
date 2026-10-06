# Boboe Agent Systems Overview

This document describes exactly how a Boboe agent (built on Meta's Muse
platform) works: what it is, what it can do, how work flows through it, and
what its limits are. It exists so Jack — and any AI working on the fleet
telemetry project — understands what the dashboard is looking at.

## 1. What a Boboe agent is

A Boboe agent is a personal AI agent: a long-running conversational AI with
its own Linux computer, its own memory, its own tools, and connections to
Jack's accounts. It is not a chatbot window — it is a persistent operator
that does work on its own, on a schedule, and in conversation.

Each agent has:
- **A name and identity** (Boboe 1–6), plus service identities (e.g. Boboe 2
  is `U0C6TQRHRT8` / `boboe2muse@gmail.com` in the agentnet Slack swarm, and
  the `Boboe2` GitHub user for this repo).
- **A VM**: Ubuntu 24.04 container, 2 vCPUs, ~100 GB disk, no GPU. Outbound
  network only — it cannot accept inbound connections, which is why
  telemetry is push-based.
- **Memory**: long-term notes (`MEMORY.md`), daily logs, and indexes of
  people and groups Jack interacts with. Memory persists across
  conversations; the agent gets smarter about Jack over time.
- **Standing instructions**: autonomy grants and hard boundaries. For
  example, Boboe 2 may act freely inside the Slack swarm but must ask Jack
  before spending money, deleting data, contacting anyone outside the swarm,
  or changing credentials.

## 2. How work flows: the execution model

There isn't one "thread" of execution — there are several, running at once:

### The main chat
The conversation with Jack. Synchronous turns: Jack writes, the agent
reasons, uses tools, and replies. This is where most directed work happens.

### Side chats
Separate persistent conversations (e.g. one per topic). Each has its own
transcript and memory scope, but the agent carries Jack's broader context
into all of them.

### Subagents (the key to "multiple tasks at once")
The agent can spawn **child agents** that work in the background while the
main conversation continues. A subagent inherits the parent's context, runs
its own task, and reports back when done. The parent can:
- run several subagents in parallel,
- check on them (`list`), send them follow-up instructions mid-task,
- close ones that are no longer needed, or resume interrupted ones.

Example: while answering Jack in chat, a subagent can be researching
something for 20 minutes in the background. The dashboard's single "current
status" line can't show both — which is why the telemetry reports active
subagents separately (see §5).

Subagents can spawn their own subagents one level down (a coordinator
pattern), but nesting stops there.

### Browser tasks
A separate delegation route for live web work: a real Chromium browser on
the agent's VM that can log into sites, fill forms, click through pages, and
make purchases (with approval). Distinct from subagents — you don't send a
subagent to do browser work.

### Scheduled work (crons, hooks, services)
- **Crons**: agent runs on a schedule (e.g. Boboe 2's Slack watch every
  5 min, telemetry watchdog every 15 min). Each run is a fresh worker that
  does its job and reports back.
- **Hooks**: event-driven automations that wake the agent when something
  arrives, rather than on a clock.
- **systemd services**: continuously running programs, like the telemetry
  daemon itself. A watchdog cron reinstalls the daemon after VM
  replacements (which wipe `/etc`).

So at any moment, an agent might be: talking to Jack, running 2 subagents,
with 3 crons ticking and a daemon pushing telemetry. The dashboard only
shows what can be read passively; the agent never writes reports for it.

## 3. Capabilities inventory

### Compute and building
- **Shell**: full bash on its VM; can run anything installable, chain
  commands, run background processes.
- **Files**: read, write, edit, organize. Can view images. Builds real
  artifacts: documents, web pages/apps, PDFs, presentations, spreadsheets.
- **Code**: writes, runs, tests, and debugs software (as this repo
  demonstrates). Can create reusable "skills" (playbooks) for repeated
  workflows.
- **Media**: generates images and video, text-to-speech, podcast-style
  audio.

### Web
- **Search & fetch**: web search (news, sports, weather, finance verticals),
  and text extraction from pages.
- **Live browser**: the Chromium route above — the agent can *do things*
  on the web, not just read.
- **Deep research**: can delegate open-ended investigations to a research
  agent that returns sourced findings.

### Connected accounts (Boboe 2's, others vary)
- **Gmail**: search, read, draft, send, labels.
- **Slack**: the agentnet swarm — reads channels/threads, posts replies.
- **Google Drive / Docs / Sheets / Slides / Forms**: full file and
  document workflows.
- **GitHub** (as the Boboe2 user): repos, files, commits, PRs, issues —
  this repo is managed that way.
- **Instagram Messages**: read and send DMs.
- **Media/services**: Spotify, Apple HealthKit / Google Health Connect,
  and others via the skill catalog.
- **Tailscale**: the agent's VM is on Jack's tailnet (client-only).

### Coordination
- **Group chats**: can participate in shared chats with Jack and others.
- **The swarm**: in agentnet, Boboe 2 has standing autonomy to read,
  decide, act, and reply without asking — inside the four boundaries
  named in §1.
- **Goals & tracking**: durable goals with progress tracking; concrete
  commitments (deliveries, reminders, trips) tracked until resolved.

### Memory and learning
- Curated long-term memory plus daily logs; people/group relationship
  maps; background jobs that maintain alignment and surface ideas.
- A personal **Feed** (editorial posts) and **Ideas** tab.

## 4. What the agent cannot do (honest limits)

- **No inbound network**: the VM can't accept incoming connections —
  everything is outbound/push.
- **No GPU**; modest CPU/RAM (see VM specs in README).
- **Approvals**: write actions on connected services (GitHub pushes,
  purchases, sharing changes) trigger approval cards Jack must accept.
- **The four boundaries** (§1): money, data deletion, outside contact,
  credential changes — always Jack first.
- **One status line**: the app's activity feed exposes a single "current"
  status, not a task list.
- **No mind-reading across agents**: Boboe 2 sees only its own VM and what
  the swarm shares. It cannot inspect another agent's machine — only what
  that agent's daemon reports.

## 5. What the telemetry reports (for dashboard builders)

Per 30-second heartbeat, each daemon sends:

| Section | Contents |
|---|---|
| `daemon` | payload version (dashboard flags outdated daemons) |
| `app_status` / `activity` | live status from the app's activity feed + recent entries |
| `observed` | heuristic working detection (file changes, CPU, browser), daemon's own files excluded |
| `system` | OS, cores, CPU model, host vs container memory, net rx/tx, Tailscale IP |
| `mem` / `cpu` / `disk` | process list with per-process CPU%, totals |
| `files` | workspace inventory: paths, sizes, mtimes (names only, never contents) |
| `capabilities` | static manifest of this agent's capabilities (this document, condensed) |
| `burst` | whether a live-tail burst is active |

Jack can click any agent card → detail view, and click any listed file to
fetch its contents (sandboxed: workspace-only, no hidden/secret files,
10 MB cap). The **Live tail** button switches that agent to 2-second
pushes for 2 minutes. Everything is read-only — there are no remote
controls, by Jack's choice.
