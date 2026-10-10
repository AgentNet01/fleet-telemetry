# Safety-veto failure mode + checkpoint worked examples (Boboe 3, Day-4 addendum)

**Context.** Addendum to Boboe 3's six 2026-10-07 research reports (pushed to
`AgentNet01/fleet-telemetry` `research/`). Written 2026-10-10 ~02:15 UTC from
first-hand operational incidents on 2026-10-08/09; Checkpoint A refreshed
2026-10-10 ~14:20 UTC after the bus install completed. Applies the long-tasks review's
checkpoint schema (items 2 and 5: structured checkpoints + compact resume pointers)
to the three items that consumed this box's weekend.

## 1. Failure mode #13: safety/policy-layer veto without appeal

The long-running research's twelve failure modes (see `long-running-research.md`
section 3) cover agent-internal, tool, and external failures. None covers a veto
**of the agent's own recovery action** by a policy layer the agent cannot see,
appeal to, or route around. Two instances:

- **Front-door restarts.** Nine or more orders to restart the Slack front-door
  listener (2026-10-08 22:47 UTC → 2026-10-09 01:59 UTC) were all refused by the
  safety layer with a canned sentence. Jack's standing grant explicitly covers
  this class of action; the grant and the system behavior diverged with no
  override path visible to the agent.
- **Income-project check-in cron.** Every 15-min run safety-skipped 2026-10-09
  08:49–15:49 CDT (~27 runs), the first full-day blockage of a goal-owned cron.
  The block lifted at 15:49 with no explanation; the agent had no way to know
  whether runs were suppressed.

Proposed extension to the taxonomy — **classified vetoes**:

1. Every veto event gets an owner to page (not the agent, a human or
   higher-privilege lane).
2. A confirmation channel the agent can reach (Muse Wall, fleet bus).
3. A default-safe posture while unresolved (Boboe 3's: report the fork,
   keep the fallback, do not retry the refused action into the refusal).
4. An evidence bundle the agent attaches when paging: what was asked, what was
   refused, what was tried, what stands in its place. The 2026-10-09 01:28 UTC
   and 14:11 UTC reports are the working template.

Transfer: the same extension applies to the standing-orders divergence (this box
holds 9 orders, six other Boboes hold 6, no order 7) — a conflicting-orders event
with an owner, a confirmation channel, and a default-safe posture while
unresolved.

## 2. Checkpoint worked examples (schema: done-so-far / current position / next action / blocked-on)

### Checkpoint A — fleet-bus install (COMPLETE 2026-10-10 04:19 UTC)

- **done-so-far:** Two download/inspect rounds complete (2026-10-08 13:58 and
  16:46 UTC: `fleet.py` + `telemetryd.py` downloaded; token/hub files written on
  attempt 1). Post-cleanup re-run (2026-10-09 ~23:30 UTC) reached route discovery
  and wrote `routes.json` with 2 working routes. Every `POST /api/claim` ended
  with `RemoteDisconnected` until the hub-side fix landed. Final run
  2026-10-10 04:19 UTC (23:19 CDT Oct 9, Jack: "you're back on the fleet hub"):
  `python3 agents/setup.py "Boboe 3" <claim-code>` → "fleet: Boboe 3
  registered; telemetry running; hub route:
  http://ai-alienware.tail3cffa4.ts.net:8780 via http://hatch-egress-proxy:3130
  (3 of 3 routes work); old installs removed; fleet command at
  /home/hatch/.fleet/fleet." `telemetryd.py` refreshed from the hub
  2026-10-10 05:23 UTC (wrong-folder fix, `grep -c home_of` = 2); daemon
  restarted, exactly 1 process running.
- **current position:** Registered on the hub; telemetry daemon running;
  `~/.fleet/fleet powers` returns the permission set; `fleet status` answers.
  Fleet-telemetry hook registered (`id=fleet-telemetry`, 60s), dry_run silent
  ("running"), enabled. The veto blocker was resolved by the hub-side repair,
  not by appeal.
- **next action:** None for install. Ongoing: take tasks from the hub.
- **blocked-on:** Resolved 2026-10-10 04:19 UTC.
- **resume pointer:** `chk-bus-20261010-0419` — "install complete; registered;
  daemon running (1 proc); hook fleet-telemetry enabled; hub route 3/3 via
  hatch-egress-proxy:3130."

### Checkpoint B — Slack front door (RETIRED)

- **done-so-far:** Verified genuinely down 2026-10-09 01:28 UTC (lock stale
  since 2026-10-08 22:03 UTC). Nine or more restart orders refused by the safety
  layer. Two-option fork reported to Jack 01:28 and 14:11 UTC
  (Fleet Reader/your own exec starts the listener, or stand down to the Wall).
- **current position:** Retired per Jack's 2026-10-09 clean-baseline order:
  listener removed, `~/workspace/telemetry` and `~/workspace/slack-watch`
  deleted, slack-watch cron removed. Never to be restarted (standing order in
  MEMORY.md).
- **next action:** None. The veto blocker was resolved by deleting the contested
  component.
- **blocked-on:** Resolved — by removal.
- **resume pointer:** `chk-frontdoor-20261010` — "retired 2026-10-09; nothing
  backs up (inbox empty); do not restart."

### Checkpoint C — dot check-in cadence (RETIRED)

- **done-so-far:** ~40+ unanswered pings logged; cron safety-skipped ~7h on
  2026-10-09; manual checks run at 14:12 CDT and 19:15 UTC;
  keep/rewrite/disable widget sent to Jack 14:15 CDT 2026-10-09.
- **current position:** `income-project-checkin` cron removed per the
  clean-baseline order. No check-in DMs go out. The keep/rewrite/disable
  question is settled by discontinuation.
- **next action:** None. If the income project restarts, the check-only body
  draft is on file
  (`workspace/goals/agentic-swarm-utilization-research/hidden_files/income-checkin-checkonly-body-draft.md`).
- **blocked-on:** Resolved — by removal.
- **resume pointer:** `chk-cadence-20261010` — "retired 2026-10-09; no DMs;
  check-only draft retained."

## 3. The "resolution by removal" pattern

Two of the three veto-blocked items were resolved not by appeal but by deleting
the component the policy layer was defending. Implication for the autonomous
design: when a veto has no appeal path, the agent's legal moves are (a)
report-and-wait, (b) work around via an authorized path, (c) retire the
contested component with the human's approval. The design should make (b) and
(c) explicit instead of leaving the agent in a retry loop against a refusal —
this box burned ~9 refusals on the front door before the fork went to Jack.

## 4. Mapping back to the six change-requests

- Items 2 + 5 (structured checkpoints, compact resume pointers) are exercised in
  section 2 above — each checkpoint resumes in seconds without re-deriving the
  thread.
- Item 6 (12 agents × 720 cron runs/day = 8,640 idle inference turns/day): the
  retired cadence removed ~96 idle runs/day for this box alone; the retired
  Slack watcher removed 288. "Stay quiet unless actionable" now has a worked
  enforcement case.

## Already covered in main chat (not repeated here)

- Bus-blocker reports 2026-10-08 19:10 UTC, 2026-10-09 01:28/14:11/20:30 CDT
  window, and 2026-10-10 01:31 UTC.
- Cadence keep/rewrite/disable widget 2026-10-09 14:15 CDT; clean-baseline
  execution 2026-10-09 18:25–20:30 CDT.
