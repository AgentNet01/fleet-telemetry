# Decision ↔ hub_plan.md dependency map (Boboe 2 analysis, 2026-10-07)

**Purpose:** Jack has 14 open decisions (OPERATING_MODEL.md §2, briefed 2026-10-07
14:03 CDT) and is designing the coordination hub (hub_plan.md v1, 15ff9b5) right
now. This map shows which decisions the hub design settles, which it reshapes,
and which stay independent — so approving the hub plan closes several calls at
once. Written against hub_plan.md v1 **plus** my 4 proposed changes (delivered
to Fleet Reader 18:06 CDT); if a proposed change is rejected, the linked row
re-opens. Conditional, not a ruling.

## Resolved or constrained by the hub design (6)

| # | Decision | What the hub plan decides |
|---|---|---|
| D1 | Typed-envelope protocol | **Superseded.** Hub work items are typed (task / request / question) with state; "no machine coordination flows through free-form Slack" removes the need for `[CLAIM]`/`[UPDATE]`/`[DONE]` prefixes. Adopting the hub = adopting D1's substance in hub form. |
| D2 | Coordination ledger | **Constrained.** The hub IS the ledger (SQLite on the hub host). The qagent-spike-vs-build choice becomes: build hub's SQLite first, qagent only if hub outgrows it. NATS stays the documented graduation path. |
| D9 | Coordinator host | **Resolved, but supersedes the OM rec.** Hub plan puts the hub on Jack's always-on home PC, not Boboe 2's box. D9's answer is now "home PC" — needs Jack's infra confirmation (already rollout step 2). |
| D12 | Static roles | **Constrained.** Hub uses "roles per project, not fixed identities" — adopts "hats not identities" but replaces the fixed 1/2/4/2/2/1 split with per-project leads. The standing-defaults half of the rec is dropped. |
| D13 | Heartbeat channel | **Resolved by design.** Hub dashboard shows every agent live; HEARTBEAT-ROLLUP posts become unnecessary. The channel question disappears — dashboard is the channel. |
| D11 | Durable execution | **Constrained.** Hub Q4 (long tasks span runs via checkpoints in the task thread or spawned subagents) covers today's failure modes. "Later" for Inngest/Temporal stands. |

## Sharpened by the hub design, still open (2)

| # | Decision | New shape |
|---|---|---|
| D6 | SEV-1 notification channel | Hub has a "Needs Jack" list, but the plan says "no main chat" while the four gates still need Jack's approval — so the real question narrows to: **how does "Needs Jack" reach Jack?** (chat ping? dashboard alert? both?). My proposed rule (gates divert to `awaiting-approval`, never attempted inline) needs this answer to be implementable. |
| D10 | External watcher | Sharper, not closed. With the hub on the home PC as single point of failure, D10 is now really **"who watches the home PC + the fleet?"** My proposed hub-down fallback (3 missed runs → degrade to #all-agentnet) covers degradation but not alerting — the watcher placement call remains yours. |

## Independent of the hub — still need calls (6)

| # | Decision | Note |
|---|---|---|
| D3 | Token posture | Orthogonal to hub. |
| D4 | Publication pre-auth | Orthogonal; hub's request flow can surface publish requests but the policy call is separate. |
| D5 | **Per-agent $ budgets — now more urgent** | The hub plan adds a permanent cost floor: 12 agents × a cron every 2 min = 360 runs/hr minimum (plus Darragh's agents if they join), even when each run exits in seconds. The "generous cap with hard stop" recommendation becomes load-bearing — the cap must cover this floor or the hub silently stops at the worst moment. |
| D7 | Red-team drills | Orthogonal. |
| D8 | Re-admission bar | Orthogonal. |
| D14 | VM quarantine mechanics | Orthogonal; still needs Jack's infra input. |

## Bottom line

If the hub plan is approved as drafted (+ the 4 proposed changes), Jack's open
queue shrinks from 14 calls to **8**: D3, D4, **D5 (set the cap above the cron
floor)**, D6 (as "how does Needs-Jack reach me"), D7, D8, D10, D14. The other
six are answered by the hub design itself.
