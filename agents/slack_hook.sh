#!/bin/bash
# slack_hook.sh -- Muse hook script: wakes the agent when Slack messages for it
# arrive. Jack's receiver reads Slack and picks the messages meant for this
# agent (it's named, @channel/@here, or it's a thread the agent posted in);
# telemetryd drops each one into ~/inbox/slack/. No messages -> silent, which
# costs no AI turn. Hook scripts have no Slack credentials; they don't need any.
#
# Register once (agent tool call), then dry_run, then enable:
#   hooks.add  id=slack-inbox  interval=15s
#              script=~/hooks/scripts/slack-inbox.sh
#              prompt="New Slack messages for you are in the payload (who, channel,
#                      thread_ts, text, and why you got each: mentioned / your
#                      thread / everyone). A thread message comes with the thread
#                      so far (original post + recent replies; thread_skipped says
#                      how many older replies were left out). Act or reply as
#                      your standing instructions say. If nothing needs you, do
#                      nothing."
# Copy this file to that script path first (see README "Slack hook").
source "$HATCH_HOOK_RUNTIME"

INBOX=/home/hatch/inbox/slack
DONE=$INBOX/done
shopt -s nullglob
files=("$INBOX"/*.json)
if [ ${#files[@]} -eq 0 ]; then
  silent "no new Slack messages"; exit 0
fi

mkdir -p "$DONE"
payload="$(python3 - "${files[@]}" <<'PY'
import json, sys
msgs = []
for p in sys.argv[1:]:
    try:
        with open(p) as f:
            m = json.load(f)
    except (OSError, ValueError):
        continue
    msgs.append({k: m.get(k) for k in ("why", "channel", "channel_id", "ts", "thread_ts", "user_name",
                                       "text", "thread", "thread_skipped")})
msgs.sort(key=lambda m: float(m["ts"] or 0))
last_in_thread = {m["thread_ts"]: id(m) for m in msgs if m.get("thread_ts")}
for m in msgs:
    m["text"] = (m["text"] or "")[:1500]
    if not m.get("thread") or last_in_thread.get(m.get("thread_ts")) != id(m):
        m.pop("thread", None); m.pop("thread_skipped", None)   # thread context once, on its newest message
print(json.dumps({"count": len(msgs), "messages": msgs[-25:],
                  "note": "older ones in ~/inbox/slack/done" if len(msgs) > 25 else ""}))
PY
)"
mv "${files[@]}" "$DONE"/
# keep a week of handled messages
find "$DONE" -name '*.json' -mtime +7 -delete 2>/dev/null
wake "${#files[@]} new Slack message(s) for you" "$payload"
