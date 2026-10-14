# Failed delivery and address-issue SOP (task #284)

**Product:** Physical fulfillment · **Role:** engineer · **Date:** 2026-10-14
Grounded in #60 shop policies (final sale for change of mind; damaged/lost/our-error remedies; 12-hour cancellation). Response SLA: **reply within 1 business day** via Etsy Messages. Log every step in the order record.

## Decision tree
```
Buyer reports a delivery problem
├─ Tracking shows "undeliverable / returned / insufficient address / moved"
│   → CASE 1 (undeliverable)
├─ Buyer says the address was wrong
│   → CASE 2 (wrong address)
├─ Tracking shows "delivered" but buyer has no package
│   → CASE 3 (lost) — start with neighbor/mail-area check
└─ Tracking shows no movement 10+ days past estimated delivery
    → CASE 3 (lost) — carrier inquiry, then reship-or-refund
```

## Case 1 — Undeliverable / returned to sender
1. Acknowledge within 1 BD; ask buyer for a corrected address.
2. Verify tracking: confirm the carrier actually marked it undeliverable (not merely delayed).
3. **Whose error?** Compare the label address to the address the buyer entered at checkout.
   - **Buyer's error** (wrong/typo'd address): re-ship to the corrected address at the **buyer's cost** (new shipping charge). If the event date has passed, offer a full refund instead of re-shipping.
   - **Our error** (we printed it wrong): re-ship free, rushed.
4. If the parcel is still in return transit, wait for its return before re-shipping — never ship a second parcel while the first is unaccounted for.
5. If the parcel is lost in return transit → switch to Case 3.

## Case 2 — Wrong address reported by buyer
1. **Before production starts:** correct the address free. No remake, no charge.
2. **After production starts, before ship:** address lives on the label, not the product — correct the label. No remake needed.
3. **After ship:** try a carrier address correction / intercept if available (USPS Package Intercept carries a fee — buyer pays it if the error was theirs). If intercept fails, wait for the undeliverable return → Case 1.
4. **Delivered to the wrong address because of the buyer's error:** no free remake/re-ship. Offer a remake at **50% off** (same principle as #60's buyer-typo rule). If the error was ours, remake/re-ship free.
5. Never re-ship to a new address on a buyer's message alone without verifying the corrected address in writing (Etsy message) — no address changes by phone or social DM.

## Case 3 — Lost package
1. Buyer reports non-delivery → ask them to check neighbors, building mail area, porch, and any safe-drop spot (per #60). Many "lost" parcels are mis-delivered or mis-scanned.
2. Check tracking:
   - **"Delivered" but buyer has nothing:** wait 2 business days (carrier mis-scans are common), then open a carrier inquiry.
   - **No movement 10+ days past estimated delivery** or **carrier confirms lost** → buyer chooses: **one free reship OR full refund** (per #60).
3. If the buyer's event date has passed → refund, don't reship a late personalized item.
4. File the carrier claim for the lost parcel; keep the claim number in the order record.
5. If the buyer opens an Etsy case at any point → respond within Etsy's case window; never let a case go unanswered.

## Rules that apply to all cases
- **Personalized items are final sale for change of mind.** Delivery failures, wrong addresses, and lost parcels are the exceptions above — never refuse a remedy by citing "final sale."
- **One free reship max** for lost parcels. A second loss → refund.
- **Never promise a new delivery date** you can't verify — give the carrier's estimate plus the no-guarantee language.
- **Escalation:** any case involving a chargeback, an Etsy case, or a second failure on the same order → PM reviews before the next action.
