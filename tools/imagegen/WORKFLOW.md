# Local GPU image generation — workflow

How to use the hub GPU (RTX 3070 Ti, 8 GB) for image generation: setup,
prompts, upscaling, and when to use local vs Muse. Everything here is from
measured runs (#286, #287, #250, #290, #291), not from model docs.

## Setup

No install step — the tool bootstraps. First run downloads the model weights
to the Hugging Face cache (`~/.cache/huggingface`): ~4 GB for the default
SD 1.5 model, ~7 GB for SDXL.

```bash
fleet tool run imagegen --diag
```

Check the log first: it prints `torch=… torch_cuda=… cuda_available=…
device_count=…`. You want `cuda_available=True device_count=1`. If it says
`torch=…+cpu`, the installed torch is the CPU-only wheel — PyPI's torch is
CPU-only — and the GPU will sit idle while generation takes ~255 s instead
of ~4 s. Fix it with one flag (reinstalls torch from PyTorch's CUDA index,
then generates):

```bash
fleet tool run imagegen --cuda-torch "<prompt>"
```

That fix is the whole story of #286: two reinstalls from PyPI kept returning
CPU torch before `--cuda-torch` was pointed at the cu126 index.

Jobs run one at a time on the hub. `fleet tool run` waits up to 10 minutes
and then says "still queued/running" — the job keeps going and a completion
note arrives when it ends. The job log shows only the last 4000 bytes, so
read the `wrote … device=… secs=…` line at the end.

## Basic use

```bash
# Default model (SD 1.5, DreamShaper 8) — fast, 512px
fleet tool run imagegen "<prompt>"

# SDXL-class model (DreamShaper XL) — better rendering, 1024px native
fleet tool run imagegen --sdxl --model Lykon/dreamshaper-xl-1-0 --size 1024 "<prompt>"

# Reproducible: fixed seed, 25 steps
fleet tool run imagegen --seed 101 --steps 25 --size 1024 "<prompt>"
```

Flags: `--seed N` (default random), `--steps N` (default 25),
`--size N` (square px, default 512), `--negative "…"` (default: "blurry,
low quality, distorted, deformed, bad anatomy, text, watermark"),
`--model <HF id or path>` (default `Lykon/dreamshaper-8`,
override with `IMAGEGEN_MODEL`), `--out DIR`.

**Do not pass an absolute `--out`.** On the Windows hub it escapes the
job's output dir and the file is not registered — the job reports "done"
but `fleet tool get` returns 500 'job has no file'. Use the default (`.`)
or a relative subdir.

Sizes: SD 1.5 at 512 (its native res), SDXL at 1024 (its native res).
Generating SDXL at 512 handicaps it; generating SD 1.5 above 512 just
smears it. Neither matches Muse's 1920×1280 originals — see Upscaling.

Measured speed on the hub GPU (device=cuda): SD 1.5, 512px/25 steps,
**4.3 s** generation. SDXL, 1024px/25 steps, **~48–50 s** generation
(plus ~1–2 min pipeline load). Same prompts on CPU: ~255 s.

## Prompts

Write prompts for what these models can actually do. Tested limits
(#250 SD 1.5, #287 SDXL — same briefs, same seeds, one attempt each):

- **Person counts fail.** "Family of four" gave 6 people (SD 1.5) and
  5 people (SDXL). Do not trust the model to count. If the count matters,
  the image is unusable — regenerate or use Muse.
- **No text or labels.** Neither model composes "Before/After" labels or
  SAMPLE badges. The default negative prompt already includes "text".
- **No caricature.** SDXL renders realistic watercolor portraits; it does
  not do exaggerated caricature features. The caricature product cannot be
  made locally — style failure, not a rendering failure.
- **No identity from a photo.** Text-to-image cannot reproduce a specific
  person's likeness. Anything whose promise is "you, as a caricature"
  must not be generated locally.
- **Structure drifts.** "One framed portrait above a sofa" became a gallery
  wall of four frames with different families. "Side-by-side before/after"
  produced two unrelated adult portraits. Simple, single-subject scenes
  hold together; multi-part compositions fall apart.
- **What works:** single-subject scenes, backgrounds, textures, room
  interiors, mood boards — anywhere exact subject fidelity doesn't matter.

For honest evaluation, follow #250/#287 discipline: same brief, fixed
seed, one attempt, no cherry-picking, no prompt engineering. Cherry-picked
samples lie about what the tool will do on the next brief.

## Upscaling

The tool has **no built-in upscaler**. Generate at the model's native
resolution (SDXL 1024) to minimize the need for it.

What is known (#290, Boboe 9): Real-ESRGAN upscales 512→2048px, but the
test ran on a CPU-only hub VM and took 128–152 s/image. GPU upscaling
has not been measured. Until a `--upscale` flag exists, upscaling is a
manual Real-ESRGAN step, not a tool command — do not document it as one.

## When to use local vs Muse

Muse stays the default for **all customer-facing listing art**:
caricature portraits, anything with a specific person's likeness,
anything needing text/labels/badges, anything needing exact counts or
composition. #250 and #287 both tested this head-on; local lost both times.

Use the local GPU for:

- Backgrounds, textures, room-mockup shells (the framed room in #287 was
  coherent; the artwork inside the frames was the failure).
- Drafts, mood boards, internal iteration — free and unlimited, ~48 s/image
  at SDXL quality, ~4 s/image at SD 1.5 quality.
- One-off upscaling (narrow niche where local wins per #291).

Cost comparison: local is free and unlimited. Muse is ~19 s/image at
1920×1280 (#291 baseline) with better adherence. Speed is not the reason
to switch — quality for the specific job is.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `device=cpu`, ~255 s | CPU-only torch. Run once with `--cuda-torch`. |
| Job "done" but `tool get` 500 'job has no file' | Absolute `--out` escaped the job dir. Re-run with default/relative `--out`. |
| SDXL job fails at `enable_vae_slicing` | Old tool version; the runner pulls fresh each job, so re-run. |
| Job fails mid weight-load, log ends at a progress bar | Killed (service restart / resource). Re-run; the model is cached. |
| Duplicate identical jobs | A retried `fleet tool run` can queue twice. Use the first completion; ignore the other. |
