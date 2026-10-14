"""Runs the fleet's tools on the hub machine, as a limited account that can't touch the hub or Jack's files.

    python tools_runner.py <jobs dir>      # loops forever: one job at a time

An agent's `fleet tool run <tool> [args]` makes the hub drop <jobs>/queue/<id>.json. This takes the oldest, runs
<repo>/tools/<tool>/run.py with the args in <jobs>/<id>/out (also $OUT_DIR), logs to <jobs>/<id>/log.txt and keeps
<jobs>/<id>/status.json current. The hub reads those files; the two never talk otherwise.

A job is refused when the disk is low, and stopped when it runs past its time, or the disk or memory get close to
empty, so the hub keeps running whatever a tool does.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time

REPO_URL = "https://github.com/AgentNet01/fleet-telemetry.git"
GB = 1 << 30
MIN_FREE = 10 * GB        # don't start a job below this
STOP_FREE = 5 * GB        # stop a running job below this
MIN_RAM = 3 * GB          # stop a running job when less memory than this is left
MAX_TIME = 4 * 3600
KEEP_DAYS = 7
TOOL = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def free_ram():
    if os.name != "nt":
        return None                                    # ponytail: only the Windows hub is guarded
    import ctypes

    class MS(ctypes.Structure):
        _fields_ = [("len", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                    ("avail", ctypes.c_ulonglong), ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong),
                    ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("ve", ctypes.c_ulonglong)]
    m = MS(); m.len = ctypes.sizeof(MS)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return m.avail


def write_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


class Runner:
    def __init__(self, jobs, repo=None, pull=True, free_disk=None, free_ram=free_ram, python=sys.executable):
        self.jobs, self.repo, self.pull = jobs, repo or os.path.join(jobs, "repo"), pull
        self.free_disk = free_disk or (lambda: shutil.disk_usage(jobs).free)
        self.free_ram, self.python = free_ram, python
        os.makedirs(os.path.join(jobs, "queue"), exist_ok=True)

    def update_repo(self):
        if not self.pull:
            return
        git = ["git", "-C", self.repo, "pull", "-q", "--ff-only"] if os.path.isdir(os.path.join(self.repo, ".git")) \
            else ["git", "clone", "-q", "--depth", "1", REPO_URL, self.repo]
        subprocess.run(git, timeout=120, capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"))

    def list_tools(self):
        out, root = [], os.path.join(self.repo, "tools")
        for name in sorted(os.listdir(root)) if os.path.isdir(root) else []:
            if TOOL.match(name) and os.path.isfile(os.path.join(root, name, "run.py")):
                readme = os.path.join(root, name, "README.md")
                first = open(readme, encoding="utf-8", errors="replace").readline().strip("# \n") if os.path.isfile(readme) else ""
                out.append({"name": name, "about": first})
        write_json(os.path.join(self.jobs, "tools.json"), out)

    def clean(self):
        cutoff = time.time() - KEEP_DAYS * 86400
        for d in os.listdir(self.jobs):
            p = os.path.join(self.jobs, d)
            if d.isdigit() and os.path.isdir(p) and os.path.getmtime(p) < cutoff:
                shutil.rmtree(p, ignore_errors=True)

    def run_once(self):
        """The oldest queued job, run to the end. False when nothing is queued."""
        q = os.path.join(self.jobs, "queue")
        waiting = sorted(f for f in os.listdir(q) if f.endswith(".json"))
        if not waiting:
            return False
        job = json.load(open(os.path.join(q, waiting[0])))
        d = os.path.join(self.jobs, str(job["id"]))
        os.makedirs(os.path.join(d, "out"), exist_ok=True)
        os.replace(os.path.join(q, waiting[0]), os.path.join(d, "job.json"))
        st = {"status": "running", "started": time.time()}
        status = lambda **kw: (st.update(kw), write_json(os.path.join(d, "status.json"), st))
        status()
        try:
            self.update_repo(); self.list_tools(); self.clean()
        except Exception as e:                         # a failed pull still runs what's already there
            st["note"] = f"repo update failed: {e}"
        run = os.path.join(self.repo, "tools", job["tool"], "run.py")
        if not TOOL.match(job["tool"]) or not os.path.isfile(run):
            return status(status="failed", ended=time.time(), note=f"no tool {job['tool']!r} (needs tools/{job['tool']}/run.py in the repo)") or True
        if self.free_disk() < MIN_FREE:
            return status(status="refused", ended=time.time(),
                          note=f"only {self.free_disk() / GB:.0f} GB free on the hub's disk; free some up first") or True
        limit = min(int(job.get("timeout") or 3600), MAX_TIME)
        flags = 0x00004000 | 0x00000200 if os.name == "nt" else 0       # below-normal priority, own process group
        with open(os.path.join(d, "log.txt"), "wb") as log:
            p = subprocess.Popen([self.python, "-u", run, *map(str, job.get("args") or [])], cwd=os.path.join(d, "out"),
                                 stdout=log, stderr=subprocess.STDOUT, creationflags=flags, start_new_session=os.name != "nt",
                                 env=dict(os.environ, OUT_DIR=os.path.join(d, "out"), TOOL_DIR=os.path.dirname(run), JOB_ID=str(job["id"])))
            why = None
            while p.poll() is None:
                time.sleep(1)
                ram = self.free_ram()
                why = (f"ran past its {limit}s limit" if time.time() - st["started"] > limit
                       else "the hub's disk is nearly full" if self.free_disk() < STOP_FREE
                       else "the hub is nearly out of memory" if ram is not None and ram < MIN_RAM else None)
                if why:
                    self.kill(p)
                    break
        code = p.wait()
        status(status="stopped" if why else "done" if code == 0 else "failed", exit=code, ended=time.time(),
               note=f"stopped: {why}" if why else st.get("note"))
        return True

    @staticmethod
    def kill(p):
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
        else:
            import signal
            os.killpg(p.pid, signal.SIGKILL)


if __name__ == "__main__":
    r = Runner(sys.argv[1])
    for f in os.listdir(r.jobs):                       # a job cut off by a restart isn't left "running" forever
        s = os.path.join(r.jobs, f, "status.json")
        if f.isdigit() and os.path.isfile(s) and json.load(open(s)).get("status") == "running":
            write_json(s, dict(json.load(open(s)), status="stopped", ended=time.time(), note="stopped: the runner restarted"))
    try:
        r.update_repo(); r.list_tools()
    except Exception:
        pass
    while True:
        if not r.run_once():
            time.sleep(3)
