"""Real-ESRGAN x4 upscaler, vendored (no basicsr dependency).

Loads the official RealESRGAN_x4plus weights and runs tiled inference so a
1024px input fits in 8 GB VRAM. Used by run.py --upscale.
"""
import math
import os
import urllib.request

import torch
from torch import nn
from torch.nn import functional as F

WEIGHTS_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/"
               "v0.1.0/RealESRGAN_x4plus.pth")
WEIGHTS_NAME = "RealESRGAN_x4plus.pth"


class _ResidualDenseBlock(nn.Module):
    def __init__(self, num_feat=64, num_grow_ch=32):
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


class _RRDB(nn.Module):
    def __init__(self, num_feat, num_grow_ch=32):
        super().__init__()
        self.rdb1 = _ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb2 = _ResidualDenseBlock(num_feat, num_grow_ch)
        self.rdb3 = _ResidualDenseBlock(num_feat, num_grow_ch)

    def forward(self, x):
        out = self.rdb1(x)
        out = self.rdb2(out)
        out = self.rdb3(out)
        return out * 0.2 + x


class RRDBNet(nn.Module):
    """Matches the official RealESRGAN_x4plus architecture/key names."""

    def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64,
                 num_block=23, num_grow_ch=32):
        super().__init__()
        self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
        self.body = nn.Sequential(
            *[_RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
        self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
        self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
        self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, x):
        feat = self.conv_first(x)
        body_feat = self.conv_body(self.body(feat))
        feat = feat + body_feat
        feat = self.lrelu(self.conv_up1(
            F.interpolate(feat, scale_factor=2, mode='nearest')))
        feat = self.lrelu(self.conv_up2(
            F.interpolate(feat, scale_factor=2, mode='nearest')))
        return self.conv_last(self.lrelu(self.conv_hr(feat)))


def _weights_path() -> str:
    d = os.environ.get("IMAGEGEN_CACHE",
                       os.path.expanduser("~/.cache/imagegen"))
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, WEIGHTS_NAME)
    if not os.path.isfile(p):
        print(f"[upscaler] downloading {WEIGHTS_NAME} ...", flush=True)
        urllib.request.urlretrieve(WEIGHTS_URL, p)
    return p


def load_model(device: str) -> RRDBNet:
    model = RRDBNet()
    sd = torch.load(_weights_path(), map_location="cpu", weights_only=True)
    model.load_state_dict(sd["params_ema"], strict=True)
    model.eval()
    return model.to(device)


def upscale_image(pil_image, device: str = "cuda", tile: int = 256,
                  tile_overlap: int = 16):
    """4x upscale a PIL image with tiled Real-ESRGAN. Returns (PIL, vram_mb)."""
    import numpy as np
    from PIL import Image

    model = load_model(device)
    img = np.asarray(pil_image.convert("RGB")).astype("float32") / 255.0
    h, w, _ = img.shape
    scale = 4
    out = np.zeros((h * scale, w * scale, 3), dtype="float32")

    if device == "cuda":
        torch.cuda.reset_peak_memory_stats()

    tiles_h = math.ceil(h / tile)
    tiles_w = math.ceil(w / tile)
    with torch.no_grad():
        for th in range(tiles_h):
            for tw in range(tiles_w):
                y0 = max(th * tile - tile_overlap, 0)
                y1 = min((th + 1) * tile + tile_overlap, h)
                x0 = max(tw * tile - tile_overlap, 0)
                x1 = min((tw + 1) * tile + tile_overlap, w)
                t = torch.from_numpy(
                    img[y0:y1, x0:x1].transpose(2, 0, 1)).unsqueeze(0)
                t = t.to(device)
                sr = model(t).squeeze(0).clamp(0, 1).cpu().numpy()
                sr = sr.transpose(1, 2, 0)
                # core region this tile owns, in input and output coords
                core_y0, core_x0 = th * tile, tw * tile
                oy0, ox0 = (core_y0 - y0) * scale, (core_x0 - x0) * scale
                keep_h = (min((th + 1) * tile, h) - core_y0) * scale
                keep_w = (min((tw + 1) * tile, w) - core_x0) * scale
                out[core_y0 * scale:core_y0 * scale + keep_h,
                    core_x0 * scale:core_x0 * scale + keep_w] = \
                    sr[oy0:oy0 + keep_h, ox0:ox0 + keep_w]

    vram_mb = (torch.cuda.max_memory_allocated() / 1024 ** 2
               if device == "cuda" else 0.0)
    result = Image.fromarray((out * 255.0 + 0.5).astype("uint8"))
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return result, vram_mb
