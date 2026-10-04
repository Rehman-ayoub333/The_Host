import logging
import sqlite3
from contextlib import asynccontextmanager, closing
from time import monotonic
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.staticfiles import StaticFiles

import config
import data
import schemas
import summaries
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
    timetable_rows = data.load_timetable()
    app.state.timetable_rows = timetable_rows
    log.info(
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


@app.get("/api/records")
def records(limit: int = Query(default=config.RECORDS_DEFAULT_LIMIT)):
    limit = max(1, min(config.RECORDS_MAX_LIMIT, limit))
    try:
        rows = data.get_recent_log(limit)
        result = []
        for row in rows:
            tool = row["tool"]
            input_args = row["input_args"]
            tool_result = row["result"]
            result.append(
                {
                    "timestamp": row["timestamp"],
                    "tool": tool,
                    "summary": summaries.summarize_done(tool, input_args, tool_result),
                    "source": tool_result.get("source", summaries.default_source(tool)),
                }
            )
        return {"records": result}
    except Exception as exc:
        log.warning("failed to load recent records: %s", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Recent records are unavailable.",
        ) from exc


@app.websocket("/ws/session")
async def websocket_session(websocket: WebSocket):
    global ACTIVE

    await websocket.accept()
    trigger = websocket.query_params.get("trigger", "button")
    if trigger != "presence":
        trigger = "button"
    if ACTIVE is not None:
        await websocket.send_text(
            schemas.ControlMessage(
                type="error",
                message="Another conversation is already active.",
            ).model_dump_json(exclude_none=True)
        )
        await websocket.close()
        return

    session_id = uuid4().hex[:8]
    session = LiveSession(websocket, trigger)
    ACTIVE = session
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