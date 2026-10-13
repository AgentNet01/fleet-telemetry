"""The 3D office in a real browser (Playwright, Chromium with software WebGL), used the way Jack uses it.

    python3 test_office3d.py toggle | people | camera | head | webcam | shots
"""
import os
import sys

from playwright.sync_api import sync_playwright

from test_ui import PASSWORD, SHOTS, seeded

GL = []   # headless Chromium already gives WebGL in software; forcing ANGLE/SwiftShader for everything dropped the whole page to ~1 frame a second
FAKE_CAM = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


class Office:
    """The Overview with the 3D switch pressed."""

    def __init__(self, pw, query="", args=()):
        self.h, self.srv, url = seeded()
        self.browser = pw.chromium.launch(args=[*GL, *args])
        ctx = self.browser.new_context(viewport={"width": 1440, "height": 900}, http_credentials={"username": "jack", "password": PASSWORD},
                                       permissions=["camera"] if args else [])
        self.page = page = ctx.new_page()
        self.log = []
        page.on("console", lambda m: self.log.append(f"{m.type}: {m.text}"))
        page.on("pageerror", lambda e: self.log.append(f"pageerror: {e}"))
        page.set_default_timeout(5000)
        page.goto(url + query)
        page.locator("[data-agent='Ada']").wait_for(state="attached")
        self.switch = page.locator("#o3d")
        assert self.switch.count() == 1, "3D switch missing"
        self.switch.click()
        try:
            page.wait_for_function("window.Office3D && Office3D.debug.state().ready", timeout=30000)
        except Exception:
            raise AssertionError("the 3D office never became ready:\n" + "\n".join(self.log[-15:]))
        page.wait_for_timeout(500)

    def js(self, expr):
        return self.page.evaluate(expr)

    def state(self):
        return self.js("Office3D.debug.state()")

    def at(self, xy):                      # office-relative css px → page px
        b = self.page.locator("#office").bounding_box()
        return b["x"] + xy[0], b["y"] + xy[1]

    def errors(self):
        return [l for l in self.log if l.startswith(("pageerror", "error"))]


def toggle(pw):
    o = Office(pw)
    page = o.page
    assert page.locator("#office3dcv").is_visible(), "a WebGL canvas fills the office"
    colours = o.js("Office3D.debug.sample()")
    assert colours > 12, f"the scene is lit and varied, not blank: {colours} colours"
    hud = page.locator("#ohud").inner_text()
    assert "working" in hud and "on break" in hud, f"the HUD still counts: {hud}"
    assert o.switch.inner_text().strip() == "2D", "the switch now offers the way back"
    o.switch.click()
    page.wait_for_function("!window.Office3D")
    page.wait_for_timeout(400)
    assert page.locator("#office3dcv").count() == 0, "the WebGL canvas is gone"
    assert o.js("!!Office.debug.cache"), "the 2D office is drawing again"
    assert not o.errors(), o.errors()


def people(pw):
    o = Office(pw)
    page = o.page
    names = sorted(a["name"] for a in o.js("board.agents"))
    assert sorted(o.state()["rigs"]) == names, f"one figure per agent: {o.state()['rigs']} vs {names}"
    ada = o.js("(() => { const p = Office.debug.people.get('Ada'); return { x: p.x, y: p.y, group: p.slot && p.slot.group, mode: p.mode }; })()")
    assert ada["mode"] == "work" and ada["group"] == "desk", f"the sim still puts Ada at a desk: {ada}"
    rig = o.js("Office3D.debug.rig('Ada')")
    assert abs(rig["x"] - ada["x"]) < .05 and abs(rig["y"] - ada["y"]) < .05, f"her figure is where the sim has her: {rig} vs {ada}"
    assert rig["parts"] >= 10, f"a figure is built from many cubes: {rig['parts']}"
    head = o.js("Office3D.debug.head('Ada')")
    page.mouse.move(*o.at(head))
    page.wait_for_timeout(200)
    assert "Ada" in page.locator("#otip").inner_text(), "hovering her shows her tooltip"
    page.mouse.click(*o.at(head))
    page.locator("#detail").wait_for(state="visible")
    assert "Ada" in page.locator("#detail").inner_text(), "clicking her opens her page"
    assert not o.errors(), o.errors()


def camera(pw):
    o = Office(pw)
    page = o.page
    spot = "Office3D.debug.project(10, 5, 0)"
    p0, c0 = o.js(spot), o.state()["cam"]
    box = page.locator("#office").bounding_box()
    cx, cy = box["x"] + box["width"] * .5, box["y"] + box["height"] * .6
    page.mouse.move(cx, cy); page.mouse.down(); page.mouse.move(cx + 240, cy, steps=8); page.mouse.up()
    page.wait_for_timeout(700)
    p1, c1 = o.js(spot), o.state()["cam"]
    assert abs(c1["yaw"] - c0["yaw"]) > .2, f"dragging orbits: yaw {c0['yaw']} → {c1['yaw']}"
    assert abs(p1[0] - p0[0]) + abs(p1[1] - p0[1]) > 30, f"the floor moved on screen: {p0} → {p1}"
    page.keyboard.down("Control"); page.mouse.wheel(0, -400); page.keyboard.up("Control")
    page.wait_for_timeout(700)
    c2 = o.state()["cam"]
    assert c2["dist"] < c1["dist"] * .9, f"the wheel zooms in: {c1['dist']} → {c2['dist']}"
    page.keyboard.down("w"); page.wait_for_timeout(500); page.keyboard.up("w")
    page.wait_for_timeout(500)
    c3 = o.state()["cam"]
    moved = sum(abs(a - b) for a, b in zip(c3["target"], c2["target"]))
    assert moved > .5, f"W walks the view forward: {c2['target']} → {c3['target']}"
    page.locator("#ozfit").click()
    page.wait_for_timeout(1200)
    p4 = o.js(spot)
    assert abs(p4[0] - p0[0]) < 2 and abs(p4[1] - p0[1]) < 2, f"Fit puts the view back: {p0} vs {p4}"
    assert not o.errors(), o.errors()


def views(pw):
    import math
    o = Office(pw)
    page = o.page
    press = lambda title: page.mouse.click(*o.js(f"(() => {{ const r = document.querySelector('.ocube button[title=\"{title}\"]').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()"))   # a real click where the face is drawn
    press("View from top")
    page.wait_for_timeout(900)
    c = o.state()["cam"]
    assert c["pitch"] > 1.4, f"the cube's Top looks straight down: {c}"
    page.locator("#ozfit").click()            # from straight above the side faces are edge-on: go back to the corner view, where Right can be seen
    page.wait_for_timeout(900)
    press("View from right")
    page.wait_for_timeout(900)
    c = o.state()["cam"]
    assert abs(c["yaw"] - math.pi / 2) < .05 and c["pitch"] < .3, f"the cube's Right stands on the right, level: {c}"
    box = page.locator("#office").bounding_box()
    page.mouse.move(box["x"] + box["width"] * .5, box["y"] + box["height"] * .6)
    page.mouse.wheel(300, 0)
    page.wait_for_timeout(700)
    d = o.state()["cam"]
    assert abs(d["target"][2] - c["target"][2]) > .5 and abs(d["yaw"] - c["yaw"]) < .01 and abs(d["dist"] - c["dist"]) < .01, f"a sideways two-finger swipe slides the camera, nothing else: {c} → {d}"
    o.page.locator("#office").screenshot(path=os.path.join(SHOTS, "3d-cube.png"))
    o.switch.click()
    page.wait_for_function("!window.Office3D")
    assert page.locator(".ocube").count() == 0, "the cube leaves with the 3D view"
    assert not o.errors(), o.errors()


def fills(pw):
    o = Office(pw)
    page = o.page
    assert o.js("document.documentElement.scrollHeight <= innerHeight"), "the office fills the window: the page has nowhere to scroll"
    z0 = o.state()["cam"]["dist"]
    box = page.locator("#office").bounding_box()
    page.mouse.move(box["x"] + box["width"] * .5, box["y"] + box["height"] * .6)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(700)
    assert o.state()["cam"]["dist"] < z0 * .9, "with no page to scroll, a plain scroll zooms"
    page.locator("#olist").click()
    assert page.locator("#office").is_hidden(), "List puts the office away"
    assert page.locator("[data-agent='Ada']").first.is_visible(), "and shows the agents as a list"
    page.locator("#ooffice").click()
    assert page.locator("#office").is_visible() and page.locator("#roster").is_hidden(), "and back again"
    assert o.js("document.documentElement.scrollHeight <= innerHeight"), "still nothing to scroll"
    assert not o.errors(), o.errors()


def head(pw):
    o = Office(pw)
    a = o.js("Office3D.debug.probe()")
    o.js("Office3D.debug.setHead(.5, 0, 1)")
    o.page.wait_for_timeout(1200)
    b = o.js("Office3D.debug.probe()")
    assert abs(b["plane"][0] - a["plane"][0]) < 1.5 and abs(b["plane"][1] - a["plane"][1]) < 1.5, f"the screen plane stays put: {a['plane']} → {b['plane']}"
    assert b["near"][0] < a["near"][0] - 5, f"head right → nearer things slide left: {a['near']} → {b['near']}"
    assert b["far"][0] > a["far"][0] + 5, f"head right → farther things slide right: {a['far']} → {b['far']}"
    o.js("Office3D.debug.setHead(0, .5, 1)")
    o.page.wait_for_timeout(1200)
    c = o.js("Office3D.debug.probe()")
    assert c["near"][1] > a["near"][1] + 5, f"head up → nearer things slide down: {a['near']} → {c['near']}"
    assert not o.errors(), o.errors()


def webcam(pw):
    o = Office(pw, args=FAKE_CAM)
    page = o.page
    btn = page.locator("#ohead")
    assert btn.is_visible(), "Look around shows in 3D"
    btn.click()
    page.wait_for_function("/loading|tracking/.test(Office3D.debug.state().head) && Office3D.debug.state().video", timeout=10000)
    assert btn.get_attribute("aria-pressed") == "true", "the button shows the camera is on"
    btn.click()
    page.wait_for_function("Office3D.debug.state().head === 'off' && !Office3D.debug.state().video")
    assert btn.get_attribute("aria-pressed") == "false"
    assert not [e for e in o.errors() if "mediapipe" not in e.lower() and "tflite" not in e.lower() and "Failed to load resource" not in e], o.errors()


def shots(pw):
    os.makedirs(SHOTS, exist_ok=True)
    for name, query, setup in [
        ("3d-day", "?officeHour=.2", None),
        ("3d-night", "?officeHour=.75", None),
        ("3d-close", "?officeHour=.2", "Office3D.debug.view({ target: [4.5, 0.6, 3.2], dist: 9, yaw: 0.55, pitch: 0.5 })"),
        ("3d-kitchen", "?officeHour=.2", "Office3D.debug.view({ target: [3.5, 0.6, 8.6], dist: 10, yaw: 1.05, pitch: 0.55 })"),
        ("3d-orbit", "?officeHour=.2", "Office3D.debug.view({ yaw: -0.5, pitch: 0.42 })"),
        ("3d-patio-night", "?officeHour=.75", "Office3D.debug.view({ target: [17.5, 0.6, 6], dist: 13, yaw: 0.2, pitch: 0.45 })"),
        ("3d-head", "?officeHour=.2", "Office3D.debug.setHead(.8, .3, .8)"),
    ]:
        o = Office(pw, query)
        if setup:
            o.js(setup)
        o.page.wait_for_timeout(2500)
        path = os.path.join(SHOTS, name + ".png")
        o.page.locator("#office").screenshot(path=path)
        assert os.path.getsize(path) > 30000, f"{name} is a real picture"
        assert o.js("Office3D.debug.sample()") > 12, f"{name} is not blank"
        assert not o.errors(), o.errors()
        o.browser.close()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    with sync_playwright() as pw:
        {"toggle": toggle, "people": people, "camera": camera, "views": views, "fills": fills, "head": head, "webcam": webcam, "shots": shots}[mode](pw)
    print("ok", mode)
