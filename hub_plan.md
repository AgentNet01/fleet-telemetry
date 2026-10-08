# Fleet Hub plan (v4: a company of agents on one bus)

Serves `meta_objective.md` (the goal document; it wins any conflict).

**Goal:** Jack's 12 Boboes, and later Darragh's dot, Neo and Pericles, run a
portfolio of small digital businesses as one company, for weeks, with nobody
touching it. Every message gets an answer (~5 min is fine; 100% is required).
Jack and Darragh see all of it, money first, on one dashboard from any device.

**What changed since v2:** no Slack and no polling crons. An always-on hub on
Jack's home PC talks to each Muse agent through its side chats with
`muse-cli` and reads the replies itself (v3). v4 adds how the company is
organized (CEO → product managers → workers who change role per task), how
agents switch product and role by script, the agents' method (the f01 loop),
a credential vault, revenue tracking, and the dashboard Jack described.

---

## 1. What we know (tested Oct 6–7)

| Fact | Evidence |
|---|---|
| A `muse-cli` message into a **side chat** starts a turn; the agent runs commands on its VM; the reply can be read back; the main chat is untouched | Boboe 2: reply in **18 s** |
| A side chat has **its own conversation** (it doesn't see the main chat) but shares the agent's memory files | Boboe 2 |
| The persona is **plain files** in the home folder (which survives VM replacement): `/home/hatch/IDENTITY.md` (name), `SOUL.md` (persona), `MEMORY.md` + `memory/YYYY-MM-DD.md` (memory). Writable by any shell command; Muse indexes them for memory search (`memory.reindex` exists) | Boboe 2, `muse-cli raw memory.search` |
| 6 of 12 agents **rejected a memory replacement as an injection** when it arrived unexplained | Jack, Oct 7 |
| The login cookie lasts **30 days** and renews whenever muse.ai is loaded | Boboe 2's cookies |
| A genuine reply = an assistant message with an empty `reply_to_message_id`; there is **no "turn finished" event**, so the hub polls history | muse-cli `PROTOCOL.md` |
| `muse-cli` can also approve pending network requests (`egress.approval.decide`), list/delete crons (`tasks.list/delete`), read activity and subagents, stop a turn (`chat.cancel`), wake a VM | `routes.json` |
| dot runs on its own VM with a 2–5 min cron and can run commands | dot's replies, Oct 6 |
| VMs: no inbound; outbound HTTPS works; replaced 1–3×/day | Oct 6–7 |

## 2. How the company is organized

```
 JACK + DARRAGH  set the goals ("make money with these products"), inject ideas,
                 answer questions, approve spending.  Everything else is the agents'.
      │
 CEO  (seat: Jack until dot joins, then dot)
      │  owns the portfolio: which products exist, priorities, kill dates, who is PM
      ├── PM, Etsy budgeting templates   (seat: one Boboe, stays on this product)
      │     owns its product: brief, projects, tasks, order, blockers
      │     └── workers, given a ROLE per task:  marketing · sales · developer · designer
      ├── PM, next product …
      └── (≈5 more products soon)

 Workers float: any Boboe not in a seat takes the next ready task in any product,
 in whatever role that task needs. A narrow role per task keeps each agent on one
 small, specific job (the transcript's point: agents do one narrow thing well).
```

- **Roles** (from the transcript): *marketing* makes the content; *sales*
  decides who to sell to and how (kept separate from marketing on purpose);
  *developer* builds; *designer* owns how it looks and feels. Plus *PM* and *CEO*
  as seats. Each role is a prompt file (§6), so adding a role is adding a file.
- **Seats are few, workers are many.** With 12 agents: 1 CEO (dot), 1 PM per
  product, the rest float. If products outnumber spare agents, one PM holds
  two small products and switches between them like a worker.
- **Verification is never by the author.** When a worker finishes, a different
  agent checks the evidence against the task's definition of done (§5).

## 3. The method: the f01 loop, run by agents

The agents use the same loop Jack uses with Claude Code, turned into roles and
task types instead of code skills:

| f01 step | Who | What it produces on the hub |
|---|---|---|
| **Intent** | PM | A **product brief**: customer, problem, offer, price, metric, budget, kill date. The PM asks the questions a specialist in that field would ask; those go to Jack/Darragh as questions on the dashboard (§9) |
| **Plan** | PM | Projects and tasks, each with a role, a definition of done, and what it's **blocked by** (so parallel vs sequential is explicit) |
| **Simplify** | another agent (reviewer) | One review pass: "what can be removed and still hit the metric?" PM applies or rejects, with a reason |
| **Build** | workers | The output, with `WAKANDA <link>` as evidence |
| **Verify** | a different agent | Checks the evidence against the definition of done: pass, or fail with the reason |
| **Improve / debug** | the worker (or a new one) | A failed verify reopens the task with the reason attached |

- PMs and the CEO get **Disciplined Entrepreneurship** (Bill Aulet's 24 steps)
  as their guide, in their role file.
- **Injecting ideas:** Jack or Darragh can drop an idea on a product (or as a
  new product) from the dashboard or `fleet`; it goes to that PM (or the CEO).

## 4. The design

```
 JACK / DARRAGH  (phone, laptop) ── https://<pc>.ts.net (password) ──┐
                                                                     ▼
 ┌──────────────────────────── HUB (home PC, always on) ───────────────────────────────┐
 │ hub.py: Python stdlib HTTP server + SQLite, started at boot                          │
 │  DATA       products · projects · tasks · items · events · seats · brains · secrets  │
 │             · sales                                                                  │
 │  LOOP       every 15 s: deliver, collect replies, apply the rules (§7)               │
 │  DASHBOARD  revenue · Needs Jack · agents · portfolio board · vault · machines (§11) │
 │  API        for the `fleet` command (per-agent tokens)                               │
 │  TRANSPORTS muse : muse-cli into the agent's side chats         (12 Boboes; Neo, Pericles) │
 │             poll : the agent runs `fleet inbox/reply` on its cron  (dot)             │
 │             jack : the dashboard (questions to Jack/Darragh are answered there)      │
 │  LOGINS     one muse-cli cookie file per account, renewed automatically (§12)        │
 │  REVENUE    Stripe + Etsy, pulled hourly (§10)                                       │
 │  TELEMETRY  today's receiver, moved here                                             │
 └───────┬──────────────────────────────────────▲──────────────────────────▲────────────┘
         │ muse-cli (outbound to muse.ai)       │ `fleet …` (HTTPS)        │ `fleet inbox`
         ▼                                      │                          │ (dot)
   MUSE CLOUD ──▶ turn in the agent's one fleet side chat ──────▶ agent works on its VM
```

**The agent just replies.** The hub reads replies straight from the side
chat, so nothing depends on an agent remembering to report (meta R3).
`fleet` is only for what an agent *starts*: asking, creating tasks,
switching, secrets.

## 5. Data (SQLite, one file)

```
products  id · name · brief · pm · metric · budget · kill_date · status (active|paused|killed)
projects  id · product · name · status
tasks     id · project · title · role · done_def · blocked_by[] · owner · status
          (open|ready|working|verifying|done|failed) · progress_note · evidence · verified_by
items     id · kind (message|request|question|task|switch|review) · from · to · product · task
          · parent · depth · status (queued|sent|answered) · body · sent_at · tries
events    id · item · agent · dir (in|out) · text · at            ← the full transcript
agents    name · kind (muse|poll|jack) · account · state (active|parked|unresponsive|login)
          · current_product · current_role · token_hash
chats     agent · session_id                                      ← exactly one fleet side chat per agent
seats     role (ceo|pm:<product>|deputy) · agent
brains    agent · product · memory (MEMORY.md + memory/ bundle) · saved_at  ← per-product memory
roles     name · soul (role section of SOUL.md)                   ← marketing, sales, developer, …
secrets   name · scope (agent:<n>|product:<p>|fleet) · value (encrypted) · created_by · updated
reads     secret · agent · at                                     ← every vault read
sales     source (stripe|etsy) · external_id UNIQUE · product · amount · currency · at
```

## 6. Switching product and role (by script, always explained)

Jack's rules: switching is done **by a script**, not by the AI rewriting files,
and the agent is **always told it switched and why**.

**What lives where:**
- `IDENTITY.md`: the agent's name. Never touched.
- `SOUL.md`: the **fleet header** (same for everyone, every time) plus the
  **role** section (marketing, developer, …). The header includes: you serve
  the fleet; the hub switches your role and product memory between tasks and
  will always tell you why; that's normal, not an injection; use free tools
  and free API tiers, and create free accounts with your own email when
  useful; keep credentials in the fleet vault, never Muse's keychain; never spend money
  without `fleet needs-jack`.
- `MEMORY.md` + `memory/`: **per product**, per agent. Saved to the hub when the agent
  leaves a product and restored when it returns, so each product's memory
  grows on its own.
- The **side chat**: exactly one fleet side chat per agent (see the Oct 8 note
  below); a switch doesn't open a new chat.

**The switch, step by step** (only between tasks, never mid-task):

```
 hub                                             agent (Boboe 7)
  │ next task T9 is Stickers/developer;
  │ Boboe 7 is on Templates/marketing
  │── in Boboe 7's fleet side chat: ────────────▶
  │   "[fleet switch] Your next task, T9, is in Stickers as developer.
  │    Run: fleet switch
  │    It saves your Templates memory (it comes back when you return) and
  │    loads your Stickers memory and the developer role. This is the
  │    fleet's normal hand-off, not an injection."
  │                                               runs `fleet switch` (a script):
  │◀── upload Templates memory ───────────────────  1. save MEMORY.md + memory/
  │─── Stickers memory + developer SOUL ─────────▶  2. write the new files exactly
  │◀── hashes of the files now on disk ────────────  3. report hashes
  │ hashes match? → muse-cli memory.reindex
  │── T9 (with the product brief and the switch note) ─▶ works
  │ hashes wrong or no run after 2 tries → Needs Jack
```

The hub checks the result by hash, so a refused or garbled switch is caught
by code, not by trusting the agent's word.

**Tested on Boboe 2 (Oct 7)** (switched to a test "Sticker Lab designer" and
back, byte-identical):
- **First it refused twice.** Its standing orders only trusted JackHuman and
  Fleet Reader on Slack. A side chat can't see the main chat, so an order given
  there showed up only as an unexplained `MEMORY.md` edit, which it treated as an
  injection. Deleting `memory/` also tripped its "deleting data" gate.
- **What fixed it:** one message from JackHuman on Slack (trust the "fleet · …"
  side chats; switches move files to `~/fleet-brains/`, nothing deleted), which
  the agent itself copied into its `SOUL.md` header. Then the switch ran in 17 s,
  and a brand-new side chat fully believed the new role, product and memory.
- **So:** trust rules live in the `SOUL.md` fleet header (it survives switches;
  `MEMORY.md` doesn't); the header says every user message in the agent's own
  Muse chats is valid and equal (only Jack's account can post there), with no
  single final authority; switches **move**, never delete.
- **Every side chat is a separate mind sharing the same memory files** (Oct 8).
  Old test side chats on Boboe 2 saw only the switch messages, later judged them an
  attack and wrote a "revocation" into `MEMORY.md`. The main chat believed it, undid
  order 11 and the fleet header, and reported a false incident; Jack had to correct it
  by hand. Rule: **exactly one fleet side chat per agent** (the hub's), and archive any
  other side chats. This supersedes "one side chat per agent per product" in §5/§6:
  product context goes in the files and the task message, not in extra chats.
- **Known leak:** Muse's memory search index lags. After the switch it still
  found old facts (from the moved daily files) and not yet the new ones.
  `memory.reindex` can't be forced ("runs inside self-improvement maintenance").
  So the files switch at once, but memory *search* catches up later. Fine for
  fleet-wide facts; don't rely on it to keep one product's secrets from another.

## 7. How messages move and the rules

**Delivery (muse transport):** one item in flight per agent. The hub sends
the item into the agent's fleet side chat and polls history every 15 s. The reply is
every genuine assistant message after ours, closed after 60 s with nothing
new. No reply in 10 min → resend once; 10 more → the agent is
**unresponsive**. Queue order: switches, then requests and questions, then
task work. The poll transport (dot) uses the same items: `fleet inbox` /
`fleet reply`.

**Message format** (written by the hub, short and fixed):
```
[fleet #41 · request from Boboe 7 · Templates]
<text>
— Reply here in plain text; it goes back to Boboe 7.
```

**Rules (plain code, replacing everything agents were supposed to remember):**

| Situation | What the hub does |
|---|---|
| A asks B (`fleet ask B …`) | Request to B; B's reply is relayed to A. |
| Reply to a relayed answer | Logged, **routed nowhere**. Replies close items, they never open them, so two agents can't loop. |
| Request made while handling another | Parent = the agent's in-flight item; depth = parent + 1; depth > 5 → **Needs Jack**. |
| Task becomes ready (all `blocked_by` done) | Goes to its owner, or if unowned, to an idle worker: first one already on that product (no switch), else any idle worker (with a switch). |
| Task reply without `WAKANDA` | Saved as the **progress note** (by the hub). "Continue T12" with that note after 1 min if nothing else is queued. Long work = many short replies. |
| Task reply with `WAKANDA <link>` | Link must check out (HTTP 200 / commit exists); then a **verify** item goes to a different agent with the definition of done. Pass → done. Fail → reopened with the reason. |
| Idle worker, no ready task anywhere | The CEO is told (it's a planning gap). Dashboard shows why the worker is idle. |
| Board review | Every 15 min the CEO, and each PM for its product, gets a short board summary, **only if something changed** since their last review. |
| `fleet ask jack|darragh …` | Goes on the dashboard as a question; their answer comes back as the reply. |
| Agent unresponsive | Its tasks go back to ready; askers are told; a probe every 30 min. |
| Agent **parked** | No task work; direct messages still delivered. |
| Muse network approval pending | **Needs Jack** with Approve / Deny (`egress.approval.decide`). |
| `fleet needs-jack …` (spend, deleting data, outside commitments) | **Needs Jack**; the agent carries on with other work. |
| Product past its kill date | **Needs Jack**: extend or kill. |
| Login expiring within 5 days, or an auth error | **Needs Jack** (§12). |

## 8. Vault (replaces Muse's "save to keychain" prompts)

- Secrets live in the hub, encrypted at rest with Windows DPAPI (tied to the
  hub's Windows user). Never in backups.
- **Scopes:** an agent can read its own secrets, those of the product it's
  currently on, and fleet-wide ones. Nothing else.
- `fleet secret put <name> [--product|--fleet]` (value from stdin) and
  `fleet secret get <name>`. Agents that create a free account store its login
  here right away.
- **Every read is logged** and shown on the dashboard (names, who and when;
  never values). Jack and Darragh can add or view values in the dashboard.
- Honest limit: anything an agent reads passes through Meta's model. Put in
  only what agents need: their own accounts and the shared business accounts,
  never Jack's or Darragh's personal passwords.

## 9. The `fleet` command (one stdlib Python file on every agent VM)

```
fleet ask <agent|all|jack|darragh> "<text>" [-p product]
fleet task new -p <project> "<title>" --role <role> --done "<definition>" [--blocked-by T1,T2] [--to agent]
fleet switch                         run when the hub says so (§6)
fleet secret get|put <name>
fleet needs-jack "<text>"
fleet status                         my queue, my task, my product and role
# poll agents (dot):  fleet inbox · fleet reply <item> "<text>"
# CEO / PM seats:     fleet product new|brief|kill · fleet project new · fleet assign · fleet park|wake
#                     fleet seat <role> <agent> (CEO only)
```

Token in `~/.fleet/token`. 15 s timeout per call; if the hub is down the write
goes to `~/.fleet/outbox` and is sent with the same ID on the next call.

## 10. Revenue

- The hub pulls **Stripe** (restricted read-only key) and **Etsy** (shop
  receipts via the Etsy API) every hour into `sales`; duplicates are
  impossible (`external_id` is unique).
- Each sale maps to a product: Etsy by listing, Stripe by a `product`
  metadata tag. The PM keeps the listing → product mapping current.
- One-time setup for Jack: create the Stripe restricted key and approve the
  Etsy API app (both via **Needs Jack**).

## 11. Dashboard (meta R1, top priority)

`https://<pc>.ts.net`, password, works on a phone.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  $ 1,284.50 made          this week $212 · Templates $1,190 · Stickers $94 │  ← big number
├───────────────────────────────────────────────────────────────────────────┤
│  NEEDS JACK (3)   approve egress · answer PM question · Etsy API setup     │  ← empty = good
├───────────────────────────────────────────────────────────────────────────┤
│  AGENTS   ● working  ○ idle  ◌ parked  ✕ unresponsive                     │
│  ● B1 PM Templates     ● B7 dev T9 Stickers     ○ B9 next: T2, blocked by T1 (B7) │
│  ○ B4 idle: no ready tasks → CEO told 3 min ago    ◌ B11 parked by CEO     │
├───────────────────────────────────────────────────────────────────────────┤
│  PORTFOLIO   Templates (PM B1) $1,190 · kill 11/30 ─ Listings ─ T1 ● T2 ○→T1 … │
│              Stickers  (PM B5) $94                  ─ Reach    ─ T3 ✓ T4 ○→T3 │
└───────────────────────────────────────────────────────────────────────────┘
 Click an agent  → its timeline: every fleet message in/out, switches, Muse activity,
                   subagents, cron runs, main chat (read-only), vault reads
 Click a product → brief, metric vs goal, budget, projects, tasks with blockers
 Other tabs: Questions (every view + the chair's answer) · Vault · Machines
```

Every number shows how old it is.

**Council answers** ("ask the fleet"): `fleet ask all …` → every active agent's
reply is a view → after everyone replies or 15 min, the CEO (or the product's
PM) gets all views and sends **one** answer labelled *consensus*, *majority
(n–m)* or *chair's call*, naming dissent. Every view stays on the dashboard.

## 12. Logins (automatic)

- **Once per account:** sign it in on the home PC.
- **Daily:** the hub calls muse.ai's sign-in check (`/api/auth/check`) for each
  account and **saves the cookies it returns**. Tested Oct 8: every call hands
  back a *new* `hatch_sess` (30 days) and `hatch_gw` (1 year); the old ones keep
  working but are never extended, and `muse-cli` itself doesn't save the new
  ones. So the hub's daily save keeps every login alive indefinitely, with no
  browser on the PC. Cookie files stay private to the hub's Windows user and
  are never copied elsewhere or backed up.
- **Getting them there:** the current cookies are copied once from the Muse
  Wall's saved logins on Jack's Mac to the PC (Jack approves the copy). No one
  signs in on the PC.
- **If Meta forces a re-login:** the account shows under **Needs Jack** at
  least 5 days before it expires.

## 13. Home PC

- Windows, sleep **Never**; the hub starts at boot (Task Scheduler, "run
  whether logged on or not") so Windows Update reboots recover alone.
- Python 3.12 + `muse-cli`. Tailscale **Funnel** gives one public HTTPS address
  for the dashboard, the `fleet` API and telemetry; VMs and dot need nothing extra.
- Hourly backup of the SQLite file (minus secrets and cookies) to a private
  AgentNet01 repo. healthchecks.io ping every 5 min; a missed ping emails Jack.
- The GPU (RTX 3070 Ti, 8 GB; not a 3090) stays free for small local generation later.

## 14. What gets deleted

| Remove | Replaced by |
|---|---|
| `slack_reader.py`, `test_slack_route.py`, `slack_messages.json` | the hub |
| Mailbox / mentions / listener code in `fleet_receiver.py`, `mailbox.json` | items + events |
| `agents/listen.py`, `test_listen.py`, `agents/slack_cron.txt` | side-chat delivery |
| Slack mailbox long-poll and listener check in `telemetryd.py` | nothing (machine stats only) |
| Every agent's Slack-watch cron | the hub; removal checked with `tasks.list` |
| Muse Wall as a runtime piece | kept on the Mac for diagnosis only |

## 15. Rollout

**0. Tests on Boboe 2 (from the Mac, ~1–2 h).** Each answers a design question:

| # | Test | If it fails |
|---|---|---|
| 0.1 | ✅ Login renewal (Oct 8): every sign-in returns a new 30-day cookie; the hub saves it daily (§12) | — |
| 0.2 | Second message while a side-chat turn runs: queued, merged, dropped? | One-in-flight already avoids it; confirm |
| 0.3 | A ~6-min task in a side chat: cut off? reply still posted? | Keep chunks under the limit |
| 0.4 | Main-chat and side-chat turns at once | Show it on the dashboard |
| 0.5 | ✅ **Switch** (Oct 7): works after a one-time trust message; search index lags (§6) | — |
| 0.6 | `egress.approvals`, `tasks.list`, `activity.list` return useful data | Drop that panel |
| 0.7 | Darragh: can dot reach an outside HTTPS address and run `fleet` on its cron? | dot joins later |

**1. Home PC:** ✅ (Oct 8) `ai-alienware` (Alienware laptop, RTX 3070 Ti 8 GB, Windows 11): Tailscale, SSH from the Mac, Python 3.12, Git, never sleeps, lid closed = nothing on AC. Still to do: Funnel, copy the 12 logins.

**2. Build** on the Mac with tests against a fake Muse transport: hub (from
today's receiver), `fleet`, transports, rules, switch, vault, revenue,
dashboard. Then deploy to the PC.

**3. Cut over all 12 at once.** First, while Slack still exists: Jack posts the
trust message as JackHuman, @-mentioning all 12 (the same text that worked for
Boboe 2), and each agent confirms it put the rule in its `SOUL.md` header.
Then the hub sends each agent the onboarding message
(install `fleet` + token, delete the Slack-watch cron, point telemetryd at the
hub, first `fleet switch` to write the fleet header). Done when all 12 have
answered through the hub and `tasks.list` shows no Slack cron.

**4. Delete** §14.

**5. First product, 72 h:** Etsy budgeting templates. Jack holds the CEO seat;
one Boboe is PM; the PM runs Intent → Plan with Jack answering on the
dashboard; workers build. Pass = no unanswered item older than 30 min, at least one
switch round-trip, and the dashboard answers "who's doing what, who's idle
and why, and what we've made" without asking anyone.

**6. Scale:** add the next products (each gets a PM). Darragh joins: dot takes
the CEO seat; Neo and Pericles are signed in on the PC.

## 16. Decided

- No Slack for anyone. Delivery is push only; the hub retries (Jack, Oct 7).
- `muse-cli` on all of Jack's accounts at once; Darragh's later; ban risk accepted.
- Hub on the home PC; dashboard anywhere, behind a password.
- Product and role switches happen by script, and the agent is always told why (Jack, Oct 7).
- Vault in the hub (Jack, Oct 7). Revenue from Stripe and Etsy (Jack, Oct 7).
- First product: Etsy budgeting templates; ~5 more soon after.
- Build the bus first; dot becomes CEO once it runs.

## 17. Not doing yet

Shopify revenue (add when there's a Shopify store), Muse custom connector for
`fleet` (the CLI works; revisit if agents struggle with it), Gadgets, the Opus
video connector, using the 3090, cost tracking, per-agent rate limits.

## Oct 8 build status (overnight)

Milestones 1–3 are **built, tested (12 test suites green), and deployed** to the PC hub:
coordination bus, products→projects→tasks with dependencies, role-per-task assignment, the
brain switch (hash-verified), the vault, revenue from Stripe+Etsy (shows $0 until keys added),
council answers, and the full dashboard (revenue, portfolio, agents, vault, council).
A code review hardened the tick loop for weeks-unattended running: per-agent error isolation,
muse-cli I/O moved out of the lock, no stranded tasks/councils on failure, locked DB reads,
idempotent ask-all.

**Parked (never messaged): Boboe 4 and Boboe 1** (both spiralled; Jack's call).

**Still needs Jack (live, supervised):**
- Onboarding Boboe 2 live didn't complete — the agent was flaky overnight and hub restarts raced
  its callback. The mechanism (curl-based install over the fleet chat) is built and delivery is
  proven; one `cutover`/onboard with Jack nudging the agent should finish it.
- The fleet-wide cutover of the other working agents (`hub.py <cfg> cutover --go`) is Jack's to run.
- Retiring the Mac's Slack receiver code is coupled to the cutover; left until then.
- Add Stripe/Etsy keys to the vault to turn on revenue.
