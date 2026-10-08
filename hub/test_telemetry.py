"""Telemetry ingest: an agent's heartbeat is stored and shows up as its focus.  python3 test_telemetry.py"""
import os, tempfile
import hub
from test_hub import Clock, FakeMuse


def ingest_and_focus():
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.add_agent("Boboe 2", "muse")
    p = h.add_product("P", brief="b"); pr = h.add_project(p, "launch")
    h.place("Boboe 2", "P", "developer")
    t = h.add_task(pr, "build the sheet", role="developer", done_def="works", owner="Boboe 2")
    h.db.execute("update tasks set status='working' where id=?", (t,))

    h.ingest("Boboe 2", {"cpu": 12, "activity": {"current": "drafting a response"}, "files": {"count": 3}})
    blob = h.telemetry("Boboe 2")
    assert blob["cpu"] == 12 and "_at" in blob, blob

    f = h._focus("Boboe 2")
    assert f["task"] == {"id": t, "title": "build the sheet"}, f
    assert f["doing"] == "drafting a response" and f["reporting"] is True, f
    print("telemetry OK")


if __name__ == "__main__":
    ingest_and_focus()
