# V1-09 — Setup

Manual, human steps. Do these once, before Day 1 of `V1-10-BUILD-PLAN.md`.

## 1. Gemini API key
1. Go to Google AI Studio (aistudio.google.com), sign in, create an API key (no card required).
2. Verify the Live model is available:
   ```
   curl "https://generativelanguage.googleapis.com/v1beta/models?key=YOUR_KEY_HERE"
   ```
   Look for `gemini-3.8-live` in the results. If it isn't there, use whichever `*-live*` model is listed, set it as `GEMINI_LIVE_MODEL` in `.env`, and note the change in the Day 2 report (per V1-03 §6.11).

## 2. Python
1. Install Python 3.11+.
2. `cd campusai-v1/backend`
3. `python -m venv .venv`
4. Activate it: `.venv\Scripts\activate` (Windows) or `source .venv/bin/activate` (macOS/Linux).
5. `pip install -r requirements.txt`

## 3. `.env`
`cp .env.example .env` (or copy by hand) and fill in `GEMINI_API_KEY`. Leave everything else at its default unless step 1 required a model change.

## 4. Timetable data
Save the placeholder `timetable.json` and `demo_data.json` from `V1-05` §5 into `backend/data/`. When the real PDF is later provided, follow `V1-05` §6 — this is a data swap, not a rebuild.

## 5. Vendoring MediaPipe (do this once, commit the files)

Create `frontend/vendor/mediapipe/` and `frontend/vendor/mediapipe/wasm/`, then download exactly these files (pinned to `0.10.14`; if unavailable, use the nearest `0.10.x` and record it per `V1-07` §2.3):

```
# from frontend/vendor/mediapipe/
curl -L -o vision_bundle.mjs         https://unpkg.com/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs
curl -L -o wasm/vision_wasm_internal.js         https://unpkg.com/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_internal.js
curl -L -o wasm/vision_wasm_internal.wasm       https://unpkg.com/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_internal.wasm
curl -L -o wasm/vision_wasm_nosimd_internal.js  https://unpkg.com/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_nosimd_internal.js
curl -L -o wasm/vision_wasm_nosimd_internal.wasm https://unpkg.com/@mediapipe/tasks-vision@0.10.14/wasm/vision_wasm_nosimd_internal.wasm
curl -L -o blaze_face_short_range.tflite https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/latest/blaze_face_short_range.tflite
```
If `curl` isn't available, use `npm pack @mediapipe/tasks-vision@0.10.14` and copy `vision_bundle.mjs` + the `wasm/` folder out of the extracted package, or download each URL in a browser and save it to the matching path.

**Verify:** the five files under `wasm/` and `vision_bundle.mjs` exist and are non-empty; `blaze_face_short_range.tflite` is roughly 200 KB. These files **are committed to git** (they are the whole reason for vendoring — no CDN dependency on demo day). Confirm `frontend/vendor/` is **not** in `.gitignore`.

## 6. `.gitignore`
Create the **root-level** `.gitignore` exactly as specified in `V1-02` §3 (`.env`, `backend/data/campus_ai.db`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `tmp_vendor/`). This is the only `.gitignore` file in the project — do not create a second one inside `backend/`. `tmp_vendor/` covers the temporary extraction folder if you use the `npm pack` alternative in §5 above; delete that folder after copying the files out, it should never be committed regardless.

## 7. Running
1. From `backend/` with the venv active: `uvicorn main:app --reload --port 8000`
2. Open `http://localhost:8000/` in Chrome or Edge.
3. Click **Start Booth**; grant camera and microphone permission when prompted.
4. `GET http://localhost:8000/health` should show `"status":"ok"` and the timetable row count.

## 8. Hardware checks (before every rehearsal and on demo day)
- **Microphone:** a USB or lapel mic outperforms a laptop's built-in mic in a noisy hall. Test at the actual distance a visitor will stand.
- **Camera:** confirm the framing catches someone at the expected standing distance; check `MIN_FACE_WIDTH_RATIO` still fits that distance (V1-07 §2.5).
- **Audio output:** use headphones for one-on-one testing to avoid the mic picking up the robot's own voice; for a crowd, keep speaker volume moderate.
- **Lighting:** the dark UI theme should be checked under the actual hall/projector lighting, not just a quiet room.

## 9. Internet backup
No offline mode exists for the Gemini Live connection (V1-01 §5). Arrange a mobile hotspot and test the whole flow over it before the exhibition — see `V1-10` Day 7 and `V1-12` §1.

## 10. Before the exhibition — final checklist
- [ ] `GEMINI_API_KEY` set and the Live model confirmed available.
- [ ] Real timetable swapped in (if available) and human-verified per V1-05 §6, or placeholder data knowingly still in use.
- [ ] `frontend/vendor/mediapipe/` present and committed.
- [ ] Mic and camera tested at real booth distance.
- [ ] Mobile hotspot tested end to end.
- [ ] Full local git history exists; nothing pushed yet (per V1-00 §5, rule 5) until the final build-plan step.
