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
#              prompt=<the PROMPT line below, verbatim>
# Copy this file to that script path first (see README "Slack hook"). When
# PROMPT changes, re-register the hook with it (hooks.update or remove + add).
#
# PROMPT: New Slack messages for you are in the payload (who, channel, ts, thread_ts, text, why you got each, and reply_required). A thread message comes with the thread so far (original post + recent replies). RULE: every message with reply_required=true is someone -- a person or another agent -- addressing you by name and expecting an answer. Always answer it in Slack, in its thread (thread_ts, or ts if thread_ts is empty), even if only to say you saw it and what you will do. Never stay silent on one, and never treat it as already handled unless you can see your own reply in that thread. why="no reply yet" means you were named a few minutes ago and have not answered. reply_required=false (an agent answering you, your threads, @channel): reply or act only if it needs you. To keep agents from looping: name another agent only when you need something from them, and don't answer an answer just to acknowledge it.
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
    m2 = {k: m.get(k) for k in ("why", "channel", "channel_id", "ts", "thread_ts", "user_name",
                                "text", "thread", "thread_skipped")}
    # the receiver decides (being named needs an answer; its loop guards say when not)
    m2["reply_required"] = m.get("reply_required", m.get("why") in ("mentioned", "no reply yet") and not m.get("from_agent"))
    msgs.append(m2)
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
# a dry run (hooks.dry_run sets HATCH_HOOK_DRY_RUN=1) wakes no one, so it
# must leave the messages in the inbox for the next real run
if [ "${HATCH_HOOK_DRY_RUN-0}" != "1" ]; then
  mv "${files[@]}" "$DONE"/
  # keep a week of handled messages
  find "$DONE" -name '*.json' -mtime +7 -delete 2>/dev/null
fi
wake "${#files[@]} new Slack message(s) for you" "$payload"
