# Commerce: three shops, one supplier, one money rule

Oct 28. Etsy removed ~64 of our listings for "Creativity Standards" (resold AliExpress items), listing fees
(~$35) passed revenue ($32.23), and Jack placed an order on AliExpress by hand. Jack's decision: resale goes to
eBay (dropship) and Amazon (FBA); Etsy keeps only what we design.

## The shape

| Channel | Sells | Stock | Who fulfils | Plan |
|---|---|---|---|---|
| Etsy | designed: Printify prints, engraved/personalised, generated art, downloads | none | Printify / us | PLAN7.md |
| eBay | plain resale items | none | CJdropshipping ships to the buyer | PLAN9-ebay.md |
| Amazon | resale items worth stocking | bought up front, on Jack's yes | Amazon (FBA) | PLAN10-amazon.md |
| (shared) | supplier quotes, money rule, automatic orders | — | CJ | PLAN8-supplier.md |

Why CJ, not AliExpress: eBay allows dropshipping "from a wholesale supplier" and bans buying from "another
retailer or marketplace that ships directly to your customer". AliExpress is a marketplace. Amazon requires the
buyer to see only us as seller. CJ is a wholesale dropshipper with unbranded packaging, US warehouses, and an
API for quotes, orders, payment and tracking.

## The money rule (binds every plan)

Jack: "An item should never be priced at something where ordering it would take a loss, including the fees."

- **Landed cost** = supplier item + supplier shipping to the buyer + tax the supplier charges + channel fees
  (eBay's fee is on the buyer's total including sales tax and shipping, so it is computed at a 12% tax buffer,
  above the highest US combined rate).
- **Profit floor**: profit >= $1.50 **and** >= 10% of the buyer's price. The stricter wins.
- **Price**: as high as possible while at or under the cheapest comparable listing. No price clears the
  floor → not listed.
- **Costs come from the supplier's own quote** (CJ variant price + freight quote to the US), never from an
  agent's guess. Re-quoted daily for every live listing; floor broken → raise the price or end the listing.
- **Spend cap**: $50/day of automatic supplier orders. The CJ wallet balance is a second, hard cap.
- **Buyer sales tax is not our cost**: eBay, Amazon and Etsy collect and remit it (Jack confirmed Oct 28).
- **No return reserve** in the price: returns and refunds are booked in our own accounting (Jack, Oct 28).
- Everything outside the rule goes to Jack's list with the numbers, never silently.

## Order of work

1. **Etsy (PLAN7)**: now. Guard and scout are live; the resale listings go off at 08:10 Oct 28.
2. **Supplier + money (PLAN8)**: build now against a fake CJ; live once Jack adds the CJ key.
3. **eBay (PLAN9)**: build now against a fake eBay; uses PLAN8 for every price; live once Jack's eBay keys
   are in and PLAN8 is live.
4. **Amazon FBA (PLAN10)**: build alongside; live once Amazon approves the SP-API app (can take days).

2-4 can be built in parallel. Nothing goes live on eBay before PLAN8 can quote, price and order.

## Status (Oct 28, 02:00)

| Plan | Built + tested against fakes | Live on the hub | Waiting on |
|---|---|---|---|
| PLAN7 Etsy | yes | guard, scout, batched sync (01:31) | 08:10 turn-off run; Printify partner OK; commit OK |
| PLAN8 supplier | yes (9 tests) | yes, idle until a channel has orders | `cj-key` in the vault, CJ wallet funded |
| PLAN9 eBay | yes (7 tests) | routes, dashboard card, deletion endpoint answering | eBay accounts + keys, Connect eBay |
| PLAN10 Amazon | yes (6 tests) | routes, `fleet amazon` | Amazon seller account, SP-API app approval, `amazon-app` in the vault |

Each plan's last step is a read-only live check (`cj.smoke`, `ebay.smoke`, `amazon.smoke`) run once the keys
are in, before any real listing or order.

## Shared rules

- Tests run against fakes only: no real listing, order, payment or deactivation from a test.
- Every deploy: back up the live files (`*.bak-<plan>`), copy, restart, read `hub.log`; restore on error.
- Secrets live only in the dashboard vault, scope `hub`; agents never see them.
- Buyer addresses are kept only until the order is delivered + 30 days, then deleted.
- Floor 2 (sports desks) is never touched: `test_floor.py` stays green.

## Open questions for Jack

None open. Answered Oct 28: buyer sales tax is not our cost; no return reserve.
