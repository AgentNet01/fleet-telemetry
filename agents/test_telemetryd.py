"""Run: python3 agents/test_telemetryd.py  (no deps, exits non-zero on failure)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telemetryd as t

t.LOG = os.devnull  # handle_cmd logs; keep the test from leaving a file behind

# cpu_percents: no baseline -> None; one core busy for the interval -> 100%
assert t.cpu_percents([(1, "a", 1.0, 500)], {}, 30) == {1: None}
tick = t.CLK_TCK
pct = t.cpu_percents([(1, "a", 1.0, 30 * tick), (2, "new", 1.0, 3 * tick)],
                     {1: 0}, 30)
assert pct == {1: 100.0, 2: 10.0}, pct
assert t.cpu_percents([(1, "a", 1.0, 5)], {1: 9}, 30) == {1: 0}  # pid reuse

# observed: the daemon's own files and process never count as "working"
now = 1_000_000
own = os.path.relpath(t.TDIR, os.path.join(t.HOME, "workspace")) + os.sep
walked = [(own + "telemetryd.log", 10, now - 5), (own + ".boot_id", 1, now - 5),
          ("notes/old.md", 10, now - 3600)]
plist = [["python3", 14.0, 80.0, 4242], ["hatch", 400.0, 1.0, 1]]
o = t.observed(walked, plist, now, self_pid=4242)
assert o["working"] is False and o["recent"] == [], o

# real evidence does count, newest file first
walked.append(("notes/plan.md", 10, now - 60))
walked.append(("README.md", 10, now - 10))
plist.append(["node", 50.0, 37.0, 7])
o = t.observed(walked, plist, now, self_pid=4242)
assert o["working"] is True, o
assert [r[0] for r in o["recent"]] == ["README.md", "notes/plan.md"], o
assert o["signals"] == ["2 files changed in last 5m", "node at 37% cpu"], o

# files(): rows keep v1 shape [path, kb] plus mtime, largest first
f = t.files([("a", 2048, 5.5), ("b", 4096, 6.0)])
assert f["entries"] == [["b", 4.0, 6], ["a", 2.0, 5]] and f["count"] == 2, f

# file viewing: only plain workspace files reach Jack -- never secrets, hidden
# files, symlink escapes or anything outside ~/workspace
import tempfile
with tempfile.TemporaryDirectory() as home:
    ws = os.path.join(home, "workspace")
    os.makedirs(os.path.join(ws, "notes"))
    os.makedirs(os.path.join(ws, "telemetry"))
    for rel, data in [("notes/plan.md", b"hi"), ("telemetry/.token", b"s3cret"),
                      ("api_token.txt", b"x"), ("big.bin", b"0" * (t.FETCH_MAX + 1))]:
        with open(os.path.join(ws, rel), "wb") as f:
            f.write(data)
    with open(os.path.join(home, "outside.txt"), "w") as f:
        f.write("nope")
    os.symlink(os.path.join(home, "outside.txt"), os.path.join(ws, "escape.txt"))
    os.symlink(os.path.join(ws, "telemetry", ".token"), os.path.join(ws, "innocent.txt"))
    t.HOME = home
    assert t.resolve_fetch("notes/plan.md").endswith("notes/plan.md")
    refused = {}
    for rel in ["telemetry/.token", "api_token.txt", "big.bin", "../outside.txt",
                "/etc/passwd", "escape.txt", "innocent.txt", "notes/gone.md", None]:
        try:
            t.resolve_fetch(rel)
        except ValueError as e:
            refused[rel] = str(e)
    assert len(refused) == 9, refused
    assert refused["innocent.txt"] == "hidden files aren't shared", refused

# burst caps still hold against hostile input
assert t.handle_cmd({"burst": True, "interval": 0, "until": 1e12}, 100.0) == (2, 400.0)
print("ok")
