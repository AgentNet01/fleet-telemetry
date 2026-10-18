"""Jack's daily brief: once a day, one PDF of broad overview, written by the hub itself.

    python3 test_reports.py
"""
import os
import tempfile
import time

import hub
import reports
from test_hub import Clock


def main():
    clock = Clock()
    clock.t = time.mktime((2026, 10, 15, 9, 0, 0, 0, 0, -1))              # 9:00 local, after the 8:00 brief is due
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), None, clock)
    pid = h.add_product("Pet portraits", brief="b")
    h.add_product("Hats", brief="b")
    proj = h.add_project(pid, "Launch")
    with h.lock:
        h.db.execute("update products set link='https://www.etsy.com/listing/1', listing_state='active', pm='Boboe 10' where id=?", (pid,))
        h.db.execute("update products set link='https://www.etsy.com/listing/2', listing_state='inactive' where name='Hats'")
        t1 = h.add_task(proj, "Post the pet portrait listing", "maker", "live")
        h.db.execute("insert into task_events(task, agent, what, text, at) values(?, 'Ada', 'verified', '', ?)", (t1, clock() - 3600))
        h.db.execute("insert into task_events(task, agent, what, text, at) values(?, 'Ada', 'verified', '', ?)", (t1, clock() - 3 * 86400))
        for i in range(3):
            t = h.add_task(proj, f"Pinterest pins {i}", "marketer", "posted")
            h.db.execute("update tasks set status='blocked', waiting_on='Boboe 1' where id=?", (t,))
        h._needs_jack("Approve $14 of Etsy ads for pet portraits")
        h.db.execute("insert into sales(source, external_id, product, amount, at) values('etsy','1','Pet portraits',29.99,?)", (clock() - 7200,))
        for i in range(400):                                                # a busy day: the brief stays short anyway
            h.db.execute("insert into events(agent, dir, text, at) values('Ada','out',?,?)", (f"chatter {i}", clock() - 60))

    sent = []
    r = reports.Reporter(h, pdf=lambda b: sent.append(b) or "/tmp/brief.pdf",
                         upload=lambda path, title: sent.append(("up", title)))
    r.tick()
    daily = [x for x in sent if isinstance(x, dict) and "daily" in x["title"]]
    hourly = [x for x in sent if isinstance(x, dict) and "hourly" in x["title"]]
    # Jack, Oct 16: "can we make it so we get hourly reports too?"
    assert len(daily) == 1 and len(hourly) == 1, f"brief: a daily and an hourly brief go out: {[x for x in sent]}"
    assert hourly[0]["title"] == "Foundlings hourly brief · Thu Oct 15 09:00", hourly[0]["title"]
    assert hourly[0]["cards"][0][0] == "$0.00" and hourly[0]["cards"][2][0] == "0", \
        f"brief: the hourly one counts only 8:00-9:00 (the 7:00 sale and the 8:00 finish belong to the day before it): {hourly[0]['cards']}"
    assert ("up", daily[0]["title"]) in sent and ("up", hourly[0]["title"]) in sent, "brief: both are posted"
    sent[:] = [daily[0], ("up", daily[0]["title"])]
    b = sent[0]
    assert b["title"] == "Foundlings daily brief · Thu Oct 15", b["title"]
    assert b["cards"][0][0] == "$29.99" and b["cards"][1][0] == "1 of 2", f"brief: the day's sales, products listed: {b['cards']}"
    assert b["cards"][2][0] == "1", "brief: only the day's finished tasks count"
    assert b["needs"] == [("Approve $14 of Etsy ads for pet portraits", None)], b["needs"]
    pets = b["products"][0]
    assert (pets["name"], pets["pm"], pets["done"], pets["stuck"], pets["latest"]) == \
        ("Pet portraits", "Boboe 10", 1, 3, "Post the pet portrait listing"), f"brief: one line per product: {pets}"
    assert b["products"][1]["latest"] == "", "brief: a quiet product says so"
    assert (pets["etsy"], b["products"][1]["etsy"]) == ("live", "off"), "brief: a taken-down listing isn't shown as live (Jack, Oct 15)"
    assert b["stuck"] == [(3, "Boboe 1", ["Pinterest pins 0", "Pinterest pins 1"])], f"brief: stuck work grouped: {b['stuck']}"
    assert "chatter" not in str(b), "brief: an overview, not the log"

    r.tick()
    assert len(sent) == 2, "brief: once a day, once an hour"
    clock.go(3600)
    r.tick()
    assert [x["title"] for x in sent[2:] if isinstance(x, dict)] == ["Foundlings hourly brief · Thu Oct 15 10:00"], sent[2:]
    clock.go(86400)
    r.tick()
    assert len([x for x in sent[4:] if isinstance(x, dict)]) == 2, "brief: the next day's goes out, with that hour's"

    fails = []
    h2 = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), None, clock)
    r2 = reports.Reporter(h2, pdf=lambda *a: 1 / 0, upload=lambda *a: None, log=fails.append)
    r2.tick()
    r2.tick()
    assert len(fails) == 2, "brief: a failure is logged once per brief, not retried every minute"
    print("reports OK")


if __name__ == "__main__":
    main()
