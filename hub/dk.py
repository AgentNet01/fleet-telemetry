"""DraftKings' own odds feed: player props for every desk (Jack, Nov 6: "write a script for DraftKings", run from the hub
PC). The hub reads the JSON the sportsbook site loads; plain HTTP gets a 403, so it goes through curl_cffi as Chrome.
Read-only, no login, one desk per tick."""
import calendar
import re
import time

BASE = "https://sportsbook-nash.draftkings.com/api/sportscontent/dkusil/v1/leagues/"
LEAGUE = {"nba": 42648, "cbb": 92483, "nfl": 88808, "cfb": 87637, "nhl": 42133, "soccer": 40253}
# desk -> [(category, subcategory, stat)]: the main O/U line where DraftKings has one, else its "N+" ladder (college, soccer)
SUBS = {
    "nba": [(1215, 12488, "points"), (1218, 12497, "threes"), (1216, 12492, "rebounds"), (1217, 12495, "assists"),
            (583, 5001, "pra"), (583, 9973, "pa"), (583, 9974, "ra"), (583, 9976, "pr")],
    "cbb": [(1215, 16477, "points"), (1218, 16480, "threes"), (1216, 16479, "rebounds"), (1217, 16478, "assists"),
            (583, 16481, "pa"), (583, 16482, "pr"), (583, 16483, "pra")],
    "nfl": [(1000, 9524, "pass_yds"), (1000, 9525, "pass_tds"), (1000, 9522, "completions"), (1000, 15937, "interceptions"),
            (1342, 14114, "rec_yds"), (1342, 14115, "receptions"), (1001, 9514, "rush_yds"), (1001, 9518, "rush_att"),
            (1001, 9523, "rush_rec_yds")],
    "cfb": [(1000, 16569, "pass_yds"), (1000, 16568, "pass_tds"), (1000, 16889, "completions"), (1342, 16570, "rec_yds"),
            (1342, 16821, "receptions"), (1001, 16571, "rush_yds"), (1001, 16820, "rush_att")],
    "nhl": [(1189, 12040, "shots"), (1675, 16213, "points"), (1676, 16215, "assists"), (1064, 16550, "saves")],
    "soccer": [(1113, 16868, "shots"), (1113, 16861, "sog"), (1714, 16863, "assists"), (1567, 18346, "saves")],
}
_session = None


def fetch(url):
    global _session
    if _session is None:
        from curl_cffi import requests as rq
        _session = rq.Session(impersonate="chrome")
    r = _session.get(url, timeout=20)
    r.raise_for_status()
    return r.json()


def _odds(s):
    try:
        return int(str(s).replace("−", "-").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _player(sel):
    p = next((x for x in sel.get("participants") or [] if x.get("type") == "Player"), None)
    if not p:
        return None
    seo = p.get("seoIdentifier") or ""
    return seo if " " in seo else p.get("name")      # "Tyrone Riley IV" where the label says "Tyrone Riley"


def props(desk, get=fetch):
    """(events, rows) for a desk: events {dk id: (start, home name, home short, away name, away short)}, rows
    [(dk event id, player, stat, side, line, odds)]. Raises if any read fails, so a partial board is never stored."""
    lid, events, rows = LEAGUE[desk], {}, []
    for cat, sub, stat in SUBS[desk]:
        j = get(f"{BASE}{lid}/categories/{cat}/subcategories/{sub}")
        for e in j.get("events") or []:
            side = {p.get("venueRole"): p for p in e.get("participants") or []}
            h, a = side.get("Home") or {}, side.get("Away") or {}
            events[e["id"]] = (calendar.timegm(time.strptime(e["startEventDate"][:19], "%Y-%m-%dT%H:%M:%S")),
                               h.get("name") or "", (h.get("metadata") or {}).get("shortName") or "",
                               a.get("name") or "", (a.get("metadata") or {}).get("shortName") or "")
        markets = {m["id"]: m for m in j.get("markets") or [] if m.get("subcategoryId") == sub}
        for s in j.get("selections") or []:
            m, who, odds = markets.get(s.get("marketId")), _player(s), _odds((s.get("displayOdds") or {}).get("american"))
            if not m or not who or odds is None:
                continue
            if s.get("outcomeType") in ("Over", "Under") and s.get("points") is not None and s.get("main") is not False:
                rows.append((m["eventId"], who, stat, s["outcomeType"].lower(), float(s["points"]), odds))
            elif s.get("milestoneValue") is not None:           # "N+" is Over N-0.5
                rows.append((m["eventId"], who, stat, "over", float(s["milestoneValue"]) - 0.5, odds))
    return events, rows


def _words(s):
    return set(re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()) - {"st", "state", "university", "fc", "the", "of"}


def _side(dk_name, dk_short, abbr, name):
    if (dk_short and dk_short.lower() == (abbr or "").lower()) or _words(dk_name) == _words(name):
        return 2
    return 1 if _words(dk_name) & _words(name) else 0


def match(events, games):
    """{dk event id: game id}: the hub game within 3 h of the DraftKings start whose teams match best: one team exact is
    enough (DraftKings says WAS and UTA where ESPN says WSH and UTAH)."""
    out = {}
    for eid, (start, hn, hs, an, as_) in events.items():
        best = None
        for g in games:
            if abs(g["start"] - start) > 3 * 3600:
                continue
            h, a = _side(hn, hs, g["home"], g["home_name"]), _side(an, as_, g["away"], g["away_name"])
            if h + a >= 2 and (not best or (h + a, -abs(g["start"] - start)) > best[0]):
                best = ((h + a, -abs(g["start"] - start)), g["id"])
        if best:
            out[eid] = best[1]
    return out
