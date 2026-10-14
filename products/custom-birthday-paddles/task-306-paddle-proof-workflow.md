# Photo-swap proof workflow: custom birthday paddles (task #306)

**Product:** Custom birthday paddles · **Role:** engineer · **Date:** 2026-10-14
Status: **PROPOSED workflow for PM approval** — per #201 rev2, no product currently has a PM-approved proof step. This doc defines the proposed workflow and demonstrates it with a sample proof image. Nothing is live until the PM approves. (Also note: the maker route decision — vinyl vs laser — is still pending PM per #260; this workflow assumes the recommended Route A vinyl + photo. If Route B laser is chosen, there is no photo step and this workflow does not apply.)

## Workflow (PROPOSED)

| Step | What happens | SLA |
|---|---|---|
| 1. Order intake | Buyer purchases the paddle listing, selects design (21st Black+Gold / Sweet 16 Pink Glitter / Milestone Navy+Gold), enters name + age, and sends their photo via Etsy message after purchase. | Buyer-side |
| 2. Photo validation | Seller checks the photo: clear, well-lit, subject's face visible, min 2000px long edge preferred. **Bad photo → re-request within 24h** with specific guidance ("closer, brighter, face toward camera"). Never composite a photo that can't print cleanly. | 1 BD |
| 3. Composite | Seller composites the photo into the design's oval photo-swap zone, adds name + age in the design's vinyl lettering, renders the proof at 1200×1200 with a **SAMPLE PROOF watermark** across the full image. The proof is a mockup of the finished paddle, not the production file. | 1 BD |
| 4. Proof sent | Watermarked proof sent to the buyer via Etsy message with: "Here's your proof. Reply APPROVE to start production, or tell us one change (free revision)." | Same day as step 3 |
| 5. Buyer decision | **APPROVE** → production file generated from the approved composite (unwatermarked, 300 DPI) and production starts. **Revision** → one free revision round; new proof sent, window restarts. **Silence 2 BD** → reminder message; order HOLDS (never auto-start production). **Cancel before approval** → cancel order, no production. | Approval window 2 BD |
| 6. Production | Approved production file used for the vinyl/decal + sealant build. Buyer gets the tracking number when it ships. | Per #281 processing config (5 BD) |

## Rules
- The proof is always watermarked. The production file is never sent to the buyer.
- One free revision round. Further revisions: seller's discretion (minor tweak free; full redesign = new order).
- Production never starts before approval — even if the buyer's event is tomorrow.
- Photo privacy: buyer's photo is used only for their order, never in marketing, unless they explicitly agree.
- Spelling: the buyer confirms name/age spelling at approval — after approval, a buyer typo falls under #60's 50%-off remake rule.

## Sample proof image
21st Black+Gold paddle with a sample (synthetic) photo composited into the oval photo zone, SOPHIA + 21 in gold vinyl lettering, watermarked SAMPLE PROOF — demonstrates exactly what a buyer sees at step 4. See the image link in the task evidence.

## Sources
- #201 rev2: proof workflow is PROPOSAL pending PM
- #260 maker route brief: Route A (vinyl + photo) recommended; route decision pending PM
- #281 processing-time config: proof-gating logic (PROPOSED)
- #85 listing package: designs, personalization flow (photo via Etsy message)
- #183 bundle package: proof-step wording model
