# Floor 2: the sports desk

## Goal
The dashboard has an elevator. Floor 1 is the Etsy company as it is today. Floor 2 is the sports desk: six Muse agents,
one per sport, plus a hub line watcher that never sleeps. Every 5 minutes (±90 s) the hub reads each sport's DraftKings
lines from ESPN's public scoreboard feed and keeps the history. It wakes a desk only when its board changes (new
openers, a real move), plus a sweep every 3 hours in the daytime. When a game starts the hub keeps the closing line,
and when it ends the hub grades every call on it by itself. Floor 2 shows the same office with only its agents, plus a
Book panel: open calls, settled calls, P/L if each call were bet at 1 unit, and how often each desk beat the closing
line. Floor 1 never routes work to the desks. The board loads in a few seconds, so the office never sits blank.

## Context
- Verified on Oct 26: `site.api.espn.com/apis/site/v2/sports/<sport>/scoreboard` carries DraftKings (`provider.name ==
  "DraftKings"`) `pointSpread`, `total` and `moneyline`, each with `open` and current (`close`) line and odds, for NBA,
  NFL, college football, NHL, college basketball and the Premier League. Soccer moneylines include `draw`. A final game
  drops `odds`, so the hub has to keep the last pre-start snapshot as the close. Final scores are in `competitors[].score`.
  Samples: scratchpad `espn/`.
- Nothing polls DraftKings automatically. Agents open DraftKings in their own browser only when woken, to confirm the
  Illinois price before a call. Boboe 6 is testing access now (item #69302).
- `hub.py`: `DESKS`/`OFF_DESK` (added today) already keep desk-team agents out of floor-1 routing. Floor = `team in DESKS`.
- `office.js` `update(b)` draws exactly the agents in `b.agents`, so floor 2 is the same office fed a filtered board.
- `fleet.py:311` passes manage verbs to `/api/manage`. Adding `call` gives agents `fleet call ...` after their hourly
  GitHub pull. Until that push lands, the brief carries a `curl` fallback.
- Board build: `portfolio()` runs about 19.5k queries (8–12 s on the PC). Replace them with bulk queries.
- PC clock: US Eastern, and there's no tzdata for zoneinfo. Clock rules use `time.localtime` on the PC.
- Match: `etsy.py` (a hub module with its own tables and calls from `tick`); `_scout` (timed asks);
  `test_autonomy.py` cases; `score.py` grading math (scratchpad `sports-desk/`).
- Decision: six desks. `nba` Boboe 6, `nfl` Boboe Prime, `cfb` Boboe 11, `nhl` Boboe 17, `cbb` Boboe 8, `soccer`
  Boboe 18 (Premier League and Champions League).
- Decision: markets are spread, total and moneyline only, since the hub can grade them. Props stay in a desk's notes
  until there's a way to grade them.
- Decision: move thresholds. Spread or total by at least 1 point (0.5 for NHL, soccer and college football totals
  under 10), or a moneyline by at least 3 percentage points of implied probability. Wakes are batched, with at most one
  per desk every 20 minutes. Sweep: every 3 h from 09:00 to 23:00 PC time.
- Decision: a call is 1 unit at the DraftKings price, logged before start, never edited. The hub fills in the close and
  the result.
- Decision: Illinois. No calls on Illinois college teams, and only markets DraftKings offers in Illinois.
- Decision: Jack watches. No floor PM yet. Each Monday, every desk reviews the previous week of the next desk in the rotation.

## Must Not Change
- Floor 1 routing, products, tasks and Etsy flows. The `desk` and `board_shared` tests keep passing.
- The office's look and 3D world.
- Jack's DraftKings account: no credentials, no automated DraftKings requests.
- The uncommitted store-website work in the main checkout.

## Steps
- [ ] Step 1: Write `test_floor.py` cases `book`, `watch`, `board_speed` and `elevator` with `f01-test-driven-development`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN6.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Bulk-build `portfolio()` (one query for tasks with product) with the same output.
  - check: `python3 test_floor.py board_speed`
  - on fail: profile `board()` on `hub-debug.db`, cut the next-largest query count, redo Step 2.
- [x] Step 3: `sports.py` with its tables (`games`, `lines`, `calls`, `desk_state`), ESPN parsing, the watcher
  (jittered polling, move detection, batched wakes, sweeps, closing line, grading) and the `book()` summary. Six
  `DESKS`. Wire it into `tick`, `board()` and `manage` (`call add|list`).
  - check: `python3 test_floor.py book && python3 test_floor.py watch`
  - on fail: fix the rule or the grading the test names, redo Step 3.
- [x] Step 4: Add the elevator to `dashboard.html`. A Floor 1 / Floor 2 button filters agents and products by floor
  before the office and roster draw, labels the floor, and shows the Book panel on floor 2. The choice is remembered.
  - check: `python3 test_floor.py elevator`
  - on fail: fix the filter or the panel the test names, redo Step 4.
- [x] Step 5: Add `call` to `fleet.py`'s manage passthrough.
  - check: `python3 test_fleet.py call`
  - on fail: fix the tuple, redo Step 5.
- [ ] Step 6: Deploy to the PC, restart, set the six teams, and watch one real poll fill `games` and `lines`.
  - check: `bash check_floor_live.sh`
  - on fail: read `C:\fleet\hub.log`, roll back to `hub.py.bak-oct26` if the hub is down, fix, redo Step 6.
- [ ] Step 7: Send each desk its brief, built from Boboe 6's access findings.
  - check: compare against PLAN6.md
  - on fail: fix the brief, resend to that desk only, redo Step 7.

## Done When
- example: Jack opens the dashboard, presses Floor 2, and sees only the six desk agents and a Book panel. Floor 1 shows the Etsy agents and none of the six.
  - check: `python3 test_floor.py elevator`
  - fails with: "elevator: no Floor 2 button"
- example: a desk agent logs a call on a scheduled game and it's refused once the game has started. After the game, the hub has recorded the close and the result, and the Book shows that call's P/L at 1 unit and whether it beat the close.
  - check: `python3 test_floor.py book`
  - fails with: "book: unknown command"
- example: when a desk's line moves 1.5 points, that desk gets one batched wake naming the move. A 0.5-point drift wakes nobody, two moves inside 20 minutes make one wake, and no floor-1 agent is ever woken.
  - check: `python3 test_floor.py watch`
  - fails with: "watch: no sports module"
- example: the board builds in under 0.5 s on the Mac against live-sized data (a few seconds on the PC).
  - check: `python3 test_floor.py board_speed`
  - fails with: "board_speed: board took"
- example: each brief tells its desk everything it needs to work alone, with no login.
  - criterion: Every brief names its sport, says the hub wakes it on line moves and sweeps, gives the exact `fleet call add` syntax with a `curl` fallback, states the before-start and no-edit rules and the two Illinois rules, and says to confirm prices on DraftKings logged out. None asks for a password, account or payment.
- suite: `for c in $(python3 -c "import re;s=open('test_autonomy.py').read();i=s.index('{',s.rindex('if __name__'));print(' '.join(re.findall(r'\"([a-z_0-9]+)\":',s[i:])))"); do python3 test_autonomy.py $c | grep -q OK || { echo "FAIL $c"; exit 1; }; done && for c in council resubmit lifecycle poll placement org suggest seats manage loose grants timeline send_now dry activity observe teams pin handoff links switch_between stuck; do python3 test_company.py $c >/dev/null || { echo "FAIL $c"; exit 1; }; done && python3 test_fleet.py dashboard && python3 test_fleet.py call && python3 test_fleet.py`
- limit: 3 attempts
