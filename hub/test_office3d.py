"""The 3D office in a real browser (Playwright, Chromium with software WebGL), used the way Jack uses it.

    python3 test_office3d.py toggle | cat | people | camera | views | fills | shrine | head | webcam | lean | steady | eyes | shots
"""
import os
import subprocess
import sys
import tempfile
import urllib.request

from playwright.sync_api import sync_playwright

from test_ui import PASSWORD, SHOTS, seeded

GL = []   # headless Chromium already gives WebGL in software; forcing ANGLE/SwiftShader for everything dropped the whole page to ~1 frame a second
FAKE_CAM = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"]


FACE_URL = "https://storage.googleapis.com/mediapipe-assets/portrait.jpg"   # MediaPipe's public sample face, looking at the lens


def face_cam(name, parts, grain=0):
    """Browser flags for a webcam that shows a real face. parts: [(seconds, how much nearer than the first part)], looped.
    grain: sensor noise, different on every frame (0 = a perfectly clean camera)."""
    d = os.path.join(tempfile.gettempdir(), "office3d-face"); os.makedirs(d, exist_ok=True)
    photo, clip = os.path.join(d, "portrait.jpg"), os.path.join(d, name + ".y4m")      # raw video: the headless browser cannot decode a compressed camera file
    if not os.path.exists(photo):
        urllib.request.urlretrieve(FACE_URL, photo)
    if not os.path.exists(clip):
        W, H, FPS = 480, 270, 5
        with open(clip + ".part", "wb") as f:
            f.write(f"YUV4MPEG2 W{W} H{H} F{FPS}:1 Ip A1:1 C420jpeg\n".encode())
            for secs, z in parts:              # the face stays centred; nearer = the same photo cropped tighter
                w, h = round(1066 / z), round(600 / z)
                raw = subprocess.run(["ffmpeg", "-v", "error", "-loop", "1", "-t", str(secs), "-r", str(FPS), "-i", photo, "-vf",
                                      f"pad=1400:1400:290:300:gray,crop={w}:{h}:{690 - w // 2}:{470 - h // 2},scale={W}:{H}" + (f",noise=alls={grain}:allf=t" if grain else ""),
                                      "-pix_fmt", "yuv420p", "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
                size = W * H * 3 // 2
                f.write(b"".join(b"FRAME\n" + raw[i:i + size] for i in range(0, len(raw), size)))
        os.replace(clip + ".part", clip)
    return [*FAKE_CAM, "--use-file-for-fake-video-capture=" + clip]


class Office:
    """The Overview, which is the 3D office (Jack, Oct 14: the flat one is gone)."""

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

    def errors(self, tracker=True):        # tracker=False: leave out what the face tracker's own wasm prints (it logs its start-up notes as errors)
        chatter = ("mediapipe", "tflite", "tensorflow", "failed to load resource")
        return [l for l in self.log if l.startswith(("pageerror", "error")) and (tracker or not any(c in l.lower() for c in chatter))]


def toggle(pw):
    o = Office(pw)
    page = o.page
    assert page.locator("#office3dcv").is_visible(), "a WebGL canvas fills the office"
    assert page.locator("#o3d").count() == 0, "no switch back to a flat office"
    colours = o.js("Office3D.debug.sample()")
    assert colours > 12, f"the scene is lit and varied, not blank: {colours} colours"
    hud = page.locator("#ohud").inner_text()
    assert "working" in hud and "on break" in hud, f"the HUD still counts: {hud}"
    assert not o.errors(), o.errors()


def cat(pw):
    """Jack, Oct 14: dot only writes reports now, so in the office it is the office cat."""
    o = Office(pw)
    dot = o.js("(() => { const p = Office.debug.people.get('dot'); return { cat: !!p.cat, mode: p.mode, group: p.slot && p.slot.group, hold: Object.keys(p.hold || {}).length, conv: !!p.conv }; })()")
    assert dot["cat"] and dot["mode"] == "idle" and dot["hold"] == 0 and not dot["conv"], f"dot roams as a cat, holding nothing: {dot}"
    assert dot["group"] not in ("ceo", "desk", "board", "review"), f"the cat doesn't sit at anyone's desk: {dot}"
    cat_parts, ada_parts = o.js("Office3D.debug.rig('dot')")["parts"], o.js("Office3D.debug.rig('Ada')")["parts"]
    assert 8 <= cat_parts < ada_parts, f"a small cube cat, not a person: {cat_parts} cubes vs Ada's {ada_parts}"
    assert o.js("!!Office3D.debug.head('dot')"), "the cat has a spot for its name label"
    o.page.locator("#office").screenshot(path=os.path.join(SHOTS, "3d-cat.png"))
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


def shrine(pw):
    """Jack, Oct 15: the whole page is the office under a ☰ menu, and what needs him is a shrine in the corner by the pool:
    the agent who needs him carries a paper over, sets it down, does a little prayer dance, the shrine lights up, and a
    small number above it says how many things wait. Clicking the number opens the list."""
    o = Office(pw, "?officeHour=.2")
    page = o.page
    b = page.locator("#office").bounding_box()
    assert (b["x"], b["y"], b["width"], b["height"]) == (0, 0, 1440, 900), f"the office is the whole window: {b}"
    assert page.locator(".top").is_hidden() and page.locator("#tabs").is_hidden(), "no header or tab bar over the office"
    page.locator(".omenu").click()
    assert page.get_by_role("tab", name="Activity").is_visible(), "☰ opens the pages"
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    assert page.get_by_role("tab", name="Activity").is_hidden(), "Escape puts the menu away"
    xy = o.js("(() => { const s = Office.sim.SHRINE; return Office3D.debug.project(s.x + .4, s.y + .4, .4); })()")
    page.mouse.click(*xy)
    page.wait_for_timeout(300)
    assert page.locator("#needs").is_visible(), "clicking the shrine itself opens what needs Jack"
    page.locator(".top .menubtn").click()
    page.get_by_role("tab", name="Overview").click()
    assert o.js("Office.sim.OBJ.shrine.n") == 0 and not o.js("Office.debug.SLOTS.shrine[0].by"), "nothing waits on Jack yet"

    o.h.jack_add("Cy", "Add a card to the Etsy shop", "listing fees", "https://www.etsy.com/your/account/payments")
    page.wait_for_function("Office.sim.OBJ.shrine.n === 1", timeout=15000)
    page.wait_for_function("(p => p && p.activity === 'shrine' && p.hold.L === 'paper')(Office.debug.people.get('Cy'))", timeout=10000)
    o.js("Office3D.debug.view({ target: [17.2, 0.8, 15.0], dist: 7, yaw: 2.6, pitch: 0.45 })")
    page.wait_for_function("(p => p.clip === 'pray')(Office.debug.people.get('Cy'))", timeout=60000)
    at = o.js("(() => { const p = Office.debug.people.get('Cy'), s = Office.debug.SLOTS.shrine[0]; return [Math.hypot(p.x - s.x, p.y - s.y), p.dir]; })()")
    assert at[0] < .1 and at[1] == "SW", f"Cy prays at the shrine, facing it (it faces into the office): {at}"
    page.wait_for_timeout(1500)
    page.locator("#office").screenshot(path=os.path.join(SHOTS, "3d-shrine.png"))
    page.wait_for_function("Office.sim.OBJ.shrine.flash > 0 && Office.debug.people.get('Cy').activity !== 'shrine'", timeout=20000)
    assert not o.js("Office.debug.SLOTS.shrine[0].by"), "Cy leaves the shrine for the next one"

    xy = o.js("Office3D.debug.project(...Office.sim.SHRINE.count)")
    page.mouse.click(xy[0], xy[1] - 10)
    page.wait_for_timeout(300)
    assert page.locator("#needs").is_visible() and "Add a card to the Etsy shop" in page.locator("#nj").inner_text(), "the number opens what needs Jack"
    assert page.locator(".top").is_visible(), "the other pages keep a light header with the ☰"
    page.locator(".top .menubtn").click()
    page.get_by_role("tab", name="Overview").click()
    assert page.locator("#office").bounding_box()["height"] == 900, "and back to the office, edge to edge"
    assert not o.errors(), o.errors()


def lean(pw):
    o = Office(pw, args=face_cam("lean", [(16, 1), (16, 1.3)]))       # a real face that sits, then comes 1.3× nearer, and back
    page = o.page
    d0 = o.state()["cam"]["dist"]
    page.locator("#ohead").click()
    page.wait_for_function("Office3D.debug.state().head === 'tracking'", timeout=90000)
    page.wait_for_function("Math.abs(Office3D.debug.state().lean - 1) > .17", timeout=60000)
    page.wait_for_timeout(1500)
    s = o.state()
    near = s["lean"] < 1                                              # tracking may have started on either part of the clip
    true = 1 / 1.3 if near else 1.3
    assert abs(s["lean"] / true - 1) < .08, f"the distance read from the face is within 8% of the truth ({true:.3f}): {s['lean']:.3f}"
    want = d0 / min(8, max(.5, s["lean"] ** -3))
    assert abs(s["cam"]["dist"] / want - 1) < .12, f"leaning {'in' if near else 'back'} moves the camera with the cube of the lean: {d0:.1f} → {s['cam']['dist']:.1f}, expected {want:.1f}"
    assert near and s["cam"]["dist"] < d0 * .55 or not near and s["cam"]["dist"] > d0 * 1.6, "…and that is a big move, not a nudge"
    page.locator(".ohome").click()                                    # Home: where the face is now becomes the resting distance
    page.wait_for_function("Math.abs(Office3D.debug.state().lean - 1) < .04 && Math.abs(Office3D.debug.state().cam.dist / %f - 1) < .06" % d0, timeout=9000)
    assert not o.errors(tracker=False), o.errors(tracker=False)
    print(f"  lean read {s['lean']:.3f} (truth {true:.3f}); camera {d0:.1f} → {s['cam']['dist']:.1f}")


def steady(pw):
    import statistics
    o = Office(pw, args=face_cam("grainy", [(12, 1)], grain=14))       # a still face through a noisy camera: every frame differs
    page = o.page
    page.locator("#ohead").click()
    page.wait_for_function("Office3D.debug.state().head === 'tracking' && Office3D.debug.state().eyes", timeout=90000)
    page.wait_for_timeout(4000)
    rows = []
    for _ in range(40):
        s = o.state(); rows.append((s["cam"]["dist"], s["eyes"][0], s["eyes"][1])); page.wait_for_timeout(200)
    dist, px, py = zip(*rows)
    shimmer = statistics.pstdev(dist) / statistics.mean(dist)
    assert shimmer < .01, f"sitting still, the zoom does not breathe: the camera distance wanders {shimmer:.2%}"
    assert statistics.pstdev(px) < 1 and statistics.pstdev(py) < 1, f"sitting still, the eye reading holds within 1 cm: {statistics.pstdev(px):.2f}, {statistics.pstdev(py):.2f}"
    assert not o.errors(tracker=False), o.errors(tracker=False)
    print(f"  through a noisy camera: zoom wanders {shimmer:.2%}; eye reading wanders {statistics.pstdev(px):.2f} cm across, {statistics.pstdev(py):.2f} cm up-down")


def eyes(pw):
    o = Office(pw, args=face_cam("still", [(20, 1)]))
    page = o.page
    page.locator("#ohead").click()
    page.wait_for_function("Office3D.debug.state().head === 'tracking'", timeout=90000)
    page.wait_for_function("Office3D.debug.state().eyes", timeout=30000)
    real = o.state()["eyes"]
    assert abs(real[0]) < 8 and abs(real[1]) < 8, f"a real face looking at the lens reads as looking near the lens (cm): {real[:2]}"
    # A photo cannot move its eyes, so from here the eye reading is supplied: eyes whose sight line lands (x-700)/45 cm right, (40-y)/45 cm up of the lens for screen spot (x, y)
    look_at = lambda x, y, shake=(0, 0): o.js(f"Office3D.debug.setEyes([{(x - 700) / 45 + shake[0]}, {(40 - y) / 45 + shake[1]}, 0, 0])")
    centre = lambda sel: o.js(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; }})()")
    btn = page.locator("#oeyes")
    assert btn.is_visible() and "Calibrate" in btn.inner_text(), "with a face in view, eye calibration is offered"
    btn.click()
    shakes = [(.2, -.1), (-.25, .15), (.1, .25), (-.15, -.2), (.25, .05), (-.05, -.25), (.15, .2), (-.2, .1), (.05, -.15)]     # ±0.25 cm of unsteadiness
    for k in range(9):
        assert f"{k + 1} of 9" in page.locator(".ocal").inner_text()
        x, y = centre(".ocalspot")
        look_at(x, y, shakes[k])
        page.mouse.click(x, y)
    page.locator(".ocal").wait_for(state="detached")
    cal = o.state()["cal"]
    assert 3 < cal["err"] < 30, f"the miss it reports matches the ±0.25 cm (±11 px) put in: {cal['err']:.1f} px"
    assert f"±{round(cal['err'])} px" in btn.inner_text(), f"the button shows that miss: {btn.inner_text()}"
    while "off" not in page.locator("#olab").inner_text():
        page.locator("#olab").click()
    inked = lambda: o.js("(() => { const c = document.getElementById('officecv'), d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 200) n++; return n; })()")
    box = page.locator("#office").bounding_box()
    look_at(box["x"] + 40, box["y"] + box["height"] - 120)             # an empty corner
    page.wait_for_timeout(1200)
    assert o.state()["gazed"] is None and inked() == 0, "looking at nobody, with labels off: no label"
    for name in ["Ada", "Bea", "Cy", "dot"]:
        look_at(*o.at(o.js(f"Office3D.debug.head('{name}')")))
        page.wait_for_function(f"Office3D.debug.state().gazed === '{name}'", timeout=6000)
        gx, gy = o.state()["gaze"]; hx, hy = o.at(o.js(f"Office3D.debug.head('{name}')"))
        assert abs(gx - hx) < 12 and abs(gy - hy) < 12, f"the gaze point lands on {name}'s head: {(gx, gy)} vs {(hx, hy)}"
        page.wait_for_timeout(400)
        assert inked() > 300, f"looking at {name} brings up their label"
    page.screenshot(path=os.path.join(SHOTS, "3d-eyes.png"))
    look_at(box["x"] + 40, box["y"] + box["height"] - 120)
    page.wait_for_function("Office3D.debug.state().gazed === null", timeout=6000)
    page.wait_for_timeout(400)
    assert inked() == 0, "looking away takes the label down again"
    assert not o.errors(tracker=False), o.errors(tracker=False)
    print(f"  real face reads {real[0]:.1f}, {real[1]:.1f} cm from the lens; calibration miss {cal['err']:.1f} px")


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
    assert not o.errors(tracker=False), o.errors(tracker=False)


def shots(pw):
    os.makedirs(SHOTS, exist_ok=True)
    for name, query, setup in [
        ("3d-day", "?officeHour=.2", None),
        ("3d-night", "?officeHour=.75", None),
        ("3d-close", "?officeHour=.2", "Office3D.debug.view({ target: [4.5, 0.6, 3.2], dist: 9, yaw: 0.55, pitch: 0.5 })"),
        ("3d-kitchen", "?officeHour=.2", "Office3D.debug.view({ target: [3.5, 0.6, 13.6], dist: 10, yaw: 1.05, pitch: 0.55 })"),
        ("3d-orbit", "?officeHour=.2", "Office3D.debug.view({ yaw: -0.5, pitch: 0.42 })"),
        ("3d-patio-night", "?officeHour=.75", "Office3D.debug.view({ target: [22.5, 0.6, 9], dist: 15, yaw: 0.2, pitch: 0.45 })"),
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
        {"toggle": toggle, "cat": cat, "people": people, "camera": camera, "views": views, "fills": fills, "shrine": shrine, "lean": lean, "steady": steady, "eyes": eyes, "head": head, "webcam": webcam, "shots": shots}[mode](pw)
    print("ok", mode)
