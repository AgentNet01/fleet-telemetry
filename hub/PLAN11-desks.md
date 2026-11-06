# Floor 2: paired strategies on every sport, props graded on the close, everyone but Pericles betting

## Goal
Every sport desk (nba, nfl, cfb, nhl, cbb, soccer) has two agents: one betting early and one betting on game day,
on the same games. The book scores each strategy per sport on profit (units); closing-line value (CLV) is a side
gauge on the dashboard that agents never see. Player props get a closing line from ESPN, and their CLV is shown
apart from game-line CLV. All Muse agents except pericles williams are on floor 2
(spares on the explorer desk). Floor 1 stays alive with Pericles alone and starts no new products.

## Context
- `sports.py`: desks = `LEAGUES`; strategy is per desk today (`EARLY = ("nfl","soccer","nhl")`), so early vs
  game day compares different sports. `_wake` sends one round to the whole desk (`desk_state.last_sweep`,
  `offered(game, stage)`), `_next_games(desk)` picks games by the desk's strategy, and `book()` tallies `strategies`
  by desk.
- `sports.py` `_grade_props` settles props from the box score but never stores a close; `_graded` only scores
  `beat_close` when `close_odds` exists, so 17 of 34 live calls (every prop) have no CLV.
- ESPN core API `.../events/{id}/competitions/{id}/odds/100/propBets?limit=1000&page=N` (provider 100 =
  DraftKings) gives each prop `type.name`, `athlete.$ref`, `open.target.value` and `current.target.value`. It has
  line numbers but no prices. Checked Nov 1: NFL 1,692 items, NBA 1,093, NHL 515; CBB and soccer none.
- `hub.py`: `manage("team <agent> <desk>")` moves an agent; floor 1 grows work through `_dry()` (plans products)
  and `_scout()` (asks free agents to find new products), both called from `tick()`.
- Live: 19 Muse agents. Desks: nba Boboe 6, nfl Prime, cfb 11, nhl 17, cbb 8, soccer 18, lab Boboe 9. Movers:
  Boboe 1, 2, 3, 4, 5, 7, 10, 14, brutus, Dash, Neo. Seven movers hold tasks (working/verifying), and about 200
  products have PMs.
- Match: tests are scenario functions in `test_floor.py` (`new_hub`, `feed`, `poll`, `event`, `confirm`), run as
  `python3 test_floor.py <name>`. Deploy = scp to `C:\fleet\hub\` + `restart_hub.ps1`.
- Decision (Jack, Nov 1): nonstop rounds stay (10 min, 3 games); a capped agent is skipped until its reset
  (deployed today, `test_floor.py capped`).
- Decision (Jack, Nov 1): profit is the verdict; CLV is an early-warning gauge only. Agents are never shown CLV
  (`fleet call list`, briefs, nudges), so they bet to win, not to chase line moves. Props stay in; prop CLV
  (line-only) is tallied separately from game-line CLV.
- Decision: strategy is a property of the agent (`agents.strategy`: early | gameday), copied onto each call
  (`calls.strategy`) when it's logged, so later moves don't rewrite history.
- Decision: an early call must be logged ≥ 12 h before the game starts, a game-day call < 12 h before. Without this
  rule the two labels blur; 12 h splits "the day before / at the opener" from "same day".
- Decision: a prop's CLV is by line only (ESPN gives no prop prices): the call beats the close when the closing
  number moved its way (over: close line > our line; under: close line < our line). An unchanged line doesn't beat
  the close. The close is the last pre-start snapshot of that player's "Total <stat>" line.
- Decision: existing desk agents keep their desk's current strategy (nfl/nhl/soccer early, nba/cfb/cbb game day),
  and each new partner takes the other one. The 5 spare movers join lab; the explorer nudge names the other
  explorers and asks each to pick a different league or question.
- Decision: floor 1 "keep alive" = `_dry` and `_scout` off (no new products or planned tasks), movers' held tasks
  released to ready (routing then reaches Pericles, the only floor-1 agent), and movers' PM slots cleared. Live
  listings, orders and the Jack/CEO screen are untouched.

## Must Not Change
- Calls already in the book keep their results, closes and reviews; no rows deleted.
- Floor 1 commerce code (`etsy.py`, `ebay.py`, `amazon.py`, `orders.py`, `cj.py`, `money.py`) and the other
  session's uncommitted hunks in this worktree: `git diff --stat -- etsy.py ebay.py amazon.py orders.py cj.py money.py`
  is identical before and after.
- No request ever goes to DraftKings; props come from ESPN only.

## Steps
- [x] Step 1: Write each Done When example's test in `test_floor.py` with `f01-test-driven-development`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN11-desks.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Per-agent strategy: `agents.strategy` + `calls.strategy` columns; `fleet team`/`manage` sets it
  (`strategy <agent> early|gameday`); `_wake` hands rounds per agent (its own last round, its own worked games,
  `_next_games` by the agent's strategy); final look goes to game-day agents only; `call add` enforces the 12 h rule;
  `book()` adds `by_sport_strategy` (units first, then game CLV and prop CLV apart) and tallies `strategies` from
  `calls.strategy`; `fleet call list` drops the beat/missed-the-close text.
  - check: `python3 test_floor.py pairs`
  - on fail: fix sports.py, re-run Step 2.
- [x] Step 3: Prop closes: for each pre-start game with an open confirmed prop call, read ESPN propBets (desk
  sport/league path), map the call's stat to its "Total …" type, match the player by athlete name (cached
  `athletes(ref, name)` table), and store the last pre-start line in `calls.close_line`; `_graded` scores props by
  line; the open-call "since" verdict uses it too.
  - check: `python3 test_floor.py prop_close`
  - on fail: fix sports.py, re-run Step 3.
- [x] Step 4: Explorers: the lab nudge lists the other explorers and their watched leagues and notebook authors,
  and asks for a different league or question.
  - check: `python3 test_floor.py explorers`
  - on fail: fix `_lab`, re-run Step 4.
- [x] Step 5: Floor 1 keep-alive: a `GROWTH = False` switch in hub.py stops `_dry` and `_scout`.
  - check: `python3 test_floor.py floor1_quiet`
  - on fail: fix hub.py tick, re-run Step 5.
- [x] Step 6: Deploy hub.py + sports.py to the PC (backups `*.bak-pairs` via `Copy-Item`), restart, then run the
  one-time move script: desks/strategies per the Decision, release movers' tasks, clear movers' PM slots, and
  send each desk agent one brief naming its sport, strategy and partner.
  - check: `python3 check_pairs_live.py`
  - on fail: read `hub.log` for the restart and the script output; fix and re-run the script (it's idempotent).

## Done When
- example: Given an NBA desk with an early agent and a game-day agent and one game 30 h out and one 6 h out, when
  rounds run, then the early agent is handed the 30 h game, the game-day agent the 6 h game, an early call on the
  6 h game is refused, and the book shows nba early and nba game day as separate rows.
  - check: `python3 test_floor.py pairs`
  - fails with: "pairs: the early agent should get only games 12 h+ out"
- example: Given a graded call that beat the close, when its agent runs `fleet call list`, then the output shows its
  result and units but no closing-line verdict; the book shows game CLV and prop CLV as separate numbers.
  - check: `python3 test_floor.py clv_hidden`
  - fails with: "clv_hidden: an agent sees CLV"
- example: Given a confirmed prop call "Over 3.5 receptions" and ESPN's propBets showing that player's Total
  Receptions at 4.5 before kickoff, when the game goes final, then the call has close_line 4.5 and beat_close true.
  - check: `python3 test_floor.py prop_close`
  - fails with: "prop_close: the hub never read ESPN's propBets"
- example: Given three agents on the lab desk, when the explorer nudge goes out, then each one's text names the
  other two explorers.
  - check: `python3 test_floor.py explorers`
  - fails with: "explorers: La's nudge doesn't name"
- example: Given floor 1 with a free agent and a product with no tasks, when hours of ticks pass, then no "Find a
  new product" scout and no planning ask is sent.
  - check: `python3 test_floor.py floor1_quiet`
  - fails with: "floor1_quiet: floor 1 still grows"
- example: Live: every sport desk has at least one early and one game-day agent, every Muse agent but pericles
  williams is on floor 2, and no mover still owns a working task.
  - check: `python3 check_pairs_live.py`
  - fails with: "nba: want 1 early + 1 gameday, have"
- suite: `for t in book watch research slate sanity review strategy explore props pages wall elevator capped; do python3 test_floor.py $t || exit 1; done && python3 test_hub.py && python3 test_hub.py timing && for t in activity truth planning standin; do python3 test_autonomy.py $t || exit 1; done && python3 test_muse.py && python3 test_muse.py capped && python3 test_company.py`
- limit: 3 attempts
