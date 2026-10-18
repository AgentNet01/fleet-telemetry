#!/usr/bin/env python3
"""
banner_composite.py — production banner-text compositing tool (task #4062).

Consolidates:
  #3831  deterministic banner-text composite prototype (PIL text -> perspective
         warp onto banner quad -> paste)
  #4010  automatic banner-corner detection (k-means color segmentation ->
         quad fit -> scoring), with --quad as manual fallback
  #4017  v2 realism: luminance-multiply blend (text picks up fabric shading),
         Gaussian blur softening, optional curved-fabric warp

Usage:
    python3 banner_composite.py --scene SCENE.png --text "Happy Birthday!" \\
        --auto --out out.png
    python3 banner_composite.py --scene SCENE.png --text "Hello" \\
        --quad x1,y1 x2,y2 x3,y3 x4,y4 --out out.png
    python3 banner_composite.py --scene SCENE.png --text "Hello" --auto \\
        --blend luminance --warp curve --curve 25 --blur 0.8 --out out.png

Flags:
    --auto / --quad   corner source (mutually exclusive, one required).
                      --auto runs the #4010 detector; --quad takes four
                      "x,y" corners (TL TR BR BL).
    --blend           {luminance, flat} (default: luminance). luminance
                      multiplies the text by the scene's brightness over the
                      banner region so wrinkles/shadows show through.
    --warp            {flat, curve} (default: flat). curve applies a
                      sine-based horizontal displacement before the
                      perspective warp, for draped fabric.
    --curve           peak displacement in px for --warp curve (default 25).
    --blur            Gaussian blur radius on the text layer (default 0.8;
                      0 disables). Softens PIL edges onto photo backgrounds.
    --v1              disable all v2 effects (flat blend, no blur, no warp)
                      for comparison with the #3831 prototype behavior.
    --color           text RGB, e.g. "20,30,80" (default: dark navy).
    --debug           with --auto: write <out>-debug.png showing the
                      detected quad overlay.
"""

import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ---------------------------------------------------------------------------
# Corner detection (#4010)
# ---------------------------------------------------------------------------

def _kmeans_colors(pixels, k=5, attempts=3):
    """k-means via cv2 on an (N,3) float32 BGR sample -> (k,3) centers."""
    import cv2
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels.astype(np.float32), k, None,
                                    criteria, attempts,
                                    cv2.KMEANS_PP_CENTERS)
    return centers


def _score_quad(quad, img_w, img_h):
    """Score a candidate quad; higher is more banner-like. Returns -inf if
    it violates hard constraints."""
    pts = np.array(quad, dtype=float)
    # Edge lengths
    edges = [np.linalg.norm(pts[(i + 1) % 4] - pts[i]) for i in range(4)]
    if min(edges) < 20:
        return float("-inf")
    w_est = (edges[0] + edges[2]) / 2
    h_est = (edges[1] + edges[3]) / 2
    aspect = w_est / max(h_est, 1e-6)
    if not (1.2 <= aspect <= 6.0):
        return float("-inf")
    # Area reward (normalized)
    area = 0.5 * abs(sum(pts[i][0] * pts[(i + 1) % 4][1] -
                         pts[(i + 1) % 4][0] * pts[i][1] for i in range(4)))
    area_score = area / (img_w * img_h)
    # Penalize edge-touching corners (walls/ceilings touch the frame;
    # hanging banners don't)
    margin = 0.02
    edge_touch = sum(1 for x, y in quad
                     if x < img_w * margin or x > img_w * (1 - margin)
                     or y < img_h * margin or y > img_h * (1 - margin))
    # Rectangularity: opposite sides parallel, angles near 90 deg
    def angle(a, b, c):
        v1, v2 = a - b, c - b
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        return math.degrees(math.acos(np.clip(cosang, -1, 1)))
    angs = [angle(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4)]
    rect_score = 1.0 - sum(abs(a - 90) for a in angs) / 360.0
    return area_score * 2.0 - edge_touch * 0.5 + rect_score


def _order_corners(pts):
    """Order 4 points as TL, TR, BR, BL."""
    pts = np.array(pts, dtype=float)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]
    return [tuple(tl), tuple(tr), tuple(br), tuple(bl)]


def detect_corners(scene_path, debug_path=None):
    """Automatic banner-corner detection (#4010 method).

    Returns [(x1,y1), (x2,y2), (x3,y3), (x4,y4)] as TL, TR, BR, BL,
    or None if no plausible quad is found.
    """
    import cv2
    img = cv2.imread(scene_path)
    if img is None:
        raise RuntimeError(f"could not read scene: {scene_path}")
    h, w = img.shape[:2]
    # Candidate colors: k-means on a downsampled pixel sample + center median
    small = cv2.resize(img, (160, 120), interpolation=cv2.INTER_AREA)
    sample = small.reshape(-1, 3)
    centers = _kmeans_colors(sample, k=5)
    cy, cx = h // 2, w // 2
    center_patch = img[cy - 20:cy + 20, cx - 20:cx + 20].reshape(-1, 3)
    candidates = [tuple(map(float, c)) for c in centers]
    candidates.append(tuple(map(float, np.median(center_patch, axis=0))))

    best, best_score = None, float("-inf")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    for bgr in candidates:
        lower = np.array([max(0, c - 28) for c in bgr], dtype=np.uint8)
        upper = np.array([min(255, c + 28) for c in bgr], dtype=np.uint8)
        mask = cv2.inRange(img, lower, upper)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        cnt = max(contours, key=cv2.contourArea)
        if cv2.contourArea(cnt) < 0.02 * w * h:
            continue
        hull = cv2.convexHull(cnt)
        for eps in (0.01, 0.02, 0.04):
            peri = cv2.arcLength(hull, True)
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) != 4:
                continue
            quad = _order_corners([tuple(p[0]) for p in approx])
            score = _score_quad(quad, w, h)
            if score > best_score:
                best, best_score = quad, score
    if best is None:
        return None
    if debug_path:
        dbg = img.copy()
        pts = np.array(best, dtype=np.int32)
        cv2.polylines(dbg, [pts], True, (0, 255, 0), 3)
        for i, (x, y) in enumerate(pts):
            cv2.circle(dbg, (int(x), int(y)), 8, (0, 0, 255), -1)
            cv2.putText(dbg, str(i), (int(x) + 10, int(y) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imwrite(debug_path, dbg)
    return best


# ---------------------------------------------------------------------------
# Text rendering + v2 effects (#3831, #4017)
# ---------------------------------------------------------------------------

def find_coeffs(dst, src):
    """8-param perspective coefficients mapping src rect -> dst quad."""
    m = []
    for (x1, y1), (x2, y2) in zip(dst, src):
        m.append([x1, y1, 1, 0, 0, 0, -x2 * x1, -x2 * y1])
        m.append([0, 0, 0, x1, y1, 1, -y2 * x1, -y2 * y1])
    A = np.array(m, dtype=float)
    B = []
    for (x2, y2) in src:
        B += [x2, y2]
    B = np.array(B, dtype=float)
    coeffs, *_ = np.linalg.lstsq(A, B, rcond=None)
    return coeffs


def render_text_layer(text, size, font_path=None, color=(20, 30, 80, 255)):
    """Render text centered on a transparent layer (deterministic PIL)."""
    W, H = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lo, hi = 10, 400
    while lo < hi:
        mid = (lo + hi + 1) // 2
        try:
            f = ImageFont.truetype(font_path or "DejaVuSans-Bold.ttf", mid)
        except OSError:
            f = ImageFont.load_default()
            break
        bb = d.multiline_textbbox((0, 0), text, font=f, align="center")
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        if tw < W * 0.8 and th < H * 0.8:
            lo = mid
        else:
            hi = mid - 1
    try:
        font = ImageFont.truetype(font_path or "DejaVuSans-Bold.ttf", lo)
    except OSError:
        font = ImageFont.load_default()
    bb = d.multiline_textbbox((0, 0), text, font=font, align="center")
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.multiline_text(((W - tw) / 2 - bb[0], (H - th) / 2 - bb[1]),
                     text, font=font, fill=color, align="center")
    return layer


def apply_curve(layer, amount):
    """Horizontal cylindrical warp (sine displacement) for draped fabric."""
    if amount <= 0:
        return layer
    W, H = layer.size
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    src_px = layer.load()
    out_px = out.load()
    for y in range(H):
        dx = int(amount * math.sin(math.pi * y / H))
        for x in range(W):
            sx = x - dx
            if 0 <= sx < W:
                out_px[x, y] = src_px[sx, y]
    return out


def luminance_multiply(text_layer, scene, quad):
    """Multiply text by the scene luminance over the quad region so fabric
    wrinkles, folds and shadows show through the lettering."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    x0, y0, x1, y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    W, H = text_layer.size
    region = scene.crop((x0, y0, x1, y1)).resize((W, H), Image.BICUBIC)
    lum = region.convert("L")
    la = np.asarray(lum, dtype=float) / 255.0
    factor = 0.55 + 0.45 * la  # 0.55 floor keeps text legible in shadows
    ta = np.asarray(text_layer, dtype=float)
    ta[..., :3] *= factor[..., None]
    return Image.fromarray(ta.astype("uint8"), "RGBA")


def composite(scene_path, text, quad, out_path, blend="luminance",
              warp="flat", curve=25.0, blur=0.8,
              text_color=(20, 30, 80, 255), v1=False):
    """Full pipeline: render -> warp -> blend -> perspective -> paste."""
    scene = Image.open(scene_path).convert("RGBA")
    # Inset the quad 12% so text sits inside the banner edges (#3831)
    cx = sum(p[0] for p in quad) / 4
    cy = sum(p[1] for p in quad) / 4
    quad = [((x - cx) * 0.88 + cx, (y - cy) * 0.88 + cy) for x, y in quad]

    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    qw, qh = int(max(xs) - min(xs)), int(max(ys) - min(ys))
    if qw < 8 or qh < 8:
        raise RuntimeError(f"banner quad too small after inset: {qw}x{qh}")

    text_layer = render_text_layer(text, (qw, qh), color=text_color)

    if not v1:
        if warp == "curve":
            text_layer = apply_curve(text_layer, curve)
        if blend == "luminance":
            text_layer = luminance_multiply(text_layer, scene, quad)
        if blur > 0:
            text_layer = text_layer.filter(ImageFilter.GaussianBlur(blur))

    src_rect = [(0, 0), (qw, 0), (qw, qh), (0, qh)]
    coeffs = find_coeffs(quad, src_rect)
    warped = text_layer.transform(scene.size, Image.PERSPECTIVE, coeffs,
                                  Image.BICUBIC)
    result = Image.alpha_composite(scene, warped)
    result.convert("RGB").save(out_path)
    print(f"wrote {out_path} "
          f"(blend={blend}, warp={warp}, curve={curve}, blur={blur}, v1={v1})")


def main():
    ap = argparse.ArgumentParser(
        description="Deterministic banner-text compositing "
                    "(tasks #3831 + #4010 + #4017).")
    ap.add_argument("--scene", required=True, help="Background scene image")
    ap.add_argument("--text", required=True, help="Banner text (exact)")
    ap.add_argument("--out", required=True, help="Output PNG path")
    corners = ap.add_mutually_exclusive_group(required=True)
    corners.add_argument("--auto", action="store_true",
                         help="Detect banner corners automatically (#4010)")
    corners.add_argument("--quad", nargs=4, metavar="X,Y",
                         help='Manual corners "x1,y1 x2,y2 x3,y3 x4,y4" '
                              "(TL TR BR BL)")
    ap.add_argument("--blend", choices=["luminance", "flat"],
                    default="luminance",
                    help="Text shading mode (default: luminance)")
    ap.add_argument("--warp", choices=["flat", "curve"], default="flat",
                    help="Fabric warp mode (default: flat)")
    ap.add_argument("--curve", type=float, default=25.0,
                    help="Peak px displacement for --warp curve (default: 25)")
    ap.add_argument("--blur", type=float, default=0.8,
                    help="Gaussian blur radius on text (default: 0.8)")
    ap.add_argument("--v1", action="store_true",
                    help="Disable all v2 effects (#3831 behavior)")
    ap.add_argument("--color", default="20,30,80",
                    help='Text RGB, e.g. "20,30,80" (default: dark navy)')
    ap.add_argument("--debug", action="store_true",
                    help="With --auto: write <out>-debug.png with the "
                         "detected quad overlay")
    a = ap.parse_args()

    if a.auto:
        debug_path = None
        if a.debug:
            root, _ = os.path.splitext(a.out)
            debug_path = root + "-debug.png"
        quad = detect_corners(a.scene, debug_path=debug_path)
        if quad is None:
            print("ERROR: --auto found no banner quad; "
                  "re-run with --quad x1,y1 x2,y2 x3,y3 x4,y4",
                  file=sys.stderr)
            sys.exit(2)
        print("detected quad: " +
              " ".join(f"{x:.0f},{y:.0f}" for x, y in quad))
    else:
        quad = [tuple(map(float, p.split(","))) for p in a.quad]

    color = tuple(map(int, a.color.split(","))) + (255,)
    composite(a.scene, a.text, quad, a.out, blend=a.blend, warp=a.warp,
              curve=a.curve, blur=a.blur, text_color=color, v1=a.v1)


if __name__ == "__main__":
    main()
