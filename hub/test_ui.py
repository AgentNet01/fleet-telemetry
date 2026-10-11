"""The dashboard in a real browser (Playwright, Chromium), driven the way Jack uses it.

    python3 test_ui.py          # creates product → project → blocked task, checks agent cards,
                                # changes the CEO seat, accepts a suggestion; saves screenshots
                                # at 1440 and 375 px to hub/ui-shots/
"""
import os
import re
import tempfile
import threading
import time

from playwright.sync_api import expect, sync_playwright

import hub
from test_hub import Clock, FakeMuse

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "ui-shots")
PASSWORD = "ui-pass"


def seeded():
    clock = Clock()
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), clock, evidence_ok=lambda link: True)
    for n in ("Ada", "Bea", "Cy", "dot"):
        h.add_agent(n, "slack" if n == "dot" else "muse")
    h.add_agent("darragh", "jack")
    shop = h.add_product("Shop", brief="Etsy budgeting templates", metric="first sale", pm="Cy")
    prj = h.add_project(shop, "launch")
    h.place("Ada", "Shop", "engineer"); h.place("Bea", "Shop", "designer"); h.place("Cy", "Shop", "optimizer")
    h.seat("ceo", "dot")
    h.add_task(prj, "build the budget sheet", role="engineer", done_def="xlsx in the repo")
    h.tick()                                   # Ada takes the sheet; Bea and Cy are free
    clock.go(13 * 3600); h.tick()              # …and stay free for 13 h
    h.suggest("Cy", "bundle the three templates at $9")
    h.manage("dot", 'product set "Shop" metric "10 sales"')
    t = clock()
    h.ingest("Ada", {"activity": {"entries": [{"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t - 30)),
                     "activity_type": "tool", "status": "running", "title": "Building the budget formulas", "message_id": "w1"}]}})
    h.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)", ("Bea", "#1 muse-cli raw for Bea: timeout", clock()))     # Bea replies later, so this one recovered
    h.db.execute("insert into events(agent, dir, text, at) values(?,'err',?,?)", ("Cy", "#2 muse-cli raw for Cy: timeout", clock()))       # Cy never answers: still failing
    long = "trace-test/trace-linux-agent/linux-unpacked/resources/app.asar.unpacked/node_modules/canvas-linux-x64-gnu/skia.linux-x64-gnu.node"
    h.ingest("Bea", {"ts": t, "files": {"count": 1, "mb": 279, "entries": [[long, 286044, t - 100]]}})
    srv = hub.serve(h, "127.0.0.1", 0, PASSWORD)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return h, srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def shoot(page, name):
    os.makedirs(SHOTS, exist_ok=True)
    page.wait_for_timeout(300)
    page.screenshot(path=os.path.join(SHOTS, name + ".png"), full_page=True)


def main():
    h, srv, url = seeded()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark", http_credentials={"username": "jack", "password": PASSWORD})
        page.set_default_timeout(4000)
        page.goto(url)

        # Light mode: a toggle top-right, remembered across reloads
        bg = lambda: page.evaluate("getComputedStyle(document.body).backgroundColor")
        dark = bg()
        toggle = page.get_by_role("button", name=re.compile("light mode", re.I))
        tb, top = toggle.bounding_box(), page.locator(".top").bounding_box()
        assert tb["x"] + tb["width"] > top["x"] + top["width"] - 60, "the toggle sits top right"
        toggle.click()
        assert bg() != dark and sum(map(int, re.findall(r"\d+", bg())[:3])) > 600, f"light background: {bg()}"
        page.reload()
        assert sum(map(int, re.findall(r"\d+", bg())[:3])) > 600, "light mode is remembered"
        page.locator("[data-agent='Ada']").wait_for()
        shoot(page, "1440-overview-light")
        page.get_by_role("button", name=re.compile("dark mode", re.I)).click()
        assert bg() == dark

        # Overview: agent cards say product, role, held task and how long they've been free
        ada = page.locator("[data-agent='Ada']")
        expect(ada).to_contain_text("in Shop")
        expect(ada).to_contain_text("build the budget sheet")
        expect(page.locator("[data-agent='Bea']")).to_contain_text(re.compile(r"free 13h"))
        page.get_by_role("tab", name="Activity").click()
        expect(page.locator("#feed")).to_contain_text('product set "Shop" metric')
        page.get_by_role("tab", name="Overview").click()
        shoot(page, "1440-overview")

        # Agent page: the conversation owns the screen; a message goes out, is delivered, and the reply shows up
        page.locator("[data-agent='Bea']").click()
        chat = page.locator("#tl")
        expect(chat).to_be_visible()
        box = chat.bounding_box()
        assert box["height"] >= 0.5 * 900, f"the conversation gets most of the height, not a sliver: {box}"
        composer = page.get_by_role("button", name="Send").bounding_box()
        assert composer["y"] + composer["height"] <= 900, f"the message box is on screen without scrolling: {composer}"
        # one agent asking another reads the same in both chats, and never like Jack's own messages
        h.ask("Ada", "Bea", "what size is the cover?"); h.tick()
        page.evaluate("load()")
        expect(chat.locator(".sys", has_text="what size is the cover?")).to_contain_text("Ada asked Bea")
        expect(chat.locator(".bub", has_text="what size is the cover?")).to_have_count(0)
        h.transport.say("Bea", "2000x1600"); h.tick(); h.clock.go(61); h.tick()      # Bea answers Ada, so she's free
        page.get_by_label("Your message").fill("how's the cover coming?")
        page.get_by_label("Your message").press("Enter")
        mine = chat.locator(".bub.me", has_text="how's the cover coming?")
        expect(mine).to_contain_text("waiting for a reply")      # delivered straight away, no loop wait
        assert "[fleet" not in mine.inner_text(), "Jack sees what he wrote, not the hub's envelope"
        assert len([t for t in h.transport.sent.get("Bea", []) if "how's the cover" in t]) == 1
        h.transport.say("Bea", "about half done, PNG tonight")
        h.tick(); h.clock.go(61); h.tick()
        page.evaluate("load()")
        expect(chat.locator(".bub.them", has_text="about half done")).to_be_visible()
        expect(mine).not_to_contain_text("waiting")
        page.get_by_label("Your message").fill("half-typed")
        page.evaluate("load()")
        page.wait_for_timeout(300)
        assert page.get_by_label("Your message").input_value() == "half-typed", "a refresh never wipes what Jack is typing"
        expect(page.get_by_role("complementary", name="Machine")).to_be_visible()
        page.locator("#machine summary", has_text="Files").click()
        expect(page.locator("#machine")).to_contain_text("skia.linux-x64-gnu.node")      # the file name survives truncation
        expect(page.locator("#machine")).to_contain_text("279.3 MB")                      # sizes in real units, not 286044 KB
        rail = page.get_by_role("complementary", name="Machine")
        assert rail.evaluate("e => e.scrollWidth <= e.clientWidth"), "the machine rail never scrolls sideways"
        shoot(page, "1440-agent")
        page.set_viewport_size({"width": 375, "height": 812})
        assert page.evaluate("document.documentElement.scrollWidth") <= 375
        shoot(page, "375-agent")
        page.set_viewport_size({"width": 1440, "height": 900})
        page.get_by_role("button", name="← All agents").click()
        page.locator("[data-agent='Ada']").click()
        expect(chat.locator(".sys", has_text="what size is the cover?")).to_contain_text("Ada asked Bea")
        page.get_by_role("button", name="← All agents").click()

        # Activity: the whole company's last hour in one place — counts, a feed you can filter, click-through
        page.get_by_role("tab", name="Activity").click()
        feed = page.locator("#feed")
        expect(page.locator("#now")).to_contain_text("Ada")                       # who is working right now
        expect(page.locator("#now")).to_contain_text("build the budget sheet")
        expect(feed).to_contain_text("Bea replied")
        expect(feed).to_contain_text("about half done")
        expect(feed).to_contain_text("You → Bea")                                # the sender is named
        expect(feed).not_to_contain_text("Ada picked up")                        # 13 h ago: outside the last hour
        page.get_by_role("button", name="7d").click()
        expect(feed).to_contain_text("Ada picked up")                            # task steps show up
        expect(feed).to_contain_text("Building the budget formulas")             # and what the agent's machine is doing
        expect(page.locator("#acttasks")).to_contain_text("build the budget sheet")
        page.get_by_role("button", name=re.compile("^Replies")).click()
        expect(feed.locator(".ev")).to_have_count(feed.locator(".ev.t-reply").count())
        expect(feed).not_to_contain_text("changed:")
        page.get_by_role("button", name=re.compile("^Everything")).click()
        expect(feed).to_contain_text("changed:")
        page.get_by_label("Agent", exact=True).select_option("Bea")
        expect(feed).not_to_contain_text("Ada picked up")
        page.get_by_label("Agent", exact=True).select_option("")
        expect(page.get_by_role("button", name="7d")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#sparkl")).to_contain_text("now")
        assert page.locator("#sparkl span").count() >= 10, "a time label on about every other bar"
        assert page.locator("#activity").bounding_box()["width"] > 1300, "the page uses the screen's width"
        mids = [(lambda b: b["y"] + b["height"] / 2)(page.locator(sel).bounding_box()) for sel in ("#ranges", "#customrange", "#act_agent")]
        assert max(mids) - min(mids) < 4, f"time controls sit on one row, no wrapping: {mids}"
        key = page.locator("#actkey"); chart = page.locator("#spark")
        assert key.bounding_box()["x"] > chart.bounding_box()["x"] + chart.bounding_box()["width"] - 1, "the key sits right of the chart"
        assert page.locator("#actcounts").count() == 0 and page.locator("#actfilter").count() == 0, "one key, not three rows of pills"
        assert feed.evaluate("e => getComputedStyle(e).overflowY") == "auto" and feed.bounding_box()["height"] < 900, "the feed scrolls in its own box"
        aa = page.locator("#actagents")
        expect(aa.locator(".aa", has_text="Cy").locator(".dot")).to_have_class(re.compile("s-unresponsive"))
        expect(aa.locator(".aa", has_text="Bea").locator(".dot")).not_to_have_class(re.compile("s-unresponsive"))
        shoot(page, "1440-activity")
        page.get_by_role("button", name="1h").click()
        expect(feed).not_to_contain_text("Ada picked up")
        feed.evaluate("e => { e.scrollTop = e.scrollHeight; e.dispatchEvent(new Event('scroll')); }")
        expect(feed).to_contain_text("Ada picked up")                            # older items load as you scroll
        feed.locator(".ev", has_text="Bea replied").first.click()
        expect(page.locator("#tl")).to_contain_text("about half done")
        page.get_by_role("tab", name="Overview").click()

        # Portfolio: a product with a PM, a project, a task blocked by another
        page.get_by_role("tab", name="Portfolio").click()
        page.get_by_role("button", name="+ Product").click()
        page.get_by_label("Product name").fill("Stickers")
        page.get_by_label("PM").select_option("Bea")
        page.get_by_role("button", name="Create product").click()
        card = page.locator("[data-product]", has_text="Stickers")
        expect(card).to_contain_text("PM Bea")
        card.click()
        page.get_by_role("button", name="+ Project").click()
        page.get_by_label("Project name").fill("launch")
        page.get_by_role("button", name="Add project").click()
        page.get_by_role("button", name="+ Task").click()
        page.get_by_label("Task").fill("draw the sticker sheet")
        page.get_by_label("Role").select_option("designer")
        page.get_by_label("Done when").fill("a 300dpi PNG")
        page.get_by_role("button", name="Add task").click()
        page.get_by_role("button", name="+ Task").click()
        page.get_by_label("Task").fill("write the listing")
        page.get_by_label("Role").select_option("marketer")
        page.get_by_label("Done when").fill("listing live")
        page.get_by_label("Blocked by").select_option(label="draw the sticker sheet")
        page.get_by_role("button", name="Add task").click()
        blocked = page.locator(".col", has_text="Blocked").locator(".tcard", has_text="write the listing")
        expect(blocked).to_contain_text("waits on")
        expect(blocked).to_contain_text("draw the sticker sheet")
        sheet = [t for p in h.board()["products"] if p["name"] == "Stickers" for pr in p["projects"] for t in pr["tasks"]
                 if t["title"] == "draw the sticker sheet"][0]
        h._set("tasks", sheet["id"], status="done")
        page.evaluate("load()")
        expect(blocked).not_to_contain_text("draw the sticker sheet")             # a finished blocker isn't listed
        h._set("tasks", sheet["id"], status="ready")
        page.evaluate("load()")
        expect(page.get_by_role("button", name="Release")).to_have_count(0)
        blocked.click()
        dlg = page.get_by_role("dialog")
        expect(dlg).to_contain_text("write the listing")
        expect(dlg).to_contain_text("listing live")                                # done-when
        expect(dlg).to_contain_text("draw the sticker sheet")                      # what it waits on
        page.keyboard.press("Escape")
        expect(dlg).to_be_hidden()
        page.get_by_role("tab", name="Portfolio").click()
        page.locator("[data-product]", has_text="Shop").click()
        working = page.locator(".col", has_text="Working").locator(".tcard", has_text="build the budget sheet")
        assert working.bounding_box()["height"] < 110, "a card is a title and a headline, not the whole record"
        working.click()
        expect(dlg).to_contain_text("Ada")                                          # who's on it
        expect(dlg).to_contain_text("Building the budget formulas")                 # what they did last
        expect(dlg).to_contain_text("xlsx in the repo")
        expect(dlg.get_by_role("button", name="Release")).to_be_visible()           # the rare action lives here
        page.keyboard.press("Escape")
        shoot(page, "1440-product")

        # Org: seats are interchangeable — Jack steps into the CEO seat
        page.get_by_role("tab", name="Org").click()
        expect(page.locator("#org")).to_contain_text("Board")
        expect(page.locator("#org")).to_contain_text("darragh")
        page.get_by_label("Team for Bea").select_option("marketer")
        expect(page.get_by_text("Bea is on the marketer team")).to_be_visible()
        assert h._agent("Bea")["team"] == "marketer" and h.changes()[0]["by"] == "jack", h.changes()[:1]
        page.get_by_label("CEO").select_option("jack")
        expect(page.get_by_text("CEO is now jack")).to_be_visible()
        assert h._chair() == "jack", h._chair()
        shoot(page, "1440-org")

        # Suggestions: accept the optimizer's idea
        page.get_by_role("tab", name="Suggestions").click()
        row = page.locator(".sug", has_text="bundle the three templates")
        row.get_by_role("button", name="Accept").click()
        expect(row).to_contain_text("accepted")
        shoot(page, "1440-suggestions")
        # Vault: link an Etsy shop — save the app keys, then Connect sends you to Etsy
        page.get_by_role("tab", name="Vault").click()
        page.get_by_label("Etsy keystring").fill("KEY")
        page.get_by_label("Etsy shared secret").fill("SECRET")
        page.get_by_role("button", name="Save app keys").click()
        expect(page.get_by_role("button", name="Connect Etsy")).to_be_visible()
        with page.expect_request(lambda r: r.url.startswith("https://www.etsy.com/oauth/connect")) as go:
            page.route("https://www.etsy.com/**", lambda route: route.fulfill(body="etsy"))
            page.get_by_role("button", name="Connect Etsy").click()
        assert "code_challenge" in go.value.url, go.value.url
        page.go_back()
        page.get_by_role("tab", name="Vault").click()
        shoot(page, "1440-vault")
        page.get_by_role("tab", name="Council").click(); shoot(page, "1440-council")

        # Phone width: every view usable, no sideways scroll of the page
        page.set_viewport_size({"width": 375, "height": 812})
        for t in ("Overview", "Activity", "Portfolio", "Org", "Suggestions", "Council", "Vault"):
            page.get_by_role("tab", name=t).click()
            wide = page.evaluate("document.documentElement.scrollWidth")
            assert wide <= 375, f"{t} scrolls sideways at 375 px ({wide})"
            shoot(page, "375-" + t.lower())
        page.get_by_role("tab", name="Portfolio").click()
        page.locator("[data-product]", has_text="Stickers").click()
        shoot(page, "375-product")
        browser.close()
    srv.shutdown()
    print("ui OK — screenshots in", SHOTS)


if __name__ == "__main__":
    main()
