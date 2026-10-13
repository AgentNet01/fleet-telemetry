// office3d-look.js — the webcam side of "Look around": where your head is, and where on the screen your eyes point.
// Nothing here draws the office. The video never leaves this browser and is never added to the page; the tracker
// (MediaPipe face landmarks, ~10 MB) is fetched only when asked for.
const VISION = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
const MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
const median = a => [...a].sort((x, y) => x - y)[a.length >> 1];

// ── geometry (pure: test_office3d_look.mjs runs it in node)
// Eyeball model, cm, in the head's own frame (x to the person's left, y up, z out of the face): the iris centre rides a
// sphere of radius EYE_R around the eyeball's centre, and the midpoint of that eye's two corners sits at CORNER from it.
// EYES is the point between the eyes in the tracker's head frame; EYE_GAP the distance between the two eyes.
// These are average-adult values. Calibration absorbs what is off about them for one person.
export const EYE_R = 1.05, CORNER = [0, -.2, .3], EYES = [0, 2.7, 2.5], EYE_GAP = 6.3;

// L: the 478 face landmarks (x, y as fractions of the frame); M: the head's 4×4 pose in the camera's space, column-major
// (x to the image's right, y up, z toward the camera, cm). Returns, as the viewer feels them:
//   head  [right, up, away from the screen] cm from the camera
//   P     where the line of sight meets the camera's plane (≈ the screen), cm right of and above the camera
//   yaw, pitch of the head (rad; right and up positive), open = eyelid gap ÷ eye width (small while blinking)
export function eyes(L, M, vw, vh) {
  const px = i => [L[i].x * vw, -L[i].y * vh], sub = (a, b) => [a[0] - b[0], a[1] - b[1]], len = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], rot = v => [0, 1, 2].map(i => M[i] * v[0] + M[4 + i] * v[1] + M[8 + i] * v[2]);
  const cR = mid(px(33), px(133)), cL = mid(px(362), px(263));                         // each eye's corners; 468 and 473 are the iris centres
  const s = len(cL, cR) / (EYE_GAP * Math.hypot(M[0], M[1]));                          // px per cm at the face, allowing for a turned head
  const uR = sub(px(468), cR), uL = sub(px(473), cL), k = rot(CORNER);
  const e = rot(EYES), o = [M[12] + e[0], M[13] + e[1], M[14] + e[2]], q = [o[0] / -o[2], o[1] / -o[2]];   // o: the eyes in camera space; q: how far off the camera's axis they sit
  // iris − corners, seen in the image, = v.xy + q·v.z where v = EYE_R·sight − CORNER turned by the head (a point nearer the
  // camera than its neighbour is pushed outward by q). Both eyes averaged; solve b = sight.xy + q·sight.z for the unit vector sight.
  const b = [0, 1].map(i => ((uR[i] + uL[i]) / 2 / s + k[i] + q[i] * k[2]) / EYE_R), bq = b[0] * q[0] + b[1] * q[1], qq = 1 + q[0] * q[0] + q[1] * q[1];
  const gz = Math.max(.2, (bq + Math.sqrt(Math.max(0, bq * bq - qq * (b[0] * b[0] + b[1] * b[1] - 1)))) / qq), gx = b[0] - q[0] * gz, gy = b[1] - q[1] * gz, t = -o[2] / gz;
  return { head: [-M[12], M[13], -M[14]], P: [-(o[0] + gx * t), o[1] + gy * t], yaw: -Math.atan2(M[8], M[10]), pitch: Math.asin(clamp(M[9], -1, 1)),
    open: (len(px(159), px(145)) / len(px(33), px(133)) + len(px(386), px(374)) / len(px(362), px(263))) / 2 };
}

// Calibration: you looked at known spots; find the straight-line map from [P.x, P.y] (and, if it helps, head yaw and
// pitch) to screen px. samples: [{ f: [Px, Py, yaw, pitch], s: [x, y] }]. err = typical miss in px, measured honestly:
// each spot is predicted by a fit that never saw it.
const dot = (a, v) => a.reduce((t, x, i) => t + x * v[i], 0);
function solve(rows, ys, n) {                                                          // least squares; a light pull to 0 on the head-angle terms so a still head cannot blow them up
  const A = Array.from({ length: n }, (_, i) => Array.from({ length: n + 1 }, (_, j) => j < n ? rows.reduce((t, r) => t + r[i] * r[j], i === j ? (i > 2 ? .01 : 1e-9) : 0) : rows.reduce((t, r, q) => t + r[i] * ys[q], 0)));
  for (let c = 0; c < n; c++) { let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r; [A[c], A[p]] = [A[p], A[c]];
    for (let r = 0; r < n; r++) if (r !== c) { const m = A[r][c] / A[c][c]; for (let j = c; j <= n; j++) A[r][j] -= m * A[c][j]; } }
  return A.map((r, i) => r[n] / r[i]);
}
export const applyCal = (c, f) => { const v = [1, ...f].slice(0, c.n); return [dot(c.ax, v), dot(c.ay, v)]; };
export function fitCal(samples) {
  const fit = (S, n) => { const rows = S.map(q => [1, ...q.f].slice(0, n)); return { n, ax: solve(rows, S.map(q => q.s[0]), n), ay: solve(rows, S.map(q => q.s[1]), n) }; };
  const miss = n => Math.sqrt(samples.reduce((t, q, i) => { const p = applyCal(fit(samples.filter((_, j) => j !== i), n), q.f); return t + (p[0] - q.s[0]) ** 2 + (p[1] - q.s[1]) ** 2; }, 0) / samples.length);
  const e3 = miss(3), e5 = samples.length > 6 ? miss(5) : Infinity, n = e5 < e3 ? 5 : 3;      // the head-angle terms stay only if they predict unseen spots better
  return { ...fit(samples, n), err: Math.min(e3, e5) };
}

// One Euro filter: heavy smoothing while the value is still (no shimmer), light while it moves (no lag). minCut in Hz; beta = how fast it lets go.
export const euro = (minCut, beta) => { let x = null, dx = 0, t = 0; const a = (cut, dt) => 1 / (1 + 1 / (2 * Math.PI * cut * dt));
  return (val, now) => { if (x === null) { x = val; t = now; return x; } const dt = Math.max(.001, (now - t) / 1000); t = now;
    dx += a(1, dt) * ((val - x) / dt - dx); x += a(minCut + beta * Math.abs(dx), dt) * (val - x); return x; }; };

// ── the tracker
const GROUND = 15;            // frames (about half a second) whose middle value becomes "where you sit": the rest pose everything is measured from
export function createLook(onState) {
  let stream = null, video = null, det = null, token = 0, rest = null, grounding = [], lastFrame = -1, seen = 0, calm = null, recent = [], shift = null;
  const look = { state: "off", head: [0, 0, 1],       // right, up (in units the camera rig scales), and distance ÷ rest distance
    f: null,                                           // the eyes right now: [P.x, P.y, yaw, pitch], smoothed; null while unseen or blinking
    forced: null,                                      // a reading to use instead of the camera's (the browser test's stand-in for moving eyes)
    cal: null, get live() { return !!(stream && stream.getTracks().some(t => t.readyState === "live")); } };
  try { look.cal = JSON.parse(localStorage.officeEyes || "null"); } catch {}
  const set = s => { look.state = s; onState(s); };
  // screen px ↔ this window's px: every mouse event carries both, so the difference is exact wherever the window sits
  const onMouse = e => { shift = [e.screenX - e.clientX, e.screenY - e.clientY]; };
  const offset = () => shift || [screenX + (outerWidth - innerWidth) / 2, screenY + outerHeight - innerHeight];
  addEventListener("pointermove", onMouse, true); addEventListener("pointerdown", onMouse, true);

  look.ground = () => { rest = null; grounding = []; calm = null; recent = []; look.head = [0, 0, 1]; };
  look.off = (state = "off") => {
    token++; if (stream) for (const t of stream.getTracks()) t.stop();
    stream = video = null; if (det) { try { det.close(); } catch {} det = null; }
    look.ground(); look.f = null; set(state);
  };
  look.on = async () => {
    const mine = ++token; set("starting");
    try {
      const s = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: "user" }, audio: false });   // the eyes are a few px wide: take all the camera has
      if (mine !== token) { for (const t of s.getTracks()) t.stop(); return; }
      stream = s; video = Object.assign(document.createElement("video"), { srcObject: s, muted: true, playsInline: true });
      await video.play(); if (mine !== token) return;
    } catch (e) { if (mine === token) look.off("error:Camera unavailable"); return; }
    set("loading");
    try {
      const vis = await import(VISION + "/vision_bundle.mjs"), files = await vis.FilesetResolver.forVisionTasks(VISION + "/wasm");
      const make = delegate => vis.FaceLandmarker.createFromOptions(files, { baseOptions: { modelAssetPath: MODEL, delegate }, runningMode: "VIDEO", numFaces: 1, outputFacialTransformationMatrixes: true });
      const d = await make("GPU").catch(() => make("CPU"));
      if (mine !== token) { d.close(); return; }
      det = d; set("tracking");
    } catch (e) { console.warn("office 3D: face tracker did not load", e); if (mine === token) look.off("error:Tracker did not load"); }
  };
  look.track = now => {
    if (!det || !video || video.readyState < 2 || video.currentTime === lastFrame) return;
    lastFrame = video.currentTime;
    let r; try { r = det.detectForVideo(video, now); } catch { return; }
    const L = r.faceLandmarks && r.faceLandmarks[0], M = r.facialTransformationMatrixes && r.facialTransformationMatrixes[0];
    if (!L || !M) { if (now - seen > 1500 && look.state === "tracking") { set("lost"); look.head = [0, 0, 1]; look.f = null; } return; }
    seen = now; if (look.state === "lost") set("tracking");
    const e = eyes(L, M.data, video.videoWidth, video.videoHeight);
    if (!rest) { grounding.push(e.head); if (grounding.length < GROUND) return;
      rest = [0, 1, 2].map(i => median(grounding.map(h => h[i]))); calm = [euro(.8, 2), euro(.8, 2), euro(.4, 1.5), euro(.4, .03), euro(.4, .03)]; }
    look.head = [calm[0](clamp((e.head[0] - rest[0]) / 18, -1.4, 1.4), now), calm[1](clamp((e.head[1] - rest[1]) / 18, -1.2, 1.2), now), calm[2](clamp(e.head[2] / rest[2], .4, 1.8), now)];
    if (e.open < .1) { look.f = null; return; }                                         // mid-blink the iris is hidden: no reading beats a wrong one
    look.f = [calm[3](e.P[0], now), calm[4](e.P[1], now), e.yaw, e.pitch];
    recent.push({ at: now, f: look.f }); while (recent[0].at < now - 400) recent.shift();
  };
  // the eyes over the last 0.4 s, middle value of each part: one steady reading for a calibration spot
  look.sample = () => look.forced || (recent.length < 5 ? null : [0, 1, 2, 3].map(i => median(recent.map(q => q.f[i]))));
  // where the eyes land, in this window's px; null until calibrated or while unseen
  look.gaze = () => { const f = look.forced || look.f; if (!look.cal || !f) return null; const p = applyCal(look.cal, f), o = offset(); return [p[0] - o[0], p[1] - o[1]]; };

  // nine spots, one at a time; you look at each and click it. Resolves with the calibration, or null if cancelled.
  look.calibrate = wrap => new Promise(done => {
    const veil = wrap.appendChild(Object.assign(document.createElement("div"), { className: "ocal" }));
    const msg = veil.appendChild(document.createElement("div")), spot = veil.appendChild(Object.assign(document.createElement("button"), { type: "button", className: "ocalspot" }));
    const quit = veil.appendChild(Object.assign(document.createElement("button"), { type: "button", className: "ofs", textContent: "Cancel" }));
    const at = [[.5, .5], [.08, .1], [.92, .1], [.92, .9], [.08, .9], [.5, .1], [.92, .5], [.5, .9], [.08, .5]], got = [];
    const place = note => { const [x, y] = at[got.length]; spot.style.left = x * 100 + "%"; spot.style.top = y * 100 + "%";
      msg.textContent = (note || "Keep your head where it is, look at the dot, and click it.") + ` ${got.length + 1} of ${at.length}`; spot.setAttribute("aria-label", `Calibration spot ${got.length + 1} of ${at.length}`); };
    const end = c => { veil.remove(); done(c); };
    quit.onclick = () => end(null);
    spot.onclick = ev => {
      const f = look.sample(); if (!f) return place("Could not see your eyes just then — try again.");
      const r = spot.getBoundingClientRect(); got.push({ f, s: [r.left + r.width / 2 + ev.screenX - ev.clientX, r.top + r.height / 2 + ev.screenY - ev.clientY] });
      if (got.length < at.length) return place();
      look.cal = fitCal(got); try { localStorage.officeEyes = JSON.stringify(look.cal); } catch {}
      end(look.cal);
    };
    place();
  });
  look.stop = () => { look.off(); removeEventListener("pointermove", onMouse, true); removeEventListener("pointerdown", onMouse, true); };
  return look;
}
