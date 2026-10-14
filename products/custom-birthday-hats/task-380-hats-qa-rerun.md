# Hats listing pre-publish QA re-run (task #380)

**Product:** Custom birthday hats · **Role:** optimizer · **Date:** 2026-10-14
Re-run against the now-complete cap package: title/tags #342, description #343, images #344, pricing #274, embroidery spec #276.

## Verdict: PACKAGE INTERNALLY CONSISTENT — NOT YET READY for Jack's publish authorization
All five components describe the same product (Yupoong 6245CM embroidered cap, name+age text embroidery) with no internal contradictions. Publish is still blocked by four external gaps below — none are contradictions inside the package.

## Component checks (all verified against source)

| Component | Status | Evidence |
|---|---|---|
| Title/tags #342 | ✓ Consistent | Title machine-checked: 133/140 chars. 13 tags, max 19 chars, none over 20. No cone/photo-swap claims. Price correctly absent from title. |
| Description #343 | ✓ Consistent | Name+age embroidery, materials (6-panel unstructured, adjustable strap; fabric composition bracketed pending #276), sizing, care, shipping (no delivery promise, 3-week guidance per #277), AI disclosure (not applicable). No proof/revision terms (correctly omitted — not PM-approved). No price in description. |
| Images #344 | ✓ Consistent | Hero + 4 previews, all 2000px, all caps (no cone hats). Personalization shown as name+age text embroidery; how-to-personalize graphic matches the embroidery flow (no photo step). |
| Pricing #274 | ✓ Consistent, planning figures | $32.99 + $8.95 buyer shipping; base $16.12, our shipping $4.95, margin $16.44 (39.2%) — fee math recomputed and correct. Base/shipping are catalog/planning, NOT dashboard-verified (no Printify account). |
| Embroidery spec #276 | ✓ Consistent, UNVERIFIED | Dash's brief: ~15k stitch guideline, free digitizing, 15 Madeira colors (max 6/design), no gradients/photos, front/side/back placement. Verification pending reassignment (procedural fail #3614 — Dash authored the doc). |

## Cross-component consistency (no contradictions found)
- **Product:** all five say Yupoong 6245CM embroidered cap. ✓
- **Personalization:** all five say embroidered name + age TEXT. Zero photo-swap / cone claims anywhere in the package (the #329 failure mode is fixed). ✓
- **Price:** $32.99 + $8.95 in #274 only; correctly absent from title (#342) and description (#343). ✓
- **Lead time:** #343's 3-week guidance matches #277's embroidered-hat lead times. ✓
- **Policies:** #343's final-sale/damage terms match #60. ✓

## Remaining gaps before Jack's publish authorization
1. **PM type decision still OPEN** — per chair's call #3286, #274's cap is a recommendation, not a PM selection. This package is ready IF the PM picks the cap; the PM has not picked it.
2. **#276 not yet verified** — verification reassignment pending (procedural). The embroidery constraints are unconfirmed until an independent verifier passes it.
3. **#274 base/shipping not dashboard-verified** — $16.12 / $4.95 are catalog/planning figures; no Printify account exists to confirm them.
4. **No Printify account / Etsy shop connection** — Jack's action, only after the PM picks the cap.

## Sources
- #342 https://gist.github.com/boboeone/a11764ec0a39825d222474c147c179fa
- #343 https://gist.github.com/boboeone/70a0730156293fd15258ffb4bf358642 (verified pass)
- #344 https://muse.ai/files/1413035511883119/4085178591783899/j12ykf00am8vm6qbgu1gqqr5/cap-listing-images-344.zip
- #274 https://muse.ai/files/1313319791872215/1331042382315863/ov0soqn1gug2k8yb8d83gi6j/task274-hats-pricing-margin.md
- #276 https://muse.ai/files/449498754922635/2546018505918796/113f22nyoudmsxu21in32xzk/embroidery-spec-276.md
- Chair's call #3286: no Printify hat SKU chosen; #274 is a recommendation, not a PM selection
