// office3d-world.js — the place: our floor, its furniture and working objects, the tower, the city, the sky, the light.
// Layout comes from the sim (sim.SOLIDS and friends); this file only decides how it looks. Coordinates are the sim's.
import { THREE, VX, snap, col, mulberry, lerp, clamp, at, MAT, Mesher, piece, textTexture, textSprite, PROPS } from "./office3d-vox.js";

const G = -31;                                              // street level; our floor tops the tower
export const DT = .75, CT = .9375;                          // table tops and the kitchen counter top, on the voxel grid
const GLASS = "#ffffff", DARK = "#3b414a";

export function buildWorld(sim) {
  const { X, Y, C, SOLIDS, DESKS, BOOTHS, OBJ, LIGHTS, shade, hash, WALL, SY, EX, DOOR, OFFICE, BR, ZONE } = sim;
  const scene = new THREE.Scene(), ticks = [], tick = f => ticks.push(f);
  const st = new Mesher(), gl = new Mesher();              // everything static and solid; everything static and glass
  const add = (o, x = 0, y = 0, z = 0, parent = scene) => (parent.add(at(o, x, y, z)), o);
  const glowBox = (w, d, h, c) => piece(m => m.box(0, 0, 0, w, d, h, "#fff"), MAT.glow(c), false);
  // a room the 2D plan moved (office.js shiftTo): the same builders, offset, so its numbers stay as they were
  const shifted = (ox, oy) => ({ st: { box: (x, y, ...r) => st.box(x + ox, y + oy, ...r) }, gl: { box: (x, y, ...r) => gl.box(x + ox, y + oy, ...r) },
    add: (o, x = 0, y = 0, z = 0, parent = scene) => add(o, x + ox, y + oy, z, parent), pool: (x, y, ...r) => pool(x + ox, y + oy, ...r) });

  // ── light: a sun that casts, a sky that fills; at night the room's own lamps take over
  const hemi = new THREE.HemisphereLight(0xffffff, 0xc9c2b6, 1.4), sun = new THREE.DirectionalLight(0xfff3df, 2.5);
  sun.position.set(X / 2 - 15, 24, Y / 2 + 10.5); sun.target.position.set(X / 2, 0, Y / 2); sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048); sun.shadow.bias = -.0004; sun.shadow.normalBias = .03;
  Object.assign(sun.shadow.camera, { left: -22, right: 22, top: 17, bottom: -17, near: 1, far: 80 });
  scene.add(hemi, sun, sun.target);
  const lamps = LIGHTS.filter(l => l.kind !== "desk").map(l => { const p = new THREE.PointLight(`rgb(${l.col})`, 0, 7.5, 1.5);   // desk lamps glow instead: every real light is paid for on every pixel
    scene.add(at(p, l.x, l.y, l.kind === "pendant" ? 2.2 : l.z)); return { l, p }; });
  const poolTex = (() => { const c = Object.assign(document.createElement("canvas"), { width: 64, height: 64 }), g = c.getContext("2d"), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gr.addColorStop(0, "rgba(255,255,255,1)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); return new THREE.CanvasTexture(c); })();
  const pool = (x, y, z, r, c) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(r * 2, r * 2), new THREE.MeshBasicMaterial({ map: poolTex, color: c, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; return add(m, x, y, z); };                                       // a soft pool of light lying on a surface

  // ── floors, by room (the same zones the 2D office paints)
  const zone = ZONE;
  const tone = { carpet: [C.carpet, C.carpet2], board: [C.board, C.board2], tile: [C.tile, C.tile2], review: [C.review, C.review2] };
  for (let y = 0; y < Y - .01; y += .5) for (let x = 0; x < X - .01; x += .5) {
    const z = zone(x + .25, y + .25), i = Math.round(x * 2), j = Math.round(y * 2);
    if (tone[z]) st.box(x, y, -VX, .5, .5, VX, tone[z][(i + j) % 2], { faces: "U" });
  }
  const boards = (x0, x1, y0, y1, alongY, base) => {         // floorboards: each strip its own tone, with butt joints
    const [a0, a1, b0, b1] = alongY ? [x0, x1, y0, y1] : [y0, y1, x0, x1];
    for (let a = a0, i = 0; a < a1 - .01; a += .25, i++) for (let b = b0, k = 0; b < b1 - .01; k++) {
      const len = Math.min(b1 - b, 1.5 + (hash(i * 7 + k * 13) % 5) * .5), c = shade(base, ((hash(i * 5 + k * 3) % 9) - 4) * .014);
      alongY ? st.box(a, b, -VX, .25, len, VX, c, { faces: "U" }) : st.box(b, a, -VX, len, .25, VX, c, { faces: "U" });
      alongY ? st.box(a, b, 0, .25, .012, .004, shade(base, -.25), { faces: "U" }) : st.box(b, a, 0, .012, .25, .004, shade(base, -.25), { faces: "U" });
      b += len;
    }
  };
  boards(WALL, X, 0, Y, true, C.deck); boards(5, 9.5, 5.5 + SY, Y, false, C.plank); boards(0, OFFICE.x, 0, OFFICE.end, false, C.plank);
  st.box(0, 0, -.32, X, Y, .32, C.slab, { faces: "EWSND" });                                        // the floor slab's edge
  st.box(-.25, -.25, -.32, WALL + .25, .25, .32, C.slab); st.box(-.25, 0, -.32, .25, Y, .32, C.slab);
  st.box(6.45, 7.3 + SY, 0, 2.3, 2.45, .02, C.rugEdge); st.box(6.6, 7.45 + SY, 0, 2.0, 2.15, .03, C.rug);      // rugs
  for (let k = 0; k < 3; k++) st.box(6.9, 7.75 + SY + k * .4, 0, 1.4, .1, .035, "#dcae8e");
  for (const oy of [0, OFFICE.split]) { st.box(.55, oy + .6, 0, 2.9, 2.4, .02, C.rugEdge); st.box(.7, oy + .75, 0, 2.6, 2.1, .03, oy ? "#cfd8e3" : "#e3d5c7"); }
  st.box(14.85, 1.0, 0, 3.7, 2.15, .02, "#d5cde6"); st.box(15.0, 1.15, 0, 3.4, 1.85, .025, "#ddd6ec");
  for (const b of BOOTHS) st.box(b.x, b.y, 0, 1.05, 1.1, .02, "#cfd5dc");
  // ── the shrine: a lit niche, candles, candle stands, the papers left for Jack; it glows while anything waits, flares when one lands
  { const S = sim.SHRINE, sh = OBJ.shrine, z = S.top;
    const door = add(glowBox(.34, .012, .34, "#5a4630"), ...S.door);
    const halo = pool(S.halo[0], S.halo[1], .012, 1.6, "#ffcf7a");
    const lanterns = S.lanterns.map(([lx, ly, lz]) => add(glowBox(.18, .18, .13, "#6b6259"), lx, ly, lz));
    const flames = S.candles.map(([cx, cy]) => { st.box(cx, cy, z, .06, .06, .12, "#f4efe3"); return add(glowBox(.025, .025, .045, "#ffb347"), cx + .018, cy + .018, z + .12); });
    const papers = [...Array(6)].map((_, k) => { const m = add(piece(mm => mm.box(-.07, -.05, 0, .14, .1, .006, "#fdfbf4")), S.papers[0], S.papers[1], z + .006 + k * .008);
      m.rotation.y = ((hash(k * 17) % 9) - 4) * .07; m.visible = false; return m; });
    tick((dt, T) => {
      const on = sh.n > 0, flare = Math.max(0, 1 - (T - sh.flash) / 2.5), fl = .85 + .15 * Math.sin(T * 11) * Math.sin(T * 7.3);
      const lit = on || flare ? (flare > .2 ? "#fff1c2" : "#ffd27a") : null;
      door.material.color.set(lit || "#5a4630"); for (const l of lanterns) l.material.color.set(lit || "#6b6259");
      halo.material.opacity = (on ? .32 + .08 * Math.sin(T * 1.6) : 0) + flare * .6;
      for (const f of flames) { f.visible = on || flare > 0; f.scale.set(1, fl, 1); }
      papers.forEach((m, k) => m.visible = k < sh.n);
    }); }

  // ── every box the sim placed, snapped to the voxel grid (both ends, so stacked pieces still meet)
  for (const [x, y, z, w, d, h, c, o] of SOLIDS) {
    const x0 = snap(x), y0 = snap(y), z0 = snap(z);
    st.box(x0, y0, z0, Math.max(VX, snap(x + w) - x0), Math.max(VX, snap(y + d) - y0), Math.max(VX, snap(z + h) - z0), c, { top: o.top });
    if (z === 0 && Math.abs(w - .08) < 1e-6 && Math.abs(d - .08) < 1e-6) { st.box(x0 - .16, y0, 0, .38, VX, .035, c); st.box(x0, y0 - .16, 0, VX, .38, .035, c); }   // a chair's stem gets feet
  }

  // ── back walls with real windows; each hides when the camera goes behind it, so the room stays a cutaway
  const north = new THREE.Group(), west = new THREE.Group(); scene.add(north, west);
  const wall = (grp, axis, a0, a1, wins) => {
    const m = new Mesher(), g = new Mesher(), H = 2.75, W0 = .5625, W1 = 2.4375;
    const B = (mm, s0, s1, z0, z1, c, t0 = -.25, t1 = 0) => axis === "x" ? mm.box(s0, t0, z0, s1 - s0, t1 - t0, z1 - z0, c) : mm.box(t0, s0, z0, t1 - t0, s1 - s0, z1 - z0, c);
    let s = a0;
    for (const [w0, w1] of wins) {
      B(m, s, w0, 0, H, C.wall); B(m, w0, w1, 0, W0, C.wall); B(m, w0, w1, W1, H, C.wall);
      B(m, w0, w1, W0 - .04, W0, C.winFrame, -.25, .06);                                            // sill
      for (let q = w0; q < w1 + .01; q += .5) { const a = Math.min(q, w1 - .04); B(m, a, a + .04, W0, W1, C.winFrame, -.18, -.08); }
      B(m, w0, w1, 1.52, 1.56, C.winFrame, -.18, -.08);
      B(g, w0, w1, W0, W1, GLASS, -.14, -.12);
      s = w1;
    }
    B(m, s, a1, 0, H, C.wall);
    B(m, a0, a1, 0, .1, "#e4e8ed", 0, .02);                                                           // skirting
    grp.add(m.mesh(), g.mesh(MAT.glass, false));
  };
  wall(north, "x", -.25, WALL, [[.3, 4.0], [6.4, 14.3], [14.8, 15.3], [18.1, 18.7]]);     // whiteboard at 4.6, boardroom screen at 15.5
  wall(west, "y", 0, Y, [[.3, 5.3], [5.6, 10.3]]);
  const sign = (text, h, grp, x, y, z, turn) => {
    const t = textTexture(text, { px: 44, pad: 14, radius: 10 }), m = new THREE.Mesh(new THREE.PlaneGeometry(h * t.userData.aspect, h), new THREE.MeshLambertMaterial({ map: t, transparent: true }));
    if (turn) m.rotation.y = Math.PI / 2; add(m, x, y, z, grp);
  };
  sign("BOARDROOM", .2, north, 16.7, .012, 2.58); sign("PRODUCT FLOOR", .2, north, 10.2, .012, 2.58); sign("KITCHEN", .2, west, .012, 7.9 + SY, 2.58, true);
  sign("CEO", .2, north, 2.15, .012, 2.58);

  // the whiteboard: whatever the sim's doodlers have drawn
  const wn = new Mesher();
  wn.box(4.6, 0, .85, 1.5, .04, 1.15, "#9aa3ab"); wn.box(4.6, .04, .8, 1.5, .07, .03, "#9aa3ab");
  wn.box(15.5, 0, .9, 2.4, .06, 1.13, "#1c2027");                                                    // the boardroom screen's case
  north.add(wn.mesh());
  const canvasTex = (w, h) => { const c = Object.assign(document.createElement("canvas"), { width: w, height: h }), t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return [c.getContext("2d"), t]; };
  const [wbG, wbT] = canvasTex(280, 210);
  add(new THREE.Mesh(new THREE.PlaneGeometry(1.4, 1.05), new THREE.MeshLambertMaterial({ map: wbT })), 5.35, .045, 1.425, north);
  let wbSeen = null;
  tick(() => { const s = OBJ.board.strokes, key = s.length + ":" + (s[s.length - 1] ? s[s.length - 1].pts[0][0] : 0); if (key === wbSeen) return; wbSeen = key;
    wbG.fillStyle = "#fbfcfd"; wbG.fillRect(0, 0, 280, 210); wbG.lineWidth = 3; wbG.lineCap = wbG.lineJoin = "round";
    for (const k of s) { wbG.strokeStyle = k.col; wbG.beginPath(); k.pts.forEach(([u, v], i) => i ? wbG.lineTo(u * 280, v * 210) : wbG.moveTo(u * 280, v * 210)); wbG.stroke(); }
    wbT.needsUpdate = true; });
  // the boardroom screen: live charts while the CEO is in
  const [scG, scT] = canvasTex(256, 108), scMat = new THREE.MeshBasicMaterial({ map: scT });
  add(new THREE.Mesh(new THREE.PlaneGeometry(2.2, .93), scMat), 16.7, .065, 1.465, north);
  let scAt = -9, scOn = null;
  tick((dt, T) => { const ceo = [...sim.people.values()].some(p => p.mode === "ceo" && p.slot && !p.path.length);
    if (ceo === scOn && (!ceo || T - scAt < .2)) return; scOn = ceo; scAt = T;
    scG.fillStyle = ceo ? "#16263a" : "#20252d"; scG.fillRect(0, 0, 256, 108);
    if (ceo) { for (let i = 0; i < 6; i++) { const h = (.2 + .5 * (.5 + .5 * Math.sin(T * .5 + i * 1.3))) * 70; scG.fillStyle = ["#5fb3e6", "#9fe0a6", "#f2cc8f"][i % 3]; scG.fillRect(20 + i * 19, 94 - h, 13, h); }
      scG.strokeStyle = "#9fe0a6"; scG.lineWidth = 3; scG.beginPath(); [[.58, .8], [.68, .55], [.78, .62], [.9, .25]].forEach(([u, v], i) => i ? scG.lineTo(u * 256, v * 108) : scG.moveTo(u * 256, v * 108)); scG.stroke();
      scG.fillStyle = "#cfe6ff"; scG.font = "600 11px system-ui"; scG.fillText("FOUNDLINGS · LIVE", 148, 16);
    } else { scG.fillStyle = "rgba(160,190,220,.35)"; scG.fillRect(120, 46, 16, 16); }
    scT.needsUpdate = true; });

  // kitchen wall: upper cabinets, and a clock that tells the real time
  const ww = new Mesher();
  for (let y = 5.95 + SY; y < 9.9 + SY; y += 1.0) { ww.box(0, y, 1.55, .32, .98, .72, C.white);
    ww.box(.32, y + .44, 1.62, .02, .03, .14, "#8c959e"); ww.box(.32, y + .52, 1.62, .02, .03, .14, "#8c959e"); ww.box(.32, y + .485, 1.56, .004, .01, .7, "#cfd4da"); }
  ww.box(0, 10.5 + SY, 2.2, .03, .36, .36, DARK); ww.box(.03, 10.53 + SY, 2.23, .012, .3, .3, "#fff");
  for (let k = 0; k < 4; k++) ww.box(.042, 10.665 + SY + [0, .12, 0, -.12][k], 2.365 + [.12, 0, -.12, 0][k], .004, .03, .03, "#9aa3ab");
  west.add(ww.mesh());
  const hand = (len, w) => { const m = piece(q => q.box(0, -w / 2, 0, .008, w, len, "#222"), MAT.solid, false); add(m, .046, 10.68 + SY, 2.38, west); return m; };
  const hr = hand(.085, .028), mn = hand(.125, .02);
  tick(() => { const d = new Date(); hr.rotation.x = -((d.getHours() % 12 + d.getMinutes() / 60) / 12) * Math.PI * 2; mn.rotation.x = -(d.getMinutes() / 60) * Math.PI * 2; });

  // ── desks: keyboard, mouse, clutter, a lamp on some, monitors that show real work, the worker's mug
  const codeTex = (() => { const [g, t] = canvasTex(64, 256); g.fillStyle = "#152030"; g.fillRect(0, 0, 64, 256);
    for (let r = 0; r < 32; r++) { if (hash(r * 17) % 6 === 0) continue; g.fillStyle = ["#5fb3e6", "#9fe0a6", "#f2cc8f", "#c4a7ff"][r % 4]; g.fillRect(5 + (r % 3) * 5, r * 8 + 3, 12 + hash(r * 31) % 36, 3); }
    t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.NearestFilter; return t; })();
  const screenOff = new THREE.MeshLambertMaterial({ color: "#2b3038" });
  for (const d of DESKS) {
    const { y, i } = d, x = d.ax;
    st.box(x + .38, y + .42, DT, .5, .16, .025, "#e9ecef"); for (let r = 0; r < 3; r++) st.box(x + .4, y + .435 + r * .045, DT + .025, .46, .03, .006, "#cdd3d9");
    st.box(x + 1.0, y + .46, DT, .07, .1, .03, "#e9ecef");
    if (i % 3 === 1) for (let j = 0; j < 3; j++) st.box(x + .08 + j * .01, y + .42, DT + j * .014, .24, .18, .014, ["#fafafa", "#f3efe2", "#fff"][j]);
    if (i % 3 === 2) { st.box(x + .1, y + .12, DT, .16, .16, .16, C.pot); st.box(x + .13, y + .15, DT + .16, .1, .1, .1, C.leaf); st.box(x + .16, y + .13, DT + .22, .08, .08, .1, C.leaf2); }
    let bulb = null;
    if (i % 3 === 0) { st.box(x + 1.16, y + .12, DT, .12, .12, .025, DARK); st.box(x + 1.205, y + .165, DT, .03, .03, .42, DARK); st.box(x + 1.205, y + .165, DT + .39, .03, .2, .03, DARK);
      st.box(x + 1.15, y + .3, DT + .32, .14, .13, .08, DARK); bulb = add(glowBox(.1, .09, .02, "#777"), x + 1.17, y + .32, DT + .3); bulb.userData.pool = pool(x + 1.1, y + .42, DT + .034, .5, "#ffd696"); }
    const screens = (d.two ? [[.1, .58], [.72, .58]] : [[.3, .8]]).map(([x0, w]) => {
      st.box(x + x0 + w / 2 - .12, y + .06, DT, .24, .14, .02, DARK); st.box(x + x0 + w / 2 - .03, y + .1, DT, .06, .05, .16, DARK);
      st.box(x + x0, y + .1, DT + .14, w, .05, .42, C.black);
      const tex = codeTex.clone(); tex.needsUpdate = true; tex.repeat.set(1, .25); tex.offset.y = (hash(i * 9 + x0 * 10) % 8) / 8;
      const mesh = add(new THREE.Mesh(new THREE.PlaneGeometry(w - .06, .36), screenOff), x + x0 + w / 2, y + .154, DT + .35);
      return { mesh, tex, on: new THREE.MeshBasicMaterial({ map: tex }) };
    });
    const mug = add(PROPS.mug({ mug: "#fff" }), x + 1.15, y + .55, DT); mug.material = MAT.tint("#fff");
    tick((dt, T, n) => { const on = !!d.busy;
      for (const s of screens) { s.mesh.material = on ? s.on : screenOff; if (on && d.typing) s.tex.offset.y -= dt * .2; }
      mug.visible = !!d.mug; if (d.mug) mug.material.color.set(d.mugColor || "#fff");
      if (bulb) { bulb.material.color.set(on && n > .3 ? "#ffe2a8" : "#6b7078"); bulb.userData.pool.material.opacity = on ? n * .55 : 0; } });
  }

  // ── boardroom table: water glasses, the CEO's laptop (it opens toward whoever sits at the head of the back row)
  for (const [gx, gy] of [[10.5, 1.7], [12.5, 1.7], [11.6, 2.3]]) gl.box(gx - .03, gy - .03, DT, .06, .06, .1, "#d8ecff");
  st.box(11.45, 1.6, DT, .5, .33, .02, "#9aa3ad"); st.box(11.5, 1.64, DT + .02, .4, .16, .004, "#7d8791");
  const lid = add(piece(m => m.box(0, -.02, 0, .5, .02, .31, "#8d96a0")), 11.45, 1.93, DT + .02), logo = add(glowBox(.05, .004, .05, "#b8c0c8"), .225, 0, .13, lid);
  let lidOpen = 0;
  tick(dt => { lidOpen = lerp(lidOpen, OBJ.laptop.open, 1 - Math.exp(-dt * 6)); lid.rotation.x = lerp(-Math.PI / 2, .22, lidOpen); logo.material.color.set(OBJ.laptop.glow ? "#e8f4ff" : "#b8c0c8"); });

  const shadeMat = new THREE.MeshLambertMaterial({ color: "#f3e3c3", emissive: "#ffcf8a", emissiveIntensity: 0 });
  { const { st, gl, add, pool } = shifted(0, SY);                    // the south rooms, moved down like the 2D plan
  // ── kitchen: counter doors, coffee machine, sink, microwave, watering can, fridge, fruit
  for (let k = 0; k < 4; k++) { st.box(.75, 5.94 + k, .08, .02, .92, .72, "#eef0f2"); st.box(.77, 6.72 + k, .46, .02, .03, .2, "#7d8790"); }
  st.box(.12, 6.1, CT, .48, .48, .5, DARK); st.box(.1, 6.08, CT + .5, .52, .52, .06, C.black);                    // coffee machine
  st.box(.6, 6.16, CT + .36, .012, .36, .1, "#1b1f24"); st.box(.6, 6.22, CT + .02, .012, .24, .28, "#23272d");
  const led = add(glowBox(.012, .03, .03, "#c0392b"), .612, 6.46, CT + .4);
  const carafe = add(PROPS.carafe(), .68, 6.34, CT), stream = add(piece(m => m.box(-.008, -.008, 0, .016, .016, .22, "#6e3e1e")), .68, 6.34, CT + .13);
  tick((dt, T) => { const o = OBJ.coffee; led.material.color.set(o.state === "brewing" ? (Math.floor(T * 3) % 2 ? "#ffb347" : "#7a4a10") : o.state === "ready" ? "#58d68d" : "#c0392b");
    carafe.visible = o.carafe; carafe.userData.level.scale.y = Math.max(.02, o.level); stream.visible = o.state === "brewing" && o.carafe; });
  for (const [a, b, c, d] of [[.14, 7.1, .48, .03], [.14, 7.67, .48, .03], [.14, 7.1, .03, .6], [.59, 7.1, .03, .6]]) st.box(a, b, CT, c, d, .02, "#c3c9cf");   // sink rim
  st.box(.17, 7.13, CT, .42, .54, .006, "#aeb6be"); st.box(.08, 7.38, CT, .04, .04, .27, "#9aa3ab"); st.box(.08, 7.38, CT + .24, .22, .04, .04, "#9aa3ab");
  const water = add(piece(m => m.box(0, 0, 0, .025, .025, .24, "#96c8f0"), MAT.glass, false), .27, 7.387, CT);
  st.box(.1, 8.3, CT, .58, .7, .4, C.steel); st.box(.68, 8.83, CT + .06, .012, .14, .28, "#3a4048");              // microwave
  const mwWin = add(glowBox(.012, .46, .28, "#4a5058"), .68, 8.34, CT + .06), mwLed = add(glowBox(.012, .04, .025, "#2a2f35"), .692, 8.88, CT + .28);
  const mwDoor = add(piece(m => { m.box(0, 0, 0, .02, .47, .3, "#aeb6be"); m.box(.02, .4, .06, .02, .03, .18, "#7d8790"); }), .69, 8.33, CT + .05);
  const ding = add(textSprite("ding!", .16, { fg: "#c0392b", bg: "rgba(255,255,255,.92)", px: 30 }), .8, 8.65, CT + .6);
  tick((dt, T) => { const o = OBJ.micro, lit = o.run && T < o.end;
    mwWin.material.color.set(lit ? "#ffcf6b" : "#4a5058"); mwLed.material.color.set(lit ? "#7dff9a" : "#2a2f35");
    mwDoor.visible = o.open > .02; mwDoor.rotation.y = o.open * 1.6;
    const k = (T - o.ding) / 1.2; ding.visible = k >= 0 && k < 1; ding.position.y = CT + .6 + k * .25; ding.material.opacity = 1 - k;
    water.visible = T < OBJ.sink.until; });
  const can = add(PROPS.can(), .38, 9.55, CT); can.rotation.y = 1.2; tick(() => { can.visible = !OBJ.can.held; });
  // fridge: a real upper compartment behind a door that swings
  const F = "#f0f2f4";
  st.box(0, 10.1, 0, .78, 1.15, 1.27, F); st.box(.78, 10.12, .04, .06, 1.11, 1.2, "#f6f8fa"); st.box(.84, 11.08, .62, .03, .04, .5, "#9aa3ab");
  st.box(0, 10.1, 1.27, .06, 1.15, .78, F); st.box(0, 10.1, 1.99, .78, 1.15, .06, F); st.box(0, 10.1, 1.27, .78, .05, .78, F); st.box(0, 11.2, 1.27, .78, .05, .78, F);
  st.box(.06, 10.15, 1.27, .012, 1.05, .72, "#fdfbf2");
  for (const z of [1.5, 1.74]) st.box(.07, 10.15, z, .62, 1.05, .02, "#d9dde0");
  [["#e76f51", 10.25, 1.29], ["#f4f1e6", 10.55, 1.29], ["#ffd6e0", 10.9, 1.29], ["#8fb996", 10.35, 1.52], ["#e9c46a", 10.75, 1.52], ["#5aa2ff", 10.5, 1.76]].forEach(([c, fy, fz]) => st.box(.3, fy, fz, .14, .14, .16, c));
  const fdoor = add(piece(m => { m.box(0, 0, 0, .06, 1.15, .78, "#f6f8fa"); m.box(.06, .98, .08, .03, .04, .5, "#9aa3ab");
    [["#e76f51", .2, .5], ["#2a9d8f", .4, .6], ["#e9c46a", .65, .42], ["#5aa2ff", .82, .64]].forEach(([c, u, v]) => m.box(.06, u, v, .012, .05, .05, c)); }), .78, 10.1, 1.27);
  const fglow = pool(1.5, 10.67, .012, 1.1, "#dcecff");
  tick((dt, T, n) => { fdoor.rotation.y = OBJ.fridge.open * 1.5; fglow.material.opacity = OBJ.fridge.open * n * .5; });
  st.box(2.86, 8.86, DT, .28, .28, .05, "#d9cdb8"); [["#e76f51", 2.9, 8.9], ["#f4d35e", 3.0, 8.98], ["#8fb996", 2.98, 8.88], ["#e76f51", 3.04, 9.02]].forEach(([c, fx, fy], k) => st.box(fx, fy, DT + .05 + (k === 3 ? .05 : 0), .08, .08, .07, c));

  // ── lounge: cushions, magazines, floor lamp, a shelf of books, the water cooler
  st.box(5.72, 7.15, .375, .14, .32, .3, C.sand); st.box(5.72, 9.2, .375, .14, .32, .3, C.teal); st.box(8.25, 10.44, .375, .32, .14, .3, C.sand);
  st.box(7.05, 7.85, .3125, .32, .24, .02, "#e76f51"); st.box(7.1, 7.9, .3325, .3, .22, .016, "#f6f1e8"); st.box(7.5, 8.3, .3125, .12, .12, .1, "#f5f5f2");
  st.box(8.94, 7.04, .0625, .04, .04, 1.5, DARK);
  add(piece(m => { m.box(-.16, -.16, 0, .32, .32, .1, "#fff"); m.box(-.13, -.13, .1, .26, .26, .1, "#fff"); m.box(-.1, -.1, .2, .2, .2, .08, "#fff"); }, shadeMat), 8.96, 7.06, 1.5);
  for (let r = 0; r < 4; r++) { const z = .06 + r * .375; st.box(5.25, 6.5, z, 1.4, .035, .025, shade(C.wood, -.3));
    for (let b = 0; b < 9; b++) { const u = .04 + b * .105, h = (.13 + ((b * 7 + r * 3 + 52) % 5) * .015) * 1.5;
      if ((b + r * 3) % 7 === 6) continue;
      st.box(5.25 + u * 1.4, 6.5, z + .025, .112, .028, h, ["#e76f51", "#2a9d8f", "#e9c46a", "#5a7bbf", "#8d6cab", "#f4a261"][(b + r * 2) % 6]); } }
  gl.box(9.68, 5.26, .8125, .22, .22, .34, "#78b4f0"); st.box(9.74, 5.32, 1.1525, .1, .1, .04, "#5a8fd0"); st.box(9.96, 5.33, .52, .035, .07, .05, "#5aa2ff");

  // ── review table, call booths (glass doors, a strip that goes green on a call), ping-pong
  [[10.45, 6.05, "#fff"], [10.62, 6.12, "#f6f6f0"], [11.05, 6.5, "#fff"]].forEach(([px, py, c], k) => st.box(px, py, DT + k * .004, .3, .22, .008, c));
  [[10.95, 6.0, "#ffe27a"], [11.1, 6.05, "#ffb3c6"], [11.25, 6.0, "#9ee6c0"]].forEach(([px, py, c]) => st.box(px, py, DT, .1, .1, .008, c));
  }
  for (const b of BOOTHS) { gl.box(b.x + .06, b.y + 1.085, 0, .99, .02, 2.12, GLASS); st.box(b.x + .12, b.y + 1.07, 1.0, .03, .05, .22, "#9aa3ab");
    st.box(b.x + .15, b.y + .12, .9, .5, .28, .04, "#8c96a3");                                             // a small shelf inside
    const strip = add(glowBox(.9, .04, .05, "#58606a"), b.x + .1, b.y + 1.07, 2.14); tick(() => strip.material.color.set(b.busy ? "#3fe08a" : "#58606a")); }
  { const { st } = shifted(0, SY);
  st.box(10.3, 10.335, DT, 1.8, .03, .004, "#fff"); st.box(10.3, 9.9, DT, 1.8, .02, .004, "#fff"); st.box(10.3, 10.78, DT, 1.8, .02, .004, "#fff");
  st.box(11.19, 9.85, DT, .02, 1.0, .12, "#f4f4f4"); st.box(11.17, 9.83, DT, .06, .04, .14, DARK); st.box(11.17, 10.83, DT, .06, .04, .14, DARK); }
  const ball = add(piece(m => m.box(-.025, -.025, -.025, .05, .05, .05, "#fff8e8")), 0, 0, 0);
  tick(() => { const b = OBJ.ball; ball.visible = !!b; if (b) at(ball, b.x, b.y, b.z + .03); });

  // ── plants: three species, grown from each plant's seed; they sway, and perk up when watered
  for (const p of OBJ.plants) {
    const r = mulberry(p.seed + 7), s = p.s, L = [C.leaf, C.leaf2, shade(C.leaf, -.14)], zp = snap(p.z);
    st.box(p.x - .11 * s, p.y - .11 * s, zp, .22 * s, .22 * s, .012, "#4a3526");
    const fol = add(piece(m => {
      if (p.seed % 3 === 0) { m.box(-.02, -.02, 0, .04, .04, .22 * s, "#6b4a2b");                    // a bush
        for (let i = 0; i < 20; i++) { const a = i * 2.4, rad = (.04 + r() * .15) * s, q = Math.max(VX, snap((.1 + r() * .08) * s));
          m.box(Math.cos(a) * rad - q / 2, Math.sin(a) * rad - q / 2, (.1 + i * .028) * s, q, q, q, L[i % 3], { ao: 1 }); } }
      else if (p.seed % 3 === 1) { m.box(-.025, -.025, 0, .05, .05, .8 * s, "#6b4a2b");               // a fiddle-leaf: a trunk and broad leaves
        for (let i = 0; i < 10; i++) { const a = i * 2.2 + r(), w = (.2 - i * .008) * s;
          m.box(Math.cos(a) * .12 * s - w / 2, Math.sin(a) * .12 * s - w / 2, (.25 + i * .065) * s, w, w, .05 * s, L[i % 3], { ao: 1 }); }
        m.box(-.07 * s, -.07 * s, .88 * s, .14 * s, .14 * s, .1 * s, L[1]); }
      else for (let i = 0; i < 9; i++) { const a = i * .8 + r(), rad = (.03 + r() * .08) * s, h = (.35 + r() * .5) * s, w = .05 * s, bx = Math.cos(a) * rad - w / 2, by = Math.sin(a) * rad - w / 2;   // snake plant: upright blades
        m.box(bx, by, 0, w, w, h, L[i % 3]); m.box(bx, by, h, w, w, .04 * s, "#c9d88a", { ao: 1 }); }
    }, MAT.tint("#fff")), p.x, p.y, zp);
    tick((dt, T) => { fol.rotation.z = Math.sin(T * .9 + p.seed % 7) * .035; fol.material.color.setScalar(1 + clamp(1 - (T - p.watered) / 20, 0, 1) * .25); });
  }

  { const { st, add } = shifted(EX, 0);                              // the patio, moved east like the 2D plan
  // ── patio: striped umbrellas, lounger pads, heater, bar cart, ashtray, railings, the glass wall and its door
  for (const [cx, cy, uc] of [[16.8, 2.8, C.teal], [16.9, 8.3, C.sand]]) {
    st.box(cx - .03, cy - .03, DT, .0625, .0625, 1.42, C.metal);
    for (let i = 0; i < 8; i++) st.box(cx - 1 + i * .25, cy - 1, 2.125, .25, 2, .09, i % 2 ? shade(uc, .32) : uc, { ao: 1 });
    [[1.5, 2.215], [1.0, 2.305], [.5, 2.395]].forEach(([sz, z], k) => st.box(cx - sz / 2, cy - sz / 2, z, sz, sz, .09, k % 2 ? uc : shade(uc, .32), { ao: 1 }));
    st.box(cx - .05, cy - .05, 2.485, .1, .1, .12, C.metal);
  }
  for (const [ly, c] of [[4.6, C.teal], [5.75, C.sand]]) { st.box(18.7, ly + .06, .25, 1.2, .48, .045, c); st.box(19.95, ly + .06, .5625, .2, .48, .035, c); }
  st.box(19.21, 7.96, .0625, .08, .08, 1.45, DARK); st.box(19.0, 7.75, 1.56, .5, .5, .06, "#4a525c"); st.box(19.12, 7.87, 1.62, .26, .26, .08, "#4a525c");
  add(glowBox(.2, .2, .12, "#ff7a32"), 19.15, 7.9, 1.42);
  for (const [px, py] of [[14.9, 10.55], [15.76, 10.55], [14.9, 10.96], [15.76, 10.96]]) { st.box(px, py, 0, .04, .04, .76, C.metal); st.box(px - .01, py - .01, 0, .06, .06, .06, DARK); }
  [[15.05, "#2a9d8f"], [15.25, "#e9c46a"], [15.45, "#e76f51"], [15.62, "#f4f1e6"]].forEach(([bx, c]) => { st.box(bx - .035, 10.72, .6875, .07, .07, .2, c); st.box(bx - .015, 10.74, .8875, .03, .03, .08, c); });
  st.box(15.0, 10.62, .1875, .3, .2, .14, "#b9895a"); st.box(20.28, 10.57, .8125, .27, .27, .03, "#555"); }
  const rail = (x0, y0, x1, y1) => { const n = Math.round(Math.hypot(x1 - x0, y1 - y0)), dx = (x1 - x0) / n, dy = (y1 - y0) / n;
    for (let i = 0; i <= n; i++) st.box(x0 + dx * i - .025, y0 + dy * i - .025, 0, .05, .05, .9, C.metal);
    st.box(Math.min(x0, x1) - .03, Math.min(y0, y1) - .03, .9, Math.abs(x1 - x0) + .06, Math.abs(y1 - y0) + .06, .05, "#8f9aa4");
    gl.box(Math.min(x0, x1) - .01, Math.min(y0, y1) - .01, .06, Math.abs(x1 - x0) + .02, Math.abs(y1 - y0) + .02, .82, GLASS); };
  rail(WALL, Y, X, Y); rail(X, 0, X, Y); rail(WALL, 0, X, 0);
  // glass partitions (the patio wall, with its door; the two offices): pane, posts, top and bottom rails
  const glassWall = (x0, y0, x1, y1) => { const vx = x0 === x1, L = vx ? y1 - y0 : x1 - x0;
    vx ? gl.box(x0 - .01, y0, 0, .02, L, 2.6, GLASS) : gl.box(x0, y0 - .01, 0, L, .02, 2.6, GLASS);
    for (const z of [0, 2.6]) vx ? st.box(x0 - .03, y0, z, .06, L, z ? .06 : .05, C.metal) : st.box(x0, y0 - .03, z, L, .06, z ? .06 : .05, C.metal);
    for (let k = 0; k <= Math.ceil(L / 1.15); k++) { const t = Math.min(k * 1.15, L); vx ? st.box(x0 - .03, y0 + t - .025, 0, .06, .05, 2.6, C.metal) : st.box(x0 + t - .025, y0 - .03, 0, .05, .06, 2.6, C.metal); } };
  glassWall(WALL, 0, WALL, DOOR[0]); glassWall(WALL, DOOR[1], WALL, Y); st.box(WALL - .05, DOOR[0], 2.6, .1, DOOR[1] - DOOR[0], .06, C.metal);
  glassWall(OFFICE.x, 0, OFFICE.x, OFFICE.doors[0][0]); glassWall(OFFICE.x, OFFICE.doors[0][1], OFFICE.x, OFFICE.doors[1][0]);
  glassWall(OFFICE.x, OFFICE.doors[1][1], OFFICE.x, OFFICE.end); glassWall(0, OFFICE.split, OFFICE.x, OFFICE.split); glassWall(0, OFFICE.end, OFFICE.x, OFFICE.end);
  glassWall(BR.x, 0, BR.x, BR.end); glassWall(BR.x, BR.end, BR.door[0], BR.end); glassWall(BR.door[1], BR.end, WALL, BR.end);    // the boardroom
  st.box(BR.door[0], BR.end - .05, 2.6, BR.door[1] - BR.door[0], .1, .06, C.metal);
  for (const [a, b] of OFFICE.doors) st.box(OFFICE.x - .05, a, 2.6, .1, b - a, .06, C.metal);
  // string lights over the patio: grey beads by day, warm at night
  const beadMat = MAT.glow("#cfd3d8"), beads = new Mesher(), wire = [];
  for (const [px, py] of [[WALL + .1, Y - .05], [X - .05, Y - .05], [X - .05, .2]]) st.box(px - .02, py - .02, .9, .04, .04, .85, C.metal);
  for (let t = 0; t <= 1.0001; t += 1 / 22) {
    const [bx, by, bz] = t < .5 ? [WALL + .1 + t * 2 * (X - WALL - .2), Y - .05, 1.62 - Math.abs(Math.sin(t * 2 * Math.PI * 3)) * .14] : [X - .05, Y - .1 - (t - .5) * 2 * (Y - .3), 1.62 - Math.abs(Math.sin((t - .5) * 2 * Math.PI * 4)) * .14];
    beads.box(bx - .03, by - .03, bz - .06, .06, .06, .06, "#fff"); wire.push(new THREE.Vector3(bx, bz, by));
  }
  scene.add(beads.mesh(beadMat, false), new THREE.Line(new THREE.BufferGeometry().setFromPoints(wire), new THREE.LineBasicMaterial({ color: 0x3b414a })));
  const leftovers = [...Array(8)].map(() => { const m = add(PROPS.mug({ mug: "#fff" })); m.material = MAT.tint("#fff"); return m; });   // mugs people left behind
  tick(() => leftovers.forEach((m, i) => { const l = OBJ.leftovers[i]; m.visible = !!l; if (l) { at(m, l.x, l.y, l.z || DT); m.material.color.set(l.col); } }));

  scene.add(st.mesh(), gl.mesh(MAT.glass, false));
  const town = city(scene, tick, sim);

  // ── sky: a gradient dome, a square sun that becomes the moon, stars, slow voxel clouds
  const sky = new THREE.Mesh(new THREE.SphereGeometry(900, 24, 12), new THREE.ShaderMaterial({ side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color() }, bot: { value: new THREE.Color() } },
    vertexShader: "varying float h; void main(){ h = normalize(position).y; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }",
    fragmentShader: "uniform vec3 top; uniform vec3 bot; varying float h; void main(){ gl_FragColor = vec4(mix(bot, top, smoothstep(-.02, .55, h)), 1.); \n#include <colorspace_fragment>\n }" }));
  const orb = new THREE.Mesh(new THREE.BoxGeometry(46, 46, 46), new THREE.MeshBasicMaterial({ fog: false })); orb.position.set(-360, 300, -560);
  const sp = [], sr = mulberry(3); for (let i = 0; i < 500; i++) { const a = sr() * 6.283, e = .05 + sr() * 1.4; sp.push(Math.cos(a) * Math.cos(e) * 850, Math.sin(e) * 850, Math.sin(a) * Math.cos(e) * 850); }
  const stars = new THREE.Points(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(sp, 3)), new THREE.PointsMaterial({ color: 0xffffff, size: 2, sizeAttenuation: false, transparent: true, opacity: 0, fog: false }));
  const cloudMat = new THREE.MeshLambertMaterial({ vertexColors: true, fog: false }), clouds = [], cr = mulberry(9);
  for (let i = 0; i < 14; i++) { const c = piece(m => { for (let k = 0, n = 4 + Math.floor(cr() * 5); k < n; k++) { const w = 10 + cr() * 18, d = 8 + cr() * 12; m.box(-w / 2 + (cr() - .5) * 26, -d / 2 + (cr() - .5) * 12, cr() * 4, w, d, 4 + cr() * 4, "#fff", { ao: .9 }); } }, cloudMat, false);
    c.position.set(-420 + cr() * 840, 40 + cr() * 70, -420 + cr() * 600); c.userData.v = 1.2 + cr() * 2; clouds.push(c); scene.add(c); }
  scene.add(sky, orb, stars);
  scene.fog = new THREE.Fog(0xffffff, 80, 420);

  const K = c => new THREE.Color(c), mix = (a, b, n) => new THREE.Color().lerpColors(a, b, n);
  const DAY = { top: K("#6fb1e6"), bot: K("#dcecf7"), sun: K("#fff3df"), hemi: K("#ffffff"), gnd: K("#c9c2b6"), orb: K("#fff6c9") };
  const NIGHT = { top: K("#040716"), bot: K("#1a2247"), sun: K("#8fa6ff"), hemi: K("#ffe9cf"), gnd: K("#6f6a78"), orb: K("#e6ebf5"), town: K("#39415f") };
  const WHITE = K("#ffffff");
  return { scene, sun,
    update(dt, T, n, cam) {
      sun.intensity = lerp(2.5, .5, n); sun.color.lerpColors(DAY.sun, NIGHT.sun, n);
      hemi.intensity = lerp(1.4, .82, n); hemi.color.lerpColors(DAY.hemi, NIGHT.hemi, n); hemi.groundColor.lerpColors(DAY.gnd, NIGHT.gnd, n);
      for (const { l, p } of lamps) p.intensity = n * (l.kind === "pendant" ? 9 : l.kind === "floor" ? 6 : 4);
      shadeMat.emissiveIntensity = n * .9; beadMat.color.lerpColors(K("#cfd3d8"), K("#ffd98c"), n);
      sky.material.uniforms.top.value.lerpColors(DAY.top, NIGHT.top, n); sky.material.uniforms.bot.value.lerpColors(DAY.bot, NIGHT.bot, n);
      scene.fog.color.lerpColors(DAY.bot, NIGHT.bot, n); orb.material.color.lerpColors(DAY.orb, NIGHT.orb, n); stars.material.opacity = n;
      const tc = mix(WHITE, NIGHT.town, n); town.facade.color.copy(tc); town.flat.color.copy(tc); town.facade.emissiveIntensity = n; cloudMat.color.copy(mix(WHITE, K("#2b3352"), n));
      for (const c of clouds) { c.position.x += c.userData.v * dt; if (c.position.x > 460) c.position.x = -460; }
      north.visible = cam.position.z > -.2; west.visible = cam.position.x > -.2;       // dollhouse: never look at the back of a wall
      for (const f of ticks) f(dt, T, n);
    } };
}

// ── the city: blocks of towers on a street grid, built the same way as ours, with traffic far below
function city(scene, tick, sim) {
  const { X, Y, C } = sim, r = mulberry(11), fa = new Mesher(), rf = new Mesher();
  const N = 8, px = 16, S = N * px, mk = () => Object.assign(document.createElement("canvas"), { width: S, height: S });
  const dayC = mk(), litC = mk(), a = dayC.getContext("2d"), b = litC.getContext("2d"), tr = mulberry(5);
  a.fillStyle = "#fff"; a.fillRect(0, 0, S, S); b.fillStyle = "#000"; b.fillRect(0, 0, S, S);
  for (let j = 0; j < N; j++) { a.fillStyle = "rgba(0,0,0,.07)"; a.fillRect(0, j * px + 14, S, 2);
    for (let i = 0; i < N; i++) { const x = i * px + 3, y = j * px + 3, q = tr();
      a.fillStyle = q < .33 ? "#8fb6d2" : q < .66 ? "#9cc2dc" : "#84abc8"; a.fillRect(x, y, 10, 9); a.fillStyle = "rgba(255,255,255,.4)"; a.fillRect(x, y, 10, 2);
      if (tr() < .3) { b.fillStyle = tr() < .7 ? "#f2c879" : "#bcd9f2"; b.fillRect(x, y, 10, 9); } } }
  const tex = c => { const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.magFilter = THREE.NearestFilter; t.anisotropy = 8; return t; };
  const facade = new THREE.MeshLambertMaterial({ map: tex(dayC), emissiveMap: tex(litC), emissive: 0xffffff, emissiveIntensity: 0, vertexColors: true });
  const flat = new THREE.MeshLambertMaterial({ vertexColors: true });
  const uv = top => ({ top, cw: 1, ch: 1.4, ou: Math.floor(r() * 8), ov: Math.floor(r() * 8) });
  const tree = (x, y, z, s) => { rf.box(x - .12 * s, y - .12 * s, z, .24 * s, .24 * s, .9 * s, "#7a5a3a"); rf.box(x - .6 * s, y - .6 * s, z + .9 * s, 1.2 * s, 1.2 * s, 1.0 * s, "#5c9d6a"); rf.box(x - .38 * s, y - .38 * s, z + 1.9 * s, .76 * s, .76 * s, .6 * s, "#79b884"); };
  const blinks = [];

  rf.box(-420, -420, G - 1, 840 + X, 840 + Y, 1, "#8b96a3", { faces: "U" });                              // streets
  fa.box(0, 0, G, X, Y, -.32 - G, C.facade, { faces: "EWSN", ao: .8, uv: { top: -.32, cw: 1, ch: 1.4, ou: 0, ov: 0 } });   // our tower
  rf.box(-18, -18, G, 46, 46, .25, "#cfd5db");                                                            // our plaza
  for (let i = 0; i < 9; i++) { tree(-14 + i * 4.6, -13, G + .25, 1.3); tree(-14 + i * 4.6, 23, G + .25, 1.3); if (i % 2) { tree(-13, -8 + i * 3.6, G + .25, 1.2); tree(25, -8 + i * 3.6, G + .25, 1.2); } }
  const lines = []; for (let v = -100; v <= 138; v += 14) lines.push(v);                                   // street centre lines
  for (const v of lines) for (let t = -112; t < 138; t += 4) { rf.box(v - .08, t, G, .16, 2, .01, "#dfe5ea", { faces: "U" }); rf.box(t, v - .08, G, 2, .16, .01, "#dfe5ea", { faces: "U" }); }

  for (let bx = -112; bx <= 126; bx += 14) for (let by = -112; by <= 126; by += 14) {
    if (bx < 27 && bx + 10 > -6 && by < 17.5 && by + 10 > -6) continue;                                   // our plaza
    rf.box(bx, by, G, 10, 10, .25, "#c5ccd3");
    const kind = r(), far = Math.hypot(bx + 5 - 10.5, by + 5 - 5.75) > 58;
    if (kind < .1) { rf.box(bx + .5, by + .5, G + .25, 9, 9, .08, "#8fc49a"); for (let k = 0; k < 6; k++) tree(bx + 1.5 + r() * 7, by + 1.5 + r() * 7, G + .3, .9 + r() * .7); continue; }
    const lots = kind < .6 ? [[bx + .7 + r(), by + .7 + r(), 7 + r() * 1.6, 7 + r() * 1.6]] : [[bx + .6, by + .6, 4.1, 6.5 + r() * 2.2], [bx + 5.3, by + .6 + r(), 4.1, 6 + r() * 2]];
    for (const [x, y, w, d] of lots) {
      // we are the tallest thing nearby (you look down on the neighbours' roofs); the skyline rises in the distance
      const roof = Math.max(G + 6, far ? -24 + r() * 18 + (r() > .9 ? 14 : 0) : -9 - r() * 17), tone = r(), glass = tone > .84;
      const c = glass ? "#a9c6dc" : ["#e7ebef", "#dfe4ea", "#ebe7e0", "#d9e0e8", "#e9ddd0", "#cfd9e4"][Math.floor(tone * 7.1) % 6], dk = sim.shade(c, -.12);
      fa.box(x, y, G + .25, w, d, roof - G - .25, c, { faces: "EWSN", ao: .78, uv: uv(roof) });
      rf.box(x, y, roof - .02, w, d, .12, "#aab2bb", { faces: "U" });                                      // roof deck inside a parapet
      for (const [px2, py2, pw, pd] of [[x, y, w, .25], [x, y + d - .25, w, .25], [x, y, .25, d], [x + w - .25, y, .25, d]]) rf.box(px2, py2, roof, pw, pd, .45, dk);
      const top = roof + .1, cx = x + w / 2, cy = y + d / 2, what = r();
      rf.box(x + w - 1.7, y + d - 1.6, top, 1.1, 1, .8, "#b2bac3"); rf.box(x + w - 1.2, y + d - .62, top, .5, .04, .6, "#6f7882");     // stair hatch and its door
      for (let k = 0, n = 2 + Math.floor(r() * 3); k < n; k++) { rf.box(x + .6 + k * .95, y + d - 1.2, top, .65, .65, .4, "#cdd3d9"); rf.box(x + .7 + k * .95, y + d - 1.1, top + .4, .45, .45, .04, "#8d96a0"); }
      if (what < .25) { for (const [lx, ly] of [[-.5, -.5], [.4, -.5], [-.5, .4], [.4, .4]]) rf.box(cx + lx, cy + ly, top, .1, .1, .8, "#7d8790");    // water tower
        rf.box(cx - .6, cy - .6, top + .8, 1.2, 1.2, 1.1, "#a0724a"); rf.box(cx - .65, cy - .65, top + 1.15, 1.3, 1.3, .08, "#7d5636"); rf.box(cx - .45, cy - .45, top + 1.9, .9, .9, .2, "#7d5636"); rf.box(cx - .2, cy - .2, top + 2.1, .4, .4, .15, "#6b4a2f"); }
      else if (what < .45) { rf.box(x + .5, y + .5, top, Math.min(2, w - 1), Math.min(1.4, d - 1), .7, "#b8c0c8"); rf.box(x + .7, y + .7, top + .7, .5, .5, .5, "#8d96a0"); }
      else if (what < .6) { rf.box(cx - .04, cy - .04, top, .08, .08, 3.4, "#7d8790"); rf.box(cx - .3, cy - .02, top + 2.4, .6, .04, .04, "#7d8790"); blinks.push([cx, cy, top + 3.45]); }
      else if (what < .74) { rf.box(x + .4, y + .4, top, w - 2.4, d - 2.2, .05, "#c79a6c");                                             // a roof terrace like ours
        for (let k = 0; k < 2; k++) { const ux = x + 1.3 + k * 2, uy = y + 1.4; rf.box(ux - .03, uy - .03, top, .06, .06, 1.1, "#8d96a0"); rf.box(ux - .6, uy - .6, top + 1.1, 1.2, 1.2, .1, ["#2a9d8f", "#e9c46a"][k]); rf.box(ux - .3, uy - .3, top + 1.2, .6, .6, .1, ["#2a9d8f", "#e9c46a"][k]); } }
      else if (what < .84) { rf.box(x + .5, y + .5, top, w - 2.6, d - 2.4, .06, "#8fc49a"); tree(x + 1.4, y + 1.5, top, .5); tree(x + 2.6, y + 2.3, top, .42); }              // a roof garden
      else if (what < .9 && w > 6) { rf.box(cx - 1.6, cy - 1.6, top, 3.2, 3.2, .04, "#59616c"); rf.box(cx - .7, cy - .9, top + .04, .25, 1.8, .01, "#fff"); rf.box(cx + .45, cy - .9, top + .04, .25, 1.8, .01, "#fff"); rf.box(cx - .7, cy - .12, top + .04, 1.4, .25, .01, "#fff"); }
    }
  }
  const fm = fa.mesh(facade, false), rm = rf.mesh(flat, false); rm.receiveShadow = false; scene.add(fm, rm);

  // rooftop warning lights
  const red = MAT.glow("#ff3b3b"), dots = blinks.map(([x, y, z], i) => { const m = piece(q => q.box(-.09, -.09, 0, .18, .18, .18, "#fff"), red, false); m.userData.k = i; scene.add(at(m, x, y, z)); return m; });
  // traffic: little cars on the streets that do not run under our plaza
  const free = lines.filter(v => v < -18 || v > 28), cr = mulberry(21), CARS = 70;
  const body = piece(m => { m.box(-.45, -.95, .16, .9, 1.9, .42, "#fff"); m.box(-.4, -.5, .58, .8, 1.05, .34, "#6c7683"); for (const [wx, wy] of [[-.48, -.7], [.36, -.7], [-.48, .45], [.36, .45]]) m.box(wx, wy, 0, .12, .3, .3, "#22262c"); }, flat, false).geometry;
  const cars = new THREE.InstancedMesh(body, flat, CARS), lights = new THREE.InstancedMesh(new THREE.BoxGeometry(.8, .12, .08), MAT.glow("#fff3c0"), CARS), o = new THREE.Object3D(), list = [];
  for (let i = 0; i < CARS; i++) { const sp = (3 + cr() * 4) * (cr() < .5 ? 1 : -1);
    list.push({ ax: i % 2, line: free[Math.floor(cr() * free.length)] + (sp > 0 ? .9 : -.9), t: -112 + cr() * 250, sp });
    cars.setColorAt(i, col(["#e76f51", "#f4f1e6", "#2a9d8f", "#e9c46a", "#5a7bbf", "#3b414a", "#c9d2da", "#f4a261"][Math.floor(cr() * 8)])); }
  cars.instanceColor.needsUpdate = true; cars.frustumCulled = lights.frustumCulled = false; scene.add(cars, lights);
  tick((dt, T, n) => {
    for (const d of dots) d.visible = Math.floor(T * .8 + d.userData.k * .37) % 3 === 0;
    lights.visible = n > .3;
    list.forEach((c, i) => { c.t += c.sp * dt; if (c.t > 138) c.t = -112; if (c.t < -112) c.t = 138;
      const x = c.ax ? c.t : c.line, y = c.ax ? c.line : c.t, yaw = (c.ax ? Math.PI / 2 : 0) + (c.sp < 0 ? Math.PI : 0);
      o.position.set(x, G, y); o.rotation.set(0, yaw, 0); o.updateMatrix(); cars.setMatrixAt(i, o.matrix);
      o.translateZ(.98); o.translateY(.34); o.updateMatrix(); lights.setMatrixAt(i, o.matrix); });
    cars.instanceMatrix.needsUpdate = lights.instanceMatrix.needsUpdate = true;
  });
  return { facade, flat };
}
