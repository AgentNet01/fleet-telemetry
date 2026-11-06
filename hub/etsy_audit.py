"""Read-only: every ACTIVE listing in the linked Etsy shop, and which are resale (PLAN7 step 3).
Exit 1 if any resale listing is live. `--off` turns those off (state inactive) and logs each id.
Run on the hub PC: C:\\fleet\\venv\\Scripts\\python.exe etsy_audit.py [--off]"""
import os
import sqlite3
import sys
import threading

import etsy


class H:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()

    def secret_put(self, name, value, scope, by):
        with self.lock:
            self.db.execute("update secrets set value=? where name=?", (value, name))
            self.db.commit()


def main():
    h = H(os.environ.get("HUB_DB", r"C:\fleet\hub.db"))
    app, name, rec = etsy._shop(h)
    rec = etsy._fresh(h, app, rec)
    tok, shop = rec["access"], rec["shop_id"]
    by_link = {etsy._listing_id(r["link"]): r for r in h.db.execute("select name, brief, link from products where link like '%etsy.com/listing/%'")}
    resale, kept, off = [], [], "--off" in sys.argv
    offset = 0
    while True:
        page = etsy._get(app, tok, f"{etsy.API}/shops/{shop}/listings?state=active&limit=100&offset={offset}")
        for l in page.get("results", []):
            p = by_link.get(l["listing_id"])
            text = " ".join(((p["brief"] if p else "") or "", l["title"], l.get("description") or ""))
            (resale if etsy.RESALE.search(text) else kept).append((l["listing_id"], p["name"] if p else "-", l["title"][:70]))
        if len(page.get("results", [])) < 100:
            break
        offset += 100
    print(f"active {len(resale) + len(kept)}: resale {len(resale)}, kept {len(kept)}")
    for r in kept:
        print("KEEP  ", *r)
    for r in resale:
        print("RESALE", *r)
        if off:
            etsy._get(app, tok, f"{etsy.API}/shops/{shop}/listings/{r[0]}", "PATCH", data={"state": "inactive"})
            print("  -> turned off")
    sys.exit(1 if resale and not off else 0)


if __name__ == "__main__":
    main()
