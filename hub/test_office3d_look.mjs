// The eye-tracking maths, checked against a made-up face whose line of sight is known.   node test_office3d_look.mjs
import assert from "node:assert/strict";
import { eyes, fitCal, applyCal, euro, EYE_R, CORNER, EYES, EYE_GAP } from "./office3d-look.js";

// A pinhole camera at the top of the screen films a head. Head pose: turned `yaw` to the viewer's right and tipped
// `pitch` up (rad), at `at` cm (viewer's right, up, distance). Both eyes look at `target`, cm right of / above the camera.
const VW = 1280, VH = 720, F = 1000;
function film(at, yaw, pitch, target) {
  const cy = Math.cos(-yaw), sy = Math.sin(-yaw), cp = Math.cos(-pitch), sp = Math.sin(-pitch);       // camera space: x is the viewer's left
  const R = [[cy, 0, sy], [sy * sp, cp, -cy * sp], [-sy * cp, sp, cy * cp]];                          // tip, then turn
  const t = [-at[0], at[1], -at[2]], rot = v => R.map(r => r[0] * v[0] + r[1] * v[1] + r[2] * v[2]), put = v => rot(v).map((x, i) => x + t[i]);
  const M = [R[0][0], R[1][0], R[2][0], 0, R[0][1], R[1][1], R[2][1], 0, R[0][2], R[1][2], R[2][2], 0, t[0], t[1], t[2], 1];
  const L = [], shot = (i, p) => { L[i] = { x: (VW / 2 + F * p[0] / -p[2]) / VW, y: (VH / 2 - F * p[1] / -p[2]) / VH }; };
  for (const [side, outer, inner, iris, lidUp, lidDown] of [[-1, 33, 133, 468, 159, 145], [1, 263, 362, 473, 386, 374]]) {
    const mid = [EYES[0] + side * EYE_GAP / 2, EYES[1], EYES[2]], ball = put(mid.map((x, i) => x - CORNER[i]));   // eyeball centre, in camera space
    const aim = [-target[0] - ball[0], target[1] - ball[1], -ball[2]], n = Math.hypot(...aim);
    shot(outer, put([mid[0] + side * 1.45, mid[1], mid[2]])); shot(inner, put([mid[0] - side * 1.45, mid[1], mid[2]]));
    shot(iris, ball.map((x, i) => x + EYE_R * aim[i] / n));
    shot(lidUp, put([mid[0], mid[1] + .5, mid[2]])); shot(lidDown, put([mid[0], mid[1] - .5, mid[2]]));
  }
  return [L, M];
}

// 1. the line of sight lands where the face is really looking, head straight or turned, near or far
for (const [at, yaw, pitch, target] of [
  [[0, -8, 60], 0, 0, [0, 0]], [[0, -8, 60], 0, 0, [14, -3]], [[0, -8, 60], 0, 0, [-14, -18]], [[0, -8, 60], 0, 0, [0, -20]],
  [[6, -10, 55], .25, 0, [-10, -12]], [[-5, -6, 70], -.2, .1, [12, -5]], [[3, -9, 40], .1, -.15, [5, -15]], [[0, -8, 60], .3, .1, [14, -18]],
]) {
  const e = eyes(...film(at, yaw, pitch, target), VW, VH), miss = Math.hypot(e.P[0] - target[0], e.P[1] - target[1]);
  assert.ok(miss < 1.5, `looking at ${target} from ${at}, head turned ${yaw}/${pitch}: read as ${e.P.map(v => v.toFixed(1))}, ${miss.toFixed(2)} cm off`);
  assert.ok(Math.abs(e.yaw - yaw) < .01 && Math.abs(e.pitch - pitch) < .01, `head angles read back: ${e.yaw}, ${e.pitch}`);
  assert.ok(Math.hypot(e.head[0] - at[0], e.head[1] - at[1], e.head[2] - at[2]) < .01, `head position read back: ${e.head}`);
}
assert.ok(eyes(...film([0, -8, 60], 0, 0, [0, 0]), VW, VH).open > .3, "open eyes read as open");

// 2. looking further right reads as further right; further up as further up (no mirrored axis)
const P = t => eyes(...film([0, -8, 60], 0, 0, t), VW, VH).P;
assert.ok(P([10, -10])[0] > P([0, -10])[0] + 9 && P([0, 0])[1] > P([0, -10])[1] + 9, "right is right, up is up");

// 3. calibration: nine looked-at spots with a shaky reading (±0.4 cm) recover the screen map; the reported miss is honest
let seed = 7; const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647 - .5;
const truth = f => [760 + 50 * f[0] + 2 * f[1], 60 - 49 * f[1] + 1.5 * f[0]];                          // a 50 px/cm screen, camera above its middle
const spots = [-13, 0, 13].flatMap(x => [-2, -10, -18].map(y => [x, y]));
const cal = fitCal(spots.map(([x, y]) => ({ f: [x + rnd() * .8, y + rnd() * .8, rnd() * .04, rnd() * .04], s: truth([x, y]) })));
const off = spots.map(([x, y]) => { const f = [x + 3, y - 2, 0, 0], p = applyCal(cal, f), q = truth(f); return Math.hypot(p[0] - q[0], p[1] - q[1]); });
assert.ok(Math.max(...off) < 35, `fresh spots land within 35 px of the truth: worst ${Math.max(...off).toFixed(0)}`);
assert.ok(cal.err > 5 && cal.err < 45, `the miss it reports (${cal.err.toFixed(0)} px) matches the ±0.4 cm (±20 px) shake put in`);
assert.ok(fitCal(spots.map(([x, y]) => ({ f: [x, y, 0, 0], s: truth([x, y]) }))).err < 1, "a perfectly still head and steady eyes calibrate exactly");

// 4. the smoothing filter: steady input stays put, a jump is followed within a quarter second
const f = euro(.4, 1.5); let v = 0; for (let i = 0; i < 30; i++) v = f(1 + (i % 2 ? .01 : -.01), i * 33);
assert.ok(Math.abs(v - 1) < .005, `shimmer of ±0.01 is flattened: ${v}`);
for (let i = 30; i < 38; i++) v = f(.6, i * 33);
assert.ok(Math.abs(v - .6) < .08, `a lean from 1 to 0.6 is followed in 8 frames: ${v}`);
process.stdout.write("ok look\n");
