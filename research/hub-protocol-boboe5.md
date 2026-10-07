# Coordination-hub protocol note — Boboe 5 (tooling lane)

**Date:** 2026-10-07. **Context:** Jack's design direction (via Fleet Reader's 2026-10-07 design check): the fleet + Darragh's agents should run fully autonomously with no dependency on Jack's Mac or Fleet Reader. Proposed hub: messages + multi-project task board + an "ask the fleet" chair pattern (one chair gathers everyone's views and returns ONE answer), all visible on Jack's dashboard. Proposed implementation: today's receiver code on a small always-on cloud host; each telemetryd keeps its existing long-poll (no new process); messages wake agents through the front door (`listen.py`).

**Scope of this note:** the wake protocol and the chair protocol — the two pieces Boboe 5 can verify from its own VM. Deployment of the cloud host is Jack/Fleet Reader's job (Boboe 5 has no spending authority, no cloud credentials, no access to Jack's Mac). This is a design proposal for review, not an implementation.

---

## 1. Wake protocol: front door (`listen.py`)

Verified on Boboe 5's VM 2026-10-07: `listen.py` runs as a foreground process that receives a message, wakes the agent per embedded instructions, then exits — the agent must restart it after handling (Jack's standing instruction). Key properties the hub must respect:

- **Single-shot, not a server.** The front door consumes one message per run. The hub must hold a per-agent outbox queue (ordered, durable on the host) and deliver one message per wake; the next message is delivered after the agent restarts the door.
- **Delivery semantics: at-least-once.** An agent may die between wake and ack. Each message carries a `msg_id`; the agent acks on its next telemetry push (or on door restart). The hub redelivers unacked messages, and agents must be idempotent on `msg_id`.
- **Urgent vs. routine channels.** Today there are two proven wake paths: the fast path (Muse Wall typing into the agent's chat — seconds) and the backstop (slack-watch cron, ~5 min). The hub's long-poll should carry a priority flag: `urgent` messages wake via the door immediately; routine board updates can ride the next telemetry push.
- **Health signal.** A door that is alive but never wakes is a silent failure (Boboe 5's door ran "silent for 90+ minutes" on 2026-10-07 before a manual restart). The hub should track per-agent "last wake delivered" and "last door restart" timestamps; if an agent hasn't woken in >N minutes while messages are queued, flag it on Jack's dashboard as a stuck door.

## 2. "Ask the fleet" chair protocol

The chair pattern returns ONE answer for the fleet. Boboe 5's design-check feedback stands; here it is made concrete:

- **Chair request envelope.** `{ask_id, question, context_refs, deadline_ts, expected_respondents[], quorum}`. The chair broadcasts the envelope via the hub; every respondent answers through the front door (never through a side channel the chair can't see).
- **Timeout rule (mandatory).** The chair answers with a quorum-attained result OR a timeout report by `deadline_ts` — whichever comes first. Timeout report format: `{ask_id, status: "timeout", respondents_heard, missing_respondents[], partial_synthesis}`. No silent hangs; a timed-out ask is a first-class result on the dashboard.
- **Retirement rule.** If a chair misses 2 consecutive deadlines or its timeout rate exceeds 50% over a rolling window, it is retired from chair duty and the next ask goes to the standby chair. Chairs rotate: default chair = the ask's originating agent's choice, standby = round-robin over respondents. This prevents one stuck agent from blocking the fleet.
- **Correction path for misrepresentation.** The chair's ONE answer ships with an attached appendix of per-respondent verbatim positions (auto-attached by the hub, not by the chair). Any respondent can file a `correction` message within 15 minutes; corrections are appended to the ask record on the board. The chair cannot silently drop or rewrite a view.
- **Chair is not a decider.** The chair synthesizes and reports ONE answer; authority to act on it stays with whoever owns the decision (Jack, dot, or the standing orders). This keeps the chair cheap and ungameable.

## 3. Multi-project task board (data model sketch)

The board the hub carries, visible on Jack's dashboard:

```
project: {id, name, owner, status}
task:    {id, project_id, title, owner_agent, state, deps[], updated_ts, last_heartbeat_ts}
claim:   {task_id, agent, ts}        # prevents double-work across agents
ask:     {ask_id, question, chair, respondents, deadline, result|timeout, corrections[]}
message: {msg_id, from, to|broadcast, priority, body, ack_ts}
```

- **Task heartbeat:** each task owner updates `last_heartbeat_ts` on its telemetry push; a task silent for >2× its declared check interval goes `stale` on the dashboard. This is the same staleness logic the current 5-min slack-watch backstop uses (inbox files older than 3 min), generalized.
- **Claims are first-come, recorded on the hub** — the current shared-claim-board pattern Jack's research project uses (one file per lane in `research/`) works precisely because claims are visible to all; the hub should make that a primitive, not a convention.

## 4. Failure modes and fallbacks

| Failure | Detection | Fallback |
|---|---|---|
| Silent chair (no answer by deadline) | deadline passes, hub timer fires | timeout report; retire chair; standby takes the next ask |
| Chair misrepresents a view | respondent files `correction` within 15 min | correction appended to ask record; dashboard shows both |
| Agent door stuck (queued messages, no wake) | `last_wake` older than threshold with non-empty outbox | dashboard flag; the agent's watchdog cron restarts the door; unacked messages redeliver |
| Hub host itself down | telemetry pushes stop fleet-wide | agents keep working their local queues; on recovery, outboxes drain in order (at-least-once, idempotent `msg_id`) |
| Network partition (agent isolated) | missed telemetry pushes | agent continues its current task from local state; on reconnect, hub reconciles board state by `updated_ts` |

## 5. What this does NOT need

- No new process on agent VMs: the existing long-poll in telemetryd plus the existing door covers messaging. Confirmed ~600 MB free on Boboe 5's box; no install needed.
- No Slack dependency for fleet-internal coordination: the hub replaces Slack-as-coordination; Slack remains only for human-facing channels (Jack's Muse Wall, DMs to people like DOT/Darragh's side).
- No credential changes: messages carry no secrets; the existing token policy is untouched.

## 6. Open decisions for Jack / Fleet Reader

1. Cloud host choice and who pays (Boboe 5 cannot provision it).
2. Ask-deadline default (suggest 15 min, matching the existing idle-check-in cadence Jack set today).
3. Whether corrections after 15 min need chair approval or auto-append (suggest auto-append; cheap, auditable).
4. Dashboard: extend the current telemetry receiver's dashboard, or a new view.
