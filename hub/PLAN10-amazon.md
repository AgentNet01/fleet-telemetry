# Amazon FBA: stock proposals with full costs, Jack buys, hub lists and tracks

## Goal
An agent's Amazon pick becomes one Jack item showing every cost (unit, freight to Amazon, prep, FBA fee,
referral fee, storage), profit per unit at the current Buy Box price, break-even units and total cash out, and
nothing is bought without Jack's yes. Once stock is at Amazon the hub lists it at a price that clears the money
rule, re-prices daily against the Buy Box, and pulls Amazon sales into the sales table.

## Context
- Overview and money rule: `COMMERCE.md`. Supplier quotes: `PLAN8-supplier.md` (`cj.quote`).
- FBA: we buy stock up front, ship it to an Amazon warehouse, Amazon packs and ships each order. No
  dropshipping on Amazon, so Amazon's seller-of-record rule is met: the stock and packaging are ours.
- SP-API with a private (own-account) app: LWA refresh token → access token. Catalog Items (find the ASIN),
  Listings Restrictions (are we allowed to sell it), Product Pricing (Buy Box and offers), Product Fees
  (FBA + referral fee estimate at a price), Listings Items (list against the ASIN, fulfilment AMAZON_NA),
  Orders (sales).
- New file `amazon.py`, `/api/amazon/*` routes, `fleet amazon propose|list` in fleet.py, sales in
  `_revenue_fetch`.
- Match: `etsy.py` / `test_etsy.py` (fake `http`, vault records), PLAN8 `money.py` (floor, FEES).
- Decision: only existing ASINs; we never create a new product page (avoids brand registry and barcode
  exemptions). An ASIN with a listing restriction for our account is refused.
- Decision, proposal numbers: unit cost and freight from a CJ quote shipped to the FBA warehouse; fees from
  the Product Fees API at the Buy Box price; storage = monthly rate × cubic feet × 3 months assumed sell-through;
  profit/unit must clear the money rule ($1.50 and 10%) or the proposal is refused before it reaches Jack.
- Decision, first buy: at most 20 units or $100 per product, whichever is smaller, until it has sold through once.
- Decision, v1 inbound: after Jack says yes, Jack places the CJ bulk order to the FBA address and creates the
  "Send to Amazon" shipment in Seller Central; the hub gives him a checklist with the numbers. Automating the
  inbound shipment waits until the first product sells through.
- Decision, price: Buy Box price - $0.01 if >= floor, else hold at floor and tell the PM; re-checked daily.
- Only Jack: Professional seller account ($39.99/mo; ID, bank, card, tax interview), FBA on, SP-API
  developer registration + private app (approval can take days) → vault `amazon-app` = {"client_id",
  "client_secret", "refresh_token", "seller_id"}; every stock purchase.

## Must Not Change
- Etsy, eBay, PLAN8 and floor 2: `test_etsy.py`, `test_ebay.py`, `test_orders.py`, `test_floor.py` stay green.
- The hub never spends money on Amazon stock by itself.
- No test reaches real Amazon: `amazon.http` is the fake in `test_amazon.py`.

## Steps
- [x] Step 1: Write each Done When example's test in `test_amazon.py` with `f01-test-driven-development`.
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN10-amazon.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Auth: LWA token from the vault record, cached and renewed.
  - check: `python3 test_amazon.py auth`
  - on fail: fix amazon.py; redo Step 2.
- [x] Step 3: Proposals: `fleet amazon propose <asin> <cj variant>` → restriction check, Buy Box, fee
  estimate, CJ quote to FBA → refused, or one Jack item with every line and the buy checklist.
  - check: `python3 test_amazon.py fba_proposal fba_refused`
  - on fail: fix the cost lines against the worked numbers; redo Step 3.
- [x] Step 4: Listing and re-pricing: list against the ASIN once stock is received; daily Buy Box re-price,
  never below floor.
  - check: `python3 test_amazon.py fba_list reprice`
  - on fail: fix amazon.py; redo Step 4.
- [x] Step 5: Sales: Amazon orders → sales table under the product, once each.
  - check: `python3 test_amazon.py amazon_sales`
  - on fail: fix amazon.py; redo Step 5.
- [ ] Step 6: Deploy (backups `*.bak-amazon`); with Jack's keys, one read-only proposal on a real ASIN.
  - check: `ssh ai1@ai-alienware.tail3cffa4.ts.net "cd C:\fleet\hub; C:\fleet\venv\Scripts\python.exe -c \"import amazon; print(amazon.smoke())\""`
  - on fail: restore the backups, read hub.log, fix, redeploy.

## Done When
- example: Given an ASIN with Buy Box $14.99, fees $5.10, CJ unit + freight to FBA $4.20 and storage $0.15, when
  an agent proposes it, then Jack gets one item showing those lines, profit $5.54/unit, break-even units and cash
  out for 20 units, and no order is placed anywhere.
  - check: `python3 test_amazon.py fba_proposal`
  - fails with: "No module named 'amazon'"
- example: Given the same ASIN with fees that leave under $1.50 or 10%, then the proposal is refused to the
  agent with the numbers and never reaches Jack.
  - check: `python3 test_amazon.py fba_refused`
  - fails with: "No module named 'amazon'"
- example: Given the Buy Box drops below our floor, when the daily re-price runs, then our price stays at the
  floor and the PM is told.
  - check: `python3 test_amazon.py reprice`
  - fails with: "No module named 'amazon'"
- example: Given an FBA order on Amazon, when the hub pulls sales, then it is in the sales table once.
  - check: `python3 test_amazon.py amazon_sales`
  - fails with: "No module named 'amazon'"
- suite: `python3 test_etsy.py && python3 test_orders.py && bash -c 'for c in book watch research slate strategy explore sanity review wall; do python3 test_floor.py $c || exit 1; done'`
- limit: 4 attempts
