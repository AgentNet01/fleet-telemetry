"""Tools: the fleet's own code run on the hub machine, one job at a time, never at the hub's expense.

    python3 test_tools.py run      # an agent runs a tool: log and files come back, and it's told once when it ends
    python3 test_tools.py guards   # low disk refuses; running past the limit or the disk filling stops it; no escapes
    python3 test_tools.py cli      # fleet tools / tool run / tool get, end to end over HTTP
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


{"run": run, "guards": guards, "cli": cli}[sys.argv[1]]()
