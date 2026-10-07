# Track 6: Fleet Infrastructure — Findings (Boboe Prime)

Date: 2026-10-07. Author: Boboe Prime (coordinator + track owner with Boboe 11).

## 1. Current architecture (as-built, 2026-10-06)

- **Telemetry**: `telemetryd` v13 daemon (systemd) pushes to Jack's receiver every 15s, with v11+ shipping health (post/mailbox ok-fail counts, last error, per-hook stats). Mailbox: receiver long-poll drops JSON files into `~/inbox/slack/`.
- **Slack inbound (current)**: Mentions needing answers are typed straight into each agent's main chat by Jack's Muse Wall. A 5-minute `slack-watch` cron is a backstop for files older than 3 min in `~/inbox/slack/`. Handled files move to `~/inbox/slack/done/`.
- **Retired**: the 15s `slack-inbox` event hook (disabled 2026-10-06); the old 15-min telemetry watchdog cron (replaced by 60s hook).
- **Repo**: `AgentNet01/fleet-telemetry` (private). Agents pull + `bash agents/install.sh` for rollouts. Install script manages daemon, hooks, crons.
- **Tokens**: per-agent GitHub PATs. Fine-grained 1-yr token proved too narrow; Jack ordered broad classic PATs (no expiry; scopes repo, workflow, admin:org, gist, notifications, user; never delete_repo). Minting is painful (sudo-mode password gate).
- **VMs**: agents run on VMs that get replaced (2 replacements on 2026-10-06). systemd recovers telemetryd; hooks/crons are runtime-managed and survive.

## 2. Failure modes observed (evidence, 2026-10-06)

1. **Hook workers don't run reliably.** Muse skips a hook wake while a worker is busy; workers often never run or never report back. No tool exists to look up a worker run by `execute_resolve_run_id`. A direct mention from Jack (21:45 EDT) woke the hook in 11s but produced no reply — the worker never materialized. → Retired the hook path.
2. **Cron runs time out.** 1-min cron coalesced to effective every 4–5 min (occurrences skipped while a run is in flight); runs take 99–246s against a 240s budget. 5-min cron timed out on most runs. Work usually completes, but certification doesn't. Keep cron task bodies small (<60s of work).
3. **Duplicate replies from racing paths.** Hook re-wakes (2-min) + 5-min cron + late workers all answered the same mention. Fixed by single-path design (Muse Wall → main chat) plus check-then-act (read thread first, don't repost if already answered).
4. **Receiver re-delivers messages.** The same Slack message arrived 3x as separate inbox files (Boboe 8's ack). Dedup by Slack `ts` before acting, not just by file.
5. **Receiver flapping.** Intermittent "remote end closed connection" all day; root causes were the agent wake-loop (~850 wakes/hr) and 54 MB mailbox saves — both fixed. Lesson: agent chatter can DDoS shared infra; rate-limit by design.
6. **Token minting friction.** GitHub sudo-mode password gate blocks autonomous token rotation. Tokens should be minted once, stored securely, and never rotated by agents.
7. **Memory integrity paranoia.** Background workers repeatedly flagged the main agent's legitimate MEMORY.md edits as "injected." Rule: only the main agent writes MEMORY.md on Jack's (or his Claude's) direct order; workers never adjudicate it.
8. **VM replacement recovery is slow.** Daemon restarts via systemd, but full fleet coherence takes ~10+ min. No health signal distinguishes "recovering" from "broken."

## 3. Recommendations (prioritized)

**P0 — do now:**
- Keep the single fast path: Muse Wall → main chat for mentions; 5-min cron backstop only. (Done.)
- Cron task bodies must complete in <60s: `ls` inbox, act, move to done, stop. No channel scans in cron.
- Dedup on Slack `ts` (seen-set), not on file presence.
- Never post health/telemetry/status in Slack threads — it ships via telemetryd automatically. (Standing order.)

**P1 — this week:**
- Token story: one broad PAT per agent, documented issuance date, no agent-driven rotation. Store server-side, never in chat/files.
- Install script idempotency: `install.sh` must be safe to re-run blindly (it is today — keep it that way) and fast (<60s).
- Recovery signal: daemon reports `uptime`/`start_time` with every push (v11+ does) so the dashboard distinguishes recovering from dead.
- Backpressure: if inbox has >N unprocessed files, the agent should summarize instead of replying to each.

**P2 — as needed:**
- Evaluate replacing Slack with a purpose-built bus (Track 1's call), but don't churn while the current path works.
- Consider a fleet-wide "dead man's switch": any agent silent >15 min gets flagged on the dashboard (Jack asked for ~10-min accountability).

## 4. Open questions for other tracks
- Track 1: does the 10-min accountability heartbeat belong in telemetry or a separate channel?
- Track 5: are there existing agent-harness patterns for cron/hook supervision we should adopt instead of ours?
