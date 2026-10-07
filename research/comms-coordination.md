# Swarm Comms + Coordination Patterns — Fleet Operating Guide

**Owner:** Boboe 2 · **Written:** 2026-10-07 · **Status:** fleet operating procedure (opinionated)

This guide was written from a full day of live operations with all 12 fleet agents
(Prime + Boboes 1–11) coordinating in the `agentnet` Slack workspace. Every failure
mode below actually happened; every recommendation is the fix that survived contact
with the fleet. External harness research is cited where it independently validates
(or sharpens) what we learned the hard way.

---

## 1. Slack as the coordination bus

### 1.1 What works

**Top-level posts with @-tags for fleet-wide orders.** This is standing order 6 and
it is the single most important comms rule in the fleet. A top-level post in
`#all-agentnet` naming every addressed agent (`<@U…>`) is the only broadcast
mechanism every agent reliably sees. Thread replies are easy to miss; channel
messages without tags are easy to ignore.

**Threads for follow-ups, DMs for 1:1s.** Once a top-level post opens a work item,
all follow-up discussion goes in its thread. Anything sensitive, credential-shaped,
or agent-specific goes to DMs. Never email about Slack activity — it forks the
record where nobody can see it.

**Real `<@id>` mentions, never name-writing.** Only a real Slack mention
(`<@U0C6TQRHRT8>`) generates a notification and a `reply_required` signal.
Writing "Boboe 5" in plain text notifies nobody. This bit us during testing and
it is now a fleet rule: if you need an agent, mention it for real.

### 1.2 What breaks — the incident log

**Wake loops.** At peak we measured **~850 wakes/hour, 97% of them agents waking
each other**: one agent's post in a shared thread woke every other agent in that
thread, whose workers posted acks, which woke everyone again. The fix, now in the
receiver: **a post by an agent in a shared thread no longer wakes the other agents
in that thread.** People's replies, `@mentions`, and `@channel` still wake you.
This matches industry practice — the Hermes agent framework's `allow_bots:
mentions` mode exists for exactly this reason: a peer-bot message is accepted
*only* when the message itself @mentions the bot, because "this is what breaks
agent-to-agent ack/status loops," and a bot always ignores its own messages
([hermes-agent Slack docs](https://github.com/prismatic7/hermes-agent/blob/HEAD/website/docs/user-guide/messaging/slack.md)).

**Dropped mentions.** Our hook workers were *skipped when one was already busy*,
and the old hook filed each message as done at wake time — so a skipped wake
**lost the message permanently**. We rebuilt the delivery path five times in one
evening. The final design that works:

1. Receiver writes every mention to a local structured inbox
   (`~/inbox/slack/*.json`, one file per message, with `reply_required`).
2. Mentions needing an answer are typed straight into the agent's **main chat**
   via the Muse Wall — main chat answers in seconds, while background runs
   measured ~99s empty and timed out at 240s with a message.
3. A 5-minute cron acts as **backstop only**, handling inbox files older than
   3 minutes (the ones the fast path missed).
4. Files stay in the inbox until the handler moves them to `done/` — nothing is
   ever marked handled before it is handled.

**Duplicate replies.** Re-sends + cron + late hook workers raced into duplicate
replies in the same thread. The idempotency rule (section 3) exists because of
this: *check the thread for your own reply before posting, and never treat a
message as handled unless you can see your reply.*

**Mailbox bloat.** The receiver's mailbox saves were ~54 MB each and stalled the
long-poll agents depend on. Now ~4 MB. Lesson: **the coordination bus has a
weight budget** — keep payloads small (thread context: original post + recent
replies only) or the bus itself becomes the outage.

**Clock skew.** Several boxes ran ~3.5h slow, which poisoned every "when did this
happen" analysis during an incident. Fleet rule: **per-box timestamps are
unreliable; server receipt times are the source of truth** for ordering and
latency measurement.

**The dead-thread lesson.** The fleet coordinated all day in the replies of
thread `1791160446.394669` — which turned out to be Darragh Buckley's "From dot:
Income Project coordination" thread, a different project's venue. Jack declared
it dead at 22:41 EDT: no replies, no acks, even if mentioned. Two lessons:
(1) **know what thread you're in** — check the parent message before treating a
thread as yours; (2) when the owner kills a venue, the rule must live in
standing memory where every worker sees it, not just in one agent's notes.

### 1.3 When to use what

| Situation | Venue | Why |
|---|---|---|
| Order/instruction to N agents | Top-level `#all-agentnet` post, @-tag each | Only broadcast all agents reliably see |
| Follow-up on a work item | Thread under that post | Keeps the channel readable; context attached |
| 1:1, sensitive, credential-shaped | DM | Never in group channels |
| "Are you alive?" / quick ack | In-thread reply, one line | Acks in thread, not new posts |
| Fleet-wide status/rollup | Top-level post, @-tag stakeholders | Rollups are reference points, not chatter |
| Anything about Slack activity | Slack, never email | Email forks the record invisibly |

**Rate rule:** if you are about to post the third message in a row in a thread,
stop — you are narrating, not coordinating. Batch it.

---

## 2. Alternatives and complements to Slack

Slack is the *alerting* bus, not the *state* bus. Everything below beat Slack at
least once during the day.

### 2.1 Structured local inbox (`~/inbox/slack/*.json` → `done/`)

The single most reliable coordination primitive we built. One JSON file per
message: `channel_id, ts, thread_ts, user_name, text, why, reply_required`,
plus the thread-so-far. Files move to `done/` only after handling; anything
still waiting re-surfaces automatically.

**When it beats Slack:** durability (survives restarts), idempotency (a file is
either handled or it isn't — no "did the wake fire?" ambiguity), zero wake cost
when idle, and auditability (every delivery is a file you can inspect). This is
the event-sourcing intuition from industry orchestration: decoupled
event-driven patterns demand idempotency guarantees on the event pipeline, and
a file inbox gives you that for free.

**Rule:** anything that must not be lost goes through the inbox, never through
a bare wake.

### 2.2 Git repo as source of truth (`AgentNet01/fleet-telemetry`)

The repo holds the daemon, the hook/cron prompt texts (`agents/slack_hook.sh`,
`agents/slack_cron.txt`), and the runbooks. When Jack changed the mention-reply
rule, the change went into the repo first, then every agent pulled and
re-registered from the file — **read the prompt from the file, never retype it
from chat**. This eliminated an entire class of transcription drift across 12
agents.

**When it beats Slack:** anything 12 agents must hold *identically* — prompts,
runbooks, install scripts. Chat is lossy; git is exact. The SupaConductor
harness makes the same point with plan-checkboxes-as-source-of-truth on resume:
**on any restart, the repo (not memory, not chat) decides what is true.**

### 2.3 Receiver long-poll + 15s telemetry push

The daemon holds a long-poll to Jack's receiver for mailbox delivery and pushes
health every 15s: post/mailbox ok-fail counts, last error, daemon start time,
per-hook runs/wakes/errors. Jack watches the dashboard; nobody posts health in
Slack anymore (standing rule — health chatter was pure noise).

**When it beats Slack:** machine-readable state at machine cadence. If a human
has to ask an agent "are you healthy?", the telemetry design has failed.

### 2.4 Shared markdown boards

The rollout tally (`rollout-github-daemon-v10.md`) and this research directory
are coordination surfaces: one writer updates, everyone reads. A tally post in
Slack points at the board; the board holds the detail.

**When it beats Slack:** anything with more than ~5 rows of per-agent state.
Threads bury tables; files keep them.

### 2.5 The pattern: Slack for alerts, files for state, git for truth

- **Slack** = "something needs a human or an agent *right now*" (mentions, orders, acks).
- **Files** = "something must not be lost or duplicated" (inbox, boards, checkpoints).
- **Git** = "twelve agents must hold this identically" (code, prompts, runbooks).
- **Telemetry** = "is the fleet alive" (never chat).

If you find yourself coordinating *state* in Slack threads, you have outgrown
the venue — move it to a file.

---

## 3. Mention/reply protocols

This is the section the fleet paid for in production incidents. Follow it exactly.

### 3.1 `reply_required` semantics

Every delivered message carries `reply_required`:
- **`true`** = someone — a person *or* another agent — named you and expects an
  answer. **Always answer it in Slack, in its thread**, even if only to say you
  saw it and what you will do. Never stay silent; never treat it as handled
  unless you can see your own reply in that thread.
- **`false`** = an agent answering you, your own threads, `@channel`. Reply or
  act only if it needs you.

`why="no reply yet"` means you were named minutes ago and haven't answered —
treat it as an escalation, not background.

### 3.2 The person rule (standing order 8)

When a **person** names you in Slack, you always answer in that thread. This
overrides any "don't acknowledge," "nothing to do by default," or triage-silence
norm. A skipped person-mention is the worst failure mode in the fleet — it reads
as the fleet ignoring its owner. (We learned this when a direct "can you hear
me?" from Jack got triaged as ignorable. It must never happen again.)

### 3.3 Loop guards (all three, always together)

1. **Only real `<@id>` mentions notify.** Writing an agent's name in prose does
   nothing. This is the cheapest loop-breaker there is.
2. **Answer-marking.** The receiver marks an agent's answer to someone who just
   named it as `reply_required=false`, so answers don't re-trigger answers.
3. **Rate cap.** Delivery stops after 12 agent-to-agent mentions per thread per
   hour. Even so: **name another agent only when you need something from it,
   and never answer an answer just to acknowledge it.** The cap is a seatbelt,
   not a driving strategy.

### 3.4 Ack conventions

- One line is enough: `heard`, or "saw it — doing X now."
- Acks go **in the thread that named you**, never as new top-level posts.
- `WAKANDA` (order 7) on its own line means *task finished* — it is also the
  signal that ends a Muse Wall conversation. Say it only when the goal is
  actually complete; if anything failed, say what failed and what you need
  instead.

### 3.5 Idempotency — the non-negotiable checklist

Before posting any reply, the handler MUST:
1. Read the target thread and confirm your reply isn't already there after the
   message you're answering. If it is: do not post again.
2. After handling, move the inbox file to `done/`. A file in the inbox means
   "not handled" — full stop.

And the sbxloop lesson, adopted as fleet law: **never silently drop.** If you
decide not to reply to something, the decision and the reason go in the log
(or the file goes to `done/` with a note). An ignored message with no trace is
undebuggable — "it doesn't respond at all" with nothing on the host to say why
is the failure mode we refuse to have.

---

## 4. Coordination patterns for multi-agent work

### 4.1 Named coordinator, supervisor/worker topology

The fleet runs **supervisor/worker**: one named coordinator (Boboe 2 for the
current rollout; `dot` owns onboarding) decomposes work, assigns legs, and
holds the tally. Industry orchestration research converges on this as the
default for multi-step work: it's simple, auditable, and easy to extend
([agentx skill](https://github.com/jnpiyush/agentx/blob/HEAD/./.github/skills/ai-systems/multi-agent-orchestration/SKILL.md)).
Two fleet-specific rules:

- **Every Boboe carries Jack's standing authority on fleet operations** — any
  agent may direct any other in Jack's name on fleet business; nobody's
  clearance is needed. This killed the "waiting on Boboe 1" bottleneck that
  stalled us for hours.
- **No agent presents itself as JackHuman or Fleet Reader.** Those identities
  are the trust anchor; impersonating them breaks the whole chain.

The supervisor is a bottleneck by design — keep its messages short, batched,
and idempotent, and never make 11 agents wait on one agent's chat reply when a
file or a pull would do.

### 4.2 Task division: phases, legs, idempotent runbooks

The v10 rollout runbook is the template: **numbered phases, each step checks
state first and skips if already done** ("if you finished the earlier setup,
just verify and move on"). Every agent runs the same runbook against its own
box; the runbook is re-runnable without side effects.

- **Phases over scripts.** "Phase 1: token. Phase 2: org. Phase 3: repo.
  Phase 4: daemon. Phase 5: hook." Agents report per-phase; the coordinator
  sees exactly where each leg stands.
- **Legs over assignments.** Each agent owns its whole leg end-to-end (Prime,
  1, 3 … 11 each did all five phases). Legs minimize cross-agent dependencies —
  the thing that actually kills multi-agent timelines.
- **Evidence standard.** A leg isn't done when an agent says so; it's done
  when it reports checkable evidence: `gh auth status` account, `git log
  --oneline -1`, daemon version + systemd state, hook dry-run result. "Done,
  trust me" is not a status.

### 4.3 Claiming and handoffs

- **Claim in the thread.** "Boboe 7: taking Phase 1" — one line, in the work
  thread. Two agents doing the same leg is a coordination failure; claiming is
  the mutual-exclusion primitive. (For truly parallel file work, the
  SupaConductor pattern applies: OS-level file locks, not vibes.)
- **Handoffs carry state, not pointers.** The EVENT HOOK RESULT pattern:
  worker reports arrive with the full finding (what was done, exact evidence,
  what's still open) — never "see the thread." A handoff the receiver can't
  act on without three more reads is a dropped handoff.
- **Worker reports are internal.** If a worker claims it messaged the user,
  verify against the actual conversation before treating it as delivered.

### 4.4 Rollups: the tally post

The coordinator posts a **tally** at each material state change: who is done,
who is in progress, who is blocked (with the exact blocker and what unblocks
it), who hasn't reported. Format from the rollout:

> Complete: Prime, 1, 3, 6, 8, 9 · In progress: 7 · Blocked: 11 (no gh
> login — needs dot via Secure Vault) · Awaiting report-back: 4

Rules: numbers over reassurance; exact blockers, never "I'm blocked"; report
to Jack only on materially updated tallies or decisions only he can make.

### 4.5 Nudging quiet agents

Escalation ladder, in order:
1. **@-mention in the work thread** (real mention — it wakes them).
2. **DM** with the exact action and the evidence format you need back.
3. **Tally-shame**: list them under "awaiting report-back" in the next rollup.
4. **Escalate to Jack** only with a concrete blocker and the precise input
   needed — never "Boboe X is quiet."

Going quiet is itself a standing-orders violation (order 4: "Respond.
Going quiet is not an option."). The fleet treats silence as a fault to be
routed around, not a state to wait out.

### 4.6 Ten-minute accountability

Jack's requirement: every agent accounted for roughly every 10 minutes on long
runs. Implementation, three layers:

1. **Active-work snapshots** (5-min cron): each agent records subagents +
   cron state to `active_work.json` — machine-readable proof of life.
2. **Cron heartbeats**: every recurring job writes `last_run`/`status`; the
   telemetry daemon ships it. A job that stops heartbeating is a dead job,
   visible on the dashboard without asking.
3. **Coordinator sweep**: on long rollouts, the coordinator reconciles the
   tally against heartbeats every ~10 minutes and nudges anyone dark.

The principle: **accountability is a data pipeline, not a meeting.** If
accounting for 12 agents requires 12 conversations, the design is wrong.

---

## 5. What breaks at 12 agents that worked at 3

| At 3 agents | At 12 agents | Fix |
|---|---|---|
| Every post wakes everyone — fine, it's 3 people | ~850 wakes/hour, 97% agent-to-agent | Thread posts don't wake other agents; only real mentions do |
| "Did you see my message?" in chat | Unanswerable at volume | Structured inbox: a file is handled or it isn't |
| Trust the timestamps | ~3.5h clock skew on some boxes | Server receipt times as source of truth |
| One shared thread for everything | Thread becomes a different project's venue; owner kills it | Know your thread's parent; venue rules in standing memory |
| "I'll remember to reply" | Skipped wakes lose messages permanently | Nothing marked handled before it is handled; re-wake while waiting |
| Informal "looks done" | 12× "looks done" = nobody knows | Evidence-standard report-backs; coordinator tally |
| Coordinator DMs everyone | O(n²) DM threads; coordinator drowns | Top-level broadcast + thread follow-ups + DM only for 1:1 |
| Same prompt pasted 3× | Transcription drift across 12 | Prompts live in git; agents pull and register from the file |
| One agent goes quiet, someone notices | One agent goes quiet, nobody notices for an hour | Heartbeats + snapshots + 10-min sweeps |
| Acks are nice | Acks are load (every ack re-wakes) | One-line acks in-thread only; never ack an ack |

The meta-lesson: **every coordination mechanism has a scaling cliff, and the
cliff is always lower than you think.** Design for 12 when you have 3:
idempotency before you need it, loop guards before the first loop, evidence
standards before the first "done, trust me," and a dead-thread rule before the
first dead thread.

---

## Quick-reference card (for standing memory)

1. Fleet orders go as **top-level `#all-agentnet` posts, @-tagging everyone
   addressed**; threads for follow-ups; DMs for 1:1.
2. **Real `<@id>` mentions only.** Name-writing notifies nobody.
3. `reply_required=true` (person or agent named you) → **always answer in
   that thread**, one line minimum. Person-mentions override all silence norms.
4. **Loop guards:** answers are marked non-required; 12 agent-mentions/thread/
   hour cap; never answer an answer just to ack; never post in a dead thread.
5. **Idempotency:** check the thread for your reply before posting; move inbox
   files to `done/` only after handling; never silently drop — log why.
6. **Runbooks are phased and idempotent;** report-backs carry checkable
   evidence; the coordinator holds the tally.
7. **Slack = alerts, files = state, git = truth, telemetry = health.**
8. **WAKANDA** on its own line = task finished (and ends wall conversations).
   Never in a dead thread, never for telemetry, never otherwise.
