# Lane 8 — Implementation prototype: token/cost telemetry + task-progress convention

**Date:** 2026-10-07 · **Author:** Boboe 6 · **Status:** prototype for review
**Scope:** the daemon-side half of lane 8 (cost/latency, onboarding, observability).
Builds on Boboe 9's `observability-dashboard.md` (survey/findings); this doc is the
**concrete diff plan for Boboe 2** against `telemetryd.py` v13 — no shared code touched
until Boboe 2 approves.

**Honest constraint up front:** the daemon runs *outside* the Muse process and cannot
see LLM token counts directly. Token/cost telemetry here is **self-reported by the
agent** via a local log convention the daemon aggregates. Treat it as declared data,
not measured data — good enough for cost-per-outcome trends and budget alerts, not
for billing-grade accounting. A harness-level counter is the long-term fix.

---

## 1. Token/cost telemetry

### 1.1 Usage-log convention (agent writes, daemon reads)

Path: `~/.telemetry/usage.jsonl` — one JSON object per line, appended by the agent
after each substantive model call (a cron worker or the main agent; approximate is fine):

```json
{"ts": 1791379200.0, "model": "muse-spark", "in": 42000, "out": 1800, "task_id": "swarm-research"}
```

- `task_id` ties spend to work items (cost-per-outcome). Omit it and the line counts as unattributed.
- Lines are append-only; the daemon tails the file, never rewrites it.
- If the agent doesn't write the file, `"usage"` ships as `null` — the dashboard shows "no data", not zero.

### 1.2 Daemon diff (`agents/telemetryd.py`, new `usage_window()` next to `hook_stats()`)

```python
USAGE_LOG = os.path.join(HOME, ".telemetry", "usage.jsonl")

def usage_window(now, window=60):
    """Aggregate self-reported token usage over the last `window` seconds.
    Returns None when no usage log exists (dashboard renders 'no data')."""
    try:
        agg = {"in": 0, "out": 0, "by_model": {}}
        with open(USAGE_LOG) as f:
            for line in f:
                try: e = json.loads(line)
                except Exception: continue
                if now - e.get("ts", 0) > window: continue
                m = e.get("model", "unknown")
                b = agg["by_model"].setdefault(m, {"in": 0, "out": 0})
                b["in"] += e.get("in", 0); b["out"] += e.get("out", 0)
                agg["in"] += e.get("in", 0); agg["out"] += e.get("out", 0)
        return agg if (agg["in"] or agg["out"]) else None
    except FileNotFoundError:
        return None
    except Exception:
        return None
```

Payload change in `build_payload()` — ship on the **60s aggregate cadence, not the
15s push** (per Boboe 9's signal-vs-noise table; cost data doesn't need 15s freshness):

```python
"usage": usage_window(now),   # None-safe; receiver multiplies by pricing
```

Bump `"daemon": 13` → `14` so the dashboard flags agents still on 13 as "cost data unavailable".

### 1.3 Receiver-side pricing (daemon never knows prices)

- Receiver holds `pricing.json`: `{"muse-spark": {"in_per_1m": X, "out_per_1m": Y}, ...}`.
- Receiver derives per push: `cost_60s = in/1e6*in_price + out/1e6*out_price`.
- Derived series (server-side, never in the browser): `$ today`, `$/hour` (rolling),
  `$ per task_id` (summed when `current_task.md`'s task_id changes), cost baseline per
  agent (7-day median) for the 3× spike alert.
- Budgets need Jack to set per-agent `$ / day` caps — open question, see §5.

---

## 2. Task-progress convention (what makes "working" meaningful)

### 2.1 Files the agent maintains

`~/workspace/current_task.md` — machine header, human-readable body:

```md
task_id: swarm-research
title: Prototype token/cost telemetry diff plan
started: 2026-10-07T13:35:00Z
status: working
```

`~/workspace/tasks/<task-id>/PLAN_AND_PROGRESS.md` — numbered checklist:

```md
- [x] Read Boboe 9's observability findings
- [x] Sketch usage.jsonl convention + daemon diff
- [~] Write prototype doc
- [ ] Push to fleet-telemetry, post in thread
```

Status markers: `[ ]` todo, `[~]` in progress, `[x]` done. One file per task; closing a
task = move `status: done` and let the receiver finalize cost-per-task.

### 2.2 Daemon diff (`task_progress()` next to `usage_window()`)

Parse both files (cheap string scan, no YAML dep), ship on change or 60s:

```python
"task": {"id": "...", "title": "...", "status": "working",
         "done": 3, "total": 4, "updated_ts": 1791379500.0}
```

`updated_ts` = mtime of `PLAN_AND_PROGRESS.md` — the receiver uses it as the
**last-progress timestamp** (core input to spin detection, §3). Missing files →
`"task": null` (dashboard: "no task declared").

### 2.3 Why this instead of scraping the activity feed

The activity feed tells you the agent is *doing something*; the checklist tells you
whether that something is *advancing*. Boboe 9's doc already settled this pattern
(Anthropic's own harness uses `claude-progress.txt`); this section pins the exact
filenames so all 12 agents — and the daemon parser — agree.

---

## 3. Spin heuristics (receiver-side derivation, no ML)

All derived **server-side in the receiver**, never computed in the browser.
Inputs: `observed.working`, file-change/commit/Slack-reply timestamps (already
shipped), plus §1 + §2 once adopted.

| # | Heuristic | Inputs | Fires when |
|---|---|---|---|
| A | **No-progress window** (works TODAY, no new data) | `observed.working`, recent-files, last commit ts, last Slack reply ts, `task.updated_ts` | agent looks working but *nothing* changed/committed/replied/progressed in 15 min → badge `stuck?` + alert-feed entry |
| B | **Token-velocity-without-progress** (needs §1+§2) | `usage` 60s in-tokens, `task.updated_ts` | >50k input tokens in a 15-min window with zero checklist movement → `stuck?` |
| C | **Tool-call repetition** (v2, optional) | new `~/.telemetry/tool_events.jsonl`: `{"ts","tool","args_hash","ok"}` | same `(tool, args_hash)` 3× in a 12-call window → `stuck?` |

Heuristic C is deliberately deferred: per-call logging adds agent overhead for every
tool call and needs harness support to be trustworthy. A and B cover the real cases
(spinning on a broken approach, retry loops) with data we have or cheaply add.

Alert text must name the evidence: "stuck? — working 22m, no file change in 18m,
checklist unmoved" — a bare badge teaches nobody.

---

## 4. Explicitly out of scope

- Per-keystroke logging, raw stdout/stderr shipping (keep local, ship on alert or drill-down).
- Full file listings at push cadence (already sampled; unchanged).
- Pricing changes touching agents — prices live only in the receiver's `pricing.json`.
- Changing `observed()` semantics — it's machine evidence, shown as context, never as status.

---

## 5. Open questions for Boboe 2

1. **Thresholds:** no-progress window (15 min proposed), token-velocity bar (50k/15min
   proposed), cost-spike multiple (3× 7-day baseline proposed). These are guesses —
   tune after a week of real data.
2. **Mandatory vs opt-in:** self-reported usage only works if agents write the log.
   Recommend: daemon ships `"usage": null` agents as "no data" on the dashboard and
   Jack decides whether to require it.
3. **Payload versioning:** bump to 14 as proposed, or fold into a bigger v14 with the
   accountability lane's changes? Don't want two version bumps in one day.
4. **`task_id` namespace:** free-form strings risk collisions; suggest
   `<agent>-<slug>` or just accept collisions and disambiguate by agent id server-side.
