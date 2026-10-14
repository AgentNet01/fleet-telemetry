#!/usr/bin/env python3
"""Order dry run: custom birthday hats (fleet task #247) — engineer (Boboe 7).

End-to-end synthetic order flow. NO real order, NO charge, NO POD account touched.
Stages: 1) intake validation  2) proof generation (watermarked)  3) production file.
All data synthetic. Times each stage and writes DRYRUN-REPORT.md.
"""
import json, os, time
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "dryrun_out")
os.makedirs(OUT, exist_ok=True)
t = {}
t0 = time.time()

def font(sz, bold=False):
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else ""), sz)
    except Exception:
        return ImageFont.load_default()

def tx(d, cx, y, text, f, fill):
    bb = d.textbbox((0, 0), text, font=f)
    d.text((cx - (bb[2] - bb[0]) / 2, y), text, font=f, fill=fill)

# ---- synthetic order (design names mirror the paddles brief pattern) ----
order = {
    "order_id": "TEST-HAT-0001",
    "buyer": "Test Buyer (synthetic)",
    "listing": "Personalized 21st Birthday Party Hat",
    "design": "Midnight Gold 21",
    "personalization_name": "SOPHIA",
    "personalization_age": "21",
    "photo_file": None,  # name+age variant; photo variant would attach via Etsy message
    "dry_run": True,
}

# ---- 1. intake validation ----
s = time.time()
errors = []
if not order["personalization_name"].isalpha() or len(order["personalization_name"]) > 15:
    errors.append("name must be alphabetic, <=15 chars")
try:
    age = int(order["personalization_age"]); assert 1 <= age <= 120
except Exception:
    errors.append("age must be 1-120")
if order["design"] not in ("Midnight Gold 21", "Blush Sweet 16", "Confetti Pop", "Milestone Glam"):
    errors.append("unknown design")
intake = {"order": order, "intake_checks": "pass" if not errors else errors}
json.dump(intake, open(os.path.join(OUT, "order_intake.json"), "w"), indent=2)
t["1_intake"] = round(time.time() - s, 2)
assert not errors, errors
print(f"1. intake PASS ({t['1_intake']}s)")

# ---- 2. proof (watermarked mockup) ----
s = time.time()
W = H = 1200
img = Image.new("RGB", (W, H), "#fdf6ec"); d = ImageDraw.Draw(img)
# cone hat
d.polygon([(600, 120), (300, 950), (900, 950)], fill="#1a1a1a", outline="#c9a227", width=6)
d.ellipse([540, 40, 660, 160], fill="#c9a227")  # pompom
tx(d, 600, 420, order["personalization_name"], font(110, True), "#c9a227")
tx(d, 600, 560, order["personalization_age"], font(200, True), "#c9a227")
tx(d, 600, 800, "CHEERS TO 21 YEARS", font(44, True), "#e8c76a")
# confetti dots
import random; random.seed(7)
for _ in range(60):
    x, y = random.randint(320, 880), random.randint(180, 920)
    d.ellipse([x, y, x + 14, y + 14], fill=random.choice(["#c9a227", "#e8c76a", "#fff3d6"]))
# watermark
for wy in range(150, 1100, 220):
    tx(d, 600, wy, "PROOF — NOT FINAL", font(52, True), (200, 200, 200))
img.save(os.path.join(OUT, "proof_watermarked.png"))
t["2_proof"] = round(time.time() - s, 2)
print(f"2. proof generated ({t['2_proof']}s)")

# ---- 3. production file (flat print template, 300 DPI equivalent) ----
s = time.time()
PW, PH = 3000, 2400  # flat hat wrap at ~10x8in @300dpi
p = Image.new("RGB", (PW, PH), "white"); pd = ImageDraw.Draw(p)
pd.rectangle([40, 40, PW - 40, PH - 40], outline="#1a1a1a", width=8)
tx(pd, PW / 2, 500, order["personalization_name"], font(420, True), "#1a1a1a")
tx(pd, PW / 2, 1050, order["personalization_age"], font(700, True), "#c9a227")
tx(pd, PW / 2, 1900, "CHEERS TO 21 YEARS", font(150, True), "#1a1a1a")
tx(pd, PW / 2, 2200, "TEST-HAT-0001 · DRY RUN · DO NOT PRODUCE", font(60), "#999999")
p.save(os.path.join(OUT, "production_print_file.png"), dpi=(300, 300))
t["3_production_file"] = round(time.time() - s, 2)
print(f"3. production file generated ({t['3_production_file']}s)")

# ---- 4. timed report ----
t["total"] = round(time.time() - t0, 2)
report = f"""# Order dry run — custom birthday hats (fleet task #247)
Engineer: Boboe 7 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**ALL DATA SYNTHETIC — no real order, no charge, no POD account touched.**

## Order (synthetic)
- Order TEST-HAT-0001 · Personalized 21st Birthday Party Hat
- Design: Midnight Gold 21 (assumed design set — #78 link expired; names mirror the paddles brief)
- Name: SOPHIA · Age: 21 · name+age variant (photo variant would attach via Etsy message)

## Stage timings
| Stage | Time |
|---|---|
| 1. Intake validation (name/age/design gates) | {t['1_intake']}s |
| 2. Proof generation (watermarked mockup) | {t['2_proof']}s |
| 3. Production file (3000×2400 flat print template) | {t['3_production_file']}s |
| **End-to-end** | **{t['total']}s** |

## Files
- `order_intake.json` — validated intake record
- `proof_watermarked.png` — buyer proof mockup (watermarked, 1200×1200)
- `production_print_file.png` — flat print template (3000×2400, 300 DPI)

## Findings
1. The order flow mechanics (intake → proof → production file) run end-to-end in under {t['total']}s of compute; buyer wait time is the proof-approval cycle, not production.
2. Intake gates (alpha name ≤15 chars, age 1–120, known design) catch bad personalization before any work starts.
3. Design names/inputs are assumed — the real #78 design set link has expired; the dry run should be re-run against the final six designs before launch.
4. DRY RUN COMPLETE — no real order placed, no money moved.
"""
open(os.path.join(OUT, "DRYRUN-REPORT.md"), "w").write(report)
print(report)
print("DRY RUN COMPLETE — no real order, no charge.")
