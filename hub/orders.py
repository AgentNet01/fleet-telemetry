"""Paid marketplace orders -> one paid CJ order each -> tracking back to the marketplace (PLAN8).

Jack, Oct 28: orders are placed automatically, "very careful with the cap ... counting for fees and tax and
shipping". Each order is re-quoted at CJ and re-checked by money.ok() with the real sale and tax before anything
is bought; the day's automatic spend stays under money.DAILY_CAP; anything else goes to Jack with the numbers.

States: new -> placing -> paying -> placed -> shipped; refused (fails the money rule), held (cap or wallet; retried
every tick). The row is written before each CJ call and our row id is CJ's order number, so a crash mid-call is
resolved by looking the order up at CJ, never by ordering again.
"""
import json
import time

import cj
import money

CHANNELS = {}                # name -> module with paid_orders(h) -> [order dict] and send_tracking(h, order_id, carrier, number)
KEEP_ADDRESS = 45 * 86400    # after shipping: delivery takes up to ~15 days, then 30 more, then the address is deleted


def _set(h, rid, **kw):
    with h.lock:
        h.db.execute(f"update supplier_orders set {', '.join(k + '=?' for k in kw)} where id=?", (*kw.values(), rid))


def _jack(h, text):
    with h.lock:
        h._needs_jack_once(text)


def spent_today(h):
    t = time.localtime(h.clock())
    start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    with h.lock:
        return h.db.execute("select coalesce(sum(cost), 0) s from supplier_orders where state in "
                            "('placing','paying','placed','shipped') and coalesce(placed, created) >= ?", (start,)).fetchone()["s"]


def tick(h):
    """Take in every channel's paid orders, then move each open one as far as it can go."""
    for name, ch in CHANNELS.items():
        try:
            got = ch.paid_orders(h)
        except Exception as e:
            with h.lock:
                h._log(None, "hub", "out", f"orders: {name} paid orders unreadable: {e}")
            continue
        with h.lock:
            for o in got:
                h.db.execute("insert or ignore into supplier_orders(channel, order_id, product, vid, qty, sale, tax, state, "
                             "address, ship_by, link, created) values(?,?,?,?,?,?,?,'new',?,?,?,?)",
                             (name, str(o["order_id"]), o.get("product"), o["vid"], o.get("qty", 1), o["sale"], o.get("tax", 0.0),
                              json.dumps(o["address"]), o.get("ship_by"), o.get("link"), h.clock()))
    with h.lock:
        rows = [dict(r) for r in h.db.execute("select * from supplier_orders where state in ('new','held','placing','paying') order by id")]
    for r in rows:
        try:
            _one(h, r)
        except Exception as e:                       # one bad order never stops the rest; it is retried next tick
            with h.lock:
                h._log(None, "hub", "out", f"orders: {r['channel']} {r['order_id']} stuck at {r['state']}: {e}")


def _one(h, r):
    rid, who = r["id"], f"{r['channel']} order {r['order_id']} ({r['product'] or r['vid']})"
    tail = f"; ship by {r['ship_by']}. {r['link'] or ''}".rstrip()
    if r["state"] == "placing":                      # we called CJ and never heard back
        cj_id = cj.find(h, rid)
        if not cj_id:
            _set(h, rid, state="new")
            return _one(h, dict(r, state="new"))
        _set(h, rid, state="paying", cj_id=cj_id)
        r = dict(r, state="paying", cj_id=cj_id)
    if r["state"] == "paying":
        cj.pay(h, r["cj_id"])
        return _set(h, rid, state="placed", placed=h.clock())
    addr = json.loads(r["address"])
    try:
        q = cj.quote(h, r["vid"], r["qty"], addr["zip"])
    except ValueError as e:                          # out of stock, too slow to ship
        _set(h, rid, state="refused", note=str(e))
        return _jack(h, f"Not ordered: {who}: {e}{tail}")
    if not money.ok(r["channel"], r["sale"], q["total"], r["tax"]):
        _set(h, rid, state="refused", cost=q["total"])
        return _jack(h, f"Not ordered, it would lose money: {who}: " + money.lines(
            r["channel"], r["sale"], {"item": q["item"], "freight": q["freight"], "tax": q["tax"]}, r["tax"]) + tail)
    spent = spent_today(h)
    if spent + q["total"] > money.DAILY_CAP:
        _set(h, rid, state="held", cost=q["total"])
        return _jack(h, f"Waiting: {who} costs ${q['total']:.2f}; today's automatic spend ${spent:.2f} would pass the "
                        f"${money.DAILY_CAP:.0f} a day cap. It goes through tomorrow, or order it yourself{tail}")
    wallet = cj.balance(h)
    if wallet < q["total"]:
        _set(h, rid, state="held", cost=q["total"])
        return _jack(h, f"Waiting: {who} costs ${q['total']:.2f} but the CJ wallet has ${wallet:.2f}. Top it up{tail}")
    _set(h, rid, state="placing", cost=q["total"], note=q["logistic"], placed=h.clock())
    cj_id = cj.place(h, rid, r["vid"], r["qty"], addr, q["logistic"], q["start"])
    _set(h, rid, state="paying", cj_id=cj_id)
    cj.pay(h, cj_id)
    _set(h, rid, state="placed")
    with h.lock:
        h._log(None, "hub", "out", f"orders: CJ {cj_id} placed for {who}, cost ${q['total']:.2f}, sale ${r['sale']:.2f}")


def track(h):
    """Placed orders: tracking to the channel once CJ ships. Shipped long enough: the buyer's address is deleted."""
    with h.lock:
        rows = [dict(r) for r in h.db.execute("select * from supplier_orders where state='placed'")]
    for r in rows:
        ch = CHANNELS.get(r["channel"])
        t = ch and cj.tracking(h, r["cj_id"])
        if t:
            try:
                ch.send_tracking(h, r["order_id"], *t)
            except Exception as e:                   # retried next round; Jack hears once, the ship-by date is his to watch
                _jack(h, f"Tracking {t[0]} {t[1]} for {r['channel']} order {r['order_id']} didn't upload: {e}. "
                         f"Add it by hand{(': ' + r['link']) if r['link'] else ''}")
                continue
            _set(h, r["id"], state="shipped", carrier=t[0], tracking=t[1], shipped=h.clock())
    with h.lock:
        h.db.execute("update supplier_orders set address=null where state='shipped' and shipped < ? and address is not null",
                     (h.clock() - KEEP_ADDRESS,))
