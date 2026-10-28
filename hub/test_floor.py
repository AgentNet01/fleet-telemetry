"""Floor 2, the sports desk: the hub watches DraftKings lines, wakes a desk on a move, grades its calls itself,
and the dashboard's elevator shows that floor apart from the Etsy company.

    python3 test_floor.py book          # a call is logged before start only; the hub keeps the close and grades it
    python3 test_floor.py watch         # a real move wakes its desk once (batched); drift and floor 1 stay quiet
    python3 test_floor.py board_speed   # the board builds fast on live-sized data (scratchpad hub-debug.db)
    python3 test_floor.py elevator      # Floor 2 shows only the desk agents and the Book; Floor 1 the rest
"""
import os
import sys
import tempfile
import time

import hub
from test_autonomy import new_hub

HOUR = 3600
DEBUG_DB = os.environ.get("HUB_DEBUG_DB", "/private/tmp/claude-501/-Users-jacc-Desktop-Fleet/"
                          "a4e0a025-6b23-477a-9688-8d414af85137/scratchpad/hub-debug.db")


def iso(t):
    return time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime(t))


def event(eid, away, home, start, status="STATUS_SCHEDULED", spread=None, total=None, ml=None, score=None):
    """One game the way ESPN's scoreboard feed shows it (shape seen on Oct 26: provider DraftKings, open/close per side).
    spread = (home line, home odds, away odds); total = (line, over odds, under odds); ml = (home odds, away odds)."""
    odds = {"provider": {"name": "DraftKings"}}
    now = lambda d: {"open": d, "close": d}
    if spread:
        hl, ho, ao = spread
        odds["pointSpread"] = {"home": now({"line": f"{hl:+g}", "odds": str(ho)}), "away": now({"line": f"{-hl:+g}", "odds": str(ao)})}
    if total:
        tl, oo, uo = total
        odds["total"] = {"over": now({"line": f"o{tl:g}", "odds": str(oo)}), "under": now({"line": f"u{tl:g}", "odds": str(uo)})}
    if ml:
        odds["moneyline"] = {"home": now({"odds": str(ml[0])}), "away": now({"odds": str(ml[1])})}
    hs, as_ = score or (0, 0)
    return {"id": eid, "date": iso(start), "name": f"{away} at {home}", "competitions": [{
        "status": {"type": {"name": status}},
        "competitors": [{"homeAway": "home", "team": {"abbreviation": home}, "score": str(hs)},
                        {"homeAway": "away", "team": {"abbreviation": away}, "score": str(as_)}],
        "odds": [] if status == "STATUS_FINAL" else [odds]}]}


def feed(h, **by_sport):
    """The guess at how the hub is handed a feed: `h.sports_fetch(url) -> json`. by_sport: nba=[events], ..."""
    def fetch(url):
        for sport, path in (("nba", "basketball/nba"), ("nfl", "football/nfl"), ("nhl", "hockey/nhl")):
            if "/" + path + "/" in url:
                return {"events": by_sport.get(sport, [])}
        return {"events": []}
    h.sports_fetch = fetch


def poll(h, clock):
    clock.go(400)                              # past the longest jittered poll gap (5 min + 90 s)
    h.tick(); h.tick()


def book():
    """Jack, Oct 26: "tracking them so I can see whether or not it would have made money regardless of whether I take
    it". A call is logged before the game only; the hub keeps the closing line and grades it from the final score."""
    h, muse, clock = new_hub("Cee", "Ada", "Nb", "Nh")
    h.seat("ceo", "Cee")
    assert "nba" in h.manage("Cee", "team Nb nba")
    h.manage("Cee", "team Nh nhl")                          # the desk that checks Nb's calls
    start = clock() + 3 * HOUR
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-11.5, -110, -110), total=(222.5, -110, -110)),
                 event("g2", "DET", "NY", start, spread=(-15, -110, -110))])
    poll(h, clock)
    try:
        h.manage("Nb", 'call add g1 spread BOS -11.5 -110 -125 2 "Brooklyn on a back-to-back" "Tatum sits"')
        h.manage("Nb", 'call add g1 total under 222.5 -110 -120 1 "two slow defenses" "pace spikes"')
        h.manage("Nb", 'call add g1 total over 222.5 -110 -120 1 "the other read" "pace dies"')
        h.manage("Nb", 'call add g2 spread NY -15 -110 -120 1 "Detroit is cold" "garbage time"')
    except (ValueError, KeyError, PermissionError) as e:
        raise AssertionError(f"book: unknown command ({e})")
    confirm(h, "Nh")
    try:
        h.manage("Ada", 'call add g1 spread BOS -11.5 -110 -125 2 "x" "y"')
        raise AssertionError("book: a floor-1 agent logged a sports call")
    except ValueError:
        pass
    # the market moves our way before tip: BOS to -13, total down to 220.5
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-13, -110, -110), total=(220.5, -110, -110)),
                 event("g2", "DET", "NY", start, spread=(-15, -110, -110))])
    poll(h, clock)
    clock.go(3 * HOUR)
    feed(h, nba=[event("g1", "BKN", "BOS", start, status="STATUS_IN_PROGRESS")])
    poll(h, clock)
    try:
        h.manage("Nb", 'call add g1 spread BKN 13 -110 -105 1 "x" "y"')
        raise AssertionError("book: a call was logged after tip-off")
    except ValueError:
        pass
    feed(h, nba=[event("g1", "BKN", "BOS", start, status="STATUS_FINAL", score=(120, 105)),
                 event("g2", "DET", "NY", start, status="STATUS_FINAL", score=(115, 100))])
    poll(h, clock)
    b = h.board()["book"]
    calls = {(c["market"], c["side"]): c for c in b["calls"]}
    sp, un, ov, ny = calls[("spread", "BOS")], calls[("total", "under")], calls[("total", "over")], calls[("spread", "NY")]
    # worked by hand: BOS won by 15, 15 - 11.5 > 0 → win, +100/110 units; closed -13, so -11.5 beat it by 1.5
    assert (sp["result"], round(sp["units"], 3), sp["close_line"], sp["beat_close"]) == ("win", 0.909, -13.0, True), sp
    # total 225 over 222.5 → the under lost a unit; closed 220.5, so 222.5 on the under beat the close by 2
    assert (un["result"], un["units"], un["close_line"], un["beat_close"]) == ("loss", -1.0, 220.5, True), un
    # the over won (225 > 222.5) but the close fell to 220.5, so over 222.5 got a worse number than the close
    assert (ov["result"], round(ov["units"], 3), ov["beat_close"]) == ("win", 0.909, False), ov
    # NY won by exactly 15 laying 15: a push, no units either way
    assert (ny["result"], ny["units"]) == ("push", 0.0), ny
    d = b["desks"]["nba"]
    assert (d["w"], d["l"], d["p"], round(d["units"], 3), d["beat_close"], d["graded"]) == (2, 1, 1, 0.818, 2, 4), d
    # Jack, Oct 27: judge the desk's judgment. Its one confidence-2 call won and beat the close; of its three leans, one
    # won (+0.909), one lost, one pushed, and one (the under) beat the close
    by = d["by_conf"]
    assert (by["2"]["calls"], round(by["2"]["units"], 3), by["2"]["beat_close"]) == (1, 0.909, 1), by
    assert (by["1"]["calls"], round(by["1"]["units"], 3), by["1"]["beat_close"], by["1"]["graded"]) == (3, -0.091, 1, 3), by
    print("book OK")


def watch():
    """Jack, Oct 26: "continuously looking and searching for lines… waking up every so often or when lines change".
    A real move wakes its desk, once and batched; a drift doesn't; no floor-1 agent is ever woken by lines."""
    h, muse, clock = new_hub("Cee", "Ada", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    start = clock() + 10 * HOUR
    told = lambda n, s: [m for m in muse.sent.get(n, []) if s in m and "lines moved" in m]     # wakes, not research rounds
    odd = event("g0", "LAL", "UTAH", start, spread=(-2, -110, -110))
    odd["competitions"][0]["odds"].insert(0, None)      # seen live Oct 26: one game's odds list held a null
    feed(h, nba=[odd, event("g1", "BKN", "BOS", start, spread=(-11.5, -110, -110))])
    poll(h, clock)
    assert told("Nb", "BOS -11.5"), f"watch: no sports module, or the opener didn't reach its desk: {muse.sent.get('Nb')}"
    assert told("Nb", "UTAH -2"), "watch: a game with a null in its odds list lost its lines"
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-12, -110, -110))])
    clock.go(HOUR); poll(h, clock)
    assert not told("Nb", "BOS -12"), "watch: half a point of drift woke the desk"
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-13, -110, -110))])
    poll(h, clock)
    assert len(told("Nb", "BOS -13")) == 1, f"watch: a 1.5-point move should wake the desk once: {muse.sent.get('Nb')}"
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-14.5, -110, -110))])
    poll(h, clock)
    assert not told("Nb", "BOS -14.5"), "watch: a second move inside 20 minutes woke the desk again"
    clock.go(20 * 60); poll(h, clock)
    assert len(told("Nb", "BOS -14.5")) == 1, f"watch: the held move never arrived: {muse.sent.get('Nb')}"
    assert not told("Ada", "BOS") and not told("Cee", "BOS"), "watch: lines reached a floor-1 agent"
    print("watch OK")


def board_speed():
    """Oct 26: the board took 8-12 s on the PC and the office sat blank until it arrived."""
    import shutil
    from test_autonomy import ActiveMuse
    from test_hub import Clock
    work = os.path.join(tempfile.mkdtemp(), "hub.db")
    shutil.copy(DEBUG_DB, work)
    h = hub.Hub(work, ActiveMuse(), Clock(), evidence_ok=lambda link: True)
    h.board()                                  # first call warms sqlite's page cache, like a running hub
    t = time.time(); b = h.board(); took = time.time() - t
    assert sum(len(j["tasks"]) for p in b["products"] for j in p["projects"]) > 9000, "board_speed: live-sized data"
    assert took < 0.5, f"board_speed: board took {took:.2f}s"
    print(f"board_speed OK ({took:.2f}s)")


def elevator():
    """Jack, Oct 26: "click an elevator button and go to the other floor… overview page/office would be the exact same"."""
    import threading
    from playwright.sync_api import sync_playwright
    from test_ui import PASSWORD, seeded
    h, srv, url = seeded()
    for n in ("Nb", "Nf"):
        h.add_agent(n, "muse")
    h.manage("dot", "team Nb nba"); h.manage("dot", "team Nf nfl")
    clock = h.clock
    feed(h, nba=[event("g1", "BKN", "BOS", clock() + 3 * HOUR, spread=(-11.5, -110, -110))])
    poll(h, clock)
    try:
        h.manage("Nb", 'call add g1 spread BOS -11.5 -110 -125 2 "back-to-back" "Tatum sits"')
    except (ValueError, KeyError, PermissionError) as e:
        raise AssertionError(f"elevator: no Floor 2 button (no sports desk yet: {e})")
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(viewport={"width": 1440, "height": 900},
                                             http_credentials={"username": "jack", "password": PASSWORD})
        page.goto(url)
        page.wait_for_function("window.Office3D && Office3D.debug.state().ready", timeout=60000)
        drawn = lambda: sorted(page.evaluate("Office3D.debug.state().rigs"))
        page.wait_for_function("Office3D.debug.state().rigs.length > 0")
        assert "Ada" in drawn() and "Nb" not in drawn(), f"elevator: floor 1 should hold the Etsy agents only: {drawn()}"
        btn = page.get_by_role("button", name="Floor 2")
        if not btn.count():
            raise AssertionError("elevator: no Floor 2 button")
        btn.click()
        page.wait_for_function("!Office3D.debug.state().rigs.includes('Ada')", timeout=10000)
        assert drawn() == ["Nb", "Nf"], f"elevator: floor 2 should hold the desk agents only: {drawn()}"
        bk = page.get_by_role("region", name="Book")
        assert bk.is_visible() and "BOS" in bk.inner_text() and "NBA" in bk.inner_text().upper(), "elevator: no Book with the call"
        page.get_by_role("button", name="Floor 1").click()
        page.wait_for_function("Office3D.debug.state().rigs.includes('Ada')", timeout=10000)
        assert "Nb" not in drawn(), f"elevator: back on floor 1 the desk agents left: {drawn()}"
    srv.shutdown()
    print("elevator OK")


def pages():
    """Jack, Oct 27: "I want to be able to see how bets are doing… are they making good decisions… informational
    digestible". Floor 2 has its own menu; an open position says in plain words whether the market has moved its way."""
    from playwright.sync_api import sync_playwright
    from test_ui import PASSWORD, seeded
    h, srv, url = seeded()
    h.add_agent("Nb", "muse"); h.manage("dot", "team Nb nba")
    clock = h.clock; start = clock() + 3 * HOUR
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-11.5, -110, -110)), event("g2", "DET", "NY", start, spread=(-3.5, -110, -110))])
    poll(h, clock)
    h.manage("Nb", 'call add g1 spread BOS -11.5 -110 -125 2 "Brooklyn on a back-to-back" "Tatum sits"')
    h.manage("Nb", 'call add g2 spread NY -3.5 -110 -120 1 "Pistons travel" "Brunson out"')
    h.add_agent("Nh", "muse"); h.manage("dot", "team Nh nhl"); confirm(h, "Nh")
    # after the calls: Boston's number grows (the market agrees), New York's shrinks (it disagrees)
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-13, -110, -110)), event("g2", "DET", "NY", start, spread=(-2, -110, -110))])
    poll(h, clock)
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(viewport={"width": 1440, "height": 900},
                                             http_credentials={"username": "jack", "password": PASSWORD})
        page.goto(url)
        page.wait_for_function("window.Office3D && Office3D.debug.state().ready", timeout=60000)
        page.get_by_role("button", name="Floor 2").click()
        page.get_by_role("button", name="Menu").first.click()
        tabs = page.get_by_role("tab")
        names = [t.inner_text().strip() for t in tabs.all() if t.is_visible()]
        if "Positions" not in " ".join(names):
            raise AssertionError(f"pages: floor 2 has no Positions page: {names}")
        assert not any(n.startswith(("Portfolio", "Needs you", "Suggestions", "Council")) for n in names), f"pages: Etsy pages on floor 2: {names}"
        page.get_by_role("tab", name="Positions").click()
        rows = page.get_by_role("region", name="Open positions")
        boston = rows.locator("tr", has_text="BOS").inner_text().lower()
        newyork = rows.locator("tr", has_text="NY").inner_text().lower()
        assert "agrees" in boston and "disagrees" not in boston, f"pages: Boston moved our way: {boston}"
        assert "disagrees" in newyork, f"pages: New York moved against us: {newyork}"
        page.get_by_role("button", name="Menu").first.click()
        page.get_by_role("tab", name="Overview").click()      # the elevator is in the office
        page.get_by_role("button", name="Floor 1").click()
        page.get_by_role("button", name="Menu").first.click()
        names = [t.inner_text().strip() for t in page.get_by_role("tab").all() if t.is_visible()]
        assert any(n.startswith("Portfolio") for n in names) and "Positions" not in names, f"pages: floor 1 menu: {names}"
    srv.shutdown()
    print("pages OK")


def wall():
    """Oct 27 live: Etsy agents kept asking desk agents about Etsy work they used to hold. Floor 1 can't pull a desk
    agent back in by asking it directly; Jack (and the board) and other desks still can."""
    h, muse, clock = new_hub("Cee", "Ada", "Nb", "Nf")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nf nfl")
    try:
        h.ask("Ada", "Nb", "can you recheck the corn listing?")
        raise AssertionError("wall: a floor-1 agent's ask reached a desk agent")
    except ValueError as e:
        assert "Cee" in str(e), f"wall: the refusal should say who to ask instead: {e}"
    assert h.ask("jack", "Nb", "how is the NBA board?") and h.ask("Nf", "Nb", "seeing the same injury news?"), "wall: board and desks still reach a desk"
    assert h.ask("Nb", "Ada", "fyi"), "wall: a desk agent can still answer or reach floor 1"
    print("wall OK")


def research():
    """Jack, Oct 27: "the research pauses absolutely shouldn't be pausing. Also every three hours seems way too
    infrequently." With nothing moving, a desk still gets a research round every 45 minutes, any hour, naming games."""
    h, muse, clock = new_hub("Cee", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    clock.t = 1_000_000.0 - (1_000_000 % 86400) + 86400 + 3 * HOUR - time.timezone     # 03:00 local: the old pause
    feed(h, nba=[event("g1", "BKN", "BOS", clock() + 10 * HOUR, spread=(-11.5, -110, -110))])
    poll(h, clock)                                     # the opener wake
    rounds = lambda: [m for m in muse.sent.get("Nb", []) if "lines moved" not in m]
    clock.go(30 * 60); poll(h, clock)                  # 36.7 min after the wake
    assert not rounds(), "research: a round came before 45 minutes passed"
    clock.go(5 * 60); poll(h, clock)                   # 48 min
    assert len(rounds()) == 1, f"research: no round after 45 quiet minutes at night: {muse.sent.get('Nb')}"
    assert "BKN at BOS" in rounds()[0], f"research: the round should name the games to look at: {rounds()[0]}"
    print("research OK")


def office():
    """Jack, Oct 27: "make it so I can see what agents are doing… on floor 2 it seems like everyone is always not
    working". Between hub rounds a desk agent is on duty: it sits at a desk working its sport's board, not on a break."""
    from playwright.sync_api import sync_playwright
    from test_ui import PASSWORD, seeded
    h, srv, url = seeded()
    h.add_agent("Nb", "muse"); h.manage("dot", "team Nb nba")
    feed(h, nba=[event("g1", "BKN", "BOS", h.clock() + 3 * HOUR, spread=(-11.5, -110, -110))])
    poll(h, h.clock)
    with h.lock:
        h.db.execute("update items set status='done' where too='Nb'")     # nothing in flight: between rounds
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(viewport={"width": 1440, "height": 900},
                                             http_credentials={"username": "jack", "password": PASSWORD})
        page.goto(url)
        page.wait_for_function("window.Office3D && Office3D.debug.state().ready", timeout=60000)
        page.get_by_role("button", name="Floor 2").click()
        page.wait_for_function("Office.debug.people.get('Nb')", timeout=20000)
        nb = page.evaluate("(() => { const p = Office.debug.people.get('Nb'); return { mode: p.mode, card: p.card }; })()")
        assert nb["mode"] == "work" and "NBA" in (nb["card"] or ""), f"office: the NBA desk agent looks off duty: {nb}"
    srv.shutdown()
    print("office OK")


def local(day, hh, mm=0):
    """Epoch for a local wall-clock time on day `day` after a fixed base, so slate tests don't depend on today's date."""
    return time.mktime((2026, 11, 2 + day, hh, mm, 0, 0, 0, -1))


def slate():
    """Jack, Oct 27: "I would have liked them to have a bunch of positions on games for today… my friend puts on 15-20
    a day". A desk is handed tonight's whole slate (not the weekend), each game once, with leans welcome, then a final
    look shortly before each game; a puck line toggling between its two sides wakes nobody."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    clock.t = local(0, 9)
    feed(h, nba=[event("g1", "BKN", "BOS", local(0, 19), spread=(-11.5, -110, -110)),
                 event("g2", "POR", "LAL", local(0, 22, 30), spread=(-1.5, -110, -110)),
                 event("g3", "MIA", "ATL", local(1, 19), spread=(-4, -110, -110))],
         nhl=[event("h1", "LA", "CHI", local(0, 20), spread=(1.5, -250, 200), ml=(120, -140))])
    poll(h, clock)
    h.manage("Nb", 'call add g2 spread LAL -1.5 -110 -125 2 "Portland on the road" "LeBron sits"')
    rounds = lambda n: [m for m in muse.sent.get(n, []) if "lines moved" not in m]
    clock.go(45 * 60); poll(h, clock)
    r = rounds("Nb")
    assert len(r) == 1 and "BKN at BOS" in r[0], f"slate: tonight's uncalled game wasn't handed to the desk: {r}"
    assert "MIA at ATL" not in r[0], f"slate: tomorrow's game crowded tonight's slate: {r[0]}"
    assert "POR at LAL" not in r[0], f"slate: a game the desk already called came back: {r[0]}"
    assert "one or two" not in r[0].lower(), f"slate: the round still caps the desk at one or two games: {r[0]}"
    clock.go(50 * 60); poll(h, clock)
    assert len(rounds("Nb")) == 1, f"slate: the same game was handed over again with nothing new: {rounds('Nb')[1:]}"
    clock.t = local(0, 17, 30); poll(h, clock)              # 90 minutes before Boston tips
    last = rounds("Nb")[-1]
    assert len(rounds("Nb")) == 2 and "BKN at BOS" in last and "POR at LAL" not in last, \
        f"slate: no final look at the game about to start: {rounds('Nb')[1:]}"
    # Chicago's puck line seen live Oct 27: the feed toggles between CHI +1.5 (-250) and CHI -1.5 (+225) all day
    before = len(muse.sent.get("Nh", []))
    feed(h, nhl=[event("h1", "LA", "CHI", local(0, 20), spread=(-1.5, 225, -278), ml=(120, -140))])
    clock.go(25 * 60); poll(h, clock)
    feed(h, nhl=[event("h1", "LA", "CHI", local(0, 20), spread=(1.5, -250, 200), ml=(120, -140))])
    clock.go(25 * 60); poll(h, clock)
    woke = [m for m in muse.sent.get("Nh", [])[before:] if "lines moved" in m]
    assert not woke, f"slate: a puck line toggling sides woke the desk: {woke}"
    print("slate OK")


def sanity():
    """Jack, Oct 27: "make sure their reasoning actually makes sense… I don't know enough to evaluate". The hub refuses
    calls whose own numbers contradict them: a fair price worse than the bet, a price DraftKings isn't showing, or an
    edge too big to be real."""
    h, muse, clock = new_hub("Cee", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    feed(h, nba=[event("g1", "BKN", "BOS", clock() + 3 * HOUR, spread=(-11.5, -110, -110), ml=(-900, 600))])
    poll(h, clock)
    bad = {"fair worse than the price": 'call add g1 spread BOS -11.5 -110 +105 2 "Boston rolls" "Tatum sits"',
           "a line DraftKings isn't showing": 'call add g1 spread BOS -8.5 -110 -130 2 "Boston rolls" "Tatum sits"',
           "odds DraftKings isn't showing": 'call add g1 spread BOS -11.5 +140 -110 2 "Boston rolls" "Tatum sits"',
           "an edge too big to be real": 'call add g1 moneyline BKN - 600 -150 3 "upset special" "Boston shows up"'}
    for what, line in bad.items():
        try:
            h.manage("Nb", line)
            raise AssertionError(f"sanity: the hub logged a call with {what}")
        except ValueError:
            pass
    assert "logged" in h.manage("Nb", 'call add g1 spread BOS -11.5 -108 -125 2 "Boston rolls" "Tatum sits"'), \
        "sanity: a sound call two cents off the feed's price was refused"
    print("sanity OK")


def review():
    """Jack, Oct 27: "why can't they just actually talk about it and do research and validate the positions". A call is a
    proposal until another desk confirms it: it reaches a reviewer on the hub's next pass (no timer), it isn't a position
    until confirmed, a flag sends it back to its desk with the reason (and the reviewer can reinstate it after they talk),
    and a call nobody confirmed by tip-off is never tracked. Nobody reviews their own calls; a flag after tip-off can't
    erase a result."""
    h, muse, clock = new_hub("Cee", "Ada", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 3 * HOUR
    feed(h, nba=[event("g1", "BKN", "BOS", start, spread=(-11.5, -110, -110), total=(222.5, -110, -110)),
                 event("g2", "DET", "NY", start, spread=(-3.5, -110, -110))])
    poll(h, clock)
    calls = lambda: {(c["game"], c["market"], c["side"]): c for c in h.board()["book"]["calls"]}
    h.manage("Nb", 'call add g1 spread BOS -11.5 -110 -125 2 "Brooklyn on a back-to-back" "Tatum sits"')
    sp = calls()[("g1", "spread", "BOS")]["id"]
    h.tick()                                                # the hub's next pass, no waiting
    assert [m for m in muse.sent.get("Nh", []) if "Brooklyn on a back-to-back" in m], \
        f"review: the call didn't go straight to another desk to check: {muse.sent.get('Nh')}"
    assert h.board()["book"]["desks"]["nba"]["open"] == 0, "review: an unchecked call already counts as a position"
    for who in ("Nb", "Ada"):
        try:
            h.manage(who, f'call review {sp} ok "fine"')
            raise AssertionError(f"review: {who} reviewed a call it may not")
        except ValueError:
            pass
    h.manage("Nh", f'call review {sp} ok "back-to-back and the rest edge both check out"')
    assert h.board()["book"]["desks"]["nba"]["open"] == 1, "review: a confirmed call isn't a position"
    # flagged: out of the book, its desk hears why; after they talk the reviewer can put it back before the game
    h.manage("Nb", 'call add g2 spread NY -3.5 -110 -120 1 "Pistons on the road" "Brunson sits"')
    ny = calls()[("g2", "spread", "NY")]["id"]
    h.manage("Nh", f'call review {ny} flag "Detroit is at home in this game, not on the road"')
    c = calls()[("g2", "spread", "NY")]
    assert c["result"] == "pulled" and c["units"] == 0, f"review: a flagged call is still in the book: {c}"
    poll(h, clock)
    assert [m for m in muse.sent.get("Nb", []) if "not on the road" in m], "review: the desk never heard why its call was pulled"
    h.manage("Nh", f'call review {ny} ok "fair: they meant the Pistons\' road trip before this, which is real"')
    assert calls()[("g2", "spread", "NY")]["result"] is None, "review: the reviewer couldn't reinstate the call after talking"
    # never confirmed by tip-off: never tracked
    h.manage("Nb", 'call add g1 total under 222.5 -110 -120 1 "two slow defenses" "pace spikes"')
    # confirmed, then flagged in hindsight after tip-off: it stands
    h.manage("Nb", 'call add g1 total over 222.5 -110 -118 1 "the other read" "pace dies"')
    over = calls()[("g1", "total", "over")]["id"]
    h.manage("Nh", f'call review {over} ok "fine"')
    clock.go(3 * HOUR)
    feed(h, nba=[event("g1", "BKN", "BOS", start, status="STATUS_IN_PROGRESS"), event("g2", "DET", "NY", start, status="STATUS_IN_PROGRESS")])
    poll(h, clock)
    try:
        h.manage("Nh", f'call review {over} flag "pace argument is thin"')    # refused or ignored: either keeps the result
    except ValueError:
        pass
    feed(h, nba=[event("g1", "BKN", "BOS", start, status="STATUS_FINAL", score=(120, 105)),
                 event("g2", "DET", "NY", start, status="STATUS_FINAL", score=(110, 100))])
    poll(h, clock)
    c = calls()
    assert c[("g1", "spread", "BOS")]["result"] == "win" and c[("g2", "spread", "NY")]["result"] == "win", c
    assert c[("g1", "total", "under")]["result"] == "unreviewed" and c[("g1", "total", "under")]["units"] == 0, \
        f"review: a call nobody confirmed was graded: {c[('g1', 'total', 'under')]}"
    assert c[("g1", "total", "over")]["result"] == "win", f"review: a flag after tip-off changed a result: {c[('g1', 'total', 'over')]}"
    print("review OK")


def confirm(h, by):
    """Another desk confirms every call waiting for review (the tests that aren't about review)."""
    for c in h.board()["book"]["calls"]:
        if c["review"] is None and c["result"] is None:
            h.manage(by, f'call review {c["id"]} ok "checks out"')


if __name__ == "__main__":
    {"book": book, "watch": watch, "board_speed": board_speed, "elevator": elevator, "pages": pages, "wall": wall, "research": research, "slate": slate, "office": office, "sanity": sanity, "review": review}[sys.argv[1]]()
