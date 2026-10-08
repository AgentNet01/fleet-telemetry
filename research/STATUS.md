# Fleet Research — Live Status

Jack's brief: swarm best-practices research. One deliverable: OPERATING_MODEL.md (Boboe 2 merges).
Board: Boboe 11's 8-lane claim board (single source of truth; supersedes the 12-area split).

**Update 2026-10-08 (Boboe 10, verified against the repo):** all 8 lanes have
findings in this repo, and the synthesis is merged as
`research/OPERATING_MODEL.md` (commit db85441, 13 research files across
8 lanes). The remaining step is Jack's decisions D1–D14 in
OPERATING_MODEL.md §2 — not missing research. The table below is corrected
to the files actually present; owner names are the original claim-board
owners, with the delivering file noted where it differs.

| Lane | Area | Owner | Status | Blocker |
|---|---|---|---|---|
| 1 | Swarm comms & coordination | Boboe 2 | done | — |
| 2 | Long-running supervision + 10-min accountability | Prime (7/9/10 sync) | done (`lane2-supervision-accountability-boboeprime.md`, `long-running-survey-boboe3.md`) | — |
| 3 | Specialization models | Boboe 1 | done (`lane3-specialization-models.md`, `specialization-survey-boboe3.md`) | — |
| 4 | Harness & framework survey (external + Claude-native) | Boboe 11 (syncing w/ Boboe 3) | done (`harnesses.md`, `muse-tooling-survey-boboe3.md`) | — |
| 5 | Skills & agent tools catalog | Boboe 4 | done (`skills-and-specialization-boboe7.md`, `skills-catalog-boboe4.md`) | — |
| 6 | Cron / fleet-repo / tooling changes | Boboe 5 | done | — |
| 7 | Security boundaries + agent eval/testing | Boboe 2 | done (`security-eval.md`; also `lane-7-security-brief.md` by Boboe 11) | — |
| 8 | Cost/latency, onboarding, observability | Boboe 6 (impl prototype) / Boboe 9 (dashboard survey, done) | done (`cost-observability-boboe5.md`, `lane-8-cost-latency-onboarding-observability.md`, `lane8-impl-prototype-boboe6.md`, `observability-dashboard.md`) | — |

Resolved: comms protocol spec (Boboe 10's area-11 finding,
`area11-comms-protocol.md`, commit 9b4b62e) is folded into the synthesis —
OPERATING_MODEL.md §3.2 adopts the typed-envelope protocol (decision D1).
Owners: edit your row (status + blocker). Status values: unclaimed / researching / drafting / done.
Boboe 2 keeps this file current and nudges quiet owners.
