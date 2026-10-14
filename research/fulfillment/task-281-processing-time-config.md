# Processing-time configuration: all physical products (task #281, rev2)

**Product:** Physical fulfillment · **Role:** engineer · **Date:** 2026-10-14
Status: **PROPOSAL for PM review** — nothing here is settled. In particular, the entire proof-gating logic below is **PROPOSED pending PM approval per #201 rev2** (no product currently has a PM-approved proof step). Nothing is set in Etsy until the PM approves the proposal — processing-time settings are listing-level changes that wait for the publish gate.

## The rule (PROPOSED, pending PM per #201 rev2)
**Production never starts before buyer proof approval.** The processing-time setting must cover **proof + approval + production**, not production alone. Etsy's processing time = order → carrier hand-off, in business days.

⚠️ **Proof-step status (read before using any figure below):** per verified #201 rev2, NO product has a PM-approved proof step — the whole proof workflow is a proposal. The #85 paddles package has ZERO proof mentions, and #135's proof promise conflicts with #60 per #131. Every proof term in this doc (1-BD proof generation, 2-BD approval window, 1 free revision, never-auto-start-on-silence) is **PROPOSED**, not settled. If the PM rejects the proof gate, the processing-time figures below must be recomputed without it.

## Proof-gating logic (PROPOSED)
```
order placed
  → proof generated within 1 business day [PROPOSED]
  → buyer approval window: 2 business days [PROPOSED]
      - buyer approves → production starts
      - buyer requests revision (1 free round) [PROPOSED] → new proof, approval window restarts
      - buyer silent 2 BD → reminder message; order HOLDS (never auto-start production) [PROPOSED]
      - buyer cancels before approval → cancel order, no production
  → production runs (product-specific, below)
  → ship; tracking written back to buyer
```

## Processing-time settings per listing

| Listing | Proof | Approval | Production | **Processing setting** | Basis |
|---|---|---|---|---|---|
| Custom birthday paddles (vinyl, Route A) | 1 BD | up to 2 BD | 2–3 BD | **5 BD — ASSUMES unapproved proof step** | #136 timeline (proof-gated, 7–12 BD arrival). The 5 BD figure is only valid if the PM approves the proof gate; without it, recompute as production + buffer. |
| Halloween photo keychains (SwiftPOD) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | #210: production time [confirm with SwiftPOD]; planning figure 1.5d → ~5 BD once confirmed |
| Custom birthday cups (maker UNRESOLVED: Printful vs Printify) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Maker unresolved — PM must decide Printful vs Printify; then confirm production time against the chosen maker's product page. Planning figure ~5 BD. |
| Custom birthday hats (type UNRESOLVED: cone vs cap vs crown) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Hat type unresolved — PM must confirm cone vs cap vs crown; production time not in any verified doc. |
| Custom birthday banners (maker CONTESTED) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Maker contested: #62 says Summit, #237 says "no Summit exists"; #257 reworked to manual sign printer. PM must reconcile before any production time can be set. |
| Stocking stuffers (PrintKK ornament) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Production time not in any verified doc |

## Why only paddles gets a number today
Paddles is the only line with a verified timeline (#136: proof + approval + production + transit = 7–12 BD arrival, processing 3–5 BD). The #260 route brief confirms vinyl production 2–3 BD fits inside that window. Setting 5 BD covers the full proof-gated chain with margin — **but only if the PM approves the proof gate**.

For the other five lines, publishing a processing-time number now would be inventing a promise. The PM's action items: approve/reject the proof gate (fleet-wide, per #201 rev2); confirm SwiftPOD keychain production time; decide cups maker (Printful vs Printify) then confirm production time; confirm hat type (cone vs cap vs crown) then production time; reconcile the banner maker contest (Summit vs #237, #257 manual sign printer); confirm ornament production time — then set each listing to proof + approval + production, rounded up.

## What changes when a setting is confirmed
1. PM approves the proof gate (or directs recomputation without it) and sets the Etsy processing-time value per the table.
2. Listing copy states the same figure + the proof-gating sentence: "Production begins after you approve your digital proof." (Only if the proof gate is approved.)
3. Turnaround/FAQ docs updated to match — no listing may show a shorter time than its setting.
4. Re-check after the first real order: actual proof + approval + production vs the setting; adjust if the setting is breached twice.

## Sources
- #201 rev2 (verified): proof workflow is PROPOSAL pending PM — no product has an approved proof step
- #136 turnaround timeline (paddles): proof 1d + approval 1–2d + production + transit = 7–12 BD
- #260 maker route brief: vinyl production 2–3 BD fits the 3–5 BD processing window
- #210 Halloween cutoff doc: SwiftPOD production [confirm with SwiftPOD]
- #131 QA: #85 has zero proof mentions; #135 proof promise conflicts with #60
- #247 hat dry run (evidence zip verified by Boboe 5): proof generation + production file demonstrated; no production time specified
