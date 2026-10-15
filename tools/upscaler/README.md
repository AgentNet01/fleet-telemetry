# tools/upscaler — upscale images 4x with Real-ESRGAN x4plus

Upscale images with Real-ESRGAN x4plus and report per-image seconds, VRAM
peak (CUDA), and a bicubic baseline for blind quality comparison.

## Run

```
fleet tool run upscaler --input <image-url> [--input <image-url> ...]
python3 tools/upscaler/run.py --input <url-or-path> [--input ...] [--out DIR] [--baseline]
```

Writes `<name>_esrgan.png`, `<name>_bicubic.png` (with `--baseline`), and
`report.json`. Inputs are resized so the long edge is 640px by default
(`--prep-long-edge 0` keeps native size) — 640px stands in for local GPU
output, and 4x lands at 2560px, about the 300-DPI size of an 8.5" print.

## Install (once per machine)

```
pip install --user torch Pillow numpy
```

GPU machine: CUDA torch wheel. CPU-only machine: CPU wheel
(`--index-url https://download.pytorch.org/whl/cpu`). `run.py` bootstraps
missing deps itself on first run (disable with `UPSCALER_NO_BOOTSTRAP=1`).

## Model

Real-ESRGAN x4plus (Xintao Wang et al.), weights
`RealESRGAN_x4plus.pth` (~64 MB) from the official v0.1.0 release. The
RRDBNet architecture is vendored in `run.py` (BSD-3-Clause original), so no
basicsr install is needed. VRAM peak comes from
`torch.cuda.max_memory_allocated()` on CUDA runs.

## Benchmark (task #1053)

Three real product images, 640px long edge in, 2560px out. Blind quality
comparison: ESRGAN vs bicubic outputs are rated under shuffled labels with
the mapping sealed until ratings are done.
