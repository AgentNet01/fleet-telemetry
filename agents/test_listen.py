"""Run: python3 agents/test_listen.py  (front door: wakes on a new message, once; one listener at a time)."""
import contextlib, fcntl, io, json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import listen as L

def run(hours=0.0005):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        L.main(hours)
    return out.getvalue()

with tempfile.TemporaryDirectory() as d:
    L.INBOX, L.SEEN, L.LOCK = d, os.path.join(d, ".announced"), os.path.join(d, ".listen.lock")
    L.BURST = L.TICK = 0.01
    assert "no messages" in run()                                              # times out cleanly
    with open(os.path.join(d, "C1-5.1.json"), "w") as f:
        json.dump({"why": "mentioned", "reply_required": True, "channel_id": "C1", "ts": "5.1", "user_name": "Jack", "text": "hi"}, f)
    o = run(); assert "1 new Slack message" in o and '"C1-5.1.json"' in o and "restart the front door" in o, o
    assert "no messages" in run()                                              # not announced twice
    held = open(L.LOCK, "w"); fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert "already running" in run(); held.close()                            # one listener at a time
    os.remove(os.path.join(d, "C1-5.1.json"))
    assert run() and open(L.SEEN).read() == ""                                 # filed messages drop out of .announced
print("ok")
