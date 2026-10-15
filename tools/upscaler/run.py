#!/usr/bin/env python3
"""Upscale images with Real-ESRGAN x4plus (fleet tool).

Usage (via the hub runner):
    fleet tool run upscaler --input <image-url> [--input <image-url> ...]

Direct usage:
    python3 tools/upscaler/run.py --input <url-or-path> [--input ...]
        [--out DIR] [--scale 4] [--prep-long-edge 640] [--baseline]

Downloads each input, upscales it 4x with Real-ESRGAN x4plus, and writes:
  <name>_esrgan.png   the upscaled image
  <name>_bicubic.png  a bicubic 4x baseline (with --baseline)
  report.json         per-image seconds, VRAM peak (CUDA), sizes, model

The RRDBNet architecture below is vendored from Real-ESRGAN
(https://github.com/xinntao/Real-ESRGAN, BSD-3-Clause) so the tool needs
only torch + Pillow + numpy -- no basicsr install. Weights are the official
RealESRGAN_x4plus.pth release (~64 MB).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

WEIGHTS_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/"
               "v0.1.0/RealESRGAN_x4plus.pth")
DEPS = [("torch", "torch"), ("PIL", "Pillow"), ("numpy", "numpy")]


def ensure_deps():
    missing = [pkg for mod, pkg in DEPS if _missing(mod)]
    if not missing:
        return
    if os.environ.get("UPSCALER_NO_BOOTSTRAP") == "1":
        raise RuntimeError(f"missing Python packages: {', '.join(missing)}")
    if os.environ.get("UPSCALER_BOOTSTRAPPED") == "1":
        raise RuntimeError(f"packages still missing after install: {', '.join(missing)}")
    print(f"[upscaler] installing missing packages: {', '.join(missing)}", file=sys.stderr)
    cmd = [sys.executable, "-m", "pip", "install", "--user"] + missing
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"pip install failed for: {', '.join(missing)}")
    os.environ["UPSCALER_BOOTSTRAPPED"] = "1"
    r = subprocess.run([sys.executable, os.path.abspath(__file__), *sys.argv[1:]])
    sys.exit(r.returncode)


def _missing(mod):
    try:
        __import__(mod)
        return False
    except ImportError:
        return True


# --- RRDBNet (Real-ESRGAN x4plus), vendored; key names match the .pth ---

def _rrdb_block():
    import torch
    import torch.nn as nn

    class ResidualDenseBlock_5C(nn.Module):
        def __init__(self, num_feat, num_grow_ch=32):
            super().__init__()
            self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
            self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat((x, x1), 1)))
            x3 = self.lrelu(self.conv3(torch.cat((x, x1, x2), 1)))
            x4 = self.lrelu(self.conv4(torch.cat((x, x1, x2, x3), 1)))
            x5 = self.conv5(torch.cat((x, x1, x2, x3, x4), 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, num_feat, num_grow_ch=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock_5C(num_feat, num_grow_ch)
            self.rdb2 = ResidualDenseBlock_5C(num_feat, num_grow_ch)
            self.rdb3 = ResidualDenseBlock_5C(num_feat, num_grow_ch)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    return RRDB


def build_rrdbnet(num_feat=64, num_block=23, num_grow_ch=32, scale=4):
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    RRDB = _rrdb_block()

    class RRDBNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.conv_first = nn.Conv2d(3, num_feat, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, 3, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            feat = self.conv_first(x)
            body_feat = self.conv_body(self.body(feat))
            feat = feat + body_feat
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            out = self.conv_last(self.lrelu(self.conv_hr(feat)))
            return out

    return RRDBNet()


def fetch(url_or_path, dest):
    if os.path.exists(url_or_path):
        with open(url_or_path, "rb") as f:
            data = f.read()
    else:
        req = urllib.request.Request(url_or_path, headers={"User-Agent": "fleet-upscaler/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def main() -> int:
    ensure_deps()
    for _k in ("NO_PROXY", "no_proxy"):
        os.environ[_k] = "localhost,127.0.0.1"
    ap = argparse.ArgumentParser(description="Upscale images 4x with Real-ESRGAN x4plus.")
    ap.add_argument("--input", action="append", required=True,
                    help="Input image URL or local path (repeatable)")
    ap.add_argument("--out", default=".", help="Output directory (default: current dir)")
    ap.add_argument("--scale", type=int, default=4, choices=[4],
                    help="Upscale factor (x4plus weights only support 4)")
    ap.add_argument("--prep-long-edge", type=int, default=640,
                    help="Resize inputs so the long edge is this many px (0 = keep native size)")
    ap.add_argument("--baseline", action="store_true",
                    help="Also emit a bicubic 4x baseline per image")
    ap.add_argument("--weights-url", default=WEIGHTS_URL, help="RealESRGAN_x4plus.pth URL")
    args = ap.parse_args()

    import numpy as np
    import torch
    from PIL import Image

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"device={device} torch={torch.__version__}", file=sys.stderr)
    os.makedirs(args.out, exist_ok=True)

    t_load0 = time.time()
    weights_path = os.path.join(tempfile.gettempdir(), "RealESRGAN_x4plus.pth")
    if not os.path.exists(weights_path) or os.path.getsize(weights_path) < 10_000_000:
        print(f"downloading weights {args.weights_url}", file=sys.stderr)
        fetch(args.weights_url, weights_path)
    model = build_rrdbnet()
    ckpt = torch.load(weights_path, map_location="cpu", weights_only=True)
    # Official release files wrap the weights: {'params_ema': {...}}
    if isinstance(ckpt, dict) and "params_ema" in ckpt:
        state = ckpt["params_ema"]
    elif isinstance(ckpt, dict) and "params-ema" in ckpt:
        state = ckpt["params-ema"]
    elif isinstance(ckpt, dict) and "params" in ckpt:
        state = ckpt["params"]
    else:
        state = ckpt
    missing_keys, unexpected = model.load_state_dict(state, strict=False)
    if missing_keys or unexpected:
        raise RuntimeError(f"state-dict mismatch: missing={missing_keys} unexpected={unexpected}")
    model.eval()
    if device == "cuda":
        model = model.half().to(device)
    load_secs = time.time() - t_load0
    print(f"model loaded in {load_secs:.1f}s", file=sys.stderr)

    results = []
    for i, src in enumerate(args.input):
        raw = os.path.join(args.out, f"_in{i}.bin")
        fetch(src, raw)
        img = Image.open(raw).convert("RGB")
        if args.prep_long_edge and max(img.size) > args.prep_long_edge:
            scale = args.prep_long_edge / max(img.size)
            img = img.resize((round(img.size[0] * scale), round(img.size[1] * scale)), Image.LANCZOS)
        w, h = img.size
        name = f"img{i + 1}"
        arr = np.asarray(img).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        if device == "cuda":
            tensor = tensor.half().to(device)
            torch.cuda.reset_peak_memory_stats()
        t0 = time.time()
        with torch.no_grad():
            out = model(tensor)
        esrgan_secs = time.time() - t0
        vram_mb = (torch.cuda.max_memory_allocated() / 1e6) if device == "cuda" else None
        out_img = out.detach().float().clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        Image.fromarray((out_img * 255.0).round().astype(np.uint8)).save(
            os.path.join(args.out, f"{name}_esrgan.png"))
        bicubic_secs = None
        if args.baseline:
            t1 = time.time()
            img.resize((w * args.scale, h * args.scale), Image.BICUBIC).save(
                os.path.join(args.out, f"{name}_bicubic.png"))
            bicubic_secs = time.time() - t1
        rec = {"name": name, "input": src, "input_px": [w, h],
               "output_px": [w * args.scale, h * args.scale],
               "esrgan_secs": round(esrgan_secs, 2),
               "bicubic_secs": round(bicubic_secs, 3) if bicubic_secs is not None else None,
               "vram_peak_mb": round(vram_mb, 1) if vram_mb is not None else None,
               "device": device}
        results.append(rec)
        print(f"RESULT {name} {w}x{h} -> {w * args.scale}x{h * args.scale} "
              f"esrgan={esrgan_secs:.2f}s bicubic={bicubic_secs} vram_mb={rec['vram_peak_mb']}",
              flush=True)

    report = {"tool": "upscaler", "model": "RealESRGAN_x4plus", "scale": args.scale,
              "device": device, "torch": torch.__version__,
              "model_load_secs": round(load_secs, 1),
              "stamp_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
              "images": results}
    with open(os.path.join(args.out, "report.json"), "w") as f:
        json.dump(report, f, indent=2)
    print(f"wrote report.json with {len(results)} images")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
