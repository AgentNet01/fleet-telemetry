"""Tools: the fleet's own code run on the hub machine, one job at a time, never at the hub's expense.

    python3 test_tools.py run      # an agent runs a tool: log and files come back, and it's told once when it ends
    python3 test_tools.py guards   # low disk refuses; running past the limit or the disk filling stops it; no escapes
    python3 test_tools.py cli      # fleet tools / tool run / tool get, end to end over HTTP
    python3 test_tools.py ui       # Jack sees the tools and what ran on the machine, who ran it, and how it ended
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

import hub
import tools_runner
from test_autonomy import new_hub

HELLO = """import os, sys
print("making", *sys.argv[1:])
os.makedirs("img", exist_ok=True)
open(os.path.join(os.environ["OUT_DIR"], "img", "card.png"), "wb").write(b"PNG" * 10)
"""
SLOW = "import time\nprint('working', flush=True)\ntime.sleep(60)\n"

def open_page(page, name):
    """The pages live in the ☰ menu (Jack, Oct 15: the office is the whole page)."""
    page.locator(".menubtn:visible").first.click()
    page.get_by_role("tab", name=name).click()



def world():
    """A hub whose jobs folder is fresh, and a repo with two tools in it."""
    h, muse, clock = new_hub("Ada")
    h.jobs_dir, repo = tempfile.mkdtemp(), tempfile.mkdtemp()
    for name, code in (("hello", HELLO), ("slow", SLOW)):
        os.makedirs(os.path.join(repo, "tools", name))
        open(os.path.join(repo, "tools", name, "run.py"), "w").write(code)
    open(os.path.join(repo, "tools", "hello", "README.md"), "w").write("# Makes a birthday card\n")
    return h, muse, tools_runner.Runner(h.jobs_dir, repo=repo, pull=False)


def run():
    h, muse, r = world()
    jid = h.tool_run("Ada", "hello", ["sweet", "16"])
    assert h.tool_job(jid)["status"] == "queued"
    assert r.run_once() and not r.run_once(), "run: one job, then nothing queued"
    j = h.tool_job(jid)
    assert j["status"] == "done" and j["by"] == "Ada", j
    assert "making sweet 16" in j["log"], j["log"]
    assert j["files"] == [{"path": "img/card.png", "size": 30}], j["files"]
    assert open(h.tool_file(jid, "img/card.png"), "rb").read() == b"PNG" * 10
    assert h.tools() == [{"name": "hello", "about": "Makes a birthday card"}, {"name": "slow", "about": ""}], h.tools()
    h.tick(); h.tick()
    told = [s for s in muse.sent.get("Ada", []) if f"job {jid} done" in s]
    assert len(told) == 1, f"run: Ada told once that it finished: {muse.sent.get('Ada')}"
    print("run OK")


def images():
    """Jack, Oct 14: he couldn't see anything the hub's GPU made. The Images tab lists every picture a finished job
    made, newest first, with who asked and what for; nothing else from the jobs folder."""
    h, muse, r = world()
    first = h.tool_run("Ada", "hello", ["sweet", "16"]); r.run_once()
    second = h.tool_run("Ada", "hello", ["21st", "birthday"]); r.run_once()
    open(os.path.join(h.jobs_dir, str(second), "out", "notes.txt"), "w").write("not a picture")
    got = h.images()
    assert [(g["job"], g["path"]) for g in got] == [(second, "img/card.png"), (first, "img/card.png")], \
        f"images: each job's pictures, newest job first, no other files: {got}"
    assert got[0]["by"] == "Ada" and "21st birthday" in got[0]["prompt"], f"images: who asked and what for: {got[0]}"

    import base64, threading, urllib.error, urllib.request
    srv = hub.serve(h, "127.0.0.1", 0, "pw")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    def get(path, auth=True):
        req = urllib.request.Request(base + path, headers={"Authorization": "Basic " + base64.b64encode(b"jack:pw").decode()} if auth else {})
        try:
            r = urllib.request.urlopen(req, timeout=10)
            return r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            return e.code, None, b""
    code, kind, body = get(f"/api/jack/image?job={second}&path=img/card.png")
    assert (code, kind, body) == (200, "image/png", b"PNG" * 10), f"images: Jack opens a picture in the browser: {code} {kind}"
    assert get(f"/api/jack/image?job={second}&path=../job.json")[0] == 404, "images: nothing outside the job's pictures"
    assert get(f"/api/jack/image?job={second}&path=notes.txt")[0] == 404, "images: only pictures"
    assert get(f"/api/jack/image?job={second}&path=img/card.png", auth=False)[0] == 401, "images: only Jack"
    srv.shutdown()

    # Jack, Oct 14: pasting a picture into a reply. Muse chat carries text only, so the agent downloads it.
    cmd = h.jack_file("../Screen Shot.png", b"PNG!")
    jid, name = cmd.split()[3:]
    assert cmd.startswith("fleet tool get ") and name == "Screen_Shot.png", f"files: a safe name in the job's folder: {cmd}"
    assert open(h.tool_file(int(jid), name), "rb").read() == b"PNG!", "files: the agent gets back what Jack pasted"
    assert not h._watch_jobs() and (int(jid), name) in [(g["job"], g["path"]) for g in h.images()], "files: shows with the pictures"
    print("images OK")


def guards():
    h, muse, r = world()
    r.free_disk = lambda: 8 * tools_runner.GB
    jid = h.tool_run("Ada", "hello")
    r.run_once()
    assert h.tool_job(jid)["status"] == "refused" and "8 GB" in h.tool_job(jid)["note"], h.tool_job(jid)

    r.free_disk = lambda: 50 * tools_runner.GB
    jid = h.tool_run("Ada", "slow", timeout=2)
    t0 = time.time(); r.run_once()
    assert h.tool_job(jid)["status"] == "stopped" and "limit" in h.tool_job(jid)["note"] and time.time() - t0 < 10, h.tool_job(jid)

    disk = iter([50, 50, 4] + [4] * 100)
    r.free_disk = lambda: next(disk) * tools_runner.GB
    jid = h.tool_run("Ada", "slow", timeout=60)
    t0 = time.time(); r.run_once()
    assert h.tool_job(jid)["status"] == "stopped" and "disk" in h.tool_job(jid)["note"] and time.time() - t0 < 10, h.tool_job(jid)

    r.free_disk = lambda: 50 * tools_runner.GB
    jid = h.tool_run("Ada", "nope")
    r.run_once()
    assert h.tool_job(jid)["status"] == "failed" and "tools/nope/run.py" in h.tool_job(jid)["note"]
    for bad in ("../hub", "Hello", "a b", ""):
        try:
            h.tool_run("Ada", bad)
            raise AssertionError(f"guards: tool name {bad!r} accepted")
        except ValueError:
            pass
    jid = h.tool_run("Ada", "hello"); r.run_once()
    for bad in ("../job.json", "../../x", "/etc/passwd", "img/../../status.json"):
        try:
            h.tool_file(jid, bad)
            raise AssertionError(f"guards: {bad} served")
        except ValueError:
            pass
    print("guards OK")


def cli():
    h, muse, r = world()
    tok = h.add_agent("Ada", "muse")
    srv = hub.serve(h, "127.0.0.1", 0, "pw")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    threading.Thread(target=lambda: [r.run_once() or time.sleep(0.2) for _ in iter(int, 1)], daemon=True).start()
    home = tempfile.mkdtemp()
    env = dict(os.environ, FLEET_HUB=f"http://127.0.0.1:{srv.server_address[1]}", FLEET_TOKEN=tok, FLEET_HOME=home)
    here = os.path.dirname(os.path.abspath(__file__))
    fleet = lambda *a: subprocess.run([sys.executable, os.path.join(here, "fleet.py"), *a], env=env, cwd=home,
                                      capture_output=True, text=True, timeout=60)
    r.list_tools()
    out = fleet("tools")
    assert "hello" in out.stdout and "Makes a birthday card" in out.stdout, out.stdout + out.stderr
    out = fleet("tool", "run", "hello", "21st")
    assert out.returncode == 0 and "done" in out.stdout and "making 21st" in out.stdout and "img/card.png" in out.stdout, out.stdout + out.stderr
    jid = out.stdout.split("Job ")[1].split()[0]
    out = fleet("tool", "get", jid, "img/card.png")
    assert out.returncode == 0 and open(os.path.join(home, "card.png"), "rb").read() == b"PNG" * 10, out.stdout + out.stderr
    print("cli OK")


def ui():
    from playwright.sync_api import expect, sync_playwright
    h, muse, r = world()
    done = h.tool_run("Ada", "hello", ["21st"]); r.run_once()
    waiting = h.tool_run("Ada", "slow")
    srv = hub.serve(h, "127.0.0.1", 0, "pw")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with sync_playwright() as pw:
        page = pw.chromium.launch().new_page(http_credentials={"username": "jack", "password": "pw"})
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        open_page(page, "Portfolio")
        machine = page.locator("#hubjobs")
        expect(machine).to_contain_text("Makes a birthday card")
        expect(machine.locator(".row", has_text=f"#{done}")).to_contain_text("hello")
        expect(machine.locator(".row", has_text=f"#{done}")).to_contain_text("Ada")
        expect(machine.locator(".row", has_text=f"#{done}")).to_contain_text("done")
        expect(machine.locator(".row", has_text=f"#{waiting}")).to_contain_text("queued")
    print("ui OK")


{"run": run, "images": images, "guards": guards, "cli": cli, "ui": ui}[sys.argv[1]]()
