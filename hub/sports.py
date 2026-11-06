"""Floor 2, the sports desk (Jack, Oct 26): six Muse agents, one per sport, find positions on DraftKings lines.

Nobody bets. The hub reads each sport's DraftKings lines from ESPN's public scoreboard feed every 5 minutes, give or
take 90 s, and keeps the history. A desk is woken only when its board changes enough to matter (new games, a real
move), plus a sweep every 3 h in the daytime. A desk logs a call with `fleet call add` before the game; the hub keeps
the last pre-start line as the close, reads the final score and grades the call itself, so the book always says
whether following the desk would have made money. Nothing here ever requests DraftKings itself.
"""
import calendar
import json
import re
import random
import time
import urllib.request

LEAGUES = {"nba": ["basketball/nba"], "nfl": ["football/nfl"], "cfb": ["football/college-football?groups=80"],
           "nhl": ["hockey/nhl"], "cbb": ["basketball/mens-college-basketball?groups=50"],
           "soccer": ["soccer/eng.1", "soccer/uefa.champions"],
           "lab": []}                    # the explorer adds its own leagues: `fleet call watch <sport/league>`
NAMES = {"nba": "NBA", "nfl": "NFL", "cfb": "College football", "nhl": "NHL", "cbb": "College basketball", "soccer": "Soccer",
         "lab": "Explorer"}
FEED = "https://site.api.espn.com/apis/site/v2/sports/"
POLL, JITTER = 300, 90                  # Jack: every five minutes, give or take 90 seconds
WAKE_GAP = 20 * 60                      # at most one wake per desk this often; moves in between are batched
ROUND, ROUND_GAP, REWORK = 3, 10 * 60, 2 * 3600           # Jack, Oct 29: desks work every game nonstop: 3 games a round, whenever idle
FINAL_LOOK = 2 * 3600                   # a last look at each game this long before it starts: lineups and goalies are out
EARLY = ("nfl", "soccer", "nhl")       # Jack, Oct 27: half the desks bet openers and news; the rest price game day
# Jack, Nov 1: that compared different sports. Strategy is now the agent's (agents.strategy), these desks only set the
# default; an early call is logged STRATEGY_SPLIT or more before the start, a game-day call inside it
STRATEGY_SPLIT = 12 * 3600
FIXED_SPREAD = ("nhl", "soccer")        # puck lines and goal lines sit at ±1.5/±0.5; the moneyline carries the moves
# a prop is graded from ESPN's box score: the stat's columns are summed. "group.LABEL" where a label repeats across groups
PROPS = {"basketball": {"points": ["PTS"], "rebounds": ["REB"], "assists": ["AST"], "threes": ["3PT"], "steals": ["STL"],
                        "blocks": ["BLK"], "pra": ["PTS", "REB", "AST"], "pr": ["PTS", "REB"], "pa": ["PTS", "AST"],
                        "ra": ["REB", "AST"]},
         "football": {"pass_yds": ["passing.YDS"], "pass_tds": ["passing.TD"], "completions": ["passing.C/ATT"], "interceptions": ["passing.INT"], "rush_yds": ["rushing.YDS"],
                      "rush_att": ["rushing.CAR"], "receptions": ["receiving.REC"], "rec_yds": ["receiving.YDS"],
                      "rush_rec_yds": ["rushing.YDS", "receiving.YDS"], "tds": ["rushing.TD", "receiving.TD"]},
         "hockey": {"shots": ["S"], "goals": ["G"], "assists": ["A"], "points": ["G", "A"], "saves": ["SV"],
                    "blocks": ["BS"], "hits": ["HT"]},       # ESPN's NHL "SOG" column reads 0 for scorers; "S" is shots on goal
         "soccer": {"shots": ["SHOT"], "sog": ["SOG"], "goals": ["G"], "assists": ["A"], "saves": ["SV"]}}
# Nov 1: a prop's close is DraftKings' main "Total <stat>" line on ESPN's core API (number only, no price)
CORE = "https://sports.core.api.espn.com/v2/sports/"
PROP_TYPES = {"basketball": {"points": "Total Points", "rebounds": "Total Rebounds", "assists": "Total Assists",
                             "threes": "Total 3-Point Field Goals", "steals": "Total Steals", "blocks": "Total Blocks",
                             "pra": "Total Points, Rebounds, and Assists", "pr": "Total Points and Rebounds",
                             "pa": "Total Points and Assists", "ra": "Total Assists and Rebounds"},
              "football": {"pass_yds": "Total Passing Yards", "pass_tds": "Total Passing Touchdowns",
                           "completions": "Total Pass Completions", "interceptions": "Total Passing Interceptions",
                           "rush_yds": "Total Rushing Yards", "rush_att": "Total Carries", "receptions": "Total Receptions",
                           "rec_yds": "Total Receiving Yards", "rush_rec_yds": "Total Rushing Plus Receiving Yards"},
              "hockey": {"points": "Total Points", "assists": "Total Assists", "shots": "Total Shots on Goal",
                         "saves": "Total Saves"}}
# Jack, Nov 6: the hub reads DraftKings' player props off ESPN for these desks (ESPN has none for college), each game
# inside PROP_AHEAD at most every PROP_EVERY, PROP_BATCH games a tick so one tick never stalls on dozens of fetches
PROP_DESKS, PROP_AHEAD, PROP_EVERY, PROP_BATCH = ("nba", "nhl", "nfl", "soccer"), 24 * 3600, 15 * 60, 6
SOCCER_PROPS = {"Shots Milestones": "shots", "Shots on Target Milestones": "sog", "Assists Milestones": "assists",
                "Anytime Goalscorer": "goals"}   # soccer has only "N+" markets: read as Over N-0.5
MAX_EDGE = 0.10                        # a claimed edge past 10 points of implied probability is a mistake, not a bet
MOVE_PTS = {"nhl": 0.5, "soccer": 0.5}  # a spread or total move worth a wake; 1 point everywhere else
MOVE_PROB = 0.03                        # a moneyline move worth a wake: 3 points of implied probability
FINAL = ("STATUS_FINAL", "STATUS_FULL_TIME", "STATUS_FINAL_OT", "STATUS_FINAL_PEN", "STATUS_FINAL_AET")
VOID = ("STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_ABANDONED", "STATUS_FORFEIT")
# DraftKings Illinois takes no online bets on Illinois college teams
ILLINOIS = ("Illinois", "Northwestern", "Bradley", "DePaul", "Loyola Chicago", "UIC", "Chicago State", "SIUE")

SCHEMA = """
create table if not exists games(id text primary key, desk text, name text, home text, away text, home_name text,
  away_name text, start real, status text, home_score real, away_score real, seen real);
create table if not exists lines(game text, market text, side text, line real, odds integer, at real);
create index if not exists lines_game on lines(game, market, side, at);
create table if not exists line_refs(game text, market text, side text, line real, odds integer,
  primary key(game, market, side));
create table if not exists calls(id integer primary key, desk text, agent text, game text, market text, side text,
  line real, odds integer, fair_odds integer, confidence integer, reason text, kill text, made_at real,
  close_line real, close_odds integer, result text, graded_at real);
create table if not exists desk_state(desk text primary key, next_poll real, last_wake real, last_sweep real, pending text);
create table if not exists offered(game text, stage integer, at real, primary key(game, stage));
create table if not exists lab_paths(path text primary key, at real);
create table if not exists worked(agent text, game text, at real, primary key(agent, game));
create table if not exists athletes(ref text primary key, name text);
create table if not exists props(game text, player text, stat text, side text, line real, odds integer, at real,
  primary key(game, player, stat, side, line));
create table if not exists lab_notes(id integer primary key, agent text, text text, at real);
"""


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "fleet-hub"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def implied(odds):
    o = float(odds)
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def payout(odds):
    o = float(odds)
    return o / 100 if o > 0 else 100 / -o


def _odds(v):
    v = str(v or "").strip().upper()
    if v == "EVEN":
        return 100
    try:
        o = int(float(v))
    except ValueError:
        return None
    return o if abs(o) >= 100 else None


def _num(v):
    try:
        return float(str(v).lstrip("ou"))
    except (TypeError, ValueError):
        return None


def parse(ev):
    """(game, [(market, side, line, odds)]) from one ESPN event; lines only from the DraftKings entry."""
    c = ev["competitions"][0]
    side = {x["homeAway"]: x for x in c["competitors"]}
    h, a = side["home"]["team"], side["away"]["team"]
    game = {"id": str(ev["id"]), "name": f"{a['abbreviation']} at {h['abbreviation']}", "home": h["abbreviation"],
            "away": a["abbreviation"], "home_name": h.get("location") or h.get("displayName") or "",
            "away_name": a.get("location") or a.get("displayName") or "", "status": c["status"]["type"]["name"],
            "start": calendar.timegm(time.strptime(ev["date"], "%Y-%m-%dT%H:%MZ")),
            "home_score": _num(side["home"].get("score")), "away_score": _num(side["away"].get("score"))}
    # the VM sees "Draft Kings", the Mac "DraftKings"
    dk = next((o for o in c.get("odds") or [] if o and ((o.get("provider") or {}).get("name") or "").replace(" ", "").lower()
               == "draftkings"), None)                 # Oct 26 live: a null sat in one game's odds list
    out = []
    if dk:
        cur = lambda d: (d or {}).get("close") or (d or {}).get("open") or {}
        for k, abbr in (("home", game["home"]), ("away", game["away"])):
            s = cur((dk.get("pointSpread") or {}).get(k))
            if _num(s.get("line")) is not None and _odds(s.get("odds")):
                out.append(("spread", abbr, _num(s["line"]), _odds(s["odds"])))
            m = cur((dk.get("moneyline") or {}).get(k))
            if _odds(m.get("odds")):
                out.append(("moneyline", abbr, None, _odds(m["odds"])))
        d = cur((dk.get("moneyline") or {}).get("draw"))
        if _odds(d.get("odds")):
            out.append(("moneyline", "draw", None, _odds(d["odds"])))
        for k in ("over", "under"):
            t = cur((dk.get("total") or {}).get(k))
            if _num(t.get("line")) is not None and _odds(t.get("odds")):
                out.append(("total", k, _num(t["line"]), _odds(t["odds"])))
    return game, out


def _show(market, side, line, odds):
    if market in ("total", "prop"):
        return f"{side} {line:g} ({odds:+d})"
    if market == "spread":
        return f"{side} {line:+g} ({odds:+d})"
    return f"{side} ML {odds:+d}"


AHEAD = {"nfl": 7, "cfb": 6, "soccer": 7}    # weekly sports post next week's lines days early; ESPN takes no date ranges


def _urls(desk, path, now):
    """Today's board plus the days ahead where lines are already posted (2 for daily sports, a week for weekly ones)."""
    base, _, q = path.partition("?")
    url = FEED + base + "/scoreboard?" + (q + "&" if q else "") + "limit=300"
    return [url] + [url + "&dates=" + time.strftime("%Y%m%d", time.localtime(now + d * 86400)) for d in range(1, AHEAD.get(desk, 2) + 1)]


def _ensure(h):
    if not getattr(h, "_sports_ready", False):
        h.db.executescript(SCHEMA)
        for tbl, col in [("calls", c) for c in ("review text", "review_by text", "review_note text", "review_asked real",
                                                "player text", "stat text", "soft integer", "strategy text")]:
            try:
                h.db.execute(f"alter table {tbl} add column {col}")
            except Exception:                         # already there
                pass
        h._sports_ready = True


def strategy_of(h, agent, desk):
    """early | gameday | explore: the agent's own, else its desk's default."""
    if desk == "lab":
        return "explore"
    r = h.db.execute("select strategy from agents where name=?", (agent,)).fetchone()
    return (r and r["strategy"]) or ("early" if desk in EARLY else "gameday")


def desk_of(h, agent):
    a = h.db.execute("select team from agents where name=?", (agent,)).fetchone()
    return a and a["team"] in LEAGUES and a["team"]


def tick(h):
    """Poll each staffed desk's leagues when due (network outside the lock), record changes, wake desks."""
    now = h.clock()
    with h.lock:
        _ensure(h)
        due = []
        for desk in LEAGUES:
            staff = [r["name"] for r in h.db.execute("select name from agents where team=? and state='active'", (desk,))]
            st = h.db.execute("select * from desk_state where desk=?", (desk,)).fetchone()
            if staff and (not st or now >= (st["next_poll"] or 0)):
                due.append((desk, LEAGUES[desk] + [r["path"] for r in h.db.execute("select path from lab_paths")]
                            if desk == "lab" else LEAGUES[desk]))
        finals = [(desk, r["game"]) for desk, _ in due for r in h.db.execute(
            "select distinct c.game from calls c join games g on g.id=c.game where c.desk=? and c.market='prop' and "
            f"c.result is null and g.status in {FINAL}", (desk,))]
        props = [(desk, r["game"], [dict(c) for c in h.db.execute(
                     "select id, player, stat from calls where game=? and market='prop' and result is null", (r["game"],))])
                 for desk, _ in due if desk != "lab" for r in h.db.execute(
                     "select distinct c.game from calls c join games g on g.id=c.game where c.desk=? and c.market='prop' and "
                     "c.result is null and g.status='STATUS_SCHEDULED' and g.start > ?", (desk, now))]
        seen_at = h.__dict__.setdefault("_props_at", {})
        boards = [(r["desk"], r["id"]) for r in h.db.execute(
            f"select desk, id from games where desk in {PROP_DESKS} and status='STATUS_SCHEDULED' and start > ? and start <= ? "
            "order by start", (now, now + PROP_AHEAD)) if now - seen_at.get(r["id"], 0) >= PROP_EVERY][:PROP_BATCH]
        names = dict(h.db.execute("select ref, name from athletes").fetchall()) if props or boards else {}
    boxes = [(desk, gid, _box(h, desk, gid)) for desk, gid in finals]
    closes = [c for desk, gid, cs in props for c in _prop_lines(h, desk, gid, cs, names)]
    priced = []
    for desk, gid in boards:
        seen_at[gid] = now                            # a failed read waits PROP_EVERY too: never hammer ESPN
        items = _prop_items(h, desk, gid, names)
        if items is not None:
            priced.append((gid, _parse_props(desk, items, names)))
    got = {}
    for desk, paths in due:
        events = []
        for path in paths:
            for url in _urls(desk, path, now):
                try:
                    events += (h.sports_fetch(url) or {}).get("events", [])
                except Exception as e:                    # one bad fetch skips this round for that url only
                    print(time.strftime("%F %T"), f"sports feed {desk} {url}: {e}", flush=True)
        got[desk] = events
    with h.lock:
        for desk, events in got.items():
            moves, seen = [], set()
            for ev in events:
                try:
                    game, lines = parse(ev)
                except Exception as e:                    # one odd game never blanks the rest of the board
                    print(time.strftime("%F %T"), f"sports: skipped {desk} event {(ev or {}).get('id')}: {e!r}", flush=True)
                    continue
                if game["id"] in seen:
                    continue
                seen.add(game["id"])
                moves += _record(h, desk, game, lines, now)
            st = h.db.execute("select * from desk_state where desk=?", (desk,)).fetchone()
            pending = json.loads(st["pending"]) if st and st["pending"] else []
            h.db.execute("insert or replace into desk_state(desk, next_poll, last_wake, last_sweep, pending) values(?,?,?,?,?)",
                         (desk, now + POLL + random.uniform(-JITTER, JITTER), st and st["last_wake"], st and st["last_sweep"],
                          json.dumps(pending + moves)))
        for desk, gid, box in boxes:
            if box:
                _grade_props(h, desk, gid, box)
        h.db.executemany("insert or ignore into athletes(ref, name) values(?,?)", names.items())
        for gid, rows in priced:
            h.db.execute("delete from props where game=?", (gid,))
            h.db.executemany("insert or replace into props(game, player, stat, side, line, odds, at) values(?,?,?,?,?,?,?)",
                             [(gid, *r, now) for r in rows])
        for cid, line in closes:                      # only pre-start reads land here: the last one is the close
            h.db.execute("update calls set close_line=? where id=? and result is null", (line, cid))
        for desk in LEAGUES:
            _wake(h, desk, now)


def _record(h, desk, game, lines, now):
    """Store the game and any changed line; grade its calls once final. Returns the moves worth a wake."""
    old = h.db.execute("select * from games where id=?", (game["id"],)).fetchone()
    h.db.execute("insert or replace into games(id, desk, name, home, away, home_name, away_name, start, status, home_score, "
                 "away_score, seen) values(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (game["id"], desk, game["name"], game["home"], game["away"], game["home_name"], game["away_name"],
                  game["start"], game["status"], game["home_score"], game["away_score"], now))
    if game["status"] in FINAL or game["status"] in VOID:
        _grade(h, game)
        return []
    if game["status"] != "STATUS_SCHEDULED" or now >= game["start"]:
        return []                                         # live odds aren't the close: the last pre-start line is
    moves = []
    for market, side, line, odds in lines:
        last = h.db.execute("select line, odds from lines where game=? and market=? and side=? order by at desc limit 1",
                            (game["id"], market, side)).fetchone()
        if not last or (last["line"], last["odds"]) != (line, odds):
            h.db.execute("insert into lines(game, market, side, line, odds, at) values(?,?,?,?,?,?)",
                         (game["id"], market, side, line, odds, now))
        if (market, side) not in (("spread", game["home"]), ("total", "over"), ("moneyline", game["home"])):
            continue                                      # one side per market says it; the other is its mirror
        if market == "spread" and desk in FIXED_SPREAD:
            continue                                      # Oct 27 live: the feed toggles CHI +1.5 / -1.5 all day
        ref = h.db.execute("select * from line_refs where game=? and market=? and side=?", (game["id"], market, side)).fetchone()
        if ref and market != "moneyline" and abs(line - ref["line"]) < MOVE_PTS.get(desk, 1.0):
            continue
        if ref and market == "moneyline" and abs(implied(odds) - implied(ref["odds"])) < MOVE_PROB:
            continue
        h.db.execute("insert or replace into line_refs(game, market, side, line, odds) values(?,?,?,?,?)",
                     (game["id"], market, side, line, odds))
        was = "" if not ref else f" (was {_show(market, side, ref['line'], ref['odds'])})"
        moves.append(f"{game['name']} {time.strftime('%a %H:%M', time.localtime(game['start']))} · {market} "
                     f"{_show(market, side, line, odds)}{was}" + ("" if ref else " · new on the board"))
    return moves


def _wake(h, desk, now):
    st = h.db.execute("select * from desk_state where desk=?", (desk,)).fetchone()
    if not st:
        return
    # a capped agent (out of Muse usage) isn't staff until its reset: anything sent meanwhile is lost (Nov 1)
    staff = [r["name"] for r in h.db.execute("select name from agents where team=? and state='active' "
                                             "and coalesce(capped_until, 0) <= ?", (desk, now))]
    pending = json.loads(st["pending"] or "[]")
    if pending and now - (st["last_wake"] or 0) >= WAKE_GAP:
        news, rest = [m for m in pending if "new on the board" in m], [m for m in pending if "new on the board" not in m]
        body = "\n".join(f"- {m}" for m in (rest + news)[:40]) + (f"\n- …and {len(pending) - 40} more" if len(pending) > 40 else "")
        early = ("\n\nYou move early: new lines are softest right after they post, so price new games now. A move you "
                 "didn't call means the market already knows something; bet it only if the new number still beats your fair.")
        for n in staff:
            h._deliver_to(n, f"{NAMES[desk]} lines moved", "DraftKings lines on your board changed:\n" + body
                          + (early if strategy_of(h, n, desk) == "early" else "") + "\n\n" + NEXT)
        h.db.execute("update desk_state set pending='[]', last_wake=? where desk=?", (now, desk))
    elif desk != "lab":
        for n in staff:                           # each agent works its own strategy's games at its own pace
            last = h.db.execute("select max(at) from worked where agent=?", (n,)).fetchone()[0] or 0
            if now - last < ROUND_GAP or _busy(h, [n]):
                continue
            strat = strategy_of(h, n, desk)
            games = _next_games(h, desk, now, n, strat, [m for m in staff if m != n and strategy_of(h, m, desk) == strat])
            if games:
                h._deliver_to(n, f"{NAMES[desk]} · next games", brief(desk) + (OPENERS if strat == "early" else SLATE)
                              + _board(games) + "\n\n" + NEXT)
                h.db.executemany("insert or replace into worked(agent, game, at) values(?,?,?)", [(n, g["id"], now) for g in games])
    looks = [n for n in staff if strategy_of(h, n, desk) == "gameday"]   # an early agent's window has closed by now
    soon = _open_games(h, desk, now, now + FINAL_LOOK, 2)
    if soon and looks:
        for n in looks:
            h._deliver_to(n, f"{NAMES[desk]} final look", LOOK + _board(soon) + "\n\n" + NEXT)
        h.db.executemany("insert or ignore into offered(game, stage, at) values(?,2,?)", [(g["id"], now) for g in soon])
    if desk == "lab":
        _lab(h, staff, now, st)
    _review_round(h, desk, staff, now)


LAB_START = ("This is your assigned work: you're on the explorer desk (team lab), and nothing else is queued for you. "
             "First task, since your notebook is empty: run `fleet call watch soccer/ger.1` and `fleet call watch "
             "soccer/esp.1` (Bundesliga and La Liga; no other desk covers them). Get last season's results with opening and "
             "closing odds (football-data.co.uk has free CSVs) and test one hypothesis, e.g. whether opening totals move "
             "toward the close in a predictable direction. Write what you find with `fleet call note`, then bet only what "
             "the data supports.\n\n")
LAB = ("You're the explorer desk. Find an edge anywhere: any sport or league ESPN's scoreboard carries with DraftKings odds "
       "(baseball/mlb, basketball/wnba, soccer/ger.1, football/ufl…; team-vs-team events only for now), or a pattern in timing, "
       "line movement or information. Find datasets, do deep research, and test a hypothesis against past results before you "
       "bet on it. Your calls get the same price check, another desk's review and grading as every desk's.\n"
       "`fleet call watch <sport/league>` adds a league to your board · `fleet call games` lists it · `fleet call add …` "
       "logs a call · `fleet call note \"<finding or hypothesis>\"` writes your notebook, which Jack reads.\n"
       "Pick up where you left off and take the next concrete step.")


def _lab(h, staff, now, st):
    """Hand the explorer its next step whenever it has nothing in flight (at most every ROUND_GAP), with its notebook."""
    if not staff or now - ((st and st["last_sweep"]) or 0) < ROUND_GAP:
        return
    free = [n for n in staff if not _busy(h, [n])]          # one busy explorer never holds up the rest
    if not free:
        return
    notes = h.db.execute("select agent, text, at from lab_notes order by id desc limit 8").fetchall()
    paths = [r["path"] for r in h.db.execute("select path from lab_paths order by at")]
    body = ("" if notes or paths else LAB_START) + LAB + "\n\nWatching: " + (", ".join(paths) or "nothing yet") + "\nThe notebook, newest first:\n" + (
        "\n".join(f"- {time.strftime('%a %H:%M', time.localtime(n['at']))} {n['agent']}: {n['text']}" for n in notes) or "- (empty)")
    for n in free:
        # Jack, Nov 1: several explorers; each takes its own league or question instead of repeating another's test
        others = [o for o in staff if o != n]
        h._deliver_to(n, "Explorer: next step", body + (
            f"\n\nOther explorers: {', '.join(others)}. Read their notes above and take a different league or question "
            "from theirs; build on a finding of theirs only to test it a new way." if others else ""))
    h.db.execute("update desk_state set last_sweep=? where desk='lab'", (now,))

# Jack, Oct 29: Sanjay's NBA prop prompt, adapted to each desk. Every slate and research round opens with it
METHOD = ("How you work, every slate: you're an elite quantitative {sport} betting strategist. Your job is to find "
          "mispriced DraftKings lines, player props first, and log a side on every game, each with an honest confidence. Skip the "
          "surface-level box score. Work through these four steps:\n"
          "1. Defense vs position. For every game, measure what each defense gives up to each position ({pos}): "
          "{stats}, above or below league average over the last 5 games, the last 15, and the season. Name the scheme "
          "weakness behind it ({scheme}).\n"
          "2. Injury cascade. Read the injury report. When a starter or high-usage player is out, work out who absorbs "
          "their {usage}, and which secondary player's line hasn't caught up to the bigger role.\n"
          "3. Role and minutes. Judge each player on recent rolling {minutes}, not season numbers padded by blowouts "
          "or early-season rotations. Set volume floors and ceilings against the opponent's pace ({pace}).\n"
          "4. Outliers. Find where DraftKings' line misses the matchup or the role change. Flag regression candidates "
          "(players riding an unsustainable {hot} against tough matchups) and breakout spots.\n"
          "Write each pick's reason in four parts: injury and usage impact · positional exploit · the outlier · risk and "
          "failure points ({risk}).\n"
          "Take DraftKings' main line at its price, not an alternate line.\n"
          "Always analyze and follow the lines on DraftKings.\n")
SPORT = {
    "nba": dict(sport="NBA", pos="PG, SG, SF, PF, C", stats="points, rebounds, assists, threes and DraftKings fantasy points",
                scheme="drop coverage vs switching vs hedging on pick-and-roll, and which guards or rolling bigs it frees up",
                usage="usage rate, field-goal attempts and potential assists", minutes="minutes and USG%",
                pace="possessions per 48 minutes", hot="shooting percentage", risk="blowout, foul trouble, a rest day, a scheme change"),
    "cbb": dict(sport="men's college basketball", pos="guards, wings, bigs", stats="points, rebounds, assists and threes",
                scheme="zone vs man, how they guard ball screens, rim protection", usage="shots, touches and minutes "
                "(rotations run 7 or 8 deep, so one absence moves a lot)", minutes="minutes and usage over the last 5 games",
                pace="adjusted tempo, possessions per 40 minutes", hot="three-point percentage",
                risk="a blowout against a weak opponent, foul trouble in a 40-minute game, a coach shortening the bench"),
    "nfl": dict(sport="NFL", pos="QB, RB, WR, TE, and slot vs outside receivers",
                stats="passing, rushing and receiving yards, receptions and touchdowns",
                scheme="man vs zone, two-high shells, blitz and pressure rate against this offensive line, run fits",
                usage="targets, carries, red-zone looks and snaps", minutes="snap share, route participation and target share",
                pace="plays per game and seconds per play, plus the game total and likely script", hot="touchdown rate or yards per catch",
                risk="game script, weather, a blowout benching, an in-game injury, a coaching change"),
    "cfb": dict(sport="college football", pos="QB, RB, WR, TE", stats="passing, rushing and receiving yards and touchdowns",
                scheme="coverage shells, pressure against a weak offensive line, how a defense handles tempo and RPOs",
                usage="targets, carries and snaps (depth charts are murky, so check beat reporters)",
                minutes="snap share and touches over the last 3 or 4 games", pace="plays per game; tempo teams swing totals",
                hot="yards per carry or catch against weak opponents",
                risk="starters pulled in a blowout, weather, a backup quarterback, a rivalry-game script"),
    "nhl": dict(sport="NHL", pos="centers, wingers, defensemen, goalies", stats="shots on goal, points, blocked shots and saves",
                scheme="shot suppression, how they defend the slot and the power play, forecheck pressure",
                usage="power-play time, line slot and ice time (check Daily Faceoff line combos)",
                minutes="ice time (TOI) and power-play TOI", pace="shot attempts per 60 for both teams, and back-to-backs",
                hot="shooting percentage or a goalie's save percentage",
                risk="a goalie change, a blowout, penalties killing even-strength time, a line shuffle"),
    "soccer": dict(sport="soccer (Premier League and Champions League)", pos="strikers, wingers, attacking mids, fullbacks, keepers",
                   stats="shots, shots on target, chances created and tackles",
                   scheme="high line vs low block, which flank they concede on, set-piece defending",
                   usage="shots, set pieces and penalties (check confirmed lineups an hour before kickoff)",
                   minutes="minutes over the last 5 matches (watch midweek European rotation)",
                   pace="possession share, shots per game and expected goals (xG)", hot="finishing well above xG",
                   risk="rotation or a late substitution, an early red card, a game state that parks the bus"),
}


PAPER = ("No money moves on this floor: nobody places a real bet. A call is a tracked pick; the hub scores it as if it "
         "were a $10 bet at DraftKings' price, so no bankroll, stake or approval is needed.\n\n")   # Nov 1: 4 new desk agents refused "betting is spending"


def brief(desk):
    """The desk's standing method, then the stat names the hub can grade on its props."""
    if desk not in SPORT:
        return ""
    stats = ", ".join(PROPS.get(_family(desk), {}))
    return (PAPER + METHOD.format(**SPORT[desk])
            + f"Props the hub grades on your desk: {stats}.\n\n")


SLATE = ("You bet on game day: the hub takes your calls inside 12 h of the start. Your next games. Research each game as deeply as it deserves, no more: a game where nothing stands out "
         "can be a quick pass with your fair price. Write out the four parts for each pick you log: injury and usage impact · "
         "positional exploits · outlier prop targets · risk and failure points. "
         "Log a call on every game you work: your side wherever your fair price beats DraftKings' at all, props first. "
         "Confidence 1 is a lean (a small edge), 2 solid, 3 strong. "
         "When you pass on a game or a prop you priced, log the pass: the same command with confidence 0 and your fair price, even when your fair says the price is no bargain. A pass is never a bet; it lets the hub score every price you set. "
         "Leans count at once; 2s and 3s count after another desk checks them. The book scores each confidence apart, "
         "so a lean costs nothing if it's honest. "
         "If you've worked a game before, say what changed. "
         "Be honest about size: a real edge is a few points of win probability, so a fair price of about -125 to -135 "
         "against -110, not -160. The next games come when you finish.\n")
OPENERS = ("You bet early: the hub takes your calls 12 h or more before the start; your game-day partner covers the rest. "
           "Your next games. You bet early, because new lines are the softest. Start with breaking news (injuries, "
           "lineups, suspensions, coaching changes) the line hasn't absorbed yet. Then research each game as deeply as it "
           "deserves, no more: a game where nothing stands out can be a quick pass with your fair price. Write out the four "
           "parts for each pick you log: injury and usage impact · positional exploits · outlier prop targets · risk and "
           "failure points. Props usually post closer to game day, so look again when they're up. "
           "Log a call on every game you work: your side wherever your fair price beats DraftKings' at all, props first. "
           "Confidence 1 is a lean (a small edge), 2 solid, 3 strong. "
           "When you pass on a game or a prop you priced, log the pass: the same command with confidence 0 and your fair price, even when your fair says the price is no bargain. A pass is never a bet; it lets the hub score every price you set. "
           "Leans count at once; 2s and 3s count after another desk checks them. The book scores each confidence apart, "
           "so a lean costs nothing if it's honest. "
           "Be honest about size: a real "
           "edge is a few points of win probability. The next games come when you finish.\n")
LOOK = ("Final look: these start within two hours and you haven't called them. Lineups, goalies, and late injury news "
        "are out now. Rerun the injury cascade, then log your side on each one (a lean is fine).\n")


def _busy(h, staff):
    """Something is still in flight for the desk: a message it hasn't finished, or its agent mid-turn."""
    q = ",".join("?" * len(staff))
    return h.db.execute(f"select 1 from items where too in ({q}) and status in ('queued','sent') union all "
                        f"select 1 from agents where name in ({q}) and busy=1", staff + staff).fetchone()


def _next_games(h, desk, now, agent, strat, mates=()):
    """The desk's next ROUND games to work, called or not: tonight's first (Jack wants same-day), then never worked,
    then worked longest ago; a game worked in the last REWORK isn't resent, so a desk with a small slate rests instead
    of re-reading identical boards. An early desk works every posted game; a game-day desk its next day of play
    (Jack's Oct 27 split). `mates` share the agent's desk and strategy: a game one of them worked counts as worked, so
    two early agents split the games instead of both reading the same ones (Jack, Nov 6)."""
    def slate_end(t):                                 # a slate runs to 6am: late West Coast games belong to it
        d = time.localtime(t - 6 * 3600)
        return time.mktime((d.tm_year, d.tm_mon, d.tm_mday + 1, 6, 0, 0, 0, 0, -1))
    who = [agent, *mates]
    begin, end = now, now + 30 * 86400
    if strat == "early":
        begin = now + STRATEGY_SPLIT              # the only games it may still call
    else:
        first = h.db.execute("select min(start) from games where desk=? and status='STATUS_SCHEDULED' and start > ?",
                             (desk, now)).fetchone()[0]
        end = min(slate_end(first), now + STRATEGY_SPLIT) if first else now
    return h.db.execute(
        "select g.*, (select line from lines l where l.game=g.id and l.market='spread' and l.side=g.home order by at desc "
        "limit 1) as sp, (select line from lines l where l.game=g.id and l.market='total' and l.side='over' order by at desc "
        "limit 1) as tot, coalesce((select max(at) from worked w where w.game=g.id and w.agent in "
        f"({','.join('?' * len(who))})), 0) as wat from games g where g.desk=? and "
        "g.status='STATUS_SCHEDULED' and g.start >= ? and g.start > ? and g.start <= ? and wat <= ? "
        "order by g.start <= ? desc, wat, g.start limit ?",
        (*who, desk, begin, now, end, now - REWORK, slate_end(now), ROUND)).fetchall()


def _open_games(h, desk, now, end, stage):
    """Scheduled games starting before `end` that the desk hasn't called and hasn't been handed at this stage yet."""
    return h.db.execute(
        "select g.*, (select line from lines l where l.game=g.id and l.market='spread' and l.side=g.home order by at desc "
        "limit 1) as sp, (select line from lines l where l.game=g.id and l.market='total' and l.side='over' order by at desc "
        "limit 1) as tot from games g where desk=? and status='STATUS_SCHEDULED' and start > ? and start <= ? and not exists "
        "(select 1 from calls c where c.game=g.id and c.confidence > 0) and not exists (select 1 from offered o where o.game=g.id and o.stage=?) "
        "order by start limit 40", (desk, now, end, stage)).fetchall()


def _board(games):
    return "\n".join(f"- {g['id']} {g['name']} {time.strftime('%a %H:%M', time.localtime(g['start']))}"
                     + (f" · {g['home']} {g['sp']:+g}" if g["sp"] is not None else "")
                     + (f" · total {g['tot']:g}" if g["tot"] is not None else "") for g in games)


def _review_round(h, desk, staff, now):
    """Hand this desk's new calls to the next staffed desk on the hub's next pass: a call counts only once confirmed."""
    staffed = [k for k in LEAGUES if h.db.execute("select 1 from agents where team=? and state='active'", (k,)).fetchone()]
    if not staff or len(staffed) < 2:
        return
    peer = staffed[(staffed.index(desk) + 1) % len(staffed)]
    calls = h.db.execute("select c.*, g.name as game_name, g.home, g.away, g.home_name, g.away_name, g.start from calls c "
                         "join games g on g.id=c.game where c.desk=? and c.review is null and c.review_asked is null and c.result is null and "
                         "g.start > ? order by c.id limit 15", (desk, now)).fetchall()
    if not calls:
        return
    body = "\n".join(f"- #{c['id']} {c['game_name']} {time.strftime('%a %H:%M', time.localtime(c['start']))} ({c['agent']}): "
                     f"{_pick(c)} at {c['odds']:+d}, fair {c['fair_odds']:+d}, confidence {c['confidence']}. Why: {c['reason']} "
                     f"Wrong if: {c['kill']}" for c in calls)
    for n in [r["name"] for r in h.db.execute("select name from agents where team=? and state='active'", (peer,))]:
        h._deliver_to(n, f"Check the {NAMES[desk]} desk's reasoning",
                      f"The {NAMES[desk]} desk proposed these calls. None counts until you confirm it, and anything not "
                      "confirmed before its game starts is never tracked, so check them now. Research each one: are the "
                      "facts right (players, goalies, injuries, who's home), does the reasoning support that side at that "
                      "price, and is the fair price honest? If something's unclear, ask the desk: `fleet ask \"<agent>\" "
                      "\"<question>\"`. Then mark each one:\n`fleet call review <id> ok \"<what you checked>\"` or "
                      "`fleet call review <id> flag \"<what's wrong>\"`. You can confirm a flagged call later if the desk "
                      "shows you were wrong.\n" + body)
    h.db.executemany("update calls set review_asked=? where id=?", [(now, c["id"]) for c in calls])


NEXT = ("Never open DraftKings in a browser: the hub has its prices. Game lines: `fleet call games` and this message show "
        "DraftKings' lines, read every 5 minutes, and the hub checks your price. Player props: `fleet call props <game id>` "
        "lists the props the hub has DraftKings prices for; a prop that isn't listed can't be logged yet. Game line: "
        "`fleet call add <game id> spread|total|moneyline <side> <line, or - for moneyline> <DraftKings odds> <your fair odds> "
        "<confidence 0-3> \"<why>\" \"<what would make it wrong>\"`. Player prop: `fleet call prop <game id> \"<player as "
        "ESPN spells it>\" <stat> over|under <line> <DraftKings odds> <your fair odds> <confidence 0-3> \"<why>\" "
        "\"<what would make it wrong>\"`. Game ids: `fleet call games`.")


def _family(desk):
    return (LEAGUES.get(desk) or [""])[0].split("/")[0]


def _box(h, desk, gid):
    """{player name, lowercased: {column: number}} from ESPN's box score, or None while it isn't posted."""
    for path in LEAGUES[desk]:
        try:
            j = h.sports_fetch(f"{FEED}{path.partition('?')[0]}/summary?event={gid}") or {}
        except Exception as e:
            print(time.strftime("%F %T"), f"sports box {desk} {gid}: {e}", flush=True)
            continue
        out = {}
        for team in (j.get("boxscore") or {}).get("players") or []:
            for grp in team.get("statistics") or []:
                for ath in grp.get("athletes") or []:
                    row = out.setdefault(((ath.get("athlete") or {}).get("displayName") or "").lower(), {})
                    for lab, v in zip(grp.get("labels") or [], ath.get("stats") or []):
                        n = _num(re.split("[-/]", str(v))[0])        # "11-22" and "15/27" count the made ones
                        if n is not None:
                            row.setdefault(lab, n)
                            row[f"{grp.get('name')}.{lab}"] = n
        for team in j.get("rosters") or []:                         # soccer keeps player stats here
            for p in team.get("roster") or []:
                st = {x.get("abbreviation"): x.get("value") or 0 for x in p.get("stats") or []}
                out[((p.get("athlete") or {}).get("displayName") or "").lower()] = st if st.get("APP") else {}
        if out:
            return out
    return None


def _prop_items(h, desk, gid, names):
    """Every propBets item ESPN holds for a game, with athlete names resolved into `names`; None if a read failed.
    Network only, no lock."""
    sport, _, league = LEAGUES[desk][0].partition("?")[0].partition("/")
    items, page, pages = [], 1, 1
    try:
        while page <= pages and page <= 5:
            j = h.sports_fetch(f"{CORE}{sport}/leagues/{league}/events/{gid}/competitions/{gid}/odds/100/propBets"
                               f"?lang=en&region=us&limit=1000&page={page}") or {}
            pages = j.get("pageCount") or 1
            items += j.get("items") or []
            page += 1
        for ref in {((it.get("athlete") or {}).get("$ref") or "").split("?")[0] for it in items} - set(names) - {""}:
            names[ref] = (h.sports_fetch(ref) or {}).get("displayName") or ""
    except Exception as e:
        print(time.strftime("%F %T"), f"sports prop board {desk} {gid}: {e}", flush=True)
        return None
    return items


def _parse_props(desk, items, names):
    """DraftKings' main player props: [(player, stat, side, line, odds or None)]. A "Total <stat>" market comes as two
    items in feed order, over then under (checked Nov 6 against the matching "N+" milestone: 6 of 6); NBA/NHL milestones
    are alternate lines and are skipped. Soccer has only "N+" markets, read as Over N-0.5."""
    totals = {v: k for k, v in PROP_TYPES.get(_family(desk), {}).items()}
    out, sides = [], {}
    for it in items:
        name = names.get(((it.get("athlete") or {}).get("$ref") or "").split("?")[0])
        typ = ((it.get("type") or {}).get("name") or "").split(" (")[0]
        cur = it.get("current") or {}
        if not name:
            continue
        if desk == "soccer" and typ in SOCCER_PROPS:
            o = _odds((cur.get("over") or {}).get("american"))
            if o:
                out.append((name, SOCCER_PROPS[typ], "over", (_num((cur.get("target") or {}).get("value")) or 1) - 0.5, o))
        elif typ in totals:
            line = _num((cur.get("target") or {}).get("value"))
            k = (name, totals[typ], line)
            if line is None or sides.get(k, 0) >= 2:
                continue
            sides[k] = sides.get(k, 0) + 1
            out.append((name, totals[typ], "over" if sides[k] == 1 else "under", line,
                        _odds(((it.get("odds") or {}).get("american") or {}).get("value")) or None))
    return out


def _prop_lines(h, desk, gid, calls, names):
    """[(call id, DraftKings' current line for that player's stat)] from ESPN's propBets; fills `names` (athlete ref ->
    name) as it goes. Network only, no lock: a failed read skips this poll."""
    types = PROP_TYPES.get(_family(desk), {})
    want = {(c["player"] or "").lower(): [] for c in calls}
    for c in calls:
        if c["stat"] in types:
            want[(c["player"] or "").lower()].append((types[c["stat"]], c["id"]))
    if not any(want.values()):
        return []
    sport, _, league = LEAGUES[desk][0].partition("?")[0].partition("/")
    out, page, pages = [], 1, 1
    try:
        while page <= pages and page <= 5:
            j = h.sports_fetch(f"{CORE}{sport}/leagues/{league}/events/{gid}/competitions/{gid}/odds/100/propBets"
                               f"?lang=en&region=us&limit=1000&page={page}") or {}
            pages = j.get("pageCount") or 1
            for it in j.get("items") or []:
                typ = ((it.get("type") or {}).get("name") or "").split(" (")[0]
                line = _num(((it.get("current") or {}).get("target") or {}).get("value"))
                ref = ((it.get("athlete") or {}).get("$ref") or "").split("?")[0]
                if line is None or not ref or not any(typ == t for ts in want.values() for t, _ in ts):
                    continue
                if ref not in names:
                    names[ref] = ((h.sports_fetch(ref) or {}).get("displayName") or "")
                out += [(cid, line) for t, cid in want.get(names[ref].lower(), []) if t == typ]
            page += 1
    except Exception as e:
        print(time.strftime("%F %T"), f"sports props {desk} {gid}: {e}", flush=True)
        return []
    return out


def _grade_props(h, desk, game, box):
    """Settle a final game's confirmed props from its box score. A player with no line in the box didn't play: void."""
    for c in h.db.execute("select * from calls where game=? and market='prop' and result is null", (game,)).fetchall():
        row = box.get((c["player"] or "").lower()) or {}
        cols = PROPS.get(_family(desk), {}).get(c["stat"]) or []
        if not row or not cols:
            res = "void"
        else:
            d = (sum(row.get(k, 0) for k in cols) - c["line"]) * (1 if c["side"] == "over" else -1)
            res = "win" if d > 0 else "push" if d == 0 else "loss"
        h.db.execute("update calls set result=?, graded_at=? where id=?", (res, h.clock(), c["id"]))


def _grade(h, game):
    for c in h.db.execute("select * from calls where game=? and result is null", (game["id"],)).fetchall():
        if c["market"] == "prop" and c["review"] == "ok" and game["status"] not in VOID:
            continue                                      # graded from the box score: _grade_props
        close = h.db.execute("select line, odds from lines where game=? and market=? and side=? and (market!='spread' or "
                             "line*?>0) order by at desc limit 1", (game["id"], c["market"], c["side"], c["line"] or 0)).fetchone()
        res = "void" if game["status"] in VOID else _result(c, game) if c["review"] == "ok" else "unreviewed"
        line = c["close_line"] if c["market"] == "prop" else close and close["line"]     # a prop's close comes from propBets
        h.db.execute("update calls set result=?, close_line=?, close_odds=?, graded_at=? where id=?",
                     (res, line, close and close["odds"], h.clock(), c["id"]))


def _result(c, g):
    hs, as_ = g["home_score"] or 0, g["away_score"] or 0
    if c["market"] == "total":
        d = (hs + as_ - c["line"]) * (1 if c["side"] == "over" else -1)
    elif c["side"] == "draw":
        return "win" if hs == as_ else "loss"
    else:
        mine, theirs = (hs, as_) if c["side"] == g["home"] else (as_, hs)
        d = mine - theirs + (c["line"] if c["market"] == "spread" else 0)
    return "win" if d > 0 else "push" if d == 0 else "loss"


def _moved(c, line, odds):
    """How far the market moved toward the call since it was made: (points, implied probability). Positive = our way."""
    prob = implied(odds) - implied(c["odds"])
    pts = 0.0
    if c["line"] is not None and line is not None:
        pts = line - c["line"] if c["side"] == "over" else c["line"] - line
    return pts, prob


def _graded(c):
    """A call as the book shows it: units at 1 risked, whether it beat the close, and (while open) where the market is now."""
    d = dict(c)
    d["units"] = payout(c["odds"]) if c["result"] == "win" else -1.0 if c["result"] == "loss" else 0.0 if c["result"] else None
    beat = None
    if c["market"] == "prop":                         # line only: ESPN carries no prop prices
        pts = None if c["close_line"] is None else (c["close_line"] - c["line"]) * (1 if c["side"] == "over" else -1)
        d["beat_close"] = None if pts is None else pts > 0
        d["since"] = None if pts is None or c["result"] is not None else {
            "pts": pts, "prob": 0.0, "verdict": "agrees" if pts > 0 else "disagrees" if pts < 0 else "flat"}
        return d
    if c["close_odds"] is not None and not c["soft"]:
        pts, prob = _moved(c, c["close_line"], c["close_odds"])
        beat = pts > 0 or (pts == 0 and prob > 0)
    d["beat_close"] = beat
    d["since"] = None
    if c["result"] is None and c["now_odds"] is not None and not c["soft"]:
        pts, prob = _moved(c, c["now_line"], c["now_odds"])
        d["since"] = {"pts": pts, "prob": round(prob, 4),
                      "verdict": "agrees" if pts > 0 or (pts == 0 and prob > 0.005) else
                                 "disagrees" if pts < 0 or (pts == 0 and prob < -0.005) else "flat"}
    return d


def _pick(c):
    """The call in plain words: "Boston -11.5", "Under 2.5", "Boston to win", "Draw"."""
    name = (c["home_name"] if c["side"] == c["home"] else c["away_name"] if c["side"] == c["away"] else "") or c["side"]
    if c["market"] == "total":
        return f"{c['side'].capitalize()} {c['line']:g}"
    if c["market"] == "prop":
        return f"{c['player']} {c['side'].capitalize()} {c['line']:g} {c['stat']}"
    if c["market"] == "spread":
        return f"{name} {c['line']:+g}"
    return "Draw" if c["side"] == "draw" else f"{name} to win"


SAME = "and (l.market!='spread' or l.line*c.line>0)"    # a spread call follows its own side of the line, not the alternate


def _calls(h, desk=None, limit=-1):     # ponytail: no cap (-1) so results stay whole; the 10 s board poll grows with the book, send totals instead if it gets slow
    """Every call with its game and the market's latest line for it: the one query the book and `call list` share."""
    rows = h.db.execute(
        "select c.*, g.name as game_name, g.start, g.status, g.home, g.away, g.home_name, g.away_name, g.home_score, "
        "g.away_score, (select line from lines l where l.game=c.game and l.market=c.market and l.side=c.side "
        f"{SAME} order by at desc limit 1) as now_line, (select odds from lines l where l.game=c.game and l.market=c.market "
        f"and l.side=c.side {SAME} order by at desc limit 1) as now_odds from calls c left join games g on g.id=c.game "
        "where ? is null or c.desk=? order by c.id desc limit ?", (desk, desk, limit))
    return [dict(_graded(c), pick=_pick(c)) for c in rows]


def book(h):
    _ensure(h)
    calls = _calls(h)
    passes = [c for c in calls if c["confidence"] == 0]   # Jack, Nov 6: every price a desk set, bet or not; never a bet
    calls = [c for c in calls if c["confidence"] != 0]
    desks = {}
    for k in LEAGUES:
        mine = [c for c in calls if c["desk"] == k]
        staff = [r["name"] for r in h.db.execute("select name from agents where team=? order by name", (k,))]
        desks[k] = {"name": NAMES[k], "agents": staff, "strategies": {n: strategy_of(h, n, k) for n in staff},
                    "calls": len(mine), "open": sum(c["result"] is None and c["review"] == "ok" for c in mine),
                    "checking": sum(c["result"] is None and c["review"] is None for c in mine),
                    "w": sum(c["result"] == "win" for c in mine), "l": sum(c["result"] == "loss" for c in mine),
                    "p": sum(c["result"] == "push" for c in mine), "pulled": sum(c["result"] == "pulled" for c in mine),
                    "units": sum(c["units"] or 0 for c in mine),
                    "graded": sum(c["beat_close"] is not None for c in mine), "beat_close": sum(bool(c["beat_close"]) for c in mine),
                    "by_conf": {str(n): _tally([c for c in mine if c["confidence"] == n]) for n in (1, 2, 3)},
                    "watching": h.db.execute("select count(*) from games where desk=? and status='STATUS_SCHEDULED' and start > ?",
                                             (k, h.clock())).fetchone()[0]}
    real = [c for c in calls if c["review"] == "ok"]
    group = lambda d: "explore" if d == "lab" else "early" if d in EARLY else "gameday"
    strat = lambda c: c["strategy"] or group(c["desk"])            # calls before Nov 1 carry their desk's
    strategies = {k: dict(_tally([c for c in real if strat(c) == k]), desks=[d for d in LEAGUES if group(d) == k])
                  for k in ("early", "gameday", "explore")}
    by_sport_strategy = {d: {k: _tally([c for c in real if c["desk"] == d and strat(c) == k]) for k in ("early", "gameday")}
                         for d in LEAGUES if d != "lab"}
    for k, d in desks.items():
        d["strategy"] = group(k)
    notes = [dict(r) for r in h.db.execute("select agent, text, at from lab_notes order by id desc limit 30")]
    return {"calls": calls, "passes": passes,
            "pass_tally": {d: _tally([c for c in passes if c["desk"] == d]) for d in LEAGUES if d != "lab"}, "desks": desks, "strategies": strategies, "by_sport_strategy": by_sport_strategy, "notes": notes,
            "activity": _activity(h)}


def _tally(cs):
    lead = [(c["start"] - c["made_at"]) / 3600 for c in cs if c.get("start")]
    return {"calls": len(cs), "units": sum(c["units"] or 0 for c in cs), "graded": sum(c["beat_close"] is not None for c in cs),
            "lead_h": sum(lead) / len(lead) if lead else None, "settled": sum(c["result"] in ("win", "loss", "push") for c in cs),
            "beat_close": sum(bool(c["beat_close"]) for c in cs), "flagged": sum(c["review"] == "flag" for c in cs),
            # Jack, Nov 1: profit is the verdict; CLV is an early gauge, props (line only, no price) kept apart
            "clv_game": _clv([c for c in cs if c["market"] != "prop"]), "clv_prop": _clv([c for c in cs if c["market"] == "prop"])}


def _clv(cs):
    return {"graded": sum(c["beat_close"] is not None for c in cs), "beat": sum(bool(c["beat_close"]) for c in cs)}


def _wake_text(text):
    """A wake as one line: its headline and the first moves it named."""
    lines = text.split("\n")
    moves = [l[2:].split(" · new on the board")[0] for l in lines if l.startswith("- ")]
    return lines[0] + (": " + "; ".join(moves[:2]) + (f" and {len(moves) - 2} more" if len(moves) > 2 else "") if moves else "")


def _activity(h, limit=80):
    """What the desks did, newest first: the hub waking them, what they said back, and the calls they logged."""
    staff = {r["name"]: r["team"] for r in h.db.execute(f"select name, team from agents where team in {tuple(LEAGUES)}")}
    if not staff:
        return []
    q = ",".join("?" * len(staff))
    out = [{"at": r["created"], "agent": r["too"], "desk": staff[r["too"]], "kind": "woken",
            "text": _wake_text(r["text"] or "")}
           for r in h.db.execute(f"select too, text, created from items where too in ({q}) and frm='hub' order by id desc limit ?",
                                 (*staff, limit))]
    out += [{"at": r["at"], "agent": r["agent"], "desk": staff[r["agent"]], "kind": "said", "text": (r["text"] or "")[:400]}
            for r in h.db.execute(f"select agent, text, at from events where agent in ({q}) and dir='out' order by id desc limit ?",
                                  (*staff, limit))]
    out += [{"at": r["made_at"], "agent": r["agent"], "desk": r["desk"], "kind": "called",
             "text": f"{_pick(r)} ({r['odds']:+d}) · {r['game_name']}"}
            for r in h.db.execute("select c.*, g.name as game_name, g.home, g.away, g.home_name, g.away_name from calls c "
                                  "left join games g on g.id=c.game order by c.id desc limit ?", (limit,))]
    return sorted(out, key=lambda e: -(e["at"] or 0))[:limit]


def manage(h, by, a):
    """`call add|list|games` from a desk agent (h.lock is held)."""
    _ensure(h)
    desk = desk_of(h, by)
    if not desk:
        raise ValueError("only a sports desk agent logs calls")
    now = h.clock()
    if a[1:2] == ["games"]:
        rows = h.db.execute("select * from games where desk=? and status='STATUS_SCHEDULED' and start > ? order by start limit 60",
                            (desk, now)).fetchall()
        return "\n".join(f"{g['id']}  {time.strftime('%a %m-%d %H:%M', time.localtime(g['start']))}  {g['name']}" for g in rows) \
            or "no upcoming games with lines yet"
    if a[1:2] == ["watch"] and desk == "lab" and len(a) == 3:
        if not re.fullmatch(r"[a-z0-9-]+/[a-z0-9.-]+", a[2]) or ".." in a[2]:
            raise ValueError("give an ESPN sport/league path, e.g. baseball/mlb or soccer/ger.1")
        owner = next((d for d, paths in LEAGUES.items() for p in paths if p.partition("?")[0] == a[2]), None)
        if owner:                     # Nov 1: lab polls relabelled the NBA desk's games as lab's and blanked its board
            raise ValueError(f"{a[2]} is the {NAMES[owner]} desk's league: pick one no sport desk covers")
        h.db.execute("insert or ignore into lab_paths(path, at) values(?,?)", (a[2], now))
        h.db.execute("update desk_state set next_poll=0 where desk='lab'")
        return f"watching {a[2]}: its games with DraftKings lines show in `fleet call games` after the next poll (~1 min)"
    if a[1:2] == ["note"] and desk == "lab" and len(a) >= 3:
        h.db.execute("insert into lab_notes(agent, text, at) values(?,?,?)", (by, " ".join(a[2:]), now))
        return "noted"
    if a[1:2] == ["props"] and len(a) == 3:
        rows = h.db.execute("select * from props where game=? order by player, stat, side='under'", (a[2],)).fetchall()
        if not rows:
            return "no DraftKings props with prices on the hub for that game yet: log its game lines"
        by = {}
        for r in rows:
            by.setdefault((r["player"], r["stat"]), []).append(
                f"{r['side'].capitalize()} {r['line']:g}" + (f" ({r['odds']:+d})" if r["odds"] else " (no price yet)"))
        return "\n".join(f"{p} · {st} · " + " · ".join(v) for (p, st), v in by.items())
    if a[1:2] == ["list"]:
        rows = _calls(h, desk, 30)
        return "\n".join(f"#{c['id']} {c['game_name']} {c['pick']} ({c['odds']:+d}) · "
                         f"{c['result'] or 'open'}" + (f" {c['units']:+.2f}u" if c["units"] is not None else "")
                         for c in rows) or "no calls yet"     # Jack, Nov 1: agents bet to win; CLV stays on the dashboard
    if a[1:2] == ["review"] and len(a) == 5 and a[3] in ("ok", "flag"):
        c = h.db.execute("select * from calls where id=?", (a[2].lstrip("#"),)).fetchone()
        if not c:
            raise ValueError(f"no call {a[2]}")
        if c["desk"] == desk:
            raise ValueError("another desk reviews your calls; you review theirs")
        g = h.db.execute("select * from games where id=?", (c["game"],)).fetchone()
        if not g or g["status"] != "STATUS_SCHEDULED" or now >= g["start"]:
            raise ValueError("that game has started: reviews count only before it")       # hindsight can't change a result
        h.db.execute("update calls set review=?, review_by=?, review_note=? where id=?", (a[3], by, a[4], c["id"]))
        if a[3] == "ok" and c["result"] == "pulled":
            h.db.execute("update calls set result=null, graded_at=null where id=?", (c["id"],))
            return f"call #{c['id']} confirmed and back in the book"
        if a[3] == "flag" and c["result"] is None:
            # Jack, Oct 27: a call built on wrong facts isn't tracked. Only before the game: a flag in hindsight can't
            # erase a loss
            h.db.execute("update calls set result='pulled', graded_at=? where id=?", (now, c["id"]))
            h._deliver_to(c["agent"], f"Call #{c['id']} pulled", f"{by} flagged your call #{c['id']} on {g['name']} "
                          f"({_pick(dict(c, home=g['home'], away=g['away'], home_name=g['home_name'], away_name=g['away_name']))}): "
                          f"{a[4]}\nIt's out of the book. If you think {by} is wrong, make your case: `fleet ask \"{by}\" "
                          "\"<why>\"`; they can confirm it again. Or, if the corrected facts still give you a view, log a "
                          "new call before the game.")
            return f"call #{c['id']} flagged and pulled from the book"
        return f"call #{c['id']} marked {a[3]}"
    if a[1:2] == ["prop"] and len(a) == 12:
        gid, player, stat, side, line, odds, fair, conf, why, kill = a[2:]
        market = "prop"
    elif a[1:2] == ["add"] and len(a) == 11:
        gid, market, side, line, odds, fair, conf, why, kill = a[2:]
        player = stat = None
    else:
        raise ValueError('use: fleet call add <game id> spread|total|moneyline <side> <line|-> <odds> <fair odds> '
                         '<confidence 0-3> "<why>" "<what would make it wrong>" | fleet call prop <game id> "<player>" '
                         '<stat> over|under <line> <odds> <fair odds> <confidence 0-3> "<why>" "<what would make it wrong>" | '
                         'fleet call review <id> ok|flag "<one line>" | fleet call watch <sport/league> | '
                         'fleet call note "<finding>" (explorer) | fleet call list | fleet call games')
    g = h.db.execute("select * from games where id=? and desk=?", (gid, desk)).fetchone()
    if not g:
        raise ValueError(f"no {NAMES[desk]} game {gid}: see `fleet call games`")
    if g["status"] != "STATUS_SCHEDULED" or now >= g["start"]:
        raise ValueError(f"{g['name']} has started: calls are logged before the game only")
    strat = strategy_of(h, by, desk)
    lead = g["start"] - now
    if strat == "early" and lead < STRATEGY_SPLIT:
        raise ValueError(f"you bet early: calls go in {STRATEGY_SPLIT // 3600} h or more before the start, and {g['name']} "
                         f"starts in {lead / 3600:.1f} h. Your game-day partner covers it")
    if strat == "gameday" and lead > STRATEGY_SPLIT:
        raise ValueError(f"you bet on game day: calls go in inside {STRATEGY_SPLIT // 3600} h of the start, and {g['name']} "
                         f"starts in {lead / 3600:.1f} h. It comes back to you then")
    if any(n in (g["home_name"] or "") + "|" + (g["away_name"] or "") for n in ILLINOIS):
        raise ValueError("DraftKings Illinois takes no online bets on Illinois college teams")
    if market == "prop":
        stats = PROPS.get(_family(desk), {})
        if stat not in stats or side not in ("over", "under") or not player.strip():
            raise ValueError(f"{NAMES[desk]} props: fleet call prop <game id> \"<player as ESPN spells it>\" "
                             f"{'|'.join(stats) or '(none on this desk)'} over|under <line> …")
    else:
        sides = {"spread": (g["home"], g["away"]), "moneyline": (g["home"], g["away"], "draw"), "total": ("over", "under")}
        if market not in sides or side not in sides[market] or (side == "draw" and desk != "soccer"):
            raise ValueError(f"{market} sides here: {', '.join(sides.get(market, ('spread', 'total', 'moneyline')))}")
    ln = None if market == "moneyline" else _num(line)
    if market != "moneyline" and ln is None:
        raise ValueError("give the line you're taking, e.g. -3.5 or 47.5")
    o, f = _odds(odds), _odds(fair)
    if not o or not f or conf not in ("0", "1", "2", "3"):
        raise ValueError("odds and fair odds are American (-110, +150); confidence is 0 (a pass), 1, 2 or 3")
    edge = implied(f) - implied(o)
    if edge <= 0 and conf != "0":
        raise ValueError(f"your fair price {f:+d} says {o:+d} is no bargain: log a call only where you think the price beats it")
    if edge > MAX_EDGE:
        raise ValueError(f"fair {f:+d} against {o:+d} claims a {edge:.0%} edge: real edges are a few points. Recheck your numbers")
    feed = None if market == "prop" else h.db.execute(
        "select line, odds from lines where game=? and market=? and side=? order by (market!='spread' or line*?>0) desc, "
        "at desc limit 1", (gid, market, side, ln or 0)).fetchone()     # a softened spread may cross zero: -0.5 → +0.5
    listed = h.db.execute("select line, odds from props where game=? and lower(player)=lower(?) and stat=? and side=? and "
                          "odds is not null", (gid, player, stat, side)).fetchall() if market == "prop" else []
    if market == "prop" and not listed:           # Jack, Nov 6: no browser checks, so no hub price means no prop call
        raise ValueError(f"the hub has no DraftKings price for {player} {side} {stat}: see `fleet call props {gid}`")
    if listed and not any(r["line"] == ln and (not r["odds"] or abs(implied(o) - implied(r["odds"])) <= 0.04) for r in listed):
        raise ValueError(f"DraftKings shows {player} {stat} " + ", ".join(
            f"{side} {r['line']:g}" + (f" ({r['odds']:+d})" if r["odds"] else "") for r in listed)
            + " on the hub's feed: log one of those at the price you can actually get")
    soft = 0                                  # Jack, Nov 6: no alt lines (they earned ~+$2.50 on 278 picks vs +$17.58 main)
    if feed and ((ln is not None and abs(ln - feed["line"]) > 0.5) or abs(implied(o) - implied(feed["odds"])) > 0.04):
        raise ValueError(f"DraftKings shows {_show(market, side, feed['line'], feed['odds'])} on the hub's feed (read every "
                         "5 minutes): log the price you can actually get")
    cid = h.db.execute("insert into calls(desk, agent, game, market, side, line, odds, fair_odds, confidence, reason, kill, "
                       "made_at, player, stat, soft, strategy) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (desk, by, gid, market, side, ln, o, f, int(conf), why, kill, now, player, stat, soft, strat)).lastrowid
    if conf in ("0", "1"):            # Jack, Nov 1: more volume; a lean counts without tying up another desk's review
        h.db.execute("update calls set review='ok', review_by=?, review_note='graded without review' where id=?",
                     ("pass" if conf == "0" else "lean", cid))
    pick = _pick({"market": market, "side": side, "line": ln, "player": player, "stat": stat, "home": g["home"],
                  "away": g["away"], "home_name": g["home_name"], "away_name": g["away_name"]})
    if conf == "0":
        return f"pass #{cid} logged: {g['name']} {pick} ({o:+d}), your fair {f:+d}. Not a bet; the hub scores the price."
    if conf == "1":
        return f"call #{cid} logged as a lean: {g['name']} {pick} ({o:+d}). It counts now."
    return (f"call #{cid} logged as a proposal: {g['name']} {pick} ({o:+d}). Another desk checks it now; it "
            "counts once they confirm it, before the game.")
