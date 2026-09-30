# V1-11 — Test Plan and Demo Script

Every test case (TC) traces to a capability (CAP) in `V1-01` §3. "Placeholder data" means the dataset in `V1-05` §5. Re-run TC-08–TC-12, TC-28, TC-29 with real numbers once real timetable data is loaded (`V1-05` §6).

## 1. Test cases

| ID | Traces to | Steps | Expected result |
|---|---|---|---|
| TC-01 | CAP-12 | Click Start Booth; allow mic + camera | Overlay hides; state `idle`; hints visible; `GET /health` returns `ok` |
| TC-02 | CAP-09 | Step through all 9 states (drive via the temp harness or a real conversation) | Each state's eye colour/motion and mouth behaviour matches `V1-07` §1.4 exactly; distinguishable from 2 m |
| TC-03 | CAP-02 | Stand in front of the camera; leave; return | Greeted within ~4 s of arriving; not greeted again while still present; leaving ≥ 6 s then returning re-triggers; two arrivals within 45 s → only the first greets |
| TC-04 | CAP-12 | Start Booth; deny mic only, then separately deny camera only | Mic denied: booth runs, typed input works, mic-dependent buttons stay disabled; camera denied: no snapshot/presence, voice still works |
| TC-05 | CAP-03 | Ask "What are you?" | Answer mentions talking, timetable, demo room/complaints, web lookup, and camera vision, in plain words |
| TC-06 | CAP-12 | With Auto-greet off, or with a face never shown, press Tap to Talk | Session starts normally |
| TC-07 | CAP-12 | Mid-conversation, press Done; in another run, press Esc | Both cleanly end the session and return to `idle` |
| TC-08 | CAP-04 | Ask "What class is in Lab 3 on Monday at 2pm?" | Answers "Database Systems", sourced to the timetable; Activity Log tag **Real** |
| TC-09 | CAP-04 | Ask "What classes are on Monday?" | Lists the 3 placeholder Monday classes |
| TC-10 | CAP-04 | Ask "Is there a class in Lab 4 on Sunday?" | Says plainly there's no such class/room, no fabrication |
| TC-11 | CAP-05 | Ask "Is Lab 2 free on Monday at 10am?" | "Yes, free" sourced to the timetable |
| TC-12 | CAP-05 | Ask "Is Lab 3 free on Monday at 2pm?" | "No" and names Database Systems as the class |
| TC-13 | CAP-06 | Ask a room-availability or complaint question with slow tool response (simulate with a temporary artificial delay if needed) | The robot never states a value before the tool call returns; it says it's checking |
| TC-14 | CAP-08 | Hold up a legible printed page and press Show It Something; repeat with a blurry/blank image | Legible: accurate one/two-sentence description; unclear: says it can't make it out, no invented detail |
| TC-15 | CAP-06 | "The projector in Room 5 is broken, report it." → "yes" | Confirmation question asked first; only after "yes" does `complaints` gain a row; spoken ticket number equals the new row id |
| TC-16 | CAP-06 | Same, then answer "no" | No row created; robot acknowledges and moves on |
| TC-17 | CAP-06 | "Something's broken somewhere." | Robot asks a clarifying question instead of guessing or logging |
| TC-18 | CAP-06, CAP-09 | During the confirmation question | UI shows the `waiting_confirmation` state (label + robot eye colour) distinctly from `listening`/`thinking` |
| TC-19 | CAP-06 | Log a complaint, then ask its status by ticket number; also ask "list recent complaints"; ask the status of ticket 9999 | Status matches the DB; list shows recent entries; unknown ticket → honest "not found" |
| TC-20 | CAP-07 | Ask "What is photosynthesis?" | Brief answer, tagged **Web**, attributed to a web lookup |
| TC-21 | CAP-07 | Ask something with no likely instant answer (e.g. a very specific, obscure question) | Honest "couldn't find that", no invented answer |
| TC-22 | CAP-12 | Disconnect the network (or stop the backend) mid-conversation | Error state with a plain message; Reconnect button restores a working session without a page reload |
| TC-23 | CAP-12 | Type "is lab 2 free monday at 10am" into the text box and send | Reaches the same tool and produces the same kind of answer as speaking it; confirmation still applies for a typed complaint |
| TC-24 | CAP-12 | Start a conversation, then go silent for 45+ s | Session ends by itself, state returns to `idle` |
| TC-25 | CAP-12 | Stay in one conversation, talking, past 5 minutes | Session ends at the cap with the toast message |
| TC-26 | CAP-13 | With Start Booth done and nobody interacting, watch the browser Network tab for 2 minutes | No image/video data is sent anywhere during idle presence detection |
| TC-27 | CAP-06 | "Is Lab 2 free at 3pm on Monday, and if the projector in Room 5 is broken can you log that?" | Both actions happen in the same exchange, in a sensible order, both reflected in the Activity Log |
| TC-28 | CAP-05 | Ask "Is Lab 1 free on Monday at 3pm?" | Unavailable, sourced **Demo**, reason mentions the staged override |
| TC-29 | CAP-05 | Ask "Is Lab 9 free on Monday at 10am?" | Says that room isn't in the timetable |
| TC-30 | CAP-01, CAP-10 | Ask something clearly outside scope (e.g. "book me a flight to Lahore") | Plain decline, no fabricated action or tool call |
| TC-31 | CAP-01, CAP-09 | Start the robot speaking, then talk over it | Its audio stops within ~0.5 s (`interrupted` handling); state returns to `listening` |
| TC-32 | CAP-11 | Have a full exchange (question → tool call → answer); then reload the browser page | Transcript shows exactly one merged line per speaker turn, not one per fragment; Activity Log shows the tool going running → done; Recent Actions table still shows the entry after the page reload (it re-fetches from the DB via `/api/records`, not from in-memory state) |

## 2. Live demo script (about 3 minutes, five beats)

**Setup:** Start Booth already done before the audience arrives; Auto-greet on.

**Opening — it notices you.** Presenter steps back from the booth, then walks up. *(TC-03)* The robot notices, perks its antenna, and greets first, unprompted. Say: "I didn't touch anything — it saw me arrive."

**Beat 1 — real data.** Ask a real timetable question. *(TC-08)* Point at the **Real** tag in the Activity Log as it answers: "That's pulled from the actual class timetable, not made up."

**Beat 2 — it looks.** Hold up a printed page or a phone screen, press Show It Something. *(TC-14)* "It's genuinely looking at this, right now, through its camera."

**Beat 3 — confirm before it acts.** Report a fabricated issue ("the projector in Room 5 is broken"). *(TC-15, TC-18)* When it asks to confirm, narrate: "It won't log anything until I actually say yes — watch." Confirm; point at the new row in Recent Actions, tagged **Demo**.

**Beat 4 — one sentence, two actions.** Ask the combined question from TC-27. *(TC-27)* "One sentence, and it just did two separate real things — checked a room and logged an issue — on its own."

**Beat 5 — it's honest about its limits.** Ask something out of scope. *(TC-30)* "It doesn't pretend to know things it doesn't — that's on purpose." Close by interrupting it mid-sentence once *(TC-31)* to show it stops immediately, like a real conversation.

## 3. Rehearsal checklist
- Run TC-01 through TC-32 at least once each before the exhibition; run TC-03, TC-15/16/17, and TC-27 at least five times each, since they're the ones the demo script actually leans on.
- Rehearse the full 5-beat script at least three times, ideally in the real venue with real background noise, at the real distance from the booth.
- Confirm the timing note in TC-13 never produces a spoken guess ahead of a tool result, even once.
- Have short, honest answers ready for: "What happens if it mishears you?" (it apologises and asks again — same as any voice interface); "Is this connected to real university systems?" (only the timetable; everything else is clearly labelled demo, per CAP-10); "Does it remember me?" (no — presence detection is momentary and nothing about visitors is stored, per CAP-13); "What would it take to make the complaint system real?" (a Final Year Project question — see `V1-12` §3).
