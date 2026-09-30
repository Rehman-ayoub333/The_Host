# V1-01 — Product Definition

This is the "what must it do" document — the brief the planning side hands to the build side. Each capability has an ID (CAP-xx), plain-language behaviour, and acceptance criteria. Test cases in `V1-11` trace back to these IDs.

## 1. Purpose

A university exhibition booth. Any visitor — technical or not — should understand within five seconds what it is, be able to use it without instructions, and remember it afterwards. The product is judged on: clarity of the concept, reliability of the live demo, honesty about what is real, and technical substance (real-time voice, tool calling, vision, on-device presence detection).

## 2. Users

- **Visitor** — walks up, talks. Knows nothing about the system.
- **Operator** — the presenter. Starts the booth once, watches for problems, can switch auto-greet off, can use the typed-text fallback.

## 3. Capabilities

### CAP-01 — Real-time voice conversation
The visitor speaks naturally; the robot answers out loud, in a conversational tone, in short replies (one or two sentences). The visitor can interrupt the robot and it stops talking. It replies in the language the visitor is using.
**Acceptance:** a spoken question receives a spoken answer with the first audio starting within ~3 seconds on a normal connection; interrupting the robot mid-sentence stops its audio within ~0.5 seconds.

### CAP-02 — Speaks first when someone arrives
When Booth Mode is running and a face appears in front of the booth camera and stays for ~1.2 seconds, the robot perks its antenna, and starts a conversation by greeting the visitor and inviting them to try something. This uses on-device face *detection* only (is there a face?) — never recognition.
**Acceptance:** a person stepping in front of the camera is greeted within ~4 seconds; the same person standing there is not greeted again until they have left (≥ 6 s without a face) and come back; at most one auto-greeting per 45 seconds; the operator can switch auto-greet off; the "Tap to Talk" button always works regardless.

### CAP-03 — Explains itself
Asked "what are you?" / "what can you do?", it answers in two or three plain sentences, no jargon, mentioning: talking, the real timetable, the demo room/complaint system, web lookups, and looking at things through the camera.
**Acceptance:** the answer mentions all five items in ordinary words.

### CAP-04 — Real timetable answers
Answers questions by day, time, room, teacher, or course from the real timetable, and says the answer comes from the timetable.
**Acceptance:** for a known entry, the spoken answer matches the data exactly; for no match it says plainly there is no class; the Activity Log shows a **Real** tag.

### CAP-05 — Room availability
Says whether a room is free at a given day and time. The real timetable decides, except where a staged demo override exists (then the demo system decides and says so). If a class is in the room, it names it. If the room isn't in the timetable at all, it says it doesn't have that room.
**Acceptance:** the three cases (free from timetable / booked by class / demo override) each produce the correct answer and the correct source tag and spoken attribution.

### CAP-06 — Complaints with confirmation
The visitor reports a problem. The robot repeats back the room and issue and **asks for confirmation before logging**. Only after a clear "yes" does it log the complaint and speak the ticket number. If the visitor says no, nothing is logged. The visitor can ask the status of a ticket and list recent complaints.
**Acceptance:** with a "yes" a new row appears in `complaints` and the spoken ticket number equals the row id; with a "no" no row is created; the robot never states a ticket number before the tool has returned it; the UI shows a distinct "waiting for your answer" state during the confirmation question; all of it is tagged **Demo**.

### CAP-07 — Web lookup (limited, honest)
For general-knowledge questions outside the timetable/demo scope, it looks the topic up on the web and answers briefly, saying it came from the web. If nothing is found, it says so plainly and does not guess.
**Acceptance:** a well-known-fact question ("what is photosynthesis?") returns an answer tagged **Web**; a question with no instant answer produces an honest "I couldn't find that"; a network failure never breaks the session.

### CAP-08 — Looks at things (one-shot vision)
While a conversation is active, pressing **Show It Something** sends one photo from the booth camera. The robot describes what it actually sees in one or two sentences, says so if it is unclear, and can answer follow-up questions about it.
**Acceptance:** holding up a printed page and pressing the button produces a spoken description of it within ~5 seconds; an illegible/blurry image produces an "I can't make that out" style answer rather than invented detail.

### CAP-09 — Robot character
A robot head-and-shoulders character is the centre of the screen. Eye colour shows state; the speaker-grille mouth moves with the robot's voice; the antenna perks when it notices someone; the eyes look toward the visitor's face; it blinks; it has a subtle idle "scanning" motion when nobody is there.
**Acceptance:** every state in `V1-07` §1.4 is visibly distinct; the mouth bars move only while the robot is speaking and stop within ~0.3 s of the audio ending; eyes follow a face moving left/right.

### CAP-10 — Data-source honesty
Every answer states its source in speech (per V1-04) and every entry in the Activity Log and Recent Actions carries a tag: **Real**, **Demo**, or **Web**. The robot never implies a connection to real university systems beyond the timetable.
**Acceptance:** asked "is that real?" it answers honestly for each source; tags are correct for every tool.

### CAP-11 — Live panels
A scrolling transcript of the conversation (cleared for each new visitor), an Activity Log of tool calls as they happen, and a Recent Actions table of the last 10 logged tool calls that survives page reloads.
**Acceptance:** each spoken exchange appears in the transcript as one line per speaker turn (not per word fragment); tool calls appear in the Activity Log as "running" then "done"; the table reflects the database after each completed tool call.

### CAP-12 — Booth operations
One-click **Start Booth** (grants camera/mic permission and unlocks audio). **Tap to Talk** / **Done**. Auto-reset to idle after 45 s of no activity, and a hard cap of 5 minutes per conversation. An **Auto-greet** switch. A typed-text input for use when voice is impractical. A **Reconnect** path after errors. Example prompts shown while idle. A privacy notice always visible.
**Acceptance:** after a visitor walks away the booth returns to idle by itself; after an error the booth recovers without a page reload; typed input reaches the same tools and confirmation flow as voice.

### CAP-13 — Privacy and behavioural boundaries
- Camera frames used for presence detection never leave the device and are never stored.
- The only image ever sent to a server is a snapshot the visitor explicitly triggers with **Show It Something**.
- Nothing about a visitor's face or identity is stored, and nothing is remembered between visitors.
- The robot never comments on a person's appearance, clothing, mood, age, or identity, and never claims to recognise or remember anyone.
- The on-screen privacy notice is accurate (text in V1-06 §8), including that voice and any shown photo are processed by Google's Gemini service under its free-tier terms.
**Acceptance:** network inspection during idle presence detection shows no image data sent; asked "do you remember me?" the robot says it doesn't keep any memory of visitors.

## 4. Non-functional requirements

| Requirement | Target |
|---|---|
| Cost | $0 (no paid services; no credit card) |
| Runs on | One Windows/macOS/Linux laptop, Chrome or Edge (latest), webcam, microphone, speakers/headphones, internet |
| Startup | Backend ready < 10 s; Booth Mode ready < 15 s after clicking Start Booth (face-detector model load) |
| Resilience | Any single tool failure degrades only that answer; a Gemini failure shows the error state and recovers via Reconnect; DuckDuckGo/timetable/DB failures never crash a session |
| Security | API key server-side only; frontend served by the same backend; no secrets in logs |
| Honesty | No fabricated results; unknown → say so |

## 5. Assumptions

- The exhibition machine has stable internet; a mobile hotspot is the backup (no offline AI mode exists in v1).
- Exactly one browser tab runs the booth at a time.
- The real timetable PDF may arrive after the build starts; a placeholder dataset is provided (V1-05) and swapping in real data must not change any code.
