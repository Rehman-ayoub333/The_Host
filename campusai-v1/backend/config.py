import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _resolved_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name, default))
    return (path if path.is_absolute() else BASE_DIR / path).resolve()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Puck")
TIMETABLE_JSON_PATH = _resolved_path("TIMETABLE_JSON_PATH", "./data/timetable.json")
DEMO_DATA_JSON_PATH = _resolved_path("DEMO_DATA_JSON_PATH", "./data/demo_data.json")
DB_PATH = _resolved_path("DB_PATH", "./data/campus_ai.db")
FRONTEND_DIR = _resolved_path("FRONTEND_DIR", "../frontend")
PORT = int(os.getenv("PORT", "8000"))

CONNECT_TIMEOUT_S = 15
TOOL_TIMEOUT_S = 10
WEB_SEARCH_TIMEOUT_S = 8
MAX_TIMETABLE_MATCHES_RETURNED = 15
MAX_TEXT_INPUT_CHARS = 500
MAX_IMAGE_BASE64_CHARS = 2_800_000
MAX_COMPLAINT_ROOM_CHARS = 60
MAX_COMPLAINT_ISSUE_CHARS = 200
RECORDS_DEFAULT_LIMIT = 10
RECORDS_MAX_LIMIT = 50
INPUT_AUDIO_MIME = "audio/pcm;rate=16000"