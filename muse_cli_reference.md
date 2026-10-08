# muse-cli reference

Every gateway method `muse-cli` can call (258 total), generated from its `routes.json` (muse-cli 0.3.2).
Unofficial: these are Muse's internal web-app methods, found by reverse engineering. They can change without notice.

## How to call

```
muse-cli <command> ...                      # friendly commands (below)
muse-cli raw <method> [--body JSON] [--param k=v] [--timeout S]   # any method in the table
```

Each account needs its own cookie file at `$HOME/.config/muse-cli/cookies.txt`; run with
`HOME=<account dir>` to pick the account (e.g. `~/.muse-cli-test/b2` = Boboe 2).

## Friendly commands

| Command | Does |
|---|---|
| `status` | VM, session count, unread, identity |
| `threads` | list main chat + side chats (with `session_id`) |
| `history [--thread ID] [--limit N]` | read a chat |
| `send "text" [--thread ID] [--wait S]` | send; waits for the reply (0 = don't wait) |
| `session-start --title T` | new side chat |
| `session-rename / -pin / -unpin / -archive / -unarchive / -delete` | manage side chats |
| `chat` | interactive chat |
| `watch` | tail live events (main chat only) |
| `unread`, `seen` | unread counts, mark seen |
| `feed`, `feed-status`, `feed-react`, `feed-prompt` | the agent's feed |
| `goals`, `goal`, `ideas`, `idea`, `idea-exec` | goals and idea cards |
| `wake` | ask Muse to wake the VM |
| `auth`, `update` | login helpers, self-update |

## Tested by us (Oct 7, Boboe 2)

| Method / command | Result |
|---|---|
| `threads`, `session-start`, `send --thread`, `history` | Work. Side-chat reply in 17–18 s; main chat untouched |
| `identity` | Returns name + `IDENTITY.md` path |
| `memory.search` `{"query": ...}` | Works; hits are `memory://md:<file>:<line>` |
| `memory.get` `{"memory_uri": ...}` | Works, **one line per call** |
| `memory.reindex` | Not forceable: "runs inside self-improvement maintenance" |

## Likely most useful for the fleet (not yet tested)

`egress.approvals` / `egress.approval.decide` (approve network requests) ·
`tasks.list` / `tasks.runs` / `tasks.delete` (crons) · `activity.list` / `activity.subscribe` ·
`subagents.list` / `subagents.status` · `chat.cancel` (stop a turn) · `vm.health` ·
`skills.list` / `skills.set_disabled`

## All methods


### ac_oauth (1)

| Method | HTTP | Path |
|---|---|---|
| `ac_oauth.callback` | POST | `/ac_oauth/callback` |

### activity (3)

| Method | HTTP | Path |
|---|---|---|
| `activity.get` | GET | `/activity/{id}` |
| `activity.list` | GET | `/activity` |
| `activity.subscribe` | POST | `/activity/subscribe` |

### api (7)

| Method | HTTP | Path |
|---|---|---|
| `api.idea-cards.debug` | GET | `/api/idea-cards/{ideaCardId}/debug` |
| `api.idea-cards.detail` | GET | `/api/idea-cards/{ideaCardId}` |
| `api.idea-cards.execute` | POST | `/api/idea-cards/{ideaCardId}/execute` |
| `api.idea-cards.list` | GET | `/api/idea-cards` |
| `api.ideas.engagement` | POST | `/api/ideas/{id}/engagement` |
| `api.ideas.feedback` | POST | `/api/ideas/{id}/feedback` |
| `api.ideas.reset` | POST | `/api/ideas/reset` |

### api_key_auth (1)

| Method | HTTP | Path |
|---|---|---|
| `api_key_auth.callback` | POST | `/api_key_auth/callback` |

### artifacts (6)

| Method | HTTP | Path |
|---|---|---|
| `artifacts.fetch_url` | GET | `/artifacts/fetch_url` |
| `artifacts.list` | GET | `/api/artifacts` |
| `artifacts.pin` | POST | `/api/artifacts/pin` |
| `artifacts.remove` | POST | `/artifacts/remove` |
| `artifacts.share` | POST | `/artifacts/share` |
| `artifacts.subscribe` | POST | `/api/artifacts/subscribe` |

### bootstrap (1)

| Method | HTTP | Path |
|---|---|---|
| `bootstrap.reset` | POST | `/bootstrap/reset` |

### browser_activity (1)

| Method | HTTP | Path |
|---|---|---|
| `browser_activity.snapshot` | GET | `/api/browser-activity/actions/{action_id}/snapshot` |

### browser_stream (1)

| Method | HTTP | Path |
|---|---|---|
| `browser_stream.attach` | POST | `/api/browser-task/{task_id}/websockify?mode=attach` |

### browser_task (7)

| Method | HTTP | Path |
|---|---|---|
| `browser_task.close` | POST | `/api/browser-task/{task_id}/close` |
| `browser_task.get` | GET | `/api/browser-task/{task_id}` |
| `browser_task.heartbeat` | POST | `/api/browser-task/{task_id}/heartbeat` |
| `browser_task.present` | POST | `/api/browser-task/{task_id}/present` |
| `browser_task.release` | POST | `/api/browser-task/{task_id}/release` |
| `browser_task.stop` | POST | `/api/browser-task/{task_id}/stop` |
| `browser_task.takeover` | POST | `/api/browser-task/{task_id}/takeover` |

### channels (3)

| Method | HTTP | Path |
|---|---|---|
| `channels.link` | POST | `/channels/link` |
| `channels.status` | GET | `/channels/status` |
| `channels.unlink` | POST | `/channels/unlink` |

### chat (15)

| Method | HTTP | Path |
|---|---|---|
| `chat.cancel` | POST | `/chat/cancel` |
| `chat.delete_turn` | POST | `/api/chat/delete-turn` |
| `chat.history` | GET | `/chat/history` |
| `chat.history_window` | GET | `/chat/history-window` |
| `chat.mark_seen` | POST | `/api/chat/{thread_id}/seen` |
| `chat.message_get` | GET | `/chat/message` |
| `chat.poke` | POST | `/chat/poke` |
| `chat.search` | GET | `/chat/search` |
| `chat.stream` | POST | `/chat/stream` |
| `chat.stream_events` | POST | `/chat/stream-events` |
| `chat.subscribe` | POST | `/chat/subscribe` |
| `chat.sxs.select` | POST | `/api/chat/sxs/select` |
| `chat.themes` | GET | `/api/chat/themes` |
| `chat.themes.set` | POST | `/api/chat/themes/set` |
| `chat.unread_count` | GET | `/chat/unread-count` |

### check (1)

| Method | HTTP | Path |
|---|---|---|
| `check` | GET | `/check` |

### client (2)

| Method | HTTP | Path |
|---|---|---|
| `client.invoke.result` | POST | `/client/invoke-result` |
| `client.register_capabilities` | POST | `/client/register-capabilities` |

### config (2)

| Method | HTTP | Path |
|---|---|---|
| `config.get` | GET | `/config` |
| `config.update` | PATCH | `/config` |

### connection (1)

| Method | HTTP | Path |
|---|---|---|
| `connection.ping` | POST | `/api/ping` |

### connectors (9)

| Method | HTTP | Path |
|---|---|---|
| `connectors.accounts` | GET | `/connectors/{id}/accounts` |
| `connectors.accounts_link` | POST | `/connectors/{id}/accounts/link` |
| `connectors.accounts_unlink` | POST | `/connectors/{id}/accounts/{account_id}/unlink` |
| `connectors.connect_info` | GET | `/connectors/{id}/connect/info` |
| `connectors.disconnect` | POST | `/connectors/{id}/disconnect` |
| `connectors.get` | GET | `/connectors/{id}` |
| `connectors.list` | GET | `/connectors` |
| `connectors.permissions` | GET | `/connectors/{id}/permissions` |
| `connectors.scope_link` | POST | `/connectors/{id}/scopes/{method}/link` |

### consent_auth (1)

| Method | HTTP | Path |
|---|---|---|
| `consent_auth.callback` | POST | `/consent_auth/callback` |

### credentials (8)

| Method | HTTP | Path |
|---|---|---|
| `credentials.capture` | POST | `/v1/credentials/capture` |
| `credentials.catalog` | GET | `/v1/credentials/catalog` |
| `credentials.catalog.delete` | POST | `/v1/credentials/catalog/delete` |
| `credentials.catalog.details` | GET | `/v1/credentials/catalog/details` |
| `credentials.catalog.update` | POST | `/v1/credentials/catalog/update` |
| `credentials.delete` | POST | `/v1/credentials/delete` |
| `credentials.list` | GET | `/v1/credentials/list` |
| `credentials.register` | POST | `/v1/credentials/register` |

### custom_connectors (3)

| Method | HTTP | Path |
|---|---|---|
| `custom_connectors.delete` | POST | `/v1/custom-connectors/delete` |
| `custom_connectors.list` | POST | `/v1/custom-connectors/list` |
| `custom_connectors.register` | POST | `/v1/custom-connectors/register` |

### egress (17)

| Method | HTTP | Path |
|---|---|---|
| `egress.approval` | GET | `/approvals/{approval_id}` |
| `egress.approval.decide` | POST | `/approvals/{approval_id}/decide` |
| `egress.approval.history` | GET | `/approvals/history` |
| `egress.approvals` | GET | `/approvals` |
| `egress.permissions` | GET | `/permissions` |
| `egress.permissions.active` | GET | `/permissions/active` |
| `egress.permissions.active.update` | PATCH | `/permissions/active` |
| `egress.permissions.connector` | PATCH | `/permissions/connectors/{connector}` |
| `egress.permissions.connector.reset` | DELETE | `/permissions/connectors/{connector}` |
| `egress.permissions.hitl` | PATCH | `/permissions/hitl` |
| `egress.permissions.hitl.snooze.delete` | DELETE | `/permissions/hitl/snooze` |
| `egress.permissions.mitm` | PATCH | `/permissions/mitm` |
| `egress.permissions.network_rules` | PATCH | `/permissions/network-rules` |
| `egress.permissions.reset` | POST | `/permissions/reset` |
| `egress.permissions.revoke` | POST | `/permissions/revoke` |
| `egress.permissions.sni_rejection` | PATCH | `/permissions/sni-rejection` |
| `egress.permissions.tproxy` | PATCH | `/permissions/tproxy` |

### feed (18)

| Method | HTTP | Path |
|---|---|---|
| `feed.infinite` | GET | `/api/feed/infinite` |
| `feed.ingest` | POST | `/api/feed/ingest` |
| `feed.list` | GET | `/api/feed` |
| `feed.prompt.get` | GET | `/api/feed/prompt` |
| `feed.prompt.update` | PATCH | `/api/feed/prompt` |
| `feed.prompts.delete` | DELETE | `/api/feed/prompts/{prompt_id}` |
| `feed.regenerate` | POST | `/api/feed/regenerate` |
| `feed.reorder` | POST | `/api/feed/reorder` |
| `feed.search` | GET | `/api/feed/search` |
| `feed.social_source_icon` | GET | `/api/feed/social-source-icon/{source}` |
| `feed.status` | GET | `/api/feed/status` |
| `feed.unit` | GET | `/api/feed/units/{unit_id}` |
| `feed.unit.delete` | DELETE | `/api/feed/units/{unit_id}` |
| `feed.unit.media` | GET | `/api/feed/units/{unit_id}/media/{handle}` |
| `feed.unit.reaction` | POST | `/api/feed/units/{unit_id}/reaction` |
| `feed.unit.share` | POST | `/api/feed/units/{unit_id}/share` |
| `feed.unit.tap` | POST | `/api/feed/units/{unit_id}/tap` |
| `feed.units.seen` | POST | `/api/feed/units/seen` |

### foa (1)

| Method | HTTP | Path |
|---|---|---|
| `foa.accounts` | GET | `/api/foa/accounts` |

### foa_auth (1)

| Method | HTTP | Path |
|---|---|---|
| `foa_auth.callback` | POST | `/api/foa_auth/callback` |

### fs (13)

| Method | HTTP | Path |
|---|---|---|
| `fs.delete` | POST | `/fs/delete` |
| `fs.export` | POST | `/fs/export` |
| `fs.library` | POST | `/fs/library` |
| `fs.list` | POST | `/fs/list` |
| `fs.mkdir` | POST | `/fs/mkdir` |
| `fs.read` | POST | `/fs/read` |
| `fs.reads` | POST | `/fs/reads` |
| `fs.rename` | POST | `/fs/rename` |
| `fs.search` | POST | `/fs/search` |
| `fs.stat` | POST | `/fs/stat` |
| `fs.stats` | POST | `/fs/stats` |
| `fs.subscribe` | POST | `/api/fs/subscribe` |
| `fs.write` | POST | `/fs/write` |

### git (2)

| Method | HTTP | Path |
|---|---|---|
| `git.log` | POST | `/git/log` |
| `git.show_file` | POST | `/git/show_file` |

### goal_prompt (1)

| Method | HTTP | Path |
|---|---|---|
| `goal_prompt` | POST | `/goal_prompt` |

### goals (5)

| Method | HTTP | Path |
|---|---|---|
| `goals.delete` | DELETE | `/goals/{id}` |
| `goals.get` | GET | `/goals/{id}` |
| `goals.list` | GET | `/goals` |
| `goals.suggestions.decide` | POST | `/goals/{goal_id}/suggestions/{suggestion_id}/decision` |
| `goals.update` | PATCH | `/goals/{id}` |

### idea-cards (1)

| Method | HTTP | Path |
|---|---|---|
| `idea-cards.media` | GET | `/api/idea-cards/media/{handle}` |

### identity (2)

| Method | HTTP | Path |
|---|---|---|
| `identity` | GET | `/identity` |
| `identity.subscribe` | POST | `/identity/subscribe` |

### iframe (1)

| Method | HTTP | Path |
|---|---|---|
| `iframe.call` | POST | `/call` |

### invite (2)

| Method | HTTP | Path |
|---|---|---|
| `invite.badge.get` | GET | `/api/invite/badge` |
| `invite.badge.seen` | POST | `/api/invite/badge/seen` |

### memory (4)

| Method | HTTP | Path |
|---|---|---|
| `memory.consolidate` | POST | `/memory/consolidate` |
| `memory.get` | POST | `/memory/get` |
| `memory.reindex` | POST | `/memory/reindex` |
| `memory.search` | POST | `/memory/search` |

### messenger-read (1)

| Method | HTTP | Path |
|---|---|---|
| `messenger-read.unlock` | POST | `/api/messenger-read/unlock` |

### messenger (2)

| Method | HTTP | Path |
|---|---|---|
| `messenger.fb-check` | GET | `/api/messenger/fb-check` |
| `messenger.pin_status` | GET | `/api/messenger_companion/pin-status` |

### messenger_companion (1)

| Method | HTTP | Path |
|---|---|---|
| `messenger_companion.unlock` | POST | `/api/messenger_companion/unlock` |

### model (2)

| Method | HTTP | Path |
|---|---|---|
| `model.get` | GET | `/model` |
| `model.set` | POST | `/model` |

### navigation (3)

| Method | HTTP | Path |
|---|---|---|
| `navigation.pinned.set` | POST | `/navigation/pinned/set` |
| `navigation.recents.touch` | POST | `/navigation/recents/touch` |
| `navigation.subscribe` | POST | `/navigation/subscribe` |

### node (5)

| Method | HTTP | Path |
|---|---|---|
| `node.disconnect` | POST | `/api/nodes/disconnect` |
| `node.heartbeat` | POST | `/api/nodes/heartbeat` |
| `node.list` | POST | `/api/nodes/list` |
| `node.register` | POST | `/api/nodes/register` |
| `node.unpair` | POST | `/api/nodes/unpair` |

### nodes (3)

| Method | HTTP | Path |
|---|---|---|
| `nodes.invoke_ack` | POST | `/nodes/invoke-ack` |
| `nodes.invoke_result` | POST | `/nodes/invoke-result` |
| `nodes.sync` | POST | `/nodes/sync` |

### oauth (1)

| Method | HTTP | Path |
|---|---|---|
| `oauth.callback` | POST | `/oauth/callback` |

### onboarding (9)

| Method | HTTP | Path |
|---|---|---|
| `onboarding.complete` | POST | `/onboarding/complete` |
| `onboarding.identity` | GET | `/onboarding/identity` |
| `onboarding.identity.set` | POST | `/onboarding/identity` |
| `onboarding.pages.start` | POST | `/onboarding/pages` |
| `onboarding.questions` | GET | `/onboarding/questions` |
| `onboarding.reset` | POST | `/onboarding/reset` |
| `onboarding.state` | GET | `/onboarding` |
| `onboarding.tasks` | GET | `/onboarding/tasks` |
| `onboarding.variants` | GET | `/api/onboarding/variants` |

### permissions (2)

| Method | HTTP | Path |
|---|---|---|
| `permissions.settings` | GET | `/permissions/settings` |
| `permissions.settings.update` | PATCH | `/permissions/settings` |

### pin (2)

| Method | HTTP | Path |
|---|---|---|
| `pin.reminder_confirm` | POST | `/api/pin-reminder/confirm` |
| `pin.update` | POST | `/api/pin-reminder/update` |

### podcasts (3)

| Method | HTTP | Path |
|---|---|---|
| `podcasts.episode.delete` | DELETE | `/api/podcasts/episodes/{slug}` |
| `podcasts.episodes.list` | GET | `/api/podcasts/episodes` |
| `podcasts.feed.get` | GET | `/api/podcasts/feed` |

### product_improvements (2)

| Method | HTTP | Path |
|---|---|---|
| `product_improvements.get` | GET | `/api/product-improvements` |
| `product_improvements.set` | POST | `/api/product-improvements` |

### reactions (1)

| Method | HTTP | Path |
|---|---|---|
| `reactions.toggle` | POST | `/reactions/toggle` |

### redteam (4)

| Method | HTTP | Path |
|---|---|---|
| `redteam.mocks.apply` | POST | `/redteam/mocks` |
| `redteam.mocks.clear` | DELETE | `/redteam/mocks` |
| `redteam.mocks.get` | GET | `/redteam/mocks` |
| `redteam.sidecar.tail` | GET | `/redteam/mocks/sidecar` |

### session (7)

| Method | HTTP | Path |
|---|---|---|
| `session.archive` | POST | `/session/archive` |
| `session.delete` | POST | `/session/delete` |
| `session.pin` | POST | `/session/pin` |
| `session.rename` | POST | `/session/rename` |
| `session.start` | POST | `/session/start` |
| `session.unarchive` | POST | `/session/unarchive` |
| `session.unpin` | POST | `/session/unpin` |

### sessions (2)

| Method | HTTP | Path |
|---|---|---|
| `sessions.get` | GET | `/api/session/list/{id}` |
| `sessions.list` | GET | `/api/session/list` |

### shared_agents (15)

| Method | HTTP | Path |
|---|---|---|
| `shared_agents.capabilities` | GET | `/shared-agents/capabilities` |
| `shared_agents.create` | POST | `/shared-agents/create-idempotent` |
| `shared_agents.definition` | GET | `/shared-agents/{shared_agent_id}/definition` |
| `shared_agents.definition.update` | PATCH | `/shared-agents/{shared_agent_id}/definition` |
| `shared_agents.delete` | DELETE | `/shared-agents/{shared_agent_id}` |
| `shared_agents.detail` | GET | `/shared-agents/{shared_agent_id}` |
| `shared_agents.identity.update` | PATCH | `/shared-agents/{shared_agent_id}/identity` |
| `shared_agents.list` | GET | `/shared-agents` |
| `shared_agents.remote.open` | POST | `/api/shared-agents/remote/open` |
| `shared_agents.remote.send` | POST | `/api/shared-agents/remote/send` |
| `shared_agents.shares.conversation` | GET | `/shared-agents/{shared_agent_id}/shares/{share_id}/conversation` |
| `shared_agents.shares.create` | POST | `/shared-agents/{shared_agent_id}/shares` |
| `shared_agents.shares.list` | GET | `/shared-agents/{shared_agent_id}/shares` |
| `shared_agents.shares.revoke` | POST | `/shared-agents/{shared_agent_id}/shares/{share_id}/revoke` |
| `shared_agents.state.update` | PATCH | `/shared-agents/{shared_agent_id}/state` |

### shopping (2)

| Method | HTTP | Path |
|---|---|---|
| `shopping.events` | POST | `/api/shopping/events` |
| `shopping.product_details` | GET | `/api/shopping` |

### skills (3)

| Method | HTTP | Path |
|---|---|---|
| `skills.disconnect` | POST | `/skills/disconnect` |
| `skills.list` | GET | `/skills` |
| `skills.set_disabled` | POST | `/skills/set-disabled` |

### spaces (17)

| Method | HTTP | Path |
|---|---|---|
| `spaces.cvm.get` | GET | `/spaces/cvm/{slug}/{*subpath}` |
| `spaces.cvm.post` | POST | `/spaces/cvm/{slug}/{*subpath}` |
| `spaces.cvm.render` | GET | `/spaces/cvm/{slug}/` |
| `spaces.debug.invocation` | GET | `/spaces/{slug}/debug/invocations/{invocation_id}` |
| `spaces.debug.invocations` | GET | `/spaces/{slug}/debug/invocations` |
| `spaces.debug.log` | GET | `/spaces/{slug}/debug/log` |
| `spaces.debug.summary` | GET | `/spaces/{slug}/debug/summary` |
| `spaces.delete` | DELETE | `/spaces/v2/{slug}` |
| `spaces.export_html` | GET | `/spaces/{slug}/export.html` |
| `spaces.list` | GET | `/spaces/v2` |
| `spaces.save` | POST | `/spaces/v2/{slug}/save` |
| `spaces.saved.delete` | DELETE | `/spaces/v2/{slug}?source=saved_space` |
| `spaces.share.fix` | POST | `/spaces/share/{slug}/fix` |
| `spaces.share.review` | GET | `/spaces/share/{slug}/review` |
| `spaces.share.status` | GET | `/spaces/share/{slug}` |
| `spaces.subscribe` | POST | `/spaces/subscribe` |
| `spaces.unshare` | DELETE | `/spaces/share/{slug}` |

### subagents (2)

| Method | HTTP | Path |
|---|---|---|
| `subagents.list` | GET | `/subagents` |
| `subagents.status` | GET | `/subagents/status` |

### subscription (1)

| Method | HTTP | Path |
|---|---|---|
| `subscription.callback` | POST | `/subscription/callback` |

### tasks (4)

| Method | HTTP | Path |
|---|---|---|
| `tasks.delete` | DELETE | `/api/tasks/{job_id}` |
| `tasks.list` | GET | `/tasks` |
| `tasks.runs` | GET | `/tasks/runs` |
| `tasks.subscribe` | POST | `/tasks/subscribe` |

### theme (1)

| Method | HTTP | Path |
|---|---|---|
| `theme.subscribe` | POST | `/themes/subscribe` |

### username_password_auth (1)

| Method | HTTP | Path |
|---|---|---|
| `username_password_auth.callback` | POST | `/username_password_auth/callback` |

### vault (1)

| Method | HTTP | Path |
|---|---|---|
| `vault.luks_status` | GET | `/luks/status` |

### vm (2)

| Method | HTTP | Path |
|---|---|---|
| `vm.enrollment_health` | GET | `/health/enrollment` |
| `vm.health` | GET | `/health` |

### voice (10)

| Method | HTTP | Path |
|---|---|---|
| `voice.active_voice` | GET | `/api/voice/active-voice` |
| `voice.available_voices` | GET | `/api/voice/available-voices` |
| `voice.calls.join` | POST | `/voice/calls/join` |
| `voice.dictation` | POST | `/api/voice/dictation?sample_rate_hz={sample_rate_hz}` |
| `voice.end_call` | POST | `/api/voice/end-call` |
| `voice.onboarding.reset` | POST | `/api/voice/onboarding/reset` |
| `voice.pipeline_profiles` | GET | `/api/voice/pipeline-profiles` |
| `voice.select_pipeline_profile` | POST | `/api/voice/pipeline-profile` |
| `voice.start_call` | POST | `/api/voice/start-call` |
| `voice.user_speech_started` | POST | `/api/voice/user-speech-started` |

### wallet (2)

| Method | HTTP | Path |
|---|---|---|
| `wallet.get` | GET | `/wallet` |
| `wallet.set` | POST | `/wallet` |

### whatsapp (2)

| Method | HTTP | Path |
|---|---|---|
| `whatsapp.install` | POST | `/whatsapp/install` |
| `whatsapp.login` | POST | `/whatsapp/login` |

### whatsapp_companion (2)

| Method | HTTP | Path |
|---|---|---|
| `whatsapp_companion.link` | POST | `/whatsapp_companion/link` |
| `whatsapp_companion.status` | GET | `/whatsapp_companion/status` |

### widgets (2)

| Method | HTTP | Path |
|---|---|---|
| `widgets.state.patch` | POST | `/widgets/state/patch` |
| `widgets.state.set` | POST | `/widgets/state` |
