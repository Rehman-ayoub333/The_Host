# V1-10 — Build Plan

Git rules are in `V1-00` §5 — commit locally every day with the message given below (or one equally specific), real timestamps, no squash/rebase, **no push until the final step of this plan**. Each day ends with a stop-and-report per `V1-00` §5 rule 7. Do not start the next day until the previous day's acceptance gate passes.

## Day 1 — Backend skeleton + frontend shell + vendoring
- Create the folder structure (`V1-02` §3). Root-level `.gitignore` (`V1-09` §6).
- `config.py`, `schemas.py` exactly per `V1-03` §3–4.
- `main.py` with `/health` only (no `/api/records`, no WebSocket yet) and the `lifespan` startup checks (`V1-03` §5.1).
- `data.py`'s `init_db()` and `load_timetable()` only (rest of `data.py` comes Day 3). Save the placeholder `timetable.json`/`demo_data.json` (`V1-05` §5).
- `normalize.py` complete (`V1-05` §3) plus `backend/tests/test_normalize.py` with at least one `assert` per row of the tables in `V1-05` §3.2 and §3.3, plus `time_in_range` and `add_minutes` cases. `pytest` must pass.
- `index.html`, `constants.js`, `styles.css` exactly per `V1-06` §2, `V1-06` §1, and `V1-08` §3. No JS logic yet beyond confirming the page renders with the Start Booth overlay.
- Vendor MediaPipe (`V1-09` §5); verify per `V1-07` §2.3's "verify at build time" note.
- **Acceptance gate:** `uvicorn main:app --reload` starts; `/health` returns the placeholder row count; `pytest` passes; the page loads showing the overlay and the (still) robot SVG with no console errors.
- Commit: `"day 1: backend skeleton, timetable load, normalize.py + tests, frontend shell, vendored mediapipe"`

## Day 2 — Gemini Live round trip (temporary harness, no tools)
- `prompts.py`'s `build_system_instruction` and the two greeting constants (`V1-04` §1), used with a **minimal** system instruction for this day only (skip the tool-related paragraphs) — full text goes in Day 3.
- `live_session.py`: `_start` and the Live config (`V1-03` §6.2–6.3) with **no** `tools=` argument yet.
- A temporary script or test-only route that opens a session, sends one text turn ("Say hello and introduce yourself in one sentence"), and writes the returned audio to a `.wav` file. Play it back and confirm it is real, intelligible speech.
- Do the "verify at build time" check in `V1-03` §6.11 now, while the surface area is small: confirm `send_realtime_input`, `receive()`, and the message field names. Record any differences.
- Pin the exact `google-genai` version in `requirements.txt` (`V1-03` §1).
- **Acceptance gate:** a real `.wav` file with intelligible speech is produced from a live API call (not mocked).
- Commit: `"day 2: gemini live round trip verified, sdk names confirmed"`

## Day 3 — Data layer + all seven tools
- `data.py` complete (`V1-03` §7). `backend/tests/test_data.py`: `query_timetable_data` cases matching the placeholder facts in `V1-05` §5 (e.g. Lab 2 free all Monday; Lab 3 Monday 14:00 booked by Database Systems); `check_override` returns the Lab 1 Monday 15:00 override; `known_room_display` returns `None` for an unknown room.
- `summaries.py` complete (`V1-03` §8).
- `tools.py` complete, all seven tools + registries (`V1-04` §2–4). `backend/tests/test_tools.py`: each tool with valid args, with an unparseable day/time, and with a missing required arg; confirm every result has a `"source"` key; confirm `signal_confirmation_request` never calls `data.log_action` (patch/spy on it).
- Wire `tools=` into the Live config; do the `behavior`/JSON-type "verify at build time" check (`V1-04` §6).
- Extend the Day 2 harness: send text turns that should trigger each tool one at a time; print the tool call, its args, and its result; confirm results match the placeholder data.
- **Acceptance gate:** `pytest` passes; all seven tools verified individually through a live Gemini call with correct results and correct `source` values.
- Commit: `"day 3: data layer, seven tools, async-tool behavior confirmed"`

## Day 4 — Confirmation flow, multi-step, real WebSocket relay
- Test the confirmation flow specifically, using the harness, with these exact phrasings and the pass/fail rule from `V1-04` §5:
  - "The AC in Room 12 is broken, report it." → then "yes" → `create_complaint` fires once, after the confirmation question.
  - Same, then "no" → `create_complaint` never fires.
  - "Is Lab 2 free at 3pm on Monday, and if the AC in Room 12 is broken can you log that" (multi-step in one turn) → both tools fire in the right order.
  - **If `create_complaint` fires without a prior spoken "yes" in any of the above, build the fallback in `V1-04` §5 now** and re-test. Record which path was needed in the commit message.
- Implement the real `main.py` WebSocket route and `live_session.py` in full (`V1-03` §5.3, §6.4–6.10), replacing the Day 2–3 harness.
- Implement `GET /api/records` (`V1-03` §5.2).
- **Acceptance gate:** TC-13, TC-15, TC-16, TC-27 (V1-11) pass through the real WebSocket endpoint (a raw WS client or a minimal HTML page is fine for this day; the full frontend arrives Day 5).
- Commit: `"day 4: confirmation flow verified, multi-step verified, websocket relay complete"`

## Day 5 — Frontend: audio, session controller, panels
- `audio.js` complete (`V1-06` §7).
- `app.js`: Start Booth (§4, without presence — stub `cameraAvailable=false` path first), the session controller (§5, `startSession`/`endSession`/`tickCheck` — trigger `"button"` only today), control-message handling (§5.5), transcript merging (§6), Activity Log (§8), Recent Actions (§9), Show It Something (§10), typed text (§11), toasts (§12).
- Static robot: mount the SVG (`V1-07` §1.3) with `setState` switching only `--eye` colour and a CSS class per state (full animation loop arrives Day 6).
- **Acceptance gate:** TC-01, TC-04–TC-12, TC-14, TC-17–TC-25, TC-32 (V1-11) pass end to end through the real browser UI via Tap to Talk. (TC-02, TC-03 are not expected to pass yet — they depend on Day 6's robot animation and presence detection.)
- Commit: `"day 5: audio pipeline, session controller, transcript/activity/records panels, static robot"`

## Day 6 — Robot animation + presence detection
- `robot.js` complete (`V1-07` Part 1: animation loop, all state visuals, eye tracking, blink, antenna perk, mouth bars).
- `presence.js` complete (`V1-07` Part 2).
- Wire presence into `app.js` (§5.3): `onArrival`/`onAbsent`/`onFace`, the eligibility rule, camera acquisition in Start Booth (§4 full version).
- **Acceptance gate:** the robot acceptance checks in `V1-07` §1.6; the presence acceptance checks in `V1-07` §2.6; TC-02, TC-03, TC-26 (V1-11).
- Commit: `"day 6: robot animation complete, presence detection wired in"`

## Day 7 — web_search, styling pass, failure-mode hardening
- `web_search` tool already built Day 3 — today, test it live: TC-20, TC-21.
- Full visual pass against `V1-08` (all of it should already match since the CSS was written Day 1, but re-check consistency now that every element is live and populated).
- Run every failure listed in `V1-02` §8 on purpose (kill the backend mid-conversation; rename `timetable.json` temporarily and confirm startup fails loudly rather than the demo failing silently; unplug the network mid-tool-call; deny camera; deny mic) and confirm the specified recovery happens in each case.
- **Acceptance gate:** every row of `V1-02` §8 behaves as specified; TC-22 passes.
- Commit: `"day 7: web search verified, design pass, failure-mode hardening complete"`

## Days 8–13 (or as many as available) — real data, rehearsal, polish
Not a fixed day-by-day script — use the time as real slack, in this order of priority:
1. If the real timetable PDF is available: run the extraction procedure (`V1-05` §6) including the mandatory human verification, then re-run TC-08–TC-12 against the real data. Commit: `"real timetable data extracted and verified"`.
2. Full rehearsals of the exact script in `V1-11` §2, ideally in the real venue, at the real mic/camera distance. Tune the presence constants per `V1-07` §2.5 if needed; commit any constant change separately with the value and the reason in the message.
3. Test the mobile hotspot path fully (`V1-09` §9).
4. Fix anything rehearsal reveals, each with its own dated commit.
5. Only if all of the above is solid and time remains, consider items from `V1-12` §3 (deferred roadmap) as **new, separately-planned work** — never as a substitute for rehearsal time, and never implemented without writing its own spec first.

## Final step — push
Once the build is complete and rehearsed: `git push -u origin main` (or the actual default branch name), pushing the entire local history in one action. This is the only push in the whole project (`V1-00` §5 rule 5).

## Definition of done
A visitor can walk up and be greeted unprompted; ask a real timetable question and get a correctly-sourced answer; ask about room availability and get the right answer for a timetable-free room, a timetable-booked room, and a demo-override room; report a complaint and have it logged only after they confirm; ask a general-knowledge question and get an honestly-sourced web answer or an honest "not found"; show the camera something and get a real description; interrupt the robot mid-sentence and have it stop; and see all of this reflected instantly in the transcript, the Activity Log, and the Recent Actions table — with nothing crashing, and with every failure mode in `V1-02` §8 degrading exactly as specified.
