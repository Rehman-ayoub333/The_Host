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
6. **Do one full test order,** end to end:
   ```powershell
   .\scripts\start-all.ps1
   ```
   Open the voice page, order one item out loud, give a first name, confirm, then on the
   dashboard move the order PREPARING → READY → COLLECTED and watch the display screen
   announce it. Then run `reset-for-gala.ps1` once more so the gala starts clean.
7. **Stop both servers** and close the laptop.

---

## 2. Setting up at the stall

Three windows, in this order.

| Window | Address | Where it goes |
|---|---|---|
| The voice page | `http://127.0.0.1:8000/?debug=mic` | Booth laptop, **full screen**, facing the guests |
| The display screen | `http://localhost:8080/display` | Second monitor or TV, **full screen** |
| The dashboard | `http://localhost:8080/` | Operator's screen |

1. **Start everything:**
   ```powershell
   cd F:\PIAIC_6_PROJECTS\THE_HOST
   .\scripts\start-all.ps1
   ```
2. **The voice page must stay visible.** THE HOST greets guests by itself, and presence
   detection pauses while the tab is hidden. A partly overlapped window is fine; a
   minimised one is not. `?debug=mic` shows the microphone readout so you can see it is
   hearing.
3. **The display screen** goes on the second monitor or the TV. In Windows press
   `Win + P` and choose **Extend** (not Duplicate), drag the browser window across, then
   press `F11` for full screen.
4. **The microphone.** Plug in the handheld microphone and set it as the Windows default
   input: right-click the speaker icon → Sound settings → Input → choose the handheld
   microphone. Say a few words and watch the input level move.
5. **The operator token.** On the dashboard open **Settings**, paste the token into
   *Operator token*, and press **Save & connect**. The agent link must read `LIVE`.
6. **Run preflight until every line is PASS:**
   ```powershell
   .\scripts\preflight.ps1
   ```

---

## 3. Roles

| Who | Looks after |
|---|---|
| **Rehman** | THE HOST and the voice page — that it is visible, hearing, and talking to guests |
| **Saad** | The dashboard — moves every order PREPARING → READY → COLLECTED |
| **Umair** | The display screen, and the backup checks in section 5 |

One person to a job. If something looks wrong, say so out loud rather than reaching across
to someone else's laptop.

---

## 4. During the gala

### The kitchen flow

A guest orders by talking to THE HOST. The order appears on the dashboard as a draft while
it is being taken, and becomes a real order the moment the guest confirms. From then on it
is Saad's:

1. **PREPARING** — the kitchen has started it.
2. **READY** — it is on the counter. The display screen announces
   *"Order #27 for Ahmed is ready!"* and speaks it aloud.
3. **COLLECTED** — the guest has taken it.

**Announce again** re-plays a ready announcement if the guest missed it.

### The operator buttons (dashboard → System)

| Button | What it does | When to use it |
|---|---|---|
| **Pause THE HOST** | Stops THE HOST talking and ends the current conversation | A break, or a queue that needs clearing by hand |
| **Take over** | Hands the stall to a person; THE HOST stops | A guest needs a human |
| **End conversation** | Ends just the conversation running now | Someone is monopolising it, or it has got stuck |
| **Retry connection** | Tests the AI service once, now | After the internet has been fixed |

Pause, Take over and End conversation ask you to confirm first. **Resume THE HOST** puts it
back to work.

### If something goes wrong

- **A short outage.** The mode shows *"Reconnecting…"* in amber and THE HOST recovers by
  itself. Wait. Do not restart anything.
- **The venue internet fails.** Switch the booth laptop to the phone hotspot, then press
  **Retry connection** on the dashboard. The mode should return to `ONLINE`.
- **Nothing works.** Open **Settings → Demo Mode (backup)** and press **Start Demo Mode**.
  Every screen carries a `DEMO DATA` badge while it runs. **Say out loud that this is a
  demonstration, not a live order.** Press **Exit demo** to go back to the live system.

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
.\scripts\preflight.ps1
```

**`.env` is not in the repository and never will be.** Copy `backend\.env` from the booth
laptop by USB stick, by hand. Do not email it, do not put it in a chat, and delete it from
the USB stick afterwards.

---

## 6. After the gala

1. Stop both servers: press `Ctrl + C` in each window, or close them.
2. **Leave the database alone.** `backend\data\the_host.db` holds the evening's real orders
   and visitors, and the report needs them. `reset-for-gala.ps1` keeps every earlier
   database in `backend\data\backups\` as well.
3. Pack the microphone, the speaker and both chargers.
