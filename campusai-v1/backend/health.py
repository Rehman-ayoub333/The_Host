"""Operational mode (07 section 3, 10 section 4) — minimal Phase 3a version.

Holds the current mode and flips it on a Gemini connect success or failure.
DEGRADED, RECOVERING, PAUSED and OPERATOR_TAKEOVER arrive in Phase 5.
"""

import logging

import event_bus
import summaries


log = logging.getLogger(__name__)

_mode = "ONLINE"


def mode() -> str:
    return _mode


def _set_mode(new_mode: str, reason: str, component_status: str, detail) -> None:
    global _mode
    if new_mode == _mode:
        return
    _mode = new_mode
    log.info("operational_mode %s (%s)", new_mode, reason)
    event_bus.publish_threadsafe(
        {
            "type": "operational_mode_changed",
            "mode": new_mode,
            "reason": reason,
            "session_id": None,
        }
    )
    event_bus.publish_threadsafe(
        {
            "type": "system_status_changed",
            "component": "ai_agent",
            "status": component_status,
            "detail": detail,
            "session_id": None,
        }
    )
    summaries.emit_activity("system", f"System mode: {new_mode}", reason, None)


def connect_ok() -> None:
    _set_mode("ONLINE", "The AI service is reachable.", "online", None)


def connect_failed(reason: str) -> None:
    _set_mode("OFFLINE", reason, "offline", reason)
