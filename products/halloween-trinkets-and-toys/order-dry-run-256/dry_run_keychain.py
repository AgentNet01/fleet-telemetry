#!/usr/bin/env python3
"""Order dry run: Halloween photo keychain (fleet task #256) — engineer (Boboe 7).

End-to-end synthetic order flow. NO real order, NO charge, NO Printify account touched.
Stages: 1) intake validation  2) proof generation (watermarked mockup)  3) production file
(acrylic cut-line + UV print artwork). All data synthetic. Times each stage.
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

# ---- synthetic order (per #87 listing package: Personalized Halloween Photo Keychain) ----
order = {
    "order_id": "TEST-KC-0001",
    "buyer": "Test Buyer (synthetic)",
    "listing": "Personalized Halloween Photo Keychain",
    "personalization_name": "LUNA",
    "photo_file": "synthetic_placeholder.png",  # real flow: buyer photo via Etsy message
    "provider": "Printify / SwiftPOD (USA) — Custom Shape Acrylic Keychain, UV print",
    "dry_run": True,
}

# ---- 1. intake validation ----
s = time.time()
errors = []
if not order["personalization_name"].isalpha() or len(order["personalization_name"]) > 15:
    errors.append("name must be alphabetic, <=15 chars")
if not order["photo_file"]:
    errors.append("photo required for photo keychain")
intake = {"order": order, "intake_checks": "pass" if not errors else errors}
json.dump(intake, open(os.path.join(OUT, "order_intake.json"), "w"), indent=2)
t["1_intake"] = round(time.time() - s, 2)
assert not errors, errors
print(f"1. intake PASS ({t['1_intake']}s)")

# ---- 2. proof (watermarked mockup: acrylic keychain with photo + name) ----
s = time.time()
W = H = 1200
img = Image.new("RGB", (W, H), "#1b1030"); d = ImageDraw.Draw(img)
# keychain ring
d.ellipse([520, 60, 680, 220], outline="#c9a227", width=10)
d.line([(600, 220), (600, 300)], fill="#c9a227", width=10)
# acrylic rounded-rect body
d.rounded_rectangle([330, 300, 870, 1000], radius=90, fill="#f5e9d0", outline="#c9a227", width=8)
# synthetic "photo" placeholder (pumpkin-ish circle)
d.ellipse([430, 380, 770, 720], fill="#e2701d", outline="#7a3a0a", width=6)
tx(d, 600, 500, "PHOTO", font(72, True), "#7a3a0a")
tx(d, 600, 590, "(buyer's)", font(44), "#7a3a0a")
tx(d, 600, 800, order["personalization_name"], font(110, True), "#3a1d0a")
tx(d, 600, 900, "HAPPY HALLOWEEN", font(44, True), "#e2701d")
# spiderweb corner doodles
for x, y in [(380, 350), (820, 950), (420, 900)]:
    d.ellipse([x - 12, y - 12, x + 12, y + 12], outline="#7a3a0a", width=3)
# watermark
for wy in range(180, 1150, 240):
    tx(d, 600, wy, "PROOF — NOT FINAL", font(52, True), (160, 150, 170))
img.save(os.path.join(OUT, "proof_watermarked.png"))
t["2_proof"] = round(time.time() - s, 2)
print(f"2. proof generated ({t['2_proof']}s)")

# ---- 3. production file (acrylic cut-line + UV artwork, 300 DPI) ----
s = time.time()
PW, PH = 3000, 3000
p = Image.new("RGB", (PW, PH), "white"); pd = ImageDraw.Draw(p)
# red cut line (industry convention: cut path in red)
pd.rounded_rectangle([700, 700, 2300, 2300], radius=220, outline="#ff0000", width=12)
pd.ellipse([1380, 560, 1620, 800], outline="#ff0000", width=12)  # ring hole cut
# UV artwork inside cut line
pd.rounded_rectangle([760, 760, 2240, 2240], radius=200, fill="#f5e9d0")
pd.ellipse([1050, 950, 1950, 1850], fill="#e2701d")
tx(pd, 1500, 1250, "PHOTO", font(220, True), "#7a3a0a")
tx(pd, 1500, 1950, order["personalization_name"], font(320, True), "#3a1d0a")
tx(pd, 1500, 2700, "TEST-KC-0001 · DRY RUN · DO NOT PRODUCE", font(70), "#999999")
p.save(os.path.join(OUT, "production_print_file.png"), dpi=(300, 300))
t["3_production_file"] = round(time.time() - s, 2)
print(f"3. production file generated ({t['3_production_file']}s)")

# ---- 4. timed report ----
t["total"] = round(time.time() - t0, 2)
report = f"""# Order dry run — Halloween photo keychain (fleet task #256)
Engineer: Boboe 7 · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**ALL DATA SYNTHETIC — no real order, no charge, no Printify account touched.**

## Order (synthetic)
- Order TEST-KC-0001 · Personalized Halloween Photo Keychain ($12.99 + $3.99 shipping)
- Name: LUNA · buyer photo replaced by a synthetic placeholder (real flow: photo via Etsy message)
- Provider: Printify / SwiftPOD (USA) — Custom Shape Acrylic Keychain, UV print (per #72)

## Stage timings
| Stage | Time |
|---|---|
| 1. Intake validation (photo present, name alpha ≤15) | {t['1_intake']}s |
| 2. Proof generation (watermarked mockup, buyer-approval workflow) | {t['2_proof']}s |
| 3. Production file (acrylic cut-line + UV artwork, 3000×3000, 300 DPI) | {t['3_production_file']}s |
| **End-to-end** | **{t['total']}s** |

## Files
- `order_intake.json` — validated intake record
- `proof_watermarked.png` — buyer proof mockup (watermarked, 1200×1200)
- `production_print_file.png` — cut-line + UV artwork (3000×3000, 300 DPI; red = cut path)

## Findings
1. The order flow mechanics (intake → proof → production file) run end-to-end in under {t['total']}s of compute; buyer wait time is the proof-approval cycle, not production — consistent with #255's timeline (proof + approval is the schedule risk, not the machines).
2. Intake gates (photo required, alpha name ≤15 chars) catch bad personalization before any work starts.
3. Production file follows the acrylic convention: red cut path + ring-hole cut, UV artwork inset — ready-shaped for SwiftPOD's UV print process.
4. DRY RUN COMPLETE — no real order placed, no money moved.
"""
open(os.path.join(OUT, "DRYRUN-REPORT.md"), "w").write(report)
print(report)
print("DRY RUN COMPLETE — no real order, no charge.")
