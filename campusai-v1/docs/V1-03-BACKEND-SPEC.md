# V1-03 — Backend Specification

Files covered: `config.py`, `schemas.py`, `main.py`, `live_session.py`, `data.py`, `summaries.py`, `requirements.txt`, `.env.example`. Prompts and tools are in `V1-04`; normalisation helpers in `V1-05`.

## 1. `requirements.txt` (exact)

```
fastapi
uvicorn[standard]
websockets
google-genai>=2.3.0
httpx
pydantic
python-dotenv
pytest
```
After the Day 2 verification (V1-10), replace `google-genai>=2.3.0` with the exact installed version (`google-genai==X.Y.Z`) and note it in the commit message.

## 2. `.env.example` (exact)

```
GEMINI_API_KEY=your_key_here
GEMINI_LIVE_MODEL=gemini-3.8-live
GEMINI_VOICE=Puck
TIMETABLE_JSON_PATH=./data/timetable.json
DEMO_DATA_JSON_PATH=./data/demo_data.json
DB_PATH=./data/campus_ai.db
FRONTEND_DIR=../frontend
PORT=8000
```

## 3. `config.py`

- `BASE_DIR = Path(__file__).resolve().parent`. Load `BASE_DIR / ".env"` with `python-dotenv`.
- Read every variable in V1-02 §4 with the stated default. Path variables are resolved: if not absolute, `BASE_DIR / value` (then `.resolve()`).
- Define every backend constant from V1-02 §5 as a module-level constant.
- `GEMINI_API_KEY` is read here and **only** imported by `live_session.py`. Never log it, never return it from any endpoint.
- No other module calls `os.getenv`.

## 4. `schemas.py` (exact)

```python
from pydantic import BaseModel
from typing import Literal, Optional

class ControlMessage(BaseModel):
    """Backend -> browser JSON messages."""
    type: Literal["state", "transcript", "tool_event", "interrupted", "error"]
    value: Optional[str] = None      # state: listening|thinking|waiting_confirmation|speaking|error
    role: Optional[Literal["user", "agent"]] = None   # transcript
    text: Optional[str] = None       # transcript fragment (NOT a full line)
    tool: Optional[str] = None       # tool_event
    status: Optional[Literal["running", "done"]] = None  # tool_event
    summary: Optional[str] = None    # tool_event
    source: Optional[Literal["real", "demo", "web"]] = None  # tool_event
    message: Optional[str] = None    # error: human-readable, never a raw exception

class VisionFrameMessage(BaseModel):
    """Browser -> backend."""
    type: Literal["vision_frame"]
    image_base64: str

class TextInputMessage(BaseModel):
    """Browser -> backend."""
    type: Literal["text_input"]
    text: str
```
Serialise control messages with `model_dump_json(exclude_none=True)`.

Rules:
- `signal_confirmation_request` never produces a `tool_event`.
- `interrupted` carries no other fields.
- Transcript `text` values are **fragments**; the frontend merges them (V1-06 §6).

## 5. `main.py`

### 5.1 Startup (FastAPI `lifespan`)
1. Configure logging: `logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")`.
2. If `config.GEMINI_API_KEY` is empty → raise `RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")`.
3. `data.init_db()` (creates tables if missing, seeds overrides if empty).
4. `data.load_timetable()` — raises `RuntimeError` with a clear message if the file is missing, unreadable, or has zero valid rows (fail fast; see V1-02 §8).
5. Log one INFO line: model, voice, timetable row count, DB path. Never log the key.

### 5.2 Routes (registered in this order; static mount last)

**`GET /health`** → `{"status":"ok","model":<GEMINI_LIVE_MODEL>,"timetable_rows":<int>,"db":"ok"|"error"}`. `db` is `"ok"` if a trivial `SELECT 1` on the DB succeeds.

**`GET /api/records?limit=10`** — `limit` clamped to 1..`RECORDS_MAX_LIMIT` (default 10). Returns:
```json
{"records":[{"timestamp":"2026-09-28T14:05:11","tool":"check_room_availability","summary":"Lab 1 is free — Monday 15:00","source":"real"}]}
```
Built from `data.get_recent_log(limit)`: for each row call `summaries.summarize_done(tool, input_args, result)` and take `result.get("source", summaries.default_source(tool))`. Rows for `signal_confirmation_request` are never logged (the tool does not call `log_action`), so none appear. On any exception return `{"records":[],"error":"<short reason>"}` with **HTTP 200**.

**`WS /ws/session`** — see §5.3.

**Static files** — after all routes: `app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")`.

CORS middleware is **not needed** (same origin). Do not add it.

### 5.3 WebSocket endpoint
1. `await websocket.accept()`.
2. `trigger = websocket.query_params.get("trigger", "button")`; anything other than `"presence"` is treated as `"button"`.
3. **One active conversation only.** Keep a module-level `ACTIVE: LiveSession | None`. If not `None` → send `ControlMessage(type="error", message="Another conversation is already active.")`, close, return.
4. Create `LiveSession(websocket, trigger)`, assign to `ACTIVE`, `await session.run()`, and in `finally` set `ACTIVE = None`.
5. Log INFO at start and end: session id (8 hex chars from `uuid4`), trigger, duration. **Do not log transcripts, audio, or images.**

## 6. `live_session.py`

### 6.1 Class shape
```python
class LiveSession:
    def __init__(self, ws: WebSocket, trigger: str): ...
    async def run(self): ...        # start → wait for either task → stop
    async def stop(self): ...
    # internal: _start, _uplink, _downlink, _handle_message, _handle_tool_call,
    #           _send_control, _send_state, _run_tool
```
State kept on the instance: `session`, `stack` (an `AsyncExitStack`), `tasks`, `awaiting_confirmation: bool = False`, `first_audio_sent: bool = False`, `last_state: str | None`, `closed: bool`.

### 6.2 Live config (exact)
```python
from google import genai
from google.genai import types

def build_live_config(now: datetime) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(parts=[types.Part(text=prompts.build_system_instruction(now))]),
        tools=[types.Tool(function_declarations=tools.TOOL_DECLARATIONS)],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.GEMINI_VOICE))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
```
Do **not** set `thinking_level` or any thinking config (not supported by `gemini-3.8-live`).

### 6.3 Start sequence (`_start`)
1. `client = genai.Client(api_key=config.GEMINI_API_KEY)` — the only place the key is used.
2. `self.stack = contextlib.AsyncExitStack()`.
3. `self.session = await asyncio.wait_for(self.stack.enter_async_context(client.aio.live.connect(model=config.GEMINI_LIVE_MODEL, config=build_live_config(datetime.now()))), timeout=config.CONNECT_TIMEOUT_S)`.
4. `await self._send_state("listening")`.
5. Send the greeting: `await self.session.send_realtime_input(text=prompts.GREETING_PRESENCE if self.trigger == "presence" else prompts.GREETING_BUTTON)`.
6. Create two tasks: `_uplink()` and `_downlink()`.

### 6.4 `run`
```python
try:
    await self._start()
    done, pending = await asyncio.wait(self.tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in done: t.result()          # re-raise task exceptions
except Exception as e:
    await self._fail(e)                # send error + state error
finally:
    await self.stop()
```
`_fail(e)` maps the exception to a message and sends `state: error` then `error`:
- text contains `429`, `RESOURCE_EXHAUSTED`, or `quota` (case-insensitive) → "The AI service is busy right now. Please try again in a minute."
- `asyncio.TimeoutError` → "I couldn't reach my brain in time. Please try again."
- anything else → "Something went wrong. Please try again."
The raw exception is logged (type + message, no secrets) but never sent to the browser. A browser disconnect is **not** an error (no messages sent, just stop).

### 6.5 Uplink (`_uplink`)
Loop: `msg = await self.ws.receive()`.
- `msg["type"] == "websocket.disconnect"` → return.
- `msg.get("bytes")` → `await self.session.send_realtime_input(audio=types.Blob(data=msg["bytes"], mime_type=config.INPUT_AUDIO_MIME))`.
- `msg.get("text")` → `json.loads`; on invalid JSON log and continue. Switch on `type`:
  - `"vision_frame"`: reject silently (log) if `len(image_base64) > MAX_IMAGE_BASE64_CHARS`; decode with `base64.b64decode(..., validate=True)` (on failure log and continue). Then:
    1. `await self.session.send_realtime_input(video=types.Blob(data=jpeg_bytes, mime_type="image/jpeg"))`
    2. `await self.session.send_realtime_input(text=prompts.VISION_PROMPT)`
  - `"text_input"`: `text = text.strip()[:MAX_TEXT_INPUT_CHARS]`; if empty ignore; else `await self.session.send_realtime_input(text=text)`.
  - any other `type` → log a warning, ignore.

### 6.6 Downlink (`_downlink`)
```python
while True:
    got_any = False
    async for message in self.session.receive():
        got_any = True
        await self._handle_message(message)
    if not got_any:
        raise RuntimeError("Live session ended")
```
(`receive()` may end at each turn boundary; the outer loop re-enters it. The `got_any` guard prevents a busy loop if the session closed.)

### 6.7 `_handle_message(message)` (exact rules, in this order)
Let `sc = message.server_content`.
1. `sc.interrupted` → send `ControlMessage(type="interrupted")`; `first_audio_sent = False`; `_send_state("listening")`.
2. `sc.model_turn.parts` → for each part with `inline_data.data`: if not `first_audio_sent`: set it `True` and `_send_state("speaking")`; then `await self.ws.send_bytes(part.inline_data.data)`.
3. `sc.input_transcription.text` (non-empty) → send `transcript` with `role="user"`. If `awaiting_confirmation` is true: set it `False` and `_send_state("listening")` (the visitor has answered).
4. `sc.output_transcription.text` (non-empty) → send `transcript` with `role="agent"`.
5. `sc.turn_complete` → `first_audio_sent = False`; `_send_state("waiting_confirmation" if awaiting_confirmation else "listening")`.
6. `message.tool_call` → `await self._handle_tool_call(message.tool_call)`.
7. `message.tool_call_cancellation` → log only.

`_send_state(value)` sends a `state` message **only if `value != last_state`**, then updates `last_state`.

### 6.8 Tool calls (`_handle_tool_call`)
For each `fc` in `tool_call.function_calls`:
1. If `fc.name == "signal_confirmation_request"`: set `awaiting_confirmation = True`; result = `tools.signal_confirmation_request(**args)`; **no** `tool_event`, **no** state message (the agent is about to speak the question; the state becomes `waiting_confirmation` at `turn_complete`, per §6.7 rule 5). Continue to the response step.
2. Otherwise: `_send_state("thinking")`; send `tool_event(status="running", tool=fc.name, summary=summaries.summarize_running(fc.name, args), source=summaries.default_source(fc.name))`; `result = await self._run_tool(fc.name, args)`; send `tool_event(status="done", tool=fc.name, summary=summaries.summarize_done(fc.name, args, result), source=result.get("source", summaries.default_source(fc.name)))`.
3. If `fc.name == "create_complaint"` and the result has no `"error"` key: `awaiting_confirmation = False`.
4. Build `types.FunctionResponse(id=fc.id, name=fc.name, response=result)`.
After all calls: `await self.session.send_tool_response(function_responses=[…])`.

`_run_tool(name, args)`:
```python
func = tools.TOOL_FUNCTIONS.get(name)
if func is None: return {"error": f"Unknown tool: {name}", "source": "demo"}
try:
    result = await asyncio.wait_for(asyncio.to_thread(func, **(args or {})), timeout=config.TOOL_TIMEOUT_S)
except asyncio.TimeoutError:
    result = {"error": "That took too long."}
except Exception:
    log.exception("tool failed: %s", name)
    result = {"error": "That didn't work."}
result.setdefault("source", summaries.default_source(name))
return result
```
Tools run in a worker thread so the async audio relay is never blocked.

### 6.9 `_send_control` and disconnects
`_send_control` = `await self.ws.send_text(msg.model_dump_json(exclude_none=True))`. If sending raises (browser gone) → mark `closed`, cancel tasks, return quietly.

### 6.10 `stop`
Cancel remaining tasks (await with `return_exceptions=True`); `await self.stack.aclose()` inside try/except (log only); `closed = True`; close the browser WebSocket if still open (`await self.ws.close()` in try/except).

### 6.11 SDK method names — "verify at build time" (Day 2 and Day 3)
The calls used are `client.aio.live.connect`, `session.send_realtime_input(audio=|video=|text=)`, `session.receive()`, `session.send_tool_response(function_responses=[...])`, and the message fields `server_content.{model_turn, input_transcription, output_transcription, turn_complete, interrupted}`, `tool_call.function_calls`. Verify each against the installed `google-genai` version. If a name differs, use the current equivalent, keep behaviour identical, and record the difference in the Day 2 commit message and the day report. Do not change any behaviour described in this document to fit the SDK.

`tools.TOOL_DECLARATIONS` (V1-04 §4) is a plain list of Python dicts. `build_live_config` (§6.2) passes it straight into `types.Tool(function_declarations=tools.TOOL_DECLARATIONS)`. Confirm on Day 2/3 that the installed SDK accepts plain dicts there (most `google-genai` pydantic-backed types do). If it raises a validation error instead, convert each dict to `types.FunctionDeclaration(**d)` at the point `build_live_config` builds the `types.Tool` — this is a wiring change only, in `live_session.py`; `tools.py`'s dicts (V1-04 §3) do not change. Record whichever path was needed in the Day 3 commit message.

## 7. `data.py`

Uses `normalize.py` (V1-05 §3). Every function opens its own short-lived connection: `with contextlib.closing(sqlite3.connect(config.DB_PATH)) as conn:` and uses `conn.row_factory = sqlite3.Row`. Exceptions propagate to the caller (tools wrap them); `log_action` alone swallows and logs its own failures.

### 7.1 Schema (created with `CREATE TABLE IF NOT EXISTS` in `init_db()`)
```sql
CREATE TABLE IF NOT EXISTS complaints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  room TEXT NOT NULL,
  issue TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'Submitted'
);
CREATE TABLE IF NOT EXISTS room_overrides (
  room TEXT NOT NULL,          -- normalised key (normalize_room)
  display_room TEXT NOT NULL,  -- as written in demo_data.json
  day TEXT NOT NULL,           -- canonical full day name
  time TEXT NOT NULL,          -- "HH:MM"
  available INTEGER NOT NULL,  -- 1 or 0
  note TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (room, day, time)
);
CREATE TABLE IF NOT EXISTS agent_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  timestamp TEXT NOT NULL,
  tool TEXT NOT NULL,
  input_args TEXT NOT NULL,
  result TEXT NOT NULL
);
```
Timestamps: `datetime.now().isoformat(timespec="seconds")` (booth-local time).

### 7.2 Functions
- `init_db()` — create tables; if `room_overrides` is empty, load `DEMO_DATA_JSON_PATH` (list of `{room, day, time, available, note}`), normalising `room`, `day`, `time`; skip and log any invalid row.
- `load_timetable()` — read `TIMETABLE_JSON_PATH`; each row must have `course, teacher, day, start_time, end_time, room, section`. Normalise into internal fields `_day, _start, _end, _room` (V1-05 §3); skip and log invalid rows; keep the list in module memory; raise `RuntimeError` if zero valid rows. Returns the count.
- `timetable_row_count() -> int`.
- `query_timetable_data(day=None, time=None, room=None, teacher=None, course=None) -> list[dict]` — AND of provided filters; rules in V1-05 §4. Returns public fields only (`course, teacher, day, start_time, end_time, room, section`), sorted by canonical day order then `start_time`.
- `known_room_display(room_raw: str) -> str | None` — display name if the normalised room exists in the timetable **or** in `room_overrides`, else `None`.
- `find_class(room_raw, day_raw, time_raw) -> dict | None` — the first timetable entry covering that room/day/time.
- `check_override(room_raw, day_raw, time_raw) -> dict | None` — `{"available": bool, "note": str}` or `None` if no override applies. An override covers the **one hour starting at its `time`** (`time <= t < time + 60 min`) — exact rule in V1-05 §4. Returns `None` if day/time cannot be normalised.
- `log_action(tool, input_args: dict, result: dict) -> None` — JSON-dumps both (`default=str`); **never raises**.
- `create_complaint_record(room: str, issue: str) -> int` — inserts, returns `lastrowid` (this is the ticket number).
- `get_complaint(ticket_number: int) -> dict | None` — `{id, timestamp, room, issue, status}`.
- `get_recent_complaints(limit: int) -> list[dict]` — newest first.
- `get_recent_log(limit: int) -> list[dict]` — newest first; `input_args` and `result` parsed back to objects.

## 8. `summaries.py` (exact texts)

```python
DEFAULT_SOURCE = {"query_timetable":"real","check_room_availability":"real","create_complaint":"demo",
                  "get_complaint_status":"demo","list_recent_complaints":"demo","web_search":"web"}
def default_source(tool) -> str: return DEFAULT_SOURCE.get(tool, "demo")
```
`summarize_running(tool, args)`:

| Tool | Text |
|---|---|
| `query_timetable` | `Searching the timetable…` |
| `check_room_availability` | `Checking {room} on {day} at {time}…` (missing values → omit that part) |
| `create_complaint` | `Logging your complaint…` |
| `get_complaint_status` | `Looking up ticket #{ticket_number}…` |
| `list_recent_complaints` | `Fetching recent complaints…` |
| `web_search` | `Looking that up online…` |
| other | `Working…` |

`summarize_done(tool, args, result)` (if `result` has `"error"` → the "failed" text in the last column applies):

| Tool | Success text | Failed text |
|---|---|---|
| `query_timetable` | `total == 0` → `No matching classes`; `1` → `1 matching class`; else `{total} matching classes` | `Timetable search failed` |
| `check_room_availability` | `known_room` false → `{room} isn't in the timetable`; available → `{room} is free — {day} {time}`; not available → `{room} is booked — {day} {time}` plus ` ({course})` if a class is named, or ` (demo: {note})` if from an override with a note | `Couldn't check that room` |
| `create_complaint` | `Ticket #{ticket_number} logged — {issue} ({room})` | `Couldn't log the complaint` |
| `get_complaint_status` | found → `Ticket #{n}: {status} — {issue}`; not found → `Ticket #{n} not found` | `Couldn't look up that ticket` |
| `list_recent_complaints` | 0 → `No complaints logged yet`; else `{n} recent complaint(s)` (singular when 1) | `Couldn't fetch complaints` |
| `web_search` | found → `Found an answer online`; else `Nothing found online` | `Web lookup failed` |
| other | `Done` | `Failed` |

`{day}`/`{time}` come from the **result** (normalised) when present, else the raw args.
