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
- **A name and identity** (boboe1–11 and boboeprime), plus service identities (e.g. Boboe 2
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
something for 20 minutes in the background. Subagents are not readable
passively from the VM (see §6), so the dashboard can't show them.

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

Every 15 seconds (sooner when the activity feed changes), each daemon sends:

| Section | Contents |
|---|---|
| `daemon` | payload version (dashboard flags outdated daemons) |
| `activity` | the latest 8 activity-feed entries (the receiver keeps every entry it sees, up to 1000 per agent) |
| `observed` | file changes and CPU, daemon's own files excluded (shown as context; status comes only from `activity`) |
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

## 6. How the agent wakes, and what can be read passively

Confirmed by Boboe 2 and by `agents/probe_sources.sh` (Oct 2026).

**The AI is not a running process on the VM.** It exists as *turns*. Only
four things start a turn: a chat message from Jack, a cron firing, a hook
deciding to wake it, or a completion handoff (subagent, browser task, device
notification). SSH, HTTP or webhooks reach the computer, not the AI.

**The VM** is Linux; the AI is root with a persistent home (`/home/hatch`),
bash, Chromium, outbound internet and systemd. Each has a Tailscale address
on Jack's tailnet, but Tailscale runs on the platform host, outside the VM:
the VM's network namespace has only `lo` and `198.19.0.2` (host0), so it can't
bind its tailnet IP. Inbound is impossible: a server on `0.0.0.0:8799` was
refused from Jack's Mac over Tailscale (tested Oct 2026). No firewall in the VM.
The tailnet IP and name survive VM replacement.
**`/etc` is wiped on every reboot**, not only on VM replacement, and the
platform reboots VMs without warning (boboe2: 3 times in about 6 hours on Oct 6). The
systemd unit and its enable link vanish, so the daemon stays down until the
15-minute watchdog cron re-runs `install.sh`. `/home/hatch` persists. Anything Jack's side wants to
send must ride a connection the VM opens. Pushes to
Jack's Mac go through the runtime's tunnel proxy on `:3130`, which answers
407 if proxy credentials are sent.

**Connectors (Slack, Gmail, …) run inside the AI's turn, not on the VM.**
What a connector returned only lands on disk if the AI writes it there, and
every agent's `slack-watch/` folder uses its own improvised format.

### Documented read-only feeds

All on the sandbox API socket `$JARVIS_SANDBOX_API_SOCK`
(`/run/hatch/sandbox-api/api.sock`), documented in
`~/subscriptions/<name>/subscription.md`. Responses are
`{"ok": true, "result": {...}}`.

| Feed | Endpoint | What it holds |
|---|---|---|
| activity_feed | `GET /activity/recent?limit=10` (max 100; filters `is_goal=true\|false`, `activity_type=`) | The sidebar cards: `timestamp`, `activity_type` (email_sent, message_sent, file_created, file_updated, reminder_set, web_search, task_running, goal), `status` (success, error, pending, blocked, stopped), `title`, `status_title`, `subtitle`, optional `task_label`, `message_id` (the chat turn it came from). Outcomes, not tool calls. The newest `pending` entry is the app's "is working" badge. |
| device_syncs | `GET /device-syncs?source=notifications&limit=20`, `GET /device-syncs/<global_seq>` | Events synced from Jack's devices: `global_seq`, `producer_id`, `source`, `received_at`, `status`, `summary_preview`; single fetch adds `payload`, `payload_representation`. Notification/SMS/iMessage text is redacted. Nothing about the AI itself. |
| spaces_actions | `GET /spaces-actions?space_slug=<slug>&limit=20`, `?invocation_id=<id>`, `?source_kind=` | Every web-artifact action, whether from a UI tap, a tool call or a cron: `invocation_id`, `space_slug`, `action`, `status`, `invoked_at_ms`, `settled_at_ms`, `source_kind`, `source_ref`, `trigger_ref`, `args_preview`, `result_preview`, `error`. Result key: `invocations`. Web artifacts only. |

### Not readable passively

- Cron jobs and their run history, and subagents: only through the AI's own
  tools (`cron.runs`, `cron.status`, `subagent.list`).
- What started a turn (chat, cron or hook), the tool-call stream, the
  conversation, and what a connector returned.

### What the activity feed can and can't tell you (checked on Boboe 2, 30 entries)

- `message_id` is always set: `activity_thread:<uuid>` for goals, a plain
  uuid for simple cards. It stays the same while an item goes from pending to
  done, and the timestamp moves to the finish time, so the receiver keys its
  history on `message_id` (daemon v9 and later send it).
- Nothing says whether an item came from chat, a cron or a hook. Chat and
  background work look identical.
- A cron run only shows up if it does something that makes a card (sends a
  message or email, creates a file through the file tools, searches the web).
  A quiet Slack-watch tick leaves no trace in the feed.

### Credentials and hooks (per Boboe 2, Oct 2026)

- **Only the AI, inside a turn, can use a connector.** The `slack` CLI
  (`/opt/hatch/bin/slack`) gets its credential injected into the AI's turn;
  there is no token on disk or in env. Hook scripts, systemd services and any
  other plain process run without secrets or connector credentials.
- **Hooks** wake the AI from code. Script: `~/hooks/scripts/<name>.sh`, sources
  `$HATCH_HOOK_RUNTIME` (`~/hooks/runtime/hatch_hook_runtime.sh`) and ends each
  run with exactly one `silent "reason"` or `wake "reason" '{payload}'`.
  Definition (id, script, prompt, interval: default 60s, min 5s, delivery chat)
  is registered with the `hooks.add` tool, not a file. Lifecycle: add (disabled)
  → `dry_run` → `enable`. State goes in `~/hooks/state/`, and every run appends to a
  JSONL log (read with `hooks.logs`). `wake` starts a worker turn that decides
  whether to notify the main agent.
