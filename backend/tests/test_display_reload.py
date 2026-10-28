"""Phase 7l: the operator's Reload display screen (16 section 2zf item 8(c)).

The TV is across the stall on a kiosk browser with no keyboard, so when it
looks wrong there is no F5 to press. This endpoint publishes one event to the
`smd` role and to nothing else: the dashboard reloading itself because the TV
was asked to would be the opposite of a recovery control.
"""

import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import event_bus
import main


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


def test_the_endpoint_publishes_one_display_reload(served):
    event_bus.PUBLISHED.clear()

    response = served.post("/api/display/reload", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"sent": True}
    reloads = [e for e in event_bus.PUBLISHED if e["type"] == "display_reload"]
    print("published:", reloads)
    assert len(reloads) == 1
    assert reloads[0]["session_id"] is None
    assert isinstance(reloads[0]["event_id"], int)
    assert reloads[0]["timestamp"]


def test_the_endpoint_needs_the_token(served):
    event_bus.PUBLISHED.clear()

    assert served.post("/api/display/reload").status_code == 401
    assert served.post(
        "/api/display/reload", headers={"X-Operator-Token": "wrong"}
    ).status_code == 401
    assert [e for e in event_bus.PUBLISHED if e["type"] == "display_reload"] == []


def test_only_the_display_is_ever_sent_it():
    """16 §2zf item 8(c): the `smd` role only."""
    event = {"type": "display_reload", "session_id": None, "event_id": 1, "timestamp": "t"}

    assert event_bus.filter_for("smd", event) == event
    assert event_bus.filter_for("dashboard", event) is None


def test_every_other_event_still_reaches_the_dashboard():
    """The new filter must not have closed the door on anything else."""
    for kind in ("order_updated", "agent_activity", "speech_transcript", "heartbeat"):
        event = {"type": kind, "session_id": None}
        assert event_bus.filter_for("dashboard", event) == event, kind


def test_it_writes_an_operator_row_and_an_audit_row(served):
    event_bus.PUBLISHED.clear()

    served.post("/api/display/reload", headers=AUTH)

    rows = [
        (e["kind"], e["label"])
        for e in event_bus.PUBLISHED
        if e["type"] == "agent_activity"
    ]
    print("activity:", rows)
    assert ("operator", "Operator: reloaded the display screen") in rows

    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        audit = [
            json.loads(row["detail"])
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'operator_action' "
                "ORDER BY id"
            )
        ]
    assert audit[-1] == {"action": "display_reload"}
