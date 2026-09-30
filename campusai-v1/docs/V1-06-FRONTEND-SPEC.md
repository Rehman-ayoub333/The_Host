# V1-06 — Frontend Specification

Files covered: `index.html`, `constants.js`, `app.js`, `audio.js` (robot and presence internals are in `V1-07`; colours/CSS in `V1-08`). No framework, no bundler. Scripts are ES modules loaded with `<script type="module" src="app.js">`. The page is served by the backend at `http://localhost:8000/`. Supported browsers: current Chrome or Edge.

## 1. `constants.js`
```js
export const C = {
  AUTO_RESET_MS: 45000, MAX_SESSION_MS: 300000, ERROR_AUTO_RECOVER_MS: 15000,
  DETECT_INTERVAL_MS: 400, ARRIVAL_CONSECUTIVE: 3, ABSENCE_MS: 6000,
  MIN_FACE_WIDTH_RATIO: 0.08, MIN_DETECTION_CONFIDENCE: 0.6, GREET_COOLDOWN_MS: 45000,
  SNAPSHOT_WIDTH: 640, SNAPSHOT_HEIGHT: 480, SNAPSHOT_QUALITY: 0.85,
  MIC_BUFFER_SIZE: 4096, INPUT_SAMPLE_RATE: 16000, OUTPUT_SAMPLE_RATE: 24000,
  ACTIVITY_LOG_MAX_LINES: 8, RECORDS_LIMIT: 10,
};
```
No other file may contain these numbers as literals.

## 2. `index.html` (exact structure and ids)

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CampusAI</title>
  <link rel="stylesheet" href="styles.css">
</head>
<body data-state="booth_off">
  <header class="topbar">
    <div class="brand"><span class="brand-name">CampusAI</span><span class="brand-tag">See. Hear. Understand. Act.</span></div>
    <div class="operator">
      <label class="switch"><input type="checkbox" id="autoGreet" checked><span>Auto-greet</span></label>
    </div>
  </header>

  <main class="stage">
    <section class="left" aria-label="Robot and controls">
      <div id="robotMount"></div>
      <p id="statusLabel" class="status-label" aria-live="polite">Ready</p>
      <div id="hints" class="hints">
        <p class="hints-title">Try saying:</p>
        <ul>
          <li>“What classes are on Monday?”</li>
          <li>“Is Lab 2 free at 3 pm on Monday?”</li>
          <li>“Report a broken projector in Room 12.”</li>
          <li>“What is photosynthesis?”</li>
        </ul>
        <p class="hints-foot">Or hold something up and press “Show It Something”.</p>
      </div>
      <div class="controls">
        <button id="talkBtn" class="btn primary" type="button">Tap to Talk</button>
        <button id="doneBtn" class="btn" type="button" hidden>Done</button>
        <button id="snapBtn" class="btn" type="button" disabled>Show It Something</button>
        <button id="reconnectBtn" class="btn primary" type="button" hidden>Reconnect</button>
      </div>
      <form id="textForm" class="textform" autocomplete="off">
        <input id="textInput" type="text" maxlength="500" placeholder="Or type here…" disabled>
        <button id="textSend" class="btn" type="submit" disabled>Send</button>
      </form>
      <div class="camera"><video id="preview" autoplay playsinline muted></video></div>
      <p id="privacy" class="privacy">Camera: used on this device only to notice when someone is nearby — nothing is recorded or stored. Voice, and any photo you choose to show, are sent to Google’s Gemini service (free-tier terms apply). Please don’t show anything sensitive.</p>
    </section>

    <section class="right" aria-label="Conversation and activity">
      <div class="panel"><h2>Conversation</h2><div id="transcript" class="transcript" aria-live="polite"></div></div>
      <div class="panel"><h2>Agent activity</h2><ul id="activityLog" class="activity"></ul></div>
    </section>
  </main>

  <section class="panel records" aria-label="Recent actions">
    <h2>Recent actions</h2>
    <table id="recordsTable"><thead><tr><th>Time</th><th>Action</th><th>Result</th><th>Source</th></tr></thead><tbody></tbody></table>
  </section>

  <div id="startOverlay" class="overlay">
    <div class="overlay-card">
      <h1>CampusAI</h1>
      <p>Operator: click once to switch on the camera and microphone and start the booth.</p>
      <button id="startBtn" class="btn primary large" type="button">Start Booth</button>
      <p id="startNote" class="start-note" aria-live="polite"></p>
    </div>
  </div>
  <div id="toast" class="toast" role="status" hidden></div>
  <script type="module" src="app.js"></script>
</body>
</html>
```
`app.js` sets `document.body.dataset.state = <state>` on every state change (CSS uses it).

## 3. State machine

States: `booth_off`, `idle`, `noticed`, `connecting`, `listening`, `thinking`, `waiting_confirmation`, `speaking`, `error`. "Session active" = any of `noticed, connecting, listening, thinking, waiting_confirmation, speaking`.

### 3.1 Transitions
| From | Event | To |
|---|---|---|
| `booth_off` | Start Booth finished | `idle` |
| `idle` | eligible arrival (§5.3) | `noticed` |
| `idle` | Tap to Talk | `connecting` |
| `noticed` / `connecting` | first backend `state` message | that state |
| active | backend `state` message | that state (`listening`, `thinking`, `waiting_confirmation`, `speaking`) |
| active | Done, Esc key, 45 s inactivity, 5-minute cap | `idle` |
| active | backend `error` message, connect failure, unexpected WebSocket close | `error` |
| `error` | Reconnect pressed | `connecting` |
| `error` | 15 s pass (`ERROR_AUTO_RECOVER_MS`) | `idle` |

### 3.2 UI per state
| State | `#statusLabel` text | talkBtn | doneBtn | snapBtn | textInput+Send | reconnectBtn | hints |
|---|---|---|---|---|---|---|---|
| `booth_off` | (overlay shown) | hidden | hidden | disabled | disabled | hidden | hidden |
| `idle` | `Ready` | visible | hidden | disabled | disabled | hidden | **visible** |
| `noticed` | `Oh — hello!` | hidden | visible | disabled | disabled | hidden | hidden |
| `connecting` | `Connecting…` | hidden | visible | disabled | disabled | hidden | hidden |
| `listening` | `Listening…` | hidden | visible | enabled* | enabled | hidden | hidden |
| `thinking` | `Thinking…` | hidden | visible | enabled* | enabled | hidden | hidden |
| `waiting_confirmation` | `Waiting for your answer…` | hidden | visible | enabled* | enabled | hidden | hidden |
| `speaking` | `Speaking…` | hidden | visible | enabled* | enabled | hidden | hidden |
| `error` | the error message text | hidden | hidden | disabled | disabled | visible | hidden |

\* enabled only if `cameraAvailable`; otherwise disabled with `title="Camera not available"`.
The robot's appearance per state is defined in `V1-07` §1.4. `robot.setState(state)` is called on every state change.

## 4. Start Booth (operator click)

```js
async function startBooth() {
  startBtn.disabled = true; startBtn.textContent = "Starting…";
  await audio.init();                                   // creates + resumes both AudioContexts (§7)
  micAvailable = await audio.probeMic();                // getUserMedia({audio:true}) then stop tracks
  try {                                                 // camera kept for the whole page lifetime
    cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" } });
    preview.srcObject = cameraStream; await preview.play(); cameraAvailable = true;
  } catch { cameraAvailable = false; }
  if (cameraAvailable) {
    try { await presence.init(preview, { onArrival, onAbsent, onFace }); presenceAvailable = true; }
    catch (e) { console.error(e); presenceAvailable = false; }
  }
  notes = [];
  if (!micAvailable) notes.push("Microphone blocked — voice is off; you can type instead.");
  if (!cameraAvailable) notes.push("Camera blocked — greeting and photos are off.");
  else if (!presenceAvailable) notes.push("Presence detection unavailable — use Tap to Talk.");
  hide overlay; setState("idle"); refreshRecords();
  if (notes.length) showToast(notes.join(" "), 8000);
}
```
The overlay's `#startNote` shows the same notes if the operator reopens nothing (it is hidden after start; notes appear as a toast).

## 5. Session controller (`app.js`)

Module state: `ws`, `state`, `endingByUs`, `lastActivity`, `sessionStartedAt`, `timers` (`tick`, `recover`), `armed=true`, `lastAutoGreetAt=0`, `micAvailable`, `cameraAvailable`, `presenceAvailable`, `autoGreetEnabled` (mirrors the checkbox).

### 5.1 `startSession(trigger)` — `trigger` is `"presence"` or `"button"`
1. If a session is active → return.
2. Clear the transcript; reset `lastLine = null`; clear the error/recover timer.
3. `setState(trigger === "presence" ? "noticed" : "connecting")`.
4. If `micAvailable`: try `await audio.startMic(onMicFrame)`; on failure set `micAvailable = false` and `showToast("Microphone unavailable — you can type instead.", 6000)`.
5. `ws = new WebSocket(\`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/session?trigger=${trigger}\`)`; `ws.binaryType = "arraybuffer"`; `endingByUs = false`.
6. `ws.onopen`: `sessionStartedAt = lastActivity = now`; start `timers.tick = setInterval(tickCheck, 1000)`.
7. `ws.onmessage`: `ArrayBuffer` → `lastActivity = now; audio.playPcm(data)`; string → `handleControl(JSON.parse(data))`.
8. `ws.onerror` / `ws.onclose`: if `!endingByUs` → `fail("Connection lost.")`.
9. `onMicFrame(buffer)`: `if (ws && ws.readyState === WebSocket.OPEN) ws.send(buffer)`.

### 5.2 `endSession(reason)` — reason ∈ `user | timeout | cap | error`
1. `endingByUs = true`; clear `timers.tick`.
2. `audio.stopMic()`; `audio.flushPlayback()`; close `ws` if open; `ws = null`.
3. `armed = (presence.state === "absent")` (auto-greet stays disarmed while the same person is still there).
4. If `reason === "cap"` → toast "Conversation ended — tap to talk again." (5 s). If `reason === "timeout"` → no message.
5. Unless `reason === "error"`: `setState("idle")`.

`tickCheck()` (every second): if `now - lastActivity >= C.AUTO_RESET_MS` → `endSession("timeout")`; else if `now - sessionStartedAt >= C.MAX_SESSION_MS` → `endSession("cap")`.
`lastActivity` is refreshed by: any binary audio received, any `transcript`, any `tool_event`, a typed message sent, a snapshot sent.

### 5.3 Auto-greet eligibility
`onArrival()` (called by `presence.js`): always `robot.perkAntenna()`. Then, **all** must be true to start a greeting: `autoGreetEnabled`, `state === "idle"`, `armed`, `now - lastAutoGreetAt >= C.GREET_COOLDOWN_MS`, `document.visibilityState === "visible"`. If so: `lastAutoGreetAt = now; armed = false; startSession("presence")`.
`onAbsent()`: `armed = true`.
`onFace(f)`: `robot.setEyeTarget(f)` where `f` is `{x, y}` (face centre, normalised 0–1, unmirrored camera frame) or `null`.
The "Tap to Talk" button never checks `armed`, cooldown, or the Auto-greet switch.

### 5.4 `fail(message)`
`setState("error")`; `#statusLabel` shows `message`; `endSession("error")` (which does not set `idle`); start `timers.recover = setTimeout(() => { if (state === "error") setState("idle"); }, C.ERROR_AUTO_RECOVER_MS)`. Reconnect button: clear `timers.recover`, `startSession("button")`.

### 5.5 Control messages (`handleControl(msg)`)
- `state`: `setState(msg.value)` (values `listening | thinking | waiting_confirmation | speaking | error`). Ignore if no session is active.
- `transcript`: `lastActivity = now; appendTranscript(msg.role, msg.text)` (§6).
- `tool_event`: `lastActivity = now; upsertActivity(msg)` (§8); if `msg.status === "done"` → `refreshRecords()`.
- `interrupted`: `audio.flushPlayback()`.
- `error`: `fail(msg.message)`.

### 5.6 Other events
- **Esc key** while a session is active → `endSession("user")`.
- **`window.beforeunload`** → `endingByUs = true`; close `ws`; `audio.stopMic()`.
- **Auto-greet checkbox** `change` → `autoGreetEnabled = checkbox.checked`. Never persisted.

## 6. Transcript rendering

Backend transcript messages are **fragments**. Keep `lastLine = {role, txtEl}`.
- `appendTranscript(role, text)`: if `lastLine && lastLine.role === role` → append `text` to `lastLine.txtEl.textContent`; else create `<div class="line line-user|line-agent"><span class="who">You:</span> <span class="txt"></span></div>` (label `CampusAI:` for agent), set its text (with leading whitespace trimmed for the first fragment), and set `lastLine`.
- `addTranscriptLine(role, text)` (used for typed messages): always creates a new line and then sets `lastLine = null` so following spoken fragments start a fresh line.
- Always use `textContent`, never `innerHTML`. Scroll `#transcript` to the bottom after every update. The transcript is cleared at the start of every session.

## 7. `audio.js` (self-contained, exact)

Exports an object `audio` with: `init()`, `probeMic()`, `startMic(onFrame)`, `stopMic()`, `playPcm(arrayBuffer)`, `flushPlayback()`, `getMicAmp()`, `getPlaybackAmp()`.

**`init()`** — called from the Start Booth click (a user gesture): `playCtx = new AudioContext({ sampleRate: C.OUTPUT_SAMPLE_RATE })`; `capCtx = new AudioContext()` (native rate); `await playCtx.resume(); await capCtx.resume()`; `master = playCtx.createGain(); master.connect(playCtx.destination)`; `nextPlayTime = 0`. Both contexts live for the whole page.

**`probeMic()`** — `getUserMedia({audio:true})`, stop all tracks, return `true`; on any error return `false`.

**`startMic(onFrame)`**
1. `stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } })`.
2. `src = capCtx.createMediaStreamSource(stream)`; `proc = capCtx.createScriptProcessor(C.MIC_BUFFER_SIZE, 1, 1)`; `mute = capCtx.createGain(); mute.gain.value = 0`; connect `src → proc → mute → capCtx.destination` (the muted gain is required so the processor runs without echoing the mic).
3. `proc.onaudioprocess = (e) => { … }`:
   - `input = e.inputBuffer.getChannelData(0)` (`Float32Array`).
   - Level: `rms = sqrt(mean(input²))`; `micAmp = clamp(rms * 6, 0, 1)`.
   - Downsample to 16 kHz by **averaging**: `ratio = capCtx.sampleRate / 16000`; `outLen = floor(input.length / ratio)`; for each `i`: average `input[floor(i*ratio) … floor((i+1)*ratio) - 1]`.
   - Convert to 16-bit PCM: `s = clamp(avg, -1, 1)`; `out[i] = s < 0 ? s * 0x8000 : s * 0x7FFF` into an `Int16Array`.
   - `onFrame(out.buffer)`.
4. Keep references to `stream`, `src`, `proc`, `mute` for `stopMic()`.

**`stopMic()`** — disconnect `src`, `proc`, `mute`; stop every track of `stream`; `micAmp = 0`. (The contexts are not closed.)

**`playPcm(arrayBuffer)`**
1. If `arrayBuffer.byteLength` is odd, drop the last byte.
2. `i16 = new Int16Array(arrayBuffer)`; `f32[i] = i16[i] / 32768`.
3. Level: `rms` over `f32`; `amp = clamp(rms * 3, 0, 1)`.
4. `buf = playCtx.createBuffer(1, f32.length, C.OUTPUT_SAMPLE_RATE); buf.copyToChannel(f32, 0)`; `node = playCtx.createBufferSource(); node.buffer = buf; node.connect(master)`.
5. `startAt = Math.max(nextPlayTime, playCtx.currentTime + 0.02)`; `node.start(startAt)`; `nextPlayTime = startAt + buf.duration`.
6. Push `{start: startAt, end: startAt + buf.duration, amp}` onto `envelope`; add `node` to `active`; `node.onended` removes it from `active`.
(Scheduling each chunk at `nextPlayTime` — never calling `start()` immediately — prevents gaps and overlaps.)

**`flushPlayback()`** — `try { node.stop() }` for every node in `active`; clear `active`; `nextPlayTime = 0`; `envelope.length = 0`.

**`getMicAmp()`** — returns `micAmp` (0–1).
**`getPlaybackAmp()`** — `t = playCtx.currentTime`; remove `envelope` entries with `end < t - 0.5`; return the `amp` of the entry with `start <= t < end`, else `0`.

## 8. Agent Activity log

`<ul id="activityLog">`, newest entry **at the top**, at most `C.ACTIVITY_LOG_MAX_LINES` (remove from the bottom).
`upsertActivity(msg)`:
- `status: "running"` → insert `<li class="running" data-tool="…"><span class="time">HH:MM:SS</span><span class="summary">…</span><span class="tag tag-real|demo|web">Real|Demo|Web</span></li>` at the top.
- `status: "done"` → find the most recent `li.running` with the same `data-tool`; update its summary and tag, replace class `running` with `done`. If none exists, insert a new `done` item.
Time uses the browser's local time. Use `textContent` for all text.

## 9. Recent Actions table

`refreshRecords()`: `fetch("/api/records?limit=" + C.RECORDS_LIMIT)`; on success re-render `<tbody>` with one row per record: time = `record.timestamp.slice(11, 19)`; action = friendly name from this map; result = `record.summary`; source = tag pill.

| tool | friendly name |
|---|---|
| `query_timetable` | Timetable search |
| `check_room_availability` | Room check |
| `create_complaint` | Complaint |
| `get_complaint_status` | Complaint status |
| `list_recent_complaints` | Recent complaints |
| `web_search` | Web lookup |

Called once after Start Booth and after every `tool_event` with `status: "done"`. Any failure is logged to the console only; the table keeps its previous content. Use `textContent`.

## 10. Show It Something

`captureSnapshot()` (button enabled only in the states of §3.2 and when `cameraAvailable`): draw the current `<video>` frame to an offscreen canvas of `C.SNAPSHOT_WIDTH × C.SNAPSHOT_HEIGHT` (unmirrored — text must stay readable); `dataUrl = canvas.toDataURL("image/jpeg", C.SNAPSHOT_QUALITY)`; strip the `data:image/jpeg;base64,` prefix; send `{"type":"vision_frame","image_base64":"<data>"}`; set `lastActivity = now`; change the button text to `Sent ✓` for 1200 ms then back to `Show It Something`. The agent's spoken description arrives through the normal audio/transcript path.

## 11. Typed text

On `#textForm` submit (preventDefault): `text = textInput.value.trim()`; if empty or `ws` not open → do nothing. Otherwise `addTranscriptLine("user", text)`; send `{"type":"text_input","text": text}`; clear the input; `lastActivity = now`. Typed messages go through exactly the same tools and confirmation flow as speech.

## 12. Toasts

`showToast(text, ms)` shows `#toast` with `text` for `ms` milliseconds (default 5000), then hides it. One toast at a time; a new toast replaces the current one.

## 13. Camera preview
`#preview` is muted, mirrored with CSS (`transform: scaleX(-1)`), ~200 px wide, in the left column. Snapshots and face detection use the **unmirrored** raw video frame.

## 14. Quality requirements
- Every interactive element is keyboard-reachable with a visible focus outline (V1-08).
- Buttons are at least 44 px tall.
- `#statusLabel`, `#transcript` use `aria-live="polite"`.
- No inline event-handler attributes in HTML; all wiring in `app.js`.
- The page works with zoom 100 %–150 % at 1280×720 without horizontal scrolling; below 900 px width the layout stacks (V1-08 §5).
- No `console.log` of transcripts or image data.
