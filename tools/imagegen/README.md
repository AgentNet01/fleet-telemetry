# tools/imagegen — local image generation

Free, unlimited image generation on the fleet's own hardware (hub machine:
RTX 3070 Ti, 8 GB VRAM). Muse's image generation stays the default; switch
only where local output is as good.

## Run

```
fleet tool run imagegen "<prompt>"
python3 tools/imagegen/run.py "<prompt>" [--out DIR] [--seed N] [--steps N] [--size N]
python3 tools/imagegen/run.py --diag          # torch/CUDA/GPU diagnostics, no generation
fleet tool run imagegen --cuda-torch "<prompt>"  # replace CPU-only torch with CUDA wheel, then generate
```

Writes a PNG, prints its path. First run downloads ~4 GB of weights to the
Hugging Face cache (`~/.cache/huggingface`).

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
