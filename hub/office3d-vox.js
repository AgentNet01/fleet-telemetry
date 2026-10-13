// office3d-vox.js — the voxel kit: one box primitive, the shared materials, and the small things people hold.
// Coordinates everywhere are the sim's: x across, y deep, z up. Three's are (x, z, y); only this file knows that.
import * as THREE from "./three.module.min.js";
export { THREE };

export const VX = 1 / 16;                                   // the voxel: sizes and edges land on this grid
export const snap = v => Math.round(v * 16) / 16;
const cache = new Map();
export const col = c => { if (c.isColor) return c; let k = cache.get(c); if (!k) cache.set(c, k = new THREE.Color(c)); return k; };
export const mulberry = s => () => { s = s + 0x6D2B79F5 | 0; let t = Math.imul(s ^ s >>> 15, 1 | s); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
export const lerp = (a, b, t) => a + (b - a) * t, clamp = (v, a, b) => Math.max(a, Math.min(b, v));
export const at = (o, x, y, z) => (o.position.set(x, z, y), o);        // place a three object at a sim point

export const MAT = {
  solid: new THREE.MeshLambertMaterial({ vertexColors: true }),
  glass: new THREE.MeshLambertMaterial({ color: 0xcfe6f5, transparent: true, opacity: .3, depthWrite: false }),
  glow: c => new THREE.MeshBasicMaterial({ color: c }),
  tint: c => new THREE.MeshLambertMaterial({ vertexColors: true, color: c }),
};

// Collects boxes into one geometry: one draw call for a whole room. Faces: E W (±x), S N (±y), U D (±z).
export class Mesher {
  constructor() { this.p = []; this.n = []; this.c = []; this.u = []; this.i = []; this.count = 0; this.boxes = 0; }
  face(pts, n, c, ao, uv) {
    const b = this.count;
    for (let k = 0; k < 4; k++) {
      const f = k < 2 ? ao : 1;                             // the two base corners are darker: baked contact shade
      this.p.push(...pts[k]); this.n.push(...n); this.c.push(c.r * f, c.g * f, c.b * f);
      uv ? this.u.push(...uv[k]) : this.u.push(0, 0);
    }
    this.i.push(b, b + 1, b + 2, b, b + 2, b + 3); this.count += 4;
  }
  box(x, y, z, w, d, h, c, o = {}) {
    const X0 = x, X1 = x + w, Y0 = z, Y1 = z + h, Z0 = y, Z1 = y + d, f = o.faces || "EWSNUD";
    const cc = col(c), top = o.top ? col(o.top) : cc, ao = o.ao ?? (h > .3 ? .84 : 1), t = o.uv;
    // facade texture: 8 cells per tile, measured down from the roof so every tower's top row lines up
    const v = Y => 1 - ((t.top - Y) / t.ch + t.ov) / 8;
    const uvs = L => { if (!t) return null; const e = (t.ou + Math.max(1, Math.round(L / t.cw))) / 8;     // whole windows per face, never a cut one
      return [[t.ou / 8, v(Y0)], [e, v(Y0)], [e, v(Y1)], [t.ou / 8, v(Y1)]]; };
    if (f.includes("E")) this.face([[X1, Y0, Z1], [X1, Y0, Z0], [X1, Y1, Z0], [X1, Y1, Z1]], [1, 0, 0], cc, ao, uvs(d));
    if (f.includes("W")) this.face([[X0, Y0, Z0], [X0, Y0, Z1], [X0, Y1, Z1], [X0, Y1, Z0]], [-1, 0, 0], cc, ao, uvs(d));
    if (f.includes("S")) this.face([[X0, Y0, Z1], [X1, Y0, Z1], [X1, Y1, Z1], [X0, Y1, Z1]], [0, 0, 1], cc, ao, uvs(w));
    if (f.includes("N")) this.face([[X1, Y0, Z0], [X0, Y0, Z0], [X0, Y1, Z0], [X1, Y1, Z0]], [0, 0, -1], cc, ao, uvs(w));
    if (f.includes("U")) this.face([[X0, Y1, Z1], [X1, Y1, Z1], [X1, Y1, Z0], [X0, Y1, Z0]], [0, 1, 0], top, 1);
    if (f.includes("D")) this.face([[X0, Y0, Z0], [X1, Y0, Z0], [X1, Y0, Z1], [X0, Y0, Z1]], [0, -1, 0], cc, ao);
    this.boxes++; return this;
  }
  mesh(mat = MAT.solid, shadow = true) {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(this.p, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(this.n, 3));
    g.setAttribute("color", new THREE.Float32BufferAttribute(this.c, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(this.u, 2));
    g.setIndex(this.i);
    const m = new THREE.Mesh(g, mat); m.castShadow = m.receiveShadow = shadow; m.userData.boxes = this.boxes;
    return m;
  }
}
// a small piece with its own pivot: build it around (0,0,0), then place it
export const piece = (fn, mat, shadow = true) => { const m = new Mesher(); fn(m); return m.mesh(mat, shadow); };

// text on a little canvas: plaques on walls, speech bubbles, the microwave's ding
export function textTexture(text, { px = 28, fg = "#fff", bg = "rgba(40,46,56,.82)", pad = 10, weight = 700, radius = 8 } = {}) {
  const c = document.createElement("canvas"), g = c.getContext("2d"), font = `${weight} ${px}px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif`;
  g.font = font; c.width = Math.ceil(g.measureText(text).width + pad * 2); c.height = Math.ceil(px * 1.25 + pad * 2);
  if (bg) { g.fillStyle = bg; g.beginPath(); g.roundRect(0, 0, c.width, c.height, radius); g.fill(); }
  g.font = font; g.fillStyle = fg; g.textBaseline = "middle"; g.textAlign = "center"; g.fillText(text, c.width / 2, c.height / 2 + px * .05);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t.userData = { aspect: c.width / c.height };
  return t;
}
export function textSprite(text, height, opts) {
  const t = textTexture(text, opts), s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, transparent: true, depthWrite: false }));
  s.scale.set(height * t.userData.aspect, height, 1); return s;
}

// ── things that fit in a hand. Each is built around its grip: z up, y away from the holder.
const GREY = "#9aa3ab";
export const PROPS = {
  mug: o => piece(m => { m.box(-.04, -.04, 0, .08, .08, .09, o.mug || "#fff"); m.box(-.028, -.028, .09, .056, .056, .004, "#6b3e1f"); m.box(.04, -.013, .02, .028, .026, .05, o.mug || "#fff"); }),
  cup: () => piece(m => m.box(-.028, -.028, 0, .056, .056, .08, "#dff0ff"), MAT.glass, false),
  carafe: () => {
    const g = new THREE.Group();
    g.add(piece(m => m.box(-.065, -.065, 0, .13, .13, .14, "#dcebf5"), MAT.glass, false));
    g.add(piece(m => { m.box(-.045, -.045, .14, .09, .09, .03, "#222"); m.box(.065, -.015, .03, .03, .03, .09, "#222"); }));
    const lv = piece(m => m.box(-.055, -.055, 0, .11, .11, .12, "#5a3219")); lv.position.y = .008; g.add(lv); g.userData.level = lv;
    return g;
  },
  plate: () => piece(m => { m.box(-.11, -.11, 0, .22, .22, .016, "#fbfbf8"); m.box(-.06, -.07, .016, .1, .12, .035, "#e8a33d"); m.box(.03, .0, .016, .05, .05, .04, "#c0392b"); }),
  salad: () => piece(m => { m.box(-.11, -.11, 0, .22, .22, .016, "#fbfbf8"); m.box(-.07, -.07, .016, .14, .14, .035, "#7cb342"); m.box(-.02, -.03, .05, .05, .05, .02, "#e76f51"); }),
  takeout: () => piece(m => { m.box(-.06, -.05, 0, .12, .1, .1, "#f4f4f0"); m.box(-.062, -.052, .045, .124, .104, .028, "#c0392b"); }),
  yogurt: () => piece(m => { m.box(-.035, -.035, 0, .07, .07, .075, "#ffd6e0"); m.box(-.04, -.04, .075, .08, .08, .012, "#fff"); }),
  apple: () => piece(m => { m.box(-.04, -.04, 0, .08, .08, .075, "#d63b2f"); m.box(-.008, -.008, .075, .016, .016, .025, "#5b3a1a"); m.box(.008, -.012, .09, .035, .024, .012, "#6a994e"); }),
  sandwich: () => piece(m => { m.box(-.07, -.045, 0, .14, .09, .022, "#f3d9a4"); m.box(-.074, -.049, .022, .148, .098, .012, "#7cb342"); m.box(-.07, -.045, .034, .14, .09, .022, "#f3d9a4"); }),
  fork: () => piece(m => { m.box(-.008, -.008, -.03, .016, .016, .13, GREY); m.box(-.016, -.006, .1, .032, .012, .03, GREY); }),
  spoon: () => piece(m => { m.box(-.008, -.008, -.03, .016, .016, .12, GREY); m.box(-.02, -.008, .09, .04, .016, .045, GREY); }),
  phone: () => { const g = piece(m => m.box(-.04, -.009, -.03, .08, .018, .15, "#1e2228")); g.add(at(piece(m => m.box(-.033, 0, -.022, .066, .003, .134, "#fff"), MAT.glow("#7fc3ff"), false), 0, -.012, 0)); return g; },
  book: o => piece(m => { m.box(-.08, -.022, 0, .16, .044, .2, o.bookColor || "#2a9d8f"); m.box(-.074, -.016, .006, .15, .032, .188, "#fbf6ea"); m.box(-.08, -.022, 0, .012, .044, .2, o.bookColor || "#2a9d8f"); }),
  paper: () => piece(m => { m.box(-.075, -.004, 0, .15, .008, .2, "#fff"); for (let i = 0; i < 4; i++) m.box(-.055, -.006, .15 - i * .035, .11 - (i % 2) * .03, .002, .01, "#9aa3ab"); }),
  cig: () => { const g = piece(m => m.box(-.006, -.006, 0, .012, .012, .07, "#f3f3f3")); g.add(at(piece(m => m.box(-.008, -.008, 0, .016, .016, .016, "#fff"), MAT.glow("#ff7a2a"), false), 0, 0, .07)); return g; },
  lighter: () => { const g = piece(m => m.box(-.014, -.014, 0, .028, .028, .055, "#e76f51"));
    const f = at(piece(m => { m.box(-.01, -.01, 0, .02, .02, .035, "#fff"); }, MAT.glow("#ffcf5c"), false), 0, 0, .06); g.add(f); g.userData.flame = f; return g; },
  can: () => piece(m => { m.box(-.055, -.075, 0, .11, .15, .11, "#3f9d6a"); m.box(-.014, .075, .05, .028, .1, .028, "#3f9d6a"); m.box(-.02, .165, .06, .04, .02, .04, "#2f7d55");
    m.box(-.014, -.115, .03, .028, .04, .028, "#2f7d55"); m.box(-.014, -.115, .09, .028, .09, .028, "#2f7d55"); }),
  marker: o => piece(m => { m.box(-.01, -.01, -.02, .02, .02, .09, "#2a2a30"); m.box(-.01, -.01, .07, .02, .02, .025, o.marker || "#e63946"); }),
  paddle: () => piece(m => { m.box(-.014, -.014, 0, .028, .028, .07, "#7a5230"); m.box(-.065, -.011, .07, .13, .022, .14, "#c0392b"); }),
};
// held upright whatever the arm does (a mug stays level); the rest follow the forearm (a fork, a phone)
export const UPRIGHT = new Set(["mug", "cup", "carafe", "plate", "salad", "takeout", "yogurt", "apple", "sandwich", "book", "paper", "lighter", "can"]);
