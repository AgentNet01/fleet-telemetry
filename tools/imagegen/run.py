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
DEFAULT_NEGATIVE = "blurry, low quality, watermark, signature"

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

    `--cuda-torch` (tasks #286, #333): when the installed torch has no CUDA
    support (CPU-only wheel) but NVIDIA hardware is present, force-reinstall
    the CUDA torch wheel from PyTorch's cu126 index and re-exec once. Since
    #333 this repair is automatic (the flag forces it); no-op when torch
    already has CUDA or the machine has no NVIDIA GPU.
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
    # subprocess (not os.execv): execv mishandles executable paths with
    # spaces on Windows (e.g. C:\Program Files\...).
    r = subprocess.run([sys.executable, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(r.returncode)


def _nvidia_gpu_present():
    """True when NVIDIA driver tooling reports at least one GPU.

    Lets the tool tell "CPU-only machine" (CPU path is correct) apart from
    "GPU machine with a CPU-only torch wheel" (repair torch automatically).
    nvidia-smi ships with the NVIDIA driver on both Windows and Linux.
    """
    try:
        r = subprocess.run(["nvidia-smi", "-L"], capture_output=True, timeout=20)
        return r.returncode == 0 and b"GPU" in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_cuda_torch():
    """Use the CUDA torch wheel on GPU machines (task #333: automatic).

    The hub's imagegen was silently running on CPU because its torch was the
    CPU-only wheel (the bootstrap no-ops when torch is merely *present*, and
    #286's `--cuda-torch` flag only helped when someone remembered to pass
    it). Now the repair is automatic: when torch has no CUDA build but
    NVIDIA hardware is present, force-reinstall the CUDA wheel from PyTorch's
    cu126 index and re-exec once. No-op when torch already has CUDA, and
    no-op on CPU-only machines (nvidia-smi finds no GPU), where the CPU path
    is correct. `--cuda-torch` still forces the check;
    IMAGEGEN_NO_CUDA_REPAIR=1 disables the automatic repair.
    """
    if os.environ.get("IMAGEGEN_CUDA_TORCH_DONE") == "1":
        return
    import torch
    if torch.version.cuda is not None:
        return  # CUDA-capable torch already; nothing to do
    forced = "--cuda-torch" in sys.argv
    if not forced and os.environ.get("IMAGEGEN_NO_CUDA_REPAIR") == "1":
        print("[imagegen] CPU-only torch; automatic CUDA repair disabled", file=sys.stderr)
        return
    if not forced and not _nvidia_gpu_present():
        print("[imagegen] CPU-only torch on a machine with no NVIDIA GPU; using CPU", file=sys.stderr)
        return
    os.environ["IMAGEGEN_CUDA_TORCH_DONE"] = "1"
    print("[imagegen] NVIDIA GPU present but torch is the CPU-only wheel; "
          "force-reinstalling the CUDA torch wheel", file=sys.stderr)
    print(f"[imagegen] pip index config: IMAGEGEN_TORCH_INDEX={os.environ.get('IMAGEGEN_TORCH_INDEX')} "
          f"PIP_INDEX_URL={os.environ.get('PIP_INDEX_URL')}", file=sys.stderr)
    for attempt in (False, True):
        cmd = [sys.executable, "-m", "pip", "install", "--user", "--force-reinstall",
               "--index-url", "https://download.pytorch.org/whl/cu126", "torch"]
        if attempt:
            cmd.append("--break-system-packages")
        if subprocess.run(cmd).returncode == 0:
            break
    else:
        raise RuntimeError("pip force-reinstall of CUDA torch failed")
    r = subprocess.run([sys.executable, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(r.returncode)


def print_diagnostics():
    """One-line torch / CUDA / GPU report for the job log."""
    import site
    import torch
    print(f"torch={torch.__version__} torch_cuda={torch.version.cuda} "
          f"cuda_available={torch.cuda.is_available()} "
          f"device_count={torch.cuda.device_count()}", file=sys.stderr)
    # Where torch actually came from: a system-site CPU wheel shadows a
    # user-site CUDA reinstall (pip --user), so torch.__file__ decides
    # whether a reinstall can ever take effect.
    print(f"torch_file={torch.__file__}", file=sys.stderr)
    print(f"user_site={site.getusersitepackages()}", file=sys.stderr)
    print(f"sys_path={os.pathsep.join(sys.path)}", file=sys.stderr)
    if torch.cuda.is_available():
        try:
            print(f"gpu0={torch.cuda.get_device_name(0)}", file=sys.stderr)
        except Exception as e:
            print(f"gpu0=<unreadable: {e}>", file=sys.stderr)


def _missing(mod):
    try:
        __import__(mod)
        return False
    except ImportError:
        return True


# Aspect presets for --aspect: (width_ratio, height_ratio). Scaled so the
# long edge equals --size, then rounded to a multiple of 8 (see resolve_dims).
ASPECT_RATIOS = {"square": (1, 1), "portrait": (3, 4), "landscape": (4, 3),
                 "wide": (16, 9), "tall": (9, 16)}


def resolve_dims(size, width, height, aspect):
    """Resolve (width, height) from --size / --width / --height / --aspect.

    Returns (width, height, requested) where requested is the pre-rounding
    (width, height) so callers can warn when rounding changed the dims.
    Rules: --aspect conflicts with --width/--height; a single --width or
    --height falls back to --size for the other dimension; no flags means
    square --size x --size. Diffusers pipelines require dims divisible by
    8, so the result is rounded to the nearest multiple of 8 (min 8).
    """
    if aspect is not None and (width is not None or height is not None):
        raise ValueError("--aspect conflicts with --width/--height; pass only one")
    if aspect is not None:
        rw, rh = ASPECT_RATIOS[aspect]
        if rw >= rh:
            req_w, req_h = size, round(size * rh / rw)
        else:
            req_w, req_h = round(size * rw / rh), size
    else:
        req_w = width if width is not None else size
        req_h = height if height is not None else size
    for name, v in (("width", req_w), ("height", req_h)):
        if v <= 0:
            raise ValueError(f"{name} must be a positive integer, got {v}")
    w = max(8, round(req_w / 8) * 8)
    h = max(8, round(req_h / 8) * 8)
    return w, h, (req_w, req_h)


def slugify(prompt: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower()).strip("-")[:48]
    return slug or "image"


def main() -> int:
    ensure_deps()
    ensure_cuda_torch()
    # The runtime's NO_PROXY contains bracketed IPv6 entries (e.g. [fd8b:...])
    # that httpx cannot parse, which breaks Hugging Face downloads. Our
    # downloads go through the egress proxy anyway, so shrink NO_PROXY to
    # plain hosts before any HTTP client reads the environment.
    for _k in ("NO_PROXY", "no_proxy"):
        os.environ[_k] = "localhost,127.0.0.1"
    ap = argparse.ArgumentParser(description="Generate one image with a local diffusion model.")
    ap.add_argument("prompt", nargs="?", default="", help="Text prompt for the image")
    ap.add_argument("--diag", action="store_true",
                    help="Print torch/CUDA/GPU diagnostics and exit (no generation)")
    ap.add_argument("--cuda-torch", action="store_true",
                    help="Replace a CPU-only torch with the CUDA wheel, then generate")
    ap.add_argument("--sdxl", action="store_true",
                    help="Use the SDXL pipeline (for SDXL-class models, e.g. Lykon/dreamshaper-xl-1-0)")
    ap.add_argument("--upscale", action="store_true",
                    help="4x upscale the output with Real-ESRGAN (tiled, task #537); "
                         "saves a second -x4.png next to the original")
    ap.add_argument("--out", default=".", help="Output directory (default: current dir). "
                      "Under the hub runner, paths outside the job's output dir are "
                      "contained to it so files stay retrievable (task #333)")
    ap.add_argument("--seed", type=int, default=None, help="Random seed (default: random)")
    ap.add_argument("--steps", type=int, default=25, help="Inference steps (default: 25)")
    ap.add_argument("--size", type=int, default=512, help="Square image size in px (default: 512). "
                      "Also the fallback for the unspecified dimension with --width/--height, "
                      "and the long edge with --aspect.")
    ap.add_argument("--width", type=int, default=None,
                    help="Output width in px (default: --size). Use with --height for non-square output.")
    ap.add_argument("--height", type=int, default=None,
                    help="Output height in px (default: --size). Use with --width for non-square output.")
    ap.add_argument("--aspect", choices=sorted(ASPECT_RATIOS), default=None,
                    help="Aspect preset, scaled to --size on the long edge: "
                         "square 1:1, portrait 3:4, landscape 4:3, wide 16:9, tall 9:16. "
                         "Conflicts with --width/--height.")
    ap.add_argument("--negative", default=DEFAULT_NEGATIVE, help="Negative prompt")
    ap.add_argument("--model", default=os.environ.get("IMAGEGEN_MODEL", DEFAULT_MODEL),
                      help=f"HF model id or local path (default: {DEFAULT_MODEL})")
    args = ap.parse_args()
    try:
        width, height, requested = resolve_dims(args.size, args.width, args.height, args.aspect)
    except ValueError as e:
        ap.error(str(e))
    if (width, height) != requested:
        print(f"[imagegen] WARNING: dimensions {requested[0]}x{requested[1]} rounded "
              f"to multiple of 8: {width}x{height}", file=sys.stderr)

    import torch
    from diffusers import StableDiffusionPipeline, StableDiffusionXLPipeline
    Pipeline = StableDiffusionXLPipeline if args.sdxl else StableDiffusionPipeline

    print_diagnostics()
    if args.diag:
        return 0
    if not args.prompt:
        ap.error("prompt is required unless --diag is given")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    print(f"device={device} dtype={dtype} model={args.model}", file=sys.stderr)

    try:
        pipe = Pipeline.from_pretrained(
            args.model, dtype=dtype, safety_checker=None)
    except Exception as e:  # fall back to a single-file checkpoint in the same repo
        print(f"diffusers-format load failed ({e}); trying single-file checkpoint", file=sys.stderr)
        from huggingface_hub import list_repo_files
        files = list_repo_files(args.model, repo_type="model")
        ckpts = [f for f in files if f.endswith((".safetensors", ".ckpt")) and "pruned" in f]
        if not ckpts:
            raise RuntimeError(f"no pruned single-file checkpoint found in {args.model}") from e
        pipe = Pipeline.from_single_file(
            f"https://huggingface.co/{args.model}/resolve/main/{ckpts[0]}",
            dtype=dtype, safety_checker=None)
    pipe = pipe.to(device)
    if device == "cpu":
        pipe.enable_attention_slicing()
    if args.sdxl:
        # SDXL weights (~7 GB fp16) are tight on 8 GB VRAM; slicing keeps
        # 1024px generation inside memory at a small speed cost. VAE slicing
        # lives on the VAE object in this diffusers version, not the pipeline.
        pipe.enable_attention_slicing()
        if hasattr(pipe.vae, "enable_slicing"):
            pipe.vae.enable_slicing()

    seed = args.seed if args.seed is not None else int.from_bytes(os.urandom(4), "big")
    generator = torch.Generator(device=device).manual_seed(seed)
    t0 = time.time()
    image = pipe(args.prompt, negative_prompt=args.negative,
                 num_inference_steps=args.steps,
                 height=height, width=width,
                 generator=generator).images[0]
    elapsed = time.time() - t0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(args.prompt.encode()).hexdigest()[:8]
    name = f"imagegen-{stamp}-{slugify(args.prompt)}-{digest}-seed{seed}.png"
    # Task #333 (backslash bug): a Linux-style --out path handed to the
    # Windows hub made os.path.join produce a mixed-separator path that
    # resolved outside the job folder (e.g. C:\home\hatch\...), so the PNG
    # was "lost" -- the hub only serves files under the job's out dir.
    # Normalize the path, and under the hub runner (JOB_ID is set by
    # tools_runner) contain --out to the job's out dir so output files can
    # never be lost again. Direct local runs keep honoring --out anywhere.
    out_dir = os.path.abspath(os.path.expanduser(args.out))
    if os.environ.get("JOB_ID"):
        job_out = os.path.abspath(os.environ.get("OUT_DIR", "."))
        # normcase: case-insensitive on Windows, identity on POSIX
        same = os.path.normcase(out_dir) == os.path.normcase(job_out)
        inside = os.path.normcase(out_dir).startswith(os.path.normcase(job_out) + os.sep)
        if not same and not inside:
            print(f"[imagegen] WARNING: --out {args.out!r} is outside the job's "
                  f"output dir; writing to {job_out} instead so the file stays "
                  f"retrievable", file=sys.stderr)
            out_dir = job_out
    out_path = os.path.join(out_dir, name)
    os.makedirs(out_dir, exist_ok=True)
    image.save(out_path)
    if not os.path.isfile(out_path):
        raise RuntimeError(f"image was not written to {out_path}")
    size = os.path.getsize(out_path)
    vram = ""
    if device == "cuda":
        # Peak VRAM incl. weights + activations (task #1096: load test needs
        # per-job VRAM; max_memory_allocated is a cheap query, no timing effect).
        # Total VRAM identifies the card the job actually ran on (#1096 found
        # a 10737 MiB peak, over the 8 GB the #1050 check reported).
        vram = f" vram_mb={torch.cuda.max_memory_allocated() / 1048576:.0f}"
        vram += f" vram_total_mb={torch.cuda.get_device_properties(0).total_memory / 1048576:.0f}"
    print(f"wrote {out_path}  seed={seed} steps={args.steps} size={width}x{height} "
          f"device={device} secs={elapsed:.1f} bytes={size}{vram}")
    if args.upscale:
        # Task #537: 4x Real-ESRGAN upscale (vendored, tiled for 8GB VRAM).
        # Weights download on first use; runs on the generation device.
        # The hub runner's cwd is the job out dir, so anchor the import
        # to this file's directory.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from upscaler import upscale_image
        u0 = time.time()
        up, vram_mb = upscale_image(image, device=device)
        u_elapsed = time.time() - u0
        up_name = name.replace(".png", "-x4.png")
        up_path = os.path.join(out_dir, up_name)
        up.save(up_path)
        up_size = os.path.getsize(up_path)
        uw, uh = up.size
        print(f"upscaled {up_path}  {uw}x{uh} device={device} "
              f"upscale_secs={u_elapsed:.1f} vram_mb={vram_mb:.0f} bytes={up_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
