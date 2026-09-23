import os

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
SHEET_TAB_NAME = os.getenv("SHEET_TAB_NAME", "Filed Records")
REVIEWER_NAME = os.getenv("REVIEWER_NAME", "Rehman Ayoub")
PORT = int(os.getenv("PORT", "8000"))

__all__ = [
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    "GOOGLE_SHEET_ID",
    "SHEET_TAB_NAME",
    "REVIEWER_NAME",
    "PORT",
]
