"""The event bus: one shape definition, two delivery paths (03 section 2).

`live_session` stamps an event once and sends it on the audio socket; everything
reaches the `/ws/events` observers through `publish`, filtered per role. The bus
stamps `event_id` and `timestamp` only — it never sets `session_id`, which the
caller owns (03 section 3).
"""

import asyncio
import collections
import contextlib
import copy
import itertools
import json
import logging
from datetime import datetime

import config


log = logging.getLogger(__name__)

# Tests read this; a live process must not grow it without limit (2b item 1).
PUBLISHED: collections.deque = collections.deque(maxlen=500)

_event_ids = itertools.count(1)
_loop: asyncio.AbstractEventLoop | None = None
_sockets: dict = {}

# The 03 section 2 role table.
SMD_NEVER = frozenset(
    {
        "memory_updated",
        "agent_activity",
        "vision_update",
        "system_status_changed",
        # Transcripts are for the operator only (16 section 2o item 2): the
        # public display receives none at all, partial or final.
        "speech_transcript",
    }
)
SMD_ALLOWED = frozenset(
    {
        "agent_state_changed",
        "person_detected",
        "person_left",
        "recommendation",
        "menu_updated",
        "operational_mode_changed",
        "interrupted",
        "error",
        "visitor_identified",
        "order_created",
        "order_updated",
        "order_ready",
        "state_snapshot",
        "heartbeat",
        # 16 section 2zf item 8(c): the operator's "Reload display screen".
        "display_reload",
        # 16 section 2zk item 3: the operator's microphone controls. `listening`
        # is the Start/Stop toggle and is what opens or silences the uplink;
        # `listening_mode` is the Settings choice between operator and automatic.
        # Both are for the TV: it is the page that holds the microphone.
        "listening",
        "listening_mode",
    }
)

# 16 section 2zf item 8(c): the one event that goes to the TV and nowhere else.
# The dashboard reloading itself because Rehman asked the TV to would be the
# opposite of a recovery control.
DASHBOARD_NEVER = frozenset({"display_reload"})
VISITOR_IDENTIFIED_PUBLIC = ("type", "name", "returning", "event_id", "timestamp", "session_id")


def set_loop(loop: asyncio.AbstractEventLoop | None) -> None:
    """Called once from the app lifespan (2b item 1)."""
    global _loop
    _loop = loop


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stamp(event: dict) -> dict:
    event["event_id"] = next(_event_ids)
    event["timestamp"] = _now()
    return event


def register(ws, role: str) -> None:
    _sockets[ws] = role


def unregister(ws) -> None:
    _sockets.pop(ws, None)


def sockets() -> dict:
    return dict(_sockets)


def filter_for(role: str, event: dict) -> dict | None:
    """The 03 section 2 table. Returns None when this role must not receive it.

    Always works on a copy; the original event is never changed.
    """
    event_type = event.get("type")
    if role == "dashboard":
        return None if event_type in DASHBOARD_NEVER else event

    if event_type in SMD_NEVER or event_type not in SMD_ALLOWED:
        return None

    view = copy.deepcopy(event)
    if event_type == "visitor_identified":
        return {key: view[key] for key in VISITOR_IDENTIFIED_PUBLIC if key in view}
    if event_type in ("order_created", "order_updated"):
        if isinstance(view.get("order"), dict):
            view["order"].pop("guest_name", None)
        return view
    if event_type == "state_snapshot":
        for order in view.get("active_orders") or []:
            if isinstance(order, dict):
                order.pop("guest_name", None)
        return view
    return view


async def _send(ws, view: dict) -> None:
    try:
        await asyncio.wait_for(
            ws.send_text(json.dumps(view)), timeout=config.EVENT_SEND_TIMEOUT_S
        )
    except Exception:
        # A slow, dead or failing observer is dropped quietly; it can never
        # disturb the audio session.
        unregister(ws)
        log.info("dropped an events observer that would not accept a send")
        with contextlib.suppress(Exception):
            await ws.close()


def _fan_out(event: dict) -> None:
    if not _sockets:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        # No running loop (a test or a standalone script): nothing to deliver to.
        return
    for ws, role in list(_sockets.items()):
        view = filter_for(role, event)
        if view is None:
            continue
        loop.create_task(_send(ws, view))


def publish(event: dict) -> None:
    if event.get("type") == "heartbeat":
        # The one event without an event_id (03 section 3).
        event.setdefault("timestamp", _now())
    elif "event_id" not in event:
        stamp(event)
    PUBLISHED.append(event)
    _fan_out(event)


def publish_threadsafe(event: dict) -> None:
    """Tools run in worker threads, so they must use this variant."""
    if _loop is not None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not _loop:
            _loop.call_soon_threadsafe(publish, event)
            return
    publish(event)
