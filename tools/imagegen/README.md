# tools/imagegen — local image generation

Free, unlimited image generation on the fleet's own hardware (hub machine:
RTX 3070 Ti, 8 GB VRAM). Muse's image generation stays the default; switch
only where local output is as good.

## Run

```
fleet tool run imagegen "<prompt>"
python3 tools/imagegen/run.py "<prompt>" [--out DIR] [--seed N] [--steps N] [--size N]
    [--width N] [--height N] [--aspect square|portrait|landscape|wide|tall]
python3 tools/imagegen/run.py --diag          # torch/CUDA/GPU diagnostics, no generation
fleet tool run imagegen --cuda-torch "<prompt>"  # force the CUDA-torch repair check
```

Writes a PNG, prints its path. First run downloads ~4 GB of weights to the
Hugging Face cache (`~/.cache/huggingface`).

## GPU (task #333)

The tool uses the hub's RTX 3070 Ti via CUDA automatically. If torch is the
CPU-only wheel while NVIDIA hardware is present, the tool force-reinstalls
the CUDA torch wheel from PyPI and re-execs once (no flag needed;
`--cuda-torch` forces the check, `IMAGEGEN_NO_CUDA_REPAIR=1` disables it).
CPU-only machines keep using the CPU path. `--diag` prints the
torch/CUDA/GPU state without generating.

## Output paths (task #333)

Under the hub runner, `--out` is contained to the job's output dir: a
foreign absolute path (e.g. a Linux path handed to the Windows hub, which
`os.path.join` used to turn into a stray `C:\home\...` location outside the
job folder, "losing" the file) now prints a warning and the PNG is written
to the job dir so it stays retrievable. Direct local runs still honor
`--out` anywhere.

## Install (once per machine)

```
pip install --user torch diffusers transformers accelerate safetensors Pillow
```

GPU machine: CUDA torch wheel. CPU-only machine: CPU wheel
(`--index-url https://download.pytorch.org/whl/cpu`).

You can skip this: `run.py` bootstraps — on first run it `pip install
--user`s any missing deps itself and re-execs (disable with
`IMAGEGEN_NO_BOOTSTRAP=1`; point torch at another wheel index with
`IMAGEGEN_TORCH_INDEX`, e.g. the CPU index).

## Model

`Lykon/dreamshaper-8` — SD 1.5 fine-tune, ungated (no HF token needed),
~4 GB, fp16 on CUDA / fp32 on CPU. Chosen because it is general-purpose
(illustration + photo), fits 8 GB VRAM, and runs on CPU-only boxes for
testing. Swap with `--model` / `IMAGEGEN_MODEL` (any SD 1.5 diffusers
checkpoint; gated checkpoints need `huggingface-cli login`).

## Comparison (task #250)

See `comparison-250/` — 3 real listings' Muse-made images side by side with
local generations from the same briefs, plus the verdict.

## GPU fix (task #286, 2026-10-14)

The hub was generating on CPU (~254 s for a 512px/25-step image) because its
torch was the CPU-only wheel. Two reinstall attempts failed: PyPI's torch
is CPU-only, so reinstalling from PyPI just reinstalled the CPU wheel.
`--cuda-torch` now reinstalls from PyTorch's CUDA index
(`--index-url https://download.pytorch.org/whl/cu126`), which hosts the
CUDA wheel for the hub's Python 3.13. Result (job 1791984024624):
**device=cuda, 512px/25 steps in 4.3 s** — ~59x faster than CPU.
