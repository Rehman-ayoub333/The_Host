# THE HOST — gala runbook

Everything the team does on the day, in order. Follow it top to bottom.

This document contains no keys, no tokens and no passwords. The operator token and the
Gemini API key live only in `backend\.env`, which is never committed and never printed by
any script here.

---

## 1. The night before

1. **Charge both laptops** — the booth laptop and the backup laptop — to 100%, and pack
   both chargers, the handheld microphone, the speaker, and the HDMI cable for the display
   screen.
2. **Get the latest code** on the booth laptop:
   ```powershell
   cd F:\PIAIC_6_PROJECTS\THE_HOST
   git pull
   ```
3. **Check the laptop is ready:**
   ```powershell
   .\scripts\preflight.ps1
   ```
   Fix every `FAIL` before going further. A `WARN` is something to look at, not something
   that stops the gala.
4. **Start the gala with an empty database.** Stop the backend first, then:
   ```powershell
   .\scripts\reset-for-gala.ps1
   ```
   It asks you to type `RESET`. Nothing is deleted: the current database is copied into
   `backend\data\backups\` and the live file is moved there too, so the next start builds a
   fresh, empty one. Backups are never removed.
5. **Set a fresh operator token.** Open `backend\.env` in Notepad and set `OPERATOR_TOKEN`
   to a new value of **letters and digits only** — no spaces, and no `# & @ ? / \` or other
   punctuation, which break the token when it travels in a web address. Save and close.
   Do not share it, photograph it, or type it into anything but this file and the
   dashboard's Settings page.
6. **Put the posters in.** The TV shows full-screen pictures whenever nobody is talking to
   THE HOST — that is the stall's menu board, so the pictures have to carry the prices and
   everything else a guest needs to read. Copy them into:
   ```
   backend\data\posters\
   ```
   `.jpg`, `.jpeg`, `.png` or `.webp`, 1920×1080 landscape, one picture per poster. **They
   are shown in file-name order,** so name them `01-burgers.jpg`, `02-drinks.jpg` and so on.
   Each one is on screen for 8 seconds. Nothing else in the folder matters — the `README.txt`
   that is already there is ignored. A picture added later in the evening appears on the TV
   by itself within a minute, with nothing to restart; and if the folder is empty the TV
   simply shows the brand screen, which is not wrong, only plainer.
7. **Do one full test order,** end to end:
   ```powershell
   .\scripts\start-all.ps1
   ```
   On the dashboard set **Settings → Display screen devices** (Camera and Microphone), then
   open the TV with `.\scripts\open-display.ps1` and allow the camera and the microphone
   the one time it asks. Order one item out loud, give a first name, answer *cash*, then on
   the dashboard press **Paid · Cash** on that order and listen: THE HOST says it is paid
   and with the kitchen. Move it PREPARING → READY → **Collected** and watch the TV announce
   it. Press **Reload display screen** and check the TV comes back on its own, with no tap.
   Check the posters are rotating on the TV between conversations. Then run `reset-for-gala.ps1` once more so
   the gala starts clean.

   Doing this tonight also gets the dashboard built. The dashboard runs as a **production
   build**, and the first start after a `git pull` builds it, which takes a few seconds and
   prints `Building the dashboard`. Getting it out of the way now means gala night starts in
   about a second instead.
8. **Stop both servers** and close the laptop.

---

## 2. Setting up at the stall

**Two screens, and only two.**

| Screen | Address | Where it goes |
|---|---|---|
| THE HOST | `http://localhost:8080/display` | The TV on top of the stall, **full screen**, facing the guests |
| The dashboard | `http://localhost:8080/` | The laptop on the front table, the operator's screen |

The TV is THE HOST: the camera, the handheld microphone and THE HOST's voice all belong to
that page. Between conversations it shows the stall's posters, full screen — that is the
menu board, so the pictures must carry the prices (section 1, step 6). The laptop is the
operator's, and it holds the only screen with order controls and guest names on it. `http://127.0.0.1:8000/` is the backend, not a screen: it answers
with one line saying where the display is. If `/display` will not start, see section 4.

1. **Plug in the hardware first,** before any window is opened: the external camera, the
   handheld microphone, the speaker, and the HDMI cable to the TV.
2. **Start everything:**
   ```powershell
   cd F:\PIAIC_6_PROJECTS\THE_HOST
   .\scripts\start-all.ps1
   ```
   It prints the three addresses and, last, `To stop both: scripts\stop-all.ps1` — the one
   way to stop them, because closing the windows leaves both servers running (section 6).

   **The gala uses the dashboard exactly as this starts it** — the production build, which
   is the default. The dashboard window should say
   `Dashboard on http://localhost:8080/ (production)`. If it instead says
   `DEVELOPMENT server, not for the gala`, someone has passed `-Dev`: close that window and
   start it again without the switch. `-Dev` is for everyday work on the dashboard, never
   for the gala — it recompiles pages on demand and can leave the dashboard feeling like it
   is hanging.
3. **Put the TV on its own screen.** In Windows press `Win + P` and choose **Extend** (not
   Duplicate). Open a browser window, go to `http://localhost:8080/display`, drag it onto
   the TV, and press `F11` for full screen.
4. **The Windows sound devices.** Right-click the speaker icon → **Sound settings**:
   - **Output** — choose the **stall speaker**, not the TV. THE HOST's voice is played by
     the `/display` page through whatever Windows calls the default output, and a TV's own
     speakers point away from the guest. Press *Test* and listen to where the sound comes
     from.
   - **Input** — choose the **handheld microphone**. Say a few words and watch the level move.
5. **Choose the display's camera and microphone on the laptop,** before touching the TV.
   On the dashboard open **Settings → Display screen devices** and set **Camera** to the
   external camera and **Microphone** to the handheld microphone. The choice is saved in that
   browser and read by `/display` on the same machine, so a reload does not ask again. If a
   saved device has been unplugged, this is where it says **Saved camera not found** or
   **Saved microphone not found** — the TV says nothing and quietly falls back to the Windows
   default, so check here rather than on the TV.
6. **Open the TV with its own script.**
   ```powershell
   .\scripts\open-display.ps1
   ```
   It opens `/display` full screen on the second monitor, with no tabs and no address bar,
   in a browser profile of its own. **The first time only**, it asks for the camera and the
   microphone: allow both. After that the TV starts itself every time and never shows
   *Tap to begin* — which is also what lets **Reload display screen** work from the
   dashboard. There are no buttons and no drop-downs on the TV at all.
   **The TV never needs touching again** — THE HOST greets guests itself, wakes on speech,
   and listens. (Use `-X 0` to open it on the laptop while testing.)
7. **Leave the TV window focused and on top.** Face detection pauses while the window is
   hidden, which is also what holds the empty-room timer. A partly overlapped window is
   fine; a minimised one is not. The operator's two keys work on this window: **Space**
   starts a conversation, **Escape** ends one.
8. **The operator token.** On the laptop open the dashboard → **Settings**, paste the token
   into *Operator token*, and press **Save & connect**. The agent link must read `LIVE`.
9. **Never start the dashboard's camera preview.** The dashboard's **Live Vision** page has
   a preview that opens the camera on the laptop. At the gala the camera belongs to
   `/display`, and two pages cannot have it at once. Leave the preview off all evening.
10. **Run preflight until every line is PASS:**
   ```powershell
   .\scripts\preflight.ps1
   ```

---

## 3. Roles

THE HOST never replaces the team; it hands work to them. There are two screens: the TV on
top of the stall is THE HOST, and the laptop on the front table is the operator's.

| Who | Looks after |
|---|---|
| **Rehman** | **Operator and project lead.** The dashboard: the Live conversation panel and AI Activity; answers "Operator help requested" at once; uses Pause, Take over, End conversation, Retry connection and Announce again; switches to the phone hotspot if the venue internet fails; last resort Settings → Demo Mode, said out loud to be a demonstration. Speaks to the Vice Chancellor, the chief guest and the judges about the technology when THE HOST hands over |
| **Saad** | **Kitchen and orders.** Watches the orders panel and marks PREPARING → READY → COLLECTED, hands food over by order number and name, takes payment, and handles the late, wrong or missing orders THE HOST flags |
| **Umair** | **Guests, display and backup.** Stands at the front: hands the microphone to each guest and says "Just talk to it", keeps one guest at a time at the microphone, keeps the TV and the camera clear, runs the backup laptop (section 5), and calls Rehman when anything looks wrong on the TV |

Saad and Rehman share the one laptop for the order statuses; Saad calls out when an order is
ready if Rehman is busy. One person to a job otherwise. If something looks wrong, say so out
loud rather than reaching across to someone else's laptop.

---

## 4. During the gala

### The kitchen flow

**The money comes first.** A guest orders by talking to THE HOST, which asks one question
— *"Shall I place it — cash or QR?"* — and places the order on their answer. It then
**waits for payment**, and the kitchen has nothing to do until it is paid. From then on it
is Saad's:

1. **PAID** — the guest has handed over the cash, or scanned the QR code and shown you the
   payment. Press **Paid · Cash** or **Paid · QR** on that order. The method the guest told
   THE HOST is already highlighted, but press what they actually paid with — that is the
   one that counts. Only this press sends the order to the kitchen, and THE HOST tells the
   guest in one line that it is paid and on its way. **Nothing is cooked before this.**
2. **PREPARING** — the kitchen has started it.
3. **READY** — it is on the counter. The TV announces
   *"Order #27 for Ahmed is ready!"* and speaks it aloud.
4. **COLLECTED** — the guest has taken it. One button now, for every order: how it was paid
   was recorded at step 1, and the card already reads *Paid · Cash* or *Paid · QR*. An order
   **on the house** goes straight to the kitchen with nothing to charge.

An order waiting for payment is shown at the top of the Orders panel and again in the Live
conversation panel, with the total in large figures, and a line counts how many are waiting.
**A guest who walks away without paying costs nothing**: after ten minutes the order cancels
itself, the feed reads *Order #27 cancelled (unpaid)*, and the Earnings panel stops counting
it as money at the counter.

**Announce again** re-plays a ready announcement if the guest missed it.

**A guest who changes their mind.** While an order is still *Waiting for payment*, THE HOST
can change or cancel it itself: it asks *"Shall I cancel order number 27?"* and waits for the
guest's yes. For a change it places the corrected order first and cancels the old one
after, so the guest is never left with nothing. Once the money has been taken, THE HOST says
the order is already paid and flags it for the team — that call is the operator's, including
any refund, and they can still cancel a paid or *Preparing* order from the dashboard.

### Telling THE HOST something, without speaking

The Live conversation panel has a box, **Tell THE HOST…**, and three buttons beside it:
*This is the Vice Chancellor*, *Ask them to pay at the counter* and *Wrap up politely*. Type
a short line and press **Send**, and THE HOST acts on it in its next breath — graciously, and
without ever reading it out or letting the guest know it was told anything. Use it when you
can see something THE HOST cannot: who the guest is, that the queue is building, that the
payment has not come. It only works while a conversation is running; the panel says so when
one is not. Nothing typed there is saved anywhere.

### The operator buttons (dashboard → System)

| Button | What it does | When to use it |
|---|---|---|
| **Pause THE HOST** | Stops THE HOST talking and ends the current conversation | A break, or a queue that needs clearing by hand |
| **Take over** | Hands the stall to a person; THE HOST stops | A guest needs a human |
| **End conversation** | Ends just the conversation running now | Someone is monopolising it, or it has got stuck |
| **Retry connection** | Tests the AI service once, now | After the internet has been fixed |
| **Reload display screen** | Reloads the TV from here | The TV looks wrong, is stuck, or has just had its camera or microphone changed |

Pause, Take over and End conversation ask you to confirm first. **Resume THE HOST** puts it
back to work.

### If something goes wrong

- **A short outage.** The TV's caption reads *"Reconnecting…"* and the dashboard shows the
  mode in amber. THE HOST recovers by itself, and the conversation carries on where it left
  off. Wait. Do not restart anything.
- **The TV looks wrong.** Press **Reload display screen**, on the dashboard's System panel
  or in **Settings → Display screen devices**. The TV reloads itself and comes straight back
  to its posters — no walking over, no keyboard, and no *Tap to begin*, because
  `open-display.ps1` started it in a window that is allowed to begin on its own. Use the same
  button after changing the camera or the microphone in Settings.
- **`/display` will not start.** THE HOST never hears or sees a guest: the orb stays idle,
  and nothing happens when someone speaks in front of it. Check
  **Settings → Display screen devices** on the laptop first — a saved camera or microphone
  that has been unplugged is named there, and the TV itself says nothing about it. If that
  is not it, open `http://localhost:8080/display` on the **laptop** instead, full screen and
  facing the guests, and tap it once. It is the same page with the laptop's own camera and
  microphone. Tell the operator, because the camera then belongs to the laptop, and they
  keep the dashboard in a second window.
- **The venue internet fails.** Switch the booth laptop to the phone hotspot, then press
  **Retry connection** on the dashboard. The mode should return to `ONLINE`.
- **Nothing works.** Open **Settings → Demo Mode (backup)** and press **Start Demo Mode**.
  Every screen carries a `DEMO DATA` badge while it runs. **Say out loud that this is a
  demonstration, not a live order.** Press **Exit demo** to go back to the live system.

### When the Vice Chancellor comes

This is the most important visit of the day. THE HOST knows the protocol; these are the
people's steps.

1. Whoever sees him coming says **"VC"** quietly to the team. Rehman stays at the dashboard,
   Umair stands beside the microphone, Saad gets the kitchen ready.
2. Umair holds the microphone toward him — or toward whoever introduces him — and says only:
   **"Sir, please speak to THE HOST."** Nobody talks over THE HOST after that.
3. THE HOST welcomes him, says the order is on the house, and takes it without asking for a
   name or saying a price. Rehman watches the Live conversation panel; the order appears
   marked **on the house**. Saad makes it first, ahead of the queue, and hands it over by
   hand. THE HOST announcing it on the TV is expected and fine.
4. When THE HOST says **"Rehman Ayoub would be glad to answer"**, Rehman steps forward. All
   three introduce themselves briefly, and Ma'am Marva is named.
5. If anything goes wrong — silence, a strange answer, *"Reconnecting…"* — Rehman presses
   **Take over** or **Pause** at once and speaks himself. Never argue with THE HOST in front
   of a guest.
6. **Pranks.** If someone who is clearly not the Vice Chancellor is given an "on the house"
   order, Rehman cancels it quietly on the dashboard and Saad speaks to the guest in person.
   THE HOST is never asked to judge who someone is — that is the team's job.
7. **The name rule.** THE HOST knows the Vice Chancellor's name, says it in its welcome, and
   uses it again whenever he asks. It also recognises him **by that name alone**: anyone who
   gives the Vice Chancellor's name — introducing themselves, or just as the name for an
   order, in any spelling — is treated as the Vice Chancellor from that moment, and an order
   already being built is rebuilt on the house. That is deliberate: THE HOST must never
   question a guest of honour. If it was a prank, Rehman cancels the order quietly on the
   dashboard, as in step 6. Nobody needs to tell THE HOST the name.
8. **Nobody else is on the house, and the system enforces it.** The chief guest, judges,
   teachers and anyone who says they are staff get exactly the same respect, formality and
   no jokes — and a normal bill. THE HOST never mentions price or payment to them either
   way, so whether to charge the chief guest is still the operator's call at the counter, but
   the order will be an ordinary paid order on the dashboard. Only the Vice Chancellor's own
   name can put an order on the house; every other name is refused in the backend, whatever
   the guest says and whatever THE HOST is told.

---

## 5. The backup laptop

Set this up before the gala, not during it.

```powershell
git clone https://github.com/Rehman-ayoub333/The_Host.git
cd The_Host
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd dashboard
bun install
cd ..
.\scripts\start-dashboard.ps1
.\scripts\preflight.ps1
```

Start the dashboard once here, before the gala: it builds the production dashboard on that
first run, and a backup laptop you have to reach for mid-gala should not be building
anything. `Ctrl + C` it once it says `(production)`.

**`.env` is not in the repository and never will be.** Copy `backend\.env` from the booth
laptop by USB stick, by hand. Do not email it, do not put it in a chat, and delete it from
the USB stick afterwards.

---

## 6. After the gala

1. **Download the sales CSV before stopping the servers.** On the dashboard, the
   **Earnings** panel (the last row of the Command Center, and the top of *Analytics*) has
   **Download today's sales (CSV)**. It saves `bite-and-pour-sales-<date>.csv`: one row per
   order of the day, with what was in it, the total, how it was paid and whether it was on
   the house. **The Earned figures should match the cash box plus the QR account** — Cash
   against what is in the box, QR against the account. A line saying *collected without a
   payment type* can only come from an order collected before the day's update, because a
   collection with neither is now refused; if one appears, that money cannot be told apart
   and has to be reconciled by hand.
2. **Stop both servers:**
   ```powershell
   .\scripts\stop-all.ps1
   ```
   It prints one line per port — `stopped python (pid 1234) on 8000` and
   `stopped node (pid 5678) on 8080` — or `nothing listening on 8000` if that half is
   already down. **Closing the two windows is not enough:** the servers they started keep
   running and keep the ports open, so the next start finds the old one still answering.
3. **Leave the database alone.** `backend\data\the_host.db` holds the evening's real orders
   and visitors, and the report needs them. `reset-for-gala.ps1` keeps every earlier
   database in `backend\data\backups\` as well.
4. Pack the microphone, the speaker and both chargers.
