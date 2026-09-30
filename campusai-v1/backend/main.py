import logging
import sqlite3
from contextlib import asynccontextmanager, closing

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import config
import data


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    data.init_db()
    timetable_rows = data.load_timetable()
    app.state.timetable_rows = timetable_rows
    logging.getLogger(__name__).info(
        "model=%s voice=%s timetable_rows=%s db=%s",
        config.GEMINI_LIVE_MODEL,
        config.GEMINI_VOICE,
        timetable_rows,
        config.DB_PATH,
    )
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    try:
        with closing(sqlite3.connect(config.DB_PATH)) as conn:
            conn.execute("SELECT 1").fetchone()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {
        "status": "ok",
        "model": config.GEMINI_LIVE_MODEL,
        "timetable_rows": getattr(app.state, "timetable_rows", 0),
        "db": db_status,
    }


app.mount(
    "/",
    StaticFiles(directory=config.FRONTEND_DIR, html=True),
    name="frontend",
)