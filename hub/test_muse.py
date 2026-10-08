"""Muse transport (against fake_muse_cli.py) and daily login renewal (against a stub sign-in check).

    python3 test_muse.py
"""
import os
import sys
import tempfile

import hub
import muse
from test_hub import Clock

HERE = os.path.dirname(os.path.abspath(__file__))


def account(root, name, cookies="hatch_sess=OLD; hatch_gw=OLDGW; datr=keep"):
    d = os.path.join(root, name)
    os.makedirs(os.path.join(d, ".config", "muse-cli"))
    with open(os.path.join(d, ".config", "muse-cli", "cookies.txt"), "w") as f:
        f.write(cookies + "\n")
    return d


def cookies_of(d):
    return open(os.path.join(d, ".config", "muse-cli", "cookies.txt")).read().strip()


def transport():
    root = tempfile.mkdtemp()
    b3 = account(root, "boboe-3")
    t = muse.MuseTransport([sys.executable, os.path.join(HERE, "fake_muse_cli.py")], {"Boboe 3": b3})
    with open(os.path.join(b3, "reply"), "w") as f:
        f.write("$3.50, matte")

    mark = t.deliver("Boboe 3", "price?")
    got = t.replies("Boboe 3", mark)
    assert [text for _, text in got] == ["$3.50, matte"], f"only the genuine, finished reply: {got}"

    mark2 = t.deliver("Boboe 3", "and the size?")
    assert all(seq > mark2 for seq, _ in t.replies("Boboe 3", mark2)), "replies only after our message"
    assert len(t.replies("Boboe 3", mark2)) == 1
    assert t.session("Boboe 3") == "sess-1", "one fleet side chat, reused"
    print("transport OK")


def renewal():
    root = tempfile.mkdtemp()
    good, bad = account(root, "boboe-3"), account(root, "boboe-7")
    rotated = ["hatch_sess=; Max-Age=0; Path=/", "hatch_sess=NEW; Max-Age=2592000; Path=/; HttpOnly",
               "hatch_gw=; Max-Age=0", "hatch_gw=NEWGW; Max-Age=31536000"]
    stub = {good: (200, rotated), bad: (401, [])}
    post = lambda account_dir, cookie_header: stub[account_dir]

    expires = muse.renew(good, post, now=1_000_000)
    assert cookies_of(good) == "hatch_sess=NEW; hatch_gw=NEWGW; datr=keep", cookies_of(good)
    assert expires == 1_000_000 + 2592000, expires

    # still valid but not due for rotation: muse.ai answers 200 with no new cookies
    fresh = account(root, "boboe-9")
    stub[fresh] = (200, [])
    assert muse.renew(fresh, post, now=1_000_000) >= 1_000_000 + 25 * 86400, "a valid login isn't a failure"
    assert cookies_of(fresh) == "hatch_sess=OLD; hatch_gw=OLDGW; datr=keep", "nothing new to save"

    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), None, Clock())
    h.add_agent("Boboe 3", "muse"); h.add_agent("Boboe 7", "muse")
    h.renew_logins({"Boboe 3": good, "Boboe 7": bad}, post)
    agents = {a["name"]: a for a in h.board()["agents"]}
    assert agents["Boboe 3"]["login_expires"] > h.clock() + 25 * 86400, agents["Boboe 3"]
    assert agents["Boboe 7"]["state"] == "login", agents["Boboe 7"]
    assert any("Boboe 7" in n["text"] and "login" in n["text"].lower() for n in h.needs_jack())
    assert cookies_of(bad) == "hatch_sess=OLD; hatch_gw=OLDGW; datr=keep", "a failed renewal leaves the file alone"
    stub[bad] = (200, rotated)
    h.renew_logins({"Boboe 7": bad}, post)
    assert not any("Boboe 7" in n["text"] for n in h.needs_jack()), "a later successful renewal clears Needs Jack"
    print("renewal OK")


if __name__ == "__main__":
    transport()
    renewal()
