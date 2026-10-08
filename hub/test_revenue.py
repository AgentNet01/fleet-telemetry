"""Revenue: Stripe + Etsy sales counted once each, deduped, mapped to a product.

    python3 test_revenue.py
"""
import os
import tempfile

import hub
from test_hub import Clock, FakeMuse


def main():
    h = hub.Hub(os.path.join(tempfile.mkdtemp(), "hub.db"), FakeMuse(), Clock())
    h.add_product("Templates", brief="b")
    h.add_product("Stickers", brief="b")

    first = [
        {"source": "stripe", "external_id": "ch_1", "amount": 5.00, "currency": "usd", "product": "Templates", "at": 1_000},
        {"source": "etsy", "external_id": "rcpt_1", "amount": 3.50, "currency": "usd", "product": "Stickers", "at": 1_001},
    ]
    h.pull_revenue(lambda: first)
    h.pull_revenue(lambda: first)                 # the same receipts again must not double-count
    rev = h.revenue()
    assert round(rev["total"], 2) == 8.50, rev
    assert round(rev["by_product"]["Templates"], 2) == 5.00, rev
    assert round(rev["by_product"]["Stickers"], 2) == 3.50, rev

    h.pull_revenue(lambda: [
        {"source": "etsy", "external_id": "rcpt_2", "amount": 3.50, "currency": "usd", "product": "Stickers", "at": 2_000},
    ])
    rev = h.revenue()
    assert round(rev["total"], 2) == 12.00, rev
    assert round(rev["by_product"]["Stickers"], 2) == 7.00, rev
    assert rev["total"] == h.board()["revenue"]["total"], "the board shows the same total"
    print("revenue OK")


if __name__ == "__main__":
    main()
