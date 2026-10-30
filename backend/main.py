import asyncio
import csv
import hmac
import io
import json
import logging
import re
import secrets
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StrictBool, StrictInt, ValidationError

import config
import data
import event_bus
import health
import netlify_feedback
import prompts
import summaries
import live_session
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


# -------------------------------------------------------------- the log file


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def log_file_path(directory, now=None) -> Path:
    """16 section 2t item 7: the log file, named for its day.

    The name is fixed when the backend starts, so a run that crosses midnight
    keeps writing to the file it opened. A gala evening is one run, and the next
    start opens the next day's file.
    """
    day = (now or datetime.now()).strftime("%Y-%m-%d")
    return Path(directory) / f"the_host-{day}.log"


def remove_file_logging() -> None:
    """Detach the log file handler (16 section 2t item 7).

    The lifespan runs once per process in production, but a test that starts the
    app leaves the handler on the root logger otherwise, and every later test in
    the session then writes into that run's file.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_the_host_log_file", False):
            root.removeHandler(handler)
            handler.close()


def setup_file_logging(directory=None, now=None) -> Path:
    """Write the same INFO lines the console gets to a file as well.

    The evidence for a phase lived only in a terminal that scrolls away, so the
    22 Oct retest could not be re-read afterwards. The handler carries the token
    filter too, because a redaction that holds only on the console is no
    redaction at all once the line is on disk.
    """
    path = log_file_path(directory or config.LOG_DIR, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(REDACT_TOKEN)
    remove_file_logging()
    handler._the_host_log_file = True
    logging.getLogger().addHandler(handler)
    return path


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
    """16 section 2b item 11: expire abandoned drafts even with no traffic.

    16 section 2zf item 3(f): and, in the same sweeper, cancel an order nobody
    ever came to the counter to pay for. The activity row is written here
    because `data` cannot reach `summaries`.
    """
    while True:
        await asyncio.sleep(config.PENDING_SWEEP_INTERVAL_S)
        try:
            await asyncio.to_thread(data.expire_pending_orders)
        except Exception:
            log.exception("draft sweep failed")
        try:
            unpaid = await asyncio.to_thread(data.expire_unpaid_orders)
        except Exception:
            log.exception("unpaid-order sweep failed")
        else:
            for order_id in unpaid:
                # 16 section 2zi item 3(b): by its number -- an unpaid order was
                # placed, so it has one.
                swept = await asyncio.to_thread(data.get_order, order_id)
                summaries.emit_activity(
                    "order",
                    f"Order #{(swept or {}).get('order_no') or order_id} "
                    "cancelled (unpaid)",
                    None,
                    None,
                )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    log_path = setup_file_logging()
    log.info("log file %s", log_path)
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key."
        )
    menu_changes = data.init_db()
    menu_items = data.load_menu()
    app.state.menu_items = menu_items
    app.state.boot_id = secrets.token_hex(3)
    app.state.present = False
    app.state.person_id = None
    event_bus.set_loop(asyncio.get_running_loop())
    # 16 section 2zb item 8: the menu followed menu.json at this startup, so
    # anything it changed is announced once the bus has a loop to publish on.
    # Nothing is connected this early -- the display and the dashboard both
    # fetch /api/menu when they open -- so this is the audit trail of a menu
    # that moved while the stall was shut, and the live signal if it ever
    # happens with a client already listening.
    for name, available in menu_changes:
        event_bus.publish(
            {
                "type": "menu_updated",
                "item": name,
                "available": available,
                "session_id": None,
            }
        )
    if menu_changes:
        log.info("menu_updated published for %s item(s)", len(menu_changes))
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
    tasks = [
        asyncio.create_task(_heartbeat_loop()),
        asyncio.create_task(_sweep_loop()),
        # 16 section 2zi item 4(b): the guests' forms, at startup then every
        # minute. With no token it logs once and stops.
        asyncio.create_task(netlify_feedback.import_loop()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        event_bus.set_loop(None)
        remove_file_logging()


app = FastAPI(lifespan=lifespan)


class PosterFiles(StaticFiles):
    """The `/posters` mount (16 section 2ze item 5).

    2v item 5 left the backend serving no static files at all; the posters are
    the one exception, because the TV's idle screen is Rehman's own pictures and
    he adds them during the gala. The folder is looked up on every request
    instead of being captured at startup, so the mount survives a folder that
    is created, emptied or renamed while the backend is running -- and a missing
    folder answers 404 rather than stopping the backend from starting.

    Starlette's own `commonpath` check still rejects any path that resolves
    outside the folder.
    """

    def lookup_path(self, path: str):
        self.all_directories = [config.POSTERS_DIR]
        return super().lookup_path(path)


app.mount(
    "/posters",
    PosterFiles(directory=config.POSTERS_DIR, check_dir=False),
    name="posters",
)

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
        # 16 section 2zk item 3: "kept across reloads". A TV that reloads mid
        # gala gets the mode and the toggle back in the snapshot rather than
        # falling back to a default and quietly opening its microphone.
        "listening": LISTENING["on"],
        "listening_mode": LISTENING["mode"],
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
        # 12 section 3 / 2e item 7: the same per-component status the event
        # stream sends, so a terminal check and the dashboard always agree.
        # Camera, microphone and speaker are browser-local and never reported.
        "components": {
            "backend": "online",
            "ai_agent": health.ai_agent_status(),
            "database": db_status,
        },
        # 16 section 2zi item 4(e): what preflight reads for its one new line.
        # No token needed and no secret in it: a state, a time, and at most an
        # exception type.
        "feedback_import": netlify_feedback.STATUS.view(),
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


@app.get("/api/metrics", dependencies=[Depends(require_operator_token)])
def get_metrics():
    """12 section 3 / 2e item 6. Real counts or an error, never a guess."""
    return _read_db(data.get_metrics)


@app.get("/api/earnings", dependencies=[Depends(require_operator_token)])
def get_earnings():
    """16 section 2z item 4: today's money, computed on request.

    Operator only, like the metrics: it never reaches /display and THE HOST has
    no tool for it.
    """
    return _read_db(data.get_earnings)


@app.get("/api/feedback", dependencies=[Depends(require_operator_token)])
def get_feedback():
    """16 section 2zi item 4(c): the guests' forms, and what they told THE HOST.

    Two lists that are never mixed: `form` is what guests filled in on Rehman's
    Netlify page, `spoken` is what a guest asked THE HOST to pass on. Operator
    only, and never on `/display`.
    """
    return {
        "form": _read_db(data.list_form_feedback),
        "spoken": _read_db(data.list_spoken_feedback),
        "summary": _read_db(data.form_feedback_summary),
        # So the page can say "import off" rather than "no feedback yet".
        "import_status": netlify_feedback.STATUS.view(),
    }


@app.get("/api/feedback.csv", dependencies=[Depends(require_operator_token)])
def get_feedback_csv():
    """16 section 2zi item 4(c): the form rows, for Rehman to keep."""
    rows = _read_db(data.list_form_feedback)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(data.FORM_FEEDBACK_COLUMNS))
    for row in rows:
        writer.writerow(
            ["" if row.get(name) is None else row[name] for name in data.FORM_FEEDBACK_COLUMNS]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bite-and-pour-feedback-{data._today()}.csv"'
            )
        },
    )


@app.get("/api/earnings.csv", dependencies=[Depends(require_operator_token)])
def get_earnings_csv():
    """16 section 2z item 6: the end-of-day sheet, one row per real order.

    No transcript and no session data: order number, time, name, items, total,
    status, how it was paid, and whether it was on the house.
    """
    rows = _read_db(data.earnings_rows)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            # 16 section 2zi item 3(b): the number the guest was given comes
            # first, because that is what a receipt or a query names. The
            # internal id stays beside it: the operator API keys on it.
            "order_no",
            "order_id",
            "time",
            "guest_name",
            "items",
            "total_rs",
            "status",
            "payment_method",
            # 16 section 2zf item 3(i): when the team marked the money taken,
            # empty for an order that was never paid or was collected before
            # pay-first existed.
            "paid_at",
            "on_the_house",
        ]
    )
    for order in rows:
        items = "; ".join(
            f"{max(1, int((entry or {}).get('quantity', 1) or 1))}x {(entry or {}).get('name')}"
            for entry in order["items"] or []
            if (entry or {}).get("name")
        )
        amount = data.order_rupees(order["items"])
        writer.writerow(
            [
                order.get("order_no") or "",
                order["id"],
                (order.get("timestamp") or "")[11:19],
                order.get("guest_name") or "",
                items,
                "" if amount is None else amount,
                order["status"],
                order.get("payment_method") or "",
                order.get("paid_at") or "",
                "yes" if order.get("complimentary") else "no",
            ]
        )
    today = _read_db(data.get_earnings)["date"]
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="bite-and-pour-sales-{today}.csv"'
            )
        },
    )


@app.get("/api/menu")
def get_menu():
    rows = _read_db(data.get_menu)
    return {"menu": [{**row, "available": bool(row["available"])} for row in rows]}


# 16 section 2ze item 5: the picture types the TV shows. A README.txt, a
# thumbs.db or anything else in the folder is not a poster and is not listed.
POSTER_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")


def list_posters() -> list[str]:
    """The poster URLs, sorted by file name, read fresh from the folder.

    Rehman drops his pictures in during the gala, so the folder is read on
    every request rather than at startup: a new poster appears on the TV within
    the display's own refresh, with no restart.
    """
    try:
        entries = sorted(config.POSTERS_DIR.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        # A missing or unreadable folder simply has no posters in it; the
        # display falls back to the brand screen.
        log.warning("the poster folder could not be read: %s", type(exc).__name__)
        return []
    return [
        f"/posters/{entry.name}"
        for entry in entries
        if entry.is_file() and entry.suffix.lower() in POSTER_SUFFIXES
    ]


@app.get("/api/posters")
def get_posters():
    """Public, like /api/menu: the display reads it with no token (2ze item 5)."""
    return {"posters": list_posters()}


# ------------------------------------------------------------ operator writes


class OrderStatusUpdate(BaseModel):
    status: str
    reason: str | None = None
    # 16 section 2z item 2: how the guest paid, recorded at collection only.
    payment_method: str | None = None


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
            "order_number": order.get("order_no"),
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

    method = (body.payment_method or "").strip().upper() or None
    if method is not None and method not in data.PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Payment is recorded at collection.")

    existing = await asyncio.to_thread(_read_db, data.get_order, order_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="There is no order with that number.")

    # 16 section 2zf item 3(d): this is the moment the team marks the money
    # taken -- CONFIRMED on an order that was waiting for payment. The method
    # recorded here is the one they really took, and it may differ from the one
    # the guest named when the order was placed.
    paying = body.status == "CONFIRMED" and existing["status"] == "AWAITING_PAYMENT"
    if method is not None:
        # 16 section 2z item 2, as 2zf item 3 amends it: a payment type belongs
        # to the payment or to the old collection path, and nowhere else.
        if not paying and body.status != "COLLECTED":
            raise HTTPException(status_code=400, detail="Payment is recorded at collection.")
        # And never to an order the team gave away.
        if existing.get("complimentary"):
            raise HTTPException(status_code=400, detail="This order is on the house.")
    if paying and method is None:
        raise HTTPException(status_code=400, detail="Choose Cash or QR.")
    # 16 section 2ze item 6(a): order #101 reached COLLECTED with no payment
    # type at all, so that sale could not be counted as cash or as QR. A paid
    # order is now collected only with one of the two, whatever the caller --
    # the dashboard's own Collected button, a page still running an older
    # build, or the operator API by hand. 2zf item 3(h): under pay-first the
    # method is already on the order by then, which is why collection is one
    # button again. An order on the house has nothing to record.
    if (
        body.status == "COLLECTED"
        and not existing.get("complimentary")
        and method is None
        and not existing.get("payment_method")
    ):
        raise HTTPException(status_code=400, detail="Choose Cash or QR.")

    result = await asyncio.to_thread(
        _read_db, data.update_order_status, order_id, body.status, body.reason, method
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["error"])

    view = data.order_view(result["order"])
    event_bus.publish({"type": "order_updated", "order": view, "session_id": None})
    if body.status == "READY":
        # order_ready follows its order_updated immediately (04 section 5 step 2).
        await _run_announcement(result["order"])

    if paying:
        # 16 section 2zf item 3(e): THE HOST is told, but only when the order
        # belongs to the guest it is talking to right now. Anyone else's order
        # is none of this conversation's business.
        session = ACTIVE
        if session is not None and session.owns_order(result["order"]):
            try:
                await session.inject(
                    "payment",
                    prompts.PAYMENT_TEMPLATE.format(
                        # 16 section 2zi item 3(b): the number the guest was
                        # given, falling back to the id for an order placed
                        # before the column existed.
                        order_number=result["order"].get("order_no") or order_id
                    ),
                )
            except Exception:
                # The order is paid and both screens know: a line that could
                # not be spoken must never fail the operator's press.
                log.exception("the paid-order line could not be spoken")

    # 16 section 2zf item 3(d): the payment gets a row of its own, so the feed
    # reads as what happened at the counter rather than "updated".
    # 16 section 2zi item 3(b): the feed names the order the way the team and the
    # guest both know it. An order from before the column has no number, and its
    # id is the only name it ever had.
    shown = result["order"].get("order_no") or order_id
    label = (
        f"Order #{shown} paid ({'cash' if method == 'CASH' else 'QR'})"
        if paying
        else f"Order #{shown} ready"
        if body.status == "READY"
        else f"Order #{shown} updated"
    )
    summaries.emit_activity("order", label, body.status.lower(), None)
    await asyncio.to_thread(
        data.log_system_event,
        "operator_action",
        "operator",
        {
            "action": "order_status",
            "order_id": order_id,
            "status": body.status,
            # 16 section 2z item 2: the audit row says how it was paid.
            "payment_method": method,
        },
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
    # 16 section 2l item 4: an operator ending a conversation is a normal end,
    # not a broken one (07 section 3: the same clean shutdown as any other), so
    # 2a item 17 still applies and the open draft is cancelled with it.
    if session.end_reason is None:
        session.end_reason = "operator"
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


# 16 section 2zf item 6: long enough for a real instruction, short enough that
# nobody pastes a paragraph into a live conversation.
NOTE_MIN_CHARS = 1
NOTE_MAX_CHARS = 300


class OperatorNote(BaseModel):
    text: str = Field(min_length=NOTE_MIN_CHARS, max_length=NOTE_MAX_CHARS)


@app.post("/api/session/note", dependencies=[Depends(require_operator_token)])
async def post_session_note(request: Request):
    """16 section 2zf item 6: Rehman steers the conversation without speaking.

    The note reaches THE HOST as a user turn carrying the bracketed prefix of
    `prompts.OPERATOR_NOTE_TEMPLATE`, deferred while THE HOST is speaking, and
    `21` Part A's OPERATOR NOTES section is what stops it ever being read out.

    The text itself is never logged and never stored: the log line counts its
    characters and the activity row says only that a note was sent.
    """
    try:
        body = OperatorNote.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid note.")
    text = " ".join(body.text.split())
    if not text:
        raise HTTPException(status_code=400, detail="Invalid note.")

    session = ACTIVE
    if session is None:
        raise HTTPException(status_code=409, detail="No conversation is running.")

    log.info(
        "operator note session %s chars=%s", session.ctx["session_id"], len(text)
    )
    try:
        await session.inject("note", prompts.OPERATOR_NOTE_TEMPLATE.format(text=text))
    except Exception:
        log.exception("the operator note could not be sent")
        raise HTTPException(status_code=503, detail="The note could not be sent.")

    summaries.emit_activity("operator", "Operator note sent", None, session.ctx["session_id"])
    # The audit row records that a note was sent and how long it was, never
    # a word of it (12 section 1, and 2zf item 6's "no detail").
    await _log_operator_action("session_note", chars=len(text))
    return {"sent": True}


# 16 section 2zk item 3: who is holding the microphone, and how. Operator is
# the default mode -- after the 30 Oct demo Rehman decides when THE HOST is
# listening -- and listening itself always starts off, because a microphone that
# is open before anybody asked is what the whole section is about. Module level
# beside ACTIVE for the same reason: one stall, one conversation at a time.
LISTENING = {"on": False, "mode": "operator"}
LISTENING_MODES = ("operator", "automatic")


class ListeningRequest(BaseModel):
    """Either half may be sent on its own: the toggle, the mode, or both."""

    on: StrictBool | None = None
    mode: Literal["operator", "automatic"] | None = None


def _publish_listening(on: bool) -> None:
    LISTENING["on"] = on
    event_bus.publish({"type": "listening", "on": on, "session_id": None})


def _publish_listening_mode(mode: str) -> None:
    LISTENING["mode"] = mode
    event_bus.publish({"type": "listening_mode", "mode": mode, "session_id": None})


def listening_off(reason: str) -> None:
    """2zk item 3(a): a conversation ending turns listening off, for any reason.

    The next guest must never walk up to a microphone that the last one left
    open. Safe to call when it is already off -- then it says nothing.
    """
    if not LISTENING["on"]:
        return
    log.info("listening off reason=%s", reason)
    _publish_listening(False)


@app.post("/api/listening", dependencies=[Depends(require_operator_token)])
async def post_listening(request: Request):
    """16 section 2zk item 3: Start listening, Stop listening, and the mode.

    The backend only relays: it is `/display` that holds the microphone, so
    this publishes to the `smd` role and the page acts on it. Start listening
    with no conversation running is what makes the page open one (trigger
    `button`, so THE HOST greets); the page decides that, because only the page
    knows whether its own socket is up.

    Carries no text and no token, and the body is two optional fields.
    """
    try:
        body = ListeningRequest.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid listening request.")
    if body.on is None and body.mode is None:
        raise HTTPException(status_code=400, detail="Invalid listening request.")

    if body.mode is not None and body.mode != LISTENING["mode"]:
        _publish_listening_mode(body.mode)
        _operator_row(f"listening mode: {body.mode}")
        await _log_operator_action("listening_mode", mode=body.mode)
    if body.on is not None:
        _publish_listening(body.on)
        _operator_row("started listening" if body.on else "stopped listening")
        await _log_operator_action("listening", on=body.on)
    return {"on": LISTENING["on"], "mode": LISTENING["mode"]}


@app.post("/api/display/reload", dependencies=[Depends(require_operator_token)])
async def post_display_reload():
    """16 section 2zf item 8(c): Rehman's own control for the TV.

    The TV is across the stall on a kiosk browser with no keyboard, so when it
    looks wrong there is no F5 to press. This publishes one event to the `smd`
    role only -- the dashboard never reloads itself because the TV was asked to
    -- and `/display` reloads on it.
    """
    event_bus.publish({"type": "display_reload", "session_id": None})
    _operator_row("reloaded the display screen")
    await _log_operator_action("display_reload")
    return {"sent": True}


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
            "order_number": order.get("order_no"),
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
    # 16 section 2h item 3: `voice` joins the triggers the page may ask for --
    # the guest started speaking while the booth sat idle.
    trigger = websocket.query_params.get("trigger", "button")
    if trigger not in ("presence", "voice"):
        trigger = "button"
    # 16 section 2zk item 3(c): which listening mode the page is in, which is
    # what picks the start-of-speech sensitivity. Anything unrecognised, and a
    # page old enough to send nothing, takes the automatic path: LOW is the
    # conservative setting, and HIGH is only right once an operator has said a
    # guest is speaking.
    listen = websocket.query_params.get("listen", "auto")
    if listen not in live_session.LISTEN_MODES:
        listen = "auto"

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
        # 16 section 2ze item 6(c): until now the only refusal with a line of
        # its own was the operator override, so a second page quietly turned
        # away left nothing in the log to explain why it went no further.
        log.info("session refused: another session is active")
        await refuse("Another conversation is already active.")
        return

    session = LiveSession(websocket, trigger, listen)
    ACTIVE = session
    session_id = session.ctx["session_id"]
    started_at = monotonic()
    log.info("session %s started trigger=%s listen=%s", session_id, trigger, listen)
    try:
        await session.run()
    finally:
        ACTIVE = None
        # 16 section 2zk item 3(a): the conversation is over, so the microphone
        # closes with it -- however it ended, including a crash or the guest
        # walking off. The next guest starts from NOT LISTENING.
        listening_off("session ended")
        log.info(
            "session %s ended trigger=%s duration=%.2fs",
            session_id,
            trigger,
            monotonic() - started_at,
        )


# ------------------------------------------------------------- the root page

# 16 section 2v item 5: THE HOST is the display screen now, and the backend
# serves no static files at all -- just this one line, for anyone who opens the
# backend's own address by habit.
ROOT_PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>THE HOST</title></head>
<body>
<p>THE HOST backend is running. The display screen is at
<a href="http://localhost:8080/display">http://localhost:8080/display</a></p>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def get_root() -> HTMLResponse:
    """16 section 2v item 5: a tiny page saying where THE HOST actually is."""
    return HTMLResponse(ROOT_PAGE, headers={"Cache-Control": "no-store"})
