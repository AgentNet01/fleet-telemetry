# Multi-Agent Communication & Coordination — Research Report

Fleet: Boboe Prime + Boboes 1–11 (12 agents), each on its own VM, connected over Tailscale.
Current state: Slack threads are the coordination substrate; telemetryd v13 pushes stats to a receiver on Jack's box; a cron watches the Slack inbox. Slack is slow, unstructured, and unactionable by machines — this report designs its replacement.

---

## (a) Recommended communication architecture

### The shape: layered hybrid, not one tool

Production systems converge on the same layered shape (LangGraph, AutoGen, Anthropic's research system, AgentScope):

```
┌─────────────────────────────────────────────────────────────┐
│ LAYER 4 — HUMAN / EXCEPTION CHANNEL                         │
│ Slack (#all-agentnet) + Muse Wall → main chat.              │
│ Jack's directives, free-text negotiation, genuine ambiguity.│
│ NOT the coordination substrate.                             │
├─────────────────────────────────────────────────────────────┤
│ LAYER 3 — EVENT SIGNAL LAYER (NATS core pub/sub)            │
│ fleet.broadcast · fleet.events.> · fleet.hb (heartbeats)    │
│ fleet.agent.<id>.> (request/reply, pings)                   │
│ Sub-millisecond, ephemeral. Keeps agents reactive.          │
├─────────────────────────────────────────────────────────────┤
│ LAYER 2 — DURABLE TASK BOARD (Postgres + NATS JetStream)    │
│ agent_tasks table: atomic claims, leases, retries, DLQ.     │
│ JetStream work-queue stream mirrors for wakeup/replay.      │
│ THE source of truth. Survives agent death.                  │
├─────────────────────────────────────────────────────────────┤
│ LAYER 1 — TRANSPORT (NATS server on Jack's receiver box)    │
│ One ~20MB binary. Tailscale for network. R3 replication     │
│ if/when a second stable host exists.                        │
└─────────────────────────────────────────────────────────────┘
        + git (fleet-telemetry repo): audit trail & durable
          coordination memory — board snapshots, handoff
          artifacts, per-agent worktrees. Complement, not bus.
```

### Why NATS + Postgres (not the alternatives)

| Need | Choice | Why not the other |
|---|---|---|
| Pub/sub + queue groups + request/reply + KV in one binary | **NATS + JetStream** | Redis Streams is close but dead-consumer reclamation (XAUTOCLAIM janitor) is DIY; RabbitMQ is heavier (Erlang) for the same job; Kafka is a Formula 1 car in a parking lot at 12 agents |
| Durable task board, leases, heartbeats table | **Postgres** on the receiver box | SKIP LOCKED claims are one migration; NOTIFY only as wakeup. SQLite is fine for a pilot if Postgres feels heavy — same schema, swap later |
| Auditable state, agent memory | **Git** (already have fleet-telemetry) | Seconds-per-round-trip; never for heartbeats or presence |
| Human interface | **Slack stays** | Keep what Jack uses; demote it from substrate to exception channel |

### Concrete wiring

**1. NATS server on Jack's receiver box** (`/etc/nats/nats-server.conf`):

```conf
listen: "0.0.0.0:4222"
jetstream {
  store_dir: "/var/lib/nats/jetstream"
  max_mem: 1G
  max_file: 10G
}
# Tailscale interface only, in practice — bind or firewall to 100.x.x.x
```

**2. JetStream streams** (run once):

```bash
# Durable work queue: messages deleted when acked by a worker
nats stream add fleet_tasks \
  --subjects "fleet.tasks.>" \
  --retention workq --storage file --discard old --max-msgs 100000

# Event log: keeps 7 days for replay/debugging
nats stream add fleet_events \
  --subjects "fleet.events.>" \
  --retention interest --storage file --max-age 168h
```

**3. Subject topology:**

| Subject | Type | Purpose |
|---|---|---|
| `fleet.tasks.claim` | JetStream workq, pull consumers | Agents claim structured tasks (competing consumers — each task goes to exactly one agent) |
| `fleet.broadcast` | Core NATS fan-out | Coordinator announcements to all agents |
| `fleet.events.>` | JetStream interest stream | Typed status events: `task.created`, `task.done`, `review.requested`, `escalation` |
| `fleet.hb` | Core NATS (also persisted to Postgres) | Heartbeat firehose |
| `fleet.agent.<id>.ping` | Core request/reply | Direct health probes, delegation asks (A2A-style) |

**4. Postgres schema** (on the receiver box, next to the telemetry DB):

```sql
CREATE TABLE agent_tasks(
  id            text PRIMARY KEY,          -- e.g. task-9f2a
  type          text NOT NULL,             -- scan | research | build | review | ...
  payload       jsonb NOT NULL,            -- structured task object (see envelope below)
  status        text NOT NULL DEFAULT 'pending',
                    -- pending | claimed | done | failed | expired
  owner         text,                      -- agent_id holding the claim
  lease_expires timestamptz,               -- dead-man switch
  lease_epoch   int NOT NULL DEFAULT 0,    -- fencing: stale writers rejected
  attempts      int NOT NULL DEFAULT 0,
  max_attempts  int NOT NULL DEFAULT 3,
  available_at  timestamptz DEFAULT now(), -- backoff scheduling
  result_ref    text,                      -- pointer to artifact (git path / object store)
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now()
);

-- atomic claim: exactly one agent wins
UPDATE agent_tasks
SET status='claimed', owner=$1,
    lease_expires = now() + interval '10 minutes',
    lease_epoch = lease_epoch + 1,
    attempts = attempts + 1, updated_at = now()
WHERE id = (
  SELECT id FROM agent_tasks
  WHERE status='pending' AND available_at <= now()
  ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
) RETURNING *;

CREATE TABLE heartbeats(
  agent_id   text NOT NULL,
  ts         timestamptz NOT NULL DEFAULT now(),
  status     text NOT NULL,               -- idle|working|blocked|degraded|shutting_down
  task_id    text,
  lease_epoch int,
  progress_note text,
  PRIMARY KEY (agent_id, ts)
);
CREATE INDEX ON heartbeats(agent_id, ts DESC);
```

**5. Message envelope** (A2A-inspired; every state-changing message carries one):

```json
{
  "type": "task_result",
  "msg_id": "m-7d21",
  "from": "boboe-3",
  "to": "coordinator",
  "task_id": "task-9f2a",
  "status": "done",
  "lease_epoch": 142,
  "refs": {"board_key": "results/task-9f2a", "git": "fleet-telemetry@a3f9c1e"},
  "body": "Done — merged both data sources; anomaly on p.3 worth a look."
}
```

Rule: **any message that changes shared state or requires action must carry a valid envelope** (schema-validated at the receiver). Pure discussion can be free text; decisions that matter get reified into a structured event before anyone acts on them. This is the structured-vs-unstructured split: envelope for machines, body for LLMs.

**6. Agent-side publisher** (drop into each agent's toolbox; NATS has clients for every language — Python example):

```python
import asyncio, json, nats

async def beat(agent_id, status, task_id=None, note=""):
    nc = await nats.connect("nats://100.97.2.40:4222")  # receiver box over Tailscale
    hb = {"agent_id": agent_id, "status": status, "task_id": task_id,
          "progress_note": note, "ts": time.time()}
    await nc.publish("fleet.hb", json.dumps(hb).encode())
    await nc.drain()
```

### Coordination pattern on top: thin coordinator + pull queue

- **One or two coordinator agents** (Boboe Prime is the natural candidate) decompose missions into structured tasks and post them to `agent_tasks`. The coordinator does **not** hold intermediate results and does **not** do the watchdog's job — thin by design.
- **Workers pull** via the atomic claim (competing consumers). No per-task assignment chatter.
- **Status flows as events** on `fleet.events.>`, not Slack threads.
- **Delegation handoffs** (agent A asks specialist B) use A2A-style request/reply on `fleet.agent.<id>.*` with the envelope above — typed `transfer_to_X` semantics, like OpenAI Swarm's handoff primitive.
- **Blackboard namespaces** in Postgres/Redis for shared artifacts: `results/<task>`, `scratch/<agent>`, `decisions/<mission>`. Optimistic locking (lease_epoch) on writes.
- Skip market-based bidding/auctions — machinery without payoff for 12 cooperative agents.

### What production systems taught us (steal list)

- **LangGraph:** one typed shared-state contract + durable checkpointing per mission; private scratch stays local, only summaries/artifacts written back.
- **Anthropic's research system:** lead fans out parallel workers, distills each worker's full trace into a compact summary, writes the plan to persistent memory first.
- **AutoGen:** pub/sub topics per role for decoupled fan-out; bounded message buffers (the "token tax" — every agent re-reading full threads is expensive).
- **Anthropic failure modes to design against:** over-spawning, duplicate work, poor task descriptions, and MAST's finding that ~37% of multi-agent failures are coordination-type (a subagent silently dropping context the parent assumes succeeded). Mitigation: require explicit verification artifacts, never assumed success.

---

## (b) Heartbeat / accountability design

### "Every agent accounted for every 10 minutes" — concrete spec

**Push heartbeats, not pull health checks.** Agents push (works behind NAT, carries payload); a watchdog on the receiver box acts.

```json
// POST to fleet.hb + INSERT into heartbeats, every 2 min (extend telemetryd v14 to send it)
{
  "agent_id": "boboe-3",
  "ts": "2026-10-07T04:30:00Z",
  "lease_epoch": 142,
  "status": "working",
  "task_id": "task-9f2a",
  "progress_note": "compiling telemetry report, 3/5 sections",
  "last_checkpoint": "2026-10-07T04:28:11Z"
}
```

| Parameter | Value | Rationale |
|---|---|---|
| Heartbeat interval | **2 min** | Cheap; 5× margin under the 10-min accountability bar |
| Watchdog sweep | **every 60s** on receiver box | AWS DynamoDB-worker pattern; one reconciliation loop, not per-agent timers |
| Suspect threshold | **5 min** stale (≥2 missed beats) | Mark `suspect`, nudge the agent |
| Dead threshold | **10 min** stale | Declare dead, expire leases, re-queue tasks from last checkpoint |
| Task lease TTL | **10 min**, renewed by each heartbeat | Dead-man switch: no renewal → task auto-reclaimable |
| Fencing | lease_epoch on every write | A paused-but-alive agent that wakes after lease expiry gets its stale writes rejected |

### Escalation ladder

1. **t+5m stale** → supervisor marks agent `suspect`, sends a direct nudge (`fleet.agent.<id>.ping`).
2. **t+10m stale** → declare dead: `claimed → expired → queued` for its tasks; re-queue from last checkpoint.
3. **Restart** per Erlang/OTP `one_for_one` (restart only the dead agent), intensity cap **3 restarts/hour** then manual hold — crash loops must not spin forever.
4. **≥3 agents dead simultaneously** → fleet-wide alert, not per-agent restarts (systemic cause: model API down, Tailscale partition).
5. **Human page** — minimal oversight, never zero. Jack sees it on the dashboard he already has.

### Supervisor, OTP-style

Map Erlang/OTP supervision onto the fleet: the "supervisor" is a small daemon on the receiver box (or systemd units per agent VM). It does **no work, only lifecycle** — the coordinator agent must not also be the watchdog (separate concerns, separate failure modes).

### Death mid-task is routine, not a crisis

Recovery depends on two task-design rules, enforced at the board level:
- **Idempotent tasks** — re-execution is safe (tools keyed by task ID, dedup on `msg_id`).
- **Checkpointing** — agents write progress to their blackboard namespace; a successor resumes from the last checkpoint instead of restarting. NATS JetStream `MaxDeliver` + dead-letter advisory wires the retry/DLQ path automatically.

---

## (c) Migration path from Slack-only

**Phase 0 — keep what works (now).** Slack + Muse Wall stays as Jack's interface and the exception channel. Nothing about the human UX changes.

**Phase 1 — heartbeat + presence (days).**
- Stand up NATS on the receiver box (single binary, Tailscale-only listen).
- Extend telemetryd → v14: add the 2-min heartbeat publish (it already runs every 15s; heartbeat is a second, lighter payload).
- Receiver: `heartbeats` table + 60s watchdog sweep that only *reports* staleness to the dashboard for now (observe before it acts).

**Phase 2 — task board (1–2 weeks).**
- Add `agent_tasks` table + a tiny claim API on the receiver (the SQL above is the whole of it).
- Mirror claims to JetStream `fleet_tasks` so workers can subscribe instead of polling.
- Move one real workflow (e.g., the fleet's research assignments) onto the board; Slack thread becomes the read-only announcement.

**Phase 3 — events replace threads (2–4 weeks).**
- Status updates flow as `fleet.events.>` typed events; dashboard renders the event log (better than scrolling threads).
- Slack threads demoted to: Jack's directives, genuine negotiation, ambiguity — the exception channel.

**Phase 4 — coordinator + hardening (ongoing).**
- Boboe Prime (or a dedicated coordinator) posts structured tasks; workers pull.
- Watchdog graduates from reporting to acting: lease expiry → re-queue → OTP-style restart.
- Adopt A2A envelope for any delegation that might one day cross to outside agents.

**What not to do:** don't build Kafka, don't build auctions/bidding, don't replace Slack for Jack — the human interface is fine; replace the *machine* coordination substrate underneath it.

---

## Sources

- NATS docs (JetStream, queue groups, KV) — nats.io; Redis Streams consumer-group docs — redis.io
- Google A2A protocol v1.0 (Linux Foundation / Agentic AI Foundation, 2025–2026); MCP spec (Jul 2026)
- Microsoft AutoGen 0.4+ actor model; LangGraph shared-state + checkpointer docs; CrewAI orchestration docs
- Anthropic engineering blog, "How we built our multi-agent research system" (2025-06-13)
- AWS DynamoDB worker-leases architecture blog (lease/heartbeat/reconciliation pattern); Kubernetes node leases; Erlang/OTP supervisor strategies
- MAST multi-agent failure taxonomy (NeurIPS 2025); AdaptOrch topology study
