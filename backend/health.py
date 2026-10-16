"""Operational mode (07 section 3, 10 section 4).

Holds the computed mode, flipped by a Gemini connect success or failure, and the
operator override on top of it. PAUSED and OPERATOR_TAKEOVER always win over
the computed mode (07 section 3); DEGRADED is not derived by this build, so the
computed mode is only ever ONLINE, RECOVERING or OFFLINE.

RECOVERING (16 section 2j item 4) lasts only as long as an automatic reconnect
attempt: 07 section 3 gives it exactly two exits, ONLINE when the attempt
succeeds and OFFLINE when the attempts are exhausted.
"""

import logging

import data
import event_bus
import summaries


log = logging.getLogger(__name__)

OVERRIDES = ("PAUSED", "OPERATOR_TAKEOVER")

# 16 section 2e item 4: the reason that travels with an override change.
SET_REASONS = {
    "PAUSED": "An operator paused THE HOST.",
    "OPERATOR_TAKEOVER": "An operator took over.",
}
CLEAR_REASONS = {
    "PAUSED": "An operator resumed THE HOST.",
    "OPERATOR_TAKEOVER": "An operator ended the takeover.",
}

_mode = "ONLINE"
_override = None


def mode() -> str:
    """The reported mode: an operator override wins over the computed one."""
    return _override or _mode


def ai_agent_status() -> str:
    """The `ai_agent` component status, as `system_status_changed` reports it.

    It follows the computed mode, never the override: pausing THE HOST does not
    make the AI service unreachable (12 section 3 requires /health and the event
    stream to agree). A reconnect in progress (RECOVERING) is not reported as
    offline either -- the service has not been given up on.
    """
    return "offline" if _mode == "OFFLINE" else "online"


def _announce_mode(before: str, reason: str) -> None:
    after = mode()
    if after == before:
        return
    log.info("operational_mode %s (%s)", after, reason)
    event_bus.publish_threadsafe(
        {
            "type": "operational_mode_changed",
            "mode": after,
            "reason": reason,
            "session_id": None,
        }
    )


def _set_mode(new_mode: str, reason: str, component_status: str, detail) -> None:
    global _mode
    if new_mode == _mode:
        return
    before = mode()
    _mode = new_mode
    _announce_mode(before, reason)
    event_bus.publish_threadsafe(
        {
            "type": "system_status_changed",
            "component": "ai_agent",
            "status": component_status,
            "detail": detail,
            "session_id": None,
        }
    )
    if mode() != before:
        summaries.emit_activity("system", f"System mode: {mode()}", reason, None)


def set_override(value) -> str:
    """16 section 2e item 4. `None` clears it and the computed mode returns."""
    global _override
    if value is not None and value not in OVERRIDES:
        raise ValueError(f"{value!r} is not an operator override.")
    if value == _override:
        return mode()
    before = mode()
    previous = _override
    _override = value
    reason = SET_REASONS[value] if value is not None else CLEAR_REASONS[previous]
    _announce_mode(before, reason)
    if mode() != before:
        summaries.emit_activity("system", f"System mode: {mode()}", reason, None)
    return mode()


def connect_ok() -> None:
    _set_mode("ONLINE", "The AI service is reachable.", "online", None)


def recovering() -> None:
    """16 section 2j item 4: a drop was detected and a reconnect is under way.

    The component status stays `online`: nothing has been given up on yet, and
    one of `connect_ok` or `connect_failed` always follows within seconds.
    """
    _set_mode(
        "RECOVERING",
        "The connection to the AI service dropped; reconnecting.",
        "online",
        None,
    )


def connect_failed(reason: str) -> None:
    # 16 section 2e item 6: every failure is counted, including one that does not
    # change the mode because the mode was already OFFLINE or overridden.
    data.log_system_event("connect_failed", "system", {"reason": reason})
    _set_mode("OFFLINE", reason, "offline", reason)
