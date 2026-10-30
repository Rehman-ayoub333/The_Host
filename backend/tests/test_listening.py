"""Phase 7o, 16 section 2zk item 3: the operator holds the microphone.

After the 30 Oct faculty demo Rehman stopped trusting a level threshold to tell
a guest from a hall: a fixed number depends on the device and on Windows gain,
and LOW sensitivity misses a soft start. So listening became a decision he makes
-- Start listening when the guest steps up, Stop listening when they are done --
and the backend's share of that is this: relay the toggle and the mode to the
TV, which is the only side that holds a microphone, and pick the start-of-speech
sensitivity from the mode.

Nothing here carries conversation text or a token.
"""

import json

import pytest
from fastapi.testclient import TestClient
from google.genai import types

import config
import event_bus
import live_session
import main


TOKEN = "operator-token-for-tests"
AUTH = {"X-Operator-Token": TOKEN}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(main, "ACTIVE", None)
    # 16 section 2zj item 7: the lifespan starts the feedback importer, and a
    # live one would reach the network during the test.
    monkeypatch.setattr(config, "NETLIFY_TOKEN", "")
    # Every test starts from the documented default, whatever ran before it.
    monkeypatch.setattr(main, "LISTENING", {"on": False, "mode": "operator"})
    with TestClient(main.app) as client:
        yield client


def published(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


# ------------------------------------------------- item 3: the default state


def test_listening_starts_off_in_operator_mode():
    """A microphone that is open before anybody asked is the whole problem."""
    print("the shipped default:", main.LISTENING)
    assert main.LISTENING == {"on": False, "mode": "operator"}


def test_the_snapshot_carries_both_so_a_reload_recovers_them(served):
    """2zk item 3: "kept across reloads"."""
    served.post("/api/listening", json={"on": True, "mode": "automatic"}, headers=AUTH)

    snapshot = main.build_state_snapshot()
    print("snapshot listening:", snapshot["listening"], snapshot["listening_mode"])
    assert snapshot["listening"] is True
    assert snapshot["listening_mode"] == "automatic"


# ------------------------------------------- item 3(a): the Start/Stop toggle


def test_the_toggle_publishes_listening(served):
    event_bus.PUBLISHED.clear()

    on = served.post("/api/listening", json={"on": True}, headers=AUTH)
    print("POST /api/listening {on: true}:", json.dumps(on.json()))
    assert on.status_code == 200
    assert on.json() == {"on": True, "mode": "operator"}
    assert [event["on"] for event in published("listening")] == [True]

    off = served.post("/api/listening", json={"on": False}, headers=AUTH)
    print("POST /api/listening {on: false}:", json.dumps(off.json()))
    assert off.json() == {"on": False, "mode": "operator"}
    assert [event["on"] for event in published("listening")] == [True, False]


def test_the_mode_publishes_listening_mode(served):
    event_bus.PUBLISHED.clear()

    response = served.post("/api/listening", json={"mode": "automatic"}, headers=AUTH)
    print("POST /api/listening {mode: automatic}:", json.dumps(response.json()))
    assert response.json() == {"on": False, "mode": "automatic"}
    assert [event["mode"] for event in published("listening_mode")] == ["automatic"]

    # The same mode again says nothing: the TV is already in it.
    served.post("/api/listening", json={"mode": "automatic"}, headers=AUTH)
    assert [event["mode"] for event in published("listening_mode")] == ["automatic"]


def test_both_halves_may_arrive_together(served):
    event_bus.PUBLISHED.clear()

    response = served.post(
        "/api/listening", json={"on": True, "mode": "automatic"}, headers=AUTH
    )
    print("published:", [event["type"] for event in event_bus.PUBLISHED])
    assert response.json() == {"on": True, "mode": "automatic"}
    assert len(published("listening")) == 1
    assert len(published("listening_mode")) == 1


def test_the_endpoint_needs_the_operator_token(served):
    response = served.post("/api/listening", json={"on": True})
    print("without a token:", response.status_code)
    assert response.status_code == 401
    assert main.LISTENING["on"] is False
    assert published("listening") == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"on": "yes"},
        {"on": None, "mode": None},
        {"mode": "push-to-talk"},
        {"mode": "Operator"},
        {"on": 1},
    ],
)
def test_a_bad_body_is_refused_and_changes_nothing(served, body):
    event_bus.PUBLISHED.clear()
    response = served.post("/api/listening", json=body, headers=AUTH)
    print(f"{body} -> {response.status_code}")
    assert response.status_code == 400
    assert main.LISTENING == {"on": False, "mode": "operator"}
    assert list(event_bus.PUBLISHED) == []


def test_a_conversation_ending_turns_listening_off(served, caplog):
    """2zk item 3(a): however it ended. The next guest starts from silence."""
    import logging

    served.post("/api/listening", json={"on": True}, headers=AUTH)
    assert main.LISTENING["on"] is True
    event_bus.PUBLISHED.clear()

    with caplog.at_level(logging.INFO, logger="main"):
        main.listening_off("session ended")

    print("after the conversation:", main.LISTENING)
    print("log:", [record.getMessage() for record in caplog.records])
    assert main.LISTENING["on"] is False
    assert [event["on"] for event in published("listening")] == [False]
    assert "listening off reason=session ended" in [
        record.getMessage() for record in caplog.records
    ]


def test_turning_it_off_when_it_is_already_off_says_nothing(served):
    event_bus.PUBLISHED.clear()
    main.listening_off("session ended")
    print("published:", list(event_bus.PUBLISHED))
    assert list(event_bus.PUBLISHED) == []


# --------------------------------------------- item 3: the TV is told, and the
# dashboard too -- it draws the badge


@pytest.mark.parametrize("event_type", ["listening", "listening_mode"])
def test_both_events_reach_the_public_display(event_type):
    """The page holds the microphone, so the smd role must receive these."""
    assert event_type in event_bus.SMD_ALLOWED
    assert event_type not in event_bus.SMD_NEVER
    event = event_bus.stamp({"type": event_type, "on": True, "mode": "operator"})
    assert event_bus.filter_for("smd", event) is not None
    # And the dashboard, which shows the LISTENING badge.
    assert event_bus.filter_for("dashboard", event) is not None


# ------------------------------- item 3(c): the sensitivity follows the mode


def test_operator_mode_asks_for_high_sensitivity():
    """The operator has decided a guest is speaking, so a soft "yes" is heard."""
    from datetime import datetime

    built = live_session.build_live_config(datetime.now(), listen="operator")
    found = built.realtime_input_config.automatic_activity_detection
    print("listen=operator ->", found.start_of_speech_sensitivity)
    assert found.start_of_speech_sensitivity == (
        types.StartSensitivity.START_SENSITIVITY_HIGH
    )
    # 2zk item 3(c): and nothing else about the detection moves.
    assert found.prefix_padding_ms == 300
    assert found.silence_duration_ms == 500


@pytest.mark.parametrize("listen", ["auto", "nonsense", ""])
def test_every_other_mode_takes_the_conservative_path(listen):
    """LOW is right until an operator says otherwise, including for a page old
    enough not to send the parameter at all."""
    from datetime import datetime

    built = live_session.build_live_config(datetime.now(), listen=listen)
    found = built.realtime_input_config.automatic_activity_detection
    print(f"listen={listen!r} ->", found.start_of_speech_sensitivity)
    assert found.start_of_speech_sensitivity == (
        types.StartSensitivity.START_SENSITIVITY_LOW
    )


def test_the_default_argument_is_the_conservative_one():
    from datetime import datetime

    found = live_session.build_live_config(
        datetime.now()
    ).realtime_input_config.automatic_activity_detection
    assert found.start_of_speech_sensitivity == (
        types.StartSensitivity.START_SENSITIVITY_LOW
    )


@pytest.mark.parametrize(
    "asked,kept", [("operator", "operator"), ("auto", "auto"), ("rubbish", "auto")]
)
def test_the_session_keeps_its_mode_for_a_rebuilt_connection(asked, kept):
    """2zk item 3(c): a reconnect mid-conversation must not change what the
    guest standing there has been getting."""
    import doubles

    session = doubles.new_session()[0]
    session.listen = asked if asked in live_session.LISTEN_MODES else "auto"
    rebuilt = live_session.LiveSession(session.ws, "button", asked)
    print(f"asked {asked!r} -> kept {rebuilt.listen!r}")
    assert rebuilt.listen == kept
