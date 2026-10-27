"""Floor 2, the sports desk (Jack, Oct 26): six Muse agents, one per sport, find positions on DraftKings lines.

Nobody bets. The hub reads each sport's DraftKings lines from ESPN's public scoreboard feed every 5 minutes, give or
take 90 s, and keeps the history. A desk is woken only when its board changes enough to matter (new games, a real
move), plus a sweep every 3 h in the daytime. A desk logs a call with `fleet call add` before the game; the hub keeps
the last pre-start line as the close, reads the final score and grades the call itself, so the book always says
whether following the desk would have made money. Nothing here ever requests DraftKings itself.
"""
import calendar
import json
import random
import time
import urllib.request

LEAGUES = {"nba": ["basketball/nba"], "nfl": ["football/nfl"], "cfb": ["football/college-football?groups=80"],
           "nhl": ["hockey/nhl"], "cbb": ["basketball/mens-college-basketball?groups=50"],
           "soccer": ["soccer/eng.1", "soccer/uefa.champions"]}
NAMES = {"nba": "NBA", "nfl": "NFL", "cfb": "College football", "nhl": "NHL", "cbb": "College basketball", "soccer": "Soccer"}
FEED = "https://site.api.espn.com/apis/site/v2/sports/"
POLL, JITTER = 300, 90                  # Jack: every five minutes, give or take 90 seconds
WAKE_GAP = 20 * 60                      # at most one wake per desk this often; moves in between are batched
SWEEP = 45 * 60                         # Jack, Oct 27: a research round this often when nothing has moved, any hour
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
    if market == "total":
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
        h._sports_ready = True


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
                due.append(desk)
    got = {}
    for desk in due:
        events = []
        for path in LEAGUES[desk]:
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
    staff = [r["name"] for r in h.db.execute("select name from agents where team=? and state='active'", (desk,))]
    pending = json.loads(st["pending"] or "[]")
    last = max(st["last_wake"] or 0, st["last_sweep"] or 0)
    if pending and now - (st["last_wake"] or 0) >= WAKE_GAP:
        news, rest = [m for m in pending if "new on the board" in m], [m for m in pending if "new on the board" not in m]
        body = "\n".join(f"- {m}" for m in (rest + news)[:40]) + (f"\n- …and {len(pending) - 40} more" if len(pending) > 40 else "")
        for n in staff:
            h._deliver_to(n, f"{NAMES[desk]} lines moved", "DraftKings lines on your board changed:\n" + body + "\n\n" + NEXT)
        h.db.execute("update desk_state set pending='[]', last_wake=? where desk=?", (now, desk))
    elif not pending and now - last >= SWEEP:
        games = h.db.execute("select g.*, (select line from lines l where l.game=g.id and l.market='spread' and l.side=g.home "
                             "order by at desc limit 1) as sp, (select line from lines l where l.game=g.id and l.market='total' "
                             "and l.side='over' order by at desc limit 1) as tot from games g where desk=? and "
                             "status='STATUS_SCHEDULED' and start > ? order by start limit 12", (desk, now)).fetchall()
        if not games:
            return
        board = "\n".join(f"- {g['id']} {g['name']} {time.strftime('%a %H:%M', time.localtime(g['start']))}"
                          + (f" · {g['home']} {g['sp']:+g}" if g["sp"] is not None else "")
                          + (f" · total {g['tot']:g}" if g["tot"] is not None else "") for g in games)
        for n in staff:
            h._deliver_to(n, f"{NAMES[desk]} research round", "Nothing big has moved since your last look. Pick one or two of "
                          "these and dig in properly: injuries and lineups, rest and travel, weather, matchups, recent form, "
                          "what the market might be missing. Then log a position or pass, and say why in one line.\n"
                          + board + "\n\n" + NEXT)
        h.db.execute("update desk_state set last_sweep=? where desk=?", (now, desk))


NEXT = ("Confirm the exact price on DraftKings (logged out) before you log anything. If it's worth a position: "
        "`fleet call add <game id> spread|total|moneyline <side> <line, or - for moneyline> <DraftKings odds> <your fair odds> "
        "<confidence 1-3> \"<why>\" \"<what would make it wrong>\"`. Game ids: `fleet call games`. Passing is fine.")


def _grade(h, game):
    for c in h.db.execute("select * from calls where game=? and result is null", (game["id"],)).fetchall():
        close = h.db.execute("select line, odds from lines where game=? and market=? and side=? order by at desc limit 1",
                             (game["id"], c["market"], c["side"])).fetchone()
        res = "void" if game["status"] in VOID else _result(c, game)
        h.db.execute("update calls set result=?, close_line=?, close_odds=?, graded_at=? where id=?",
                     (res, close and close["line"], close and close["odds"], h.clock(), c["id"]))


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
    if c["close_odds"] is not None:
        pts, prob = _moved(c, c["close_line"], c["close_odds"])
        beat = pts > 0 or (pts == 0 and prob > 0)
    d["beat_close"] = beat
    d["since"] = None
    if c["result"] is None and c["now_odds"] is not None:
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
    if c["market"] == "spread":
        return f"{name} {c['line']:+g}"
    return "Draw" if c["side"] == "draw" else f"{name} to win"


def _calls(h, desk=None, limit=500):
    """Every call with its game and the market's latest line for it: the one query the book and `call list` share."""
    rows = h.db.execute(
        "select c.*, g.name as game_name, g.start, g.status, g.home, g.away, g.home_name, g.away_name, g.home_score, "
        "g.away_score, (select line from lines l where l.game=c.game and l.market=c.market and l.side=c.side "
        "order by at desc limit 1) as now_line, (select odds from lines l where l.game=c.game and l.market=c.market "
        "and l.side=c.side order by at desc limit 1) as now_odds from calls c left join games g on g.id=c.game "
        "where ? is null or c.desk=? order by c.id desc limit ?", (desk, desk, limit))
    return [dict(_graded(c), pick=_pick(c)) for c in rows]


def book(h):
    _ensure(h)
    calls = _calls(h)
    desks = {}
    for k in LEAGUES:
        mine = [c for c in calls if c["desk"] == k]
        desks[k] = {"name": NAMES[k], "agents": [r["name"] for r in h.db.execute("select name from agents where team=?", (k,))],
                    "calls": len(mine), "open": sum(c["result"] is None for c in mine),
                    "w": sum(c["result"] == "win" for c in mine), "l": sum(c["result"] == "loss" for c in mine),
                    "p": sum(c["result"] == "push" for c in mine),
                    "units": sum(c["units"] or 0 for c in mine),
                    "graded": sum(c["beat_close"] is not None for c in mine), "beat_close": sum(bool(c["beat_close"]) for c in mine),
                    "watching": h.db.execute("select count(*) from games where desk=? and status='STATUS_SCHEDULED' and start > ?",
                                             (k, h.clock())).fetchone()[0]}
    return {"calls": calls, "desks": desks, "activity": _activity(h)}


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
           for r in h.db.execute(f"select too, text, created from items where too in ({q}) and frm='hub' and (text like '% lines moved%' "
                                 "or text like '% sweep%') order by id desc limit ?",
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
    if a[1:2] == ["list"]:
        rows = _calls(h, desk, 30)
        return "\n".join(f"#{c['id']} {c['game_name']} {_show(c['market'], c['side'], c['line'], c['odds'])} · "
                         f"{c['result'] or 'open'}" + (f" {c['units']:+.2f}u" if c["units"] is not None else "") +
                         ("" if c["beat_close"] is None else " · beat the close" if c["beat_close"] else " · missed the close")
                         for c in rows) or "no calls yet"
    if a[1:2] != ["add"] or len(a) != 11:
        raise ValueError('use: fleet call add <game id> spread|total|moneyline <side> <line|-> <odds> <fair odds> '
                         '<confidence 1-3> "<why>" "<what would make it wrong>" | fleet call list | fleet call games')
    gid, market, side, line, odds, fair, conf, why, kill = a[2:]
    g = h.db.execute("select * from games where id=? and desk=?", (gid, desk)).fetchone()
    if not g:
        raise ValueError(f"no {NAMES[desk]} game {gid}: see `fleet call games`")
    if g["status"] != "STATUS_SCHEDULED" or now >= g["start"]:
        raise ValueError(f"{g['name']} has started: calls are logged before the game only")
    if desk in ("cfb", "cbb") and any(n in (g["home_name"] or "") + "|" + (g["away_name"] or "") for n in ILLINOIS):
        raise ValueError("DraftKings Illinois takes no online bets on Illinois college teams")
    sides = {"spread": (g["home"], g["away"]), "moneyline": (g["home"], g["away"], "draw"), "total": ("over", "under")}
    if market not in sides or side not in sides[market] or (side == "draw" and desk != "soccer"):
        raise ValueError(f"{market} sides here: {', '.join(sides.get(market, ('spread', 'total', 'moneyline')))}")
    ln = None if market == "moneyline" else _num(line)
    if market != "moneyline" and ln is None:
        raise ValueError("give the line you're taking, e.g. -3.5 or 47.5")
    o, f = _odds(odds), _odds(fair)
    if not o or not f or conf not in ("1", "2", "3"):
        raise ValueError("odds and fair odds are American (-110, +150); confidence is 1, 2 or 3")
    cid = h.db.execute("insert into calls(desk, agent, game, market, side, line, odds, fair_odds, confidence, reason, kill, made_at) "
                       "values(?,?,?,?,?,?,?,?,?,?,?,?)", (desk, by, gid, market, side, ln, o, f, int(conf), why, kill, now)).lastrowid
    return f"call #{cid} logged: {g['name']} {_show(market, side, ln, o)}. The hub records the close and grades it."
