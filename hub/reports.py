"""Jack's daily brief (Jack, Oct 15: "a quick touch point I can read in one to two pages", broad, not every event).
Once a day the hub writes it from its own records, prints it to PDF and posts the file in the reports channel.
No agent writes it: dot sat parked and every report it was asked for was missed."""
import json
import os
import re
import time
import traceback
import urllib.request

SCHEMA = ("create table if not exists reports(id integer primary key, period text, start real, end real, ts real, "
          "reply text, status text, at real)")
HOUR = 8                    # the brief covers the 24 hours up to 8:00 local and goes out then
DAY = 86400
TOP = 6                     # at most this many lines in any list, so it stays on two pages


class Reporter:
    def __init__(self, hub, pdf, upload, log=None):
        """pdf(brief) -> path; upload(path, title) posts the file."""
        self.h, self.pdf, self.upload, self.log = hub, pdf, upload, log
        with hub.lock:
            hub.db.execute(SCHEMA)

    def tick(self):
        now = self.h.clock()
        lt = time.localtime(now)
        day = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, HOUR, 0, 0, 0, 0, -1))
        hour = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 0, 0, 0, 0, -1))
        # Jack, Oct 16: "can we make it so we get hourly reports too?" — the same page, for the hour just gone
        for period, length, end in (("brief", DAY, day - DAY if day > now else day), ("hourly", 3600, hour)):
            self._send(period, length, end, now)

    def _send(self, period, length, end, now):
        with self.h.lock:
            if self.h.db.execute("select 1 from reports where period=? and end=?", (period, end)).fetchone():
                return
            rid = self.h.db.execute("insert into reports(period, start, end, status, at) values(?,?,?,'sending',?)",
                                    (period, end - length, end, now)).lastrowid
            b = brief(self.h, end - length, end)
        try:                                   # one try: a half-done upload retried would post twice
            self.upload(self.pdf(b), b["title"])
            status = "done"
        except Exception:
            status = "failed"
            if self.log:
                self.log(traceback.format_exc())
        with self.h.lock:
            self.h.db.execute("update reports set status=? where id=?", (status, rid))


def brief(h, start, end):
    daily = end - start > 2 * 3600
    """The day as plain data: the numbers, what needs Jack, one row per product, what's stuck. Called under the hub lock."""
    db = h.db
    one = lambda sql, *a: db.execute(sql, a).fetchone()[0]
    sales_day = one("select coalesce(sum(amount),0) from sales where at>? and at<=?", start, end)
    sales_all = one("select coalesce(sum(amount),0) from sales")
    products = db.execute("select * from products where status='active' and coalesce(kind,'product')='product' order by id").fetchall()
    finished = db.execute("select t.title, p.name product from task_events te join tasks t on t.id=te.task "
                          "join projects j on t.project=j.id join products p on j.product=p.id "
                          "where te.what='verified' and te.at>? and te.at<=? order by te.at desc", (start, end)).fetchall()
    needs = db.execute("select text, link from needs_jack where done=0 and triage is null order by id").fetchall()
    blocked = db.execute("select t.title, t.waiting_on, p.name product from tasks t join projects j on t.project=j.id "
                         "join products p on j.product=p.id where t.status='blocked' and p.status='active'").fetchall()
    agents = db.execute("select busy from agents where kind != 'jack' and state='active'").fetchall()
    groups = {}
    for b in blocked:
        groups.setdefault(b["waiting_on"] or "outside", []).append(b["title"])
    busy = sum(1 for a in agents if a["busy"])
    return {
        "title": (f"Foundlings daily brief · {time.strftime('%a %b %d', time.localtime(end))}" if daily else
                  f"Foundlings hourly brief · {time.strftime('%a %b %d %H:%M', time.localtime(end))}"),
        "sub": f"The {'24 hours' if daily else 'hour'} to {time.strftime('%H:%M', time.localtime(end))}, written by the hub from its records.",
        "done_label": "Done today" if daily else "Done this hour",
        "cards": [(f"${sales_day:,.2f}", f"sales {'today' if daily else 'this hour'}, ${sales_all:,.2f} all time"),
                  (f"{sum(1 for p in products if p['listing_state'] == 'active')} of {len(products)}", "products live on Etsy"),
                  (str(len(finished)), "tasks finished"),
                  (str(len(needs)), "things need you")],
        "needs": [(_short(n["text"], 160), n["link"]) for n in needs[:TOP]],
        "needs_more": max(0, len(needs) - TOP),
        "products": [{"name": p["name"], "pm": p["pm"] or "no PM", "link": p["link"],
                      "etsy": "not yet" if not p["link"] else "live" if p["listing_state"] == "active" else (p["listing_state"] and "off") or "unchecked",
                      "done": sum(1 for f in finished if f["product"] == p["name"]),
                      "stuck": sum(1 for b in blocked if b["product"] == p["name"]),
                      "latest": next((_short(f["title"], 70) for f in finished if f["product"] == p["name"]), "")}
                     for p in products],
        "stuck": [(len(t), "outside events (dates, other services)" if who == "outside" else who, [_short(x, 60) for x in t[:2]])
                  for who, t in sorted(groups.items(), key=lambda g: -len(g[1]))[:TOP]],
        "team": f"{len(agents)} agents online, {busy} busy right now, {len(agents) - busy} between tasks.",
    }


def _short(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


# ---- the real PDF and upload (fpdf2: Edge can't print under the hub's SYSTEM account; the bot needs files:write) ----
FONTS = [(r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
         ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")]
INK, GREY, LINE, BLUE = (29, 29, 34), (120, 120, 128), (225, 225, 230), (26, 95, 180)


def make_pdf(folder):
    def make(b):
        from fpdf import FPDF
        from fpdf.fonts import FontFace
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, re.sub(r"[^\w.-]+", "-", b["title"])[:90] + ".pdf")
        pdf = FPDF(format="letter")
        pdf.set_margins(18, 16)
        pdf.set_auto_page_break(True, 16)
        reg, bold = next(f for f in FONTS if os.path.exists(f[0]))
        pdf.add_font("b", "", reg)
        pdf.add_font("b", "B", bold)
        pdf.add_page()
        w = pdf.epw

        def text(s, size=10, style="", color=INK, gap=5.2, link=""):
            pdf.set_font("b", style, size)
            pdf.set_text_color(*color)
            pdf.multi_cell(w, gap, s, align="L", new_x="LMARGIN", new_y="NEXT", link=link)

        def heading(s):
            pdf.ln(4)
            text(s, 12.5, "B", gap=7)
            pdf.set_draw_color(*LINE)
            pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
            pdf.ln(2)

        text(b["title"], 19, "B", gap=9)
        text(b["sub"], 9.5, color=GREY)
        pdf.ln(4)
        y, cw = pdf.get_y(), (w - 9) / 4
        for i, (big, label) in enumerate(b["cards"]):
            x = pdf.l_margin + i * (cw + 3)
            pdf.set_draw_color(*LINE)
            pdf.rect(x, y, cw, 20, round_corners=True, style="D")
            pdf.set_xy(x + 3, y + 2.5)
            pdf.set_font("b", "B", 15)
            pdf.set_text_color(*INK)
            pdf.cell(cw - 6, 7, big)
            pdf.set_xy(x + 3, y + 10)
            pdf.set_font("b", "", 8.5)
            pdf.set_text_color(*GREY)
            pdf.multi_cell(cw - 6, 4, label, align="L")
        pdf.set_xy(pdf.l_margin, y + 22)

        heading("Needs you")
        for s, link in b["needs"]:
            text("•  " + s + ("  (open)" if link else ""), link=link or "")
        if b["needs_more"]:
            text(f"and {b['needs_more']} more on the dashboard.", 9.5, color=GREY)
        if not b["needs"]:
            text("Nothing. The agents are handling everything themselves.")

        heading("Products")
        pdf.set_font("b", "", 9.5)
        pdf.set_text_color(*INK)
        with pdf.table(col_widths=(30, 11, 9, 8, 42), text_align="LEFT", borders_layout="HORIZONTAL_LINES",
                       headings_style=FontFace(emphasis="BOLD", color=GREY), line_height=5, padding=1.6, markdown=True) as t:
            t.row(["Product", "Etsy", b["done_label"], "Stuck", "Latest finished"])
            for p in b["products"]:
                r = t.row()
                r.cell(f"**{p['name']}**\n{p['pm']}")
                r.cell(p["etsy"], link=p["link"] or None, style=FontFace(color=BLUE if p["etsy"] == "live" else GREY))
                r.cell(str(p["done"]))
                r.cell(str(p["stuck"] or ""))
                r.cell(p["latest"] or "quiet", style=None if p["latest"] else FontFace(color=GREY))

        heading("What's stuck")
        for n, who, eg in b["stuck"]:
            pdf.set_font("b", "", 10)
            pdf.set_text_color(*INK)
            pdf.multi_cell(w, 5.2, f"•  **{n} waiting on {who}**, e.g. {'; '.join(eg)}", markdown=True, align="L",
                           new_x="LMARGIN", new_y="NEXT")
        if not b["stuck"]:
            text("Nothing is stuck.")

        heading("Team")
        text(b["team"])
        pdf.output(path)
        return path
    return make


def slack_upload(api, token, channel):
    """api: SlackTransport.api. The external-upload flow, into the channel."""
    def up(path, title):
        data = open(path, "rb").read()
        u = api("files.getUploadURLExternal", filename=os.path.basename(path), length=len(data))
        req = urllib.request.Request(u["upload_url"], data=data, headers={"Authorization": "Bearer " + token()})
        urllib.request.urlopen(req, timeout=60).read()
        api("files.completeUploadExternal", files=json.dumps([{"id": u["file_id"], "title": title}]), channel_id=channel)
    return up
