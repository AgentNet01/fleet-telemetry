#!/usr/bin/env python3
"""Post a pin to the fleet's Pinterest account from the hub machine (fleet tool).

Pinterest walls off the agent VMs (403 Access Denied); the hub machine's home connection gets through.

    fleet tool run pinterest --image <url> --title "<title>" --description "<text>" --link <listing url> --board "<board>"
    fleet tool run pinterest --check          # signed in? which boards? (screenshot in the job's files)

Prints the live pin URL and writes pin.json {"url", "id"} to the job's out folder. On any failure it saves
error.png so you can see what Pinterest showed.

Sign-in: a saved Edge profile in ~/.fleet-pinterest/profile. When it's signed out, the tool signs in with
~/.fleet-pinterest/login.json {"email": ..., "password": ...}, which an operator places once on the hub machine
(the tools account can't read the vault).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request

HOME = os.path.join(os.path.expanduser("~"), ".fleet-pinterest")
OUT = os.environ.get("OUT_DIR") or os.getcwd()


def ensure_deps():
    try:
        import playwright  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("PINTEREST_BOOTSTRAPPED") == "1":
        raise RuntimeError("playwright still missing after install")
    print("[pinterest] installing playwright", file=sys.stderr)
    if subprocess.run([sys.executable, "-m", "pip", "install", "--user", "playwright"]).returncode:
        raise RuntimeError("pip install playwright failed")
    os.environ["PINTEREST_BOOTSTRAPPED"] = "1"
    sys.exit(subprocess.run([sys.executable, os.path.abspath(__file__), *sys.argv[1:]]).returncode)


def fetch(src):
    if os.path.exists(src):
        return src
    ext = os.path.splitext(src.split("?")[0])[1].lower()
    path = os.path.join(tempfile.mkdtemp(), "pin" + (ext if ext in (".png", ".jpg", ".jpeg", ".webp") else ".png"))
    req = urllib.request.Request(src, headers={"User-Agent": "fleet-pinterest/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def signed_in(page):
    page.goto("https://www.pinterest.com/", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    return page.locator('[data-test-id="header-profile"], [data-test-id="header-avatar"]').count() > 0


def sign_in(page):
    login = os.path.join(HOME, "login.json")
    if not os.path.isfile(login):
        raise RuntimeError(f"signed out and there's no {login} on the hub machine: ask an operator to place it "
                           "(it's the pinterest-quietledger vault entry as {\"email\", \"password\"})")
    cred = json.load(open(login))
    page.goto("https://www.pinterest.com/login/", wait_until="domcontentloaded")
    page.fill("#email", cred["email"])
    page.fill("#password", cred["password"])
    page.click('button[type="submit"]')
    page.wait_for_timeout(8000)
    if not signed_in(page):
        raise RuntimeError("sign-in didn't go through (wrong password, a code sent by email, or a CAPTCHA): see error.png")


def boards(page):
    page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
    page.locator('[data-test-id="board-dropdown-select-button"]').click(timeout=30000)
    page.wait_for_timeout(1500)
    rows = page.locator('[data-test-id^="board-row-"]')
    return [rows.nth(i).get_attribute("data-test-id")[len("board-row-"):] for i in range(rows.count())]


def post(page, a):
    page.goto("https://www.pinterest.com/pin-creation-tool/", wait_until="domcontentloaded")
    page.locator('input[type="file"]').first.set_input_files(fetch(a.image), timeout=30000)
    page.wait_for_timeout(5000)                                   # upload preview
    page.fill("#storyboard-selector-title", a.title[:100])
    desc = page.locator('[aria-label="Add a detailed description"], #storyboard-selector-description').first
    desc.click()
    page.keyboard.insert_text(a.description[:500])
    if a.link:
        page.fill("#WebsiteField", a.link)
    page.locator('[data-test-id="board-dropdown-select-button"]').click()
    page.fill("#pickerSearchField", a.board)
    page.wait_for_timeout(1500)
    row = page.locator(f'[data-test-id="board-row-{a.board}"]')
    if not row.count():
        raise RuntimeError(f"no board named {a.board!r}; run with --check to list them")
    row.first.click()
    with page.expect_response(lambda r: "PinResource/create" in r.url, timeout=60000) as resp:
        page.locator('[data-test-id="storyboard-creation-nav-done"] button, [data-test-id="storyboard-creation-nav-done"]').first.click()
    data = resp.value.json()["resource_response"]["data"]
    return {"id": data["id"], "url": f"https://www.pinterest.com/pin/{data['id']}/"}


def main():
    ap = argparse.ArgumentParser(description="Post a pin to the fleet's Pinterest account.")
    ap.add_argument("--check", action="store_true", help="report sign-in and boards, post nothing")
    ap.add_argument("--image")
    ap.add_argument("--title")
    ap.add_argument("--description", default="")
    ap.add_argument("--link", default="")
    ap.add_argument("--board")
    a = ap.parse_args()
    if not a.check and not (a.image and a.title and a.board):
        ap.error("--image, --title and --board are required to post")
    ensure_deps()
    from playwright.sync_api import sync_playwright
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(os.path.join(HOME, "profile"), channel="msedge", headless=True,
                                                   viewport={"width": 1400, "height": 1000}, locale="en-US")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            if not signed_in(page):
                sign_in(page)
            if a.check:
                result = {"signed_in": True, "boards": boards(page)}
                page.screenshot(path=os.path.join(OUT, "check.png"))
            else:
                result = post(page, a)
            json.dump(result, open(os.path.join(OUT, "check.json" if a.check else "pin.json"), "w"))
            print(json.dumps(result))
            return 0
        except Exception as e:
            page.screenshot(path=os.path.join(OUT, "error.png"))
            print(f"[pinterest] failed: {e}", file=sys.stderr)
            return 1
        finally:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
