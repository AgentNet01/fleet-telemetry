#!/usr/bin/env python3
"""Local image generation tool (fleet tool #12).

Usage (via the hub runner):
    fleet tool run imagegen "<prompt>"

Direct usage:
    python3 tools/imagegen/run.py "<prompt>" [--out DIR] [--seed N]
        [--steps N] [--size N] [--negative "..."] [--model HF_ID_OR_PATH]

Writes a PNG and prints its path. Model: DreamShaper 8 (SD 1.5, ungated),
~4 GB, fits 8 GB VRAM (fp16 on CUDA) and runs on CPU (fp32) where no GPU
exists. First run downloads the weights (~4 GB) to the Hugging Face cache.

Install (once per machine):
    pip install --user torch diffusers transformers accelerate safetensors Pillow
On a GPU machine use the CUDA torch wheel; on a CPU-only machine use the
CPU wheel (https://download.pytorch.org/whl/cpu).
"""
import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

DEFAULT_MODEL = "Lykon/dreamshaper-8"
DEFAULT_NEGATIVE = "blurry, low quality, distorted, deformed, bad anatomy, text, watermark"

DEPS = [("torch", "torch"), ("diffusers", "diffusers"),
        ("transformers", "transformers"), ("accelerate", "accelerate"),
        ("safetensors", "safetensors"), ("PIL", "Pillow"),
        ("huggingface_hub", "huggingface_hub")]


def ensure_deps():
    """pip-install any missing Python deps once, then re-exec.

    The done-when includes `pip install --user`; doing it here keeps the
    one-command contract (`fleet tool run imagegen "<prompt>"`) on machines
    that don't have the deps yet (e.g. the hub). No-op when all deps exist.
    Set IMAGEGEN_NO_BOOTSTRAP=1 to disable, or IMAGEGEN_TORCH_INDEX to a
    torch wheel index (e.g. the CPU index) instead of default PyPI.
    """
    missing = [pkg for mod, pkg in DEPS if _missing(mod)]
    if not missing:
        return
    if os.environ.get("IMAGEGEN_NO_BOOTSTRAP") == "1":
        raise RuntimeError(f"missing Python packages: {', '.join(missing)} "
                           "(bootstrap disabled via IMAGEGEN_NO_BOOTSTRAP=1)")
    if os.environ.get("IMAGEGEN_BOOTSTRAPPED") == "1":
        raise RuntimeError(f"packages still missing after install: {', '.join(missing)}")
    print(f"[imagegen] installing missing packages: {', '.join(missing)}", file=sys.stderr)
    index = os.environ.get("IMAGEGEN_TORCH_INDEX")
    for attempt in (False, True):  # retry with --break-system-packages on PEP 668 systems
        cmd = [sys.executable, "-m", "pip", "install", "--user"]
        if attempt:
            cmd.append("--break-system-packages")
        if index:
            cmd += ["--index-url", index, "torch"]
            rest = [p for p in missing if p != "torch"]
            if rest:
                r = subprocess.run(cmd + rest)
            else:
                r = subprocess.run(cmd)
        else:
            r = subprocess.run(cmd + missing)
        if r.returncode == 0:
            break
    else:
        raise RuntimeError(f"pip install failed for: {', '.join(missing)}")
    os.environ["IMAGEGEN_BOOTSTRAPPED"] = "1"
    os.execv(sys.executable, [sys.executable, os.path.abspath(__file__), *sys.argv[1:]])


def _missing(mod):
    try:
        __import__(mod)
        return False
    except ImportError:
        return True


def slugify(prompt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48]
    return slug or "image"


def main() -> int:
    ensure_deps()
    # The runtime's NO_PROXY contains bracketed IPv6 entries (e.g. [fd8b:...])
    # that httpx cannot parse, which breaks Hugging Face downloads. Our
    # downloads go through the egress proxy anyway, so shrink NO_PROXY to
    # plain hosts before any HTTP client reads the environment.
    for _k in ("NO_PROXY", "no_proxy"):
        os.environ[_k] = "localhost,127.0.0.1"
    ap = argparse.ArgumentParser(description="Generate one image with a local diffusion model.")
    ap.add_argument("prompt", help="Text prompt for the image")
    ap.add_argument("--out", default=".", help="Output directory (default: current dir)")
    ap.add_argument("--seed", type=int, default=None, help="Random seed (default: random)")
    ap.add_argument("--steps", type=int, default=25, help="Inference steps (default: 25)")
    ap.add_argument("--size", type=int, default=512, help="Square image size in px (default: 512)")
    ap.add_argument("--negative", default=DEFAULT_NEGATIVE, help="Negative prompt")
    ap.add_argument("--model", default=os.environ.get("IMAGEGEN_MODEL", DEFAULT_MODEL),
                      help=f"HF model id or local path (default: {DEFAULT_MODEL})")
    args = ap.parse_args()

    import torch
    from diffusers import StableDiffusionPipeline

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"device={device} dtype={dtype} model={args.model}", file=sys.stderr)

    try:
        pipe = StableDiffusionPipeline.from_pretrained(
            args.model, dtype=dtype, safety_checker=None)
    except Exception as e:  # fall back to a single-file checkpoint in the same repo
        print(f"diffusers-format load failed ({e}); trying single-file checkpoint", file=sys.stderr)
        from huggingface_hub import list_repo_files
        files = list_repo_files(args.model, repo_type="model")
        ckpts = [f for f in files if f.endswith((".safetensors", ".ckpt")) and "pruned" in f]
        if not ckpts:
            raise RuntimeError(f"no pruned single-file checkpoint found in {args.model}") from e
        pipe = StableDiffusionPipeline.from_single_file(
            f"https://huggingface.co/{args.model}/resolve/main/{ckpts[0]}",
            dtype=dtype, safety_checker=None)
    pipe = pipe.to(device)
    if device == "cpu":
        pipe.enable_attention_slicing()

    seed = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "big")
    generator = torch.Generator(device=device).manual_seed(seed)
    t0 = time.time()
    image = pipe(args.prompt, negative_prompt=args.negative,
                 num_inference_steps=args.steps,
                 height=args.size, width=args.size,
                 generator=generator).images[0]
    elapsed = time.time() - t0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(args.prompt.encode()).hexdigest()[:8]
    name = f"imagegen-{stamp}-{slugify(args.prompt)}-{digest}-seed{seed}.png"
    out_path = os.path.join(args.out, name)
    os.makedirs(args.out, exist_ok=True)
    image.save(out_path)
    print(f"wrote {out_path}  seed={seed} steps={args.steps} size={args.size} "
          f"device={device} secs={elapsed:.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
