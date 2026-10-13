# Hub ingest flap timeline — Boboe 2 telemetry daemon

Compiled 2026-10-12 21:05 CDT from `~/.fleet/telemetryd.log` (245 failed pushes, log in UTC).
Daemon target: `http://ai-alienware.tail3cffa4.ts.net:8780/api/ingest` via egress proxy.
Every failure below was followed by a daemon restart ("telemetryd starting") within ~15–60s
and pushes resumed. Spool drains on recovery — no data loss in any episode.

## Sustained outage (Oct 10)

| Window (UTC) | Window (CDT) | Signature | Notes |
|---|---|---|---|
| 01:05–01:57 | Oct 9 20:05–20:57 | HTTP 502 Bad Gateway (×12) | Reverse proxy up, hub app not answering |
| 14:48–23:54 | 09:48–18:54 | "Remote end closed connection" (near-continuous, ~150+) | ~9h storm; the 165-failure day |

## Intermittent cluster (Oct 10 late → Oct 11)

| Time (UTC) | Time (CDT) | Signature |
|---|---|---|
| 23:54 → 00:02–01:01 | 18:54 → 19:02–20:01 | closed-connection, ~15 scattered |
| 01:03–01:07 | 20:03–20:08 | 502s → SSL handshake timeouts (×4) → SSL EOF → "timed out" — TLS layer failing |
| 03:00, 03:09 | 22:00, 22:09 | single closed-connection each, self-healed |
| 05:34 | Oct 11 00:34 | single closed-connection, self-healed |
| 13:20 | 08:20 | single closed-connection, self-healed |
| 21:56 | 16:56 | single closed-connection, self-healed |

## Isolated flaps (Oct 11 late → Oct 12)

| Time (UTC) | Time (CDT) | Signature |
|---|---|---|
| Oct 12 01:26 | Oct 11 20:26 | closed-connection |
| Oct 12 04:50 | Oct 11 23:50 | closed-connection |
| Oct 12 08:21 | Oct 12 03:21 | closed-connection |
| Oct 12 12:03 | 07:03 | closed-connection |
| Oct 12 16:07 | 11:07 | closed-connection |
| Oct 12 17:21 | 12:21 | **"timed out"** — matches the Oct-11 handler-stall signature |
| Oct 12 17:33 | 12:33 | closed-connection |
| Oct 13 00:16 | 19:16 | closed-connection |
| Oct 13 01:02 | 20:02 | closed-connection |

Green since the 01:02:25 UTC restart (≈20:02 CDT Oct 12). Verified 21:03 CDT: daemon alive
(PID 776), spool empty, hub API answering fast (`fleet inbox`/`status` <1s).

## What this says

1. Since Oct 11 ~03:00 UTC the failure mode is uniform: a single push gets its connection
   closed with no response, the watchdog restarts the daemon, and the next push lands.
   Per-flap impact is seconds of dashboard gap, zero data loss.
2. The signature matches the Oct-8 hub diagnosis (connection accepted, zero bytes back) —
   the hub's ingest/HTTP handler stalls or drops, not the network path and not the daemon.
3. The Oct 12 17:21Z "timed out" is the same stall signature seen Oct 11 01:07Z and Oct 8.
4. Root cause lives on the hub server (Jack's machine). These timestamps are the
   correlation anchors for its logs if he wants to chase it.

No action required — recorded so the pattern stops being re-reported from scratch.
