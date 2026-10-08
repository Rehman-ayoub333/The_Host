import json
import logging
import sqlite3
from contextlib import asynccontextmanager, closing
from time import monotonic

from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles

import config
import data
import event_bus
from live_session import LiveSession


log = logging.getLogger(__name__)
ACTIVE: LiveSession | None = None


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
    menu_items = data.load_menu()
    app.state.menu_items = menu_items
    log.info(
        "model=%s voice=%s menu_items=%s db=%s",
        config.GEMINI_LIVE_MODEL,
        config.GEMINI_VOICE,
        menu_items,
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
        "menu_items": getattr(app.state, "menu_items", 0),
        "db": db_status,
    }


@app.websocket("/ws/session")
async def websocket_session(websocket: WebSocket):
    global ACTIVE

    await websocket.accept()
    trigger = websocket.query_params.get("trigger", "button")
    if trigger != "presence":
        trigger = "button"
    if ACTIVE is not None:
        await websocket.send_text(
            json.dumps(
                event_bus.stamp(
                    {
                        "type": "error",
                        "message": "Another conversation is already active.",
                        "recoverable": True,
                        "session_id": None,
                    }
                )
            )
        )
        await websocket.close()
        return

    session = LiveSession(websocket, trigger)
    ACTIVE = session
    session_id = session.ctx["session_id"]
    started_at = monotonic()
    log.info("session %s started trigger=%s", session_id, trigger)
    try:
        await session.run()
    finally:
        ACTIVE = None
        log.info(
            "session %s ended trigger=%s duration=%.2fs",
            session_id,
            trigger,
            monotonic() - started_at,
        )


app.mount(
    "/",
    StaticFiles(directory=config.FRONTEND_DIR, html=True),
    name="frontend",
)