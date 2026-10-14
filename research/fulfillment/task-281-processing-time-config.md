# Processing-time configuration: all physical products (task #281)

**Product:** Physical fulfillment · **Role:** engineer · **Date:** 2026-10-14
Status: CONFIGURATION SPEC for PM review. Nothing is set in Etsy until the PM applies it — processing-time settings are listing-level changes that wait for the publish gate.

## The rule (applies to every physical listing)
**Production never starts before buyer proof approval.** The processing-time setting must cover **proof + approval + production**, not production alone. Etsy's processing time = order → carrier hand-off, in business days.

## Proof-gating logic
```
order placed
  → proof generated within 1 business day
  → buyer approval window: 2 business days
      - buyer approves → production starts
      - buyer requests revision (1 free round) → new proof, approval window restarts
      - buyer silent 2 BD → reminder message; order HOLDS (never auto-start production)
      - buyer cancels before approval → cancel order, no production
  → production runs (product-specific, below)
  → ship; tracking written back to buyer
```
Never auto-start production on no-reply. Never set processing time to production-only.

## Processing-time settings per listing

| Listing | Proof | Approval | Production | **Processing setting** | Basis |
|---|---|---|---|---|---|
| Custom birthday paddles (vinyl, Route A) | 1 BD | up to 2 BD | 2–3 BD | **5 BD** | #136 timeline; 7–12 BD total arrival with 2–5d transit |
| Halloween photo keychains (SwiftPOD) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | #210: production time [confirm with SwiftPOD]; planning figure 1.5d → ~5 BD once confirmed |
| Custom birthday cups (Printful tumbler) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Confirm against Printful product page; planning figure ~5 BD |
| Custom birthday hats (cone hats) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Production time not in any verified doc; #247 proved the proof step only |
| Custom birthday banners (Summit) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Production time not in any verified doc |
| Stocking stuffers (PrintKK ornament) | 1 BD | up to 2 BD | **UNVERIFIED** | **DO NOT SET — confirm first** | Production time not in any verified doc |

## Why only paddles gets a number today
Paddles is the only line with a verified timeline (#136: proof + approval + production + transit = 7–12 BD arrival, processing 3–5 BD). The #260 route brief confirms vinyl production 2–3 BD fits inside that window. Setting 5 BD covers the full proof-gated chain with margin.

For the other five lines, publishing a processing-time number now would be inventing a promise. The PM's action items: confirm SwiftPOD keychain production time (from the provider dashboard or a test order, not a blog post), Printful tumbler production time, and the hats/banners/ornament production times — then set each listing to proof + approval + production, rounded up.

## What changes when a setting is confirmed
1. PM sets the Etsy processing-time value per the table.
2. Listing copy states the same figure + the proof-gating sentence: "Production begins after you approve your digital proof."
3. Turnaround/FAQ docs updated to match — no listing may show a shorter time than its setting.
4. Re-check after the first real order: actual proof + approval + production vs the setting; adjust if the setting is breached twice.

## Sources
- #136 turnaround timeline (paddles): proof 1d + approval 1–2d + production + transit = 7–12 BD
- #260 maker route brief: vinyl production 2–3 BD fits the 3–5 BD processing window
- #210 Halloween cutoff doc: SwiftPOD production [confirm with SwiftPOD]
- #135 FAQ / #183 bundle: proof-before-production rule
- #247 hat dry run: proof step proven; production time not specified
