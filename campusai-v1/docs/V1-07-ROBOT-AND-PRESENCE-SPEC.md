# V1-07 — Robot Character and Presence Detection

Files covered: `frontend/robot.js`, `frontend/presence.js`. Colours reference `V1-08` tokens. Constants reference `constants.js` (`C`, defined in V1-06 §1).

# Part 1 — The robot (`robot.js`)

## 1.1 What it is
A flat, illustrated robot (head with antenna, visor with two LED eyes, speaker-grille mouth of five bars, small neck and chest with a status LED), drawn as **one inline SVG** and animated with a `requestAnimationFrame` loop. No 3D, no images, no external assets.

## 1.2 Public API
```js
import { C } from "./constants.js";
export function createRobot(mountEl) → {
  setState(name),            // one of the 9 frontend states (V1-06 §3)
  setEyeTarget(face|null),   // {x,y} normalised 0..1 in the UNMIRRORED camera frame, or null
  perkAntenna(),             // triggers the 1.8 s antenna perk
  setAmplitudeSources({ getMicAmp, getPlaybackAmp }),  // functions returning 0..1
}
```
`createRobot` inserts the SVG (§1.3) into `mountEl`, sets initial state `booth_off`, and starts the animation loop. The loop pauses while `document.hidden`.

## 1.3 Exact SVG markup (insert verbatim)
```html
<svg id="robotSvg" viewBox="0 0 200 250" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="CampusAI robot" style="--eye:#5B6B8C">
  <g id="antenna">
    <line x1="100" y1="34" x2="100" y2="12" stroke="#3B4660" stroke-width="4" stroke-linecap="round"/>
    <circle id="antennaTip" cx="100" cy="8" r="7" fill="var(--eye)"/>
  </g>
  <rect x="18" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="168" y="92" width="14" height="44" rx="5" fill="#222B3D" stroke="#3B4660" stroke-width="2"/>
  <rect x="30" y="34" width="140" height="150" rx="26" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <rect x="48" y="60" width="104" height="50" rx="14" fill="#0A0F18"/>
  <g id="eyes">
    <g id="eyeLeft"><g class="eye-inner">
      <circle class="eye-glow" cx="78" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="78" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
    <g id="eyeRight"><g class="eye-inner">
      <circle class="eye-glow" cx="122" cy="85" r="16" fill="var(--eye)" opacity="0.22"/>
      <circle class="eye-core" cx="122" cy="85" r="10" fill="var(--eye)"/>
    </g></g>
  </g>
  <rect x="52" y="122" width="96" height="50" rx="10" fill="#0A0F18"/>
  <g id="mouth">
    <rect class="bar" x="59"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="77"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="95"  y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="113" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
    <rect class="bar" x="131" y="162" width="10" height="4" rx="3" fill="var(--eye)"/>
  </g>
  <rect x="82" y="184" width="36" height="14" rx="4" fill="#2A3346"/>
  <rect x="50" y="198" width="100" height="42" rx="16" fill="#161D2B" stroke="#3B4660" stroke-width="3"/>
  <circle id="chestLed" cx="100" cy="219" r="6" fill="var(--eye)"/>
</svg>
```
The robot's on-screen width is `clamp(220px, 26vw, 360px)` (set in CSS on `#robotMount svg`).

## 1.4 State → appearance (exact)

`--eye` (set with `svg.style.setProperty("--eye", colour)` whenever the state changes):

| State | Eye colour | Eye/glow behaviour | Mouth | Extra |
|---|---|---|---|---|
| `booth_off` | `#5B6B8C` | none | flat | — |
| `idle` | `#5B6B8C` | eyes sweep left–right slowly when no face; blink | flat | antenna sways |
| `noticed` | `#FF8A5B` | eyes look at the face; glow radius +3 | flat | `perkAntenna()` is called by the app on arrival |
| `connecting` | `#3E7BFA` | slow breathing glow (same as `waiting_confirmation`) | flat | — |
| `listening` | `#3E7BFA` | glow radius = `16 + 8 × smoothedMicAmp` | flat | — |
| `thinking` | `#E8A33D` | eye scale pulses 0.85 ↔ 1.10, period 600 ms | flat | — |
| `waiting_confirmation` | `#37C6C0` | slow breathing glow, period 2000 ms | flat | — |
| `speaking` | `#33C481` | steady | **bars follow playback amplitude** | — |
| `error` | `#E5484D` | none; **no blinking** | flat | — |

Chest LED and antenna tip always use the same `--eye` colour. Blinking and the sweep are also disabled when `prefers-reduced-motion: reduce` is set (mouth, colour changes, and glow still work; the antenna perk is applied instantly for 1.8 s without easing).

## 1.5 Animation rules (evaluated every frame; `now` = `performance.now()`)

**Smoothing helper:** `lerp(a, b, k) = a + (b − a) × k`.

**Eye direction.** State variables `lookX`, `lookY`; `lastFaceAt`; `faceTarget`.
- `setEyeTarget(face)`: if `face` → `faceTarget = face; lastFaceAt = now`; else `faceTarget = null`.
- Each frame, the target offsets are:
  - if `faceTarget && now − lastFaceAt < 1500`: `tx = clamp((0.5 − face.x) × 16, −6, 6)`; `ty = clamp((face.y − 0.5) × 10, −4, 4)`. (The camera frame is unmirrored, so a person on the viewer's right — image left — makes the robot look toward the viewer's right.)
  - else if state is `idle` or `booth_off` (and not reduced-motion): `tx = 5 × sin(now / 1800)`, `ty = 0`.
  - else `tx = ty = 0`.
- `lookX = lerp(lookX, tx, 0.15)`; `lookY = lerp(lookY, ty, 0.15)`; apply `transform="translate(lookX lookY)"` on `#eyes`.

**Blink.** `nextBlinkAt = now + random(3000, 6000)` initially and after every blink. When `now ≥ nextBlinkAt` a blink of 160 ms starts: with `p = (now − blinkStart) / 160`, `blinkScale = 1 − 0.9 × (p < 0.5 ? p × 2 : (1 − p) × 2)`; at `p ≥ 1` the blink ends and `nextBlinkAt` is re-drawn. `blinkScale = 1` otherwise (and always 1 in `error`, reduced-motion).

**Eye scale.** For each `.eye-inner`: `style.transformBox = "fill-box"`, `style.transformOrigin = "center"`, `style.transform = scale(pulse, pulse × blinkScale)` where `pulse = 1` except in `thinking`: `pulse = 0.975 + 0.125 × sin(2π × now / 600)` (range 0.85–1.10).

**Glow radius** (`.eye-glow` `r` attribute on both eyes): base 16; `listening`: `16 + 8 × micS` where `micS = lerp(micS, getMicAmp(), 0.25)`; `waiting_confirmation` and `connecting`: `16 + 4 × (0.5 + 0.5 × sin(2π × now / 2000))`; `noticed`: 19; other states 16.

**Mouth.** `ampS = lerp(ampS, state === "speaking" ? getPlaybackAmp() : 0, 0.4)`.
`MULT = [0.6, 0.9, 1.0, 0.85, 0.65]`. For bar `i` (0–4):
`h = 4 + 30 × clamp(ampS × MULT[i] × (0.75 + 0.25 × sin(now / 90 + i × 1.7)), 0, 1)`; set `height = h` and `y = 166 − h`.
When not speaking, `ampS` decays to 0 within ~5 frames, so bars return to 4 px flat.

**Antenna.** `perkAntenna()` sets `perkStart = now`. Each frame: `p = (now − perkStart) / 1800`; `k = p < 0 || p > 1 ? 0 : p < 0.17 ? p / 0.17 : p < 0.67 ? 1 : 1 − (p − 0.67) / 0.33`. Idle sway `sway = 2 × sin(now / 1300)` (0 with reduced-motion). Set `transform="translate(0 ${−6 × k}) rotate(${−14 × k + sway} 100 34)"` on `#antenna`.

**Chest LED.** `opacity = 0.75 + 0.25 × sin(2π × now / 2400)`.

**Performance.** Update SVG attributes only (no layout reads); a single loop; skip work while `document.hidden`.

## 1.6 Robot acceptance checks (also in V1-11)
1. All nine states are visually distinguishable at a glance from 2 m away (eye colour + motion).
2. Bars move only while the robot speaks and are flat within 0.3 s after audio ends.
3. Moving a face left/right makes the eyes follow; leaving the frame returns the eyes to the idle sweep within ~1.5 s.
4. The antenna perks on arrival and returns smoothly.
5. Blinks occur roughly every 3–6 s except in `error`.

---

# Part 2 — Presence detection (`presence.js`)

## 2.1 What it does and does not do
It tells the app **whether a face is present in front of the booth camera**, entirely on the device. It does **not** identify, recognise, count, store, or transmit anything. Frames are handed straight to MediaPipe from the `<video>` element; no canvas copies, no network calls, no storage.

## 2.2 Public API
```js
import { C } from "./constants.js";
export const presence = {
  async init(videoEl, { onArrival, onAbsent, onFace }),  // loads the model, starts the loop; throws on failure
  get state(),   // "absent" | "present"  (initially "absent")
  stop(),        // stops the loop and closes the detector
}
```
- `onFace(face|null)` is called every detection tick with the largest qualifying face as `{x, y}` (centre, normalised 0–1 in the unmirrored frame) or `null`.
- `onArrival()` is called once when the state changes `absent → present`.
- `onAbsent()` is called once when the state changes `present → absent`.

## 2.3 Loading the detector (exact; loaded lazily so a missing vendor folder cannot break the rest of the app)
```js
const { FaceDetector, FilesetResolver } = await import("./vendor/mediapipe/vision_bundle.mjs");
const fileset = await FilesetResolver.forVisionTasks("/vendor/mediapipe/wasm");
detector = await FaceDetector.createFromOptions(fileset, {
  baseOptions: { modelAssetPath: "/vendor/mediapipe/blaze_face_short_range.tflite", delegate: "CPU" },
  runningMode: "VIDEO",
  minDetectionConfidence: C.MIN_DETECTION_CONFIDENCE,
});
```
Vendoring the files is in `V1-09` §5. If `init` throws, the app continues without presence (Tap to Talk still works); it logs the error and shows the toast defined in V1-06 §4.

**Verify at build time (Day 1):** confirm that the vendored `vision_bundle.mjs` exports `FaceDetector` and `FilesetResolver` and that detection runs. If the pinned version `0.10.14` has a different API, use the nearest 0.10.x version that works and record the version in the Day 1 commit message. The behaviour below must not change.

## 2.4 Detection loop
`setInterval(tick, C.DETECT_INTERVAL_MS)`. In `tick`:
1. Skip the tick if `document.hidden` or `videoEl.readyState < 2` or `videoEl.videoWidth === 0`.
2. `result = detector.detectForVideo(videoEl, performance.now())`.
3. For each `d` in `result.detections`: `bb = d.boundingBox` (`originX, originY, width, height` in pixels); `ratio = bb.width / videoEl.videoWidth`. A detection **qualifies** if `ratio >= C.MIN_FACE_WIDTH_RATIO` (this ignores small, distant faces in the crowd behind the visitor).
4. Choose the **largest** qualifying detection (by `bb.width`). `face = { x: (bb.originX + bb.width/2) / videoWidth, y: (bb.originY + bb.height/2) / videoHeight }`, else `null`.
5. Call `onFace(face)`.
6. State machine:
   - Face found: `consecutive += 1; lastFaceAt = now`; if `state === "absent"` and `consecutive >= C.ARRIVAL_CONSECUTIVE` → `state = "present"`; `onArrival()`.
   - No face: `consecutive = 0`; if `state === "present"` and `now − lastFaceAt >= C.ABSENCE_MS` → `state = "absent"`; `onAbsent()`.
7. Wrap the whole tick in `try/catch`; log the first error only; keep running.

Timeline example at defaults: a person steps in → third consecutive detection at ~1.2 s → arrival. They step out → after 6 s without a face → absent. Brief dropouts (< 6 s) while present do not retrigger arrival.

## 2.5 Tuning at rehearsal (values only, never logic)
`MIN_FACE_WIDTH_RATIO` (raise it if people passing behind the visitor trigger greetings; lower it if the person standing at the intended distance is not detected), `ABSENCE_MS`, `GREET_COOLDOWN_MS`, `MIN_DETECTION_CONFIDENCE`. Record any change in the commit message and in the day report.

## 2.6 Presence acceptance checks (also in V1-11)
1. A person standing ~0.7–1.5 m from the camera is detected within ~1.5 s of stopping there.
2. Someone walking past quickly (< 1 s in frame) does not trigger a greeting.
3. A photo of a face held to the camera triggers detection (acceptable — this is detection, not recognition).
4. While idle, the browser's network panel shows **no** image data leaving the machine.
5. The same person standing still after a conversation ended is not greeted again until they leave (≥ 6 s) and return.
