# V1-02 — Architecture

## 1. System overview

```
                    ONE LAPTOP (booth machine)
┌──────────────────────────────────────────────────────────────┐
│  Browser (Chrome/Edge) — served from http://localhost:8000    │
│  ┌────────────┐ ┌────────────┐ ┌──────────────┐              │
│  │ robot.js   │ │ presence.js│ │ audio.js     │  app.js      │
│  │ SVG robot  │ │ MediaPipe  │ │ mic/playback │  (controller,│
│  │ animation  │ │ face detect│ │ PCM in/out   │  state, UI)  │
│  └────────────┘ └────────────┘ └──────────────┘              │
│        ▲ on-device only ▲                 │ WS 1 (ours)      │
└──────────────────────────────────────────┼───────────────────┘
                                            ▼
┌──────────────────────────────────────────────────────────────┐
│  FastAPI backend (same laptop, port 8000)                     │
│  main.py · live_session.py · tools.py · summaries.py          │
│  data.py · normalize.py · prompts.py · schemas.py · config.py │
│        │ WS 2 (google-genai SDK)                │ local        │
└────────┼─────────────────────────────────────────┼────────────┘
         ▼                                         ▼
  Gemini Live API (Google)          data/timetable.json (real, read-only)
  model: gemini-3.8-live            data/campus_ai.db (SQLite: demo data + audit log)
                                    DuckDuckGo Instant Answer API (web_search tool only)
```

**Why a relay backend:** the API key never reaches the browser; tool logic lives in one place (Python); the browser only talks to its own origin.

**Why the frontend is served by the backend:** ES modules, camera/mic access, and the WebSocket all work reliably from `http://localhost:8000` (a secure context). Opening `index.html` from disk is **not** supported.

## 2. Technology (final)

| Layer | Choice |
|---|---|
| Backend | Python 3.11+, FastAPI, Uvicorn, `websockets` |
| AI | Gemini Live API via `google-genai>=2.3.0`, model `gemini-3.8-live` |
| Data | `timetable.json` (real) + SQLite via stdlib `sqlite3` (demo + log) |
| Web lookup | DuckDuckGo Instant Answer API via `httpx` |
| Frontend | Vanilla HTML/CSS/JS with ES modules; no framework, no bundler, no build step |
| Presence | MediaPipe Tasks Vision `FaceDetector`, `blaze_face_short_range`, vendored locally |
| Audio | Web Audio API (`AudioContext`, `ScriptProcessorNode`) |
| Tests | `pytest` (backend data/normalisation/tools) + the manual test plan (V1-11) |

## 3. Folder structure of the project to build

```
campusai-v1/
├── backend/
│   ├── main.py             # app, routes, WS endpoint, static mount, lifespan
│   ├── live_session.py     # one Gemini Live session per browser WS
│   ├── tools.py            # 7 tool functions + TOOL_FUNCTIONS + TOOL_DECLARATIONS
│   ├── summaries.py        # human-readable tool summaries + default sources
│   ├── data.py             # timetable load/query + SQLite access
│   ├── normalize.py        # day/time/room normalisation helpers
│   ├── prompts.py          # system instruction builder, greeting/vision prompts
│   ├── schemas.py          # Pydantic models for WS messages
│   ├── config.py           # env vars + constants (only file that reads env)
│   ├── requirements.txt
│   ├── .env.example
│   ├── tests/
│   │   ├── test_normalize.py
│   │   ├── test_data.py
│   │   └── test_tools.py
│   └── data/
│       ├── timetable.json      # placeholder first, real later (V1-05)
│       ├── demo_data.json      # staged availability overrides
│       └── campus_ai.db        # auto-created; git-ignored
├── frontend/
│   ├── index.html
│   ├── styles.css
│   ├── constants.js        # all frontend thresholds/timings
│   ├── app.js              # controller, state machine, WS, panels
│   ├── audio.js            # mic capture, PCM conversion, playback queue
│   ├── presence.js         # MediaPipe face detection + presence state
│   ├── robot.js            # SVG robot + animation loop
│   └── vendor/mediapipe/   # vision_bundle.mjs, wasm/*, blaze_face_short_range.tflite
├── scripts/
│   └── extract_timetable.py    # one-time PDF → timetable.json (V1-05)
├── docs/                   # copy of this spec package
├── .gitignore
└── README.md
```

`.gitignore` must contain: `.env`, `backend/data/campus_ai.db`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `tmp_vendor/`. The vendored MediaPipe files **are committed**.

## 4. Environment variables (`backend/.env`, read only by `config.py`)

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `GEMINI_API_KEY` | — | **Yes** | Google AI Studio key |
| `GEMINI_LIVE_MODEL` | `gemini-3.8-live` | No | Live model id |
| `GEMINI_VOICE` | `Puck` | No | Prebuilt voice name |
| `TIMETABLE_JSON_PATH` | `./data/timetable.json` | No | Real timetable |
| `DEMO_DATA_JSON_PATH` | `./data/demo_data.json` | No | Staged overrides |
| `DB_PATH` | `./data/campus_ai.db` | No | SQLite file |
| `FRONTEND_DIR` | `../frontend` | No | Static files |
| `PORT` | `8000` | No | HTTP/WS port |

Paths are resolved relative to the `backend/` directory (the working directory when running `uvicorn`).

## 5. Constants (single source of truth)

**Backend (`config.py`):**

| Constant | Value |
|---|---|
| `CONNECT_TIMEOUT_S` | 15 |
| `TOOL_TIMEOUT_S` | 10 |
| `WEB_SEARCH_TIMEOUT_S` | 8 |
| `MAX_TIMETABLE_MATCHES_RETURNED` | 15 |
| `MAX_TEXT_INPUT_CHARS` | 500 |
| `MAX_IMAGE_BASE64_CHARS` | 2_800_000 (~2 MB) |
| `MAX_COMPLAINT_ROOM_CHARS` / `MAX_COMPLAINT_ISSUE_CHARS` | 60 / 200 |
| `RECORDS_DEFAULT_LIMIT` / `RECORDS_MAX_LIMIT` | 10 / 50 |
| `INPUT_AUDIO_MIME` | `audio/pcm;rate=16000` |

**Frontend (`constants.js`, exported as one object `C`):**

| Constant | Value | Meaning |
|---|---|---|
| `AUTO_RESET_MS` | 45000 | idle time before a conversation auto-ends |
| `MAX_SESSION_MS` | 300000 | hard cap per conversation |
| `ERROR_AUTO_RECOVER_MS` | 15000 | time in error state before returning to idle |
| `DETECT_INTERVAL_MS` | 400 | face detection period |
| `ARRIVAL_CONSECUTIVE` | 3 | consecutive detections to count as arrived (~1.2 s) |
| `ABSENCE_MS` | 6000 | no-face time to count as absent |
| `MIN_FACE_WIDTH_RATIO` | 0.08 | ignore faces narrower than 8 % of frame width |
| `MIN_DETECTION_CONFIDENCE` | 0.6 | MediaPipe threshold |
| `GREET_COOLDOWN_MS` | 45000 | min gap between auto-greetings |
| `SNAPSHOT_WIDTH` / `SNAPSHOT_HEIGHT` / `SNAPSHOT_QUALITY` | 640 / 480 / 0.85 | Show It Something |
| `MIC_BUFFER_SIZE` | 4096 | ScriptProcessor buffer |
| `INPUT_SAMPLE_RATE` / `OUTPUT_SAMPLE_RATE` | 16000 / 24000 | PCM rates |
| `ACTIVITY_LOG_MAX_LINES` | 8 | Activity Log length |
| `RECORDS_LIMIT` | 10 | rows requested for Recent Actions |

Tunable-at-rehearsal constants (change value only, never logic): `MIN_FACE_WIDTH_RATIO`, `ABSENCE_MS`, `GREET_COOLDOWN_MS`, `MIN_DETECTION_CONFIDENCE`. Record any change in the commit message.

## 6. Flows

### 6.1 Start Booth (operator, once)
1. Page loads → overlay "Start Booth" over a still robot. Nothing is requested yet.
2. Operator clicks **Start Booth** (the required user gesture).
3. `audio.js` creates the playback `AudioContext` (24 kHz) and `resume()`s it.
4. Request microphone once (`getUserMedia({audio:true})`) purely to trigger the permission prompt, then stop those tracks immediately. If denied → `micAvailable = false` (booth still runs; voice input disabled; typed input works).
5. Request the camera (`getUserMedia({video:{width:640,height:480,facingMode:"user"}})`) and keep the stream for the page lifetime. If denied → `cameraAvailable = false` (no presence, no snapshots; Tap to Talk still works).
6. If the camera is available, `presence.js` loads the vendored MediaPipe model and starts the detection loop.
7. Overlay hides; state → `idle`.

### 6.2 Arrival greeting
1. `presence.js` reports **arrival** (≥ `ARRIVAL_CONSECUTIVE` consecutive detections after being absent).
2. `app.js` checks eligibility (V1-06 §5.3). If eligible: state → `noticed`, robot antenna perks, `startSession("presence")`.
3. Same path as a button start from here on, except the backend uses the *presence* greeting prompt.

### 6.3 Conversation
1. `startSession(trigger)`: acquire the mic stream (no prompt expected), open `WS /ws/session?trigger=presence|button`.
2. Backend opens the Gemini Live session, sends the greeting text via `send_realtime_input(text=…)`, starts the uplink and downlink tasks, sends `state: listening`.
3. Browser streams microphone PCM as binary frames; backend forwards to Gemini as `audio`.
4. Gemini streams back audio chunks, transcription fragments, and tool calls; the backend relays audio (binary) and control messages (JSON).
5. Tool calls are run in a worker thread, results returned to Gemini, and `tool_event` messages (running → done) sent to the browser.
6. The browser plays audio through a gap-free queue, shows the transcript and Activity Log, drives robot animation.

### 6.4 Snapshot
Browser captures one 640×480 JPEG → `{"type":"vision_frame","image_base64":…}` → backend sends it as `video` via `send_realtime_input`, then sends the vision prompt text (V1-04 §3) so the robot describes it immediately.

### 6.5 End of conversation
Triggered by **Done**, 45 s inactivity, the 5-minute cap, or an error. Browser: stop the mic stream, flush playback, close WS, clear timers, state → `idle` (or `error`). Backend: cancel tasks, close the Gemini session. Auto-greet is **disarmed** until presence goes absent (V1-06 §5.3).

## 7. Data-flow and privacy table

| Data | Where it goes | Stored? |
|---|---|---|
| Camera frames for presence detection | Browser memory only (MediaPipe, on-device) | No |
| Face detection results (bounding boxes) | Browser memory only | No |
| Snapshot JPEG (only on button press) | Browser → local backend → Gemini | Not stored by us |
| Microphone audio (only during a conversation) | Browser → local backend → Gemini | Not stored by us |
| Transcript text | Browser memory (cleared per visitor) | No |
| Tool calls + results | Local SQLite `agent_log` | Yes (demo audit trail; contains no faces, no audio, no names) |
| Complaints | Local SQLite `complaints` | Yes (demo data) |

Google's handling of audio/images sent to Gemini on the free tier is stated in the on-screen privacy notice.

## 8. Failure handling (mandatory behaviours)

| Failure | Required behaviour |
|---|---|
| Gemini connect fails / times out (15 s) / quota error | Backend sends `error` message, closes; frontend shows error state + Reconnect; auto-returns to idle after 15 s |
| Gemini drops mid-conversation | Same as above |
| Tool raises or times out (10 s) | Tool result becomes `{"error": "..."}`; agent tells the visitor it couldn't do that; session continues |
| DuckDuckGo slow/unreachable | `web_search` returns `found:false` with an error note; session continues |
| SQLite error | The affected tool returns an error result; session continues |
| `timetable.json` missing/invalid at startup | Backend refuses to start with a clear message (fail fast before the demo, never mid-demo) |
| WebSocket to backend closes unexpectedly | Frontend error state + Reconnect |
| Camera denied/unavailable | No presence, no snapshots; everything else works |
| Microphone denied/unavailable | Text-only conversation; note shown |
| MediaPipe model fails to load | Presence disabled, note shown in the operator area; Tap to Talk works |
| Frontend `/api/records` fails | Silent (console only); panel keeps last content |
| Browser tab hidden/throttled | Not supported; the booth tab must stay visible |
