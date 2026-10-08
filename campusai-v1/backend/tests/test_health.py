import json
import sqlite3

import config
import data
import event_bus
import health


def published(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


def activity_rows():
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            json.loads(row["detail"])
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'agent_activity' ORDER BY id"
            ).fetchall()
        ]


def test_the_mode_starts_online():
    assert health.mode() == "ONLINE"


def test_a_failed_connect_goes_offline_and_announces_it():
    health.connect_failed("I couldn't reach my brain in time. Please try again.")

    assert health.mode() == "OFFLINE"

    mode_event = published("operational_mode_changed")[0]
    status_event = published("system_status_changed")[0]
    print("operational_mode_changed:", mode_event)
    print("system_status_changed:", status_event)
    print("activity rows:", activity_rows())

    assert mode_event["mode"] == "OFFLINE"
    assert mode_event["reason"] == "I couldn't reach my brain in time. Please try again."
    assert mode_event["session_id"] is None
    assert status_event["component"] == "ai_agent"
    assert status_event["status"] == "offline"
    assert status_event["detail"] == "I couldn't reach my brain in time. Please try again."

    activity = published("agent_activity")[0]
    assert activity["kind"] == "system"
    assert activity["label"] == "System mode: OFFLINE"
    assert activity["detail"] == "I couldn't reach my brain in time. Please try again."
    assert activity_rows()[-1]["label"] == "System mode: OFFLINE"


def test_the_next_successful_connect_returns_online():
    health.connect_failed("Something went wrong. Please try again.")
    event_bus.PUBLISHED.clear()

    health.connect_ok()

    assert health.mode() == "ONLINE"
    mode_event = published("operational_mode_changed")[0]
    status_event = published("system_status_changed")[0]
    print("operational_mode_changed:", mode_event)
    print("system_status_changed:", status_event)

    assert mode_event["mode"] == "ONLINE"
    assert status_event["status"] == "online"
    assert status_event["detail"] is None
    assert published("agent_activity")[0]["label"] == "System mode: ONLINE"


def test_no_event_when_the_mode_does_not_actually_change():
    health.connect_ok()
    assert list(event_bus.PUBLISHED) == []

    health.connect_failed("Something went wrong. Please try again.")
    first = len(event_bus.PUBLISHED)
    health.connect_failed("Something went wrong. Please try again.")
    assert len(event_bus.PUBLISHED) == first
