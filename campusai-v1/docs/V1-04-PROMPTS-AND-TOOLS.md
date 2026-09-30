# V1-04 — Prompts and Tools

Files covered: `prompts.py`, `tools.py`. Helper functions `normalize_day`, `normalize_time`, `normalize_room` are defined in `V1-05` §3; data functions in `V1-03` §7; summaries in `V1-03` §8.

## 1. `prompts.py`

### 1.1 `build_system_instruction(now: datetime) -> str`
Returns the text below with `{now}` replaced by `now.strftime("%A %d %B %Y, %H:%M")` (booth-local time). The text is final; do not reword it.

```
You are CampusAI, a friendly little robot assistant at a university exhibition booth. Visitors walk up and talk to you out loud. You are warm, curious and a little playful, like a helpful person at an information desk who happens to be a robot. Keep every reply short: one or two sentences, because this is a spoken conversation. Never assume the person is technical; explain things the way you would to someone who has never used an AI system. Reply in the language the person is speaking to you.

Current date and time at the booth: {now}. Use this to understand words like "today", "tomorrow" and "this afternoon". If a day has no classes, say so plainly.

WHAT YOU CAN DO
- Answer questions about the real class timetable (query_timetable).
- Check whether a room is free at a given day and time (check_room_availability).
- Log a facility complaint in a small demonstration system, check a complaint's status, and list recent complaints.
- Look up general facts on the web (web_search). This is a limited lookup and often finds nothing.
- Look at something the visitor shows you through the camera.

BE HONEST ABOUT WHERE ANSWERS COME FROM
- Timetable answers: say so, for example "According to the timetable...".
- Room availability: if the result's source is "real", say the timetable shows it; if the source is "demo", say "in our demo system..." and give the reason if there is one.
- Complaints: always say "in our demo system" or "for this demonstration".
- Web answers: say "I looked that up online...". If nothing was found, say so plainly. Never guess or invent an answer.
- You are NOT connected to any real university complaints system, booking system or security camera. Your only real university data is the class timetable. If asked whether something is real or a demo, answer honestly.
- Never state a result (a room's availability, a ticket number, a class time) until the tool has returned it. While you wait, say briefly that you are checking.
- If a tool result contains an "error", tell the visitor simply that you could not do that right now.
- If check_room_availability returns known_room false, say you do not have that room in the timetable.

COMPLAINTS NEED CONFIRMATION
Before logging a complaint: first call signal_confirmation_request with a one-sentence summary, then read back the room and the issue and ask "Should I log that?" Only call create_complaint after the visitor clearly says yes. If they say no or change their mind, log nothing and say that is fine. If the room or the issue is unclear, ask one short question first. Read-only requests never need confirmation and never need signal_confirmation_request.

SEEING THINGS
When the visitor shows you something on camera, describe only what you can actually see, in one or two sentences. If it is blurry or unclear, say so; never invent details. Never comment on any person's appearance, clothing, mood, age or identity, even if a person is visible.

PEOPLE AND PRIVACY
You do not recognise people and you do not remember visitors. If asked whether you remember or recognise someone, say you do not keep any memory of visitors. Never guess who anyone is.

ABOUT YOURSELF
If asked what you are or what you can do, answer in two or three plain, friendly sentences with no jargon, for example: "I'm CampusAI, a little robot you can just talk to. I can check the real class timetable, help with a small demo room and complaints system, look things up online, and even look at something you hold up to my camera."

If someone asks for something you have no tool for, say so plainly and do not make up an answer.
```

### 1.2 Fixed prompt constants (exact)
```python
GREETING_PRESENCE = ("A visitor has just walked up to your booth. Greet them warmly in one or two short "
    "sentences, tell them your name is CampusAI, and invite them to just talk to you - for example to ask "
    "about the timetable, report a problem, or show you something on the camera. Do not comment on their appearance.")

GREETING_BUTTON = ("A visitor has just started talking to you. Greet them warmly in one or two short "
    "sentences, tell them your name is CampusAI, and invite them to ask about the timetable, report a "
    "problem, or show you something on the camera.")

VISION_PROMPT = ("The visitor has just shown you something through the camera. Describe what you actually "
    "see in one or two sentences. If it is unclear, say so instead of guessing. Do not comment on any "
    "person's appearance. Then ask if they want to know something specific about it.")
```
These are sent as text input (see V1-03 §6.3, §6.5). They are instructions to the model, not visitor speech, and are never shown in the transcript.

## 2. `tools.py` — general rules

- Seven tools, exactly these names: `query_timetable`, `check_room_availability`, `create_complaint`, `get_complaint_status`, `list_recent_complaints`, `signal_confirmation_request`, `web_search`.
- Each function is **synchronous** (it is run in a worker thread by the backend).
- Every tool except `signal_confirmation_request` ends by calling `_finish(tool, args, result)`:
  ```python
  def _finish(tool: str, args: dict, result: dict) -> dict:
      data.log_action(tool, args, result)   # never raises
      return result
  ```
  This includes error results, so the audit log shows failures.
- Every tool body is wrapped so that **no exception escapes**: `try: ... except Exception: log.exception(...); return _finish(tool, args, {"source": <default>, "error": "..."})`.
- Every result contains `"source"` (`"real"`, `"demo"`, or `"web"`).
- Argument values may arrive as any JSON type; coerce as stated per tool.

## 3. The seven tools

### 3.1 `query_timetable(day=None, time=None, room=None, teacher=None, course=None)`
```python
def query_timetable(day=None, time=None, room=None, teacher=None, course=None) -> dict:
    args = {"day": day, "time": time, "room": room, "teacher": teacher, "course": course}
    try:
        if day and not normalize_day(day):
            return _finish("query_timetable", args, {"source": "real", "error": "I couldn't understand that day."})
        if time and not normalize_time(time):
            return _finish("query_timetable", args, {"source": "real", "error": "I couldn't understand that time."})
        rows = data.query_timetable_data(day=day, time=time, room=room, teacher=teacher, course=course)
        cap = config.MAX_TIMETABLE_MATCHES_RETURNED
        result = {"source": "real", "total": len(rows), "truncated": len(rows) > cap, "matches": rows[:cap]}
        return _finish("query_timetable", args, result)
    except Exception:
        log.exception("query_timetable failed")
        return _finish("query_timetable", args, {"source": "real", "error": "The timetable lookup failed."})
```
Declaration:
```python
{"name": "query_timetable",
 "description": "Search the REAL class timetable by any combination of day, time, room, teacher, or course name. Provide only the fields the visitor mentioned. Returns matching classes with course, teacher, day, start_time, end_time, room and section.",
 "parameters": {"type": "object", "properties": {
    "day": {"type": "string", "description": "Day of the week, e.g. 'Monday'."},
    "time": {"type": "string", "description": "A time of day, e.g. '10am', '2 pm' or '14:00'. Matches classes running at that time."},
    "room": {"type": "string", "description": "Room or lab name, e.g. 'Lab 3'."},
    "teacher": {"type": "string", "description": "Teacher's name or part of it."},
    "course": {"type": "string", "description": "Course name or part of it."}},
  "required": []},
 "behavior": "BLOCKING"}
```

### 3.2 `check_room_availability(room, day, time)`
```python
def check_room_availability(room, day, time) -> dict:
    args = {"room": room, "day": day, "time": time}
    try:
        d, t = normalize_day(str(day or "")), normalize_time(str(time or ""))
        if not d or not t:
            return _finish("check_room_availability", args,
                           {"source": "real", "error": "I couldn't understand that day or time."})
        display = data.known_room_display(str(room or ""))
        if display is None:
            return _finish("check_room_availability", args,
                           {"source": "real", "known_room": False, "room": str(room), "day": d, "time": t, "available": None})
        override = data.check_override(room, d, t)
        if override is not None:
            result = {"source": "demo", "known_room": True, "room": display, "day": d, "time": t,
                      "available": override["available"], "reason": override["note"]}
        else:
            cls = data.find_class(room, d, t)
            result = {"source": "real", "known_room": True, "room": display, "day": d, "time": t,
                      "available": cls is None,
                      "class": None if cls is None else {k: cls[k] for k in ("course", "teacher", "start_time", "end_time")}}
        return _finish("check_room_availability", args, result)
    except Exception:
        log.exception("check_room_availability failed")
        return _finish("check_room_availability", args, {"source": "real", "error": "The room check failed."})
```
Precedence: a demo override, when present, decides (source `"demo"`); otherwise the real timetable decides (source `"real"`).
Declaration:
```python
{"name": "check_room_availability",
 "description": "Check whether a room is free at a specific day and time. Uses the real timetable, except where a staged demo override exists. If the room is booked by a class, the class is included. If known_room is false the room is not in the timetable.",
 "parameters": {"type": "object", "properties": {
    "room": {"type": "string", "description": "Room or lab name, e.g. 'Lab 3'."},
    "day": {"type": "string", "description": "Day of the week, e.g. 'Monday'."},
    "time": {"type": "string", "description": "Time of day, e.g. '2pm' or '14:00'."}},
  "required": ["room", "day", "time"]},
 "behavior": "BLOCKING"}
```

### 3.3 `create_complaint(room, issue)`
```python
def create_complaint(room, issue) -> dict:
    args = {"room": room, "issue": issue}
    try:
        r = str(room or "").strip()[:config.MAX_COMPLAINT_ROOM_CHARS]
        i = str(issue or "").strip()[:config.MAX_COMPLAINT_ISSUE_CHARS]
        if not r or not i:
            return _finish("create_complaint", args, {"source": "demo", "error": "I need both the room and the issue."})
        ticket = data.create_complaint_record(r, i)
        return _finish("create_complaint", {"room": r, "issue": i},
                       {"source": "demo", "ticket_number": ticket, "room": r, "issue": i, "status": "Submitted"})
    except Exception:
        log.exception("create_complaint failed")
        return _finish("create_complaint", args, {"source": "demo", "error": "I couldn't log the complaint."})
```
This function executes immediately when called. The **confirmation rule is enforced by the system instruction**, not by code (see §5).
Declaration:
```python
{"name": "create_complaint",
 "description": "Log a facilities complaint in the DEMONSTRATION complaint system. Only call this AFTER calling signal_confirmation_request and after the visitor has clearly confirmed the room and issue.",
 "parameters": {"type": "object", "properties": {
    "room": {"type": "string", "description": "Where the problem is, e.g. 'Room 12'."},
    "issue": {"type": "string", "description": "What is wrong, e.g. 'air conditioner not working'."}},
  "required": ["room", "issue"]},
 "behavior": "BLOCKING"}
```

### 3.4 `get_complaint_status(ticket_number)`
```python
def get_complaint_status(ticket_number) -> dict:
    args = {"ticket_number": ticket_number}
    try:
        n = int(float(ticket_number))
    except (TypeError, ValueError):
        return _finish("get_complaint_status", args, {"source": "demo", "error": "I couldn't understand that ticket number."})
    try:
        rec = data.get_complaint(n)
        return _finish("get_complaint_status", {"ticket_number": n}, {"source": "demo", "ticket_number": n, "found": rec is not None, "record": rec})
    except Exception:
        log.exception("get_complaint_status failed")
        return _finish("get_complaint_status", args, {"source": "demo", "error": "The lookup failed."})
```
Declaration: name `get_complaint_status`; description `"Look up the status of a complaint in the demonstration system by ticket number."`; parameter `ticket_number` (integer, required); `"behavior": "BLOCKING"`.

### 3.5 `list_recent_complaints(limit=5)`
```python
def list_recent_complaints(limit=5) -> dict:
    args = {"limit": limit}
    try:
        try: n = max(1, min(10, int(float(limit))))
        except (TypeError, ValueError): n = 5
        rows = data.get_recent_complaints(n)
        return _finish("list_recent_complaints", {"limit": n}, {"source": "demo", "total": len(rows), "complaints": rows})
    except Exception:
        log.exception("list_recent_complaints failed")
        return _finish("list_recent_complaints", args, {"source": "demo", "error": "I couldn't fetch the complaints."})
```
Declaration: name `list_recent_complaints`; description `"List the most recently logged complaints in the demonstration system."`; parameter `limit` (integer, optional, default 5, maximum 10); `"behavior": "BLOCKING"`.

### 3.6 `signal_confirmation_request(summary)`
```python
def signal_confirmation_request(summary) -> dict:
    return {"acknowledged": True}
```
Not logged, no `source`, no side effect. Its only purpose is to tell the backend that a confirmation question is about to be asked (the UI then shows the "waiting for your answer" state — V1-03 §6.7/§6.8).
Declaration:
```python
{"name": "signal_confirmation_request",
 "description": "Call this immediately before asking the visitor to confirm a write action such as logging a complaint. Pass a one-sentence summary of what you are about to confirm. It does not perform the action.",
 "parameters": {"type": "object", "properties": {
    "summary": {"type": "string", "description": "One sentence, e.g. 'Log a complaint about the air conditioner in Room 12.'"}},
  "required": ["summary"]},
 "behavior": "BLOCKING"}
```

### 3.7 `web_search(query)`
Honest scope: this calls DuckDuckGo's free **Instant Answer** API. It only returns something when DuckDuckGo has a ready instant answer (definitions, well-known people/places/things, summaries). Many everyday questions return nothing. That is acceptable **because the agent says so plainly**.
```python
def web_search(query) -> dict:
    q = str(query or "").strip()
    args = {"query": q}
    if not q:
        return _finish("web_search", args, {"source": "web", "query": q, "found": False, "summary": "", "error": "What should I look up?"})
    try:
        resp = httpx.get("https://api.duckduckgo.com/",
                         params={"q": q, "format": "json", "no_html": 1, "skip_disambig": 1},
                         headers={"User-Agent": "CampusAI-Exhibition/1.0"},
                         timeout=config.WEB_SEARCH_TIMEOUT_S, follow_redirects=True)
        payload = json.loads(resp.text)
        summary = (payload.get("AbstractText") or payload.get("Answer") or payload.get("Definition") or "").strip()
        if not summary:
            for item in payload.get("RelatedTopics", []):
                if isinstance(item, dict) and item.get("Text"):
                    summary = item["Text"].strip(); break
                for sub in (item.get("Topics", []) if isinstance(item, dict) else []):
                    if sub.get("Text"): summary = sub["Text"].strip(); break
                if summary: break
        summary = summary[:500]
        return _finish("web_search", args, {"source": "web", "query": q, "found": bool(summary),
                                            "summary": summary, "url": payload.get("AbstractURL", "")})
    except Exception:
        log.exception("web_search failed")
        return _finish("web_search", args, {"source": "web", "query": q, "found": False, "summary": "",
                                            "error": "Web lookup is unavailable right now."})
```
Summary order: `AbstractText` → `Answer` → `Definition` → first `RelatedTopics` text (including nested `Topics`).
Declaration:
```python
{"name": "web_search",
 "description": "Look up general knowledge on the web: definitions, well-known facts, people, places or things. This is a limited instant-answer lookup, not a full search engine, so it may find nothing. Do not use it for timetable, room or complaint questions.",
 "parameters": {"type": "object", "properties": {
    "query": {"type": "string", "description": "What to look up, e.g. 'photosynthesis'."}},
  "required": ["query"]},
 "behavior": "BLOCKING"}
```

## 4. Registries (exact)
```python
TOOL_FUNCTIONS = {
    "query_timetable": query_timetable,
    "check_room_availability": check_room_availability,
    "create_complaint": create_complaint,
    "get_complaint_status": get_complaint_status,
    "list_recent_complaints": list_recent_complaints,
    "signal_confirmation_request": signal_confirmation_request,
    "web_search": web_search,
}
TOOL_DECLARATIONS = [ ...the seven declaration dicts above, in this order... ]
```

## 5. The confirmation guarantee — what it is and is not

Confirmation before `create_complaint` is a **prompt-level** safeguard (system instruction §1.1 "COMPLAINTS NEED CONFIRMATION"), backed by the deterministic UI signal from `signal_confirmation_request`. It is not a code gate. Day 4 testing (V1-10) must verify it with the exact demo phrasings (TC-15 to TC-18).

**Fallback — build ONLY if Day 4 testing shows the model calling `create_complaint` without a prior spoken "yes":**
in `live_session._handle_tool_call`, before running `create_complaint`, check that (a) `awaiting_confirmation` was set at some point since the last `create_complaint`, **and** (b) a user transcript fragment containing one of `yes`, `yeah`, `yep`, `sure`, `confirm`, `okay`, `ok`, `please do`, `go ahead`, `haan`, `جی`, `ہاں` (case-insensitive, whole-word) arrived after the confirmation question. If either check fails, return `{"source":"demo","error":"Please confirm first."}` without executing. Do not build this unless the test fails; if built, record it in the Day 4 commit message.

## 6. `behavior` field and async tool calling — "verify at build time" (Day 3)

`gemini-3.8-live` runs asynchronous function calling by default, meaning the model could start talking before a slow tool returns. Every declaration therefore sets `"behavior": "BLOCKING"` so the answer waits for the result.
- If the connect call rejects the `behavior` field or value, remove that one field from all declarations, keep the "never state a result until the tool has returned" rule in the system instruction, and record it in the Day 3 commit message.
- Either way, run TC-13 (the agent must not speak a ticket number or an availability answer before the tool result) and report the outcome.

Also verify that the lowercase JSON-schema type names (`"object"`, `"string"`, `"integer"`) are accepted by the installed SDK; if it requires uppercase (`"OBJECT"`, `"STRING"`, `"INTEGER"`), convert all declarations and record it.
