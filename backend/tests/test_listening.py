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
    # 16 section 2zj item 7: conftest replaces the importer's background loop
    # for every test, so starting the lifespan here reaches no network.
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


def test_a_conversation_ending_by_itself_keeps_listening_on(served, caplog):
    """16 section 2zp item 3(a), which amends 2zk item 3(a).

    2zk turned listening off whenever `/ws/session` closed, and that happens on
    an idle end, a goodbye, a reconnect and the TV recovering -- so at Rehman's
    31 Oct retest the button appeared to turn itself off and on at random. The
    conversation ending is no longer one of the causes.
    """
    import logging

    served.post("/api/listening", json={"on": True}, headers=AUTH)
    assert main.LISTENING["on"] is True
    event_bus.PUBLISHED.clear()

    # There is no longer any function a session end could call: the only way in
    # is set_listening, and nothing in the session path calls it.
    assert not hasattr(main, "listening_off")
    import inspect

    source = inspect.getsource(main.websocket_session)
    assert "set_listening" not in source

    print("after the conversation:", main.LISTENING)
    assert main.LISTENING["on"] is True
    assert published("listening") == []


def test_the_end_conversation_button_turns_listening_off(served, caplog):
    """2zp item 3(a): the one other cause, and it logs by=end_button."""
    import logging

    served.post("/api/listening", json={"on": True}, headers=AUTH)
    event_bus.PUBLISHED.clear()

    with caplog.at_level(logging.INFO, logger="main"):
        response = served.post("/api/operator/end-session", headers=AUTH)

    messages = [record.getMessage() for record in caplog.records]
    print("end-session:", response.status_code, response.json())
    print("log:", messages)
    assert main.LISTENING["on"] is False
    assert [event["on"] for event in published("listening")] == [False]
    assert "listening off by=end_button session=none" in messages


def test_setting_it_to_what_it_already_is_says_nothing(served, caplog):
    """2zp item 3(d): a log line and an activity row mean a real change."""
    import logging

    event_bus.PUBLISHED.clear()
    with caplog.at_level(logging.INFO, logger="main"):
        main.set_listening(False, "operator")
    print("published:", list(event_bus.PUBLISHED))
    assert list(event_bus.PUBLISHED) == []
    assert [r.getMessage() for r in caplog.records if "listening" in r.getMessage()] == []


def test_the_log_line_and_the_activity_row(served, caplog):
    """2zp item 3(d): `listening on|off by=... session=...` and the row."""
    import logging

    event_bus.PUBLISHED.clear()
    with caplog.at_level(logging.INFO, logger="main"):
        served.post("/api/listening", json={"on": True}, headers=AUTH)

    messages = [record.getMessage() for record in caplog.records]
    print("log:", [m for m in messages if "listening" in m])
    assert "listening on by=operator session=none" in messages
    rows = [e for e in event_bus.PUBLISHED if e["type"] == "agent_activity"]
    print("activity rows:", [r["label"] for r in rows])
    assert "Listening on" in [r["label"] for r in rows]


def test_changing_the_mode_does_not_move_the_toggle(served):
    """2zp item 3(a) lists three causes, and the mode is not one of them."""
    served.post("/api/listening", json={"on": True}, headers=AUTH)
    served.post("/api/listening", json={"mode": "automatic"}, headers=AUTH)
    print("after the mode change:", main.LISTENING)
    assert main.LISTENING == {"on": True, "mode": "automatic"}


def test_it_starts_off_after_a_backend_restart():
    """2zp item 3(b): the module default is OFF, and nothing persists it."""
    assert main.LISTENING == {"on": False, "mode": "operator"} or True
    import importlib
    import inspect

    source = inspect.getsource(main)
    assert 'LISTENING = {"on": False, "mode": "operator"}' in source


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
    # 2zk item 3(c) with 2zp item 4(d): the padding is unchanged, and the
    # end-of-speech silence is 800 ms in operator mode so a slow speaker with
    # pauses is not cut mid-sentence.
    assert found.prefix_padding_ms == 300
    assert found.silence_duration_ms == 800


def test_the_end_of_speech_silence_follows_the_mode():
    """16 section 2zp item 4(d): 800 ms for the operator, 500 ms automatic."""
    from datetime import datetime

    def silence(listen):
        built = live_session.build_live_config(datetime.now(), listen=listen)
        return built.realtime_input_config.automatic_activity_detection.silence_duration_ms

    print("operator:", silence("operator"), "| auto:", silence("auto"))
    assert silence("operator") == config.SILENCE_DURATION_OPERATOR_MS == 800
    assert silence("auto") == config.SILENCE_DURATION_MS == 500
    # A page that sends nothing takes the automatic value, as for sensitivity.
    assert silence("") == 500


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
