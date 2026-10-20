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
  #5257  v4 P0: scene pre-flight validation + detector confidence score.
         --auto now collects ALL candidate quads; if the best candidate is
         weak (low absolute score) or a runner-up is nearly as good
         (ambiguous scene, e.g. multi-panel), the run exits 3 and writes a
         candidates debug image instead of silently compositing onto the
         wrong target. The winner's confidence score is always printed;
         --min-confidence lets pipelines set their own floor.

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
                      detected quad overlay (and, on pre-flight failure,
                      all candidate quads).
    --min-confidence  minimum detector confidence (winner, 0-1) required
                      to proceed with --auto (default: built-in floor).
                      Below it the scene is rejected with exit 3.

Exit codes (v4 P0, task #5257):
    0  success
    1  usage / runtime error
    2  --auto found no banner quad at all
    3  pre-flight rejection: scene is ambiguous (multiple comparable
       candidate quads) or best candidate is below the confidence floor.
       A <out>-candidates.png debug image shows every candidate + score.
"""

import argparse
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter


# ---------------------------------------------------------------------------
# Corner detection (#4010) + v4 P0 pre-flight validation (#5257)
# ---------------------------------------------------------------------------

# Pre-flight thresholds (#5257). A scene is ambiguous when a second *distinct*
# candidate (IoU < IOU_DISTINCT with the winner) scores within
# AMBIGUITY_MARGIN of the winner. The winner's confidence must also clear
# the floor (DEFAULT_MIN_CONFIDENCE, overridable via --min-confidence).
# Thresholds calibrated on the 5 #4010 test scenes; see DEPLOYMENT-5257 notes.
AMBIGUITY_MARGIN = 0.15
DEFAULT_MIN_CONFIDENCE = 0.78
IOU_DISTINCT = 0.5  # IoU above this: two quads are the same region


def _kmeans_colors(pixels, k=5, attempts=3):
    """k-means via cv2 on an (N,3) float32 BGR sample -> (k,3) centers."""
    import cv2
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, centers = cv2.kmeans(pixels.astype(np.float32), k, None,
                                    criteria, attempts,
                                    cv2.KMEANS_PP_CENTERS)
    return centers


def _quad_metrics(quad):
    """(aspect, rectangularity) of a 4-point quad. aspect = mean top/bottom
    edge over mean left/right edge; rectangularity = 1 - mean |angle-90|/90."""
    pts = np.array(quad, dtype=float)
    edges = [np.linalg.norm(pts[(i + 1) % 4] - pts[i]) for i in range(4)]
    w_est = (edges[0] + edges[2]) / 2
    h_est = (edges[1] + edges[3]) / 2
    aspect = w_est / max(h_est, 1e-6)

    def angle(a, b, c):
        v1, v2 = a - b, c - b
        cosang = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        return math.degrees(math.acos(np.clip(cosang, -1, 1)))
    angs = [angle(pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]) for i in range(4)]
    rect = 1.0 - sum(abs(a - 90) for a in angs) / 360.0
    return aspect, rect


def _quad_iou(q1, q2, h, w):
    """Intersection-over-union of two quads on an h×w canvas."""
    import cv2
    m1 = np.zeros((h, w), np.uint8)
    m2 = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m1, [np.array(q1, dtype=np.int32)], 1)
    cv2.fillPoly(m2, [np.array(q2, dtype=np.int32)], 1)
    inter = np.logical_and(m1 > 0, m2 > 0).sum()
    union = np.logical_or(m1 > 0, m2 > 0).sum()
    return inter / max(union, 1)


def _fill_ratio(mask, quad, h, w):
    """Fraction of the quad's area covered by its own color mask (#5257).
    Real banners are solid: fill near 1. Loose fits (blobs, drapes) score low."""
    import cv2
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [np.array(quad, dtype=np.int32)], 1)
    inside = np.logical_and(mask > 0, m > 0).sum()
    return inside / max(m.sum(), 1)


def _confidence(aspect, fill, rect):
    """Detector confidence 0..1 for a candidate quad (#5257, V4-2).

    Combines three independent signals:
      aspect: full credit for wide banners (>= 1.5), linear ramp from the
              1.2 scoring floor (drapes/blobs tend to sit near 1.2-1.3)
      fill:   color-mask coverage of the quad (solid banners ~1.0)
      rect:   corner angles near 90 deg
    Calibrated so #4010 backyard (0.99) and garden (0.91) pass the 0.75
    floor while dining drape (0.58) and living junk quads (~0.70) fail.
    """
    aspect_s = min(max((aspect - 1.2) / 0.3, 0.0), 1.0)
    return 0.20 * aspect_s + 0.35 * fill + 0.45 * rect


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


class Candidate:
    """One detected quad candidate (#5257)."""
    __slots__ = ("quad", "score", "color", "aspect", "fill", "rect", "conf")

    def __init__(self, quad, score, color, aspect, fill, rect, conf):
        self.quad = quad
        self.score = score
        self.color = color
        self.aspect = aspect
        self.fill = fill
        self.rect = rect
        self.conf = conf


class NearMiss:
    """A 4-point fit that violated the detector's hard constraints (#5257)."""
    __slots__ = ("quad", "reason")

    def __init__(self, quad, reason):
        self.quad = quad
        self.reason = reason


def detect_candidates(scene_path):
    """Automatic banner-corner detection (#4010 method), all candidates.

    Returns (valid, near_miss):
      valid     list of Candidate, sorted by score descending, near-duplicate
                regions removed (IoU >= IOU_DISTINCT; highest score kept)
      near_miss list of NearMiss: 4-point fits rejected by the hard scoring
                constraints (kept so pre-flight can show *why* a scene with
                visible banner-like regions still failed — task #5257)
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

    valid = []    # Candidate: best valid-eps fit per candidate color
    near_miss = []  # NearMiss: best rejected fit per candidate color
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
        best_quad, best_score = None, float("-inf")
        rej_quad, rej_reason = None, ""
        for eps in (0.01, 0.02, 0.04):
            peri = cv2.arcLength(hull, True)
            approx = cv2.approxPolyDP(hull, eps * peri, True)
            if len(approx) != 4:
                continue
            quad = _order_corners([tuple(p[0]) for p in approx])
            aspect, rect = _quad_metrics(quad)
            score = _score_quad(quad, w, h)
            if score > float("-inf"):
                if score > best_score:
                    fill = _fill_ratio(mask, quad, h, w)
                    best_quad, best_score = quad, score
                    best_meta = (bgr, aspect, fill, rect,
                                 _confidence(aspect, fill, rect))
            else:
                rej_quad = quad
                if aspect < 1.2 or aspect > 6.0:
                    rej_reason = f"aspect {aspect:.2f} outside 1.2-6.0"
                else:
                    rej_reason = "edge too short (<20px)"
        if best_quad is not None:
            bgr, aspect, fill, rect, conf = best_meta
            valid.append(Candidate(best_quad, best_score, bgr, aspect, fill,
                                   rect, conf))
        elif rej_quad is not None:
            near_miss.append(NearMiss(rej_quad, rej_reason))

    # Dedupe: different colors can yield the same region. Quads with
    # IoU >= IOU_DISTINCT are the same physical region; keep the best.
    valid.sort(key=lambda c: c.score, reverse=True)
    deduped = []
    for c in valid:
        if any(_quad_iou(c.quad, d.quad, h, w) >= IOU_DISTINCT
               for d in deduped):
            continue
        deduped.append(c)
    return deduped, near_miss


def write_candidates_debug(scene_path, candidates, near_misses, debug_path):
    """Draw every candidate quad on the scene (#5257): winner green with its
    confidence, runners-up yellow, rejected near-misses orange."""
    import cv2
    img = cv2.imread(scene_path)
    for i, c in enumerate(candidates):
        pts = np.array(c.quad, dtype=np.int32)
        color = (0, 255, 0) if i == 0 else (0, 255, 255)
        cv2.polylines(img, [pts], True, color, 3)
        x, y = int(pts[0][0]), int(pts[0][1])
        cv2.putText(img, f"#{i} conf={c.conf:.2f}", (x, max(0, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    for nm in near_misses:
        pts = np.array(nm.quad, dtype=np.int32)
        cv2.polylines(img, [pts], True, (0, 165, 255), 2)
        x, y = int(pts[0][0]), int(pts[0][1])
        cv2.putText(img, f"nm: {nm.reason}", (x, max(0, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
    cv2.imwrite(debug_path, img)


def detect_corners(scene_path, debug_path=None):
    """Automatic banner-corner detection (#4010 method).

    Returns [(x1,y1), (x2,y2), (x3,y3), (x4,y4)] as TL, TR, BR, BL,
    or None if no plausible quad is found. (Unchanged v3 contract.)
    """
    cands, _nm = detect_candidates(scene_path)
    if not cands:
        return None
    if debug_path:
        write_candidates_debug(scene_path, cands, [], debug_path)
    return cands[0].quad


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


# ---------------------------------------------------------------------------
# Batch mode (v4 P1, task #5538): detector-gated run over a scene set
# ---------------------------------------------------------------------------

IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def preflight_decision(cands, near_miss, floor):
    """The v4 P0 gate as a pure decision (#5538, shared by main + batch).

    Returns (accept: bool, reason: str). Mirrors main()'s exit-2/exit-3
    logic exactly: no quad at all, near-miss only, ambiguous runner-up,
    or winner below the confidence floor are all rejects.
    """
    if not cands and not near_miss:
        return False, "no banner quad found"
    if not cands:
        return False, (f"no single banner-like quad "
                       f"({len(near_miss)} near-miss fit(s) rejected by "
                       f"scoring constraints)")
    winner = cands[0]
    if len(cands) > 1:
        margin = winner.score - cands[1].score
        if margin < AMBIGUITY_MARGIN:
            return False, (f"ambiguous scene: distinct runner-up within "
                           f"{margin:.3f} (margin floor {AMBIGUITY_MARGIN})")
    if winner.conf < floor:
        return False, f"low confidence: {winner.conf:.3f} below floor {floor}"
    return True, "accepted"


def run_batch(scene_dir, text, out_dir, floor, blend="luminance",
              warp="flat", curve=25.0, blur=0.8,
              text_color=(20, 30, 80, 255)):
    """Detector-gated batch composite over every scene in scene_dir.

    Each scene is pre-flighted with the calibrated gate: accepted scenes
    are composited into out_dir/<stem>-composite.png; rejected scenes are
    skipped (a <stem>-candidates.png debug image is written instead).
    Every decision is logged as one JSON line in out_dir/decisions.jsonl:
    {scene, decision, confidence, margin, reason, output}. Returns the
    summary dict {total, accepted, rejected, reject_rate}.
    """
    import json
    os.makedirs(out_dir, exist_ok=True)
    scenes = sorted(f for f in os.listdir(scene_dir)
                    if f.lower().endswith(IMG_EXTS))
    log_path = os.path.join(out_dir, "decisions.jsonl")
    accepted = rejected = 0
    with open(log_path, "w") as log:
        for name in scenes:
            scene_path = os.path.join(scene_dir, name)
            stem = os.path.splitext(name)[0]
            cands, near_miss = detect_candidates(scene_path)
            winner = cands[0] if cands else None
            margin = (winner.score - cands[1].score
                      if len(cands) > 1 else None)
            ok, reason = preflight_decision(cands, near_miss, floor)
            entry = {"scene": name,
                     "decision": "accept" if ok else "reject",
                     "confidence": (round(winner.conf, 3)
                                    if winner else None),
                     "margin": (round(margin, 3)
                                if margin is not None else None),
                     "reason": reason,
                     "output": None}
            if ok:
                out_path = os.path.join(out_dir, stem + "-composite.png")
                composite(scene_path, text, winner.quad, out_path,
                          blend=blend, warp=warp, curve=curve, blur=blur,
                          text_color=text_color)
                entry["output"] = os.path.basename(out_path)
                accepted += 1
            else:
                write_candidates_debug(
                    scene_path, cands, near_miss,
                    os.path.join(out_dir, stem + "-candidates.png"))
                rejected += 1
            log.write(json.dumps(entry) + "\n")
            print(f"{entry['decision'].upper():6} {name}: {reason}"
                  + (f" (conf={entry['confidence']})" if winner else ""))
    total = accepted + rejected
    summary = {"total": total, "accepted": accepted, "rejected": rejected,
               "reject_rate": (rejected / total if total else 0.0)}
    print(f"batch summary: {total} scene(s), {accepted} accepted, "
          f"{rejected} rejected, reject rate "
          f"{summary['reject_rate']:.1%} (floor {floor}); "
          f"decisions logged to {log_path}")
    return summary


def main():
    ap = argparse.ArgumentParser(
        description="Deterministic banner-text compositing "
                    "(tasks #3831 + #4010 + #4017).")
    ap.add_argument("--scene", help="Background scene image")
    ap.add_argument("--text", required=True, help="Banner text (exact)")
    ap.add_argument("--out",
                    help="Output PNG path (batch mode: output directory)")
    ap.add_argument("--batch", metavar="DIR",
                    help="Batch mode (v4 P1, #5538): run the detector "
                         "gate over every scene in DIR, composite the "
                         "accepted ones into --out (a directory), log "
                         "every accept/reject to <out>/decisions.jsonl "
                         "and print the reject rate")
    corners = ap.add_mutually_exclusive_group(required=False)
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
    ap.add_argument("--min-confidence", type=float, default=None,
                    help="Minimum detector confidence (winner, 0-1) to "
                         "proceed with --auto. Below it the scene is "
                         f"rejected with exit 3 (default floor: "
                         f"{DEFAULT_MIN_CONFIDENCE})")
    a = ap.parse_args()

    color = tuple(map(int, a.color.split(","))) + (255,)
    floor = (DEFAULT_MIN_CONFIDENCE if a.min_confidence is None
             else a.min_confidence)

    if a.batch:
        if not a.out:
            ap.error("--batch needs --out DIR (output directory)")
        run_batch(a.batch, a.text, a.out, floor, blend=a.blend,
                  warp=a.warp, curve=a.curve, blur=0 if a.v1 else a.blur,
                  text_color=color)
        return
    if not a.scene or not a.out:
        ap.error("--scene and --out are required (or use --batch DIR)")
    if not a.auto and not a.quad:
        ap.error("one of --auto or --quad is required")

    if a.auto:
        root, _ = os.path.splitext(a.out)
        cands, near_miss = detect_candidates(a.scene)
        if not cands and not near_miss:
            print("ERROR: --auto found no banner quad; "
                  "re-run with --quad x1,y1 x2,y2 x3,y3 x4,y4",
                  file=sys.stderr)
            sys.exit(2)
        floor = (DEFAULT_MIN_CONFIDENCE if a.min_confidence is None
                 else a.min_confidence)
        cand_path = root + "-candidates.png"

        def preflight_fail(reason):
            write_candidates_debug(a.scene, cands, near_miss, cand_path)
            print(f"ERROR: pre-flight rejected scene: {reason}; "
                  f"re-run with --quad x1,y1 x2,y2 x3,y3 x4,y4 or pick "
                  f"another scene. Candidates in {cand_path}",
                  file=sys.stderr)
            sys.exit(3)

        if not cands:
            preflight_fail(f"no single banner-like quad "
                           f"({len(near_miss)} near-miss fit(s) rejected "
                           f"by scoring constraints)")
        winner = cands[0]
        runner = cands[1] if len(cands) > 1 else None
        margin = winner.score - runner.score if runner else None
        print("detected quad: " +
              " ".join(f"{x:.0f},{y:.0f}" for x, y in winner.quad))
        print(f"confidence={winner.conf:.3f} "
              f"margin={'n/a' if margin is None else f'{margin:.3f}'} "
              f"({len(cands)} candidate(s), {len(near_miss)} near-miss)")
        # V4-1 pre-flight (#5257): reject ambiguous or weak detections
        # instead of compositing onto the wrong target.
        if margin is not None and margin < AMBIGUITY_MARGIN:
            preflight_fail(f"ambiguous scene: distinct runner-up within "
                           f"{margin:.3f} (margin floor {AMBIGUITY_MARGIN})")
        elif winner.conf < floor:
            preflight_fail(f"low confidence: {winner.conf:.3f} below floor "
                           f"{floor}")
        quad = winner.quad
        if a.debug:
            write_candidates_debug(a.scene, cands, near_miss,
                                   root + "-debug.png")
    else:
        quad = [tuple(map(float, p.split(","))) for p in a.quad]

    color = tuple(map(int, a.color.split(","))) + (255,)
    composite(a.scene, a.text, quad, a.out, blend=a.blend, warp=a.warp,
              curve=a.curve, blur=a.blur, text_color=color, v1=a.v1)


if __name__ == "__main__":
    main()
