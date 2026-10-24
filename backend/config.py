import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)


def _resolved_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default))
    return (path if path.is_absolute() else BASE_DIR / path).resolve()


def _origins(name: str, default: str) -> list[str]:
    return [origin.strip() for origin in os.getenv(name, default).split(",") if origin.strip()]


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
# 16 section 2e item 3: Sulafat after the Phase 4 check. A value in .env wins.
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Sulafat")
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "")
AGENT_NAME = os.getenv("AGENT_NAME", "THE HOST")
STALL_NAME = os.getenv("STALL_NAME", "Bite & Pour")
MENU_JSON_PATH = _resolved_path("MENU_JSON_PATH", "./data/menu.json")
BUSINESS_INFO_JSON_PATH = _resolved_path("BUSINESS_INFO_JSON_PATH", "./data/business_info.json")
DB_PATH = _resolved_path("DB_PATH", "./data/the_host.db")
# 16 section 2v item 5: FRONTEND_DIR is gone. The backend serves no static
# files; THE HOST is the display screen. A value left behind in a .env is read
# by nothing.
# 16 section 2t item 7: the console scrolls away and a phase's evidence is gone
# with it. The same INFO lines are also written to a file named for the day.
LOG_DIR = _resolved_path("LOG_DIR", "./logs")
CORS_ALLOW_ORIGINS = _origins(
    "CORS_ALLOW_ORIGINS",
    "http://localhost:8080,http://localhost:5173,http://localhost:4173",
)
PORT = int(os.getenv("PORT", "8000"))
# 16 section 2d item 4: how a snapshot reaches Gemini. "client_content" sends the
# picture and the prompt as one user turn; "realtime" is the older two-call path.
VISION_SEND_MODE = os.getenv("VISION_SEND_MODE", "client_content").strip() or "client_content"

CONNECT_TIMEOUT_S = 15
TOOL_TIMEOUT_S = 10
WEB_SEARCH_TIMEOUT_S = 8
MAX_TEXT_INPUT_CHARS = 500
MAX_IMAGE_BASE64_CHARS = 2_800_000
INPUT_AUDIO_MIME = "audio/pcm;rate=16000"
PENDING_ORDER_TTL_S = 300
PENDING_SWEEP_INTERVAL_S = 60
HEARTBEAT_INTERVAL_S = 10
EVENT_SEND_TIMEOUT_S = 1
VISION_MAX_PEOPLE = 50
VISION_MAX_OBJECTS = 10
LOOK_TIMEOUT_S = 6
# 16 section 2f item 5: how long an immediate announcement waits and looks again,
# so a guest who has only just started speaking is not talked over.
ANNOUNCE_GRACE_S = 0.8
# 16 section 2g item 4: room noise latches the page's voice flag, so a flag that
# has been true this long with no transcription behind it is treated as inactive.
VOICE_ACTIVE_STALE_S = 10
# 16 section 2g item 4: however busy the conversation looks, a ready order waits
# no longer than this before it is spoken.
ANNOUNCE_MAX_DEFER_S = 20
# 16 section 2j item 6: Google's guidance is 500-800 ms and the server default is
# about 800, which made every reply feel a beat late at the booth.
SILENCE_DURATION_MS = 500
# 16 section 2r item 5: how much audio from just before the server decided the
# guest had started speaking is kept. A short soft reply ("yes", a name) loses
# its first syllable without this, which is one way it goes unheard.
PREFIX_PADDING_MS = 300
# 16 section 2j item 5: Gemini has heard the guest, or has been given a tool
# result, and nothing has come back for this long. The conversation is not over,
# so the connection is rebuilt rather than the session ended.
#
# 16 section 2zb item 5 raises it from 8 to 15. The 7i-b diagnosis timed eight
# safety turns: the backend answered every tool in 15-24 ms, and Gemini's own
# time before speaking ran to 7.7 s after the tool response and to 17.7 s before
# the tool call. At 8 s the watchdog turned a slow but healthy turn into a
# reconnect, a lost context and "Sorry, I missed that" -- twice, on the one
# scenario where speed matters most ("Someone fainted here!"). A real hang is
# still caught; it now takes 15 s, and the display's "One moment…" at 3 s
# already covers the wait.
STALL_S = 15
# 16 section 2j item 4: a GoAway with more time left than this waits for the
# current turn to finish before the connection is rebuilt.
GOAWAY_TURN_GRACE_S = 5
# 16 section 2k item 2: a real outage is not instant to come back from. Both of
# 2j's attempts were spent inside ten seconds of the Wi-Fi going off (sessions
# ced7bcbf and 03db21d2), so recovery now keeps trying across a whole window.
RECOVER_RETRY_S = 3
RECOVER_WINDOW_S = 30
# 16 section 2l item 4: how long an unconfirmed draft from a conversation that
# broke is held for the guest to come back and claim.
ORPHAN_DRAFT_S = 180
# 16 section 2h item 5, verified at build time on 13 Oct 2026 against
# gemini-3.8-live: the setup is rejected outright with
#   Invalid JSON payload received. Unknown name "proactivity" at 'setup':
#   Cannot find field.
# so it is left off, as that item requires. The attempt-and-fall-back path in
# live_session stays in place: turning this back on is all a supporting model
# needs, and a refusal only logs `proactive_audio unsupported` once.
PROACTIVE_AUDIO = False
