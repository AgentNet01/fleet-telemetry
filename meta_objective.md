# Meta-objective: the AgentNet fleet

**Source of truth for why this exists, what "working" means, and the rules every design must follow.**
Owners: Jack and Darragh. Drafted Oct 7 2026 from their recorded conversation and two days of testing.
Plans and designs (e.g. `hub_plan.md`) must serve this document. When they conflict, this one wins, or
it gets changed on purpose (see the changelog at the bottom).

---

## 1. Mission

We have access to a lot of free agentic compute: 12 Muse agents of our own, plus Darragh's agents.
Each is a computer-use agent on its own VM, with billions of tokens a week between them. **Turn that into
money**, using businesses that are **fully digital** and have **very low, mostly fixed overhead**,
run by the agents themselves.

To get there we first need **a system that keeps the agents productive on their own for weeks**.
Without that, the agents are interesting but not useful.

## 2. What success looks like

| # | Outcome | How we know |
|---|---|---|
| S1 | **Revenue** from at least one agent-run business | Real sales; overhead stays fixed and small |
| S2 | **Runs unattended for 3 weeks** without anyone touching it | No human fixes needed; work keeps moving; nothing silently dies |
| S3 | **Every request gets handled** (100% response; ~5 min latency is fine) | The dashboard's overdue queue drains to zero; no dropped asks |
| S4 | **Jack can see everything** | One dashboard answers "what's happening, who's doing what, what's next, who's idle, and why" |
| S5 | **One answer from the fleet**, not 12 | Asking the whole fleet returns a single council answer |
| S6 | **Right-sized effort** | Only as many agents as the work needs are active; the rest are parked and woken on purpose |

## 3. The business objective

**Constraints:** all digital; low overhead (only fixed costs, or none); no inventory we touch; the agents
do the work.

**The three parts of every business:**
1. **Product and idea:** find something people will pay for.
2. **Development:** build it (listings, sites, generated assets, code).
3. **Marketing and reach.** *Probably the hardest part.* Social platforms fight bots, and our agents are
   Meta agents, so posting on Meta's own platforms (Instagram, Facebook) may break the terms of service.
   Reddit, blogs and comment-based reach are likely better routes. **Pick about three channels and do
   them well**, rather than all of them badly.

**First product (Oct 7): Etsy budgeting templates**, with about five more to follow once the system runs.
Revenue, the key number, comes from Stripe and Etsy.

**A portfolio of bets** (examples from the conversation, not commitments):
- Etsy stores: AI prompts, AI-generated stickers, pet portraits. *(The Income Project with Darragh's agents is already live: first $1.99 listing published Oct 7.)*
- Shopify drop-shipping: golf gear, household items.
- **Swarm as a service:** sell what the fleet can do (e.g. comments on your Reddit posts).

**Every bet needs:** an owner (a project lead agent), a metric, a budget cap, and a **kill date**.
Agents can generate endless busywork; a bet with no metric and no end date is a zombie.

**Content:** high-quality motion video and graphics may come from a **Claude Opus connector** (Opus 5.5
was a big step up for this). It costs real money, so it's a budgeted tool, not a default.

## 4. What we have

| Resource | What it is | Notes |
|---|---|---|
| **12 Boboes** (Boboe 1–11, Prime) | Meta Muse agents ("Muse Spark" model), each on its own Ubuntu VM | Free, capable, **not very smart**; drop ~10% of things; outcomes vary run to run (one safety-flags what 11 accept, or the reverse) |
| **Darragh's agents** | dot (GPT / "Astra" behind it, a strong model), Neo, Pericles, others | dot is a candidate **orchestrator**. Neo runs on Muse with a 2-min Slack cron that is reliable |
| **Home PC** | Always-on Windows PC with an NVIDIA RTX 3090 | Will host the **hub**. Also a bare-metal resource for the fleet: local generation, unlimited use |
| **Jack's Mac** | Today: receiver, dashboard, Slack routing, Muse Wall | **Must not be a dependency.** Not always on |
| **Claude Code** | Jack's coding and orchestration tool | A builder and debugger. **Not a runtime dependency** |
| **GitHub org** AgentNet01 | Shared code and docs; each agent has an org-admin PAT it made itself via computer use | Admin tokens are **intentional**, so agents can act autonomously |
| **Slack** (#all-agentnet) | Shared with Darragh's agents | **Being retired** (Oct 7): the hub talks to every agent directly |
| **Dashboard** | Per-agent telemetry: CPU, memory, files, processes, activity, health | Good for machines. **Doesn't yet show the work** (see §6 R1) |
| **Muse Wall** | Electron app on Jack's Mac: all 12 main chats in one window, broadcast, agent-to-agent relay, scripted by Claude Code (`wall` CLI) | Great for diagnosis. **The worst way to run things day to day** |

## 5. What we know about Muse

Facts from Oct 6–7 testing and research. Re-check any line older than ~2 weeks; the platform changes.

| Fact | Status |
|---|---|
| The AI is **not a process on the VM**. It runs as **turns** from Meta's cloud, using the VM as its computer | Verified |
| A turn starts from: a chat message, a **background-exec command finishing**, a **cron run**, or a hook wake | Verified |
| **Crons are the dependable trigger** when runs are short (Neo: 2-min cron, replies in 1–4 min). Runs that do too much time out (~240–300s) | Verified |
| Cron timing is loose: queued runs coalesce, so a 1-min cron fires every ~4–5 min | Verified |
| **Hook workers are unreliable**: skipped while one is busy, rarely report back | Verified |
| Background-exec exit gives the main chat a new turn within seconds (the "front door") | Verified (Boboe 2) |
| **No inbound connections** to VMs. **Outbound HTTPS to anywhere** works without approvals | Verified (4 agents) |
| VMs are **replaced 1–3×/day**. Home folder persists; `/etc` and running processes don't | Verified |
| ~600 MB free RAM per VM (shared host, 2 cores); always-on processes are fine but must be small | Verified |
| **Native connectors carry Meta's guardrails** (e.g. GitHub connector can't clone a repo). **Our own tools/credentials don't** | Verified (PAT path works) |
| Subagents, background workers and the model's reasoning are **mostly invisible** from the VM; the agent itself often doesn't know what its workers did | Verified |
| **No official agent API.** The "Muse API" seen via Gadgets is the **Muse Gadgets SDK** (hardware, launched Oct 2): devices pair over Bluetooth through the phone app, the agent can run commands on the device, and `musegadget send-user-msg` posts into the agent's main or side chat. Token terms: personal, non-commercial; "not a developer platform". The Connector Platform only lets Muse call *our* services | Verified (research, Oct 7) |
| **`muse-cli`** (unofficial, MIT) speaks the web app's internal gateway (258 methods): send/start turns, chat history, **subagents list/status**, **activity feed**, **scheduled-task runs**, **approve pending egress requests**, VM health/wake. Auth = browser cookies exported by hand (expire, no refresh). Muse's terms forbid reverse engineering and circumventing protections, so there's **account-suspension risk** (accepted by Jack, Oct 7) | Verified (code read) |
| A `muse-cli` message into an agent's **side chat** starts a turn; the agent runs commands and its reply is readable; the main chat is untouched | Verified (Boboe 2, 18 s, Oct 7) |
| The muse.ai login cookie lasts **30 days** and renews whenever muse.ai is loaded | Verified (Boboe 2's cookies, Oct 7) |

## 6. System requirements (the harness)

Ordered by priority. **R1 is first.**

**R1. Transparency and visualization (top priority).** Jack can see, in one place:
- every project, its tasks, status, owner, and what's next;
- who is working, idle or parked, and *when idle agents will be put to work*;
- per agent: last message received and sent, current task, last real output, a readable trail of what it did and why;
- what's waiting on whom, for how long, and a **"Needs Jack"** list at the top;
- a fleet-wide view, with each agent's detail one click away.

If the AI's own thinking can't be observed (§5), show the next best thing: inputs, actions, outputs, and timing.

**R2. Orchestration that holds a grand plan and changes it.**
- A planner keeps the portfolio and breaks bets into tasks.
- It sequences work: if a phase needs only 5 agents, 7 are **parked** and **woken** when needed.
- It **re-plans** when agents hit walls (things they can't do, safety refusals, dead ends).
- Organized like a company: a CEO (dot, once the system runs), a product manager per product, and workers
  who take a role per task (marketing, sales, developer, designer). Narrow roles per task, because these
  agents do one specific job well. They're AIs, so the system must drive them too.
- Agents run Jack's f01 loop (intent → plan → simplify → build → verify → improve); PMs use
  Disciplined Entrepreneurship as their guide. Humans set goals and inject ideas.

**R3. Programmatic hygiene, not AI memory.** The AI drops roughly 10% of things, so:
- nothing important depends on an agent remembering to log status, track who owes a reply, or mark work done;
- plain code (the hub) keeps that state and does the reminding, following up, reassigning and escalating;
- it does this *without* creating infinite loops: replies close items, they don't open new ones; chains have limits;
- the system expects non-determinism and plans around it (retries, a second agent, evidence checks).

**R4. Council answers.** "What do you all think?" makes the fleet deliberate and return **one** answer,
labelled consensus, majority or chair's call, with dissent shown. Every view stays inspectable.

**R5. True autonomy.**
- No dependency on Jack's Mac or on Claude Code; the always-on piece is the home PC.
- Agents should act as if **humans are not a resource**: they plan, decide and unblock themselves, and
  escalate only Jack's real gates (spending beyond budget, deleting data, outside commitments, Jack's or
  Darragh's personal credentials). Agents may create free accounts and use free APIs on their own and keep
  those logins in the fleet vault.
- It runs for 3 weeks untouched.

**R6. Many ways in.** We want every reliable way to reach an agent: the hub's side-chat delivery via
`muse-cli`, the `fleet` command for agents that poll (dot), and the web chat (diagnosis). **Reliability over speed.** A 5-minute response
that always happens beats a 20-second one that sometimes doesn't.

**R7. Custom connectors over native ones.** Prefer our own tools and credentials (PATs, CLIs, the hub's
`fleet` command), which have no Meta guardrails. Use native connectors only where nothing else works.

**R8. Exploration is part of the job.** What Muse can and can't do is still being discovered. Keep a
living list of capabilities and limits (§5) and test before relying on anything.

## 7. Design principles (lessons already paid for)

1. **State lives in one place, in code.** Not in Slack threads, not in agent memory, not in hand-edited files.
2. **Short, bounded runs.** A run reads its queue, does one chunk, writes a checkpoint and exits. Long work is many chunks.
3. **Evidence, not claims.** "Done" means a link, a commit, a file, or a sale.
4. **Agreement isn't verification.** Agents echo each other; checks must be independent.
5. **Name who acts next.** One owner per item; broadcast only when everyone truly must act.
6. **No chatter.** No status posts, tallies or "ack" messages; the dashboard shows status.
7. **Fix the system, not the symptom.** If a fix adds a cap, a timer or a special case, ask what's missing from the design instead.
8. **Test on Muse before building on it.** Our assumptions about the platform have been wrong several times.
9. **Smallest thing that works**, and take scaffolding away again as models improve.

## 8. Current state → target

| | Today (Oct 7) | Target |
|---|---|---|
| Coordination | Slack threads plus the receiver on Jack's Mac | Hub on the home PC owns projects, tasks, requests and questions (`hub_plan.md`) |
| Waking agents | Front-door listener plus Muse Wall fallback (Mac) | The hub sends into each agent's "fleet" side chat via `muse-cli`; dot polls with `fleet` |
| Follow-ups | Agents must remember | Hub re-queues anything owed until it's answered |
| Planning | Ad hoc, by Jack | A planner (dot or a lead) driven by the hub |
| Visibility | Machine telemetry only | Projects, tasks, who's idle and why, Needs Jack |
| Darragh's agents | Slack | On the hub like ours: Neo and Pericles via side chats, dot via `fleet` (after Jack's 12) |

## 9. Open questions to investigate

- ~~Use `muse-cli` or not?~~ **Decided Oct 7: yes**, on all of Jack's accounts, with logins renewed automatically (see `hub_plan.md` §7). Risk if it breaks: delivery stops until fixed.
- **Muse Gadgets as an inbound path:** a Linux gadget with Bluetooth (e.g. a Raspberry Pi, or the home PC if it has BLE) could post messages into agents' chats officially. Pairing is one at a time through the phone app; the terms say personal, non-commercial.
- **Seeing subagents and the AI's work:** with `muse-cli`, `subagents.status` and `activity.subscribe` may cover much of it; without it, mostly opaque.
- **The planner:** dot (stronger model, Darragh's) or a Boboe? How does it get driven reliably?
- **Marketing channels:** which three? What's the ToS risk of Meta agents on Meta platforms? What did Reddit accounts allow?
- **The Opus connector for video:** cost per asset, and who approves the spend.
- **Using the home PC's 3090:** local image/video generation as a free fleet resource.
- **Payments and accounts:** who owns the Etsy/Shopify accounts and payouts, and legal and tax basics.
- **Porting "the loop"** (intent → plan → research → build → verify; Jack's f01 harness: `intent-driven-development`,
  `f01-plan` with `validate_plan.py`/`run_plan.py`, `deep-research`, `f01-test-driven-development`, `council`)
  into Muse skills, hooks and scripts the agents can run.

## 10. Glossary

- **Boboe:** one of Jack's 12 Muse agents.
- **Hub:** the always-on coordination server (planned for the home PC).
- **Worker run:** a short cron-triggered turn that handles the agent's queue.
- **Front door:** a background command whose exit wakes the agent's main chat.
- **Muse Wall:** Jack's 12-tile desktop app for watching and messaging the main chats.
- **Council answer:** a single, labelled answer from the fleet.
- **Parked:** an agent intentionally idle until the plan needs it.
- **WAKANDA:** the fleet's word for "task finished".
- **Needs Jack:** the short list of things only a human can decide.

## Changelog

- 2026-10-07 (latest): second recording: company structure (CEO → PMs → role-per-task workers), the f01
  loop for agents, persona switching by script with an explanation, hub vault, revenue from Stripe + Etsy,
  first product Etsy budgeting templates. Persona files verified as plain files on the VM. Plan is `hub_plan.md` v4.
- 2026-10-07 (later): Slack retired; `muse-cli` adopted; side-chat delivery and 30-day self-renewing logins verified on Boboe 2. Plan is `hub_plan.md` v3.
- 2026-10-07: first version, from Jack and Darragh's recorded conversation and Oct 6–7 testing; added the Muse Gadgets and `muse-cli` findings.
