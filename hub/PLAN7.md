# Etsy: designed items only

## Goal
The Etsy shop sells only items we design (Printify prints, engraved/personalised, generated art, downloads).
The hub refuses a resale listing, the scout never sends resale to Etsy, no resale listing is live, and the hub
stays under Etsy's 10,000 API calls a day so the sales pull works.

## Context
- Overview and money rule: `COMMERCE.md`.
- Why: Shop Manager → Policy violations shows ~64 removals, every one "Creativity Standards", Oct 20-27, all
  resold AliExpress items. 123 listings were live, 115 of them resale.
- `etsy.py` post(): refusal rule `RESALE` (dropship supplier named in the product brief, title or description).
- `hub.py` _scout: the ask sent to idle agents; now routes designed → Etsy, resale → eBay.
- `etsy.py` sync_listings: was one GET per listing every 10 min (~25k/day vs 10k limit → 429, sales pull
  broken). Now one batch call per 100 listings.
- `etsy_audit.py`: read-only list of live listings marked KEEP / RESALE, exit 1 if any resale; `--off` turns
  the resale ones off and logs each.
- Match: `test_etsy.py` FakeEtsy harness.
- Decision: refusal is by supplier words, not by a production-partner field, because the hub's product briefs
  already name the supplier and the existing Printify listings carry no partner id.
- Decision: the 115 resale listings are turned off, not deleted, so they can be moved to eBay later.
- Etsy limit: `retry-after 23211` at 01:33 Oct 28, so the turn-off runs as one-shot task `etsy-resale-off`
  at 08:10 on the hub PC, output in `C:\fleet\etsy_resale_off.log`.

## Must Not Change
- The budgeting-templates listing, the 8 designed listings (pet portraits, caricatures, storybooks, birthday
  banners/cups/hats, stocking stuffers, Halloween magnet) and every Printify listing stay live.
- `fleet etsy update`, shop linking and the sales pull keep working: `test_etsy.py` stays green.

## Steps
- [x] Step 1: Write each Done When example's test with `f01-test-driven-development` (`test_commerce.py`).
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py PLAN7.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Etsy guard in post(), scout routing, batched listing sync; deployed 01:31 Oct 28.
  - check: `python3 test_commerce.py etsy_resale scout && python3 test_etsy.py`
  - on fail: fix etsy.py / _scout; redo Step 2.
- [ ] Step 3: After 08:10, read `C:\fleet\etsy_resale_off.log`: every RESALE line says "turned off", every KEEP
  line is a designed item. Then re-run the audit read-only.
  - check: `ssh ai1@ai-alienware.tail3cffa4.ts.net "cd C:\fleet\hub; C:\fleet\venv\Scripts\python.exe etsy_audit.py"`
  - on fail: a KEEP line that is resale → add its supplier word to RESALE (Step 2); a RESALE line still live →
    re-run with `--off`; a 429 → wait for `retry-after`.
- [ ] Step 4: Bring the kept listings in line with `etsy-creativity-standards.md`: Printify added as a production
  partner (Shop Manager → Settings → Production partners, Jack's OK first) and attached to each Printify listing;
  "made with AI" in the description of every AI-generated item; first photo of each personalised item is a
  finished example. Agents told the same rules in the scout ask.
  - check: compare against etsy-creativity-standards.md
  - on fail: fix the listing in the editor (or `fleet etsy update`), redo Step 4.
- [ ] Step 5: Commit and push the Etsy changes once Jack says yes.
  - check: `git -C .. diff --quiet origin/main -- hub/etsy.py hub/hub.py hub/test_etsy.py`
  - on fail: ask Jack again; nothing else depends on it.

## Done When
- example: Given a product whose brief says "AliExpress, $1.80", when an agent runs `fleet etsy post` for it,
  then the hub refuses, names eBay, and nothing reaches Etsy.
  - check: `python3 test_commerce.py etsy_resale`
  - fails with: "etsy accepted a resale listing"
- example: Given an idle agent, when the hub scouts it, then the ask sends resale finds to eBay and only designed
  items to Etsy.
  - check: `python3 test_commerce.py scout`
  - fails with: "scout still sends resale to Etsy"
- example: Given the live shop after Step 3, every active Etsy listing is designed or digital.
  - criterion: PASS if `etsy_audit.py` on the hub prints no RESALE line and its KEEP lines are all designed
    items; FAIL otherwise.
- suite: `python3 test_etsy.py && python3 test_autonomy.py scout && bash -c 'for c in book watch research slate strategy explore sanity review wall; do python3 test_floor.py $c || exit 1; done'`
- limit: 3 attempts
