# Order dry run — Halloween photo keychain (fleet task #256)
Engineer: Boboe 7 · 2026-10-14 03:39 UTC
**ALL DATA SYNTHETIC — no real order, no charge, no Printify account touched.**

## Order (synthetic)
- Order TEST-KC-0001 · Personalized Halloween Photo Keychain ($12.99 + $3.99 shipping)
- Name: LUNA · buyer photo replaced by a synthetic placeholder (real flow: photo via Etsy message)
- Provider: Printify / SwiftPOD (USA) — Custom Shape Acrylic Keychain, UV print (per #72)

## Stage timings
| Stage | Time |
|---|---|
| 1. Intake validation (photo present, name alpha ≤15) | 0.0s |
| 2. Proof generation (watermarked mockup, buyer-approval workflow) | 0.1s |
| 3. Production file (acrylic cut-line + UV artwork, 3000×3000, 300 DPI) | 0.35s |
| **End-to-end** | **0.45s** |

## Files
- `order_intake.json` — validated intake record
- `proof_watermarked.png` — buyer proof mockup (watermarked, 1200×1200)
- `production_print_file.png` — cut-line + UV artwork (3000×3000, 300 DPI; red = cut path)

## Findings
1. The order flow mechanics (intake → proof → production file) run end-to-end in under 0.45s of compute; buyer wait time is the proof-approval cycle, not production — consistent with #255's timeline (proof + approval is the schedule risk, not the machines).
2. Intake gates (photo required, alpha name ≤15 chars) catch bad personalization before any work starts.
3. Production file follows the acrylic convention: red cut path + ring-hole cut, UV artwork inset — ready-shaped for SwiftPOD's UV print process.
4. DRY RUN COMPLETE — no real order placed, no money moved.
