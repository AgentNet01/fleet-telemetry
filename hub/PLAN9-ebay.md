# eBay: resale listings priced by the money rule, fulfilled by CJ

## Goal
Agents post plain resale items to eBay with `fleet ebay post`; the hub, not the agent, sets each price from a
fresh CJ quote and comparable eBay listings (PLAN8 money rule), refuses an item no price can carry, re-prices or
ends live listings daily, pulls paid orders into sales and into PLAN8's ordering, and uploads tracking.

## Context
- Overview and money rule: `COMMERCE.md`. Costs, floor, ordering: `PLAN8-supplier.md` (must be live first).
- eBay policy: dropshipping "from a wholesale supplier" is allowed; buying from "another retailer or
  marketplace that ships directly to your customer" is not. Supplier = CJ only.
- APIs: OAuth authorization-code grant with a RuName (seller token, refresh ~18 months); client-credentials
  token for the Browse API. Inventory API: inventory location (once), inventory item per SKU, offer (EBAY_US,
  fixed price, category, business policies, price), publish → listing id; update offer to re-price, withdraw
  to end. Taxonomy API: category suggestion. Fulfillment API: paid orders, shipping fulfilment (tracking).
  Marketplace Account Deletion: a public endpoint must answer eBay's challenge (SHA-256 of challenge code +
  verification token + endpoint URL) or production keys stay off.
- New file `ebay.py`, plus `/api/ebay/*` routes in hub.py, `fleet ebay post|list` in fleet.py, a Connect eBay
  button on the dashboard's Vault tab, sales in `_revenue_fetch`, listing sync beside Etsy's.
- Match: `etsy.py` / `test_etsy.py` (vault app record, shop record, fake `http`, duplicate guard `_twin`).
- Decision, price: p = (cheapest comparable eBay listing's item + shipping) - $0.01, if p >= PLAN8 floor; else
  refused with both numbers. Comparable = Browse API search on the item's key words, new condition, US, top 20
  by price; fewer than 3 comparables → p = floor × 1.5 capped at $19.99, marked "no comparables" for review.
- Decision, delivery: only CJ variants stocked in a US warehouse are listed, handling time 3 days, so delivery
  stays inside eBay's stated window; a China-only variant is refused.
- Decision, SKU = "cj-<variant id>"; a second post of the same SKU, or a title the duplicate guard matches, is
  refused.
- Decision, daily re-quote: every live listing gets a fresh CJ quote; floor above price → raise to floor if
  still <= cheapest comparable, else end the listing and tell its PM.
- Decision, images: CJ's product image URLs (eBay needs public HTTPS image URLs).
- New eBay accounts start with low selling limits; an eBay "limit" error goes to Jack's list, not retried.
- Only Jack: business seller account (ID, bank, SSN/EIN), business policies (free shipping 3-day handling,
  30-day returns, payment), developer account + Production keyset → vault `ebay-app` = {"client_id",
  "client_secret", "runame"}, accept URL + deletion endpoint pasted from the dashboard, then Connect eBay once.

## Must Not Change
- Etsy, floor 2, PLAN8's money rule: `test_etsy.py`, `test_floor.py`, `test_orders.py` stay green.
- No test reaches real eBay: `ebay.http` is the fake in `test_ebay.py`.

## Steps
- [x] Step 1: Write each Done When example's test in `test_ebay.py` with `f01-test-driven-development`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN9-ebay.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Linking: vault app record, Connect eBay (consent URL, callback, token refresh), deletion
  endpoint answering the challenge.
  - check: `python3 test_ebay.py link deletion`
  - on fail: fix ebay.py / the route; redo Step 2.
- [x] Step 3: Pricing: comparables via Browse API, price from PLAN8 floor, US-warehouse check.
  - check: `python3 test_ebay.py ebay_price`
  - on fail: fix the price rule against the worked numbers; redo Step 3.
- [x] Step 4: Posting: location (once), inventory item, offer, publish; duplicate guard; `fleet ebay post`;
  product linked, PM told.
  - check: `python3 test_ebay.py ebay_post`
  - on fail: fix ebay.py; redo Step 4.
- [x] Step 5: Orders and sales: paid orders → sales table and PLAN8 `paid_orders`; tracking upload as PLAN8's
  `send_tracking`.
  - check: `python3 test_ebay.py ebay_sales tracking`
  - on fail: fix ebay.py; redo Step 5.
- [x] Step 6: Daily re-quote: raise or end.
  - check: `python3 test_ebay.py requote`
  - on fail: fix ebay.py; redo Step 6.
- [ ] Step 7: Deploy (backups `*.bak-ebay`), Jack connects, one real listing posted by an agent and checked on
  ebay.com, then the scout is told eBay is open.
  - check: `ssh ai1@ai-alienware.tail3cffa4.ts.net "cd C:\fleet\hub; C:\fleet\venv\Scripts\python.exe -c \"import ebay; print(ebay.smoke())\""`
  - on fail: restore the backups, read hub.log, fix, redeploy.

## Done When
- example: Given CJ cost $5.30 and the cheapest comparable at $11.49 shipped, when an agent posts the item,
  then it goes live at $11.48 under SKU cj-<variant>, linked to its hub product.
  - check: `python3 test_ebay.py ebay_post`
  - fails with: "No module named 'ebay'"
- example: Given CJ cost $5.30 and the cheapest comparable at $7.99, then the post is refused with "floor $8.38
  is above the market $7.99" and nothing reaches eBay.
  - check: `python3 test_ebay.py ebay_price`
  - fails with: "No module named 'ebay'"
- example: Given a live listing whose CJ cost rose so its floor passed the cheapest comparable, when the daily
  re-quote runs, then the listing is ended and its PM is told.
  - check: `python3 test_ebay.py requote`
  - fails with: "No module named 'ebay'"
- example: Given a paid eBay order, when the hub pulls sales, then it is in the sales table once and offered to
  PLAN8's ordering once, however many pulls run.
  - check: `python3 test_ebay.py ebay_sales`
  - fails with: "No module named 'ebay'"
- example: Given eBay sends its deletion challenge, the endpoint answers with the right hash.
  - check: `python3 test_ebay.py deletion`
  - fails with: "No module named 'ebay'"
- suite: `python3 test_etsy.py && python3 test_orders.py && bash -c 'for c in book watch research slate strategy explore sanity review wall; do python3 test_floor.py $c || exit 1; done'`
- limit: 4 attempts
