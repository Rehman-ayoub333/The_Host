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
GEMINI_VOICE = os.getenv("GEMINI_VOICE", "Puck")
OPERATOR_TOKEN = os.getenv("OPERATOR_TOKEN", "")
AGENT_NAME = os.getenv("AGENT_NAME", "THE HOST")
STALL_NAME = os.getenv("STALL_NAME", "Bite & Pour")
MENU_JSON_PATH = _resolved_path("MENU_JSON_PATH", "./data/menu.json")
BUSINESS_INFO_JSON_PATH = _resolved_path("BUSINESS_INFO_JSON_PATH", "./data/business_info.json")
DB_PATH = _resolved_path("DB_PATH", "./data/campus_ai.db")
FRONTEND_DIR = _resolved_path("FRONTEND_DIR", "../frontend")
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
