# Supplier + money: CJ quotes, the profit floor, automatic orders

## Goal
Every price and every supplier order goes through one money rule (`COMMERCE.md`): the hub quotes the real CJ
cost, never lists or orders below profit >= $1.50 and >= 10% after all fees, and places each paid order with CJ
exactly once, paid from the CJ wallet, inside $50/day, with tracking sent back to the channel. Anything that
fails the rule lands on Jack's list with the numbers.

## Context
- Jack, Oct 28: "never be priced at something where ordering it would take a loss, including the fees... go
  as high as we can with the margin... minimum of $1.50 per profit or 10%... 50 a day."
- CJ API v2 (developers.cjdropshipping.com): access token from email + API key; variant lookup; freight quote
  to a US address; create order; pay from wallet balance; tracking. Exact paths checked against CJ's docs when
  `cj.py` is written; the fake mirrors them.
- New files: `cj.py` (CJ calls only), `money.py` (fees, profit, floor, the breakdown), `orders.py` (paid order
  → CJ order → tracking). Channels plug in through two calls each: `paid_orders(h)` and `send_tracking(h, ...)`.
- Match: `etsy.py` (module-level `http` swapped for a fake in tests, vault-held credentials), `test_etsy.py`.
- Decision, the floor: price p must satisfy p - fee(p) - cost >= max(1.50, 0.10 p), where fee is the channel's
  percentage on the buyer's total (p plus a 12% tax buffer for eBay) plus its per-order fee. Solved exactly,
  rounded up to the cent. Worked: eBay, CJ $3.20 + $2.10 freight = $5.30 → floor $8.38.
- Decision, fee table: one `FEES` dict in `money.py`, one row per channel, each with its source URL and the date
  checked. eBay: 13.6% of total incl. tax and shipping, $0.30/order ≤ $10, $0.40 above. Etsy: $0.20 listing,
  6.5% transaction, 3% + $0.25 payment. Amazon: read live from the Product Fees API (PLAN10).
- Decision, at order time the check is redone with the real sale total and the real tax the buyer paid, and a
  fresh CJ quote; listing-time numbers are not trusted.
- Decision, exactly once: table `supplier_orders`, unique(channel, order_id). The row is marked `placing`
  before CJ is called, and our row id is sent as CJ's order number; after a crash a `placing` row is looked up
  at CJ by that number, never re-created.
- Decision, cap: "today" is the hub PC's calendar day; spend = sum of placed CJ costs today. The CJ wallet is a
  second, hard cap.
- Decision, privacy: the buyer's address is kept only to place the order, and deleted 30 days after delivery.
- Only Jack: CJ account, API key into vault `cj-key` = {"email", "api_key"}, wallet top-up ($50-100).

## Must Not Change
- Etsy posting and sales pull (`test_etsy.py`), floor 2 (`test_floor.py`).
- No test reaches the real CJ: `http` is always the fake in `test_orders.py`.

## Steps
- [x] Step 1: Write each Done When example's test in `test_orders.py` with `f01-test-driven-development`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN8-supplier.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: `money.py`: FEES table with sources, `fees(channel, price, tax)`, `floor(channel, cost)`,
  `profit(channel, price, cost, tax)`, `ok(...)`, `lines(...)` for Jack's breakdown (the day's
  spend lives in `orders.py`, which owns the table).
  - check: `python3 test_orders.py floor fees`
  - on fail: fix the formula against the worked numbers in Context; redo Step 2.
- [x] Step 3: `cj.py`: token (cached, renewed), `quote(variant, zip)` → item + freight + tax, `place(order)`,
  `pay(cj_id)`, `find(our_no)`, `tracking(cj_id)`, wallet balance.
  - check: `python3 test_orders.py quote`
  - on fail: compare the request shapes with CJ's docs; fix the fake or cj.py; redo Step 3.
- [x] Step 4: `orders.py`: supplier_orders table; each tick, for every channel's paid orders: re-quote, check
  floor and cap and wallet, place + pay once, or put a Jack item with the breakdown and the channel's ship-by date.
  - check: `python3 test_orders.py order_auto order_refused order_cap order_once`
  - on fail: fix orders.py; redo Step 4.
- [x] Step 5: Tracking loop: placed orders polled hourly, tracking sent through the channel's `send_tracking`,
  row marked shipped; addresses purged 30 days after delivery.
  - check: `python3 test_orders.py tracking purge`
  - on fail: fix orders.py; redo Step 5.
- [ ] Step 6: Live check with Jack's key: one real quote for a known CJ variant, no order.
  - check: `ssh ai1@ai-alienware.tail3cffa4.ts.net "cd C:\fleet\hub; C:\fleet\venv\Scripts\python.exe -c \"import cj; print(cj.smoke())\""`
  - on fail: read the CJ error; fix credentials (Jack) or cj.py.

## Done When
- example: Given CJ cost $5.30 on eBay, the floor price is $8.38, and at $8.38 profit after the 12%-tax fee is
  at least $1.50 and at least 10%.
  - check: `python3 test_orders.py floor`
  - fails with: "No module named 'money'"
- example: Given a paid eBay order at $9.99 with $0.80 tax and a fresh CJ quote of $5.30, when the hub ticks,
  then one CJ order is placed and paid to the buyer's address.
  - check: `python3 test_orders.py order_auto`
  - fails with: "No module named 'orders'"
- example: Given the fresh CJ quote rose so profit is under the floor, then nothing is ordered and Jack's list
  shows item, freight, tax, fee and profit lines and the ship-by date.
  - check: `python3 test_orders.py order_refused`
  - fails with: "No module named 'orders'"
- example: Given $47.00 already spent today and a $5.30 order, then nothing is ordered and Jack is asked.
  - check: `python3 test_orders.py order_cap`
  - fails with: "No module named 'orders'"
- example: Given the hub crashed after calling CJ, when it restarts and re-reads the same paid order, then CJ's
  create-order is called once in total.
  - check: `python3 test_orders.py order_once`
  - fails with: "No module named 'orders'"
- example: Given CJ returns a tracking number, then the channel receives it and the row is shipped.
  - check: `python3 test_orders.py tracking`
  - fails with: "No module named 'orders'"
- suite: `python3 test_etsy.py && bash -c 'for c in book watch research slate strategy explore sanity review wall; do python3 test_floor.py $c || exit 1; done'`
- limit: 4 attempts
