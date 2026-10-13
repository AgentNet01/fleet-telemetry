// office3d-people.js — the people: cube figures posed by the sim's joint angles, what they hold, and what drifts off them.
// The sim decides everything (where, which clip, which prop); this file only turns p.pose and p.hold into cubes.
import { THREE, lerp, clamp, at, MAT, piece, textSprite, PROPS, UPRIGHT } from "./office3d-vox.js";
import { CT } from "./office3d-world.js";

const D = Math.PI / 180, TH = .30, SH = .40, TO = .42, NK = .03, UA = .25, FA = .23;
const PX = 1 / 45;                                          // the sim's bob is in its own screen px; this many tiles each
const YAW = { SW: 0, SE: Math.PI / 2, NE: Math.PI, NW: -Math.PI / 2 };   // the sim's four facings, as a turn about the vertical
const LIE = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, -Math.PI / 2, 0, "YXZ"));   // on the back, head toward +x (both beds run that way)
const UP = new THREE.Vector3(0, 1, 0), INK = "#1d1d22";
const joint = (parent, x, y, z) => { const g = new THREE.Group(); parent.add(at(g, x, y, z)); return g; };

function buildRig(L, shade) {
  const k = L.scale * .98, rig = { k, boxes: 0, yaw: null, props: {}, sh: [], el: [], hand: [], hip: [], knee: [], eyes: [] };
  const P = (fn, parent, x = 0, y = 0, z = 0) => { const m = piece(fn); rig.boxes += m.userData.boxes; parent.add(at(m, x, y, z)); return m; };
  const root = rig.root = new THREE.Group(), body = rig.body = joint(root, 0, 0, 0), torso = rig.torso = joint(body, 0, 0, 0);
  root.scale.setScalar(k);
  const sleeve = L.cut === "jacket" ? L.top2 : L.top, bare = L.cut === "tee";
  P(m => {                                                   // hips, chest, and what the cut of the top adds
    m.box(-.15, -.09, 0, .3, .18, .1, L.pants); m.box(-.155, -.095, .1, .31, .19, .32, L.top, { ao: .9 }); m.box(-.045, -.045, TO, .09, .09, NK + .01, L.skin);
    if (L.cut === "jacket") { m.box(-.05, .095, .1, .1, .008, .32, L.top2); m.box(-.11, .095, .34, .06, .01, .08, shade(L.top, -.12)); m.box(.05, .095, .34, .06, .01, .08, shade(L.top, -.12)); }
    if (L.cut === "hoodie") { m.box(-.045, .095, .3, .012, .008, .1, "#fff"); m.box(.033, .095, .3, .012, .008, .1, "#fff"); m.box(-.09, .095, .13, .18, .008, .09, shade(L.top, -.15)); m.box(-.13, -.14, .33, .26, .07, .12, shade(L.top, -.08)); }
    if (L.cut === "shirt") { m.box(-.075, .095, .36, .055, .008, .06, "#fff"); m.box(.02, .095, .36, .055, .008, .06, "#fff"); m.box(-.006, .095, .12, .012, .006, .22, "#fff"); }
    if (L.cut === "sweater") { m.box(-.157, -.097, .27, .314, .194, .05, shade(L.top, .3)); m.box(-.157, -.097, .1, .314, .194, .03, shade(L.top, -.12)); }
    if (L.cut === "tee") m.box(-.045, .095, .24, .09, .006, .09, L.top2);
  }, torso);
  const head = rig.head = joint(torso, 0, 0, TO + NK), hc = L.hair;
  P(m => {
    m.box(-.17, -.16, 0, .34, .32, .32, L.skin, { ao: .93 });
    const cap = () => m.box(-.18, -.17, .25, .36, .34, .09, hc), back = (z0 = .1) => m.box(-.18, -.175, z0, .36, .09, .25 - z0, hc);
    if (L.beanie) { m.box(-.185, -.175, .2, .37, .35, .15, L.top2); m.box(-.19, -.18, .18, .38, .36, .05, shade(L.top2, -.18)); m.box(-.04, -.04, .35, .08, .08, .06, shade(L.top2, .3)); back(.1); }
    else ({
      crop: () => { cap(); back(); m.box(-.18, .1, .27, .36, .07, .07, hc); },
      side: () => { cap(); back(.08); m.box(-.18, .11, .2, .2, .065, .12, hc); m.box(.16, -.1, .14, .022, .2, .12, hc); },
      bun: () => { cap(); back(); m.box(-.075, -.2, .3, .15, .15, .15, hc); },
      pony: () => { cap(); back(); m.box(-.055, -.25, -.04, .11, .09, .3, hc); },
      afro: () => m.box(-.23, -.22, .13, .46, .44, .3, hc),
      long: () => { cap(); m.box(-.18, -.19, -.14, .36, .1, .4, hc); m.box(-.186, -.1, 0, .03, .2, .26, hc); m.box(.156, -.1, 0, .03, .2, .26, hc); },
      buzz: () => m.box(-.173, -.163, .27, .346, .326, .055, hc),
      curly: () => { cap(); back(); for (let i = 0; i < 6; i++) m.box(-.19 + (i % 3) * .13, -.17 + Math.floor(i / 3) * .2, .32, .12, .12, .07, hc); },
    }[L.hairStyle] || (() => { cap(); back(); }))();
    const blush = new THREE.Color(L.skin).lerp(new THREE.Color("#e86a6a"), .4);
    m.box(-.145, .16, .085, .045, .004, .035, blush); m.box(.1, .16, .085, .045, .004, .035, blush);
    if (L.glasses) { for (const cx of [-.075, .075]) { m.box(cx - .05, .16, .205, .1, .012, .014, INK); m.box(cx - .05, .16, .12, .1, .012, .014, INK); m.box(cx - .05, .16, .12, .014, .012, .1, INK); m.box(cx + .036, .16, .12, .014, .012, .1, INK); }
      m.box(-.025, .16, .17, .05, .012, .014, INK); }
    if (L.phones) { m.box(-.19, -.03, .31, .38, .06, .04, "#2a2d33"); m.box(-.205, -.06, .09, .04, .12, .16, "#2a2d33"); m.box(.165, -.06, .09, .04, .12, .16, "#2a2d33"); }
  }, head);
  for (const cx of [-.075, .075]) rig.eyes.push(P(m => m.box(-.02, 0, -.03, .04, .014, .06, INK), head, cx, .16, .165));
  rig.mouth = P(m => m.box(-.035, 0, -.012, .07, .012, .024, "#6b2a2a"), head, 0, .16, .07);
  for (const side of [-1, 1]) {                             // R is index 0: facing +y, the right hand is at -x
    const sh = joint(torso, side * .2, 0, TO - .03), el = joint(sh, 0, 0, -UA);
    P(m => { m.box(-.047, -.047, -UA, .094, .094, UA, bare ? L.skin : sleeve); if (bare) m.box(-.05, -.05, -.12, .1, .1, .12, sleeve); }, sh);
    P(m => { m.box(-.042, -.042, -FA, .084, .084, FA, bare ? L.skin : sleeve); m.box(-.044, -.044, -FA - .07, .088, .088, .07, L.skin); }, el);
    rig.sh.push(sh); rig.el.push(el); rig.hand.push(joint(el, 0, 0, -FA - .04));
    const hip = joint(body, side * .08, 0, 0), knee = joint(hip, 0, 0, -TH);
    P(m => m.box(-.065, -.065, -TH, .13, .13, TH, L.pants), hip);
    P(m => { m.box(-.06, -.06, -SH + .07, .12, .12, SH - .07, L.pants); m.box(-.065, -.065, -SH, .13, .23, .07, "#1c1f25"); }, knee);
    rig.hip.push(hip); rig.knee.push(knee);
  }
  // a square on the floor under them: red when not answering, blue for hover and for "something just changed"
  rig.ring = piece(m => { for (const [x, y, w, d] of [[-.5, -.5, 1, .07], [-.5, .43, 1, .07], [-.5, -.43, .07, .86], [.43, -.43, .07, .86]]) m.box(x, y, 0, w, d, .012, "#fff"); },
    new THREE.MeshBasicMaterial({ transparent: true, depthWrite: false }), false);
  return rig;
}

// small drifting cubes: steam, smoke, water
class Puffs {
  constructor(scene, n = 300) {
    this.n = n; this.list = []; this.o = new THREE.Object3D();
    this.mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshBasicMaterial({ transparent: true, opacity: .62, depthWrite: false }), n);
    this.mesh.frustumCulled = false; this.mesh.count = 0; scene.add(this.mesh);
  }
  emit(pos, v, o) { if (this.list.length < this.n) this.list.push({ x: pos.x, y: pos.y, z: pos.z, v, age: 0, life: 2, size: .03, grow: .05, g: 0, c: WHITE, ...o }); }
  update(dt) {
    const L = this.list, o = this.o;
    for (let i = L.length - 1; i >= 0; i--) { const s = L[i]; s.age += dt; if (s.age > s.life) { L.splice(i, 1); continue; }
      s.v[1] -= s.g * dt; s.x += s.v[0] * dt; s.y += s.v[1] * dt; s.z += s.v[2] * dt; }
    L.forEach((s, i) => { const k = (s.size + s.grow * s.age) * Math.min(1, (s.life - s.age) / (s.life * .45));
      o.position.set(s.x + Math.sin(s.age * 4 + s.x * 9) * .01, s.y, s.z); o.scale.setScalar(k); o.rotation.y = s.age; o.updateMatrix();
      this.mesh.setMatrixAt(i, o.matrix); this.mesh.setColorAt(i, s.c); });
    this.mesh.count = L.length; this.mesh.instanceMatrix.needsUpdate = true; if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true;
  }
}
const WHITE = new THREE.Color("#ffffff"), SMOKE = new THREE.Color("#c9ccd2"), DROP = new THREE.Color("#5aa0e6");
const RED = new THREE.Color("#d63031"), BLUE = new THREE.Color("#5aa2ff");

export class People {
  constructor(scene, sim) { this.scene = scene; this.sim = sim; this.rigs = new Map(); this.puffs = new Puffs(scene); this.sprites = new Map(); }
  rig(name) { return this.rigs.get(name); }
  drop(name) { const r = this.rigs.get(name); if (!r) return; this.scene.remove(r.root, r.ring); this.rigs.delete(name); }

  update(dt, T, n, hover) {
    const { people, OBJ, PARTS, shade } = this.sim, v = this.v || (this.v = new THREE.Vector3()), q = this.q || (this.q = new THREE.Quaternion()), q2 = this.q2 || (this.q2 = new THREE.Quaternion());
    const chance = rate => Math.random() < rate * dt;
    for (const [name, r] of this.rigs) if (people.get(name) !== r.p) this.drop(name);
    for (const p of people.values()) {
      let r = this.rigs.get(p.name);
      if (!r) { r = buildRig(p.look, shade); r.p = p; this.rigs.set(p.name, r); this.scene.add(r.root, r.ring); }
      const po = p.pose, k = r.k, lie = po.lie || 0, group = (p.slot && p.slot.group) || "";
      // facing: the sim's four directions when still; the way they are actually going when they walk
      let want = YAW[p.dir] ?? 0;
      if (p.path.length && r.px != null && Math.hypot(p.x - r.px, p.y - r.py) > 1e-4) want = Math.atan2(p.x - r.px, p.y - r.py);
      r.yaw = r.yaw == null ? want : r.yaw + (((want - r.yaw) % (2 * Math.PI) + 3 * Math.PI) % (2 * Math.PI) - Math.PI) * (1 - Math.exp(-dt * 12));
      r.px = p.x; r.py = p.y;
      q.setFromAxisAngle(UP, r.yaw); r.root.quaternion.copy(q).slerp(LIE, lie);
      at(r.root, p.x, p.y, (p.z || 0) + lie * .1);
      const seat = /^(sofa|nap)/.test(group) ? .375 : .5, atTable = /^(desk|board|ceo|review|dine|patio)/.test(group);
      const hipH = lerp(TH + SH, (seat + .05) / k, po.sit) + (po.bob || 0) * PX;
      r.body.position.set(0, lerp(hipH, 0, lie), atTable ? po.sit * .14 / k : 0);      // at a table they sit forward, so their hands reach it
      r.torso.rotation.x = po.lean * D;
      r.head.rotation.set(po.ht * .6 * D, (po.hy || 0) * .5, 0);
      [po.aR, po.aL].forEach(([s, e], i) => { r.sh[i].rotation.set(-(s + po.lean) * D, (i ? -1 : 1) * clamp(e / 110, 0, 1) * .38, 0); r.el[i].rotation.x = -e * D; });
      [po.lR, po.lL].forEach(([h, kn], i) => { r.hip[i].rotation.x = -h * D; r.knee[i].rotation.x = -kn * D; });
      const blink = po.eyes < .5 || ((T + p.seed % 50) % 4.3) < .12;
      for (const e of r.eyes) e.scale.y = blink ? .15 : 1;
      r.mouth.scale.y = po.mouth > .15 ? 1 + po.mouth * 2.4 : .6;

      // what is in each hand
      const hold = p.hold || {};
      ["R", "L"].forEach((side, i) => {
        const kind = PROPS[hold[side]] ? hold[side] : null, cur = r.props[side];
        if ((cur ? cur.kind : null) === kind) return;
        if (cur) r.hand[i].remove(cur.obj);
        r.props[side] = kind ? { kind, obj: PROPS[kind]({ mug: p.look.mug, bookColor: p.bookColor, marker: p.marker }) } : null;
        if (kind) r.hand[i].add(r.props[side].obj);
      });
      r.root.updateMatrixWorld(true);
      ["R", "L"].forEach((side, i) => {
        const pr = r.props[side]; if (!pr) return;
        if (UPRIGHT.has(pr.kind)) {                           // stays level whatever the arm does; a pour tips it
          const tilt = pr.kind === "carafe" ? [0, 0, (i ? 1 : -1) * (po.pour || 0) * 1.1] : pr.kind === "can" ? [(po.pour || 0) * .5, 0, 0] : [0, 0, 0];
          q2.setFromEuler(new THREE.Euler(...tilt)); r.hand[i].getWorldQuaternion(q).invert(); pr.obj.quaternion.copy(q).multiply(r.root.quaternion).multiply(q2);
        } else pr.obj.rotation.set(Math.PI, 0, 0);            // runs on along the forearm
        if (pr.obj.userData.flame) pr.obj.userData.flame.visible = !!po.flame;
        if (pr.obj.userData.level) pr.obj.userData.level.scale.y = Math.max(.02, OBJ.coffee.level);
        const hw = r.hand[i].getWorldPosition(v), fx = Math.sin(r.yaw), fz = Math.cos(r.yaw);
        const hot = T - (p.hotSince ?? -99);
        if ((pr.kind === "mug" && hot < 90) || ((pr.kind === "plate" || pr.kind === "takeout") && hot < 60)) { if (chance(3)) this.puffs.emit({ x: hw.x, y: hw.y + .12, z: hw.z }, [0, .22, 0], { life: 1.7 }); }
        if (pr.kind === "cig" && chance(2.5)) this.puffs.emit({ x: hw.x, y: hw.y + .04, z: hw.z }, [(Math.random() - .5) * .05, .2, (Math.random() - .5) * .05], { life: 2.3, grow: .08, c: SMOKE });
        if (pr.kind === "can" && po.pour > .5 && chance(16)) this.puffs.emit({ x: hw.x + fx * .22, y: hw.y + .06, z: hw.z + fz * .22 }, [fx * .5, 0, fz * .5], { life: .5, size: .028, grow: 0, g: 4, c: DROP });
      });
      if (po.exhale && !r.puffed) { r.head.localToWorld(v.set(0, .09, .2)); for (let i = 0; i < 5; i++) this.puffs.emit(v, [Math.sin(r.yaw) * (.2 + i * .06), .08, Math.cos(r.yaw) * (.2 + i * .06)], { life: 2.4, size: .04, grow: .1, c: SMOKE }); }
      r.puffed = !!po.exhale;

      // the square under them
      const pulse = p.pulse != null && T - p.pulse < 2 ? (T - p.pulse) / 2 : null, ring = r.ring, rm = ring.material;
      ring.visible = p === hover || !!p.flag || pulse != null;
      if (ring.visible) { at(ring, p.x, p.y, (p.lying ? p.z : 0) + .03);
        if (p === hover) { ring.scale.setScalar(.7); rm.color.copy(BLUE); rm.opacity = .95; }
        else if (p.flag) { ring.scale.setScalar(.62 + .03 * Math.sin(T * 4)); rm.color.copy(RED); rm.opacity = .6 + .3 * Math.sin(T * 4); }
        else { ring.scale.setScalar(.5 + pulse * 1.4); rm.color.copy(BLUE); rm.opacity = 1 - pulse; } }
    }
    // steam from the machines
    if (OBJ.coffee.state === "brewing" && chance(6)) this.puffs.emit({ x: .36, y: CT + .58, z: 6.34 }, [(Math.random() - .5) * .08, .28, 0], {});
    if (OBJ.micro.run && chance(2)) this.puffs.emit({ x: .4, y: CT + .42, z: 8.65 }, [0, .2, 0], {});
    this.puffs.update(dt);

    // the sim's speech bubbles and sleepy z's, above whoever they belong to
    const live = new Set();
    for (const s of PARTS) {
      if ((s.kind !== "bubble" && s.kind !== "z") || !s.follow) continue;
      const r = this.rigs.get(s.follow.name); if (!r) continue;
      let sp = this.sprites.get(s);
      if (!sp) { sp = s.kind === "z" ? textSprite("z", .22, { fg: "#3d4a63", bg: null, px: 40 }) : textSprite(s.glyph, .3, { fg: "#333", bg: "rgba(255,255,255,.96)", px: 34, radius: 16, pad: 12 }); this.sprites.set(s, sp); this.scene.add(sp); }
      live.add(s);
      const age = clamp((T - s.born) / (s.life || 2.5), 0, 1); r.head.localToWorld(v.set(0, .16, 0));
      if (s.kind === "z") { sp.position.set(v.x + .15 + age * .3, v.y + .2 + age * .6, v.z); sp.material.opacity = 1 - age; }
      else { sp.position.set(v.x, v.y + .52, v.z); sp.material.opacity = age < .1 ? age * 10 : age > .8 ? (1 - age) * 5 : 1; }
    }
    for (const [s, sp] of this.sprites) if (!live.has(s)) { this.scene.remove(sp); sp.material.map.dispose(); sp.material.dispose(); this.sprites.delete(s); }
  }
}
