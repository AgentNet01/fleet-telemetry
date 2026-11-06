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


def tick_speed():
    """Oct 28 live: every hub pass held the lock ~15 s in its "no work lined up" check, and the board waited behind it
    (15-20 s loads). On live-sized data a pass's planning checks finish well under a second."""
    import shutil
    from test_autonomy import ActiveMuse
    from test_hub import Clock
    work = os.path.join(tempfile.mkdtemp(), "hub.db")
    shutil.copy(DEBUG_DB, work)
    h = hub.Hub(work, ActiveMuse(), Clock(), evidence_ok=lambda link: True)
    with h.lock:
        h._dry()                                # warm the page cache
        t = time.time(); h._dry(); took = time.time() - t
    assert took < 0.3, f"tick_speed: the no-work check took {took:.2f}s"
    print(f"tick_speed OK ({took:.2f}s)")


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
        confirm(h, "Nf")
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
    """Jack, Oct 27: "the research pauses absolutely shouldn't be pausing", and Oct 29: "they should essentially constantly
    be working". At 3am with nothing moving, an idle desk still gets its games to work, named."""
    h, muse, clock = new_hub("Cee", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    clock.t = 1_000_000.0 - (1_000_000 % 86400) + 86400 + 3 * HOUR - time.timezone     # 03:00 local: the old pause
    feed(h, nba=[event("g1", "BKN", "BOS", clock() + 10 * HOUR, spread=(-11.5, -110, -110))])
    poll(h, clock)
    rounds = [m for m in muse.sent.get("Nb", []) if "lines moved" not in m]
    assert rounds and "BKN at BOS" in rounds[-1], f"research: no named round for an idle desk at night: {muse.sent.get('Nb')}"
    print("research OK")


def capped():
    """Nov 1: Boboe 18 (soccer) was out of weekly Muse tokens since Oct 31 and the hub still sent it a round every 10 min
    (119 in a day), each answered by Muse's usage-limit notice. A capped agent gets nothing until its reset, then resumes."""
    import muse
    h, fake, clock = new_hub("Cee", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    until = clock() + 3 * 86400
    real = fake.deliver
    def deliver(agent, text, now=None):
        if agent == "Nb" and clock() < until:
            raise muse.Capped(agent, until)
        return real(agent, text)
    fake.deliver = deliver
    feed(h, nba=[event(f"g{i}", "BKN", "BOS", clock() + (10 + i) * HOUR, spread=(-11.5, -110, -110)) for i in range(6)])
    tries = 0
    orig = h.transport.deliver
    def count(agent, text, now=None):
        nonlocal tries
        tries += agent == "Nb"
        return orig(agent, text)
    h.transport.deliver = count
    for _ in range(12):                        # two hours of ticks
        poll(h, clock)
    assert tries <= 1, f"capped: hub kept sending to a capped agent ({tries} tries in 2 h)"
    nb = {a["name"]: a for a in h.board()["agents"]}["Nb"]
    assert nb.get("capped_until") == until, f"capped: board doesn't show the reset: {nb.get('capped_until')}"
    clock.t = until + 60
    poll(h, clock)
    assert fake.sent.get("Nb"), "capped: no send after the reset"
    assert not {a["name"]: a for a in h.board()["agents"]}["Nb"].get("capped_until"), "capped: flag not cleared"
    print("capped OK")


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
    """Jack, Oct 29: "this should be running on literally every game… they should essentially constantly be working even
    if they aren't placing frequent positions". Whenever a desk has nothing in flight it gets its next few games to run
    through the full method: games it has never worked first, then the ones it worked longest ago, called or not. A
    desk still working gets nothing more piled on, and a final look still comes before each uncalled game."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    clock.t = local(0, 9)
    feed(h, nba=[event("g1", "BKN", "BOS", local(0, 19), spread=(-11.5, -110, -110)),
                 event("g2", "POR", "LAL", local(0, 19, 30), spread=(-1.5, -110, -110)),
                 event("g3", "MIA", "ATL", local(0, 20), spread=(-4, -110, -110)),
                 event("g4", "DEN", "PHX", local(0, 21), spread=(-2, -110, -110))],
         nhl=[event("h1", "LA", "CHI", local(0, 20), spread=(1.5, -250, 200), ml=(120, -140))])
    clock.go(400); h.tick()
    h.manage("Nb", 'call add g2 spread LAL -1.5 -110 -125 2 "Portland on the road" "LeBron sits"')
    rounds = lambda n: [m for m in muse.sent.get(n, []) if "lines moved" not in m and "Check the" not in m]
    clock.go(15 * 60); h.tick()
    r = rounds("Nb")
    assert len(r) == 1, f"slate: an idle desk wasn't handed games to work: {r}"
    assert all(g in r[0] for g in ("BKN at BOS", "POR at LAL", "MIA at ATL")) and "DEN at PHX" not in r[0], \
        f"slate: the round isn't the next three games, called ones included: {r[0]}"
    assert "Defense vs position" in r[0] and "Injury cascade" in r[0], f"slate: the round came without the method: {r[0]}"
    muse.acts["Nb"] = {"busy": True, "at": clock(), "line": "Pulling Boston's defense vs centers, last 15"}
    h.observe()                                            # the hub's activity reader (its own thread live)
    clock.go(15 * 60); h.tick()
    assert len(rounds("Nb")) == 1, f"slate: a second round landed while the first was in flight: {rounds('Nb')[1:]}"
    muse.acts["Nb"] = {"busy": False, "at": clock(), "line": "Logged a prop on Davis"}
    h.observe()
    clock.go(15 * 60); h.tick()
    r = rounds("Nb")
    assert len(r) == 2 and "DEN at PHX" in r[1] and "BKN at BOS" not in r[1], \
        f"slate: the next round isn't just the unworked game (the rest were worked under 2h ago): {r[1:]}"
    clock.go(2 * HOUR); h.tick()                           # Jack, Oct 29: a 3-game slate resent every 10 min read "unchanged" 30 times
    r = rounds("Nb")
    assert len(r) == 3 and "BKN at BOS" in r[2] and "POR at LAL" in r[2], f"slate: worked games never came back: {r[2:]}"
    clock.t = local(0, 17, 30); h.tick()                    # 90 minutes before Boston tips
    looks = [m.split("final look]")[1].split("[fleet")[0] for m in muse.sent["Nb"] if "final look]" in m]
    assert [m for m in looks if "BKN at BOS" in m and "POR at LAL" not in m], \
        f"slate: no final look at the uncalled game about to start: {rounds('Nb')[3:]}"
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
    # never confirmed by tip-off: never tracked (Nov 1: a lean counts unchecked, so this is a confidence-2 call)
    h.manage("Nb", 'call add g1 total under 222.5 -110 -120 2 "two slow defenses" "pace spikes"')
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


def strategy():
    """Jack, Oct 27: "shift three of them to [moving early] and have three on the other strategy so we can evaluate them
    against each other". An early desk is handed every posted game as soon as it can price it, days ahead; a game-day
    desk gets its next day only. The book compares the two groups side by side."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    clock.t = local(0, 9)
    feed(h, nba=[event("g1", "BKN", "BOS", local(0, 19), spread=(-11.5, -110, -110)),
                 event("g2", "MIA", "ATL", local(3, 19), spread=(-4, -110, -110))],
         nhl=[event("h1", "LA", "CHI", local(0, 20), total=(5.5, -110, -110)),
              event("h2", "TOR", "SEA", local(3, 22), total=(6.5, -110, -110))])
    poll(h, clock)
    clock.go(45 * 60); poll(h, clock)
    rounds = lambda n: " ".join(m for m in muse.sent.get(n, []) if "lines moved" not in m)
    # Nov 1: an early agent only gets games it may still call, 12 h+ out; LA at CHI (11 h) is its game-day partner's
    assert "TOR at SEA" in rounds("Nh") and "LA at CHI" not in rounds("Nh"), \
        f"strategy: the early NHL desk wasn't handed the game three days out: {rounds('Nh')}"
    assert "BKN at BOS" in rounds("Nb") and "MIA at ATL" not in rounds("Nb"), \
        f"strategy: the game-day NBA desk got games beyond its next day: {rounds('Nb')}"
    st = h.board()["book"]["strategies"]
    assert "nhl" in st["early"]["desks"] and "nba" in st["gameday"]["desks"], st
    h.manage("Nh", 'call add h2 total under 6.5 -110 -120 1 "two rested starting goalies" "both backups start"')
    confirm(h, "Nb")
    feed(h, nhl=[event("h1", "LA", "CHI", local(0, 20), total=(5.5, -110, -110)),
                 event("h2", "TOR", "SEA", local(3, 22), total=(5.5, -110, -110))])
    clock.go(HOUR); poll(h, clock)
    clock.t = local(4, 2); feed(h, nhl=[event("h2", "TOR", "SEA", local(3, 22), status="STATUS_FINAL", score=(3, 2))])
    poll(h, clock)
    st = h.board()["book"]["strategies"]
    # worked by hand: under 6.5 at -110 with 5 goals scored wins (+0.909); the total closed 5.5, so 6.5 beat it
    assert (st["early"]["calls"], round(st["early"]["units"], 3), st["early"]["beat_close"]) == (1, 0.909, 1), st
    assert st["gameday"]["calls"] == 0, st
    print("strategy OK")


def explore():
    """Jack, Oct 27: "one that just goes off and tries to find a strategy of its own… tracking the same way… should just
    kinda always be working". The explorer adds any league the feed carries, its calls are checked and graded like every
    desk's, it keeps a notebook, and the hub hands it its next step whenever it finishes one, never two at once."""
    h, muse, clock = new_hub("Cee", "Nb", "Lx")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Lx lab")
    start = clock() + 5 * HOUR
    games = {"baseball/mlb": [event("m1", "NYY", "LAD", start, ml=(-130, 110), total=(8.5, -110, -110))]}
    h.sports_fetch = lambda url: {"events": next((v for k, v in games.items() if "/" + k + "/" in url), [])}
    for bad in ("../../admin", "baseball/mlb?x=1", "x"):
        try:
            h.manage("Lx", f"call watch {bad}")
            raise AssertionError(f"explore: the hub took a league path it can't trust: {bad}")
        except ValueError:
            pass
    h.manage("Lx", "call watch baseball/mlb")
    poll(h, clock)
    assert "m1" in h.manage("Lx", "call games"), "explore: the league the explorer added never reached its board"
    h.manage("Lx", 'call note "MLB totals drift under after 1pm wind reports; testing on 40 past games"')
    h.manage("Lx", "call note unquoted: Bundesliga openers overshoot by 0.25 goals")   # live Oct 28: an unquoted note was refused
    h.manage("Lx", 'call add m1 total under 8.5 -110 -122 1 "wind blowing in at 15 mph per the afternoon report" "wind dies"')
    confirm(h, "Nb")
    # always working: whenever it has nothing in flight, the hub hands it the next step with its notebook
    nudges = lambda: [m for m in muse.sent.get("Lx", []) if "lines moved" not in m and "Check the" not in m]
    with h.lock:
        h.db.execute("update items set status='done' where too='Lx'")
    clock.go(15 * 60); poll(h, clock)
    assert nudges() and "wind reports" in nudges()[-1] and "overshoot by 0.25" in nudges()[-1], \
        f"explore: the explorer sat idle, or lost its notebook: {nudges()}"
    n = len(nudges())
    muse.acts["Lx"] = {"busy": True, "at": clock(), "line": "Downloading 2024 MLB weather and totals"}
    h.observe()                                            # the hub's activity reader (its own thread live)
    clock.go(15 * 60); poll(h, clock)                      # still working on the last step: nothing more piles on
    assert len(nudges()) == n, f"explore: a second step landed while the first was still in flight: {nudges()[n:]}"
    muse.acts["Lx"] = {"busy": False, "at": clock(), "line": "Wrote mlb-wind.csv"}
    h.observe()                                            # the hub's activity reader (its own thread live)
    clock.go(15 * 60); poll(h, clock)
    assert len(nudges()) == n + 1, f"explore: the explorer finished a step and wasn't handed the next: {nudges()[n:]}"
    games["baseball/mlb"] = [event("m1", "NYY", "LAD", start, status="STATUS_FINAL", score=(3, 2))]
    clock.go(5 * HOUR); poll(h, clock)
    st = h.board()["book"]["strategies"]
    # worked by hand: under 8.5 at -110 with 5 runs wins +0.909
    assert (st["explore"]["calls"], round(st["explore"]["units"], 3)) == (1, 0.909), st
    print("explore OK")


def props():
    """Jack, Oct 29: desks log player props; the hub grades a prop from ESPN's box score and a player who didn't play
    voids it. Jack, Nov 6: no more softening: easier alt lines earned ~+$2.50 on 278 picks vs +$17.58 on main lines,
    so a game line must be DraftKings' main line at its price."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 3 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110), total=(222.5, -110, -110))])
    poll(h, clock)
    h.manage("Nb", 'call add g1 spread BOS -3.5 -110 -130 2 "x" "y"')
    h.manage("Nb", 'call add g1 total over 222.5 -110 -130 1 "x" "y"')
    for bad, why in (('call add g1 spread BOS -2.5 -135 -150 2 "x" "y"', "an easier alt line"),
                     ('call add g1 total over 221 -130 -145 1 "x" "y"', "an easier alt total"),
                     ('call prop g1 "Anthony Davis" touchdowns over 0.5 -110 -130 1 "x" "y"', "not an NBA stat")):
        try:
            h.manage("Nb", bad)
            raise AssertionError(f"props: accepted a call that is {why}")
        except ValueError:
            pass
    h.db.executemany("insert into props(game, player, stat, side, line, odds, at) values('g1',?,?,?,?,?,0)",
                     [("Anthony Davis", "pra", "over", 38.5, -125), ("Jayson Tatum", "threes", "under", 3.5, -120),
                      ("Kristaps Porzingis", "points", "over", 15.5, -115)])
    h.manage("Nb", 'call prop g1 "Anthony Davis" pra over 38.5 -125 -145 2 "Boston bleeds rebounds to bigs" "foul trouble"')
    h.manage("Nb", 'call prop g1 "Jayson Tatum" threes under 3.5 -120 -140 1 "x" "y"')
    h.manage("Nb", 'call prop g1 "Kristaps Porzingis" points over 15.5 -115 -130 1 "x" "y"')    # doesn't play
    confirm(h, "Nh")
    box = {"boxscore": {"players": [{"statistics": [{"labels": ["MIN", "PTS", "3PT", "REB", "AST"], "athletes": [
        {"athlete": {"displayName": "Anthony Davis"}, "stats": ["36", "29", "3-6", "10", "1"]},
        {"athlete": {"displayName": "Jayson Tatum"}, "stats": ["38", "31", "5-11", "8", "4"]},
        {"athlete": {"displayName": "Kristaps Porzingis"}, "stats": []}]}]}]}}
    clock.go(3 * HOUR)
    fin = [event("g1", "LAL", "BOS", start, status="STATUS_FINAL", score=(110, 106))]
    feed(h, nba=fin)
    plain = h.sports_fetch
    h.sports_fetch = lambda url: box if "/summary?event=g1" in url else plain(url)
    poll(h, clock)
    poll(h, clock)                                          # props settle on the poll after the final: box scores lag
    c = {(x["player"] or x["market"], x["side"]): x for x in h.board()["book"]["calls"]}
    # worked by hand: BOS won by 4 laying 3.5 → win; total 216 under 222.5 → the over lost; Davis 29+10+1 = 40 > 38.5 → win;
    # Tatum hit 5 threes over 3.5 → the under lost; Porzingis had no minutes → void
    assert c[("spread", "BOS")]["result"] == "win" and c[("total", "over")]["result"] == "loss", c
    assert c[("Anthony Davis", "over")]["result"] == "win" and c[("Anthony Davis", "over")]["pick"] == "Anthony Davis Over 38.5 pra", c
    assert c[("Jayson Tatum", "under")]["result"] == "loss" and c[("Kristaps Porzingis", "over")]["result"] == "void", c
    assert c[("spread", "BOS")]["beat_close"] is not None, "props: a main-line call wasn't compared to the close"
    print("props OK")


def pairs():
    """Jack, Nov 1: early vs game day was compared across different sports, so it proved nothing. Every sport gets one
    agent of each; both work the same games, the early one >= 12 h before start and the game-day one inside 12 h, and
    the book scores each strategy per sport."""
    h, muse, clock = new_hub("Cee", "Ne", "Ng", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Ne nba"); h.manage("Cee", "team Ng nba"); h.manage("Cee", "team Nh nhl")
    h.manage("Cee", "strategy Ne early"); h.manage("Cee", "strategy Ng gameday")
    clock.t = local(0, 9)
    soon, later = local(0, 15), local(1, 15)                  # 6 h and 30 h out
    feed(h, nba=[event("g1", "BKN", "BOS", soon, spread=(-11.5, -110, -110)),
                 event("g2", "MIA", "ATL", later, spread=(-4, -110, -110))],
         nhl=[event("h1", "LA", "CHI", local(1, 20), total=(5.5, -110, -110))])
    poll(h, clock)
    clock.go(45 * 60); poll(h, clock)
    rounds = lambda n: " ".join(m for m in muse.sent.get(n, []) if "lines moved" not in m and "Check the" not in m)
    assert "MIA at ATL" in rounds("Ne") and "BKN at BOS" not in rounds("Ne"), \
        f"pairs: the early agent should get only games 12 h+ out: {rounds('Ne')[:300]}"
    assert "BKN at BOS" in rounds("Ng") and "MIA at ATL" not in rounds("Ng"), \
        f"pairs: the game-day agent should get today's slate only: {rounds('Ng')[:300]}"
    for who, gid in (("Ne", "g1"), ("Ng", "g2")):
        try:
            h.manage(who, f'call add {gid} spread BOS -11.5 -110 -125 1 "x" "y"'.replace("BOS", "BOS" if gid == "g1" else "ATL"))
            raise AssertionError(f"pairs: {who} logged a call outside its strategy's window on {gid}")
        except ValueError as e:
            assert "12 h" in str(e), f"pairs: refused for the wrong reason: {e}"
    h.manage("Ne", 'call add g2 spread ATL -4 -110 -125 1 "rest edge" "MIA rests nobody"')
    h.manage("Ng", 'call add g1 spread BOS -11.5 -110 -125 1 "BKN on a back to back" "BOS sits starters"')
    confirm(h, "Nh")
    clock.go(2 * HOUR + 30 * 60); poll(h, clock)             # 2.5 h before g1: the final look
    looks = lambda n: [m for m in muse.sent.get(n, []) if "final look" in m.lower()]
    assert not looks("Ne"), f"pairs: the early agent got a final look: {looks('Ne')}"
    clock.t = local(2, 3)
    feed(h, nba=[event("g1", "BKN", "BOS", soon, status="STATUS_FINAL", score=(120, 100)),
                 event("g2", "MIA", "ATL", later, status="STATUS_FINAL", score=(100, 110))])
    poll(h, clock)
    bss = h.board()["book"]["by_sport_strategy"]
    assert bss["nba"]["early"]["calls"] == 1 and bss["nba"]["gameday"]["calls"] == 1, bss.get("nba")
    st = h.board()["book"]["strategies"]
    assert st["early"]["calls"] == 1 and st["gameday"]["calls"] == 1, st
    print("pairs OK")


def clv_hidden():
    """Jack, Nov 1: profit is the verdict; closing-line value is an early gauge on the dashboard only. Agents never see
    it, so they bet to win rather than chase moves. Game-line CLV and prop CLV are kept apart."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 5 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110))])
    poll(h, clock)
    h.manage("Nb", 'call add g1 spread BOS -3.5 -110 -125 1 "x" "y"')
    confirm(h, "Nh")
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-5.5, -110, -110))])
    poll(h, clock)
    clock.go(6 * HOUR)
    feed(h, nba=[event("g1", "LAL", "BOS", start, status="STATUS_FINAL", score=(110, 100))])     # (home, away): BOS by 10
    poll(h, clock)
    out = h.manage("Nb", "call list")
    assert "win" in out and "close" not in out.lower(), f"clv_hidden: an agent sees CLV: {out}"
    t = h.board()["book"]["by_sport_strategy"]["nba"]["gameday"]
    assert round(t["units"], 3) == 0.909 and t["clv_game"] == {"graded": 1, "beat": 1} and t["clv_prop"] == {"graded": 0, "beat": 0}, t
    print("clv_hidden OK")


def prop_close():
    """Jack, Nov 1: props stay in; ESPN's DraftKings propBets give each player's line (no price), so a prop's close is
    the last pre-start line, and it beats the close when that line moved its way."""
    h, muse, clock = new_hub("Cee", "Nf", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nf nfl"); h.manage("Cee", "team Nh nhl")
    start = clock() + 30 * HOUR
    feed(h, nfl=[event("f1", "KC", "BUF", start, spread=(-2.5, -110, -110))])
    plain = h.sports_fetch
    line = {"v": 3.5}
    hits = []
    def fetch(url):
        if "propBets" in url:
            hits.append(url)
            assert "/football/leagues/nfl/events/f1/" in url and "/odds/100/" in url, url
            item = lambda ref, typ, v: {"athlete": {"$ref": f"http://x/athletes/{ref}?lang=en"}, "type": {"name": typ},
                                        "current": {"target": {"value": v}}, "open": {"target": {"value": 3.5}}}
            return {"count": 3, "pageCount": 1, "items": [
                item(77, "Total Receptions (incl. overtime)", line["v"]),
                item(88, "Total Receptions (incl. overtime)", 9.5),            # another player
                item(77, "Receptions Milestones", 6.5)]}                        # an alt line, not the main one
        if "/athletes/77" in url:
            return {"displayName": "Dalton Kincaid"}
        if "/athletes/88" in url:
            return {"displayName": "Travis Kelce"}
        if "/summary?event=f1" in url:
            return {"boxscore": {"players": [{"statistics": [{"name": "receiving", "labels": ["REC", "YDS"], "athletes": [
                {"athlete": {"displayName": "Dalton Kincaid"}, "stats": ["6", "71"]}]}]}]}}
        return plain(url)
    h.sports_fetch = fetch
    poll(h, clock)
    h.db.execute("insert into props(game, player, stat, side, line, odds, at) values('f1','Dalton Kincaid','receptions','over',3.5,-115,0)")
    h.manage("Nf", 'call prop f1 "Dalton Kincaid" receptions over 3.5 -115 -135 1 "x" "y"')
    confirm(h, "Nh")
    poll(h, clock)
    line["v"] = 4.5
    poll(h, clock)
    clock.t = start + 60                                    # in play: a live prop line is not the close
    line["v"] = 7.5
    feed_live = [event("f1", "KC", "BUF", start, status="STATUS_IN_PROGRESS")]
    feed(h, nfl=feed_live); inner = h.sports_fetch
    h.sports_fetch = lambda url: fetch(url) if ("propBets" in url or "/athletes/" in url or "summary" in url) else inner(url)
    poll(h, clock)
    feed(h, nfl=[event("f1", "KC", "BUF", start, status="STATUS_FINAL", score=(20, 24))]); inner = h.sports_fetch
    h.sports_fetch = lambda url: fetch(url) if ("propBets" in url or "/athletes/" in url or "summary" in url) else inner(url)
    poll(h, clock); poll(h, clock)
    c = next(x for x in h.board()["book"]["calls"] if x["market"] == "prop")
    assert hits, "prop_close: the hub never read ESPN's propBets"
    assert c["result"] == "win" and c["close_line"] == 4.5 and c["beat_close"] is True, \
        {k: c[k] for k in ("result", "close_line", "beat_close")}
    t = h.board()["book"]["by_sport_strategy"]["nfl"]["early"]
    assert t["clv_prop"] == {"graded": 1, "beat": 1} and t["clv_game"] == {"graded": 0, "beat": 0}, t
    print("prop_close OK")


def explorers():
    """Jack, Nov 1: the spare agents all join the explorer desk. Each nudge names the other explorers so they split
    leagues and questions instead of five agents running the same test."""
    h, muse, clock = new_hub("Cee", "La", "Lb", "Lc")
    h.seat("ceo", "Cee")
    for n in ("La", "Lb", "Lc"):
        h.manage("Cee", f"team {n} lab")
    poll(h, clock); clock.go(15 * 60); poll(h, clock)
    for n, others in (("La", ("Lb", "Lc")), ("Lb", ("La", "Lc")), ("Lc", ("La", "Lb"))):
        got = [m for m in muse.sent.get(n, []) if "explorer" in m.lower()]
        assert got and all(o in got[-1] for o in others), f"explorers: {n}'s nudge doesn't name {others}: {got[-1:]}"
    print("explorers OK")


def floor1_quiet():
    """Jack, Nov 1: everyone but Pericles moves to betting; Pericles keeps floor 1 alive alone and no new products start.
    No scout ("find a new product") and no planning ask goes out, however long agents sit free."""
    h, muse, clock = new_hub("Cee", "Ada")
    h.seat("ceo", "Cee")
    pid = h.add_product("Cups", brief="cups", pm="Cee")
    h.add_project(pid, "launch")
    for _ in range(8):
        clock.go(hub.PLAN_WAIT); h.tick(); h.tick()
    sent = [m for n in ("Cee", "Ada") for m in muse.sent.get(n, [])]
    bad = [m for m in sent if hub.Hub.SCOUT in m or "no work lined up" in m or "planner" in m.lower()]
    assert not bad, f"floor1_quiet: floor 1 still grows: {bad[:2]}"
    print("floor1_quiet OK")


def desk_move():
    """Nov 1 live: Boboe 2 and 7 refused the desk because `fleet status` still showed their Etsy product, PM slot and a
    pinned task. Putting an agent on a desk releases all of that, and its status names the desk and its strategy."""
    h, muse, clock = new_hub("Cee", "Bo", "Cy")
    h.seat("ceo", "Cee")
    pid = h.add_product("Cups", brief="cups", pm="Bo")
    prj = h.add_project(pid, "launch")
    h.place("Bo", pid, "marketer")
    t1 = h.add_task(prj, "copy", "marketer", "posted", owner="Bo")
    t2 = h.add_task(prj, "later", "marketer", "posted")
    h.tick()
    with h.lock:                                # held for Bo until it can move (the hub's own "wait" shape)
        h.db.execute("update tasks set status='blocked', pin='Bo' where id=?", (t2,))
    h.manage("Cee", "team Bo nfl"); h.manage("Cee", "strategy Bo gameday")
    st = h.status("Bo")
    assert st["product"] == "the NFL desk (floor 2)" and st["role"] == "game-day bettor", f"desk_move: status: {st['product']}, {st['role']}"
    assert not st["tasks"], f"desk_move: still holds floor-1 tasks: {st['tasks']}"
    assert h.db.execute("select pm from products where id=?", (pid,)).fetchone()[0] is None, "desk_move: still PM"
    assert h.task(t1)["owner"] is None and h.task(t1)["status"] == "ready", h.task(t1)
    assert h.task(t2)["pin"] is None and h.task(t2)["status"] == "blocked", h.task(t2)
    print("desk_move OK")


def lab_steal():
    """Nov 1 live: explorers ran `call watch basketball/nba` (and nfl, nhl, eng.1); every lab poll relabelled those games
    as lab's, so the NBA desk's board flickered to 0 games and its calls were refused. A league a sport desk covers is
    that desk's: the explorer can't watch it."""
    h, muse, clock = new_hub("Cee", "Nb", "Lx")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Lx lab")
    for path in ("basketball/nba", "soccer/eng.1"):
        try:
            h.manage("Lx", f"call watch {path}")
            raise AssertionError(f"lab_steal: the explorer took {path}, a sport desk's league")
        except ValueError as e:
            assert "desk" in str(e), e
    h.manage("Lx", "call watch baseball/mlb")
    print("lab_steal OK")


def book_all():
    """The results board counted only the newest 500 calls, so settled calls dropped off it as new ones were logged and
    the settled count and profit went down. Old results stay on the book however many calls come after them."""
    h, muse, clock = new_hub("Cee", "Nb")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba")
    start = clock() + 5 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110))])
    poll(h, clock)
    h.manage("Nb", 'call add g1 spread BOS -3.5 -110 -115 1 "edge" "risk"')
    h.db.execute("update calls set result='win', graded_at=? where id=1", (clock(),))
    cols = ", ".join(r[1] for r in h.db.execute("pragma table_info(calls)") if r[1] not in ("id", "result", "graded_at"))
    for _ in range(500):
        h.db.execute(f"insert into calls({cols}) select {cols} from calls where id=1")
    assert sum(c["result"] == "win" for c in hub.sports.book(h)["calls"]) == 1, "book_all: a settled call fell off the book"


def leans():
    """Jack, Nov 1: "I want to increase volume so yes log leans". Desks log a side on every game they work: a lean
    (confidence 1) counts at once with no other desk's check, so volume doesn't pile reviews on the desks; 2s and 3s
    are still checked first. The book splits results by confidence so leans can be judged apart."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 5 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110), total=(222.5, -110, -110))])
    poll(h, clock)
    rounds = [m for m in muse.sent.get("Nb", []) if "next games" in m]
    assert rounds and "every game" in rounds[-1] and "won't have one" not in rounds[-1], \
        f"leans: the round still tells desks most games have no pick: {rounds[-1][:600] if rounds else rounds}"
    out = h.manage("Nb", 'call add g1 spread BOS -3.5 -110 -115 1 "slight rest edge" "BOS sits starters"')
    assert "lean" in out and "counts" in out, f"leans: {out}"
    h.manage("Nb", 'call add g1 total over 222.5 -110 -130 2 "two fast teams" "pace dies"')       # nobody confirms it
    clock.go(11 * 60)
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110), total=(222.5, -110, -110))])
    poll(h, clock)
    asked = [m for m in muse.sent.get("Nh", []) if "reasoning" in m]
    assert asked and "two fast teams" in asked[-1], f"leans: the confidence-2 call wasn't sent for review: {asked}"
    assert not any("slight rest edge" in m for m in asked), "leans: a lean was still sent to another desk for review"
    clock.go(6 * HOUR)
    feed(h, nba=[event("g1", "LAL", "BOS", start, status="STATUS_FINAL", score=(120, 110))])
    poll(h, clock)
    c = {(x["market"]): x for x in h.board()["book"]["calls"]}
    assert c["spread"]["result"] == "win", f"leans: a lean with no review wasn't graded: {c['spread']['result']}"
    assert c["total"]["result"] == "unreviewed", f"leans: an unchecked confidence-2 call counted: {c['total']['result']}"
    bc = h.board()["book"]["desks"]["nba"]["by_conf"]
    assert bc["1"]["settled"] == 1 and round(bc["1"]["units"], 3) == 0.909, bc["1"]
    print("leans OK")


def split():
    """Jack, Nov 6: a second early agent on a desk works different games from the first, not the same ones twice."""
    h, muse, clock = new_hub("Cee", "Ea", "Eb", "Nh")
    h.seat("ceo", "Cee")
    for n in ("Ea", "Eb"):
        h.manage("Cee", f"team {n} nba"); h.manage("Cee", f"strategy {n} early")
    h.manage("Cee", "team Nh nhl")
    clock.t = local(0, 9)
    feed(h, nba=[event(f"c{i}", f"A{i}", f"H{i}", local(1, 12 + i), spread=(-5.5, -110, -110)) for i in range(6)])
    poll(h, clock)
    clock.go(45 * 60); poll(h, clock)
    got = {n: {f"A{i} at H{i}" for i in range(6) if f"A{i} at H{i}" in " ".join(
        m for m in muse.sent.get(n, []) if "next games" in m)} for n in ("Ea", "Eb")}
    assert got["Ea"] and got["Eb"], f"split: both early agents should get a slate: {got}"
    assert not got["Ea"] & got["Eb"], f"split: the two early agents got the same games: {got}"
    print("split OK")


def passes():
    """Jack, Nov 6: "make it give a fair price for everything it passes on". A pass is confidence 0: the desk's fair
    price on a game or prop it won't bet. It is graded like a call so the hub can score every price the desks set,
    but it never counts as a bet, and it doesn't stop the game-day final look."""
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 5 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110), total=(222.5, -110, -110))])
    poll(h, clock)
    rounds = [m for m in muse.sent.get("Nb", []) if "next games" in m]
    assert rounds and "confidence 0" in rounds[-1], f"passes: the round doesn't ask for passes: {rounds[-1][-800:] if rounds else rounds}"
    out = h.manage("Nb", 'call add g1 spread BOS -3.5 -110 -105 0 "fair is about -105" "-"')     # fair worse than the price
    assert "pass" in out, f"passes: {out}"
    h.db.execute("insert into props(game, player, stat, side, line, odds, at) values('g1','Anthony Davis','points','over',24.5,-110,0)")
    h.manage("Nb", 'call prop g1 "Anthony Davis" points over 24.5 -110 -110 0 "priced right" "-"')
    clock.go(3 * HOUR); poll(h, clock)                      # 2 h out: final look still comes, a pass isn't a call
    assert any("final look" in m.lower() for m in muse.sent.get("Nb", [])), "passes: a pass stopped the final look"
    h.manage("Nb", 'call add g1 total over 222.5 -110 -120 1 "pace" "pace dies"')
    clock.go(3 * HOUR)
    feed(h, nba=[event("g1", "LAL", "BOS", start, status="STATUS_FINAL", score=(120, 110))])
    poll(h, clock)
    b = h.board()["book"]
    assert [c["market"] for c in b["calls"]] == ["total"], f"passes: a pass counted as a bet: {[c['market'] for c in b['calls']]}"
    assert b["desks"]["nba"]["calls"] == 1, b["desks"]["nba"]
    p = {c["market"]: c for c in b["passes"]}
    assert p["spread"]["result"] == "win" and p["spread"]["beat_close"] is not None, p
    assert b["pass_tally"]["nba"]["calls"] == 2, b["pass_tally"]
    print("passes OK")


def prop_board():
    """Jack, Nov 6: "write a script for DraftKings". The hub reads DraftKings' own player props for every desk (main O/U
    where it has one, "N+" ladders read as Over N-0.5 where it doesn't), matches each DraftKings game to the hub's,
    lists them with `fleet call props`, and holds a prop call to a listed line and price: no browser checks."""
    import dk
    h, muse, clock = new_hub("Cee", "Nb", "Nh")
    h.seat("ceo", "Cee")
    h.manage("Cee", "team Nb nba"); h.manage("Cee", "team Nh nhl")
    start = clock() + 5 * HOUR
    feed(h, nba=[event("g1", "LAL", "BOS", start, spread=(-3.5, -110, -110), total=(222.5, -110, -110))])
    ev = {"id": "e1", "startEventDate": time.strftime("%Y-%m-%dT%H:%M:%S.0000000Z", time.gmtime(start - 600)),
          "participants": [{"venueRole": "Home", "name": "BOS Celtics", "metadata": {"shortName": "BOS"}},
                           {"venueRole": "Away", "name": "LA Lakers", "metadata": {"shortName": "LAL"}}]}
    ad = [{"type": "Player", "name": "Anthony Davis", "seoIdentifier": "Anthony Davis"}]
    sel = lambda mid, typ, pts, odds, main=True: {"marketId": mid, "outcomeType": typ, "points": pts, "main": main,
                                                 "displayOdds": {"american": odds}, "participants": ad}
    pages = {f"leagues/{dk.LEAGUE['nba']}/categories/1215/subcategories/12488": {
        "events": [ev], "markets": [{"id": "m1", "eventId": "e1", "subcategoryId": 12488}],
        "selections": [sel("m1", "Over", 22.5, "\u2212105"), sel("m1", "Under", 22.5, "\u2212121"),
                       sel("m1", "Over", 20.5, "\u2212150", main=False)]}}
    h.dk_fetch = lambda url: next((v for k, v in pages.items() if url.endswith(k)), {})
    poll(h, clock); poll(h, clock)                          # a game's props land on the poll after the game itself
    out = h.manage("Nb", "call props g1")
    assert "Anthony Davis" in out and "Over 22.5 (-105)" in out and "Under 22.5 (-121)" in out, f"prop_board: {out}"
    assert "-150" not in out, f"prop_board: an alternate line was listed as the main line: {out}"
    for bad, why in (('call prop g1 "Anthony Davis" points over 20.5 -150 -170 1 "x" "y"', "an alt line"),
                     ('call prop g1 "Anthony Davis" points over 22.5 -140 -160 1 "x" "y"', "the wrong price")):
        try:
            h.manage("Nb", bad)
            raise AssertionError(f"prop_board: accepted {why}")
        except ValueError as e:
            assert "22.5" in str(e), f"prop_board: refused {why} for the wrong reason: {e}"
    assert "logged" in h.manage("Nb", 'call prop g1 "Anthony Davis" points over 22.5 -105 -125 1 "x" "y"')
    try:                                                    # Jack, Nov 6: no browser checks: no hub price, no prop call
        h.manage("Nb", 'call prop g1 "Jayson Tatum" points over 26.5 -110 -130 1 "x" "y"')
        raise AssertionError("prop_board: accepted a prop the hub has no DraftKings price for")
    except ValueError as e:
        assert "no DraftKings price" in str(e), e
    said = (h.manage("Nb", "call props g9") + " ".join(muse.sent.get("Nb", []))).lower()
    assert "logged out" not in said and "check draftkings" not in said, "prop_board: something still asks for a DraftKings check"
    h.dk_fetch = lambda url: (_ for _ in ()).throw(OSError("403"))   # a failed read keeps the last board
    clock.go(400); h.tick(); h.tick()
    assert "Over 22.5 (-105)" in h.manage("Nb", "call props g1"), "prop_board: a failed DraftKings read wiped the board"
    lad = {"events": [], "markets": [{"id": "m2", "eventId": "e2", "subcategoryId": 16477}],
           "selections": [{"marketId": "m2", "milestoneValue": 15, "displayOdds": {"american": "+120"},
                           "participants": [{"type": "Player", "name": "Tyrone Riley", "seoIdentifier": "Tyrone Riley IV"}]}]}
    _, rows = dk.props("cbb", lambda url: lad if url.endswith("/subcategories/16477") else {})
    assert rows == [("e2", "Tyrone Riley IV", "points", "over", 14.5, 120)], rows
    print("prop_board OK")

def confirm(h, by):
    """Another desk confirms every call waiting for review (the tests that aren't about review)."""
    for c in h.board()["book"]["calls"]:
        if c["review"] is None and c["result"] is None:
            h.manage(by, f'call review {c["id"]} ok "checks out"')


if __name__ == "__main__":
    {"book": book, "watch": watch, "board_speed": board_speed, "tick_speed": tick_speed, "elevator": elevator, "pages": pages, "wall": wall, "research": research, "slate": slate, "office": office, "strategy": strategy, "explore": explore, "sanity": sanity, "review": review, "props": props, "capped": capped, "pairs": pairs, "clv_hidden": clv_hidden, "prop_close": prop_close, "explorers": explorers, "floor1_quiet": floor1_quiet, "desk_move": desk_move, "lab_steal": lab_steal, "leans": leans, "book_all": book_all, "split": split, "passes": passes, "prop_board": prop_board}[sys.argv[1]]()
