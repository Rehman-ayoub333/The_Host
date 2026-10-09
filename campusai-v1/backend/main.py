import asyncio
import hmac
import json
import logging
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, closing
from time import monotonic

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import config
import data
import event_bus
import health
import summaries
from live_session import LiveSession


log = logging.getLogger(__name__)
ACTIVE: LiveSession | None = None

LIMIT_MIN = 1
LIMIT_MAX = 100


# ----------------------------------------------------------- token redaction


class RedactTokenFilter(logging.Filter):
    """16 section 2b item 12.

    The dashboard token travels as `?token=` on `/ws/events` because a browser
    cannot set a header on a WebSocket handshake, and uvicorn's access logger
    prints the request path. This rewrites the value before it is ever written.
    """

    PATTERN = re.compile(r"(token=)[^\s\"'&]+")
    REPLACEMENT = r"\1[REDACTED]"

    def _clean(self, value):
        if isinstance(value, str):
            return self.PATTERN.sub(self.REPLACEMENT, value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._clean(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(item) for item in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: self._clean(item) for key, item in record.args.items()}
        return True


REDACT_TOKEN = RedactTokenFilter()
for _logger_name in ("uvicorn.access", "uvicorn.error"):
    logging.getLogger(_logger_name).addFilter(REDACT_TOKEN)


def _clamp(limit: int, default: int) -> int:
    try:
        return max(LIMIT_MIN, min(LIMIT_MAX, int(limit)))
    except (TypeError, ValueError):
        return default


async def _heartbeat_loop() -> None:
    while True:
        await asyncio.sleep(config.HEARTBEAT_INTERVAL_S)
        event_bus.publish({"type": "heartbeat"})


async def _sweep_loop() -> None:
    """16 section 2b item 11: expire abandoned drafts even with no traffic."""
    while True:
        await asyncio.sleep(config.PENDING_SWEEP_INTERVAL_S)
        try:
            await asyncio.to_thread(data.expire_pending_orders)
        except Exception:
            log.exception("draft sweep failed")


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
    app.state.boot_id = secrets.token_hex(3)
    app.state.present = False
    app.state.person_id = None
    event_bus.set_loop(asyncio.get_running_loop())
    if not config.OPERATOR_TOKEN:
        log.warning(
            "OPERATOR_TOKEN is not set: the dashboard role and every "
            "token-protected endpoint are refused."
        )
    log.info(
        "model=%s voice=%s menu_items=%s boot_id=%s db=%s",
        config.GEMINI_LIVE_MODEL,
        config.GEMINI_VOICE,
        menu_items,
        app.state.boot_id,
        config.DB_PATH,
    )
    tasks = [asyncio.create_task(_heartbeat_loop()), asyncio.create_task(_sweep_loop())]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event_bus.set_loop(None)


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ALLOW_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Operator-Token"],
    allow_credentials=False,
)


# ------------------------------------------------------------------- security


def require_operator_token(x_operator_token: str | None = Header(default=None)) -> None:
    """12 section 2. Fails closed when OPERATOR_TOKEN is not configured."""
    expected = config.OPERATOR_TOKEN
    if not expected or not x_operator_token:
        raise HTTPException(status_code=401, detail="Operator token required.")
    if not hmac.compare_digest(x_operator_token, expected):
        raise HTTPException(status_code=401, detail="Operator token required.")


def _read_db(function, *args):
    try:
        return function(*args)
    except sqlite3.Error as exc:
        log.warning("database read failed: %s: %s", type(exc).__name__, exc)
        raise HTTPException(
            status_code=503, detail="The database could not be read."
        ) from exc


# ---------------------------------------------------------------------- state


def build_state_snapshot() -> dict:
    session = ACTIVE
    return {
        "type": "state_snapshot",
        "boot_id": getattr(app.state, "boot_id", ""),
        "operational_mode": health.mode(),
        "conversation_state": (session.last_state if session and session.last_state else "IDLE"),
        "session_id": session.ctx["session_id"] if session else None,
        "present": bool(getattr(app.state, "present", False)),
        "active_orders": data.list_orders("active", limit=50)["orders"],
    }


# -------------------------------------------------------------------- health


@app.get("/health")
def get_health():
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
        "operational_mode": health.mode(),
        "db": db_status,
    }


# ----------------------------------------------------------------- read REST


@app.get("/api/orders", dependencies=[Depends(require_operator_token)])
def get_orders(status: str = "all", limit: int = 20):
    return _read_db(data.list_orders, status, _clamp(limit, 20))


@app.get("/api/visitors", dependencies=[Depends(require_operator_token)])
def get_visitors(limit: int = 20):
    return {"visitors": _read_db(data.list_visitors, _clamp(limit, 20))}


@app.get("/api/activity", dependencies=[Depends(require_operator_token)])
def get_activity(limit: int = 30):
    return {"activity": _read_db(data.list_activity, _clamp(limit, 30))}


@app.get("/api/analytics", dependencies=[Depends(require_operator_token)])
def get_analytics():
    return _read_db(data.get_analytics)


@app.get("/api/menu")
def get_menu():
    rows = _read_db(data.get_menu)
    return {"menu": [{**row, "available": bool(row["available"])} for row in rows]}


# ------------------------------------------------------------ operator writes


class OrderStatusUpdate(BaseModel):
    status: str
    reason: str | None = None


class AvailabilityUpdate(BaseModel):
    # A real boolean: pydantic's lax mode would otherwise accept "no" and "off".
    available: StrictBool


async def _run_announcement(order: dict) -> None:
    """04 section 5 / 2c item 2: the guard, then order_ready, then the live voice."""
    if not await asyncio.to_thread(data.mark_announced, order["id"]):
        return
    event_bus.publish(
        {
            "type": "order_ready",
            "order_id": order["id"],
            "customer_name": order.get("guest_name"),
            "session_id": None,
        }
    )
    session = ACTIVE
    if session is None:
        # 04 section 5 step 4: the backend never opens a session just to speak.
        return
    try:
        await session.announce(order)
    except Exception:
        # The order state and order_ready are already correct, so the operator's
        # call still succeeds (2c item 3).
        log.exception("the order-ready announcement could not be spoken")


@app.post("/api/orders/{order_id}/status", dependencies=[Depends(require_operator_token)])
async def post_order_status(order_id: int, request: Request):
    """2c item 1 / 12 section 1. Transition validation lives in data.py (08 section 5)."""
    try:
        body = OrderStatusUpdate.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid status update.")
    if body.status not in data.ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status update.")

    if await asyncio.to_thread(_read_db, data.get_order, order_id) is None:
        raise HTTPException(status_code=404, detail="There is no order with that number.")

    result = await asyncio.to_thread(
        _read_db, data.update_order_status, order_id, body.status, body.reason
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    view = data.order_view(result["order"])
    event_bus.publish({"type": "order_updated", "order": view, "session_id": None})
    if body.status == "READY":
        # order_ready follows its order_updated immediately (04 section 5 step 2).
        await _run_announcement(result["order"])

    label = (
        f"Order #{order_id} ready"
        if body.status == "READY"
        else f"Order #{order_id} updated"
    )
    summaries.emit_activity("order", label, body.status.lower(), None)
    await asyncio.to_thread(
        data.log_system_event,
        "operator_action",
        "operator",
        {"action": "order_status", "order_id": order_id, "status": body.status},
    )
    return {"order": view}


@app.post("/api/menu/{name}/availability", dependencies=[Depends(require_operator_token)])
async def post_menu_availability(name: str, request: Request):
    """2c item 4 / 12 section 1."""
    try:
        body = AvailabilityUpdate.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid availability update.")

    row = await asyncio.to_thread(
        _read_db, data.set_menu_availability, name, body.available
    )
    if row is None:
        raise HTTPException(status_code=404, detail="That item isn't on the menu.")

    item = {**row, "available": bool(row["available"])}
    event_bus.publish(
        {
            "type": "menu_updated",
            "item": item["name"],
            "available": item["available"],
            "session_id": None,
        }
    )
    summaries.emit_activity(
        "operator",
        f"Marked {item['name']} available" if item["available"] else f"Marked {item['name']} sold out",
        None,
        None,
    )
    await asyncio.to_thread(
        data.log_system_event,
        "operator_action",
        "operator",
        {"action": "menu_availability", "item": item["name"], "available": item["available"]},
    )
    return {"item": item}


# ----------------------------------------------------- the operator audit trail


async def _log_operator_action(action: str, **fields) -> None:
    """12 section 1: every operator action lands in system_events."""
    await asyncio.to_thread(
        data.log_system_event,
        "operator_action",
        "operator",
        {"action": action, **fields},
    )


def _operator_row(text: str) -> None:
    """The one activity shape every operator control emits (2e items 4 and 5)."""
    summaries.emit_activity("operator", f"Operator: {text}", None, None)


# ------------------------------------------------------- visitor corrections


MAX_DISPLAY_NAME = 60
MAX_FAVORITE_ITEM = 80
VISITOR_PATCH_FIELDS = ("display_name", "favorite_item")


def _validated_visitor_patch(payload) -> dict:
    """11 section 5 / 2e item 5. Returns the fields to change, or raises 400.

    Validated by hand rather than by a model because `favorite_item: null` is a
    real instruction (clear it) that must stay distinguishable from an absent
    field, and because pydantic's lax mode would accept `7` as a name.
    """
    invalid = HTTPException(status_code=400, detail="Invalid visitor update.")
    if not isinstance(payload, dict) or not payload:
        raise invalid
    if set(payload) - set(VISITOR_PATCH_FIELDS):
        raise invalid

    changes = {}
    if "display_name" in payload:
        name = payload["display_name"]
        if not isinstance(name, str):
            raise invalid
        name = name.strip()
        if not 1 <= len(name) <= MAX_DISPLAY_NAME:
            raise invalid
        changes["display_name"] = name
    if "favorite_item" in payload:
        favorite = payload["favorite_item"]
        if favorite is not None:
            if not isinstance(favorite, str) or len(favorite) > MAX_FAVORITE_ITEM:
                raise invalid
        changes["favorite_item"] = favorite
    return changes


@app.patch("/api/visitors/{name_key}", dependencies=[Depends(require_operator_token)])
async def patch_visitor(name_key: str, request: Request):
    try:
        payload = await request.json()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid visitor update.")
    changes = _validated_visitor_patch(payload)

    profile = await asyncio.to_thread(
        _read_db,
        data.update_visitor,
        name_key,
        changes.get("display_name"),
        changes.get("favorite_item", data.UNCHANGED),
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="There is no visitor with that name.")

    event_bus.publish({**data.memory_event(profile), "session_id": None})
    _operator_row("corrected a visitor")
    await _log_operator_action("visitor_update", name_key=profile["name_key"])
    return {"visitor": data.visitor_view(profile)}


@app.delete("/api/visitors/{name_key}", status_code=204,
            dependencies=[Depends(require_operator_token)])
async def delete_visitor(name_key: str):
    """Deleted means deleted (11 section 5). Orders are never touched."""
    if not await asyncio.to_thread(_read_db, data.delete_visitor, name_key):
        raise HTTPException(status_code=404, detail="There is no visitor with that name.")

    _operator_row("forgot a visitor")
    await _log_operator_action("visitor_delete", name_key=str(name_key).lower())
    return Response(status_code=204)


# --------------------------------------------------------- operator controls


# 16 section 2e item 4: the connectivity probe. The key travels in a header and
# is never logged; the response body is never read.
MODELS_PROBE_URL = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"

PAUSED_REFUSAL = "THE HOST is paused right now. Please ask the team."


class AnnounceRequest(BaseModel):
    order_id: StrictInt


async def _end_active_session() -> bool:
    """Ends whatever conversation is running, down the normal stop() path."""
    session = ACTIVE
    if session is None:
        return False
    try:
        await session.stop()
    except Exception:
        log.exception("could not end the active session")
    return True


@app.post("/api/operator/pause", dependencies=[Depends(require_operator_token)])
async def post_operator_pause():
    mode = health.set_override("PAUSED")
    await _end_active_session()
    _operator_row("paused THE HOST")
    await _log_operator_action("pause")
    return {"operational_mode": mode}


@app.post("/api/operator/resume", dependencies=[Depends(require_operator_token)])
async def post_operator_resume():
    mode = health.set_override(None)
    _operator_row("resumed THE HOST")
    await _log_operator_action("resume")
    return {"operational_mode": mode}


@app.post("/api/operator/takeover", dependencies=[Depends(require_operator_token)])
async def post_operator_takeover():
    mode = health.set_override("OPERATOR_TAKEOVER")
    await _end_active_session()
    _operator_row("took over")
    await _log_operator_action("takeover")
    return {"operational_mode": mode}


@app.post("/api/operator/takeover/end", dependencies=[Depends(require_operator_token)])
async def post_operator_takeover_end():
    mode = health.set_override(None)
    _operator_row("ended the takeover")
    await _log_operator_action("takeover_end")
    return {"operational_mode": mode}


@app.post("/api/operator/end-session", dependencies=[Depends(require_operator_token)])
async def post_operator_end_session():
    ended = await _end_active_session()
    _operator_row("ended the conversation")
    await _log_operator_action("end_session", ended=ended)
    return {"ended": ended}


@app.post("/api/operator/retry-connection", dependencies=[Depends(require_operator_token)])
async def post_operator_retry_connection():
    """A real check, once, now. No background loop and no retry schedule."""
    reachable = False
    reason = ""
    try:
        async with httpx.AsyncClient(timeout=config.CONNECT_TIMEOUT_S) as client:
            response = await client.get(
                MODELS_PROBE_URL, headers={"x-goog-api-key": config.GEMINI_API_KEY}
            )
        reachable = response.status_code == 200
        if not reachable:
            # The status code only: the body can carry the key back.
            reason = f"The AI service answered {response.status_code}."
    except Exception as exc:
        # The type only, for the same reason.
        reason = f"The AI service could not be reached ({type(exc).__name__})."

    if reachable:
        health.connect_ok()
    else:
        log.info("retry-connection failed: %s", reason)
        health.connect_failed(reason)

    _operator_row("retried the connection")
    await _log_operator_action("retry_connection", reachable=reachable)
    return {"operational_mode": health.mode(), "reachable": reachable}


@app.post("/api/operator/announce", dependencies=[Depends(require_operator_token)])
async def post_operator_announce(request: Request):
    """A deliberate repeat: it bypasses the `announced` guard (04 section 5)."""
    try:
        body = AnnounceRequest.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid announcement request.")

    order = await asyncio.to_thread(_read_db, data.get_order, body.order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="There is no order with that number.")
    if order["status"] != "READY":
        raise HTTPException(
            status_code=400, detail="Only a READY order can be announced again."
        )

    view = data.order_view(order)
    event_bus.publish(
        {
            "type": "order_ready",
            "order_id": order["id"],
            "customer_name": order.get("guest_name"),
            "session_id": None,
        }
    )
    session = ACTIVE
    if session is not None:
        try:
            await session.announce(order)
        except Exception:
            log.exception("the repeated announcement could not be spoken")

    _operator_row(f"repeated the announcement for order #{order['id']}")
    await _log_operator_action("announce", order_id=order["id"])
    return {"order": view}


# --------------------------------------------------------------- vision input


class VisionObject(BaseModel):
    label: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0.0, le=1.0)


class VisionReport(BaseModel):
    present: bool
    people: int = Field(ge=0, le=config.VISION_MAX_PEOPLE)
    objects: list[VisionObject] = Field(default_factory=list, max_length=config.VISION_MAX_OBJECTS)


@app.post("/api/vision")
async def post_vision(request: Request):
    """03 section 8. A report, never a command: unauthenticated, 400 on anything invalid."""
    try:
        payload = await request.json()
        report = VisionReport.model_validate(payload)
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid vision report.")

    was_present = bool(getattr(app.state, "present", False))
    if report.present and not was_present:
        app.state.person_id = "p-" + secrets.token_hex(2)
        event_bus.publish(
            {"type": "person_detected", "person_id": app.state.person_id, "session_id": None}
        )
        summaries.emit_activity("vision", "Visitor detected", None, None)
    elif not report.present and was_present:
        event_bus.publish(
            {
                "type": "person_left",
                "person_id": getattr(app.state, "person_id", None),
                "session_id": None,
            }
        )
        summaries.emit_activity("vision", "Visitor left", None, None)
        app.state.person_id = None
    app.state.present = report.present

    event_bus.publish(
        {
            "type": "vision_update",
            "present": report.present,
            "people": report.people,
            "objects": [item.model_dump() for item in report.objects],
            "session_id": None,
        }
    )
    return Response(status_code=204)


# ------------------------------------------------------------------- sockets


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """Read-only observer stream (03 section 2). The server ignores what clients send."""
    role = websocket.query_params.get("role")
    # The close code only reaches the client over a completed handshake, so the
    # socket is accepted first and then closed with the documented code.
    if role not in ("dashboard", "smd"):
        await websocket.accept()
        await websocket.close(code=4400)
        return
    if role == "dashboard":
        token = websocket.query_params.get("token") or ""
        expected = config.OPERATOR_TOKEN
        if not expected or not hmac.compare_digest(token, expected):
            await websocket.accept()
            await websocket.close(code=4401)
            return

    await websocket.accept()
    event_bus.register(websocket, role)
    log.info("events observer connected role=%s", role)
    try:
        snapshot = event_bus.stamp(await asyncio.to_thread(build_state_snapshot))
        view = event_bus.filter_for(role, snapshot)
        if view is not None:
            await websocket.send_text(json.dumps(view))
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        event_bus.unregister(websocket)
        log.info("events observer disconnected role=%s", role)


@app.websocket("/ws/session")
async def websocket_session(websocket: WebSocket):
    global ACTIVE

    await websocket.accept()
    trigger = websocket.query_params.get("trigger", "button")
    if trigger != "presence":
        trigger = "button"

    async def refuse(message: str) -> None:
        await websocket.send_text(
            json.dumps(
                event_bus.stamp(
                    {
                        "type": "error",
                        "message": message,
                        "recoverable": True,
                        "session_id": None,
                    }
                )
            )
        )
        await websocket.close()

    # 16 section 2e item 4: an operator override wins over everything, so it is
    # checked before the single-session rule.
    if health.mode() in health.OVERRIDES:
        log.info("session refused: operational_mode=%s", health.mode())
        await refuse(PAUSED_REFUSAL)
        return
    if ACTIVE is not None:
        await refuse("Another conversation is already active.")
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


class NoStoreStaticFiles(StaticFiles):
    """16 section 2e item 2.

    Chrome served the pre-Phase-4 `app.js` through a whole booth test, so the
    page ignored `capture_request` and the fault looked like a backend one.
    Every file this mount serves now says `no-store`, the 404 included.
    """

    async def get_response(self, path, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Same body FastAPI's own handler would have produced, but routed
            # through here so the header is on the miss as well.
            response = JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        response.headers["Cache-Control"] = "no-store"
        return response


app.mount(
    "/",
    NoStoreStaticFiles(directory=config.FRONTEND_DIR, html=True),
    name="frontend",
)
