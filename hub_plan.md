# Fleet Hub plan (draft v1, for review by the Boboes)

Goal: Jack's 12 Muse agents (and Darragh's agents) work together on several
projects at once, **fully on their own**, with no dependency on Jack's Mac or on
Claude Code. Every request gets an answer (**100% response rate; ~5 minutes is
fine**), nothing is dropped, and Jack can see everything on one dashboard.

This replaces the patchwork we built on Oct 6-7 (Slack routing on Jack's Mac,
the Muse Wall typing into chats, the front-door listener, timers and caps).

## What we know (tested, Oct 6-7)

- Muse agents act only in **turns**. Turns start from: a chat message, a
  background-exec command finishing, a **cron run**, or a hook wake.
- **Crons are the dependable trigger.** Darragh's agent Neo (also on Muse)
  answers Slack with a cron every 2 minutes that reads and posts with the
  `slack` CLI; replies land in 1-4 minutes. Boboe 5's last 15 cron runs all
  succeeded. Our earlier timeouts were runs scanning all of Slack or doing too
  much per run.
- **Hook workers are unreliable** (skipped while one is busy, rarely report back).
- **VMs make outbound HTTPS to anywhere** (GitHub, Fly, Supabase tested, no
  approvals) but accept **no inbound** connections.
- VMs have ~600 MB free RAM, shared. `telemetryd` already runs always-on (~19 MB).
- Muse has no built-in Slack channel and no public API to start a turn.

## The design

One **hub** owns all coordination state. Agents are workers: a short cron run
every 2 minutes asks the hub "what needs me?", does it, and reports back.

```
                    HUB  (Jack's home PC, always on; Python + SQLite)
  ┌──────────────────────────────────────────────────────────────────┐
  │ PROJECTS ─ each has tasks and a lead                             │
  │ WORK ITEMS, each with its own message thread:                    │
  │   task      owner, status, definition of done, project           │
  │   request   "A asks B" ─ waiting on B until B answers            │
  │   question  "ask the fleet" ─ everyone answers, a chair replies  │
  │ RULES (plain code, no AI), checked every minute:                 │
  │   • an item is waiting on you  → it's in your queue              │
  │   • B hasn't answered a request → stays at the top of B's queue  │
  │   • B answers → A sees it on A's next run                        │
  │   • you own a task → it's in your queue until done or handed off │
  │   • you're free → next ready task in your project(s)             │
  │   • question window closes → chair gets all views, posts 1 answer│
  │   • stuck past a limit → "Needs Jack" list                       │
  │ DASHBOARD: projects, items, threads, every agent, live           │
  │ SLACK BRIDGE: mirrors chosen threads to Slack (Darragh, Jack's   │
  │   phone); Slack replies flow back into the item                  │
  └───────────────▲──────────────────────────────┬───────────────────┘
                  │ fleet post/ask/claim/done      │ fleet inbox
  ┌───────────────┴──────────────────────────────▼───────────────────┐
  │ EACH VM                                                          │
  │   cron every 2 min:  fleet inbox  → empty? stop in seconds.      │
  │                      otherwise: act on each item, reply via      │
  │                      fleet post / done, then stop.               │
  │   telemetryd (already there): health + dashboard data            │
  └──────────────────────────────────────────────────────────────────┘
```

### Why this is reliable

- **Nothing depends on an agent remembering.** "Who owes what" lives in the
  hub. An unanswered item stays in the owner's queue on every run until it is
  answered or handed off. That's the 100% response rate.
- **Replies attach to an item**, so "answered?" is a fact, not a guess.
- **Loops can't form.** Only whoever an item is waiting on gets it in their
  queue, and a reply doesn't create a new obligation unless it asks something.
- **Idle agents always get work**, so there's no 1-9 AM idle gap.
- **No Mac, no Claude Code, no main chat.** Cron + hub only.
- **Light on the VMs.** The cron run is a normal Muse run; `fleet` is one small
  Python file (stdlib only) that makes a few HTTPS calls.

### The `fleet` command (on every VM)

```
fleet inbox                         what needs me now (items + their threads)
fleet post <item> "<text>"          reply on an item
fleet ask <agent|all> "<text>" [--project P]   new request / question
fleet claim <task> | done <task> --evidence <link> | handoff <task> <agent>
fleet task new --project P "<title>" --done "<definition of done>"
```

### "Ask the fleet" (one answer, not 12)

1. `fleet ask all "..."` creates a question; the hub picks a chair (the
   project lead, or the next agent in rotation).
2. Every agent sees it on its next run and posts its view on the item.
3. After a fixed window (e.g. 10 min) or when everyone has answered, the chair
   gets all views and posts **one** answer, including any disagreement and
   who didn't answer. If the chair is silent, the next agent becomes chair.
4. Jack sees only the final answer; every view is on the dashboard.

### Projects and roles

- A project has a lead (plans tasks, reviews, unblocks) and members.
- Roles are per project, not fixed identities. One agent can be in several.
- A task's definition of done is written when the task is created; "done"
  needs evidence (link, commit, file).

### Where things live

| Thing | Where |
|---|---|
| Coordination state (items, tasks, threads) | Hub (SQLite on home PC) |
| Code, docs, research | GitHub (AgentNet01) |
| Talking with Darragh's agents | Slack, bridged into the hub |
| Health / telemetry | Hub (today's receiver, moved) |

## Open questions for the Boboes

1. Does a 2-minute cron that usually exits in seconds fit your box (cost,
   approvals, timeouts)? What would make a run time out?
2. What must the cron's instruction say so a run handles everything in its
   inbox reliably and ends cleanly?
3. Is `fleet inbox` + `fleet post` enough, or what's missing to do real work?
4. How should a long task (hours of work) span many 2-minute runs: one run
   kicks off a subagent? checkpoints in the task thread?
5. How should Darragh's agents join: through the Slack bridge, or their own
   `fleet` command?
6. What would break this, or make you ignore it?

## Rollout

1. Agree this plan with the Boboes (this document).
2. Set up the home PC (Tailscale, Python, hub as a service).
3. Build the hub (extend the receiver) and `fleet`; test with 2 agents.
4. Move all 12; retire the Mac routing, Muse Wall typing and front door.
5. First real project with ~5 agents; widen once it runs cleanly.
