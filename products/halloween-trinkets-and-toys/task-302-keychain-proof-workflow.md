# Keychain photo-swap proof workflow (task #302)

**Product:** Halloween trinkets and toys · **Role:** engineer · **Date:** 2026-10-14
Status: **PROPOSED workflow for PM approval** — per #201 rev2, no product currently has a PM-approved proof step. This doc defines the proposed workflow and demonstrates it with a sample proof image. Nothing is live until the PM approves.

## Workflow (PROPOSED)

| Step | What happens | SLA |
|---|---|---|
| 1. Order intake | Buyer purchases the keychain listing, selects shape (ghost / pumpkin / bat / candy corn), enters name/age if any, and sends their photo via Etsy message after purchase. | Buyer-side |
| 2. Photo validation | Seller checks the photo: clear, well-lit, subject's face visible, min 2000px long edge preferred. **Bad photo → re-request within 24h** with specific guidance ("closer, brighter, face toward camera"). Never composite a photo that can't print cleanly. | 1 BD |
| 3. Composite | Seller composites the photo into the chosen keychain shape (photo-swap zone), adds name/age text if ordered, renders the proof at 1200×1200 with a **SAMPLE PROOF watermark** across the full image. The proof is a mockup of the finished keychain, not the production file. | 1 BD |
| 4. Proof sent | Watermarked proof sent to the buyer via Etsy message with: "Here's your proof. Reply APPROVE to start production, or tell us one change (free revision)." | Same day as step 3 |
| 5. Buyer decision | **APPROVE** → production file generated from the approved composite (unwatermarked, 300 DPI) and production starts. **Revision** → one free revision round; new proof sent, window restarts. **Silence 2 BD** → reminder message; order HOLDS (never auto-start production). **Cancel before approval** → cancel order, no production. | Approval window 2 BD |
| 6. Production | Approved production file submitted to SwiftPOD. Buyer gets the tracking number when it ships. | Per #281 processing config |

## Rules
- The proof is always watermarked. The production file is never sent to the buyer.
- One free revision round. Further revisions: seller's discretion (minor tweak free; full redesign = new order).
- Production never starts before approval — even if the buyer's event is tomorrow.
- Photo privacy: buyer's photo is used only for their order, never in marketing, unless they explicitly agree.

## Sample proof image
Ghost-shape keychain with a sample (synthetic) golden retriever photo swapped in, watermarked SAMPLE PROOF — demonstrates exactly what a buyer sees at step 4. See the image link in the task evidence.

## Sources
- #201 rev2: proof workflow is PROPOSAL pending PM
- #281 processing-time config: proof-gating logic (PROPOSED)
- #210 Halloween cutoff doc: SwiftPOD production [confirm with SwiftPOD]
- listing-package/00-listing.md: shapes, personalization flow (photo via Etsy message)
