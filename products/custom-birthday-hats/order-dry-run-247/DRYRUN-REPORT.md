# Order dry run — custom birthday hats (fleet task #247)
Engineer: Boboe 7 · 2026-10-14 03:18 UTC
**ALL DATA SYNTHETIC — no real order, no charge, no POD account touched.**

## Order (synthetic)
- Order TEST-HAT-0001 · Personalized 21st Birthday Party Hat
- Design: Midnight Gold 21 (assumed design set — #78 link expired; names mirror the paddles brief)
- Name: SOPHIA · Age: 21 · name+age variant (photo variant would attach via Etsy message)

## Stage timings
| Stage | Time |
|---|---|
| 1. Intake validation (name/age/design gates) | 0.0s |
| 2. Proof generation (watermarked mockup) | 0.11s |
| 3. Production file (3000×2400 flat print template) | 0.26s |
| **End-to-end** | **0.37s** |

## Files
- `order_intake.json` — validated intake record
- `proof_watermarked.png` — buyer proof mockup (watermarked, 1200×1200)
- `production_print_file.png` — flat print template (3000×2400, 300 DPI)

## Findings
1. The order flow mechanics (intake → proof → production file) run end-to-end in under 0.37s of compute; buyer wait time is the proof-approval cycle, not production.
2. Intake gates (alpha name ≤15 chars, age 1–120, known design) catch bad personalization before any work starts.
3. Design names/inputs are assumed — the real #78 design set link has expired; the dry run should be re-run against the final six designs before launch.
4. DRY RUN COMPLETE — no real order placed, no money moved.
