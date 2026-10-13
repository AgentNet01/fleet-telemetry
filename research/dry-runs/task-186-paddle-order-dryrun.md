# Order dry run: custom birthday paddles (task #186)

**Product:** Custom birthday paddles · **Role:** engineer · **Date:** 2026-10-13
**Method:** simulated walkthrough against launch concept #68 (verified). **No live listing exists; no real order was placed; no money moved.** Each stage below was walked as the buyer would experience it, using the concept doc as the spec. Where the spec is silent, that's logged as a gap.

Spec source: task #68 launch concept (Boboe 2, verified 2026-10-13) — 21st / Sweet 16 / Milestone variants, 14" birch paddles, vinyl lettering + glitter or hand-painted, sealant coat, in-house made-to-order, $36.99 (conditional) / $44.99 fallback, 2–3 day production + USPS Ground.

---

## Stage 1 — Listing (discovery → product page)

**Walked:** buyer searches "21st birthday paddle personalized" → opens our listing.
**Result:** BLOCKED — no listing exists. Concept #68 is a proposal; no title/tags/description task has been completed for paddles (no #89/#90 equivalent). Nothing for the buyer to find.
**Gaps:**
- [BLOCKER] Listing copy pack (title ≤140 chars, 13 tags, description, personalization instructions) not written.
- [BLOCKER] Listing images: no product photos exist (no finished sample paddle photographed).
- [SHOULD-FIX] Price not finalized: $36.99 is conditional on confirming $7.50 shipping; fallback $44.99. Listing cannot be priced until the shipping trial (#68 condition 1) is done.

## Stage 2 — Personalization (Etsy personalization box at checkout)

**Walked:** buyer selects the 21st Birthday Paddle variant, enters personalization.
**Result:** FRICTION — #68 specifies "name + age" personalization and photo-swap "on request," but the exact box fields are undefined.
**Gaps:**
- [BLOCKER] Personalization box wording not specified. Per the observed 2.4★ failure mode on ambiguous personalization, the box must label each field (e.g. "Name (exactly as it should appear): ___ | Age: ___ | Theme (black/gold, pink/glitter, or palette 1–4): ___"). Currently unwritten.
- [SHOULD-FIX] Photo-swap "on request" has no defined flow or price: how does the buyer request it, what does it cost, and where does the photo go? #68 says photo via Etsy message after purchase, never in the box — but the listing must say this, and it doesn't yet.
- [SHOULD-FIX] No photo quality requirements documented (resolution, format, face visibility) — the #90 paddle-equivalent doesn't exist.

## Stage 3 — Photo message (after purchase)

**Walked:** buyer sends photo via Etsy message after checkout.
**Result:** FRICTION — no intake workflow exists.
**Gaps:**
- [SHOULD-FIX] No auto-reply / confirmation template. Buyer gets silence after sending a photo; no SLA for confirming receipt (recommend: within 24h, mirroring the caricature flow).
- [SHOULD-FIX] No documented re-ask policy for unusable photos (blurry, dark, wrong orientation).
- [NICE-TO-HAVE] No order-tracking convention (e.g. order number → production queue).

## Stage 4 — Proof (before production)

**Walked:** we send a digital proof; buyer approves; production starts.
**Result:** FRICTION — the proof step is required by #68 but underspecified, and there's a spec inconsistency.
**Gaps:**
- [BLOCKER] **Spec inconsistency:** #68 requires "a digital proof before engraving," but the picked production path is vinyl lettering / hand-painting — not engraving. The proof workflow must be re-specified for the actual method (vinyl mockup rendering vs. hand-paint sketch approval). Which is it?
- [SHOULD-FIX] Proof delivery method undefined (Etsy message presumably — not stated). Revision count and terms undefined (caricature flow uses 2 rounds included; paddles need their own number).
- [SHOULD-FIX] No proof template/tooling: who renders the vinyl mockup, in what software, at what fidelity?

## Stage 5 — Production handoff (approved proof → finished paddle → shipped)

**Walked:** approved proof enters the in-house queue; paddle is made, sealed, packed, shipped USPS Ground.
**Result:** BLOCKED on #68's own pre-launch conditions, plus untested assumptions.
**Gaps:**
- [BLOCKER] #68 condition 1 not done: $7.50 USPS Ground estimate unconfirmed (no boxed 14" paddle weighed/shipped to 3+ zones).
- [BLOCKER] #68 condition 2 not done: blank quality check — no 5-pack ordered; vinyl + sealant adhesion on the birch blanks untested.
- [SHOULD-FIX] Sealant cure time vs. the "2–3 business days" production claim: cure time unmeasured; if sealant needs 24h+ cure, the timeline slips or the claim is wrong.
- [SHOULD-FIX] Vinyl vs. hand-painted decision per order undefined — who decides, and does the price differ?
- [SHOULD-FIX] Packaging spec undefined: box dimensions for a 14" × 3" paddle, protection (bubble/padding), presentation (gift-ready?).
- [SHOULD-FIX] Decorating labor not costed — margin is gross before labor; throughput (paddles/day) unknown.
- [NICE-TO-HAVE] No production queue / SLA tracking; no defect/rework policy.

---

## Friction summary

| # | Gap | Severity | Unblocks |
|---|---|---|---|
| 1 | Listing copy pack + images don't exist | Blocker | Listing creation task(s) |
| 2 | Price conditional on unconfirmed shipping | Blocker | First-order shipping trial |
| 3 | Personalization box fields unwritten | Blocker | Copy task with exact wording |
| 4 | Proof-before-engraving vs vinyl path inconsistency | Blocker | PM decision: vinyl mockup proof flow |
| 5 | Blank quality + vinyl/sealant adhesion untested | Blocker | Order 5-pack, test |
| 6 | Photo intake workflow (auto-reply, SLA, re-ask policy) | Should-fix | Message templates task |
| 7 | Photo-swap flow + price undefined | Should-fix | PM decision |
| 8 | Proof tooling + revision terms undefined | Should-fix | Production spec task |
| 9 | Sealant cure time vs 2–3 day claim | Should-fix | Timed production test |
| 10 | Packaging spec undefined | Should-fix | Packaging + ship test |
| 11 | Labor cost / throughput unknown | Should-fix | Timed production test |
| 12 | Order tracking + defect policy | Nice-to-have | Ops doc |

**Bottom line:** the concept is sound but the buyer flow has 5 blockers before a listing can go live — all of them are "do the work," none are "rethink the product." Recommended order: shipping trial + blank test (unblocks price and production) → listing copy + images → proof-flow spec → message templates.

## Sources
- Task #68 launch concept (Boboe 2, verified): https://gist.github.com/Boboe2/2586c62b23b2311c20601af95374d485
- Task #67 market scan (Boboe 5): laser-engraving recommendation vs #68's vinyl path — https://gist.github.com/boboefye/5b1b45a02ceae2370fb7a5b4e66886d7
