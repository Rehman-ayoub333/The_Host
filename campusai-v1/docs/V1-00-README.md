# CampusAI v1 — Specification Package

**Status:** final for build. **Spec date:** 28 September 2026.
**Audience:** the coding agent / developer who will build the product. Every decision is made in these documents. If something seems undecided, that is a defect in the documents — stop and ask; do not improvise.

---

## 1. What CampusAI v1 is (one paragraph)

CampusAI is a booth-based AI assistant that appears on a screen as a small robot. When a visitor walks up, the robot notices them and speaks first. The visitor simply talks to it — no typing, no menus. It can answer questions from a **real class timetable**, check room availability and log facility complaints in a clearly-labelled **demo system** (always asking for confirmation before logging), look up general facts on the web, and look at something the visitor holds up to the camera. Every answer says, out loud and on screen, whether it came from the **real timetable**, the **demo system**, or the **web**.

Tagline: **"See. Hear. Understand. Act."**

## 2. Scope of v1

**In scope (this package specifies all of it):**
1. Real-time two-way voice conversation (Gemini Live API).
2. Robot character on screen with a reactive face (eyes change colour with state, speaker-grille mouth moves with its voice, antenna perks up when it notices someone).
3. Presence detection with the booth's own webcam, fully on-device, and a spoken greeting when someone arrives ("speaks first").
4. Answers about itself ("what are you / what can you do").
5. Real timetable Q&A.
6. Room availability (real timetable + staged demo overrides).
7. Complaint logging with spoken confirmation, complaint status lookup, recent complaints list (demo system).
8. Limited general-knowledge web lookup.
9. One-shot camera vision ("Show It Something").
10. Data-source honesty: spoken + on-screen tags (Real / Demo / Web).
11. Live activity log, recent-actions table, transcript.
12. Booth operations: one-click "Start Booth", auto-reset between visitors, auto-greet toggle, typed-text fallback, reconnect.

**Explicitly NOT in v1 (deferred to a later phase — do not build, do not stub):**
- Recognising or remembering *who* a person is, or "have I seen you before" of any kind.
- Counting people for conversation, unattended-item alerts, crowd alerts, any anomaly detection.
- Commenting on any person's appearance, clothing, mood, or age (this is also a permanent behavioural rule, see V1-04).
- Multilingual behaviour beyond "reply in the language the visitor uses".
- Any connection to real university systems or real CCTV.
- Physical hardware output (printers, lights, servos).
- Photorealistic/3D avatars.
See `V1-12-RISKS-RECOVERY-ROADMAP.md` for the deferred list and why.

## 3. Authority and conflicts with older files in the directory

The output directory already contains older spec packages. They are **superseded history** and must not be used to build v1:

| Folder (already present) | Status |
|---|---|
| `ai-document-detective-spec/` | Superseded (different project idea). Ignore. |
| `campus-concierge-spec/` | Superseded. Ignore. |
| `campus-concierge-spec-v2/` | Superseded. Ignore. |
| `campusai-spec/` (files 00–10) | Superseded by this package. Ignore. |
| `campusai-spec/11-AMBIENT-VISION-SPEC.md` | **Not part of v1.** It describes deferred features (same-day face matching, anomaly alerts). Do not implement anything from it. It is left untouched as a reference for a possible later phase, which would need its own privacy review first. |

**How this package avoids collisions:**
- It lives in its own folder, `campusai-v1-spec/`.
- Every file name starts with `V1-`, so even if files from several packages are copied into one folder, nothing is overwritten.
- It is fully self-contained — it never says "see the previous package". Everything needed (including exact audio capture/playback rules) is written here.
- The project to be built lives in its own root folder, **`campusai-v1/`** (not `campusai/`, not `campus-concierge-agent/`).

**Rule:** if anything in an older folder disagrees with this package, this package wins. The coding agent should not open the older folders at all.

## 4. Reading order

1. `V1-00-README.md` (this file)
2. `V1-01-PRODUCT-DEFINITION.md` — what the product must do, with acceptance criteria (CAP-xx)
3. `V1-02-ARCHITECTURE.md` — components, folders, env vars, constants, flows
4. `V1-03-BACKEND-SPEC.md` — FastAPI backend, WebSocket protocol, Live session handling, data layer
5. `V1-04-PROMPTS-AND-TOOLS.md` — system instruction, greeting prompts, all seven tools
6. `V1-05-TIMETABLE-DATA.md` — timetable schema, normalisation rules, placeholder data, one-time extraction
7. `V1-06-FRONTEND-SPEC.md` — screens, state machine, audio, controls, panels
8. `V1-07-ROBOT-AND-PRESENCE-SPEC.md` — exact robot SVG and animation rules; presence-detection algorithm
9. `V1-08-DESIGN-SYSTEM.md` — colours, type, layout
10. `V1-09-SETUP.md` — accounts, installs, vendoring, running
11. `V1-10-BUILD-PLAN.md` — day-by-day plan with acceptance gates and git rules
12. `V1-11-TEST-PLAN-AND-DEMO-SCRIPT.md` — test cases (TC-xx) and the exhibition script
13. `V1-12-RISKS-RECOVERY-ROADMAP.md` — risks, live recovery, jury review, deferred roadmap

## 5. Rules for the coding agent

1. **No design decisions during coding.** Names, endpoints, message shapes, thresholds, texts, colours, and behaviours are specified. Implement them exactly.
2. **"Verify at build time" items** are the only places where reality (a third-party API) may differ from this document. Each such item states what to check, what to do if it differs, and where to record the difference. They are not open design questions.
3. **If something is genuinely missing or contradictory, stop and ask.** Do not guess. Report which document and section.
4. **Do not add features, tools, endpoints, or dependencies** that are not in this package.
5. **Git rules (mandatory, every phase):**
   - Commit locally at the end of each day's work as specified in `V1-10-BUILD-PLAN.md`, using the commit message given there (or one equally specific).
   - Use real timestamps. Never back-date, never batch several days into one commit.
   - Never squash, rebase, amend published history, or force-push.
   - **Do not push to GitHub until the final step of the build plan.** Then push the full history once.
   - Never commit `.env`, API keys, the SQLite database file, or `__pycache__`.
6. **Secrets:** the Gemini API key exists only in `backend/.env` and is read only in `live_session.py` via `config.py`. It must never appear in any frontend file, log line, or commit.
7. **Stop-and-report checkpoints:** at the end of every day in the build plan, report (a) what was built, (b) the acceptance-gate results, (c) any "verify at build time" item and its outcome, (d) anything unclear. Then wait for confirmation before starting the next day.

## 6. Facts verified while writing this spec (28 Sep 2026)

| Fact | Detail | Consequence in this spec |
|---|---|---|
| Live model | `gemini-3.8-live` is the current recommended Live model; `gemini-3.1-flash-live-preview` is its predecessor | Default model is `gemini-3.8-live`; documented fallback is `gemini-3.1-flash-live-preview` |
| Free tier | Live models take free input/output on the free tier; **rate limits for these models are not published**; free-tier content may be used by Google to improve its products | Zero-cost holds; the UI shows a privacy notice; auto-greet has a cooldown and an off switch; quota errors are handled gracefully |
| SDK | `google-genai` ≥ 2.3.0 | Pinned as `google-genai>=2.3.0` |
| Sending input | Use `session.send_realtime_input(audio=…, video=…, text=…)` for all real-time input. `send_client_content` is only for seeding history on 3.x models | All audio, image, and text input in this spec use `send_realtime_input` |
| Async tools | 3.8 Live has asynchronous function calling on by default | Tools are declared BLOCKING where supported, and the system instruction forbids stating a result before the tool returns (V1-04) |
| Presence detection | MediaPipe Tasks Vision `FaceDetector` (`@mediapipe/tasks-vision`) runs in the browser, free, no key | Vendored into `frontend/vendor/` so it also works if the CDN is slow (V1-09) |
| Web lookup | DuckDuckGo Instant Answer API is free and keyless but limited to "instant answers" | Built with honest limits; the agent says so when nothing is found (V1-04) |

## 7. Defects in the older packages that this package fixes (so they are not repeated)

- Transcript text arrives in **fragments**; older files appended one line per fragment. v1 merges consecutive fragments from the same speaker.
- Older state tables never returned to `listening` after the agent finished speaking. v1 defines `turn_complete → listening`.
- Older files ignored the Live API's `interrupted` signal (visitor talks over the agent). v1 flushes queued audio.
- Older backend spec never handled the `text_input` message that the frontend sent. v1 defines it.
- Older files ran blocking tool code inside the async loop. v1 runs tools in a worker thread.
- Older files never told the model what day and time it is, so "today" could not work. v1 injects the current date and time.
- Older frontend spec referred to another package for audio details. v1 is self-contained.
