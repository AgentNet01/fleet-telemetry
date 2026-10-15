// office3d.js — the office in 3D. office.js still runs the sim and decides everything; this draws it with three.js,
// owns the camera (orbit, slide, zoom, walk) and, on request, moves the view with your head like a window.
import { THREE, lerp, clamp } from "./office3d-vox.js";
import { buildWorld } from "./office3d-world.js";
import { People } from "./office3d-people.js";
import { createLook } from "./office3d-look.js";

const FOV = 30 * Math.PI / 180, NEAR = .5, FAR = 2400;
const HOME = { yaw: Math.PI / 4, pitch: .42, zoom: 1, target: [13.0, .7, 8.2] };      // the classic corner view (three coords: x, up, y)
const HEAD_GAIN = +new URLSearchParams(location.search).get("officeHead") || 1;      // calibration: how far the view swings per head move
const LEAN = +new URLSearchParams(location.search).get("officeLean") || 3;           // calibration: lean in to 0.7 of your resting distance → zoom 0.7^-LEAN (2.9× at 3)

export function start(wrap, overlay, sim) {
  const cv = Object.assign(document.createElement("canvas"), { id: "office3dcv" }); cv.setAttribute("aria-hidden", "true");
  wrap.insertBefore(cv, overlay);
  const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "high-performance" });
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const world = buildWorld(sim), people = new People(world.scene, sim), camera = new THREE.PerspectiveCamera(30, 1, NEAR, FAR);
  let W = 0, H = 0, ready = false;

  // ── camera rig: where we want to be (goal) and where we are (cur), eased
  const goal = { ...HOME, target: new THREE.Vector3(...HOME.target) }, cur = { ...HOME, target: goal.target.clone() };
  const fitDist = () => { const a = W / Math.max(1, H), t = Math.tan(FOV / 2); return Math.max(16.4 / (t * a), 9.6 / t); };   // the whole floor in frame, whatever the shape
  const limit = () => { goal.pitch = clamp(goal.pitch, .06, 1.5); goal.zoom = clamp(goal.zoom, .45, 9);
    goal.target.set(clamp(goal.target.x, -8, 36), clamp(goal.target.y, 0, 4), clamp(goal.target.z, -8, 26)); };
  const keys = new Set(); let over = wrap.matches(":hover");          // the 3D button is inside the office: the pointer is usually already here
  const typing = e => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  const onKey = e => { if (typing(e) || e.metaKey || e.ctrlKey || !(over || document.fullscreenElement === wrap)) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (!"wasdqe".includes(k) && !k.startsWith("Arrow")) return;
    e.type === "keydown" ? keys.add(k) : keys.delete(k); e.preventDefault(); };
  const enter = () => { over = true; }, leave = () => { over = false; keys.clear(); }, noMenu = e => e.preventDefault();
  addEventListener("keydown", onKey); addEventListener("keyup", onKey); addEventListener("blur", leave);
  wrap.addEventListener("pointerenter", enter); wrap.addEventListener("pointerleave", leave); overlay.addEventListener("contextmenu", noMenu);

  // ── view cube: the room in miniature, turning with the camera. Press a face, edge or corner to stand on that side.
  const viewFrom = ([x, y, z]) => { const a = Math.atan2(x, z) - goal.yaw; if (x || z) goal.yaw += Math.atan2(Math.sin(a), Math.cos(a));   // the short way round
    goal.pitch = Math.max(.16, Math.atan2(y, Math.hypot(x, z))); goal.zoom = 1; goal.target.set(...HOME.target); limit(); };
  const cube = Object.assign(document.createElement("div"), { className: "ocube" }), box = cube.appendChild(document.createElement("div"));
  for (const [name, deg, top] of [["Front", 0], ["Right", 90], ["Back", 180], ["Left", -90], ["Top", 0, 1]]) {
    const f = box.appendChild(document.createElement("div")), s = Math.sin(deg * Math.PI / 180), c = Math.cos(deg * Math.PI / 180);
    f.style.transform = (top ? "rotateX(90deg)" : `rotateY(${deg}deg)`) + " translateZ(36px)";
    for (const row of [1, 0, -1]) for (const col of [-1, 0, 1]) {
      const b = f.appendChild(Object.assign(document.createElement("button"), { type: "button", textContent: row || col ? "" : name }));
      const side = ["front", "right", "back", "left"], i = side.indexOf(name.toLowerCase());      // a side face's left and right columns are the corners it shares with its neighbours
      b.title = "View from " + (top ? ["top", row ? (row > 0 ? "back" : "front") : "", col ? (col < 0 ? "left" : "right") : ""] : [side[i], col ? side[(i + col + 4) % 4] : "", row > 0 ? "high" : ""]).filter(Boolean).join(" ");
      b.setAttribute("aria-label", b.title);
      b.onclick = () => viewFrom(top ? [col, 1, -row] : [s + col * c, Math.max(0, row), c - col * s]);
    }
  }
  wrap.appendChild(cube);

  // ── home: back to the starting view, and "where I sit now" becomes the resting pose the head is measured from
  const home = wrap.appendChild(Object.assign(document.createElement("button"), { type: "button", className: "ofs ohome", title: "Home: the starting view. With Look around on, where you sit now becomes your resting distance.",
    innerHTML: '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true"><path d="M8 1.6 1.5 7.4h1.9v6.3h3.5V9.6h2.2v4.1h3.5V7.4h1.9z" fill="currentColor"/></svg>' }));
  home.setAttribute("aria-label", "Home view"); home.onclick = () => api.reset();

  // ── head and eyes: office3d-look.js measures them; here they move the camera and pick who you are looking at.
  // head x, y: screen half-widths/heights off centre (right, up); z: distance ÷ resting distance (lean in → below 1 → zoom)
  const head = { x: 0, y: 0, z: 1, forced: null };
  let lookBtn = null, eyesBtn = null, gazed = null, cand = null, candAt = 0, heldAt = 0, distNow = 0;
  const paintBtn = () => { if (!lookBtn) return; const s = look.state, seeing = s === "tracking" || s === "lost";
    lookBtn.setAttribute("aria-pressed", String(s !== "off" && !s.startsWith("error")));
    lookBtn.textContent = s === "off" ? "◉ Look around" : s === "starting" ? "◉ Asking for the camera…" : s === "loading" ? "◉ Loading tracker…" : s === "tracking" ? "◉ Looking" : s === "lost" ? "◉ No face in view" : "◉ " + s.slice(6);
    eyesBtn.hidden = !seeing; eyesBtn.setAttribute("aria-pressed", String(!!look.cal));
    eyesBtn.textContent = look.cal ? `◎ Eyes ±${Math.round(look.cal.err)} px` : "◎ Calibrate eyes"; };
  const look = createLook(paintBtn);
  const ring = wrap.appendChild(Object.assign(document.createElement("div"), { className: "ogaze", hidden: true }));     // where the eyes are read to be, as wide as the reading is unsure
  // who the eyes are on: the figure nearest the gaze point, if near enough, once it has stayed the nearest for a quarter second
  function whom(now) {
    const g = look.gaze(), r = g && wrap.getBoundingClientRect(); let best = null, bd = Infinity;
    ring.hidden = !g || !!wrap.querySelector(".ocal");
    if (g) { const k = overlay.width / r.width, x = (g[0] - r.left) * k, y = (g[1] - r.top) * k, unsure = clamp(look.cal.err, 24, 160), reach = clamp(unsure * 1.5, 70, 220) * k;
      ring.style.width = ring.style.height = 2 * unsure + "px"; ring.style.transform = `translate(${g[0] - r.left - unsure}px,${g[1] - r.top - unsure}px)`;
      for (const p of sim.people.values()) { if (!p.scr) continue; const [hx, hy] = p.scr.head, [fx, fy] = p.scr.foot, dx = fx - hx, dy = fy - hy;
        const t = clamp(((x - hx) * dx + (y - hy) * dy) / (dx * dx + dy * dy || 1), 0, 1), d = Math.hypot(x - hx - t * dx, y - hy - t * dy) * (p.name === gazed ? .7 : 1);   // anywhere along the body counts; whoever is already picked holds on a little
        if (d < reach && d < bd) bd = d, best = p.name; } }
    if (best !== cand) cand = best, candAt = now;
    if (cand && now - candAt > 250) gazed = cand, heldAt = now; else if (!cand && now - heldAt > 600) gazed = null;
  }

  // ── one picture
  const Q = new THREE.Quaternion(), v = new THREE.Vector3(), v2 = new THREE.Vector3(), right = new THREE.Vector3(), up = new THREE.Vector3(), back = new THREE.Vector3();
  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight; if (!w || !h || (w === W && h === H)) return;
    W = w; H = h; renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.setSize(w, h, false);
  }
  function aim(dt) {
    const k = 1 - Math.exp(-dt * 10), hk = 1 - Math.exp(-dt * 12);
    box.style.transform = `rotateX(${-cur.pitch}rad) rotateY(${-cur.yaw}rad)`;
    if (keys.size) { const sp = (fitDist() / goal.zoom) * .55 * dt, f = (keys.has("w") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("s") || keys.has("ArrowDown") ? 1 : 0), s = (keys.has("d") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("a") || keys.has("ArrowLeft") ? 1 : 0);
      goal.target.x += (-Math.sin(goal.yaw) * f + Math.cos(goal.yaw) * s) * sp; goal.target.z += (-Math.cos(goal.yaw) * f - Math.sin(goal.yaw) * s) * sp;
      goal.yaw += ((keys.has("e") ? 1 : 0) - (keys.has("q") ? 1 : 0)) * 1.2 * dt; limit(); }
    cur.yaw = lerp(cur.yaw, goal.yaw, k); cur.pitch = lerp(cur.pitch, goal.pitch, k); cur.zoom = lerp(cur.zoom, goal.zoom, k); cur.target.lerp(goal.target, k);
    const h = head.forced || look.head; head.x = lerp(head.x, h[0], hk); head.y = lerp(head.y, h[1], hk); head.z = lerp(head.z, h[2], hk);
    // The screen is a window: a rectangle fixed in the world at the target, facing the orbit direction. The eye is the
    // camera; when the head moves, the eye moves and the frustum skews so the window's edges stay on the screen's edges.
    const dist = distNow = Math.max(2, fitDist() / (cur.zoom * clamp(Math.pow(1 / head.z, LEAN), .5, 8))), cp = Math.cos(cur.pitch);   // leaning in is zooming in
    back.set(Math.sin(cur.yaw) * cp, Math.sin(cur.pitch), Math.cos(cur.yaw) * cp);
    camera.position.copy(cur.target).addScaledVector(back, dist); camera.up.set(0, 1, 0); camera.lookAt(cur.target);
    right.set(1, 0, 0).applyQuaternion(camera.quaternion); up.set(0, 1, 0).applyQuaternion(camera.quaternion);
    const hh = dist * Math.tan(FOV / 2), hw = hh * W / Math.max(1, H), ex = head.x * hw * 1.1 * HEAD_GAIN, ey = head.y * hh * 1.1 * HEAD_GAIN, ez = dist;
    camera.position.copy(cur.target).addScaledVector(back, ez).addScaledVector(right, ex).addScaledVector(up, ey);
    const n = NEAR / ez;
    camera.projectionMatrix.makePerspective((-hw - ex) * n, (hw - ex) * n, (hh - ey) * n, (-hh - ey) * n, NEAR, FAR);
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert(); camera.updateMatrixWorld(true);
    return dist;
  }
  // a sim point (three coords) → overlay canvas px; null when it is behind the eye
  const toScreen = (p, sx, sy) => { v2.copy(p).applyMatrix4(camera.matrixWorldInverse); if (v2.z > -NEAR) return null; v2.applyMatrix4(camera.projectionMatrix); return [(v2.x + 1) / 2 * sx, (1 - v2.y) / 2 * sy]; };
  function frame(dt, T, night, hover) {
    resize(); if (!W) return;
    const now = performance.now(); look.track(now); aim(dt);
    world.update(dt, T, night, camera); people.update(dt, T, night, hover);
    renderer.render(world.scene, camera);
    // where each head and pair of feet landed on screen: office.js hangs the name labels and the click boxes on these
    for (const p of sim.people.values()) {
      const r = people.rig(p.name); p.scr = null; if (!r) continue;
      r.head.localToWorld(v.set(0, .16, 0)); const h = toScreen(v, overlay.width, overlay.height);
      const top = toScreen(v.addScaledVector(up, .3 * r.k), overlay.width, overlay.height)   /* clears the hair, seen from above */, f = toScreen(v.set(p.x, p.lying ? p.z : 0, p.y), overlay.width, overlay.height);
      if (h && top && f) p.scr = { head: h, foot: f, r: Math.hypot(top[0] - h[0], top[1] - h[1]) };
    }
    whom(now); ready = true;
  }

  const api = window.Office3D = {
    frame,
    zoom(k) { goal.zoom *= k; limit(); },
    drag(dx, dy, pan) {
      if (pan) { const u = 2 * (fitDist() / goal.zoom) * Math.tan(FOV / 2) / Math.max(1, H), f = dy * u / Math.max(.35, Math.sin(goal.pitch));    // slide the floor under the cursor
        goal.target.x += -Math.cos(goal.yaw) * dx * u - Math.sin(goal.yaw) * f; goal.target.z += Math.sin(goal.yaw) * dx * u - Math.cos(goal.yaw) * f; }
      else { goal.yaw -= dx * .006; goal.pitch += dy * .005; }
      limit();
    },
    reset() { goal.yaw = HOME.yaw + Math.round((goal.yaw - HOME.yaw) / (2 * Math.PI)) * 2 * Math.PI; goal.pitch = HOME.pitch; goal.zoom = 1; goal.target.set(...HOME.target); look.ground(); },
    look(btn, eyes) { lookBtn = btn; eyesBtn = eyes; look.state === "off" || look.state.startsWith("error") ? look.on() : look.off(); },
    eyes() { if (look.state === "tracking" && !wrap.querySelector(".ocal")) look.calibrate(wrap).then(paintBtn); },
    get gazed() { return gazed; },
    screen: (x, y, z) => toScreen(v.set(x, z, y), overlay.width, overlay.height),   // a sim point → overlay canvas px, for things that aren't people (the shrine's count)
    stop() {
      look.stop(); removeEventListener("keydown", onKey); removeEventListener("keyup", onKey); removeEventListener("blur", leave);
      wrap.removeEventListener("pointerenter", enter); wrap.removeEventListener("pointerleave", leave); overlay.removeEventListener("contextmenu", noMenu);
      for (const p of sim.people.values()) p.scr = null;
      renderer.dispose(); cv.remove(); cube.remove(); home.remove(); ring.remove(); window.Office3D = null;
    },
    debug: {
      state: () => ({ ready, head: look.state, video: look.live, rigs: [...people.rigs.keys()], lean: head.z, eyes: look.f, gazed, gaze: look.gaze(), cal: look.cal,
        cam: { yaw: cur.yaw, pitch: cur.pitch, dist: distNow, target: cur.target.toArray() } }),
      project: (x, y, z) => { const s = toScreen(v.set(x, z, y), W, H); return s; },
      head: name => { const p = sim.people.get(name); return p && p.scr && [p.scr.head[0] * W / overlay.width, p.scr.head[1] * H / overlay.height]; },
      rig: name => { const r = people.rig(name); return r && { x: r.root.position.x, y: r.root.position.z, parts: r.boxes }; },
      probe: () => { const d = distNow, at = t => toScreen(v.copy(cur.target).addScaledVector(back, t * d), W, H); return { plane: at(0), near: at(.3), far: at(-.3) }; },
      setHead: (x, y, z) => { head.forced = x == null ? null : [x, y || 0, z || 1]; },
      setEyes: f => { look.forced = f; },           // the eye reading to use instead of the camera's, [P.x, P.y, yaw, pitch]; null hands back to the camera
      view: o => { if (o.target) goal.target.set(...o.target); for (const k of ["yaw", "pitch", "zoom"]) if (o[k] != null) goal[k] = o[k]; if (o.dist) goal.zoom = fitDist() / o.dist; limit(); },
      sample: () => { renderer.render(world.scene, camera); const gl = renderer.getContext(), px = new Uint8Array(4), seen = new Set();
        for (let j = 1; j < 20; j++) for (let i = 1; i < 20; i++) { gl.readPixels(Math.floor(gl.drawingBufferWidth * i / 20), Math.floor(gl.drawingBufferHeight * j / 20), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); seen.add((px[0] >> 3) << 10 | (px[1] >> 3) << 5 | px[2] >> 3); }
        return seen.size; },
    },
  };
  return api;
}
