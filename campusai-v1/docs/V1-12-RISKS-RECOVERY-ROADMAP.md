# V1-12 — Risks, Recovery, and Roadmap

## 1. Live recovery playbook

| Situation | What to do |
|---|---|
| Internet drops or gets slow | Switch to the mobile hotspot (`V1-09` §9), narrate it plainly ("switching connections, one sec") rather than hiding it |
| The robot goes quiet for a few seconds | Say so out loud ("give it a moment") — the `thinking` state exists for exactly this; if it doesn't recover, press Reconnect |
| A tool fails (network blip on `web_search`, a locked DB file) | Per `V1-02` §8 the robot should say it couldn't do that and keep going; if it visibly doesn't, that's a rehearsal bug to fix before the exhibition, not something to debug live |
| Camera stops working | Presence and Show It Something stop; voice keeps working — mention it's fine and carry on |
| A judge asks something out of scope | Let the honest decline happen (TC-30) — say plainly "it won't guess, that's deliberate" |
| Full freeze / nothing recovers | Reconnect button; if that fails, refresh the page (Start Booth again); last resort, restart `uvicorn` |
| Someone asks "does it remember me / recognise people?" | Answer honestly per CAP-13: no, and explain presence detection is momentary, not identification |

## 2. Strict jury self-critique

**Where this could fail to land:** the confirmation guarantee (CAP-06) is enforced by instruction, not code, unless Day 4 testing forced the fallback in `V1-04` §5. If it hasn't been genuinely stress-tested with the real demo phrasing, this is the single highest-risk claim in the whole pitch — it's also the one line ("it won't act without asking") that does the most work in making the project feel trustworthy rather than gimmicky, so it deserves proportionate rehearsal time.

**Is this actually original, or an AI wrapper with extra steps?** The honesty framing (Real/Demo/Web, spoken and shown) and the on-device presence detection are the two genuinely substantive pieces — most student AI demos don't bother distinguishing what's real from what's staged, and few run any part of their pipeline entirely on the visitor's own device with zero data leaving it. Both are worth naming explicitly if a judge asks "what's actually novel here."

**Can two weeks actually build this?** Only with the scope this package holds to — the deferred list in §3 exists specifically because each of those items would have eaten days that the must-have list needs. Adding any of them mid-build without cutting something else is the most likely way to run out of time.

**Would it still work if the AI or the internet failed completely?** Partially — typed input keeps the tool-calling and confirmation story intact without voice; presence detection and the robot's idle behaviour keep working with no internet at all, since they're on-device. A full Gemini outage still stops the core conversation; there's no offline AI fallback in v1, by design (`V1-01` §5).

**The honest risk nobody likes admitting:** `MIN_FACE_WIDTH_RATIO` and the other presence thresholds in `V1-07` §2.5 are tuned on paper, not in the real venue. Presence detection is the single most "wow" moment in the demo (a robot noticing you unprompted) and also the one most likely to need last-minute tuning — budget real rehearsal time for it specifically, not just a pass/fail check.

## 3. Deferred roadmap — explicitly not in v1

These are not simply "not done yet" — each was considered and set aside for a stated reason. None should be added to v1 mid-build; each is a legitimate direction for a Final Year Project with its own planning pass.

| Idea | Why it's deferred |
|---|---|
| **Recognising or remembering specific people** ("have I seen you before", matching a face to an identity) | This is a firm boundary, not a scheduling decision. It means capturing and storing a biometric identifier for people who walked past a public booth without agreeing to that. Presence *detection* (is a face there, right now) is in v1 and stays privacy-safe because nothing is stored past the moment; recognition is a different category of system with real regulatory and consent implications a two-week student project has no basis to take on |
| Counting people / crowd or unattended-object alerts | Interesting for a real safety-monitoring product, but needs actual validation before anyone should trust its judgement about "something unusual" — a demo-only version risks either crying wolf or being quietly wrong, neither of which is a good look live |
| Commenting on a person's appearance, mood, clothing, or age | A firm behavioural rule (also stated in `V1-04` §1.1's system instruction), not a resourcing decision — this is uncomfortable in public even when it's meant kindly, and there's no way to guarantee it always lands well |
| Full multilingual behaviour beyond replying in the visitor's language | Reply-in-kind is already in v1's system instruction; anything beyond that (menus, UI translation) is real additional work for a secondary benefit |
| Real university system integration (real booking/complaints backends, authentication, real CCTV) | Needs institutional access and permission a student project doesn't have; also the whole reason the Real/Demo distinction exists — see CAP-10 |
| Physical hardware output (printers, lights, servos) | Would be a genuinely bigger "wow" jump, but only worth it if the hardware is already owned — buying anything now risks the zero-cost constraint and adds a new, late integration point |
| Photorealistic or 3D avatar | The flat SVG robot in `V1-07` was chosen specifically because it's reliable to animate in the time available; a dimensional character is real extra build time for a look, not a new capability |
| A second, richer visual ("case board" style activity view) | Considered during planning as an alternative to the robot; not incompatible with it, just extra scope — revisit only once the must-have list is solid with real time to spare |

If a future phase takes any of these on, it should get its own `V2-xx` spec package, written with the same rigor as this one, starting with a privacy review for anything involving cameras and people.
