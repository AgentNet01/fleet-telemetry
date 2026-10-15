# Prompt library v3 — Local image generation (tools/imagegen)

Measured guards for the fleet's local SD pipeline (DreamShaper 8 / SD 1.5).
v3 adds failure-mode guards from #584. See WORKFLOW.md for setup and the
default negative prompt: `blurry, low quality, distorted, deformed, bad
anatomy, text, watermark`.

## Guard 1 — Filled frames where empty required (#584)

**Failure:** asking for an empty frame, placeholder, or blank area and the
model fills it (a landscape inside the "empty" picture frame, a design inside
the "blank" mockup). The model treats frames as things that *contain* pictures.

**Negative-prompt patterns** (append to the default negative):
```
filled frame, picture inside frame, artwork in frame, photo in frame,
content in frame, image inside frame
```

**Positive-prompt patterns** (state the emptiness explicitly — the model needs
the interior described, not just the frame):
```
the frame is empty, plain white blank interior, nothing inside the frame,
blank canvas, empty placeholder
```

**Before / after example (proven on the fleet pipeline, same seed 42):**
- BEFORE: `a black picture frame hanging on a white wall`
  → every frame filled with mountain/landscape photos. Proof: `guard-proof/frame-before-seed42.png`.
- AFTER: `a black picture frame hanging on a white wall, the frame is empty,
  plain white blank interior, nothing inside the frame`
  + negative: `filled frame, picture inside frame, artwork in frame, photo in frame`
  → blank white interior (minor black-square artifact, no photo content).
  Proof: `guard-proof/frame-after-seed42.png`.

**Rule:** whenever the brief says "empty", "blank", or "placeholder", describe
the *interior* of the thing, not just the thing.

## Guard 2 — Garbled text (#584)

**Failure:** any prompt containing words to render ("a sign that says OPEN")
produces gibberish letterforms. SD 1.5 cannot render legible text; SDXL is
marginally better and still unreliable.

**Negative-prompt patterns** (strengthen the default `text, watermark`):
```
text, words, letters, lettering, typography, watermark, signature,
caption, subtitle
```

**Positive-prompt patterns:**
```
blank sign, no text, empty label, blank chalkboard
```

**Before / after example:**
- BEFORE: `a chalkboard sign in a cafe that says Fresh Coffee`
  → garbled pseudo-letters.
- AFTER: `a blank chalkboard sign in a cafe, no text, empty chalkboard`
  + negative: `text, words, letters, lettering, typography`
  → clean blank sign; add "Fresh Coffee" afterwards with PIL
  (the fleet's standard practice for watermarks and disclosure footers).

**Rule:** never generate text in the model — on EITHER pipeline. #832's
blind shootout found garbled text on local (pair 02) *and* on Muse (pair 17):
"text rendering is not one-sided in this test." Generate the blank surface,
then letter it with PIL. This is a hard rule, not a suggestion — no prompt
engineering makes these models spell reliably.

## Combined quick-reference

| Brief says | Add to positive | Add to negative |
|---|---|---|
| empty/blank frame or placeholder | `the frame is empty, plain white blank interior, nothing inside the frame` | `filled frame, picture inside frame, artwork in frame, photo in frame` |
| sign/label with words | `blank sign, no text` (+ PIL the text after) | `text, words, letters, lettering, typography, watermark, signature` |

---
*v3 — 2026-10-15, Boboe 5 (task #837). Guards measured against #584's
failure modes. v1/v2: WORKFLOW.md measured defaults (#286, #287, #250,
#290, #291).*
*Scope: per #832 (340 blind ratings, 17 raters), local is NOT for mockup
stages — Muse won 96.2%, and the filled-frame failure was systematic (~17/20
pairs). These guards apply to local's authorized lanes (drafts, backgrounds /
textures, internal concepting); the text rule is pipeline-agnostic per #832.*
