"""Event bus — Phase 1 stand-in.

Holds the three final signatures (``stamp``, ``publish``, ``publish_threadsafe``)
so the tool layer can be written and tested against them now. Phase 3 adds the
sockets, role filtering, heartbeat and snapshot behind these same signatures.

The bus stamps ``event_id`` and ``timestamp`` only. It never sets or touches
``session_id``: the caller owns that (``tools._pub``, ``live_session``, or an
explicit ``None`` for operator- and expiry-originated events).
"""

import itertools
from datetime import datetime


PUBLISHED: list[dict] = []

_event_ids = itertools.count(1)


def stamp(event: dict) -> dict:
    event["event_id"] = next(_event_ids)
    event["timestamp"] = datetime.now().isoformat(timespec="seconds")
    return event


def publish(event: dict) -> None:
    # Stamp only when the event has no id yet (03 section 2), so an event already
    # stamped by live_session._send_control keeps the same event_id on both paths.
    if "event_id" not in event:
        stamp(event)
    PUBLISHED.append(event)


def publish_threadsafe(event: dict) -> None:
    publish(event)
