// office3d.js — the office in 3D. office.js still runs the sim and decides everything; this draws it with three.js,
// owns the camera (orbit, slide, zoom, walk) and, on request, moves the view with your head like a window.
import { THREE, lerp, clamp } from "./office3d-vox.js";
import { buildWorld } from "./office3d-world.js";
import { People } from "./office3d-people.js";

const FOV = 30 * Math.PI / 180, NEAR = .5, FAR = 2400;
const HOME = { yaw: Math.PI / 4, pitch: .42, zoom: 1, target: [10.2, .7, 5.9] };      // the classic corner view (three coords: x, up, y)
const HEAD_GAIN = +new URLSearchParams(location.search).get("officeHead") || 1;      // calibration: how far the view swings per head move
const VISION = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
const FACE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite";

export function start(wrap, overlay, sim) {
  const cv = Object.assign(document.createElement("canvas"), { id: "office3dcv" }); cv.setAttribute("aria-hidden", "true");
  wrap.insertBefore(cv, overlay);
  const renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: true, powerPreference: "high-performance" });
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  const world = buildWorld(sim), people = new People(world.scene, sim), camera = new THREE.PerspectiveCamera(30, 1, NEAR, FAR);
  let W = 0, H = 0, ready = false;

  // ── camera rig: where we want to be (goal) and where we are (cur), eased
  const goal = { ...HOME, target: new THREE.Vector3(...HOME.target) }, cur = { ...HOME, target: goal.target.clone() };
  const fitDist = () => { const a = W / Math.max(1, H), t = Math.tan(FOV / 2); return Math.max(13.2 / (t * a), 7.6 / t); };   // the whole floor in frame, whatever the shape
  const limit = () => { goal.pitch = clamp(goal.pitch, .06, 1.5); goal.zoom = clamp(goal.zoom, .45, 9);
    goal.target.set(clamp(goal.target.x, -8, 30), clamp(goal.target.y, 0, 4), clamp(goal.target.z, -8, 20)); };
  const keys = new Set(); let over = wrap.matches(":hover");          // the 3D button is inside the office: the pointer is usually already here
  const typing = e => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || e.target.isContentEditable;
  const onKey = e => { if (typing(e) || e.metaKey || e.ctrlKey || !(over || document.fullscreenElement === wrap)) return;
    const k = e.key.length === 1 ? e.key.toLowerCase() : e.key;
    if (!"wasdqe".includes(k) && !k.startsWith("Arrow")) return;
    e.type === "keydown" ? keys.add(k) : keys.delete(k); e.preventDefault(); };
  const enter = () => { over = true; }, leave = () => { over = false; keys.clear(); }, noMenu = e => e.preventDefault();
  addEventListener("keydown", onKey); addEventListener("keyup", onKey); addEventListener("blur", leave);
  wrap.addEventListener("pointerenter", enter); wrap.addEventListener("pointerleave", leave); overlay.addEventListener("contextmenu", noMenu);

  // ── head: x, y in screen half-widths/heights off centre (right, up), z = distance relative to where you sat down
  const head = { x: 0, y: 0, z: 1, tx: 0, ty: 0, tz: 1, state: "off", forced: false, seen: 0 };
  let stream = null, video = null, detector = null, lookToken = 0, neutral = null, lastFrame = -1, lookBtn = null;
  const paintBtn = () => { if (!lookBtn) return; const s = head.state;
    lookBtn.setAttribute("aria-pressed", String(s !== "off" && !s.startsWith("error")));
    lookBtn.textContent = s === "off" ? "◉ Look around" : s === "starting" ? "◉ Asking for the camera…" : s === "loading" ? "◉ Loading tracker…" : s === "tracking" ? "◉ Looking" : s === "lost" ? "◉ No face in view" : "◉ " + s.slice(6); };
  const setState = s => { head.state = s; paintBtn(); };
  function lookOff(state = "off") {
    lookToken++; if (stream) for (const t of stream.getTracks()) t.stop();
    stream = video = null; neutral = null; if (detector) { try { detector.close(); } catch {} detector = null; }
    if (!head.forced) head.tx = head.ty = 0, head.tz = 1;
    setState(state);
  }
  async function lookOn() {
    const token = ++lookToken; setState("starting");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240, facingMode: "user" }, audio: false });
      if (token !== lookToken) { for (const t of s.getTracks()) t.stop(); return; }
      stream = s; video = Object.assign(document.createElement("video"), { srcObject: s, muted: true, playsInline: true });   // never added to the page, never sent anywhere
      await video.play(); if (token !== lookToken) return;
    } catch (e) { if (token === lookToken) lookOff("error:Camera unavailable"); return; }
    setState("loading");
    try {
      const vis = await import(/* the tracker is 10 MB of wasm: fetched only when asked for */ VISION + "/vision_bundle.mjs");
      const files = await vis.FilesetResolver.forVisionTasks(VISION + "/wasm");
      const make = delegate => vis.FaceDetector.createFromOptions(files, { baseOptions: { modelAssetPath: FACE_MODEL, delegate }, runningMode: "VIDEO" });
      const det = await make("GPU").catch(() => make("CPU"));
      if (token !== lookToken) { det.close(); return; }
      detector = det; setState("tracking");
    } catch (e) { console.warn("office 3D: face tracker did not load", e); if (token === lookToken) lookOff("error:Tracker did not load"); }
  }
  function track(now) {
    if (!detector || !video || video.readyState < 2 || video.currentTime === lastFrame) return;
    lastFrame = video.currentTime;
    let faces = []; try { faces = detector.detectForVideo(video, now).detections; } catch { return; }
    const f = faces.map(d => d.boundingBox).sort((a, b) => b.width - a.width)[0];          // the nearest face is the viewer
    if (!f) { if (now - head.seen > 1500 && head.state === "tracking") { setState("lost"); head.tx = head.ty = 0; head.tz = 1; } return; }
    head.seen = now; if (head.state === "lost") setState("tracking");
    const vw = video.videoWidth, vh = video.videoHeight, m = { x: (f.originX + f.width / 2) / vw, y: (f.originY + f.height / 2) / vh, w: f.width / vw };
    if (!neutral) neutral = m;                                                             // wherever you were sitting when it first saw you is "centre"
    head.tx = clamp((neutral.x - m.x) * 3.2, -1.4, 1.4); head.ty = clamp((neutral.y - m.y) * 3.2, -1.2, 1.2); head.tz = clamp(neutral.w / m.w, .6, 1.7);   // the camera sees you mirrored
  }

  // ── one picture
  const Q = new THREE.Quaternion(), v = new THREE.Vector3(), v2 = new THREE.Vector3(), right = new THREE.Vector3(), up = new THREE.Vector3(), back = new THREE.Vector3();
  function resize() {
    const w = wrap.clientWidth, h = wrap.clientHeight; if (!w || !h || (w === W && h === H)) return;
    W = w; H = h; renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1)); renderer.setSize(w, h, false);
  }
  function aim(dt) {
    const k = 1 - Math.exp(-dt * 10), hk = 1 - Math.exp(-dt * 7);
    if (keys.size) { const sp = (fitDist() / goal.zoom) * .55 * dt, f = (keys.has("w") || keys.has("ArrowUp") ? 1 : 0) - (keys.has("s") || keys.has("ArrowDown") ? 1 : 0), s = (keys.has("d") || keys.has("ArrowRight") ? 1 : 0) - (keys.has("a") || keys.has("ArrowLeft") ? 1 : 0);
      goal.target.x += (-Math.sin(goal.yaw) * f + Math.cos(goal.yaw) * s) * sp; goal.target.z += (-Math.cos(goal.yaw) * f - Math.sin(goal.yaw) * s) * sp;
      goal.yaw += ((keys.has("e") ? 1 : 0) - (keys.has("q") ? 1 : 0)) * 1.2 * dt; limit(); }
    cur.yaw = lerp(cur.yaw, goal.yaw, k); cur.pitch = lerp(cur.pitch, goal.pitch, k); cur.zoom = lerp(cur.zoom, goal.zoom, k); cur.target.lerp(goal.target, k);
    head.x = lerp(head.x, head.tx, hk); head.y = lerp(head.y, head.ty, hk); head.z = lerp(head.z, head.tz, hk);
    // The screen is a window: a rectangle fixed in the world at the target, facing the orbit direction. The eye is the
    // camera; when the head moves, the eye moves and the frustum skews so the window's edges stay on the screen's edges.
    const dist = fitDist() / cur.zoom, cp = Math.cos(cur.pitch);
    back.set(Math.sin(cur.yaw) * cp, Math.sin(cur.pitch), Math.cos(cur.yaw) * cp);
    camera.position.copy(cur.target).addScaledVector(back, dist); camera.up.set(0, 1, 0); camera.lookAt(cur.target);
    right.set(1, 0, 0).applyQuaternion(camera.quaternion); up.set(0, 1, 0).applyQuaternion(camera.quaternion);
    const hh = dist * Math.tan(FOV / 2), hw = hh * W / Math.max(1, H), ex = head.x * hw * .6 * HEAD_GAIN, ey = head.y * hh * .6 * HEAD_GAIN, ez = dist * head.z;
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
    track(performance.now()); aim(dt);
    world.update(dt, T, night, camera); people.update(dt, T, night, hover);
    renderer.render(world.scene, camera);
    // where each head and pair of feet landed on screen: office.js hangs the name labels and the click boxes on these
    for (const p of sim.people.values()) {
      const r = people.rig(p.name); p.scr = null; if (!r) continue;
      r.head.localToWorld(v.set(0, .16, 0)); const h = toScreen(v, overlay.width, overlay.height);
      const top = toScreen(v.addScaledVector(up, .3 * r.k), overlay.width, overlay.height)   /* clears the hair, seen from above */, f = toScreen(v.set(p.x, p.lying ? p.z : 0, p.y), overlay.width, overlay.height);
      if (h && top && f) p.scr = { head: h, foot: f, r: Math.hypot(top[0] - h[0], top[1] - h[1]) };
    }
    ready = true;
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
    reset() { goal.yaw = HOME.yaw + Math.round((goal.yaw - HOME.yaw) / (2 * Math.PI)) * 2 * Math.PI; goal.pitch = HOME.pitch; goal.zoom = 1; goal.target.set(...HOME.target); neutral = null; },
    look(btn) { lookBtn = btn; head.state === "off" || head.state.startsWith("error") ? lookOn() : lookOff(); },
    stop() {
      lookOff(); removeEventListener("keydown", onKey); removeEventListener("keyup", onKey); removeEventListener("blur", leave);
      wrap.removeEventListener("pointerenter", enter); wrap.removeEventListener("pointerleave", leave); overlay.removeEventListener("contextmenu", noMenu);
      for (const p of sim.people.values()) p.scr = null;
      renderer.dispose(); cv.remove(); window.Office3D = null;
    },
    debug: {
      state: () => ({ ready, head: head.state, video: !!(stream && stream.getTracks().some(t => t.readyState === "live")), rigs: [...people.rigs.keys()],
        cam: { yaw: cur.yaw, pitch: cur.pitch, dist: fitDist() / cur.zoom, target: cur.target.toArray() } }),
      project: (x, y, z) => { const s = toScreen(v.set(x, z, y), W, H); return s; },
      head: name => { const p = sim.people.get(name); return p && p.scr && [p.scr.head[0] * W / overlay.width, p.scr.head[1] * H / overlay.height]; },
      rig: name => { const r = people.rig(name); return r && { x: r.root.position.x, y: r.root.position.z, parts: r.boxes }; },
      probe: () => { const d = fitDist() / cur.zoom, at = t => toScreen(v.copy(cur.target).addScaledVector(back, t * d), W, H); return { plane: at(0), near: at(.3), far: at(-.3) }; },
      setHead: (x, y, z) => { head.forced = x != null; head.tx = x || 0; head.ty = y || 0; head.tz = z || 1; },
      view: o => { if (o.target) goal.target.set(...o.target); for (const k of ["yaw", "pitch", "zoom"]) if (o[k] != null) goal[k] = o[k]; if (o.dist) goal.zoom = fitDist() / o.dist; limit(); },
      sample: () => { renderer.render(world.scene, camera); const gl = renderer.getContext(), px = new Uint8Array(4), seen = new Set();
        for (let j = 1; j < 20; j++) for (let i = 1; i < 20; i++) { gl.readPixels(Math.floor(gl.drawingBufferWidth * i / 20), Math.floor(gl.drawingBufferHeight * j / 20), 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, px); seen.add((px[0] >> 3) << 10 | (px[1] >> 3) << 5 | px[2] >> 3); }
        return seen.size; },
    },
  };
  return api;
}
