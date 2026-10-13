# Office in 3D: a voxel world you can look around

## Goal
The Overview's office has a 3D switch. On, the same live office (same sim, same truth from
`api/board`) is drawn by three.js as a voxel world: cube-built people, furniture, building and city,
with real light and shadow, day and night. The view can be orbited, panned, zoomed and walked, and a
"Look around" button uses the webcam so moving your head shifts the view like a window. Labels,
tooltip, HUD, ticker and click-to-open work as before. Off, the 2D office is exactly as it was.

## Context
- `hub/office.js`: one IIFE holding the sim (slots, routines, poses: lines ~389-1115) and the 2D
  paint. It gains only hooks: record each `solid()` box, export sim state on `Office.sim`, hand the
  frame to `window.Office3D` when present, and route wheel/drag/reset to it.
- `hub/office3d.js` (entry: renderer, camera rig, head tracking), `hub/office3d-world.js` (building,
  furniture, city, sky, light), `hub/office3d-people.js` (cube rigs, props, particles): new.
- `hub/three.module.min.js`: three.js r160, vendored (one file, MIT).
- `hub/dashboard.html`: two buttons in `.obtns` (`#o3d`, `#ohead`). `hub/hub.py`: the `/office.js`
  route also serves the new files.
- Match: `test_ui.py` (`seeded()`, Playwright Chromium, screenshots to `hub/ui-shots/`), plain asserts.
- Decision (Jack): three.js, real 3D, webcam head tracking, free camera; display only.
- Decision: 2D stays the default; the 3D choice is remembered in `localStorage.office3d`.
- Decision: head view is an off-axis frustum (the screen is a window), not a camera rotation.
- Decision: the face tracker (MediaPipe face detector, ~10 MB wasm) loads from its CDN only when
  "Look around" is pressed, instead of living in git; video never leaves the browser. If it cannot
  load or the camera is refused, the button says so and the mouse camera still works.
- Decision: `test_ui.py` is left out of the suite: it already fails at HEAD (it waits for an agent row inside the
  collapsed "All agents" list), checked in a clean checkout of 97e7c76; not caused by this work.
- Decision: `test_office3d.py` launches plain headless Chromium; forcing ANGLE/SwiftShader flags (the first draft)
  dropped the whole page to about one frame a second, so clicks timed out.
- Decision: world units are the sim's tiles (x → X, y → Z, height z → Y), so nothing is re-laid-out.

## Must Not Change
- The sim: where agents go, what they do, slots, routines, timings, the ticker's lines.
- `hub.py` behaviour beyond serving three more static files; `hub.db`; the live hub (no deploy here).
- The 2D office when the switch is off.

## Steps
- [ ] Step 1: Write each Done When example's test with `f01-test-driven-development` in
  `test_office3d.py` (modes toggle, people, camera, head, webcam, shots).
  - check: `python3 /Users/jacc/.claude/skills/f01-plan/scripts/run_plan.py /Users/jacc/Desktop/Fleet/fleet-telemetry/hub/PLAN5.md red done`
  - on fail: rewrite the test until it fails with its `fails with:` text, redo Step 1.
- [x] Step 2: Hooks in `office.js`, buttons in `dashboard.html`, routes in `hub.py`, vendored three.js,
  and the voxel world (building, floors, walls, furniture, live objects, city, sky, day/night).
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py toggle`
  - on fail: read the assertion and the browser console it prints; fix the loader or world, redo Step 2.
- [x] Step 3: Cube-rig people driven by the sim's poses, props in hands, particles, labels and click.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py people`
  - on fail: fix the rig or the label projection, redo Step 3.
- [x] Step 4: Free camera: drag to orbit, shift/right-drag to pan, wheel to zoom, WASD to walk, Fit to reset.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py camera`
  - on fail: fix the camera rig or the input routing in `office.js`, redo Step 4.
- [x] Step 5: Head-coupled view: off-axis frustum from a head position; webcam face tracker behind `#ohead`.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py head && python3 test_office3d.py webcam`
  - on fail: fix the frustum math or the tracker start/stop, redo Step 5.
- [x] Step 6: Look pass: shoot day, night, close-up and orbit views; fix what reads badly.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py shots`
  - on fail: fix the scene, redo Step 6.

## Done When
- example: Jack presses 3D on the Overview → a WebGL canvas fills the office and shows a lit scene (not blank), the HUD still counts working/on break, and pressing 2D brings the old office back.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py toggle`
  - fails with: "3D switch missing"
- example: in 3D every agent on the board has a cube figure where the sim put it (Ada at a desk), and clicking Ada's figure opens her agent page.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py people`
  - fails with: "3D switch missing"
- example: dragging orbits, the wheel zooms, W walks forward, and Fit puts the view back where it started.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py camera`
  - fails with: "3D switch missing"
- example: the head moves right → things nearer than the screen plane slide left, things beyond it slide right, and the point on the plane stays put.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py head`
  - fails with: "3D switch missing"
- example: Jack presses Look around with a camera attached → the page asks for the camera and the button shows tracking is on; pressing it again turns the camera off.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py webcam`
  - fails with: "3D switch missing"
- example: day, night, close-up and orbit screenshots are saved from the 3D office.
  - check: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && python3 test_office3d.py shots`
  - fails with: "3D switch missing"
- example: someone who has never seen the code looks at `ui-shots/3d-*.png`.
  - criterion: PASS if people, furniture, building and city are all visibly built from cubes with one consistent flat-shaded style, the scene has light and shadow, name labels are readable, and nothing is floating, garbled, flickering-looking or overlapping wrongly; FAIL otherwise.
- suite: `cd /Users/jacc/Desktop/Fleet/fleet-telemetry/hub && node --check office.js && node --check office3d.js && node --check office3d-world.js && node --check office3d-people.js && node --check office3d-vox.js && python3 test_fleet.py dashboard`
- limit: 5 attempts
