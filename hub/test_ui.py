"""The dashboard in a real browser (Playwright, Chromium), driven the way Jack uses it.

    python3 test_ui.py          # creates product → project → blocked task, checks agent cards,
                                # changes the CEO seat, accepts a suggestion; saves screenshots
                                # at 1440 and 375 px to hub/ui-shots/
"""
import os
import re
import tempfile
import threading

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
        page = browser.new_page(viewport={"width": 1440, "height": 900}, http_credentials={"username": "jack", "password": PASSWORD})
        page.set_default_timeout(4000)
        page.goto(url)

        # Overview: agent cards say product, role, held task and how long they've been free
        ada = page.locator("[data-agent='Ada']")
        expect(ada).to_contain_text("Shop · engineer")
        expect(ada).to_contain_text("build the budget sheet")
        expect(page.locator("[data-agent='Bea']")).to_contain_text(re.compile(r"free 13h"))
        expect(page.locator("#changes")).to_contain_text('product set "Shop" metric')
        shoot(page, "1440-overview")

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
        shoot(page, "1440-product")

        # Org: seats are interchangeable — Jack steps into the CEO seat
        page.get_by_role("tab", name="Org").click()
        expect(page.locator("#org")).to_contain_text("Board")
        expect(page.locator("#org")).to_contain_text("darragh")
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
        for t in ("Overview", "Portfolio", "Org", "Suggestions", "Council", "Vault"):
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
