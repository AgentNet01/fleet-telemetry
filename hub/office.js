// office.js — Foundlings HQ, the hub's Overview tab.
// Where an agent is and what it's doing at work comes from api/board and is always true (desk = its task,
// review = checking, booth = answering, red "!" = not answering). Idle agents live their lives: that is ambience.
// Uses dashboard.html's globals: $, esc, label, seatsOf, showAgent, board.
(() => {
"use strict";
const Q = new URLSearchParams(location.search);
const SPEED = +Q.get("officeSpeed") || 1;                 // debug: run the sim faster
const HOUR = Q.has("officeHour") ? +Q.get("officeHour") : null;   // debug: pin day/night (0..1 of the hour)

// ───────────────────────────── basics ─────────────────────────────
const TW = 64, TH = 32, ZH = 32, X = 21, Y = 11.5, D2R = Math.PI / 180;
const wx = (x, y) => (x - y) * TW / 2, wy = (x, y, z = 0) => (x + y) * TH / 2 - z * ZH;
const P = (x, y, z = 0) => [wx(x, y), wy(x, y, z)];
const rnd = (a, b) => a + Math.random() * (b - a), pick = a => a[Math.floor(Math.random() * a.length)];
const clamp = (v, a, b) => Math.max(a, Math.min(b, v)), lerp = (a, b, t) => a + (b - a) * t;
const ease = t => (t = clamp(t, 0, 1)) * t * (3 - 2 * t);
const hash = s => { let h = 2166136261; for (const c of String(s)) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; };
function shade(col, f) {                                   // takes #hex or rgb(); returns a lighter (+f) or darker (-f) rgb()
  let r, g, b;
  if (col[0] === "#") { const hx = col.length === 4 ? [...col.slice(1)].map(c => c + c).join("") : col.slice(1), n = parseInt(hx, 16); r = n >> 16; g = (n >> 8) & 255; b = n & 255; }
  else [r, g, b] = col.match(/[\d.]+/g).map(Number);
  const t = f > 0 ? 255 : 0, k = Math.abs(f);
  return `rgb(${Math.round(r + (t - r) * k)},${Math.round(g + (t - g) * k)},${Math.round(b + (t - b) * k)})`;
}
const C = {
  carpet: "#e2e7ed", carpet2: "#dce2e9", board: "#d9d5e4", board2: "#d3cfdf", tile: "#efe8dc", tile2: "#e5dccd",
  plank: "#d8bf9a", review: "#e3e6ea", review2: "#dde1e6", deck: "#c79a6c", wall: "#f6f7f9", winFrame: "#dfe5ec",
  glassSky: "#cfe8f6", white: "#f5f5f2", stone: "#d9dcdf", metal: "#a5aeb7", steel: "#c8cfd6", dark: "#3b414a",
  black: "#25292f", wood: "#b9895a", oak: "#d2a878", fabric: "#6e8fb9", sage: "#8fb996", sand: "#e9c46a",
  teal: "#2a9d8f", plum: "#8d6cab", green: "#2f7d5b", pot: "#c8794f", leaf: "#5c9d6a", leaf2: "#79b884",
  rug: "#e8d3b5", rugEdge: "#c99f6e", slab: "#cfd5dc", facade: "#e7ebef", facadeWin: "#a9cbe0",
};

// ───────────────────────────── drawing primitives (world px) ─────────────────────────────
function poly(g, pts, fill, stroke, lw = 1) {
  g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.closePath();
  if (fill) { g.fillStyle = fill; g.fill(); }
  if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
}
function line(g, pts, col, lw = 1) { g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.strokeStyle = col; g.lineWidth = lw; g.stroke(); }
function face(g, pts, c0, c1) {
  const ys = pts.map(p => p[1]), gr = g.createLinearGradient(0, Math.min(...ys), 0, Math.max(...ys));
  gr.addColorStop(0, c0); gr.addColorStop(1, c1); poly(g, pts, gr);
}
// a shaded box: gradient sides (darker at the base = baked occlusion), lit top, bright near edges, dark base seam
function box(g, x, y, z, w, d, h, c, o = {}) {
  const L = [P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)];
  const R = [P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)];
  const T = [P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)];
  if (h > .015) { face(g, L, o.left || shade(c, -.03), shade(o.left || c, -.15)); face(g, R, o.right || shade(c, -.18), shade(o.right || c, -.31)); }
  poly(g, T, o.top || shade(c, .07));
  if (o.hl !== false) {
    g.lineCap = "round"; g.strokeStyle = "rgba(255,255,255,.5)"; g.lineWidth = .8; g.beginPath();
    if (o.hiF !== false) { g.moveTo(...T[3]); g.lineTo(...T[2]); }
    if (o.hiR !== false) { g.moveTo(...T[2]); g.lineTo(...T[1]); }
    g.stroke();
  }
  if (h > .015 && o.seam !== false) line(g, [L[0], L[1], R[0]], "rgba(0,0,0,.13)", .8);
  return { L, R, T };
}
// draw on a box face: f(u, v) maps face-local [0..1]x[0..1] (u along the face, v up) to world px
const onL = (x, y, z, w, d, h) => (u, v) => P(x + w * u, y + d, z + h * v);   // the +y face (front-left)
const onR = (x, y, z, w, d, h) => (u, v) => P(x + w, y + d * u, z + h * v);   // the +x face (front-right)
const onT = (x, y, z, w, d) => (u, v) => P(x + w * u, y + d * v, z);           // a top face
const quad = (f, u0, v0, u1, v1) => [f(u0, v0), f(u1, v0), f(u1, v1), f(u0, v1)];

// ───────────────────────────── the floor plan: sortable items ─────────────────────────────
// Each item has a footprint and a sort key (footprint centre x+y). Long pieces are split into ≤1-tile chunks so a
// person standing between them sorts correctly. `draw` is static (cached as a sprite); `live` is drawn every frame.
const ITEMS = [], BLOCK = [], SHADOWS = [], LIGHTS = [], OBJ = {};
function item(o) { o.pad = o.pad || 6; ITEMS.push(o); return o; }
function solid(x, y, z, w, d, h, c, o = {}) {
  const n = Math.max(1, Math.ceil(Math.max(w, d) - 1e-6)), alongX = w >= d;
  for (let i = 0; i < n; i++) {
    const cx = alongX ? x + w * i / n : x, cy = alongX ? y : y + d * i / n, cw = alongX ? w / n : w, cd = alongX ? d : d / n;
    const last = i === n - 1;
    item({ key: (o.wallY ? cy + cd / 2 + .1 : cx + cw / 2 + cy + cd / 2) + (o.bias || 0), fp: [cx, cy, cw, cd], z0: z, z1: z + h, pad: o.pad,
      draw: g => { const f = box(g, cx, cy, z, cw, cd, h, c, { ...o, hiR: alongX ? last : true, hiF: alongX ? true : last });
        if (o.after) o.after(g, cx, cy, cw, cd, f, i, n); } });
  }
  if (o.block) BLOCK.push(o.block === true ? [x, y, w, d] : o.block);
  if (o.shadow !== false && z < .5) SHADOWS.push([x, y, w, d, o.shadowA || .16]);
}
// small things sitting on another item's top: drawn just after it
const deco = (key, fp, z0, z1, draw, live) => item({ key, fp, z0, z1, draw, live });

// chairs: seat + stem, back on the side away from where the sitter faces
function chair(x, y, dir, c = C.fabric, o = {}) {
  const s = .44, z = o.z || .4;
  const bx = { NE: [x - s / 2, y + s / 2 - .06, s, .07], SW: [x - s / 2, y - s / 2 - .01, s, .07],
               NW: [x + s / 2 - .06, y - s / 2, .07, s], SE: [x - s / 2 - .01, y - s / 2, .07, s] }[dir];
  solid(x - .04, y - .04, 0, .08, .08, z, C.dark, { shadow: false, hl: false });
  solid(x - s / 2, y - s / 2, z, s, s, .07, c, { shadow: false });
  solid(bx[0], bx[1], z + .07, bx[2], bx[3], o.back || .46, shade(c, -.08), { shadow: false, bias: dir === "NE" || dir === "NW" ? .3 : -.3 });
  SHADOWS.push([x - .28, y - .28, .56, .56, .12]);
  BLOCK.push([x - .25, y - .25, .5, .5]);
}
function plantAt(x, y, s = 1, potc = C.pot) {
  const w = .34 * s, h = .32 * s;
  solid(x - w / 2, y - w / 2, 0, w, w, h, potc, { block: [x - w / 2, y - w / 2, w, w] });
  const p = { x, y, z: h, s, seed: hash(x * 13 + y), watered: -99 };
  item({ key: x + y + .01, fp: [x - w / 2, y - w / 2, w, w], z0: h, z1: h + 1.1 * s, pad: 26 * s, live: (g, T) => drawLeaves(g, p, T) });
  (OBJ.plants = OBJ.plants || []).push(p);
  return p;
}
function drawLeaves(g, p, T) {
  const [bx, by] = P(p.x, p.y, p.z), sway = Math.sin(T * .9 + p.seed % 7) * 1.2 * p.s, wet = clamp(1 - (T - p.watered) / 20, 0, 1);
  const n = 7 + (p.seed % 3);
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2 + p.seed, r = (5 + (i * 7 % 5)) * p.s, up = (8 + (i * 11 % 9)) * p.s;
    const lx = bx + Math.cos(a) * r * 1.2 + sway * (up / 14), ly = by - up - Math.sin(a) * r * .5;
    g.fillStyle = i % 2 ? shade(C.leaf2, wet * .15) : shade(C.leaf, wet * .12);
    g.beginPath(); g.ellipse(lx, ly, 6 * p.s, 3.4 * p.s, a * .6, 0, 7); g.fill();
  }
  g.fillStyle = shade(C.leaf2, .12 + wet * .2); g.beginPath(); g.ellipse(bx + sway, by - 17 * p.s, 5 * p.s, 3 * p.s, 0, 0, 7); g.fill();
}
// lights; pendants have no fixture drawn (the floor is a cutaway with no ceiling), only their light at night
function lamp(x, y, z, r, col, kind = "pool") {
  LIGHTS.push({ x, y, z, r, col, kind });
}

// ── desks: two rows of five, each with chair, monitor(s), keyboard, mug spot, a little clutter
const DESKS = [];
[.9, 3.1].forEach((yy, row) => [.9, 2.55, 4.2, 5.85, 7.5].forEach((xx, col) => {
  const i = DESKS.length, two = [0, 3, 6, 9].includes(i), d = { i, x: xx, y: yy, two, busy: null, typing: false, mug: false };
  DESKS.push(d);
  solid(xx, yy, .66, 1.4, .75, .06, C.white, { block: [xx, yy, 1.4, .75], shadowA: .1 });
  solid(xx, yy + .05, 0, .05, .65, .66, C.steel, { shadow: false, hl: false });
  solid(xx + 1.35, yy + .05, 0, .05, .65, .66, C.steel, { shadow: false, hl: false });
  const k = xx + yy + 1.46;
  deco(k + .02, [xx + .35, yy + .4, .55, .16], .72, .75, g => {             // keyboard + mouse
    poly(g, quad(onT(xx + .38, yy + .42, .725, .52, .15), 0, 0, 1, 1), "#e9ecef", "rgba(0,0,0,.18)", .6);
    for (let r = 0; r < 3; r++) line(g, [P(xx + .41, yy + .46 + r * .04, .727), P(xx + .87, yy + .46 + r * .04, .727)], "rgba(0,0,0,.12)", .6);
    g.fillStyle = "#e9ecef"; const [mx, my] = P(xx + 1.04, yy + .5, .725); g.beginPath(); g.ellipse(mx, my, 2.4, 1.6, 0, 0, 7); g.fill();
  });
  if (i % 3 === 1) deco(k + .01, [xx + .08, yy + .4, .25, .2], .72, .8, g => { for (let j = 0; j < 3; j++) box(g, xx + .08, yy + .42, .72 + j * .02, .24, .18, .018, ["#fafafa", "#f3efe2", "#fff"][j], { hl: false, seam: false }); });
  if (i % 3 === 0) {                                                          // desk lamp
    deco(k + .03, [xx + 1.15, yy + .1, .15, .15], .72, 1.25, g => {
      box(g, xx + 1.16, yy + .12, .72, .12, .12, .02, C.dark, { hl: false });
      line(g, [P(xx + 1.22, yy + .18, .74), P(xx + 1.22, yy + .18, 1.12), P(xx + 1.12, yy + .3, 1.2)], C.dark, 1.2);
      const [lx, ly] = P(xx + 1.1, yy + .32, 1.17); g.fillStyle = C.dark; g.beginPath(); g.ellipse(lx, ly, 4, 2.4, -.4, 0, 7); g.fill(); });
    LIGHTS.push({ x: xx + 1.1, y: yy + .35, z: 1.1, r: 46, col: "255,214,150", kind: "desk", desk: d });
  }
  d.slot = { x: xx + .7, y: yy + 1.32, dir: "NE", pose: "sit" };
  chair(xx + .7, yy + 1.32, "NE", C.fabric);
  // monitor(s): live, so the screen shows real work
  item({ key: k, fp: [xx + .2, yy + .08, 1, .1], z0: .72, z1: 1.4, pad: 8, live: (g, T) => drawMonitors(g, d, T) });
  item({ key: k + .04, fp: [xx + 1.05, yy + .45, .1, .1], z0: .72, z1: .85, live: g => { if (d.mug) drawMugAt(g, ...P(xx + 1.15, yy + .55, .72), d.mugColor || "#fff"); } });
}));
function drawMonitors(g, d, T) {
  const scr = (x0, w, j) => {
    const x = d.x + x0, y = d.y + .1;
    box(g, x + w / 2 - .03, y + .02, .72, .06, .06, .16, C.dark, { hl: false });                       // neck
    box(g, x + w / 2 - .12, y - .02, .72, .24, .12, .015, C.dark, { hl: false });                      // foot
    const f = box(g, x, y, .86, w, .05, .42, C.black, { hl: false });
    const s = onL(x, y, .86, w, .05, .42), on = !!d.busy;
    poly(g, quad(s, .05, .08, .95, .94), on ? "#152030" : "#2b3038");
    if (on) {
      const scroll = d.typing ? (T * 1.8 + j) % 1 : 0;
      for (let r = 0; r < 7; r++) {
        const v = .86 - ((r / 7 + scroll / 7) % 1) * .74, len = .25 + ((hash(d.i * 31 + r + j * 7 + Math.floor(T * (d.typing ? 1.8 : 0) + (r < 7 - scroll * 7 ? 0 : 1))) % 60) / 100);
        line(g, [s(.1 + (r % 3) * .06, v), s(Math.min(.9, .1 + (r % 3) * .06 + len), v)], ["#5fb3e6", "#9fe0a6", "#f2cc8f", "#c4a7ff"][(r + j) % 4], 1.1);
      }
      if (d.typing && Math.floor(T * 2) % 2) line(g, [s(.5, .12), s(.56, .12)], "#fff", 1.2);
    }
  };
  if (d.two) { scr(.1, .58, 0); scr(.72, .58, 1); } else scr(.3, .8, 0);
}
function drawMugAt(g, x, y, col, fill = .7) {
  g.fillStyle = col; g.strokeStyle = "rgba(0,0,0,.35)"; g.lineWidth = .6;
  g.beginPath(); g.roundRect(x - 2, y - 5, 4, 5, 1); g.fill(); g.stroke();
  g.beginPath(); g.arc(x + 2.3, y - 2.6, 1.3, -1.4, 1.4); g.stroke();
  g.fillStyle = "#6b3e1f"; g.beginPath(); g.ellipse(x, y - 5, 1.6, .6, 0, 0, 7); g.fill();
}

// ── boardroom
solid(10.1, 1.5, .66, 3.2, 1.1, .06, C.wood, { block: [10.1, 1.5, 3.2, 1.1] });
solid(10.7, 1.9, 0, .3, .3, .66, C.dark, { shadow: false }); solid(12.4, 1.9, 0, .3, .3, .66, C.dark, { shadow: false });
const BOARD = { back: [], front: [], head: null, laptop: null };
[10.6, 11.7, 12.8].forEach(x => { chair(x, 1.05, "SW", C.plum); BOARD.back.push({ x, y: 1.05, dir: "SW", pose: "sit" });
  chair(x, 2.95, "NE", C.plum); BOARD.front.push({ x, y: 2.95, dir: "NE", pose: "sit" }); });
chair(13.62, 2.05, "NW", C.plum); BOARD.head = { x: 13.62, y: 2.05, dir: "NW", pose: "sit" };
for (const [gx, gy] of [[10.5, 1.7], [12.5, 1.7], [11.6, 2.3]]) deco(gx + gy + .9, [gx, gy, .1, .1], .72, .85, g => {
  const [x, y] = P(gx, gy, .72); g.fillStyle = "rgba(200,230,255,.7)"; g.strokeStyle = "rgba(120,150,180,.6)"; g.lineWidth = .5;
  g.beginPath(); g.roundRect(x - 1.5, y - 4, 3, 4, .6); g.fill(); g.stroke(); });
OBJ.laptop = { open: 0, glow: 0 };
item({ key: 14.2, fp: [11.45, 1.55, .5, .35], z0: .72, z1: 1, live: g => {
  const o = OBJ.laptop; box(g, 11.45, 1.6, .72, .5, .33, .02, "#9aa3ad", { hl: false });
  if (o.open > .05) { poly(g, [P(11.45, 1.62, .74), P(11.95, 1.62, .74), P(11.95, 1.62 - .08 * o.open, .74 + .3 * o.open), P(11.45, 1.62 - .08 * o.open, .74 + .3 * o.open)], "#8d96a0", "rgba(0,0,0,.25)", .6);
    const [lx, ly] = P(11.7, 1.6, .89); g.fillStyle = o.glow ? "#e8f4ff" : "#b8c0c8"; g.beginPath(); g.arc(lx, ly, 1.4, 0, 7); g.fill(); } } });
lamp(11.7, 2.05, 2.3, 120, "255,224,170", "pendant");

// ── kitchen: counter with coffee machine, sink, microwave, watering can; fridge; dining table
solid(0, 5.9, 0, .72, 4.0, .86, C.white, { block: true, wallY: true, after: (g, x, y, w, d, f) => {
  const s = onR(x, y, 0, w, d, .86);
  for (let u = .02; u < .99; u += .25) poly(g, quad(s, u + .01, .08, u + .23, .92), null, "rgba(0,0,0,.12)", .7);
  for (let u = .02; u < .99; u += .25) line(g, [s(u + .19, .5), s(u + .19, .7)], "rgba(0,0,0,.35)", 1); } });
solid(0, 5.88, .86, .8, 4.04, .05, C.stone, { shadow: false, wallY: true, bias: .01 });
OBJ.coffee = { state: "idle", t: 0, level: 0, carafe: true };
item({ key: 6.55, fp: [.1, 6.1, .52, .5], z0: .91, z1: 1.5, pad: 10, live: (g, T) => {
  const o = OBJ.coffee; box(g, .12, 6.1, .91, .48, .48, .55, C.dark);
  box(g, .12, 6.1, 1.46, .48, .48, .04, C.black, { hl: false });
  const s = onR(.12, 6.1, .91, .48, .48, .55);
  poly(g, quad(s, .15, .78, .85, .93), "#1b1f24");
  const led = o.state === "brewing" ? (Math.floor(T * 3) % 2 ? "#ffb347" : "#7a4a10") : o.state === "ready" ? "#58d68d" : "#c0392b";
  g.fillStyle = led; const [lx, ly] = s(.8, .85); g.beginPath(); g.arc(lx, ly, 1.3, 0, 7); g.fill();
  if (o.carafe) drawCarafe(g, ...P(.66, 6.42, .93), o.level, 0);
  if (o.state === "brewing") { const [sx, sy] = s(.5, .6); line(g, [[sx, sy], [sx, sy + 7]], "rgba(110,62,30,.8)", 1); }
} });
deco(8.05, [.12, 7.1, .5, .6], .91, 1.2, g => {                   // sink basin + faucet
  poly(g, quad(onT(.15, 7.12, .912, .46, .56), 0, 0, 1, 1), "#c3c9cf", "rgba(0,0,0,.2)", .7);
  poly(g, quad(onT(.19, 7.17, .912, .38, .46), 0, 0, 1, 1), "#aeb6be");
  line(g, [P(.12, 7.4, .92), P(.12, 7.4, 1.18), P(.3, 7.4, 1.22)], "#9aa3ab", 2); });
OBJ.sink = { until: 0 };
item({ key: 8.06, fp: [.2, 7.3, .2, .2], z0: .9, z1: 1.2, live: (g, T) => { if (T < OBJ.sink.until) {
  const [a, b] = P(.3, 7.4, 1.2), [c, d] = P(.3, 7.4, .92); line(g, [[a, b], [c, d]], "rgba(150,200,240,.85)", 1.4); } } });
OBJ.micro = { open: 0, run: 0, end: 0, item: null, ding: -99 };
item({ key: 8.85, fp: [.1, 8.3, .6, .72], z0: .91, z1: 1.35, pad: 12, live: (g, T) => {
  const o = OBJ.micro; box(g, .1, 8.3, .91, .58, .7, .4, C.steel);
  const s = onR(.1, 8.3, .91, .58, .7, .4), lit = o.run && T < o.end;
  poly(g, quad(s, .06, .14, .7, .86), lit ? "#ffcf6b" : "#4a5058");
  if (o.item && (lit || o.open > .5)) { const [fx, fy] = s(.38, .3); g.fillStyle = o.item === "takeout" ? "#f4f4f0" : "#f6f1e8"; g.beginPath(); g.ellipse(fx, fy, 4, 1.6, 0, 0, 7); g.fill(); }
  poly(g, quad(s, .76, .3, .94, .86), "#3a4048"); g.fillStyle = lit ? "#7dff9a" : "#2a2f35"; const [bx, by] = s(.85, .75); g.fillRect(bx - 1.5, by - 1, 3, 2);
  if (o.open > .02) {                                                        // the door swings out on its left hinge
    const a = o.open * 1.6, hx = .68, hy = 8.33, len = .46;
    const ex = hx + Math.sin(a) * len, ey = hy + Math.cos(a) * len;
    poly(g, [P(hx, hy, .95), P(ex, ey, .95), P(ex, ey, 1.27), P(hx, hy, 1.27)], C.steel, "rgba(0,0,0,.25)", .7);
  }
  if (T - o.ding < 1.2) { const [dx, dy] = s(.5, 1.6); g.font = "700 7px system-ui"; g.fillStyle = "#c0392b"; g.globalAlpha = 1 - (T - o.ding) / 1.2; g.fillText("ding!", dx - 8, dy - (T - o.ding) * 6); g.globalAlpha = 1; }
} });
OBJ.can = { held: false };
item({ key: 9.65, fp: [.2, 9.4, .3, .25], z0: .91, z1: 1.2, live: g => { if (!OBJ.can.held) drawCan(g, ...P(.38, 9.55, .91), 0); } });
OBJ.fridge = { open: 0 };
item({ key: .43 + 10.68 + .1, fp: [0, 10.1, .86, 1.15], z0: 0, z1: 2.05, pad: 14, live: (g, T) => {
  const o = OBJ.fridge; box(g, 0, 10.1, 0, .84, 1.15, 2.05, "#f0f2f4");
  const s = onR(0, 10.1, 0, .84, 1.15, 2.05);
  line(g, [s(0, .62), s(1, .62)], "rgba(0,0,0,.18)", .8);
  for (const [u, v] of [[.2, .8], [.35, .86], [.6, .75], [.75, .9]]) { g.fillStyle = ["#e76f51", "#2a9d8f", "#e9c46a", "#5aa2ff"][(u * 10 | 0) % 4]; const [mx, my] = s(u, v); g.beginPath(); g.arc(mx, my, 1.4, 0, 7); g.fill(); }
  if (o.open < .98) { line(g, [s(.9, .66), s(.9, .9)], "#9aa3ab", 1.6); line(g, [s(.9, .3), s(.9, .56)], "#9aa3ab", 1.6); }
  if (o.open > .02) {
    poly(g, quad(s, .03, .64, .97, .98), "#fdfbf2");                       // the lit inside
    for (const v of [.72, .82, .92]) line(g, [s(.05, v), s(.95, v)], "#d9dde0", .8);
    [["#e76f51", .2, .74], ["#f4f1e6", .45, .74], ["#ffd6e0", .7, .74], ["#8fb996", .3, .84], ["#e9c46a", .62, .84]].forEach(([c, u, v]) => {
      const [ix, iy] = s(u, v); g.fillStyle = c; g.fillRect(ix - 2, iy - 4, 4, 4); });
    const a = o.open * 1.5, hx = .84, hy = 10.1, len = 1.1;
    const ex = hx + Math.sin(a) * len, ey = hy + Math.cos(a) * len;
    poly(g, [P(hx, hy, .66), P(ex, ey, .66), P(ex, ey, 2.0), P(hx, hy, 2.0)], "#e8ebee", "rgba(0,0,0,.25)", .7);
  }
} });
solid(1.0, 11.05, 0, .32, .32, .5, C.dark, { block: true });                // bin
solid(2.4, 8.4, .66, 1.2, 1.2, .06, C.oak, { block: [2.4, 8.4, 1.2, 1.2] });
solid(2.92, 8.92, 0, .16, .16, .66, C.dark, { shadow: false });
deco(3.0 + 9.0 + .3, [2.8, 8.8, .4, .4], .72, .9, g => {
  const [x, y] = P(3.0, 9.0, .72); g.fillStyle = "#d9cdb8"; g.beginPath(); g.ellipse(x, y - 1, 7, 3, 0, 0, 7); g.fill();
  [["#e76f51", -3, -3], ["#f4d35e", 1, -4], ["#8fb996", 3, -2], ["#e76f51", -1, -5]].forEach(([c, dx, dy]) => { g.fillStyle = c; g.beginPath(); g.arc(x + dx, y + dy, 2.2, 0, 7); g.fill(); }); });
const DINE = [{ x: 3.0, y: 8.0, dir: "SW" }, { x: 3.0, y: 10.0, dir: "NE" }, { x: 2.0, y: 9.0, dir: "SE" }, { x: 4.0, y: 9.0, dir: "NW" }];
DINE.forEach(s => { s.pose = "sit"; chair(s.x, s.y, s.dir, C.sage); });
lamp(3.0, 9.0, 2.2, 110, "255,206,140", "pendant");

// ── lounge: L-sofa, rug, coffee table, floor lamp, bookshelf, water cooler
solid(5.7, 7.0, 0, .7, 2.6, .38, C.fabric, { block: true, after: (g, x, y, w, d) => line(g, [P(x + .05, y + d, .38), P(x + .68, y + d, .38)], "rgba(0,0,0,.15)", .8) });
solid(5.52, 6.85, 0, .18, 2.9, .82, shade(C.fabric, -.12), { block: true });
solid(5.7, 6.85, 0, .7, .15, .56, shade(C.fabric, -.06), { block: true }); solid(5.7, 9.6, 0, .7, .15, .56, shade(C.fabric, -.06), { block: true });
solid(6.4, 9.95, 0, 2.3, .65, .38, C.fabric, { block: true }); solid(6.4, 10.6, 0, 2.3, .16, .74, shade(C.fabric, -.12), { block: true, bias: .05 });
solid(8.7, 9.95, 0, .15, .81, .56, shade(C.fabric, -.06), { block: true });
for (const [px, py, c] of [[5.78, 7.2, C.sand], [5.78, 9.25, C.teal], [8.3, 10.5, C.sand]]) deco(px + py + .5, [px, py, .3, .3], .38, .7, g => box(g, px, py, .38, .28, .14, .26, c, { hl: false }));
solid(6.9, 7.7, 0, 1.0, 1.0, .3, C.oak, { block: true });
deco(7.4 + 8.2 + .6, [7.0, 7.8, .8, .8], .3, .4, g => { box(g, 7.05, 7.85, .3, .32, .24, .02, "#e76f51", { hl: false }); box(g, 7.1, 7.9, .32, .3, .22, .015, "#f6f1e8", { hl: false }); });
solid(8.85, 6.95, 0, .22, .22, .05, C.dark, { block: [8.85, 6.95, .22, .22] });
deco(8.96 + 7.06 + .1, [8.9, 7.0, .1, .1], 0, 1.8, g => { line(g, [P(8.96, 7.06, .05), P(8.96, 7.06, 1.55)], C.dark, 1.5);
  poly(g, [P(8.82, 7.06, 1.5), P(8.96, 6.92, 1.5), P(9.1, 7.06, 1.5), P(8.96, 7.2, 1.5), P(8.96, 7.06, 1.82)], "#f3e3c3", "rgba(0,0,0,.2)", .6); });
lamp(8.96, 7.06, 1.6, 120, "255,200,130", "floor");
solid(5.25, 6.2, 0, 1.4, .3, 1.5, C.wood, { block: true, after: (g, x, y, w, d) => {
  const s = onL(x, y, 0, w, d, 1.5);
  for (let r = 0; r < 4; r++) { line(g, [s(0, .04 + r * .25), s(1, .04 + r * .25)], shade(C.wood, -.3), 1);
    for (let b = 0; b < 9; b++) { const h = .13 + ((b * 7 + r * 3 + (x * 10 | 0)) % 5) * .015, u = .04 + b * .105;
      poly(g, quad(s, u, .06 + r * .25, u + .08, .06 + r * .25 + h), ["#e76f51", "#2a9d8f", "#e9c46a", "#5a7bbf", "#8d6cab", "#f4a261"][(b + r * 2) % 6]); } } } });
solid(9.62, 5.2, 0, .34, .34, .82, C.white, { block: true });
deco(9.79 + 5.37 + .3, [9.62, 5.2, .34, .34], .82, 1.25, g => { const [x, y] = P(9.79, 5.37, .82);
  g.fillStyle = "rgba(120,180,240,.75)"; g.beginPath(); g.roundRect(x - 5, y - 14, 10, 14, 4); g.fill(); g.fillStyle = "rgba(255,255,255,.5)"; g.fillRect(x - 3, y - 12, 2, 9); });

// ── review table, call booths, ping-pong
solid(10.3, 5.9, .66, 1.2, 1.0, .05, C.white, { block: [10.3, 5.9, 1.2, 1.0] });
solid(10.35, 5.95, 0, .05, .9, .66, C.steel, { shadow: false, hl: false }); solid(11.42, 5.95, 0, .05, .9, .66, C.steel, { shadow: false, hl: false });
deco(10.9 + 6.4 + .4, [10.4, 6.0, 1.0, .8], .71, .75, g => {
  for (const [px, py, c] of [[10.45, 6.05, "#fff"], [10.62, 6.12, "#f6f6f0"], [11.05, 6.5, "#fff"]]) box(g, px, py, .712, .3, .22, .006, c, { hl: false, seam: false });
  for (const [px, py, c] of [[10.95, 6.0, "#ffe27a"], [11.1, 6.05, "#ffb3c6"], [11.25, 6.0, "#9ee6c0"]]) box(g, px, py, .712, .1, .1, .006, c, { hl: false, seam: false }); });
const REVIEW = [{ x: 10.9, y: 7.25, dir: "NE" }, { x: 11.85, y: 6.4, dir: "NW" }, { x: 10.9, y: 5.55, dir: "SW" }, { x: 9.95, y: 6.4, dir: "SE" }];
REVIEW.forEach(s => { s.pose = "sit"; chair(s.x, s.y, s.dir, C.teal); });
lamp(10.9, 6.4, 2.2, 100, "255,224,170", "pendant");
const BOOTHS = [6.9, 8.2].map(by => {
  const b = { y: by, busy: false };
  solid(12.8, by, 0, 1.05, .06, 2.1, "#6b7684", { shadow: false }); solid(12.8, by + .06, 0, .06, 1.04, 2.1, "#6b7684", { shadow: false });
  solid(12.8, by, 2.1, 1.05, 1.1, .08, "#6b7684", { shadow: false, top: "#7d8896" });
  BLOCK.push([12.8, by, 1.05, .1], [12.8, by, .1, 1.1]);
  item({ key: 13.33 + by + 1.1 + .1, fp: [12.8, by + 1.08, 1.05, .02], z0: 0, z1: 2.1, live: g => {
    poly(g, [P(12.86, by + 1.1), P(13.85, by + 1.1), P(13.85, by + 1.1, 2.1), P(12.86, by + 1.1, 2.1)], "rgba(200,225,245,.30)", "rgba(255,255,255,.5)", .8);
    line(g, [P(12.9, by + 1.1, 2.13), P(13.8, by + 1.1, 2.13)], b.busy ? "#3fe08a" : "#58606a", 2); } });
  b.slot = { x: 13.35, y: by + .55, dir: "SW", pose: "stand" };
  return b;
});
solid(10.3, 9.9, .7, 1.8, .9, .05, C.green, { block: [10.3, 9.9, 1.8, .9], after: (g, x, y, w, d) => {
  line(g, [P(x, y + d / 2, .755), P(x + w, y + d / 2, .755)], "rgba(255,255,255,.7)", .7); } });
solid(10.4, 10.0, 0, .05, .7, .7, C.dark, { shadow: false, hl: false }); solid(12.0, 10.0, 0, .05, .7, .7, C.dark, { shadow: false, hl: false });
deco(11.2 + 10.35 + .4, [11.18, 9.85, .04, 1.0], .75, .9, g => poly(g, [P(11.2, 9.85, .755), P(11.2, 10.85, .755), P(11.2, 10.85, .87), P(11.2, 9.85, .87)], "rgba(255,255,255,.55)", "#ddd", .6));
const PONG = [{ x: 9.85, y: 10.35, dir: "SE", pose: "stand" }, { x: 12.55, y: 10.35, dir: "NW", pose: "stand" }];
OBJ.ball = null;
item({ key: 0, fp: [0, 0, 0, 0], z0: 0, z1: 0, dynKey: () => OBJ.ball ? OBJ.ball.x + OBJ.ball.y : -1, live: g => {
  const b = OBJ.ball; if (!b) return; const [x, y] = P(b.x, b.y, b.z), [sx, sy] = P(b.x, b.y, .755);
  g.fillStyle = "rgba(0,0,0,.18)"; g.beginPath(); g.ellipse(sx, sy, 2, 1, 0, 0, 7); g.fill();
  g.fillStyle = "#fff8e8"; g.beginPath(); g.arc(x, y, 1.7, 0, 7); g.fill(); } });

// ── plants indoors
const PLANT_SPOTS = [[9.35, .35, 1.1, { x: 9.35, y: .95, dir: "NE" }], [13.75, .3, 1.2, { x: 13.4, y: .75, dir: "NE" }],
  [9.4, 9.6, 1.2, { x: 9.4, y: 9.0, dir: "SW" }], [5.0, 5.35, 1, { x: 5.0, y: 4.85, dir: "SW" }], [14.4, .35, 1.3, null], [20.65, .4, 1.3, null], [14.4, 11.1, 1.15, null]];
const PLANTS = PLANT_SPOTS.map(([x, y, s, w]) => { const p = plantAt(x, y, s); if (w) p.slot = { ...w, pose: "stand" }; return p; });

// ── patio: two umbrella tables, loungers, heater, bar cart, smoking corner, planters
const PATIO = [];
for (const [cx, cy, uc] of [[16.8, 2.8, C.teal], [16.9, 8.3, C.sand]]) {
  solid(cx - .45, cy - .45, .66, .9, .9, .05, C.white, { block: [cx - .45, cy - .45, .9, .9] });
  solid(cx - .05, cy - .05, 0, .1, .1, .66, C.metal, { shadow: false });
  const seats = [{ x: cx, y: cy - .78, dir: "SW" }, { x: cx + .8, y: cy, dir: "NW" }, { x: cx, y: cy + .78, dir: "NE" }, { x: cx - .8, y: cy, dir: "SE" }];
  seats.forEach(s => { s.pose = "sit"; chair(s.x, s.y, s.dir, "#7a8691", { back: .4 }); });
  PATIO.push(seats);
  item({ key: cx + cy + .02, fp: [cx - .45, cy - .45, .9, .9], z0: .7, z1: 2.5, pad: 40, draw: g => {
    box(g, cx - .03, cy - .03, .71, .06, .06, 1.45, C.metal, { hl: false });
    const r = .95, z = 2.12, top = P(cx, cy, 2.42), N = 10;
    const rim = [...Array(N)].map((_, i) => { const a = i / N * Math.PI * 2; return P(cx + Math.cos(a) * r, cy + Math.sin(a) * r, z); });
    const order = [...Array(N).keys()].sort((i, j) => Math.sin((i + .5) / N * Math.PI * 2 + .79) - Math.sin((j + .5) / N * Math.PI * 2 + .79));
    for (const i of order) { const lit = Math.cos((i + .5) / N * Math.PI * 2 - 2.4); poly(g, [rim[i], rim[(i + 1) % N], top], shade(uc, lit * .18), shade(uc, -.2), .5); }
    for (let i = 0; i < N; i++) { const a = rim[i], b = rim[(i + 1) % N]; line(g, [a, [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 2.2], b], shade(uc, -.28), .9); }
  } });
}
const LOUNGERS = [4.6, 5.75].map(ly => {
  solid(18.6, ly, 0, 1.55, .6, .26, C.white, { block: true });
  solid(19.95, ly, .26, .2, .6, .32, C.white, { shadow: false });
  deco(19.4 + ly + .3 + .1, [18.7, ly + .05, 1.2, .5], .26, .3, g => poly(g, quad(onT(18.7, ly + .06, .27, 1.2, .48), 0, 0, 1, 1), ly < 5 ? C.teal : C.sand));
  return { x: 19.25, y: ly + .3, dir: "SE", pose: "lie", z: .28, lieAng: Math.atan2(TH / 2, TW / 2) };
});
solid(19.15, 7.9, 0, .2, .2, .08, C.dark, { block: [19.1, 7.85, .3, .3] });
deco(19.25 + 8.0 + .1, [19.15, 7.9, .2, .2], 0, 1.8, g => { box(g, 19.21, 7.96, .08, .08, .08, 1.45, C.dark, { hl: false });
  poly(g, [P(19.0, 8.0, 1.55), P(19.25, 7.75, 1.55), P(19.5, 8.0, 1.55), P(19.25, 8.25, 1.55), P(19.25, 8.0, 1.75)], "#4a525c"); });
lamp(19.25, 8.0, 1.45, 70, "255,120,50", "heater");
solid(14.9, 10.55, .1, .9, .45, .05, C.metal, { block: [14.9, 10.55, .9, .45] }); solid(14.9, 10.55, .62, .9, .45, .05, C.metal, { shadow: false });
deco(15.35 + 10.8 + .2, [14.95, 10.6, .8, .35], .67, 1.0, g => [[15.05, "#2a9d8f"], [15.25, "#e9c46a"], [15.45, "#e76f51"], [15.62, "#f4f1e6"]].forEach(([bx, c]) => {
  const [x, y] = P(bx, 10.75, .67); g.fillStyle = c; g.beginPath(); g.roundRect(x - 1.5, y - 8, 3, 8, 1); g.fill(); g.fillRect(x - .6, y - 11, 1.2, 3); }));
solid(20.3, 10.6, 0, .22, .22, .78, C.metal, { block: true, after: (g) => { const [x, y] = P(20.41, 10.71, .78); g.fillStyle = "#555"; g.beginPath(); g.ellipse(x, y, 4, 2, 0, 0, 7); g.fill(); } });
const SMOKE = [{ x: 19.9, y: 10.2, dir: "SE", pose: "stand" }, { x: 20.65, y: 10.05, dir: "SW", pose: "stand" }];
for (const [px, py] of [[20.45, 2.2], [20.45, 6.9], [17.6, 11.1]]) plantAt(px, py, 1.05, C.wood);

// ── railings + glass wall + door: transparent panels, sorted with people
const glassP = (x0, y0, x1, y1, h, key, frame = true) => item({ key, fp: [Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0)], z0: 0, z1: h, pad: 4, draw: g => {
  poly(g, [P(x0, y0), P(x1, y1), P(x1, y1, h), P(x0, y0, h)], "rgba(205,232,248,.24)", null);
  line(g, [P(x0, y0, h), P(x1, y1, h)], frame ? "#9aa5ae" : "rgba(255,255,255,.6)", frame ? 1.6 : .8);
  line(g, [P(x0, y0), P(x0, y0, h)], "rgba(150,165,175,.8)", 1);
  g.strokeStyle = "rgba(255,255,255,.45)"; g.lineWidth = 1.2; g.beginPath();
  const a = P(lerp(x0, x1, .2), lerp(y0, y1, .2), h * .2), b = P(lerp(x0, x1, .45), lerp(y0, y1, .45), h * .85); g.moveTo(...a); g.lineTo(...b); g.stroke(); } });
for (let x = 14; x < X - .01; x += 1) glassP(x, Y, x + 1, Y, .9, x + .5 + Y + .4);
for (let y = 0; y < Y - .01; y += 1) glassP(X, y, X, Math.min(y + 1, Y), .9, X + y + .5 + .4);
for (let x = 14; x < X - .01; x += 1) glassP(x, 0, x + 1, 0, .9, x + .5 - .4);
for (let y = 0; y < Y - .01; y += 1.15) { const y1 = Math.min(y + 1.15, Y); if (y1 <= 4.62 || y >= 6.78) glassP(14, y, 14, y1, 2.6, 14 + (y + y1) / 2 + .01); }
for (let y = 0; y < Y; y += .5) if (y < 4.6 || y > 6.75) BLOCK.push([13.9, y, .2, .5]);
deco(14 + 4.6, [13.95, 4.55, .1, .1], 0, 2.6, g => box(g, 13.95, 4.55, 0, .1, .1, 2.6, C.metal, { hl: false }));
deco(14 + 6.85, [13.95, 6.8, .1, .1], 0, 2.6, g => box(g, 13.95, 6.8, 0, .1, .1, 2.6, C.metal, { hl: false }));

// ── slots people can use (fixed spots; idle routines and work both claim them)
const SLOTS = {
  desk: DESKS.map(d => ({ ...d.slot, desk: d })), ceo: [BOARD.back[1], BOARD.back[0], BOARD.back[2], BOARD.head],
  board: [...BOARD.front, ...BOARD.back, BOARD.head], review: REVIEW, booth: BOOTHS.map(b => ({ ...b.slot, booth: b })),
  coffee: [{ x: 1.15, y: 6.35, dir: "NW", pose: "stand" }], coffeeQ: [{ x: 1.75, y: 6.9, dir: "NW", pose: "stand" }],
  sink: [{ x: 1.15, y: 7.4, dir: "NW", pose: "stand" }], micro: [{ x: 1.15, y: 8.65, dir: "NW", pose: "stand" }],
  fridge: [{ x: 1.45, y: 10.6, dir: "NW", pose: "stand" }], can: [{ x: 1.15, y: 9.55, dir: "NW", pose: "stand" }],
  bin: [{ x: 1.8, y: 11.25, dir: "NW", pose: "stand" }], counter: [{ x: 1.2, y: 7.95, dir: "SE", pose: "stand", lean: 1 }, { x: 1.2, y: 9.15, dir: "SE", pose: "stand", lean: 1 }],
  dine: DINE, sofa: [{ x: 6.05, y: 7.45 }, { x: 6.05, y: 8.3 }, { x: 6.05, y: 9.15 }].map(s => ({ ...s, dir: "SE", pose: "sit" })),
  sofa2: [{ x: 7.0, y: 10.25 }, { x: 7.95, y: 10.25 }].map(s => ({ ...s, dir: "NE", pose: "sit" })),
  nap: [{ x: 7.25, y: 10.25, dir: "NE", pose: "lie", z: .38, lieAng: Math.atan2(TH / 2, TW / 2) }],
  books: [{ x: 5.95, y: 6.85, dir: "NE", pose: "stand" }], coolerA: [{ x: 9.05, y: 5.95, dir: "SE", pose: "stand" }],
  coolerB: [{ x: 9.8, y: 5.92, dir: "NW", pose: "stand" }],
  window: [{ x: 9.85, y: .4, dir: "NE", pose: "stand" }, { x: .45, y: 5.3, dir: "NW", pose: "stand" }, { x: 13.1, y: .4, dir: "NE", pose: "stand" }],
  whiteboard: [{ x: 3.9, y: .38, dir: "NE", pose: "stand" }], pong: PONG,
  patioA: PATIO[0], patioB: PATIO[1], lounger: LOUNGERS,
  rail: [{ x: 20.62, y: 1.9, dir: "SE" }, { x: 20.62, y: 3.6, dir: "SE" }, { x: 18.5, y: 11.15, dir: "SW" }, { x: 16.1, y: 11.15, dir: "SW" }, { x: 15.2, y: .4, dir: "NE" }].map(s => ({ ...s, pose: "stand", lean: 1 })),
  smoke: SMOKE, plant: PLANTS.filter(p => p.slot).map(p => ({ ...p.slot, plant: p })),
};
for (const [g, list] of Object.entries(SLOTS)) list.forEach((s, i) => { s.group = g; s.id = g + i; s.by = null; });

// ───────────────────────────── people: a small procedural rig ─────────────────────────────
// A pose is joint angles (0° = limb hanging straight down, + swings it forward). Clips return a target pose for
// time t; the drawn pose eases toward it, so every change of action blends instead of snapping.
let NIGHT_N = 0;
const BODY = { thigh: 8.4, shin: 8.4, torso: 13.5, neck: 1.8, head: 6.1, upper: 7.2, fore: 6.4, seat: 12.6 };
const SKIN = ["#f6d5bd", "#eec3a1", "#dca37c", "#c68859", "#a86b43", "#8a5232", "#6b3d22", "#f1c9a8"];
const HAIRC = ["#2b1d14", "#4a3020", "#6e4a2a", "#a0703f", "#d9b26f", "#1f1f24", "#7a3b1f", "#b9b9be", "#3b2a4a"];
const TOPS = ["#e07a5f", "#3d85c6", "#81b29a", "#e9c46a", "#9b72cf", "#e56b9f", "#4fb0c6", "#f4a261", "#6a994e", "#c1666b", "#2a3d66", "#f2efe6"];
const PANTS = ["#2d3340", "#3b4a6b", "#4a4038", "#2a2a2e", "#55606e"];
function look(name) {                                    // every trait seeded separately from the name
  const h = k => hash(name + "|" + k);
  return { skin: SKIN[h("s") % SKIN.length], hair: HAIRC[h("h") % HAIRC.length], hairStyle: ["crop", "side", "bun", "pony", "afro", "long", "buzz", "curly"][h("y") % 8],
    top: TOPS[h("t") % TOPS.length], top2: TOPS[h("u") % TOPS.length], cut: ["tee", "hoodie", "jacket", "shirt", "sweater"][h("c") % 5],
    pants: PANTS[h("p") % PANTS.length], glasses: h("g") % 10 < 3, phones: h("f") % 10 < 2, beanie: h("b") % 12 === 0,
    scale: 1.1 + (h("z") % 12) / 100, smoker: h("k") % 10 < 4, mug: ["#ffffff", "#e76f51", "#2a9d8f", "#e9c46a", "#5aa2ff", "#2d3340"][h("m") % 6] };
}
const STAND = { sit: 0, lie: 0, lean: 0, bob: 0, ht: 0, hy: 0, aL: [6, 14], aR: [-4, 12], lL: [3, 0], lR: [-3, 0], mouth: 0, eyes: 1, tilt: 0 };
const SIT = { ...STAND, sit: 1, lL: [84, -86], lR: [78, -82], aL: [16, 44], aR: [12, 50] };
const kf = (t, keys) => {                                // keyframes [[t, value], ...] with smoothstep between
  if (t <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) if (t <= keys[i][0]) {
    const [t0, a] = keys[i - 1], [t1, b] = keys[i], k = ease((t - t0) / (t1 - t0));
    return Array.isArray(a) ? a.map((v, j) => lerp(v, b[j], k)) : lerp(a, b, k);
  }
  return keys[keys.length - 1][1];
};
const S = Math.sin;
// clip(name, t, p) → target pose. `base` is SIT or STAND depending on where the person is.
const CLIPS = {
  idle: (t, p, b) => { const w = S(t * .7 + p.seed) ; const pockets = p.seed % 3 === 0;
    return { ...b, lL: [b.lL[0] + (b.sit ? 0 : 3 * w), b.lL[1]], lR: [b.lR[0] - (b.sit ? 0 : 3 * w), b.lR[1] - (b.sit ? 0 : Math.max(0, w) * 8)],
      aL: pockets && !b.sit ? [-14, 30] : [b.aL[0] + 2 * w, b.aL[1]], aR: pockets && !b.sit ? [-12, 28] : b.aR, hy: S(t * .23 + p.seed) * .6 }; },
  wait: (t, p, b) => ({ ...CLIPS.idle(t, p, b), lR: [-3, -Math.max(0, S(t * 9)) * 14], hy: .4 }),
  walk: (t, p, b, hold) => { const f = t * 10.5, c = S(f), k = S(f + 1.57);
    const arm = side => side > 0 ? [-20 * c, 22] : [20 * c, 22];
    return { ...STAND, lL: [24 * c, -38 * Math.max(0, -k)], lR: [-24 * c, -38 * Math.max(0, k)], bob: 1.1 * Math.abs(k), lean: 4,
      aL: hold.L ? [32, 92] : arm(1), aR: hold.R ? [30, 88] : arm(-1), hy: 0 }; },
  press: (t, p, b) => ({ ...b, lean: 6, aR: kf(t, [[0, b.aR], [.3, [78, 8]], [.45, [86, 2]], [.6, [78, 8]], [.95, [20, 40]]]), hy: .3 }),
  reach: (t, p, b) => ({ ...b, lean: kf(t, [[0, 0], [.3, 14], [1.1, 14], [1.4, 2]]), bob: -kf(t, [[0, 0], [.3, 2.5], [1.1, 2.5], [1.4, 0]]),
    aR: kf(t, [[0, b.aR], [.3, [82, 8]], [1.1, [86, 14]], [1.4, [40, 70]]]), aL: [10, 30], lL: [10, -14], lR: [-4, -16] }),
  pour: (t, p, b) => ({ ...b, lean: 6, ht: 10, aR: kf(t, [[0, [30, 80]], [.4, [62, 46]], [2, [62, 46]], [2.4, [30, 80]]]), aL: [38, 78], pour: kf(t, [[0, 0], [.4, 1], [2, 1], [2.4, 0]]) }),
  sip: (t, p, b) => ({ ...b, ht: kf(t, [[0, 0], [.5, -12], [1.4, -12], [1.9, 2], [2.2, 0]]),
    aR: kf(t, [[0, [24, 80]], [.5, [44, 132]], [1.4, [46, 136]], [1.9, [22, 84]], [2.2, [24, 80]]]) }),
  hold: (t, p, b) => ({ ...CLIPS.idle(t, p, b), aR: [26, 82] }),                          // standing or sitting with a mug
  type: (t, p, b) => ({ ...b, lean: 9, ht: 4, aL: [60, 36 + 4 * S(t * 23 + p.seed)], aR: [56, 40 + 4 * S(t * 27)], hy: .15 * S(t * .5) }),
  mouse: (t, p, b) => ({ ...b, lean: 5, ht: 2, aL: [26, 70], aR: [52, 30 + 3 * S(t * 2.5)], hy: .3 }),
  glance: (t, p, b) => ({ ...CLIPS.type(t, p, b), hy: kf(t, [[0, 0], [.4, .9], [1.6, .9], [2, 0]]), aL: [40, 60] }),
  leanback: (t, p, b) => ({ ...b, lean: -13, ht: -6, aL: [168, 150], aR: [168, 150], hy: S(t * .4) * .5 }),
  think: (t, p, b) => ({ ...b, lean: 3, ht: 6, aR: [30, 150], aL: [24, 76], hy: -.3 }),
  deskstretch: (t, p, b) => ({ ...b, lean: -6, bob: -kf(t, [[0, 0], [.6, 2], [1.8, 2], [2.5, 0]]), aL: kf(t, [[0, b.aL], [.6, [176, 6]], [1.8, [176, 6]], [2.5, b.aL]]), aR: kf(t, [[0, b.aR], [.6, [176, 6]], [1.8, [176, 6]], [2.5, b.aR]]), mouth: kf(t, [[.5, 0], [.9, 1], [1.6, 1], [2, 0]]) }),
  review: (t, p, b) => ({ ...b, lean: 6, ht: 12 + 3 * S(t * 1.3), aL: [40, 82], aR: kf(t % 7, [[0, [30, 70]], [5, [30, 70]], [5.4, [72, 16]], [6.4, [72, 16]], [7, [30, 70]]]) }),
  call: (t, p, b) => ({ ...CLIPS.idle(t, p, b), aR: [24, 152], aL: [32 + 16 * Math.max(0, S(t * 1.7)), 64 + 18 * S(t * 2.3)], hy: S(t * .6) * .6, mouth: Math.max(0, S(t * 9)) * (S(t * .8) > -.2) }),
  gesture: (t, p, b) => ({ ...b, aR: [44 + 22 * S(t * 2.4), 62 + 20 * S(t * 1.9)], aL: [30, 60], ht: 3 * S(t * 3), mouth: Math.max(0, S(t * 10)) }),
  talk: (t, p, b) => ({ ...b, aR: [36 + 26 * Math.max(0, S(t * 2.6)), 66 + 22 * S(t * 2.1)], ht: 3 * S(t * 4), mouth: Math.max(0, S(t * 11)), hy: .2 }),
  listen: (t, p, b) => ({ ...b, aL: [22, 112], aR: [24, 108], ht: 4 + 4 * Math.max(0, S(t * 1.6)), hy: .2 }),
  laugh: (t, p, b) => ({ ...b, bob: 1.6 * Math.abs(S(t * 13)), ht: -14, aL: [20, 60], aR: [24, 70], mouth: 1, eyes: 0 }),
  eat: (t, p, b) => { const c = t % 4.2;
    return { ...b, lean: 6, ht: kf(c, [[0, 10], [.9, -2], [1.4, -2], [2.0, 8]]), aL: [30, 74],
      aR: kf(c, [[0, [34, 60]], [.5, [38, 54]], [.9, [44, 134]], [1.4, [44, 134]], [1.9, [32, 66]]]),
      mouth: c > .9 && c < 2.6 ? Math.max(0, S(c * 16)) * .8 : 0 }; },
  bite: (t, p, b) => { const c = t % 4.6;
    return { ...b, ht: kf(c, [[0, 6], [.7, -4], [1.4, -4], [2, 6]]), aR: kf(c, [[0, [26, 80]], [.7, [44, 134]], [1.3, [44, 134]], [2, [26, 80]]]),
      mouth: c > .7 && c < 2.8 ? Math.max(0, S(c * 15)) * .8 : 0 }; },
  phone: (t, p, b) => ({ ...b, ht: 16, aL: [32, 112], aR: [30, 114 + 4 * Math.max(0, S(t * 7) * (S(t * .7) > 0))], hy: .1 }),
  stretch: (t, p, b) => ({ ...b, bob: -kf(t, [[0, 0], [.7, 2.5], [2, 2.5], [2.8, 0]]), lean: kf(t, [[0, 0], [.7, -5], [2, -5], [2.8, 0]]),
    aL: kf(t, [[0, b.aL], [.7, [178, 4]], [2, [178, 4]], [2.8, b.aL]]), aR: kf(t, [[0, b.aR], [.7, [178, 4]], [2, [178, 4]], [2.8, b.aR]]), mouth: kf(t, [[.4, 0], [.9, 1], [1.8, 1], [2.3, 0]]), eyes: t > .8 && t < 1.9 ? 0 : 1 }),
  yawn: (t, p, b) => ({ ...b, ht: kf(t, [[0, 0], [.6, -16], [1.5, -16], [2, 0]]), aR: kf(t, [[0, b.aR], [.5, [44, 140]], [1.5, [44, 140]], [2, b.aR]]), mouth: kf(t, [[0, 0], [.5, 1], [1.5, 1], [2, 0]]), eyes: t > .4 && t < 1.6 ? 0 : 1 }),
  smoke: (t, p, b) => { const c = t % 6;
    return { ...b, aL: [20, 104], aR: kf(c, [[0, [18, 96]], [.6, [42, 140]], [1.4, [42, 140]], [2, [18, 96]]]), ht: kf(c, [[0, 0], [1.4, -6], [2.2, -10], [3, 0]]), hy: .3 + S(t * .3) * .3, drag: c > .6 && c < 1.4 ? 1 : 0, exhale: c > 2 && c < 2.25 }; },
  light: (t, p, b) => ({ ...b, ht: 8, aR: [42, 140], aL: [40, 132], flame: t > .4 && t < 1.2 }),
  water: (t, p, b) => ({ ...b, lean: 9, ht: 14, aR: [58, 18 + 4 * S(t * 3)], aL: [12, 30], pour: 1 }),
  draw: (t, p, b) => ({ ...b, lean: 3, ht: -6, aR: [112 + 9 * S(t * 6.3), 26 + 12 * S(t * 8.7)], aL: [14, 28], hy: .2 * S(t * .7) }),
  erase: (t, p, b) => ({ ...b, aR: [104 + 16 * S(t * 5), 20 + 14 * S(t * 5 + 1)], aL: [10, 26], lean: 2 }),
  read: (t, p, b) => ({ ...b, ht: 18, aL: [36, 96], aR: (t % 9) > 8 ? [48, 70] : [34, 98] }),
  gaze: (t, p, b) => ({ ...b, ht: -4, aL: [-26, 34], aR: [-24, 34], hy: S(t * .25) * .8, lL: [b.lL[0] + 2, 0], lR: [-6, -6] }),
  lean: (t, p, b) => ({ ...b, lean: -3, aL: [-12, 18], aR: [-10, 22], lL: [10, 0], lR: [-8, -10], hy: S(t * .3) * .5 }),
  nap: (t, p, b) => ({ ...b, aL: [150, 120], aR: [20, 40], ht: 8, eyes: 0, lL: [40, -80], lR: [30, -70], bob: -.5 * S(t * 1.2) }),
  sunbathe: (t, p, b) => ({ ...b, aL: [168, 150], aR: [168, 150], eyes: 0, lL: [10, -14], lR: [0, 0], bob: -.4 * S(t * 1.1) }),
  paddle: (t, p, b) => ({ ...b, lean: 12, lL: [12, -24], lR: [-8, -20], bob: 2 + .8 * S(t * 6), aL: [30, 50],
    aR: kf(p.swing || 0, [[0, [40, 60]], [.5, [-10, 40]], [.75, [95, 20]], [1, [40, 60]]]), hy: .3 }),
};
const lerpPose = (a, b, k) => { const o = {}; for (const key in b) { const x = a[key], y = b[key];
  o[key] = Array.isArray(y) ? y.map((v, i) => lerp(x ? x[i] : v, v, k)) : typeof y === "number" ? lerp(x == null ? y : x, y, k) : y; } return o; };

// ── drawing a person at the current pose. Local frame: feet at (0,0), facing +x. Back views and mirroring come from dir.
const dv = (a, back) => { const s = Math.sin(a * D2R), c = Math.cos(a * D2R); return [s * .82, c + (back ? -.3 : .3) * s]; };
function limb(g, pts, w, col, out) {
  g.lineCap = "round"; g.lineJoin = "round";
  g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.strokeStyle = out; g.lineWidth = w + 1.5; g.stroke();
  g.beginPath(); pts.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y)); g.strokeStyle = col; g.lineWidth = w; g.stroke();
}
const add = (a, b, k = 1) => [a[0] + b[0] * k, a[1] + b[1] * k];
function drawPerson(g, p, T) {
  const L = p.look, po = p.pose, lying = po.lie > .5;
  const back = !lying && (p.dir === "NE" || p.dir === "NW"), mirror = !lying && (p.dir === "SW" || p.dir === "NW");
  const OUT = "rgba(20,24,32,.55)";
  g.save();
  g.scale(L.scale * (mirror ? -1 : 1), L.scale);
  // lying: rotate so the head points along the bed, pivoting at the pelvis (the slot point)
  if (lying) { g.rotate((p.lieAng || 0) + Math.PI / 2); g.translate(0, BODY.thigh + BODY.shin); }
  p.mirror = mirror;
  const hipH = lerp(BODY.thigh + BODY.shin, BODY.seat, po.sit), pelvis = [0, -hipH - po.bob];
  const tdir = dv(180 - po.lean, back), neck = add(pelvis, tdir, BODY.torso);
  const head = add(neck, dv(180 - po.lean - po.ht * .6, back), BODY.neck + BODY.head);
  const sh = add(neck, tdir, -1.6);
  const legs = ["lR", "lL"].map(k => { const [hp, kn] = po[k], knee = add(pelvis, dv(hp, back), BODY.thigh); return [pelvis, knee, add(knee, dv(hp + kn, back), BODY.shin)]; });
  const arms = ["aR", "aL"].map((k, i) => { const [s, e] = po[k], o = add(sh, [i ? -1.4 : 1.4, 0]), el = add(o, dv(s, back), BODY.upper); return [o, el, add(el, dv(s + e, back), BODY.fore)]; });
  p.hands = { R: arms[0][2], L: arms[1][2], head, mouth: add(head, [2.4 + po.hy * 1.2, 2.6]) };
  const sleeve = L.cut === "jacket" ? L.top2 : L.top, bareArms = L.cut === "tee";
  const drawArm = (a, dark) => { const c = dark ? shade(sleeve, -.18) : sleeve;
    if (bareArms) { limb(g, [a[0], add(a[0], [(a[1][0] - a[0][0]) * .45, (a[1][1] - a[0][1]) * .45])], 3.6, c, OUT); limb(g, [add(a[0], [(a[1][0] - a[0][0]) * .45, (a[1][1] - a[0][1]) * .45]), a[1], a[2]], 3.0, dark ? shade(L.skin, -.12) : L.skin, OUT); }
    else limb(g, a, 3.4, c, OUT);
    g.fillStyle = dark ? shade(L.skin, -.12) : L.skin; g.beginPath(); g.arc(a[2][0], a[2][1], 1.9, 0, 7); g.fill(); };
  const drawLeg = (l, dark) => { const c = dark ? shade(L.pants, -.2) : L.pants; limb(g, l, 4.2, c, OUT);
    g.fillStyle = "#1c1f25"; g.beginPath(); g.ellipse(l[2][0] + 1.4, l[2][1] - .4, 2.8, 1.5, 0, 0, 7); g.fill(); };
  // back arm/leg first, then torso, then the near limbs; from behind, both arms are behind the torso
  drawLeg(legs[0], true);
  if (back) { drawArm(arms[0], true); drawArm(arms[1], false); } else drawArm(arms[0], true);
  drawLeg(legs[1], false);
  // torso: a rounded trapezoid along the spine
  const perp = [-tdir[1], tdir[0]], br = 1 + .025 * S(T * 1.8 + p.seed);
  const s1 = add(neck, perp, 5.4 * br), s2 = add(neck, perp, -5.4 * br), h1 = add(pelvis, perp, 4.6), h2 = add(pelvis, perp, -4.6);
  const tg = g.createLinearGradient(s1[0], s1[1], h2[0], h2[1]); tg.addColorStop(0, shade(L.top, .1)); tg.addColorStop(1, shade(L.top, -.12));
  g.beginPath(); g.moveTo(...add(s1, tdir, -1)); g.quadraticCurveTo(...add(neck, tdir, 1.2), ...add(s2, tdir, -1));
  g.lineTo(...h2); g.quadraticCurveTo(...add(pelvis, tdir, -1.4), ...h1); g.closePath();
  g.fillStyle = tg; g.fill(); g.strokeStyle = NIGHT_N > .3 ? shade(L.top, .45) : OUT; g.lineWidth = 1.1; g.stroke();
  if (!back) {
    if (L.cut === "jacket") { g.fillStyle = L.top2; g.beginPath(); g.moveTo(...add(neck, perp, 1.6)); g.lineTo(...add(pelvis, perp, 1.4)); g.lineTo(...add(pelvis, perp, -1.4)); g.lineTo(...add(neck, perp, -1.6)); g.fill(); }
    if (L.cut === "hoodie") { line(g, [add(neck, tdir, -1.5), add(neck, tdir, -5)], "rgba(255,255,255,.7)", .7); line(g, [add(add(neck, perp, 1.6), tdir, -1.5), add(add(neck, perp, 1.6), tdir, -4.5)], "rgba(255,255,255,.7)", .7);
      g.fillStyle = shade(L.top, -.15); g.beginPath(); g.ellipse(...add(add(pelvis, tdir, 4), perp, 0), 3.5, 1.6, 0, 0, 7); g.fill(); }
    if (L.cut === "shirt") { g.fillStyle = "#fff"; g.beginPath(); g.moveTo(...add(neck, perp, 2.6)); g.lineTo(...add(neck, tdir, -2.6)); g.lineTo(...add(neck, perp, -2.6)); g.fill(); }
    if (L.cut === "sweater") line(g, [add(add(neck, tdir, -6), perp, 5), add(add(neck, tdir, -6), perp, -5)], shade(L.top, .3), 1.6);
  } else if (L.cut === "hoodie") { g.fillStyle = shade(L.top, -.08); g.beginPath(); g.ellipse(...add(neck, tdir, -1.5), 4.2, 2.6, 0, 0, 7); g.fill(); }
  if (!back) drawArm(arms[1], false);
  // head
  const [hx, hy] = head, r = BODY.head, hc = L.hair;
  if (back) {                                                // from behind: hair over the crown, ears and the nape still show
    g.fillStyle = L.skin; g.beginPath(); g.arc(hx, hy, r, 0, 7); g.fill(); g.strokeStyle = OUT; g.lineWidth = .9; g.stroke();
    g.fillRect(hx - 1.5, hy + r - 1, 3, 2);
    const low = { buzz: -.1, crop: .05, side: .1, curly: .2, bun: .15, pony: .15, afro: .3, long: 1.2 }[L.hairStyle] ?? .1;
    g.fillStyle = hc; g.beginPath(); g.arc(hx, hy - .3, r + .45, Math.PI - low, low); g.quadraticCurveTo(hx, hy + r * .15, hx - (r + .45) * Math.cos(low), hy + (r + .45) * Math.sin(low)); g.fill();
    g.fillStyle = L.skin; g.beginPath(); g.ellipse(hx - r + .4, hy + .9, 1.2, 1.7, 0, 0, 7); g.ellipse(hx + r - .4, hy + .9, 1.2, 1.7, 0, 0, 7); g.fill();
    g.fillStyle = hc;
    if (L.hairStyle === "curly") for (let i = 0; i < 5; i++) { g.beginPath(); g.arc(hx - 4.5 + i * 2.3, hy - 5 + (i % 2), 1.9, 0, 7); g.fill(); }
    if (L.hairStyle === "pony") { g.beginPath(); g.ellipse(hx - .5, hy + 5.5, 1.8, 3.8, .2, 0, 7); g.fill(); }
    if (L.hairStyle === "bun") { g.beginPath(); g.arc(hx, hy - 6, 2.8, 0, 7); g.fill(); }
    if (L.hairStyle === "afro") { g.beginPath(); g.arc(hx, hy - 2.2, r + 1.4, 0, 7); g.fill(); }
    if (L.hairStyle === "long") { g.beginPath(); g.roundRect(hx - r + 1, hy - 1, 2 * r - 2, r + 2, 3); g.fill(); }
  } else {
    if (L.hairStyle === "afro") { g.fillStyle = hc; g.beginPath(); g.arc(hx - .6, hy - 2.2, r + 1.4, 0, 7); g.fill(); }
    if (L.hairStyle === "long") { g.fillStyle = hc; g.beginPath(); g.roundRect(hx - r - .4, hy - 2, 2 * r - 1, r + 6, 3); g.fill(); }
    if (L.hairStyle === "pony") { g.fillStyle = hc; g.beginPath(); g.ellipse(hx - r - .5, hy + 1.5, 1.7, 3.8, .5, 0, 7); g.fill(); }
    g.fillStyle = L.skin; g.beginPath(); g.arc(hx, hy, r, 0, 7); g.fill(); g.strokeStyle = OUT; g.lineWidth = .9; g.stroke();
    g.fillStyle = hc; g.beginPath();
    const cap = { crop: [Math.PI * 1.05, -.05], side: [Math.PI * .95, -.25], bun: [Math.PI * 1.02, -.02], pony: [Math.PI * 1.0, 0], afro: [Math.PI * 1.0, 0], long: [Math.PI * .9, -.1], buzz: [Math.PI * 1.1, -.1], curly: [Math.PI * .95, .05] }[L.hairStyle];
    g.arc(hx, hy - .3, r + .5, cap[0], cap[1]); g.quadraticCurveTo(hx + 1, hy - 2.6, hx - r + .5, hy - .5); g.fill();
    if (L.hairStyle === "side") { g.beginPath(); g.moveTo(hx - 3, hy - 5); g.quadraticCurveTo(hx + 5, hy - 5.5, hx + 5.8, hy - 1.5); g.lineTo(hx + 1, hy - 3.6); g.fill(); }
    if (L.hairStyle === "bun") { g.beginPath(); g.arc(hx - 1.5, hy - 6.8, 2.7, 0, 7); g.fill(); }
    if (L.hairStyle === "curly") for (let i = 0; i < 5; i++) { g.beginPath(); g.arc(hx - 4.5 + i * 2.3, hy - 5.2 + (i % 2), 1.9, 0, 7); g.fill(); }
    if (L.hairStyle === "buzz") { g.globalAlpha = .55; g.beginPath(); g.arc(hx, hy - .3, r + .2, Math.PI * 1.05, -.05); g.fill(); g.globalAlpha = 1; }
    // face (3/4: features sit toward the facing side)
    const ex = hx + 1.2 + po.hy * 1.6, ey = hy + .2, blink = po.eyes < .5 || ((T + p.seed % 50) % 4.3) < .12;
    g.fillStyle = "#1d1d22"; g.strokeStyle = "#1d1d22"; g.lineWidth = .8;
    for (const dx of [-1.6, 1.8]) { if (blink) { g.beginPath(); g.moveTo(ex + dx - .9, ey); g.lineTo(ex + dx + .9, ey); g.stroke(); } else { g.beginPath(); g.arc(ex + dx, ey, .85, 0, 7); g.fill(); } }
    g.fillStyle = "rgba(230,110,110,.22)"; g.beginPath(); g.arc(ex + 3.4, ey + 2, 1.5, 0, 7); g.fill();
    const m = p.hands.mouth; if (po.mouth > .15) { g.fillStyle = "#6b2a2a"; g.beginPath(); g.ellipse(m[0], m[1], 1.1, .45 + po.mouth * .9, 0, 0, 7); g.fill(); }
    else line(g, [[m[0] - .9, m[1]], [m[0] + .9, m[1] + .1]], "rgba(60,30,30,.7)", .7);
    if (L.glasses) { g.strokeStyle = "#2a2a30"; g.lineWidth = .7; for (const dx of [-1.6, 1.8]) { g.beginPath(); g.arc(ex + dx, ey, 1.55, 0, 7); g.stroke(); } line(g, [[ex - .05, ey], [ex + .25, ey]], "#2a2a30", .6); }
  }
  if (L.phones) { g.strokeStyle = "#2a2d33"; g.lineWidth = 1.4; g.beginPath(); g.arc(hx, hy - .5, r + 1.1, Math.PI * 1.1, -.1); g.stroke();
    g.fillStyle = "#2a2d33"; g.beginPath(); g.ellipse(hx + (back ? 0 : -2.4), hy + .5, 2.2, 2.8, 0, 0, 7); g.fill(); }
  if (L.beanie) { g.fillStyle = L.top2; g.beginPath(); g.arc(hx, hy - 1, r + .8, Math.PI, 0); g.fill(); g.fillRect(hx - r - .8, hy - 1.6, 2 * r + 1.6, 2); }
  // props in hand
  const pr = p.hold || {}, aR = arms[0], aL = arms[1];
  if (pr.R) drawProp(g, pr.R, aR[2], aR[1], p, T, po, "R");
  if (pr.L) drawProp(g, pr.L, aL[2], aL[1], p, T, po, "L");
  g.restore();
}
function drawCarafe(g, x, y, level, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt);
  g.fillStyle = "rgba(220,235,245,.55)"; g.strokeStyle = "rgba(60,70,80,.7)"; g.lineWidth = .7;
  g.beginPath(); g.moveTo(-3, 0); g.lineTo(3, 0); g.lineTo(3.4, -4.5); g.lineTo(1.6, -7); g.lineTo(-1.6, -7); g.lineTo(-3.4, -4.5); g.closePath(); g.fill(); g.stroke();
  if (level > .02) { g.fillStyle = "rgba(90,50,25,.9)"; g.fillRect(-3, -4.5 * level, 6, 4.5 * level); }
  g.fillStyle = "#222"; g.fillRect(-1.8, -8, 3.6, 1.4); g.restore();
}
function drawCan(g, x, y, tilt) {
  g.save(); g.translate(x, y); g.rotate(tilt); g.fillStyle = "#3f9d6a"; g.strokeStyle = "rgba(0,0,0,.4)"; g.lineWidth = .6;
  g.beginPath(); g.roundRect(-3.5, -5, 7, 5, 1.2); g.fill(); g.stroke(); line(g, [[3, -3], [7.5, -6.5]], "#3f9d6a", 1.3);
  g.beginPath(); g.arc(-1, -5.5, 2.4, Math.PI, 0); g.stroke(); g.restore();
}
// props are drawn in the person's local (possibly mirrored) frame at a hand
function drawProp(g, kind, h, elbow, p, T, po, side) {
  const [x, y] = h, fa = Math.atan2(h[1] - elbow[1], h[0] - elbow[0]);
  g.save(); g.translate(x, y);
  switch (kind) {
    case "mug": drawMugAt(g, 1.2, 2.2, p.look.mug); if (T - (p.hotSince || -99) < 90) steamAt(p, side); break;
    case "cup": g.fillStyle = "rgba(220,240,255,.85)"; g.strokeStyle = "rgba(90,120,150,.7)"; g.lineWidth = .5; g.beginPath(); g.moveTo(-1.5, -3); g.lineTo(1.5, -3); g.lineTo(1.1, 1); g.lineTo(-1.1, 1); g.closePath(); g.fill(); g.stroke(); break;
    case "carafe": drawCarafe(g, 1, 3, OBJ.coffee.level, (po.pour || 0) * 1.1); break;
    case "plate": case "salad": g.fillStyle = "#fbfbf8"; g.strokeStyle = "rgba(0,0,0,.25)"; g.lineWidth = .5; g.beginPath(); g.ellipse(2.5, 0, 6.5, 2.3, 0, 0, 7); g.fill(); g.stroke();
      g.fillStyle = kind === "salad" ? "#7cb342" : "#e8a33d"; g.beginPath(); g.ellipse(2.5, -1, 3.6, 1.4, 0, 0, 7); g.fill();
      if (kind !== "salad") { g.fillStyle = "#c0392b"; g.beginPath(); g.arc(4, -1.6, 1.1, 0, 7); g.fill(); }
      if (T - (p.hotSince || -99) < 60) steamAt(p, side); break;
    case "takeout": g.fillStyle = "#f4f4f0"; g.strokeStyle = "rgba(0,0,0,.35)"; g.lineWidth = .5; g.beginPath(); g.moveTo(-3, -4.5); g.lineTo(4, -4.5); g.lineTo(3, 1); g.lineTo(-2, 1); g.closePath(); g.fill(); g.stroke();
      g.fillStyle = "#c0392b"; g.fillRect(-1.5, -3, 4, 1.4); if (T - (p.hotSince || -99) < 60) steamAt(p, side); break;
    case "yogurt": g.fillStyle = "#ffd6e0"; g.strokeStyle = "rgba(0,0,0,.3)"; g.lineWidth = .5; g.beginPath(); g.moveTo(-2, -3.5); g.lineTo(2, -3.5); g.lineTo(1.5, 1); g.lineTo(-1.5, 1); g.closePath(); g.fill(); g.stroke(); g.fillStyle = "#fff"; g.fillRect(-2, -4, 4, .9); break;
    case "apple": g.fillStyle = "#d63b2f"; g.beginPath(); g.arc(0, -1.5, 2.5, 0, 7); g.fill(); line(g, [[0, -4], [.6, -5.2]], "#5b3a1a", .7); g.fillStyle = "#6a994e"; g.beginPath(); g.ellipse(1.4, -4.6, 1.2, .6, -.5, 0, 7); g.fill(); break;
    case "sandwich": g.fillStyle = "#f3d9a4"; g.beginPath(); g.moveTo(-3, 1); g.lineTo(3, 1); g.lineTo(0, -4); g.closePath(); g.fill(); g.fillStyle = "#7cb342"; g.fillRect(-2.5, -.2, 5, .8); break;
    case "fork": case "spoon": g.rotate(fa - Math.PI / 2); line(g, [[0, -1], [0, 6]], "#9aa3ab", .8); if (kind === "spoon") { g.fillStyle = "#9aa3ab"; g.beginPath(); g.ellipse(0, 6.5, .9, 1.4, 0, 0, 7); g.fill(); } break;
    case "phone": g.rotate(fa - Math.PI / 2 + .3); g.fillStyle = "#1e2228"; g.beginPath(); g.roundRect(-1.4, -1, 2.8, 4.6, .6); g.fill();
      g.fillStyle = "#7fc3ff"; g.globalAlpha = .9; g.fillRect(-1, -.5, 2, 3.6); g.globalAlpha = 1; break;
    case "book": g.fillStyle = p.bookColor || "#2a9d8f"; g.beginPath(); g.roundRect(-1, -4.5, 7, 5, .6); g.fill(); g.fillStyle = "#fbf6ea"; g.fillRect(-.6, -4, 6.2, .8); break;
    case "paper": g.fillStyle = "#fff"; g.strokeStyle = "rgba(0,0,0,.25)"; g.lineWidth = .4; g.fillRect(-1, -5, 5, 6); g.strokeRect(-1, -5, 5, 6);
      for (let i = 0; i < 3; i++) line(g, [[0, -3.8 + i * 1.6], [3, -3.8 + i * 1.6]], "rgba(0,0,0,.3)", .4); break;
    case "cig": { g.rotate(fa - Math.PI / 2); line(g, [[0, 0], [0, 4]], "#f3f3f3", 1); const glow = po.drag ? 1 : .4;
      g.fillStyle = `rgba(255,${120 - glow * 60},40,${.6 + glow * .4})`; g.beginPath(); g.arc(0, 4.3, .9, 0, 7); g.fill(); p.ember = true; break; }
    case "lighter": g.fillStyle = "#e76f51"; g.fillRect(-1, -1, 2, 3.5); if (po.flame) { g.fillStyle = "#ffcf5c"; g.beginPath(); g.ellipse(0, -2.6, .9, 1.8, 0, 0, 7); g.fill(); } break;
    case "can": drawCan(g, 1, 2, (po.pour || 0) * .5); if (po.pour) p.pouring = side; break;
    case "marker": g.rotate(fa - Math.PI / 2); line(g, [[0, -1], [0, 4]], "#2a2a30", 1.4); g.fillStyle = p.marker || "#e63946"; g.fillRect(-.7, 3.4, 1.4, 1.4); break;
    case "paddle": g.rotate(fa - Math.PI / 2); line(g, [[0, 0], [0, 2.5]], "#7a5230", 1.4); g.fillStyle = "#c0392b"; g.beginPath(); g.ellipse(0, 5, 2.6, 3, 0, 0, 7); g.fill(); break;
  }
  g.restore();
}
// steam / smoke particles need world coordinates; the renderer converts the hand's local position after drawing
function steamAt(p, side) { p.emit = p.emit || []; p.emit.push(side); }

// ───────────────────────────── the sim: walking, slots, routines ─────────────────────────────
let T = 0;                                                  // sim seconds
const people = new Map();
OBJ.leftovers = []; OBJ.board = { strokes: [] }; OBJ.fridge.target = 0; OBJ.micro.target = 0;
const PARTS = [];                                           // particles (world px)
const part = o => { if (PARTS.length < 400 && !REDUCED) PARTS.push({ born: T, ...o }); };
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

// walking grid: half-tile cells; furniture blocks
const CELL = .5, NX = Math.round(X / CELL), NY = Math.round(Y / CELL), blocked = new Uint8Array(NX * NY);
for (const [x, y, w, d] of BLOCK) for (let i = Math.floor(x / CELL + .08); i < Math.ceil((x + w) / CELL - .08); i++)
  for (let j = Math.floor(y / CELL + .08); j < Math.ceil((y + d) / CELL - .08); j++) if (i >= 0 && j >= 0 && i < NX && j < NY) blocked[j * NX + i] = 1;
const cellOf = (x, y) => [clamp(Math.floor(x / CELL), 0, NX - 1), clamp(Math.floor(y / CELL), 0, NY - 1)];
const walkable = (x, y) => { if (x < .05 || y < .05 || x > X - .05 || y > Y - .05) return false; const [i, j] = cellOf(x, y); return !blocked[j * NX + i]; };
function nearestFree(i, j) {
  for (let r = 0; r < 8; r++) for (let di = -r; di <= r; di++) for (let dj = -r; dj <= r; dj++) {
    const a = i + di, b = j + dj; if (a >= 0 && b >= 0 && a < NX && b < NY && !blocked[b * NX + a]) return [a, b]; }
  return [i, j];
}
function route(fx, fy, tx, ty) {                            // A*, 8-way, no corner cutting
  const [si, sj] = nearestFree(...cellOf(fx, fy)), [gi, gj] = nearestFree(...cellOf(tx, ty));
  const N = NX * NY, gs = new Float32Array(N).fill(Infinity), prev = new Int32Array(N).fill(-1), open = [[0, sj * NX + si]];
  gs[sj * NX + si] = 0;
  const h = k => { const dx = Math.abs(k % NX - gi), dy = Math.abs((k / NX | 0) - gj); return Math.max(dx, dy) + .414 * Math.min(dx, dy); };
  while (open.length) {
    let bi = 0; for (let k = 1; k < open.length; k++) if (open[k][0] < open[bi][0]) bi = k;   // ponytail: linear open list; 966 cells
    const cur = open.splice(bi, 1)[0][1]; if (cur === gj * NX + gi) break;
    const ci = cur % NX, cj = cur / NX | 0;
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const a = ci + di, b = cj + dj, k = b * NX + a;
      if (a < 0 || b < 0 || a >= NX || b >= NY || blocked[k] || (di && dj && (blocked[cj * NX + a] || blocked[b * NX + ci]))) continue;
      const ng = gs[cur] + (di && dj ? 1.414 : 1); if (ng < gs[k]) { gs[k] = ng; prev[k] = cur; open.push([ng + h(k), k]); }
    }
  }
  const pts = []; for (let k = gj * NX + gi; k !== -1; k = prev[k]) { pts.push([(k % NX + .5) * CELL, ((k / NX | 0) + .5) * CELL]); if (k === sj * NX + si) break; }
  pts.reverse();
  // string-pull: drop points we can see past, so paths read as walks, not staircases
  const out = [[fx, fy]];
  for (let i = 1; i < pts.length; i++) { const a = out[out.length - 1], c = pts[i + 1]; if (!c || !clearLine(a, c)) out.push(pts[i]); }
  out.push([tx, ty]); out.shift(); return out;
}
function clearLine([ax, ay], [bx, by]) { const n = Math.ceil(Math.hypot(bx - ax, by - ay) / .2); for (let i = 1; i < n; i++) if (!walkable(lerp(ax, bx, i / n), lerp(ay, by, i / n))) return false; return true; }

// slots
const free = g => SLOTS[g].some(s => !s.by);
function claimSlot(p, s) { if (!s || (s.by && s.by !== p)) return null; s.by = p; p.claims.add(s); return s; }
function claim(p, g, prefer) { const list = SLOTS[g]; for (const s of prefer != null ? [list[prefer], ...list] : list.slice().sort(() => Math.random() - .5)) if (s && !s.by) return claimSlot(p, s); return null; }
function claimNear(p, groups) {
  let best = null, bd = 1e9; for (const g of groups) for (const s of SLOTS[g] || []) if (!s.by) { const d = Math.hypot(s.x - p.x, s.y - p.y) + Math.random() * 3; if (d < bd) { bd = d; best = s; } }
  return claimSlot(p, best);
}
const release = (p, s) => { if (s && s.by === p) s.by = null; p.claims.delete(s); };
const releaseAll = p => { for (const s of p.claims) if (s.by === p) s.by = null; p.claims.clear(); };
function loiter(p, near) {                                  // any free floor cell away from people and fixed spots
  const cx = near ? near.x : p.x, cy = near ? near.y : p.y;
  for (let tries = 0; tries < 60; tries++) {
    const x = clamp(cx + rnd(-3, 3), .4, 13.6), y = clamp(cy + rnd(-3, 3), .4, Y - .4);
    if (!walkable(x, y)) continue;
    if ([...people.values()].some(q => q !== p && Math.hypot(q.x - x, q.y - y) < .9)) continue;
    if (Object.values(SLOTS).some(l => l.some(s => Math.hypot(s.x - x, s.y - y) < .6))) continue;
    return { x, y, dir: pick(["SE", "SW", "NE", "NW"]), pose: "stand", temp: true };
  }
  return { x: p.x, y: p.y, dir: p.dir, pose: "stand", temp: true };
}

// scripts: generators that yield {dur}, {walk}, {until}
const setClip = (p, c) => { if (p.clip !== c) { p.clip = c; p.clipT = 0; } };
function* act(p, c, a, b = a) { p.clip = c; p.clipT = 0; yield { dur: rnd(a, b) }; }
function* go(p, slot) {
  if (!slot) return;
  p.slot = slot; p.seated = false; p.lying = false; p.z = 0;
  if (p.teleport || REDUCED) { p.x = slot.x; p.y = slot.y; p.path = []; p.teleport = false; }
  else if (Math.hypot(slot.x - p.x, slot.y - p.y) > .05) { p.path = route(p.x, p.y, slot.x, slot.y); setClip(p, "walk"); yield { walk: 1 }; }
  p.dir = slot.dir; p.seated = slot.pose === "sit"; p.lying = slot.pose === "lie"; p.lieAng = slot.lieAng; p.z = slot.z || 0;
  setClip(p, "idle");
}
function start(p, gen) { p.co = gen; p.wait = null; }   // callers stop() first, before claiming
function stop(p) {
  if (p.co) { try { p.co.return(); } catch (e) {} p.co = null; }
  p.wait = null;
  for (const f of p.onStop.splice(0)) f();
  releaseAll(p);
  if (p.conv) { p.conv.dead = true; p.conv = null; }
  if (p.rally) { p.rally.dead = true; p.rally = null; }
  if (p.hold.R === "carafe" || p.hold.L === "carafe") OBJ.coffee.carafe = true;
  if (p.hold.R === "can") OBJ.can.held = false;
  p.hold = {}; p.interruptible = false;
}
function run(p) {
  for (let guard = 0; guard < 20; guard++) {
    const w = p.wait;
    if (w) {
      if (w.t != null && T < w.t) return;
      if (w.walk && p.path.length) return;
      if (w.until && !w.until()) return;
      p.wait = null;
    }
    if (!p.co) return;
    let r; try { r = p.co.next(); } catch (e) { console.error("office script", e); r = { done: true }; }
    if (r.done) { p.co = null; p.onStop.splice(0).forEach(f => f()); releaseAll(p); return; }
    p.wait = r.value || null; if (p.wait && p.wait.dur != null) p.wait.t = T + p.wait.dur;
  }
}

// ── idle routines
function* coffee(p) {
  let s = claim(p, "coffee");
  if (!s) { const q = claim(p, "coffeeQ"); if (!q) return; yield* go(p, q); setClip(p, "wait");
    yield { until: () => !SLOTS.coffee[0].by }; release(p, q); s = claim(p, "coffee"); if (!s) return; }
  yield* go(p, s);
  const M = OBJ.coffee;
  if (M.state !== "ready") {
    if (M.state === "idle") { yield* act(p, "press", .95); M.state = "brewing"; M.t = T + rnd(6, 9); }
    setClip(p, "wait"); yield { until: () => M.state === "ready" };
  }
  M.carafe = false; p.hold = { R: "carafe", L: "mug" };
  yield* act(p, "pour", 2.4);
  M.carafe = true; M.level = Math.max(0, M.level - .2); if (M.level < .12) M.state = "idle";
  p.hold = { R: "mug" }; p.hotSince = T;
  yield* act(p, "sip", 2.2);
  p.energy = Math.min(1, p.energy + .55);
  release(p, s);
  yield* withDrink(p);
}
function* withDrink(p) {
  const seat = claimNear(p, pick([["sofa", "sofa2", "dine"], ["patioA", "patioB"], ["window", "rail", "counter"], ["patioA", "patioB", "sofa"]]))
    || claimNear(p, ["sofa", "sofa2", "dine", "patioA", "patioB", "window", "rail", "counter"]);
  yield* go(p, seat || loiter(p));
  p.interruptible = true;
  for (const end = T + rnd(40, 110); T < end;) { yield* act(p, "hold", 5, 11); yield* act(p, "sip", 2.2); if (Math.random() < .12) yield* act(p, "laugh", 1.2); }
  p.interruptible = false; release(p, seat);
  if (seat && seat.pose === "sit" && Math.random() < .3) {   // leaves the mug behind; someone's always doing that
    OBJ.leftovers.push({ x: seat.x + (seat.dir === "SE" ? .3 : seat.dir === "NW" ? -.3 : 0), y: seat.y + (seat.dir === "SW" ? .3 : seat.dir === "NE" ? -.3 : 0), col: p.look.mug, until: T + 150 });
    p.hold = {}; return;
  }
  yield* dishes(p);
}
function* dishes(p) {
  const s = claim(p, "sink"); if (!s) { p.hold = {}; return; }
  yield* go(p, s); yield* act(p, "reach", 1.1); p.hold = {}; OBJ.sink.until = T + 2.4; yield* act(p, "idle", 2.4); release(p, s);
}
function* food(p, meal) {
  const f = claim(p, "fridge"); if (!f) return;
  yield* go(p, f);
  OBJ.fridge.target = 1; p.onStop.push(() => OBJ.fridge.target = 0);
  yield* act(p, "reach", 1.5);
  const kind = meal ? pick(["takeout", "plate", "plate", "salad", "takeout"]) : pick(["yogurt", "apple", "sandwich", "yogurt"]);
  p.hold = { R: kind }; yield* act(p, "idle", .5); OBJ.fridge.target = 0; yield { dur: .5 };
  release(p, f);
  if (kind === "takeout" || kind === "plate") {
    let m = claim(p, "micro");
    if (!m) { yield* go(p, loiter(p, SLOTS.micro[0])); setClip(p, "wait"); yield { until: () => !SLOTS.micro[0].by }; m = claim(p, "micro"); }
    if (m) {
      yield* go(p, m);
      const M = OBJ.micro; p.onStop.push(() => { M.target = 0; M.run = 0; M.item = null; });
      M.target = 1; yield* act(p, "reach", 1.1); p.hold = {}; M.item = kind; M.target = 0; yield { dur: .4 };
      yield* act(p, "press", .95); M.run = 1; M.end = T + rnd(12, 22);
      while (T < M.end) { if (Math.random() < .5) { p.hold = { R: "phone" }; yield* act(p, "phone", 3, 6); p.hold = {}; } else yield* act(p, "wait", 2, 4); }
      M.run = 0; M.ding = T; yield* act(p, "idle", .6);
      M.target = 1; yield* act(p, "reach", 1.1); p.hold = { R: kind }; M.item = null; p.hotSince = T; M.target = 0;
      release(p, m);
    }
  }
  const cold = ["apple", "yogurt", "sandwich"].includes(kind);
  const seat = claimNear(p, pick(cold ? [["counter", "window"], ["sofa", "sofa2"], ["dine"], ["patioA", "patioB"]] : [["dine"], ["dine"], ["sofa", "sofa2"], ["patioA", "patioB"]]))
    || claimNear(p, ["dine", "sofa", "sofa2", "counter", "patioA", "patioB"]);
  yield* go(p, seat || loiter(p));
  const utensil = kind === "yogurt" || kind === "salad" ? "spoon" : cold ? null : "fork";
  p.hold = utensil ? { L: kind, R: utensil } : { R: kind };
  p.interruptible = true;
  for (const end = T + (meal ? rnd(60, 140) : rnd(25, 55)); T < end;) yield* act(p, utensil ? "eat" : "bite", 4.2, 8.4);
  p.interruptible = false;
  p.hunger = meal ? 0 : Math.max(0, p.hunger - .45);
  release(p, seat);
  if (kind === "plate" || kind === "salad") { p.hold = { R: "plate" }; yield* dishes(p); return; }
  if (kind === "apple") { p.hold = {}; }
  const b = claim(p, "bin"); if (!b) { p.hold = {}; return; }
  p.hold = kind === "apple" ? {} : { R: kind === "takeout" ? "takeout" : kind };
  yield* go(p, b); yield* act(p, "reach", .9); p.hold = {}; release(p, b);
}
function partnerFor(p) {
  const c = [...people.values()].filter(q => q !== p && q.mode === "idle" && !q.conv && !q.rally && (!q.co || q.interruptible) && !q.path.length);
  c.sort((a, b) => Math.hypot(a.x - p.x, a.y - p.y) - Math.hypot(b.x - p.x, b.y - p.y));
  return c[0] || null;
}
function* chat(p) {
  const q = partnerFor(p); if (!q) return;
  const places = [];
  if (!SLOTS.coolerA[0].by && !SLOTS.coolerB[0].by) places.push([SLOTS.coolerA[0], SLOTS.coolerB[0], "water"]);
  for (const g of ["patioA", "patioB"]) { const s = SLOTS[g]; if (!s[0].by && !s[2].by) places.push([s[0], s[2]]); if (!s[1].by && !s[3].by) places.push([s[3], s[1]]); }
  if (!SLOTS.dine[0].by && !SLOTS.dine[1].by) places.push([SLOTS.dine[0], SLOTS.dine[1]]);
  if (!SLOTS.dine[2].by && !SLOTS.dine[3].by) places.push([SLOTS.dine[2], SLOTS.dine[3]]);
  const pl = pick(places); if (!pl) return;
  const conv = { a: p, b: q, speaker: p, end: T + rnd(35, 90), laugh: 0, ready: 0, next: 0 };
  stop(q); claimSlot(p, pl[0]); claimSlot(q, pl[1]); q.activity = "chat";
  q.co = convo(q, conv, pl[1], false, null); q.wait = null;
  yield* convo(p, conv, pl[0], true, pl[2]);
}
function* convo(p, conv, slot, lead, water) {
  p.conv = conv;
  yield* go(p, slot);
  if (water) { p.dir = "NE"; yield* act(p, "reach", 1.0); p.hold = { R: "cup" }; p.dir = slot.dir; }
  conv.ready++; setClip(p, "idle");
  yield { until: () => conv.ready >= 2 || conv.dead || T > conv.end };
  conv.end = Math.max(conv.end, T + 25);
  while (T < conv.end && !conv.dead) {
    if (lead && T > conv.next) { conv.speaker = Math.random() < .5 ? conv.a : conv.b; conv.next = T + rnd(3, 7);
      if (Math.random() < .14) conv.laugh = T + 2.2; bubble(conv.speaker); }
    setClip(p, T < conv.laugh ? "laugh" : conv.speaker === p ? "talk" : "listen");
    yield { dur: .25 };
  }
  p.social = 0; p.conv = null; p.hold = {}; release(p, slot);
}
function* pong(p) {
  const q = partnerFor(p); if (!q || SLOTS.pong.some(s => s.by)) return;
  stop(q); claimSlot(p, SLOTS.pong[0]); claimSlot(q, SLOTS.pong[1]); q.activity = "pong";
  const r = { a: p, b: q, ready: 0, end: T + rnd(45, 110), leg: 0, from: 0, t0: 0, dur: .95, dead: false, pause: 0 };
  q.co = rally(q, r, SLOTS.pong[1], 1); q.wait = null;
  yield* rally(p, r, SLOTS.pong[0], 0);
}
function* rally(p, r, slot, side) {
  p.rally = r; yield* go(p, slot); p.hold = { R: "paddle" }; r.ready++;
  setClip(p, "paddle"); yield { until: () => r.ready >= 2 || r.dead };
  if (side === 0) { r.t0 = T; r.from = 0; }
  while (T < r.end && !r.dead) { setClip(p, "paddle"); yield { dur: .3 }; }
  if (side === 0) { r.dead = true; OBJ.ball = null; }
  p.social = 0; p.rally = null; p.hold = {}; release(p, slot);
  yield* act(p, "laugh", 1.2);
}
function rallyStep() {
  const r = OBJ.rally; if (!r) return;
  if (r.dead || r.ready < 2) { OBJ.ball = null; if (r.dead) OBJ.rally = null; return; }
  const A = [10.15, 10.35, .95], B = [12.25, 10.35, .95];
  if (T < r.pause) { OBJ.ball = null; return; }
  let u = (T - r.t0) / r.dur;
  if (u >= 1) {
    if (Math.random() < .12) { r.pause = T + 2; r.t0 = T + 2; r.from = Math.random() < .5 ? 0 : 1; bubble(Math.random() < .5 ? r.a : r.b, "!"); OBJ.ball = null; return; }
    r.t0 += r.dur; r.from = 1 - r.from; r.wob = rnd(-.25, .25); u = (T - r.t0) / r.dur;
    (r.from ? r.b : r.a).hitAt = T;
  }
  const s = r.from ? B : A, e = r.from ? A : B, x = lerp(s[0], e[0], u), y = lerp(s[1], e[1], u) + (r.wob || 0) * Math.sin(Math.PI * u);
  const z = u < .62 ? lerp(.95, .755, u / .62) + Math.sin(Math.PI * u / .62) * .38 : lerp(.755, .95, (u - .62) / .38) + Math.sin(Math.PI * (u - .62) / .38) * .26;
  OBJ.ball = { x, y, z };
  for (const [pl, isTarget] of [[r.a, r.from === 1], [r.b, r.from === 0]]) {
    const since = T - (pl.hitAt || -9);
    pl.swing = since < .35 ? .5 + .5 * since / .35 : isTarget ? .5 * clamp((u - .5) / .5, 0, 1) : 0;
  }
}
function* nap(p) {
  const n = SLOTS.nap[0]; if (n.by || SLOTS.sofa2.some(s => s.by)) return;
  claimSlot(p, n); SLOTS.sofa2.forEach(s => claimSlot(p, s));
  yield* go(p, SLOTS.sofa2[0]); yield* act(p, "yawn", 2);
  p.x = n.x; p.y = n.y; p.lying = true; p.seated = false; p.lieAng = n.lieAng; p.z = n.z; p.napping = true;
  yield* act(p, "nap", 60, 150);
  p.napping = false; p.lying = false; p.seated = true; p.x = SLOTS.sofa2[0].x; p.y = SLOTS.sofa2[0].y; p.z = 0; p.dir = "NE";
  yield* act(p, "stretch", 2.8); p.energy = 1; releaseAll(p);
}
function* phoneTime(p) {
  const s = claimNear(p, pick([["sofa", "sofa2"], ["rail", "counter", "window"], ["patioA", "patioB"], ["dine"]]));
  yield* go(p, s || loiter(p)); p.hold = { R: "phone" }; p.interruptible = true;
  for (const end = T + rnd(25, 80); T < end;) { yield* act(p, "phone", 6, 14); if (Math.random() < .3) yield* act(p, "laugh", 1.1); }
  p.interruptible = false; p.hold = {}; release(p, s);
}
function* gaze(p) {
  const s = claimNear(p, ["window", "rail"]); if (!s) return;
  yield* go(p, s); p.interruptible = true; yield* act(p, "gaze", 25, 70); if (Math.random() < .3) yield* act(p, "stretch", 2.8);
  p.interruptible = false; release(p, s);
}
function* smoke(p) {
  const s = claim(p, "smoke"); if (!s) return;
  yield* go(p, s); p.hold = { R: "cig", L: "lighter" }; yield* act(p, "light", 1.4); p.hold = { R: "cig" };
  p.interruptible = true;
  yield* act(p, "smoke", 35, 80);
  p.interruptible = false; yield* act(p, "reach", .9); p.hold = {}; release(p, s);
}
function* stretch(p) { yield* go(p, loiter(p)); yield* act(p, "stretch", 2.8); yield* act(p, "idle", 2, 4); }
function* waterPlants(p) {
  const c = claim(p, "can"); if (!c || OBJ.can.held) return;
  yield* go(p, c); yield* act(p, "reach", .9); OBJ.can.held = true; p.hold = { R: "can" }; release(p, c);
  const thirsty = SLOTS.plant.filter(s => !s.by).sort((a, b) => a.plant.watered - b.plant.watered).slice(0, rnd(2, 4) | 0);
  for (const s of thirsty) { if (!claimSlot(p, s)) continue; yield* go(p, s); yield* act(p, "water", 3, 4.5); s.plant.watered = T; release(p, s); }
  const back = claim(p, "can"); yield* go(p, back || SLOTS.can[0]); yield* act(p, "reach", .9); OBJ.can.held = false; p.hold = {}; release(p, back);
}
function* doodle(p) {
  const s = claim(p, "whiteboard"); if (!s) return;
  yield* go(p, s); p.marker = pick(["#e63946", "#1d3557", "#2a9d8f", "#f4a261"]); p.hold = { R: "marker" };
  if (OBJ.board.strokes.length > 18) { yield* act(p, "erase", 3); OBJ.board.strokes = []; }
  p.interruptible = true;
  for (const end = T + rnd(20, 45); T < end;) { yield* act(p, "draw", 1.6, 3); OBJ.board.strokes.push(scribble(p.marker)); if (OBJ.board.strokes.length > 24) OBJ.board.strokes.shift(); }
  p.interruptible = false; p.hold = {}; release(p, s);
}
function scribble(col) {                                   // small marks: handwriting, boxes, arrows, a chart line
  const u = rnd(.06, .78), v = rnd(.12, .82), k = Math.floor(rnd(0, 5)), pts = [];
  if (k === 0) for (let i = 0; i < 8; i++) pts.push([u + i * .018, v + Math.sin(i * 1.9) * .02]);
  else if (k === 1) pts.push([u, v], [u + .1, v], [u + .1, v + .09], [u, v + .09], [u, v]);
  else if (k === 2) pts.push([u, v + .08], [u + .12, v], [u + .09, v - .01], [u + .12, v], [u + .115, v + .03]);
  else if (k === 3) for (let i = 0; i < 12; i++) pts.push([u + .05 + Math.cos(i / 1.8) * .05, v + .05 + Math.sin(i / 1.8) * .05]);
  else { let y = v; for (let i = 0; i < 5; i++) { pts.push([u + i * .03, y]); y += rnd(-.04, .04); } }
  return { col, pts };
}
function* read(p) {
  const b = claim(p, "books"); if (!b) return;
  yield* go(p, b); yield* act(p, "reach", 1.1); p.bookColor = pick(["#e76f51", "#2a9d8f", "#e9c46a", "#5a7bbf", "#8d6cab"]); p.hold = { R: "book" }; release(p, b);
  const s = claimNear(p, pick([["sofa", "sofa2"], ["patioA", "patioB"], ["window"], ["dine"]])) || claimNear(p, ["sofa", "sofa2", "dine"]);
  yield* go(p, s || loiter(p)); p.interruptible = true; yield* act(p, "read", 60, 150); p.interruptible = false; release(p, s);
  const b2 = claim(p, "books"); yield* go(p, b2 || SLOTS.books[0]); yield* act(p, "reach", 1); p.hold = {}; release(p, b2);
}
function* sunbathe(p) {
  const s = claim(p, "lounger"); if (!s) return;
  yield* go(p, s); p.interruptible = true; yield* act(p, "sunbathe", 60, 160); p.energy = Math.min(1, p.energy + .3);
  p.interruptible = false; p.lying = false; yield* act(p, "stretch", 2.8); release(p, s);
}
const IDLE = {
  coffee: [p => 1 + 2.2 * (1 - p.energy), () => free("coffee") || free("coffeeQ"), coffee],
  lunch: [p => .2 + 3.2 * p.hunger, () => free("fridge"), p => food(p, true)],
  snack: [p => .3 + 1.3 * p.hunger, () => free("fridge"), p => food(p, false)],
  chat: [p => .4 + 2.6 * p.social, p => !!partnerFor(p), chat],
  pong: [p => .25 + 1.5 * p.social, p => !!partnerFor(p) && !SLOTS.pong.some(s => s.by), pong],
  nap: [p => 1.9 * (1 - p.energy) - .35, () => !SLOTS.nap[0].by && !SLOTS.sofa2.some(s => s.by), nap],
  phone: [() => .8, () => true, phoneTime],
  gaze: [() => .7, () => free("window") || free("rail"), gaze],
  smoke: [p => p.look.smoker ? 1.1 : 0, () => free("smoke"), smoke],
  stretch: [() => .3, () => true, stretch],
  water: [() => OBJ.plants.some(pl => T - pl.watered > 900) ? .4 : 0, () => free("can") && !OBJ.can.held, waterPlants],
  whiteboard: [() => .5, () => free("whiteboard"), doodle],
  read: [() => .55, () => free("books"), read],
  sun: [() => nightness() < .2 ? .7 : 0, () => free("lounger"), sunbathe],
};
const SETTLED = ["phone", "gaze", "read", "chat", "smoke", "sun", "whiteboard", "pong", "drink"];
function* drink(p) { p.hold = { R: "mug" }; p.hotSince = T - 60; yield* withDrink(p); }
function startIdle(p) {
  if (p.teleport) {                                       // first sight of the floor: people mid-break, spread out, not queuing at the fridge
    const k = pick(SETTLED.filter(k => k === "drink" || (IDLE[k][1](p) && IDLE[k][0](p) > 0)));
    p.activity = k === "drink" ? "coffee" : k; p.recent = [p.activity]; start(p, k === "drink" ? drink(p) : IDLE[k][2](p)); return;
  }
  const opts = Object.entries(IDLE).map(([k, [w, ok, fn]]) => [k, Math.max(0, w(p)) * (p.recent.includes(k) ? .25 : 1), ok, fn]).filter(o => o[1] > 0 && o[2](p));
  let r = Math.random() * opts.reduce((s, o) => s + o[1], 0), c = opts.find(o => (r -= o[1]) < 0) || opts[0];
  if (!c) { start(p, stretch(p)); return; }
  p.recent = [c[0], ...p.recent].slice(0, 2); p.activity = c[0];
  start(p, c[3](p));
}

// ── work: the true part
function* deskWork(p, slot) {
  yield* go(p, slot); const d = slot.desk;
  if (d) { d.busy = p; d.mug = true; d.mugColor = p.look.mug; p.onStop.push(() => { d.busy = null; d.typing = false; d.mug = false; }); }
  for (;;) {
    const r = Math.random(); if (d) d.typing = false;
    if (r < .42) { if (d) d.typing = true; yield* act(p, "type", 5, 14); }
    else if (r < .54) yield* act(p, "mouse", 3, 6);
    else if (r < .62) { if (d) d.typing = true; yield* act(p, "glance", 2, 2.4); }
    else if (r < .70) yield* act(p, "leanback", 3, 5);
    else if (r < .79) yield* act(p, "think", 3, 6);
    else if (r < .9) { if (d) d.mug = false; p.hold = { R: "mug" }; yield* act(p, "sip", 2.2); p.hold = {}; if (d) d.mug = true; }
    else yield* act(p, "deskstretch", 2.5);
  }
}
function* reviewWork(p, slot) {
  yield* go(p, slot); p.hold = { L: "paper" };
  for (;;) { const r = Math.random();
    if (r < .55) yield* act(p, "review", 6, 10); else if (r < .8) yield* act(p, "think", 3, 5); else { p.hold = { R: "mug" }; yield* act(p, "sip", 2.2); p.hold = { L: "paper" }; } }
}
function* callWork(p, slot) {
  yield* go(p, slot); const b = slot.booth; if (b) { b.busy = true; p.onStop.push(() => b.busy = false); }
  if (!b) { yield* deskWork(p, slot); return; }
  p.hold = { R: "phone" };
  for (;;) yield* act(p, Math.random() < .7 ? "call" : "wait", 4, 10);
}
function* ceoWork(p, slot) {
  yield* go(p, slot); const lap = slot === BOARD.back[1];
  if (lap) { OBJ.laptop.open = 1; OBJ.laptop.glow = 1; p.onStop.push(() => { OBJ.laptop.open = 0; OBJ.laptop.glow = 0; }); }
  for (;;) { const r = Math.random();
    if (r < .45) yield* act(p, "type", 4, 9); else if (r < .7) yield* act(p, "gesture", 3, 6); else if (r < .88) yield* act(p, "think", 3, 5);
    else { p.hold = { R: "mug" }; yield* act(p, "sip", 2.2); p.hold = {}; } }
}
function placeWork(p) {
  stop(p); const m = p.mode;
  if (m === "ceo") { const s = claim(p, "ceo", 0) || claim(p, "board") || claim(p, "review"); start(p, ceoWork(p, s || loiter(p))); return; }
  if (m === "review") { const s = claim(p, "review") || claim(p, "board"); start(p, reviewWork(p, s || loiter(p))); return; }
  if (m === "call") { const s = claim(p, "booth") || claim(p, "desk", p.deskIdx) || claim(p, "board"); start(p, callWork(p, s || loiter(p))); return; }
  const s = claim(p, "desk", p.deskIdx) || claim(p, "board") || claim(p, "review");
  if (s && s.desk) p.deskIdx = s.desk.i;
  start(p, deskWork(p, s || loiter(p)));
}

// ── truth from the hub
function want(a) {
  const short = (s, n = 40) => { s = String(s || "").replace(/\s+/g, " ").trim(); if (s.length <= n) return s; const cut = s.slice(0, n); return cut.slice(0, cut.lastIndexOf(" ") > n * .6 ? cut.lastIndexOf(" ") : n) + "…"; };
  const f = a.focus || {};
  const flag = { unresponsive: "not answering", login: "login expired", parked: "parked" }[a.state] || null;
  if (flag) return { mode: "idle", flag, key: "idle!" + flag, card: null };
  if (a.kind === "slack") return { mode: "ceo", key: "ceo", card: (seatsOf(a.name).join(" · ") || "via Slack") + (a.queue ? ` · ${a.queue} waiting` : "") };
  if (a.task && a.task.status === "verifying") return { mode: "review", key: "review#" + a.task.id, card: short(`checking #${a.task.id} ${a.task.title}`) };
  if (a.task || f.task) { const t = a.task || f.task; return { mode: "work", key: "work#" + t.id, card: short(`#${t.id} ${t.title}`) }; }
  if (f.doing) return { mode: "work", key: "work:" + f.doing, card: short(f.doing) };
  if (a.current) return { mode: "call", key: "call#" + a.current.id, card: "↩ " + short(a.current.text, 34) };
  return { mode: "idle", key: "idle", card: null };
}
let events = [], first = true, lastBoard = null;
function update(b) {
  lastBoard = b;
  const seen = new Set();
  for (const a of b.agents || []) {
    seen.add(a.name);
    const w = want(a);
    let p = people.get(a.name), isNew = !p;
    if (!p) {
      p = { name: a.name, look: look(a.name), seed: hash(a.name) % 1000, x: 1.5, y: 5.2, z: 0, dir: "SE", path: [], clip: "idle", clipT: 0,
        hold: {}, claims: new Set(), onStop: [], recent: [], pose: { ...STAND }, teleport: true, mode: null, key: null,
        hunger: rnd(0, .6), energy: rnd(.35, 1), social: rnd(0, .6) };
      people.set(a.name, p);
    }
    p.a = a; p.card = w.card; p.flag = w.flag;
    if (p.key === w.key) continue;
    if (!isNew && !first) {
      const n = a.name, was = p.key || "";
      const line = w.flag ? `${n} stopped answering (${w.flag})` : was.startsWith("idle!") && w.mode === "idle" ? `${n} is back`
        : w.mode === "idle" ? `${n} finished and took a break` : w.mode === "work" ? `${n} sat down to ${w.card}`
        : w.mode === "review" ? `${n} started ${w.card}` : w.mode === "call" ? `${n} is replying to #${a.current.id}` : `${n}: ${w.card}`;
      events.unshift({ at: b.now, line, who: n }); events = events.slice(0, 6);
      p.pulse = T;
    }
    const modeChanged = p.mode !== w.mode;
    p.key = w.key; p.mode = w.mode;
    if (w.mode === "idle") { if (modeChanged) { stop(p); } }       // the idle chooser picks up next frame
    else placeWork(p);
  }
  for (const [n, p] of people) if (!seen.has(n)) { stop(p); people.delete(n); }
  first = false;
}

// ── per-frame sim step
function simStep(dt) {
  T += dt;
  const M = OBJ.coffee; if (M.state === "brewing" && T > M.t) { M.state = "ready"; M.level = 1; }
  if (M.state === "brewing" && Math.random() < dt * 6) part({ kind: "steam", ...wpt(.35, 6.3, 1.5), vx: rnd(-2, 2), vy: -8 });
  for (const o of [OBJ.fridge, OBJ.micro]) o.open = lerp(o.open, o.target, 1 - Math.exp(-dt * 6));
  if (OBJ.micro.run && Math.random() < dt * 2) part({ kind: "steam", ...wpt(.4, 8.6, 1.32), vx: rnd(-1, 1), vy: -6 });
  OBJ.leftovers = OBJ.leftovers.filter(l => T < l.until);
  rallyStep();
  for (const p of people.values()) {
    p.hunger = Math.min(1, p.hunger + dt / 700); p.social = Math.min(1, p.social + dt / 800);
    p.energy = Math.max(0, p.energy - dt / (p.mode === "idle" ? 1100 : 650));
    if (p.mode === "idle" && !p.co) startIdle(p);
    run(p);
    if (p.rally && !OBJ.rally) OBJ.rally = p.rally;
    // walk along the path, easing around corners, keeping a little personal space
    if (p.path.length) {
      const [tx, ty] = p.path[0], dx = tx - p.x, dy = ty - p.y, dist = Math.hypot(dx, dy), sp = (p.hold.R || p.hold.L ? 1.15 : 1.35) * dt;
      if (dist <= sp) { p.x = tx; p.y = ty; p.path.shift(); }
      else {
        let mx = dx / dist * sp, my = dy / dist * sp;
        for (const q of people.values()) { if (q === p) continue; const ox = p.x - q.x, oy = p.y - q.y, d = Math.hypot(ox, oy);
          if (d < .5 && d > 1e-3 && p.path.length > 1) { mx += ox / d * (.5 - d) * dt * 2.5; my += oy / d * (.5 - d) * dt * 2.5; } }
        if (walkable(p.x + mx, p.y + my) || p.path.length <= 1) { p.x += mx; p.y += my; } else { p.x += dx / dist * sp; p.y += dy / dist * sp; }
        if (Math.abs(dx) > .01 || Math.abs(dy) > .01) p.dir = Math.abs(dx) >= Math.abs(dy) ? (dx > 0 ? "SE" : "NW") : (dy > 0 ? "SW" : "NE");
      }
      setClip(p, "walk");
    }
    p.clipT += dt;
    const base = p.lying ? { ...STAND, lie: 1 } : p.seated ? SIT : STAND;
    const tgt = (CLIPS[p.clip] || CLIPS.idle)(p.clipT, p, base, p.hold);
    if (p.slot && p.slot.lean && !p.seated && p.clip === "hold") tgt.lean = -3;
    p.pose = lerpPose(p.pose, tgt, 1 - Math.exp(-dt * (p.clip === "walk" ? 18 : 9)));
    if (p.napping && Math.random() < dt * .7) part({ kind: "z", wx: 0, wy: 0, follow: p });
  }
  for (const s of PARTS) { s.x += (s.vx || 0) * dt; s.y += (s.vy || 0) * dt; s.vy = (s.vy || 0) + (s.g || 0) * dt; }
  for (let i = PARTS.length - 1; i >= 0; i--) if (T - PARTS[i].born > (PARTS[i].life || 2.5)) PARTS.splice(i, 1);
}
const wpt = (x, y, z) => { const [a, b] = P(x, y, z); return { x: a, y: b }; };
function bubble(p, glyph) { if (!p) return; part({ kind: "bubble", follow: p, glyph: glyph || pick(["…", "!", "?", "♪", "☺", "♥", "ha", "→", "✓"]), life: 2.2 }); }

// ───────────────────────────── rendering ─────────────────────────────
let cv, ctx, wrap, hudEl, tipEl, tickEl, DPR = 1, W = 1, H = 1, cam = { s: 1, tx: 0, ty: 0 }, cache = null, hits = [], hover = null, FDT = 0;
const BB = { x0: wx(0, Y) - 20, x1: wx(X, 0) + 20, y0: wy(0, 0, 2.75) - 46, y1: wy(X, Y, -.55) };
function nightness(t = Date.now() / 1000) {
  const p = HOUR != null ? HOUR : (t % 3600) / 3600, f = .05, s = ease;
  return p < .5 - f ? 0 : p < .5 ? s((p - (.5 - f)) / f) : p < 1 - f ? 1 : 1 - s((p - (1 - f)) / f);
}
function phaseText(t = Date.now() / 1000) {
  const p = HOUR != null ? HOUR : (t % 3600) / 3600, m = Math.max(1, Math.ceil(((p < .5 ? .5 : 1) - p) * 60));
  return p < .5 ? `☀ Day · dusk in ${m}m` : `☾ Night · dawn in ${m}m`;
}
function layout() {
  const r = wrap.getBoundingClientRect(); DPR = Math.min(2, window.devicePixelRatio || 1);
  if (!r.width || !r.height) return;
  W = Math.round(r.width * DPR); H = Math.round(r.height * DPR); cv.width = W; cv.height = H;
  const s = Math.min(W / (BB.x1 - BB.x0), H / (BB.y1 - BB.y0));
  cam = { s, tx: W / 2 - s * (BB.x0 + BB.x1) / 2, ty: H / 2 - s * (BB.y0 + BB.y1) / 2 + (H - s * (BB.y1 - BB.y0)) * .18 };
  cache = null;
}
const toScreen = ([x, y]) => [cam.tx + x * cam.s, cam.ty + y * cam.s];
const worldT = g => g.setTransform(cam.s, 0, 0, cam.s, cam.tx, cam.ty);

// ── caches: static sprites per item, the base (floor, walls, building), the city day+night
function buildCache() {
  const mk = (w, h) => { const c = document.createElement("canvas"); c.width = Math.max(1, Math.ceil(w)); c.height = Math.max(1, Math.ceil(h)); return c; };
  const sprites = new Map();
  for (const it of ITEMS) if (it.draw) {
    const [x, y, w, d] = it.fp, pts = [];
    for (const [a, b] of [[x, y], [x + w, y], [x, y + d], [x + w, y + d]]) for (const z of [it.z0, it.z1]) pts.push(P(a, b, z));
    const x0 = Math.min(...pts.map(p => p[0])) - it.pad, x1 = Math.max(...pts.map(p => p[0])) + it.pad;
    const y0 = Math.min(...pts.map(p => p[1])) - it.pad, y1 = Math.max(...pts.map(p => p[1])) + it.pad;
    const c = mk((x1 - x0) * cam.s, (y1 - y0) * cam.s), g = c.getContext("2d");
    g.setTransform(cam.s, 0, 0, cam.s, -x0 * cam.s, -y0 * cam.s); it.draw(g);
    sprites.set(it, { c, dx: Math.round(cam.tx + x0 * cam.s), dy: Math.round(cam.ty + y0 * cam.s) });
  }
  const base = mk(W, H), bg = base.getContext("2d"); worldT(bg); drawBase(bg);
  const city = [0, 1].map(night => { const c = mk(W, H); drawCity(c.getContext("2d"), night); return c; });
  cache = { sprites, base, city };
}
function drawBase(g) {
  // the tower: our floor's slab and one storey of facade below it (a cutaway; the city shows beneath)
  box(g, 0, 0, -1.35, X, Y, 1.05, C.facade, { hl: false });
  for (let fx = .3; fx < X - .5; fx += .9) poly(g, [P(fx, Y, -1.22), P(fx + .62, Y, -1.22), P(fx + .62, Y, -.45), P(fx, Y, -.45)], C.facadeWin);
  for (let fy = .3; fy < Y - .5; fy += .9) poly(g, [P(X, fy, -1.22), P(X, fy + .62, -1.22), P(X, fy + .62, -.45), P(X, fy, -.45)], shade(C.facadeWin, -.12));
  line(g, [P(0, Y, -1.35), P(X, Y, -1.35), P(X, 0, -1.35)], "rgba(60,70,80,.35)", 1.5);
  box(g, -.05, -.05, -.32, X + .1, Y + .1, .32, C.slab);
  // floors, by room
  const zone = (x, y) => x >= 14 ? "deck" : y < 5.6 ? (x < 9.6 ? "carpet" : y < 4.6 ? "board" : "review") : x < 5.1 ? "tile" : x < 9.6 ? "plank" : "review";
  for (let y = 0; y < Y - .01; y += .5) for (let x = 0; x < X - .01; x += .5) {
    const z = zone(x + .25, y + .25), i = Math.round(x * 2), j = Math.round(y * 2), alt = (i + j) % 2;
    const c = z === "carpet" ? (alt ? C.carpet : C.carpet2) : z === "board" ? (alt ? C.board : C.board2) : z === "tile" ? (alt ? C.tile : C.tile2)
      : z === "review" ? (alt ? C.review : C.review2) : z === "plank" ? shade(C.plank, ((hash(i * 7 + j * 3) % 7) - 3) * .012) : shade(C.deck, ((hash(i * 5 + j) % 7) - 3) * .015);
    poly(g, [P(x, y), P(x + .5, y), P(x + .5, y + .5), P(x, y + .5)], c);
  }
  for (let y = 5.6; y < Y; y += .25) line(g, [P(5.1, y), P(9.6, y)], "rgba(90,60,30,.12)", .6);           // lounge planks
  for (let x = 14; x < X; x += .25) line(g, [P(x, 0), P(x, Y)], "rgba(60,35,15,.22)", .7);              // deck boards
  for (let y = .5; y < Y; y += 1.5) for (let x = 14; x < X; x += .25) if ((hash(x * 40 + y) % 3) === 0) line(g, [P(x, y), P(x + .25, y)], "rgba(60,35,15,.2)", .6);
  // rugs
  poly(g, [P(6.45, 7.3), P(8.75, 7.3), P(8.75, 9.75), P(6.45, 9.75)], C.rugEdge); poly(g, [P(6.6, 7.45), P(8.6, 7.45), P(8.6, 9.6), P(6.6, 9.6)], C.rug);
  for (let k = 0; k < 3; k++) poly(g, [P(6.9 + k * .02, 7.75 + k * .4), P(8.3, 7.75 + k * .4), P(8.3, 7.85 + k * .4), P(6.9 + k * .02, 7.85 + k * .4)], "rgba(200,120,80,.25)");
  poly(g, [P(9.85, 1.0), P(13.55, 1.0), P(13.55, 3.15), P(9.85, 3.15)], "rgba(141,108,171,.16)");
  for (const by of [6.9, 8.2]) poly(g, [P(12.8, by), P(13.85, by), P(13.85, by + 1.1), P(12.8, by + 1.1)], "#cfd5dc");
  // contact shadows: soft, under everything that stands on the floor
  g.save(); if ("filter" in g) g.filter = `blur(${Math.max(1, 3 * cam.s)}px)`;
  for (const [x, y, w, d, a] of SHADOWS) poly(g, [P(x - .05, y - .02), P(x + w + .12, y - .02), P(x + w + .12, y + d + .12), P(x - .05, y + d + .12)], `rgba(30,35,45,${a})`);
  g.restore();
  // back walls: windows with mullions on the city, the whiteboard, the boardroom screen, kitchen cabinets, a clock
  box(g, -.22, -.22, 0, 14.22, .22, 2.75, C.wall, { hl: false }); box(g, -.22, 0, 0, .22, Y, 2.75, C.wall, { hl: false });
  const winY = (x0, x1) => { poly(g, [P(x0, 0, .55), P(x1, 0, .55), P(x1, 0, 2.4), P(x0, 0, 2.4)], C.winFrame);
    const gl = [P(x0 + .05, 0, .6), P(x1 - .05, 0, .6), P(x1 - .05, 0, 2.35), P(x0 + .05, 0, 2.35)], [, ya] = gl[3], [, yb] = gl[0];
    const gr = g.createLinearGradient(0, ya, 0, yb); gr.addColorStop(0, "#b7dcf3"); gr.addColorStop(1, "#e3f2fb"); poly(g, gl, gr);
    for (let x = x0 + .5; x < x1 - .1; x += .5) line(g, [P(x, 0, .6), P(x, 0, 2.35)], C.winFrame, 1.2);
    line(g, [P(x0, 0, 1.55), P(x1, 0, 1.55)], C.winFrame, 1); line(g, [P(x0 + .2, 0, .8), P(x0 + .6, 0, 2.1)], "rgba(255,255,255,.55)", 2); };
  const winX = (y0, y1) => { poly(g, [P(0, y0, .55), P(0, y1, .55), P(0, y1, 2.4), P(0, y0, 2.4)], C.winFrame);
    const gl = [P(0, y0 + .05, .6), P(0, y1 - .05, .6), P(0, y1 - .05, 2.35), P(0, y0 + .05, 2.35)], gr = g.createLinearGradient(0, gl[3][1], 0, gl[0][1]);
    gr.addColorStop(0, "#acd3ec"); gr.addColorStop(1, "#d9edf8"); poly(g, gl, gr);
    for (let y = y0 + .5; y < y1 - .1; y += .5) line(g, [P(0, y, .6), P(0, y, 2.35)], C.winFrame, 1.2);
    line(g, [P(0, y0, 1.55), P(0, y1, 1.55)], C.winFrame, 1); };
  winY(.3, 3.0); winY(4.8, 9.4); winY(9.75, 10.45); winY(12.95, 13.9); winX(.3, 5.3);
  poly(g, [P(3.15, 0, .85), P(4.65, 0, .85), P(4.65, 0, 2.0), P(3.15, 0, 2.0)], "#9aa3ab");
  poly(g, [P(3.2, 0, .9), P(4.6, 0, .9), P(4.6, 0, 1.95), P(3.2, 0, 1.95)], "#fbfcfd");
  poly(g, [P(3.15, .02, .82), P(4.65, .02, .82), P(4.65, .1, .85), P(3.15, .1, .85)], "#9aa3ab");
  poly(g, [P(10.55, 0, .95), P(12.85, 0, .95), P(12.85, 0, 1.98), P(10.55, 0, 1.98)], "#1c2027");
  for (let y = 5.95; y < 9.9; y += 1.0) { box(g, 0, y, 1.55, .32, .98, .72, C.white, { hl: false });
    const s = onR(0, y, 1.55, .32, .98, .72); line(g, [s(.5, .05), s(.5, .95)], "rgba(0,0,0,.12)", .7); line(g, [s(.45, .2), s(.45, .35)], "#8c959e", 1.2); line(g, [s(.55, .2), s(.55, .35)], "#8c959e", 1.2); }
  for (let y = 5.95; y < 9.9; y += .2) line(g, [P(0, y, .92), P(0, y, 1.55)], "rgba(0,0,0,.06)", .6);
  const [cx, cy] = P(0, 10.68, 2.38); g.fillStyle = "#fff"; g.strokeStyle = "#3b414a"; g.lineWidth = 1.4; g.beginPath(); g.ellipse(cx, cy, 6, 7.5, -.45, 0, 7); g.fill(); g.stroke();
  // room names on small wall plaques
  const plaque = (t, x, y, z, onX) => { g.save(); const [px, py] = P(x, y, z); g.translate(px, py); g.transform(1, onX ? -.5 : .5, 0, 1, 0, 0);
    g.font = "700 6.5px system-ui,sans-serif"; const w = g.measureText(t).width + 8; g.fillStyle = "rgba(40,46,56,.78)"; g.beginPath(); g.roundRect(0, -8, w, 10, 2); g.fill();
    g.fillStyle = "#fff"; g.fillText(t, 4, 0); g.restore(); };
  plaque("BOARDROOM", 13.95, 0, 2.62, false); plaque("PRODUCT FLOOR", 5.6, 0, 2.62, false); plaque("KITCHEN", 0, 5.65, 2.62, true);
}
function drawWalls(g) {
  for (const s of OBJ.board.strokes) line(g, s.pts.map(([u, v]) => P(3.25 + u * 1.3, .01, 1.9 - v * .95)), s.col, .8);
  const ceo = [...people.values()].find(p => p.mode === "ceo" && p.slot && !p.path.length);
  const scr = (u, v) => P(10.6 + u * 2.2, 0, 1.0 + v * .93);
  poly(g, quad(scr, 0, 0, 1, 1), ceo ? "#16263a" : "#20252d");
  if (ceo) {
    for (let i = 0; i < 6; i++) { const h = .2 + .5 * (.5 + .5 * Math.sin(T * .5 + i * 1.3)); poly(g, quad(scr, .08 + i * .075, .12, .13 + i * .075, .12 + h * .7), ["#5fb3e6", "#9fe0a6", "#f2cc8f"][i % 3]); }
    line(g, [scr(.58, .2), scr(.68, .45), scr(.78, .38), scr(.9, .75)], "#9fe0a6", 1.4);
    g.save(); const [tx, ty] = scr(.58, .92); g.translate(tx, ty); g.transform(1, .5, 0, 1, 0, 0); g.font = "600 5px system-ui"; g.fillStyle = "#cfe6ff"; g.fillText("FOUNDLINGS · LIVE", 0, 0); g.restore();
  } else { const [lx, ly] = scr(.5, .5); g.fillStyle = "rgba(160,190,220,.35)"; g.beginPath(); g.arc(lx, ly, 5, 0, 7); g.fill(); }
  const [cx, cy] = P(0, 10.68, 2.38), d = new Date(), hr = (d.getHours() % 12 + d.getMinutes() / 60) / 12 * Math.PI * 2, mn = d.getMinutes() / 60 * Math.PI * 2;
  line(g, [[cx, cy], [cx + Math.sin(hr) * 2.6, cy - Math.cos(hr) * 3.6]], "#222", 1.2); line(g, [[cx, cy], [cx + Math.sin(mn) * 3.8, cy - Math.cos(mn) * 5.4]], "#222", .8);
}
// ── the city, screen space, two moods; generated from a fixed seed so day and night line up
const SKY = [];
function drawCity(g, night) {
  let seed = 7; const r = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const base = H * .98, hz = cam.ty + wy(X, 0, 0) * cam.s;          // horizon roughly at the right corner of our floor
  SKY.length = 0;
  for (const [layer, col, top, minW, maxW, lit] of [[0, night ? "#141a33" : "#c3d5e2", .34, 30, 80, .18], [1, night ? "#1b2342" : "#a9c0d1", .5, 40, 110, .26]]) {
    for (let x = -20 * DPR; x < W + 20 * DPR;) {
      const w = (minW + r() * (maxW - minW)) * DPR, h = (H * (top + r() * .28)) * (layer ? .9 : 1), y = Math.min(hz + 40 * DPR, base) - h;
      g.fillStyle = col; g.fillRect(x, y, w - 3 * DPR, H - y);
      g.fillStyle = night ? "rgba(255,255,255,.04)" : "rgba(255,255,255,.18)"; g.fillRect(x, y, (w - 3 * DPR) * .18, H - y);
      for (let wy2 = y + 8 * DPR; wy2 < H; wy2 += 11 * DPR) for (let wx2 = x + 5 * DPR; wx2 < x + w - 10 * DPR; wx2 += 8 * DPR) {
        if (night) { if (r() < lit) { g.fillStyle = r() < .8 ? "rgba(255,206,120,.75)" : "rgba(180,220,255,.7)"; g.fillRect(wx2, wy2, 3 * DPR, 4 * DPR); } }
        else if (r() < .5) { g.fillStyle = "rgba(255,255,255,.22)"; g.fillRect(wx2, wy2, 3 * DPR, 4 * DPR); }
      }
      if (h > H * .55 && r() < .6) { g.fillStyle = col; g.fillRect(x + w / 2 - DPR, y - 18 * DPR, 2 * DPR, 18 * DPR); SKY.push([x + w / 2, y - 18 * DPR]); }
      x += w;
    }
  }
  const haze = g.createLinearGradient(0, hz - H * .1, 0, H); haze.addColorStop(0, "rgba(0,0,0,0)"); haze.addColorStop(1, night ? "rgba(10,14,30,.55)" : "rgba(235,244,250,.6)");
  g.fillStyle = haze; g.fillRect(0, 0, W, H);
}
const plane = { t0: -99 }, clouds = [0, 1, 2, 3].map(i => ({ x: Math.random(), y: .06 + i * .07, s: .7 + Math.random() * .8, v: .004 + Math.random() * .004 }));
function drawSky(g, n, now) {
  // everything here goes *behind* what's already drawn (destination-over), front-most first
  g.globalCompositeOperation = "destination-over";
  if (now - plane.t0 > 75) { plane.t0 = now; plane.y = H * (.06 + Math.random() * .12); plane.dir = Math.random() < .5 ? 1 : -1; }
  const pu = (now - plane.t0) / 40;
  if (pu < 1) { const px = plane.dir > 0 ? pu * W * 1.1 - W * .05 : W * 1.05 - pu * W * 1.1, py = plane.y;
    g.fillStyle = n > .5 ? "rgba(255,255,255,.0)" : "rgba(70,80,95,.7)"; g.fillRect(px - 9 * DPR, py, 18 * DPR, 2 * DPR); g.fillRect(px - 2 * DPR, py - 3 * DPR, 4 * DPR, 8 * DPR);
    if (Math.floor(now * 1.5) % 2) { g.fillStyle = "#ff4d4d"; g.beginPath(); g.arc(px + 9 * DPR * plane.dir, py, 1.6 * DPR, 0, 7); g.fill(); }
    g.fillStyle = "rgba(255,255,255,.9)"; if (Math.floor(now * 2.3) % 3 === 0) { g.beginPath(); g.arc(px - 9 * DPR * plane.dir, py, 1.3 * DPR, 0, 7); g.fill(); } }
  if (n > .2) for (const [x, y] of SKY) if ((Math.floor(now * .8 + x) % 3) === 0) { g.fillStyle = `rgba(255,60,60,${n})`; g.beginPath(); g.arc(x, y, 2 * DPR, 0, 7); g.fill(); }
  if (n > 0) { g.globalAlpha = n; g.drawImage(cache.city[1], 0, 0); g.globalAlpha = 1; }
  g.drawImage(cache.city[0], 0, 0);
  for (const c of clouds) { const x = ((c.x + now * c.v * .1) % 1.3 - .15) * W, y = c.y * H; g.fillStyle = `rgba(255,255,255,${.75 * (1 - n)})`;
    for (const [dx, dy, rr] of [[0, 0, 22], [20, 4, 16], [-18, 5, 15], [8, -8, 14]]) { g.beginPath(); g.ellipse(x + dx * c.s * DPR, y + dy * c.s * DPR, rr * c.s * DPR * 1.4, rr * c.s * DPR * .7, 0, 0, 7); g.fill(); } }
  const sunx = W * .9, suny = H * .13;
  if (n < 1) { g.globalAlpha = 1 - n; const sg = g.createRadialGradient(sunx, suny, 0, sunx, suny, 90 * DPR); sg.addColorStop(0, "rgba(255,248,220,1)"); sg.addColorStop(.25, "rgba(255,240,190,.8)"); sg.addColorStop(1, "rgba(255,240,190,0)");
    g.fillStyle = sg; g.fillRect(sunx - 90 * DPR, suny - 90 * DPR, 180 * DPR, 180 * DPR); g.globalAlpha = 1; }
  if (n > 0) { g.globalAlpha = n; g.fillStyle = "#f4f1e6"; g.beginPath(); g.arc(sunx, suny, 18 * DPR, 0, 7); g.fill(); g.fillStyle = "rgba(200,200,190,.5)"; g.beginPath(); g.arc(sunx - 5 * DPR, suny - 3 * DPR, 4 * DPR, 0, 7); g.fill();
    for (let i = 0; i < 120; i++) { g.fillStyle = `rgba(255,255,255,${.25 + (i * 37 % 60) / 100})`; g.fillRect((i * 173.3 * DPR) % W, (i * 97.7 * DPR) % (H * .45), 1.4 * DPR, 1.4 * DPR); }
    const ng = g.createLinearGradient(0, 0, 0, H); ng.addColorStop(0, "#060a1c"); ng.addColorStop(1, "#1d2650"); g.fillStyle = ng; g.fillRect(0, 0, W, H); g.globalAlpha = 1; }
  const dg = g.createLinearGradient(0, 0, 0, H); dg.addColorStop(0, "#9fd0ef"); dg.addColorStop(.6, "#d7ecf8"); dg.addColorStop(1, "#eef6fb"); g.fillStyle = dg; g.fillRect(0, 0, W, H);
  g.globalCompositeOperation = "source-over";
}
// ── night: grade the whole building down, then add light back
function drawNight(g, n) {
  if (n <= 0) return;
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "source-atop"; g.fillStyle = `rgba(10,14,34,${.72 * n})`; g.fillRect(0, 0, W, H);
  worldT(g); g.globalCompositeOperation = "source-atop";    // window glass goes dark: the night is outside
  const dark = `rgba(6,10,28,${.5 * n})`, wY = (a, b) => poly(g, [P(a, 0, .6), P(b, 0, .6), P(b, 0, 2.35), P(a, 0, 2.35)], dark);
  wY(.3, 3.0); wY(4.8, 9.4); wY(9.75, 10.45); wY(12.95, 13.9); poly(g, [P(0, .3, .6), P(0, 5.3, .6), P(0, 5.3, 2.35), P(0, .3, 2.35)], dark);
  g.globalCompositeOperation = "lighter";
  const glow = (x, y, r, rgb, a, sy = 1) => { g.save(); g.translate(x, y); g.scale(1, sy); const gr = g.createRadialGradient(0, 0, 0, 0, 0, r);
    gr.addColorStop(0, `rgba(${rgb},${a})`); gr.addColorStop(1, `rgba(${rgb},0)`); g.fillStyle = gr; g.fillRect(-r, -r, 2 * r, 2 * r); g.restore(); };
  for (const l of LIGHTS) {
    if (l.kind === "desk" && !(l.desk.busy)) continue;
    const [x, y] = P(l.x, l.y, l.z), [fx, fy] = P(l.x, l.y, 0);
    if (l.kind === "pendant") glow(fx, fy, l.r, l.col, .5 * n, .5);
    else if (l.kind === "floor") { glow(x, y, 16, l.col, .8 * n); glow(fx, fy, l.r, l.col, .42 * n, .5); }
    else if (l.kind === "desk") { glow(x, y, 8, l.col, .8 * n); glow(...P(l.x, l.y + .1, .72), l.r, l.col, .35 * n, .5); }
    else if (l.kind === "heater") { glow(x, y, 22, l.col, .9 * n); glow(fx, fy, l.r, l.col, .35 * n, .5); }
  }
  for (const d of DESKS) if (d.busy) glow(...P(d.x + .7, d.y + .35, 1.05), 44, "90,180,255", .3 * n, .8);
  if (OBJ.micro.run) glow(...P(.75, 8.65, 1.1), 26, "255,200,110", .55 * n);
  if (OBJ.fridge.open > .1) glow(...P(1.0, 10.6, .9), 50, "220,240,255", .45 * n * OBJ.fridge.open, .6);
  for (const b of BOOTHS) if (b.busy) glow(...P(13.3, b.y + 1.1, 2.1), 24, "60,230,140", .5 * n);
  if ([...people.values()].some(p => p.mode === "ceo")) glow(...P(11.7, 0, 1.45), 60, "120,180,255", .25 * n, .8);
  for (let t = 0; t <= 1.0001; t += 1 / 22) {                // string lights over the patio
    const [x, y] = t < .5 ? P(14.1 + t * 2 * (X - 14.2), Y - .05, 1.55 - Math.sin(t * 2 * Math.PI * 3) * .12) : P(X - .05, Y - .1 - (t - .5) * 2 * (Y - .3), 1.55 - Math.sin((t - .5) * 2 * Math.PI * 4) * .12);
    glow(x, y, 5, "255,214,140", .95 * n); glow(x, y + 4, 14, "255,190,110", .18 * n, .6); }
  for (const p of people.values()) if (p.handW && (p.hold.R === "phone" || p.hold.L === "phone")) glow(...p.handW[p.hold.R === "phone" ? "R" : "L"], 12, "120,190,255", .5 * n);
  for (let i = 0; i < 18; i++) { const fx = .3 + (hash(i * 13) % 22) * .9; if (fx > X - .6) continue; const lit = hash(i * 7) % 2;     // a few lit windows below us
    if (lit) { g.globalAlpha = .7 * n; poly(g, [P(fx, Y, -1.22), P(fx + .62, Y, -1.22), P(fx + .62, Y, -.45), P(fx, Y, -.45)], "rgb(120,90,40)"); g.globalAlpha = 1; } }
  g.globalCompositeOperation = "source-over";
}
function drawParticles(g) {
  worldT(g);
  for (const s of PARTS) {
    const age = (T - s.born) / (s.life || 2.5);
    if (s.kind === "steam" || s.kind === "smoke") { g.fillStyle = s.kind === "steam" ? `rgba(255,255,255,${.4 * (1 - age)})` : `rgba(205,208,214,${.55 * (1 - age)})`;
      g.beginPath(); g.arc(s.x + Math.sin(age * 6 + s.born) * 1.5, s.y, 1.4 + age * (s.kind === "smoke" ? 6 : 4), 0, 7); g.fill(); }
    else if (s.kind === "drop") { g.fillStyle = "rgba(90,160,230,.85)"; g.fillRect(s.x, s.y, 1, 1.8); }
    else if (s.kind === "z" && s.follow && s.follow.handW) { const [hx, hy] = s.follow.handW.head; g.globalAlpha = 1 - age; g.fillStyle = "#3d4a63";
      g.font = `700 ${6 + age * 4}px system-ui`; g.fillText("z", hx + 4 + age * 8, hy - 6 - age * 18); g.globalAlpha = 1; }
    else if (s.kind === "bubble" && s.follow && s.follow.handW) { const [hx, hy] = s.follow.handW.head, a = age < .1 ? age * 10 : age > .8 ? (1 - age) * 5 : 1;
      g.globalAlpha = a; g.fillStyle = "#fff"; g.strokeStyle = "rgba(0,0,0,.2)"; g.lineWidth = .6; g.beginPath(); g.roundRect(hx - 6, hy - 25, 13, 10, 4); g.fill(); g.stroke();
      g.beginPath(); g.moveTo(hx - 1, hy - 15.5); g.lineTo(hx + 1, hy - 12.5); g.lineTo(hx + 2.5, hy - 15.5); g.fill();
      g.fillStyle = "#333"; g.font = "700 6.5px system-ui"; g.textAlign = "center"; g.fillText(s.glyph, hx + .5, hy - 17.8); g.textAlign = "start"; g.globalAlpha = 1; }
  }
}
// ── one person, plus everything that hangs off them in world space (shadow, rings, particles from hands)
function drawPersonAt(g, p) {
  const [sx, sy] = P(p.x, p.y, p.z), [fx, fy] = P(p.x, p.y, p.lying ? p.z : 0);
  g.fillStyle = "rgba(25,30,40,.2)"; g.beginPath(); g.ellipse(fx, fy, p.lying ? 16 : 9, p.lying ? 6 : 4, 0, 0, 7); g.fill();
  if (p.flag) { const a = .55 + .3 * Math.sin(T * 4); g.strokeStyle = `rgba(214,48,49,${a})`; g.lineWidth = 1.6; g.beginPath(); g.ellipse(fx, fy, 12, 5.5, 0, 0, 7); g.stroke(); }
  if (p.pulse != null && T - p.pulse < 2) { const k = (T - p.pulse) / 2; g.strokeStyle = `rgba(90,162,255,${1 - k})`; g.lineWidth = 2; g.beginPath(); g.ellipse(fx, fy, 10 + k * 26, 5 + k * 12, 0, 0, 7); g.stroke(); }
  if (p === hover) { g.strokeStyle = "#5aa2ff"; g.lineWidth = 1.8; g.beginPath(); g.ellipse(fx, fy, 14, 6.5, 0, 0, 7); g.stroke(); }
  p.emit = []; p.ember = false; p.pouring = false;
  g.save(); g.translate(sx, sy); drawPerson(g, p, T); g.restore();
  const k = p.look.scale, m = p.mirror ? -1 : 1, lying = p.lying;
  const toW = ([lx, ly]) => lying ? [sx + Math.cos(p.lieAng || 0) * (ly + 17) * -k, sy + Math.sin(p.lieAng || 0) * (ly + 17) * -k] : [sx + lx * k * m, sy + ly * k];
  p.handW = { R: toW(p.hands.R), L: toW(p.hands.L), head: toW(p.hands.head), mouth: toW(p.hands.mouth) };
  for (const side of p.emit) if (Math.random() < FDT * 3) { const [hx, hy] = p.handW[side]; part({ kind: "steam", x: hx + m * 1.5, y: hy - 4, vx: rnd(-1.5, 1.5), vy: -7, life: 2 }); }
  if (p.ember && Math.random() < FDT * 2.5) { const [hx, hy] = p.handW.R; part({ kind: "smoke", x: hx, y: hy - 1, vx: rnd(-1, 1), vy: -6, life: 2.2 }); }
  if (p.pose.exhale && !p.puffed) { p.puffed = true; const [mx, my] = p.handW.mouth; for (let i = 0; i < 4; i++) part({ kind: "smoke", x: mx + m * 2, y: my, vx: m * rnd(4, 9), vy: rnd(-5, -2), life: 2.4 }); }
  if (!p.pose.exhale) p.puffed = false;
  if (p.pouring && Math.random() < FDT * 14) { const [hx, hy] = p.handW.R; part({ kind: "drop", x: hx + m * 7, y: hy - 4, vx: m * rnd(2, 6), vy: 6, g: 120, life: .45 }); }
}
// ── labels (screen px): who, and for anyone at work, what. Problems get a red badge on the head.
const LABEL_FONT = (px, w = 600) => `${w} ${px}px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif`;
function drawLabels(g) {
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "source-over";
  const ls = clamp(cam.s / DPR * .75, 1, 1.25) * DPR, fs = 11.5 * ls, fs2 = 10.5 * ls, pad = 5 * ls, rad = 5 * ls;
  const tone = p => p.flag ? 0 : p.mode === "ceo" ? 1 : p.mode !== "idle" ? 2 : 3;
  const list = [...people.values()].filter(p => p.handW).sort((a, b) => tone(a) - tone(b));
  const placed = []; hits = [];
  for (const p of people.values()) if (p.handW) { const [hx, hy] = toScreen(p.handW.head), [fx, fy] = toScreen(P(p.x, p.y, 0));
    hits.push({ p, r: [Math.min(hx, fx) - 12 * ls, hy - 10 * ls, 24 * ls, Math.max(18 * ls, fy - hy + 12 * ls)] }); }
  const collide = r => placed.some(q => r[0] < q[0] + q[2] + 2 && r[0] + r[2] + 2 > q[0] && r[1] < q[1] + q[3] + 2 && r[1] + r[3] + 2 > q[1]);
  for (const p of list) {
    const [hx, hy] = toScreen(p.handW.head), top = hy - BODY.head * p.look.scale * cam.s - 2 * ls;
    const t = tone(p), line2 = t === 1 || t === 2 ? p.card : null;
    g.font = LABEL_FONT(fs); const w1 = g.measureText(p.name).width; g.font = LABEL_FONT(fs2, 500); const w2 = line2 ? g.measureText(line2).width : 0;
    const w = Math.max(w1, w2) + pad * 2, h = line2 ? fs + fs2 + pad * 1.6 : fs + pad * 1.2, badge = p.flag ? 16 * ls : 0;
    const ay = top - badge - 4 * ls;
    const cands = [[0, 0], [w * .55, -2 * ls], [-w * .55, -2 * ls], [0, -h - 3 * ls], [w * .6, -h - 3 * ls], [-w * .6, -h - 3 * ls], [w * .75, h * .6], [-w * .75, h * .6]];
    let rect = null;
    for (const [dx, dy] of cands) { const r = [hx - w / 2 + dx, ay - h + dy, w, h]; if (r[0] < 2 || r[0] + w > W - 2 || r[1] < 2) continue; if (!collide(r)) { rect = r; break; } }
    if (!rect) { if (t === 3) continue; rect = [clamp(hx - w / 2, 2, W - w - 2), Math.max(2, ay - h), w, h]; }
    placed.push(badge ? [rect[0], rect[1], rect[2], rect[3] + badge + 4 * ls] : rect);
    const [bx, by] = rect, moved = Math.hypot(bx + w / 2 - hx, by + h - ay) > 10 * ls;
    if (moved) { g.strokeStyle = "rgba(30,36,48,.45)"; g.lineWidth = 1.2 * ls; g.beginPath(); g.moveTo(clamp(hx, bx + 4, bx + w - 4), by + h); g.lineTo(hx, top - badge); g.stroke(); }
    const bg = t === 0 ? "rgba(255,255,255,.96)" : t === 1 ? "#6d3fd6" : t === 2 ? "#1f6feb" : "rgba(255,255,255,.86)";
    g.fillStyle = bg; g.beginPath(); g.roundRect(bx, by, w, h, rad); g.fill();
    if (t === 0 && p === hover) { g.strokeStyle = "#d63031"; g.lineWidth = 1.6 * ls; g.stroke(); } else if (t === 0 || t === 3) { g.strokeStyle = "rgba(0,0,0,.1)"; g.lineWidth = 1; g.stroke(); }
    g.fillStyle = t === 1 || t === 2 ? "#fff" : t === 0 ? "#b42318" : "#1f2933"; g.font = LABEL_FONT(fs); g.textBaseline = "top";
    g.fillText(p.name, bx + pad, by + pad * .65);
    if (line2) { g.font = LABEL_FONT(fs2, 500); g.globalAlpha = .92; g.fillText(line2, bx + pad, by + pad * .65 + fs + 2 * ls); g.globalAlpha = 1; }
    g.textBaseline = "alphabetic";
    hits.push({ p, r: rect });
    if (p.flag) {                                                // the badge rides on the head
      const cx = hx, cy = top - badge / 2 + Math.sin(T * 3 + p.seed) * ls, rr = badge / 2;
      g.fillStyle = "#d63031"; g.beginPath(); g.arc(cx, cy, rr, 0, 7); g.fill(); g.strokeStyle = "#fff"; g.lineWidth = 1.5 * ls; g.stroke();
      g.fillStyle = "#fff"; g.font = LABEL_FONT(rr * 1.35, 800); g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(p.flag === "login expired" ? "⟳" : p.flag === "parked" ? "P" : "!", cx, cy + .5 * ls); g.textAlign = "start"; g.textBaseline = "alphabetic";
    }
  }
}

// ── frame
let lastT = performance.now(), hudAt = 0;
function frame(t) {
  requestAnimationFrame(frame);
  const visible = !document.hidden && !$("overview").hidden;
  FDT = Math.min(.1, (t - lastT) / 1000) * SPEED; lastT = t;
  if (!people.size || !visible) return;
  const r = wrap.getBoundingClientRect(); if (!r.width || !r.height) return;
  if (Math.abs(r.width * DPR - W) > 2 || Math.abs(r.height * DPR - H) > 2) layout();
  if (!cache) buildCache();
  simStep(FDT);
  const g = ctx, n = nightness(); NIGHT_N = n;
  g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = "source-over"; g.globalAlpha = 1; g.clearRect(0, 0, W, H);
  g.drawImage(cache.base, 0, 0);
  worldT(g); drawWalls(g);
  const list = [];
  for (const it of ITEMS) list.push([it.dynKey ? it.dynKey() : it.key, it]);
  for (const p of people.values()) list.push([p.x + p.y + (p.seated ? .1 : 0) + (p.lying ? 1.1 : 0) + .02, p]);   // on a bed/lounger: over it
  for (const l of OBJ.leftovers) list.push([l.x + l.y + .05, { live: g2 => drawMugAt(g2, ...P(l.x, l.y, l.z || .72), l.col) }]);
  list.sort((a, b) => a[0] - b[0]);
  for (const [, o] of list) {
    if (o.look) { worldT(g); drawPersonAt(g, o); continue; }
    if (o.draw) { const sp = cache.sprites.get(o); if (sp) { g.setTransform(1, 0, 0, 1, 0, 0); g.drawImage(sp.c, sp.dx, sp.dy); } }
    if (o.live) { worldT(g); o.live(g, T); }
  }
  drawParticles(g);
  drawNight(g, n);
  g.setTransform(1, 0, 0, 1, 0, 0); drawSky(g, n, Date.now() / 1000);
  drawLabels(g);
  if (t - hudAt > 1000) { hudAt = t; paintHud(); }
}

// ── HUD, tooltip, input
const stamp = s => new Date(s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
function paintHud() {
  if (!lastBoard) return;
  let w = 0, i = 0, d = 0;
  for (const p of people.values()) p.flag ? d++ : p.mode === "idle" ? i++ : p.mode === "ceo" ? 0 : w++;
  const nj = (lastBoard.needs_jack || []).length;
  hudEl.innerHTML = `<b>Foundlings HQ</b><span class="o-w">● ${w} working</span><span class="o-i">● ${i} on break</span>`
    + (d ? `<span class="o-d">● ${d} not answering</span>` : "") + (nj ? `<button class="o-nj" type="button">⚑ ${nj} need${nj > 1 ? "" : "s"} you</button>` : "")
    + `<span class="o-ph">${phaseText()}</span>`;
  const njb = hudEl.querySelector(".o-nj"); if (njb) njb.onclick = () => { if (document.fullscreenElement) document.exitFullscreen(); $("njwrap").scrollIntoView({ behavior: "smooth" }); };
  tickEl.innerHTML = events.length ? events.slice(0, 4).map((e, k) => `<div style="opacity:${1 - k * .2}"><time>${stamp(e.at)}</time> ${esc(e.line)}</div>`).join("")
    : `<div class="faint">Moves show up here as they happen.</div>`;
}
function at(e) {
  const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) * DPR, y = (e.clientY - r.top) * DPR;
  for (let i = hits.length - 1; i >= 0; i--) { const [hx, hy, w, h] = hits[i].r; if (x >= hx && x <= hx + w && y >= hy && y <= hy + h) return hits[i].p; }
  return null;
}
const DOING = { coffee: "getting a coffee", lunch: "having lunch", snack: "grabbing a snack", chat: "chatting", pong: "playing ping-pong", nap: "napping on the couch",
  phone: "on their phone", gaze: "taking in the view", smoke: "on a smoke break", stretch: "stretching", water: "watering the plants", whiteboard: "doodling on the whiteboard",
  read: "reading", sun: "sunbathing" };
function showTip(e) {
  const p = hover; if (!p || !p.a) { tipEl.hidden = true; return; }
  const a = p.a, seats = seatsOf(a.name), free = a.free_since && p.mode === "idle" ? Math.floor((lastBoard.now - a.free_since) / 3600) : 0;
  tipEl.innerHTML = `<b>${esc(a.name)}</b><div>${esc(label(a))}</div>` + (p.mode === "idle" && p.activity ? `<div class="faint">On a break: ${esc(DOING[p.activity] || p.activity)}${free ? ` · free ${free}h` : ""}</div>` : "")
    + `<div class="faint">${esc([a.kind === "slack" ? "Slack" : a.team, a.product, ...seats].filter(Boolean).join(" · "))}</div><div class="faint">Click to open</div>`;
  tipEl.hidden = false;
  const r = wrap.getBoundingClientRect(), tw = tipEl.offsetWidth, th = tipEl.offsetHeight;
  let x = e.clientX - r.left + 16, y = e.clientY - r.top + 16;
  if (x + tw > r.width - 8) x = e.clientX - r.left - tw - 16; if (y + th > r.height - 8) y = e.clientY - r.top - th - 16;
  tipEl.style.left = Math.max(8, x) + "px"; tipEl.style.top = Math.max(8, y) + "px";
}
function fit() {                                                // outside full screen: fill the window below the tabs
  if (document.fullscreenElement === wrap) { wrap.style.height = ""; return; }
  const top = wrap.getBoundingClientRect().top + scrollY;
  wrap.style.height = Math.max(460, innerHeight - top - 14) + "px";
}
function mount() {
  wrap = $("office"); cv = $("officecv"); ctx = cv.getContext("2d"); hudEl = $("ohud"); tipEl = $("otip"); tickEl = $("oticker");
  cv.addEventListener("mousemove", e => { hover = at(e); cv.style.cursor = hover ? "pointer" : "default"; showTip(e); });
  cv.addEventListener("mouseleave", () => { hover = null; tipEl.hidden = true; });
  cv.addEventListener("click", e => { const p = at(e); if (p) { if (document.fullscreenElement) document.exitFullscreen(); showAgent(p.name); } });
  const fs = $("ofs");
  if (document.fullscreenEnabled) fs.onclick = () => document.fullscreenElement ? document.exitFullscreen() : wrap.requestFullscreen();
  else fs.hidden = true;
  document.addEventListener("fullscreenchange", () => { fs.textContent = document.fullscreenElement ? "✕ Exit full screen" : "⛶ Full screen"; fit(); });
  addEventListener("resize", fit); new ResizeObserver(fit).observe($("njwrap")); fit();
  requestAnimationFrame(frame);
}
window.Office = { update, mount, debug: { people, SLOTS, OBJ, get T() { return T; }, get cache() { return cache; },
  force(name, k) { const p = people.get(name); if (!p || p.mode !== "idle") return; stop(p); p.activity = k; start(p, IDLE[k][2](p)); } } };
mount();
if (typeof board !== "undefined" && board) update(board);
})();
