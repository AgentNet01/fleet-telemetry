# Fleet Hub plan (v2, revised after review by 11 Boboes)

Goal: Jack's 12 Muse agents (and Darragh's agents) work together on several
projects at once, **fully on their own**, with no dependency on Jack's Mac or
on Claude Code. Every request gets an answer (**100% response rate; ~5 minutes
is fine**), nothing is dropped, and Jack sees everything on one dashboard.

This replaces the patchwork built Oct 6-7 (Slack routing on Jack's Mac, the
Muse Wall typing into chats, the front-door listener, timers and caps).

v1 -> v2: cron every 5 min (not 2) with small, capped runs; the hub assigns
leads, chairs and fallbacks by clock; two-step "ask the fleet"; checkpointed
long tasks; per-agent tokens, idempotent writes, local outbox; capability
tags; Darragh bridge via @mentions in a dedicated channel; parallel rollout.

## What we know (tested, Oct 6-7)

- Muse agents act only in **turns** (a chat message, a background command
  finishing, a **cron run**, or a hook wake). No inbound connections to VMs;
  outbound HTTPS works to anywhere without approvals.
- **Crons are the dependable trigger.** Darragh's agent Neo (on Muse) answers
  Slack with a 2-minute cron, replies in 1-4 min. Our cron runs time out only
  when a run tries to do too much (scan all of Slack, handle a full inbox), or,
  we suspect, waits on an approval nobody answers.
- Cron timing is loose: a 1-min cron drifted to every 4-5 min (queued runs are
  coalesced). Empty runs have taken up to ~99s to start and finish.
- Hook workers are unreliable (skipped while busy, rarely report back).
- ~600 MB free RAM per VM, shared; `telemetryd` already runs always-on.
- Jack's home PC runs the hub and is always on.

## The design

```
                    HUB  (Jack's home PC, always on; Python + SQLite)
  ┌──────────────────────────────────────────────────────────────────┐
  │ PROJECTS: lead + deputy (named in the project record), members   │
  │ AGENTS:   token, capabilities (e.g. drive-write, etsy, gh)       │
  │ WORK ITEMS, each with a thread:                                  │
  │   task      project, owner, definition of done, needs (caps),    │
  │             checkpoint {done, next, blocked_on, evidence}        │
  │   request   "A asks B": waiting on B                             │
  │   question  "ask the fleet": views, then one chair answer        │
  │ RULES (plain code, every minute):                                │
  │   • waiting on you → in your inbox, oldest first, until answered │
  │   • owner silent for 3 runs (~15 min) → re-offered to deputy/lead│
  │   • task with no new checkpoint for 3 runs → released to lead    │
  │   • lead assigns tasks; unassigned for 30 min → offered to an    │
  │     idle member with matching capabilities                       │
  │   • request chain deeper than 5 → "Needs Jack"                   │
  │   • anything needing Jack's 4 gates (spend, delete, outside      │
  │     contact, credentials) → "Needs Jack", never blocks a run     │
  │ DASHBOARD: Needs Jack (top) · overdue items and who they wait on │
  │   · projects/tasks/threads · agents: working/stuck/silent by last│
  │   meaningful action · every view on questions · freshness stamps │
  │ SLACK BRIDGE: requests to Darragh's agents → @mention in a       │
  │   dedicated channel; their in-thread replies flow back; dedup key│
  │ BACKUP: SQLite pushed to GitHub hourly; healthchecks.io ping     │
  └───────────────▲──────────────────────────────┬───────────────────┘
                  │ fleet post/ask/claim/done/   │ fleet inbox (≤3 items)
                  │ checkpoint (outbox if down)  │
  ┌───────────────┴──────────────────────────────▼───────────────────┐
  │ EACH VM: cron every 5 min ── a short, capped worker run          │
  │   telemetryd (already there): health + dashboard data            │
  └──────────────────────────────────────────────────────────────────┘
```

### The worker run (the cron instruction, drafted by Boboe 2)

```
FLEET WORKER RUN — about 90 seconds, then exit no matter what.
1. fleet inbox   (10s timeout). Empty → exit now, no other tool calls.
2. Handle at most 3 items, oldest first. One next action each:
   read the item, then reply / claim / checkpoint / done via fleet.
3. Never do more than ~2 min of work in a run: do one bounded chunk, write
   a checkpoint (done, next, blocked_on, evidence), and exit. Leftover items
   wait for the next run.
4. Never wait on an approval: anything needing Jack's gates → fleet post
   "awaiting-approval: <what>" and move on.
5. Every network call has a timeout; on failure note it and continue.
   If the hub is unreachable, fleet queues writes locally and the run exits.
```

Expect runs every ~5 min (sometimes later). That meets "~5 minutes is fine".
Cost: ~288 runs/agent/day, mostly empty; the hub tracks the empty-run rate.

### The `fleet` command (one stdlib Python file on every VM)

```
fleet inbox                              what needs me now (≤3 items, with
                                         checkpoint + short thread summary)
fleet post <item> "<text>"               reply on an item
fleet ask <agent|all> "<text>" [-p P]    new request / question
fleet task new -p P "<title>" --done "<definition>" [--needs cap,...]
fleet claim <task> | done <task> --evidence <link>
fleet checkpoint <task> --done ".." --next ".." [--blocked ".."]
fleet handoff <task> <agent>             receiver or lead must accept
```

Each agent has its own token. Every write carries an idempotency key, so a run
that timed out can safely redo its work. Writes made while the hub is down
are queued in `~/.fleet/outbox` and sent on the next run.

### "Ask the fleet" (one answer, not 12)

1. `fleet ask all "..."` creates a question. The hub assigns the chair: the
   project lead (deputy as fallback), never chosen by the agents.
2. Each agent posts its view (capped length) on its next run.
3. The window closes at max(10 min, 3 runs after the last agent was
   notified), or early once at least 7 views are in.
4. The chair gets all views on its next run and posts **one** answer,
   labelled *consensus*, *majority (n-m)*, or *chair's call*, with dissent
   and non-responders named. Chair silent 5 min after the window closes → the
   hub promotes the deputy.
5. Jack sees the answer. Every view is on the dashboard.

### Projects, roles, long work

- A project names a lead and a deputy (set by Jack or the project owner, e.g.
  dot for the Income Project). The lead plans and assigns tasks.
- Agents declare capabilities; tasks list what they need; the hub never hands
  a task to an agent that can't do it.
- Long tasks are worked in chunks across many runs. Each run resumes from the
  task's checkpoint, does one chunk, commits real output (GitHub or Drive), and
  updates the checkpoint. No subagents for long work.
- Done means evidence (a link, commit or file).

### Darragh's agents

They keep their own proven setup (2-min cron + Slack CLI); no hub access. The
hub's Slack bridge posts our requests to them as @mentions in a dedicated
channel and imports their in-thread replies. Our side owns the follow-up: an
unanswered bridged request stays overdue on the dashboard and escalates to
Darragh, then Jack.

### Where things live

| Thing | Where |
|---|---|
| Coordination state (projects, items, threads, checkpoints) | Hub (SQLite on home PC, hourly backup to GitHub) |
| Code, docs, research, task output | GitHub (AgentNet01), or Drive |
| Talking with Darragh's agents | Slack, via the hub's bridge |
| Health / telemetry | Hub (today's receiver, moved) |

## Rollout

1. ✅ Review by the Boboes (this v2).
2. Set up the home PC: Tailscale, Python, hub as an always-on service.
3. Build the hub (extending today's receiver) and `fleet`, with tests.
4. Approval test: run `fleet inbox` and `fleet post` from a cron run on 2
   agents and confirm no approval prompts and no timeouts.
5. Run the hub **alongside** today's setup for 24h; keep the 5-min Slack
   backstop until every old inbox has been empty for 24h; then retire the
   Mac routing, Muse Wall typing and front door.
6. First real project: Darragh's Income Project with 3-4 Boboes, Slack bridge
   live, zero disruption to Darragh's agents. Widen after it runs cleanly.

## Decided / not doing

- Hub on Jack's home PC (always on), not a cloud host. (Boboe 11 preferred a
  VPS; Jack's call.)
- No Slack fallback for our agents if the hub is briefly down: the outbox
  holds writes and runs retry; ad-hoc Slack coordination is what we're
  replacing.
- No agent-chosen chairs, no rotation by agent agreement, no subagents for
  long work, no cost dashboard until real cost data exists.
