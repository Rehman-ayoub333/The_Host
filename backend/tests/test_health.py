import json
import sqlite3

import pytest

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


# ------------------------------------- Phase 5: the override (16 2e items 4, 6)


def connect_failed_rows():
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT event_type, actor, detail FROM system_events "
                "WHERE event_type = 'connect_failed' ORDER BY id"
            ).fetchall()
        ]


def test_every_connect_failure_writes_its_own_system_event():
    health.connect_failed("Something went wrong. Please try again.")
    health.connect_failed("Something went wrong. Please try again.")

    rows = connect_failed_rows()
    print("connect_failed rows:", rows)
    assert len(rows) == 2
    assert rows[0]["actor"] == "system"
    assert json.loads(rows[0]["detail"]) == {
        "reason": "Something went wrong. Please try again."
    }
    # The second one changed no mode, so it published nothing new.
    assert len(published("operational_mode_changed")) == 1


def test_pausing_overrides_the_computed_mode_and_resuming_returns_it():
    assert health.set_override("PAUSED") == "PAUSED"
    assert health.mode() == "PAUSED"

    mode_event = published("operational_mode_changed")[0]
    print("operational_mode_changed:", mode_event)
    print("activity rows:", activity_rows())
    assert mode_event["mode"] == "PAUSED"
    assert mode_event["reason"] == "An operator paused THE HOST."
    assert mode_event["session_id"] is None
    assert published("agent_activity")[0]["label"] == "System mode: PAUSED"
    assert published("agent_activity")[0]["kind"] == "system"
    # Pausing says nothing about the AI service itself.
    assert published("system_status_changed") == []
    assert health.ai_agent_status() == "online"

    event_bus.PUBLISHED.clear()
    assert health.set_override(None) == "ONLINE"
    assert health.mode() == "ONLINE"
    print("after resume:", published("operational_mode_changed")[0])
    assert published("operational_mode_changed")[0]["mode"] == "ONLINE"
    assert published("operational_mode_changed")[0]["reason"] == (
        "An operator resumed THE HOST."
    )
    assert published("agent_activity")[0]["label"] == "System mode: ONLINE"


def test_a_takeover_has_its_own_reasons():
    health.set_override("OPERATOR_TAKEOVER")
    assert health.mode() == "OPERATOR_TAKEOVER"
    assert published("operational_mode_changed")[0]["reason"] == "An operator took over."

    event_bus.PUBLISHED.clear()
    health.set_override(None)
    print("after the takeover ended:", published("operational_mode_changed")[0])
    assert published("operational_mode_changed")[0]["reason"] == (
        "An operator ended the takeover."
    )


def test_setting_the_same_override_twice_publishes_nothing():
    health.set_override("PAUSED")
    event_bus.PUBLISHED.clear()
    assert health.set_override("PAUSED") == "PAUSED"
    assert list(event_bus.PUBLISHED) == []
    # Clearing an override that is not set is also a no-op.
    health.set_override(None)
    event_bus.PUBLISHED.clear()
    assert health.set_override(None) == "ONLINE"
    assert list(event_bus.PUBLISHED) == []


def test_the_override_hides_a_connect_failure_from_the_reported_mode():
    health.set_override("PAUSED")
    event_bus.PUBLISHED.clear()

    health.connect_failed("Something went wrong. Please try again.")

    print("mode while paused:", health.mode())
    print("published:", [event["type"] for event in event_bus.PUBLISHED])
    assert health.mode() == "PAUSED"
    # No mode event: the reported mode did not change. The component status did.
    assert published("operational_mode_changed") == []
    assert published("agent_activity") == []
    assert published("system_status_changed")[0]["status"] == "offline"
    assert health.ai_agent_status() == "offline"

    event_bus.PUBLISHED.clear()
    assert health.set_override(None) == "OFFLINE"
    print("after resume:", published("operational_mode_changed")[0])
    assert published("operational_mode_changed")[0]["mode"] == "OFFLINE"


def test_an_unknown_override_is_refused():
    with pytest.raises(ValueError):
        health.set_override("SLEEPING")
    assert health.mode() == "ONLINE"
