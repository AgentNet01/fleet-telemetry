# banner_composite.py — Production Banner-Text Compositing Tool

**Task #4062** · Consolidates #3831 (prototype), #4010 (auto corner detection),
#4017 (luminance blend + curved-fabric warp) into one script.

## What it does

Takes a **blank scene** (AI-generated background with an empty banner) and
**exact text**, renders the text deterministically with PIL, perspective-warps
it onto the banner, and blends it for photorealism. Text is never
model-generated, so spelling is always 100% correct by construction.

## Workflow: blank scene → finished banner

1. **Generate a blank scene** (no text) with the imagegen tool:
   ```bash
   fleet tool run imagegen --sdxl --seed 42 --steps 30 \
     "backyard birthday party, blank white vinyl banner hanging between two posts, no text"
   ```
2. **Composite the text** (auto-detect the banner, or pass corners manually):
   ```bash
   python3 banner_composite.py --scene blank.png --text "Happy Birthday Emma!" \
     --auto --out finished.png
   ```
3. **Inspect** the output. If `--auto` missed (wrong target or no quad found),
   re-run with `--quad`:
   ```bash
   python3 banner_composite.py --scene blank.png --text "Happy Birthday Emma!" \
     --quad 331,282 1613,306 1604,1034 289,1014 --out finished.png
   ```
4. **Tune realism** per scene (see flags below). Draped fabric wants
   `--warp curve`; flat banners are fine with defaults.

## CLI flags

| Flag | Values | Default | Notes |
|------|--------|---------|-------|
| `--auto` / `--quad` | — | (one required) | Corner source. `--auto` runs the #4010 detector; `--quad` takes `x1,y1 x2,y2 x3,y3 x4,y4` (TL TR BR BL). Mutually exclusive. |
| `--blend` | `luminance` / `flat` | `luminance` | `luminance` multiplies text by scene brightness over the banner so wrinkles/shadows show through (#4017). |
| `--warp` | `flat` / `curve` | `flat` | `curve` applies sine-based horizontal displacement before the perspective warp, for draped fabric (#4017). |
| `--curve` | px | 25 | Peak displacement for `--warp curve`. |
| `--blur` | px | 0.8 | Gaussian blur on the text layer; softens PIL edges onto photos. |
| `--v1` | — | off | Disable all v2 effects (pure #3831 behavior) for comparison. |
| `--color` | `R,G,B` | `20,30,80` | Text color (dark navy default). |
| `--debug` | — | off | With `--auto`: writes `<out>-debug.png` with the detected quad overlay. |

Exit codes: `0` success · `1` usage/error · `2` `--auto` found no quad
(re-run with `--quad`).

## Corner detection (#4010 method)

1. k-means (k=5) on a pixel sample → candidate solid colors, plus the
   center-patch median as an extra candidate.
2. Per candidate: mask within BGR tolerance → morphological cleanup →
   largest connected component → convex hull → `approxPolyDP` quad fit
   (tried at multiple epsilons).
3. Scoring picks the most banner-like quad: rewards area, requires 1.2–6.0
   aspect ratio, penalizes edge-touching corners, rewards rectangularity.

**Honest limits:** assumes a solid-color quadrilateral distinct from its
surroundings. Fails gracefully (exit 2) when it can't find one. Multi-panel
scenes may yield a spanning quad (text crosses the gap — see sample 2).
Pink-on-pink and similar color-ambiguous cases need `--quad`.

## Dependencies

`Pillow`, `numpy`, `opencv-python-headless` (for `--auto` only).
Pure-Python + PIL otherwise; runs on CPU.

## Samples (task #4062)

Run on existing #3831 scenes (which already had text baked in from the
prototype runs — the new text below is what this consolidated script
rendered, composited over the old):

1. **sample1-backyard-auto.png** — backyard scene, `--auto` (quad detected:
   331,282 1613,306 1604,1034 289,1014), default v2 settings
   (luminance blend + blur 0.8, flat warp). Text "Happy Birthday Emma!"
   lands centered on the banner with fabric shading.
2. **sample2-garden-warp.png** — garden scene, `--auto` + `--warp curve
   --curve 25`. Detector picked the spanning quad across both panels
   (documented #4010 behavior); the curved warp follows the fabric drape.

## Provenance

- #3831: Boboe 3 — deterministic composite prototype
- #4010: Dash — auto corner detection + `--quad` fallback
- #4017: Boboe 11 — luminance-multiply blend, blur, curved-fabric warp
- #4062: Boboe 5 — single production script + README + samples
