# Automation workflow spec: design → shipping (task #240)

**Product:** Physical fulfillment · **Role:** engineer · **Date:** 2026-10-13
Status: TECHNICAL SPEC for review. Builds nothing, installs nothing, charges nothing. Per owner directive #2133: dot owns Printify API engineering and Alienware Hub hosting feasibility; this spec defines what that build must implement.

## 0. Principles
- **Humans gate money, publishing, and brand.** Automation prepares; it never publishes a listing, changes live branding, or spends money without the named approval.
- **Every order is a state machine.** No silent drops: an order is always in exactly one known state, and stuck states page a human.
- **Idempotent everywhere.** Retries must never double-charge or double-submit.

## 1. Stages

| # | Stage | What happens | Human gate |
|---|---|---|---|
| 1 | Design intake | Designs + personalized templates land in the repo (Brutus/Boboes under pericles). Each design gets a product record: SKU, Printify product/variant IDs (from Neo's SKU mapping), print file specs. | Design QA by PM before a SKU goes live. |
| 2 | Printify product draft | Orchestrator creates the product via Printify API (`POST /v1/shops/{shop_id}/products.json`) as a **draft**, mockups generated, not pushed to any sales channel. Draft creation costs nothing. | None (no charge, no public surface). |
| 3 | Listing publish | Draft pushed to the connected Etsy shop via Printify's sales-channel publish. | **PM QA + Jack's authorization** — first publish per product, per #2133. No auto-publish on new SKUs. |
| 4 | Order intake | Etsy order → Printify import (auto-import or webhook `order:created`) → orchestrator records order: Etsy order ID, items, buyer personalization inputs, payment status. Orders with unpaid/held payment stay in `received_unpaid` and never proceed. | None for paid orders; unpaid held for buyer action. |
| 5 | Personalization render | For personalized SKUs: merge buyer inputs into the design template → generate print-ready file → upload to Printify (`POST /v1/uploads/images.json`) → attach to order. Buyer proof sent via Etsy message; production waits for approval (same proof-before-production rule as existing product specs). | **Buyer approves proof.** Non-personalized SKUs skip to stage 6. |
| 6 | Production submit | Submit to Printify (`POST /v1/shops/{shop_id}/orders.json`) with idempotency key = Etsy order ID. Poll `order:shipment:created` / status endpoints. | None. |
| 7 | Shipping & delivery | Tracking number from Printify → written back to Etsy order → buyer notified (template). | None. |
| 8 | Reconciliation | Nightly job: every Etsy order has a matching Printify order in a terminal state; every Printify charge has a matching order; margin per order logged. | Discrepancies → human review queue. |

## 2. APIs and integration points
- **Printify REST API** (`api.printify.com/v1`): shops, catalog, products, orders, uploads, webhooks. Auth: API token from the vault/fleet secret only — never in chat, logs, code, or screenshots. dot's engineering task covers client implementation and hosting.
- **Webhooks:** Printify `order:created`, `order:updated`, `order:shipment:created` → our listener. Verify webhook signatures; acknowledge fast, process async.
- **Etsy API:** listing/order read-write is a **dependency, not assumed**. Requires a separate Etsy app + OAuth grant (owner action). Until then, Etsy-side actions (tracking write-back, message templates) are manual or via Printify's channel sync. Mark every Etsy-API-dependent step in the build plan as BLOCKED until credentials exist.
- **Hosting:** runtime location per dot's Alienware Hub feasibility (#2133). Spec is host-agnostic: one stateless orchestrator + a persistent order-state store (Postgres/SQLite) + a job queue.

## 3. Failure handling
- **Webhook loss/dupes:** signature verify; dedupe on event ID; missed events caught by the nightly reconciliation (stage 8).
- **Submission failure:** exponential backoff (5 tries); after that, order → `submit_failed` and pages the on-call human. Idempotency key prevents double orders on retry.
- **Provider errors (print reject, out of stock):** order → `provider_blocked`; auto-fallback to the alternate supplier for that SKU if Neo's mapping defines one; otherwise human picks.
- **Stuck orders:** alert if an order sits >4h in `artwork_ready`, >24h in `submitted` without production start, or >7d in `shipped` without delivery scan.
- **Cost guardrails:** per-order cost ceiling = 60% of item price; breach → hold + human review. No auto-increase of ad spend, ever.
- **Buyer comms failures:** every buyer-facing message is templated and logged; failed sends retry 3× then escalate to the marketer.

## 4. Data model (minimum)
`orders(etsy_order_id PK, printify_order_id, sku, state, personalization_json, proof_status, cost_cents, price_cents, created_at, updated_at)` · `events(order_id, type, payload, at)` (append-only audit log) · `skus(sku PK, printify_product_id, variant_ids, template_ref, fallback_supplier)`.

## 5. What this spec does NOT authorize
- No API key handling by anyone except the owner via the secure install flow.
- No listing published, no storefront branding changed, no charges incurred without the gates in §1.
- No physical sample order yet (per #2133 — sample planning is separate).

## Dependencies
- dot: Printify API client + Alienware Hub hosting feasibility (owner directive #2133).
- Neo: product → Printify SKU mapping with fallback suppliers.
- pericles: brand/visual standards the templates must satisfy.
- Owner: Etsy API app/OAuth if direct Etsy integration is wanted; API key install (already in vault per #2133).
