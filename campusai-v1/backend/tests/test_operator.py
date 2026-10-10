"""Phase 3b: the operator write endpoints, the order-ready announcement and the
token redaction filter (16 section 2b item 12 and section 2c)."""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import data
import doubles
import event_bus
import main
import prompts
import tools


TOKEN = "operator-token-for-tests"
AUTH = {"X-Operator-Token": TOKEN}
BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}
LEMONADE = {"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}


class CountingSession:
    """Stands in for an active LiveSession and counts announcements."""

    def __init__(self):
        self.announced = []

    async def announce(self, order):
        self.announced.append(order["id"])


class FailingSession:
    async def announce(self, order):
        raise RuntimeError("the live session is gone")


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(main, "ACTIVE", None)
    with TestClient(main.app) as client:
        yield client


@pytest.fixture(autouse=True)
def no_grace(monkeypatch):
    """16 section 2f item 5 makes an immediate announcement wait
    `ANNOUNCE_GRACE_S` and look again. These tests are about what is sent and
    what it is labelled, not about the wait, so the grace is zero here. The
    grace itself is tested in `test_voice_activity.py`.
    """
    monkeypatch.setattr(config, "ANNOUNCE_GRACE_S", 0)


def confirmed(guest_name="Ahmed", items=(BURGER,)):
    order_id = data.create_order_draft(list(items), guest_name, "s-1")["order_id"]
    data.update_order_status(order_id, "CONFIRMED")
    event_bus.PUBLISHED.clear()
    return order_id


def advance(client, order_id, status, **body):
    event_bus.PUBLISHED.clear()
    response = client.post(
        f"/api/orders/{order_id}/status", json={"status": status, **body}, headers=AUTH
    )
    print(f"POST /api/orders/{order_id}/status {{'status': '{status}'}} -> {response.status_code}")
    print("   ", json.dumps(response.json(), indent=2) if response.text else "")
    print("    published:", [event["type"] for event in event_bus.PUBLISHED])
    return response


def order_row(order_id):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(
            conn.execute(
                "SELECT id, status, announced, estimated_ready_at, ready_at, cancel_reason "
                "FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        )


def system_events(event_type):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT event_type, actor, detail FROM system_events "
                "WHERE event_type = ? ORDER BY id",
                (event_type,),
            ).fetchall()
        ]


def of_type(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


# ------------------------------------------------------------------------- (a)


def test_each_forward_transition_through_the_status_endpoint(served):
    order_id = confirmed()

    preparing = advance(served, order_id, "PREPARING")
    assert preparing.status_code == 200
    assert preparing.json()["order"]["status"] == "PREPARING"
    # Chicken Burger has prep_seconds 300, so an estimate really exists.
    assert preparing.json()["order"]["estimated_ready_at"] is not None
    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_updated",
        "agent_activity",
    ]
    assert of_type("agent_activity")[0]["label"] == f"Order #{order_id} updated"
    assert of_type("agent_activity")[0]["detail"] == "preparing"

    ready = advance(served, order_id, "READY")
    assert ready.status_code == 200
    assert ready.json()["order"]["status"] == "READY"
    assert ready.json()["order"]["ready_at"] is not None
    # order_ready follows its order_updated immediately (04 section 5 step 2).
    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_updated",
        "order_ready",
        "agent_activity",
    ]
    assert of_type("agent_activity")[0]["label"] == f"Order #{order_id} ready"
    assert of_type("agent_activity")[0]["detail"] == "ready"

    collected = advance(served, order_id, "COLLECTED")
    assert collected.status_code == 200
    assert collected.json()["order"]["status"] == "COLLECTED"
    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_updated",
        "agent_activity",
    ]

    actions = system_events("operator_action")
    print("operator_action rows:", actions)
    assert [json.loads(row["detail"])["status"] for row in actions] == [
        "PREPARING",
        "READY",
        "COLLECTED",
    ]
    assert all(row["actor"] == "operator" for row in actions)
    assert json.loads(actions[0]["detail"]) == {
        "action": "order_status",
        "order_id": order_id,
        "status": "PREPARING",
    }


def test_an_illegal_transition_is_refused_and_changes_nothing(served):
    order_id = confirmed()

    response = advance(served, order_id, "READY")
    assert response.status_code == 400
    assert response.json() == {
        "detail": "Order is CONFIRMED; mark it PREPARING before READY."
    }
    print("row after the refusal:", order_row(order_id))
    assert order_row(order_id)["status"] == "CONFIRMED"
    assert order_row(order_id)["ready_at"] is None
    assert order_row(order_id)["announced"] == 0
    assert list(event_bus.PUBLISHED) == []


def test_the_status_endpoint_rejects_an_unknown_id_a_missing_token_and_a_bad_body(served):
    order_id = confirmed()

    unknown = served.post("/api/orders/9999/status", json={"status": "PREPARING"}, headers=AUTH)
    print("unknown id ->", unknown.status_code, unknown.json())
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "There is no order with that number."}

    no_token = served.post(f"/api/orders/{order_id}/status", json={"status": "PREPARING"})
    print("no token ->", no_token.status_code, no_token.json())
    assert no_token.status_code == 401
    assert no_token.json() == {"detail": "Operator token required."}

    wrong_token = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "PREPARING"},
        headers={"X-Operator-Token": "nope"},
    )
    assert wrong_token.status_code == 401

    for body in ({}, {"status": "FLYING"}, {"status": 7}, {"reason": "x"}, [1, 2]):
        bad = served.post(f"/api/orders/{order_id}/status", json=body, headers=AUTH)
        print(f"bad body {body!r} ->", bad.status_code, bad.json())
        assert bad.status_code == 400
        assert bad.json() == {"detail": "Invalid status update."}

    invalid_json = served.post(
        f"/api/orders/{order_id}/status",
        content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    print("invalid JSON ->", invalid_json.status_code, invalid_json.json())
    assert invalid_json.status_code == 400

    assert order_row(order_id)["status"] == "CONFIRMED"


def test_cancelled_and_flagged_statuses_go_through_the_same_endpoint(served):
    cancelled = confirmed()
    response = advance(served, cancelled, "CANCELLED", reason="the stall ran out")
    assert response.status_code == 200
    assert order_row(cancelled)["cancel_reason"] == "the stall ran out"

    flagged = confirmed()
    assert advance(served, flagged, "REQUIRES_ATTENTION").status_code == 200
    assert order_row(flagged)["status"] == "REQUIRES_ATTENTION"


# ------------------------------------------------------------------------- (b)


def test_ready_twice_announces_exactly_once(served, monkeypatch):
    session = CountingSession()
    monkeypatch.setattr(main, "ACTIVE", session)
    order_id = confirmed()
    advance(served, order_id, "PREPARING")

    first = advance(served, order_id, "READY")
    assert first.status_code == 200
    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_updated",
        "order_ready",
        "agent_activity",
    ]
    print("first READY order_ready:", of_type("order_ready"))
    assert order_row(order_id)["announced"] == 1
    assert session.announced == [order_id]

    assert advance(served, order_id, "REQUIRES_ATTENTION").status_code == 200

    second = advance(served, order_id, "READY")
    assert second.status_code == 200
    print("second READY published:", list(event_bus.PUBLISHED))
    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_updated",
        "agent_activity",
    ]
    assert of_type("order_ready") == []
    print("announce call count:", len(session.announced))
    assert session.announced == [order_id]


# ------------------------------------------------------------------------- (c)


def test_ready_with_an_active_session_speaks_the_announcement(served, monkeypatch):
    session, ws = doubles.new_session()
    monkeypatch.setattr(main, "ACTIVE", session)
    order_id = confirmed(guest_name="Ahmed")
    advance(served, order_id, "PREPARING")

    assert advance(served, order_id, "READY").status_code == 200

    sent = session.session.inputs[-1]
    print("sent to Gemini:", json.dumps(sent, indent=2))
    assert sent == {
        "text": (
            f"An order just became ready: order #{order_id} for Ahmed. "
            "Let the guests know, briefly and naturally, even if it is not their order."
        )
    }
    assert sent["text"] == prompts.ANNOUNCE_TEMPLATE.format(order_id=order_id, name="Ahmed")
    assert session.announcing is True


def test_an_order_with_no_name_announces_a_guest(served, monkeypatch):
    session, ws = doubles.new_session()
    monkeypatch.setattr(main, "ACTIVE", session)
    order_id = confirmed(guest_name=None)
    advance(served, order_id, "PREPARING")
    advance(served, order_id, "READY")

    print("sent to Gemini:", session.session.inputs[-1])
    assert session.session.inputs[-1]["text"].endswith(
        "Let the guests know, briefly and naturally, even if it is not their order."
    )
    assert f"order #{order_id} for a guest." in session.session.inputs[-1]["text"]
    assert of_type("order_ready")[0]["customer_name"] is None


def test_the_announcing_turn_is_announcing_and_returns_to_resting_state():
    """07 section 2 rules 2 and 3, with and without a pending draft."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True
    order = {"id": 27, "guest_name": "Ahmed"}

    asyncio.run(session.announce(order))
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00\x01"))))
    print("states after announcing:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"

    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("states after turn_complete:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "LISTENING"
    assert session.announcing is False

    # Rule 2: ANNOUNCING is one of the four states that may interrupt TAKING_ORDER.
    session.ctx["pending_order_id"] = 27
    asyncio.run(session._send_state("TAKING_ORDER"))
    asyncio.run(session.announce(order))
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00\x01"))))
    print("states with a draft pending:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_an_interruption_before_the_announcing_turn_does_not_cancel_it():
    """The 9 Oct booth sequence: the announcement arrives while the greeting is
    still playing, Gemini interrupts itself, and the announcing turn follows.

    Phase 4 (16 section 2d item 3) keeps the announcement out of a speaking turn
    in the first place, so it now leaves through the interruption's own end of
    turn. The guard this test exists for -- `announcing` surviving an interruption
    nobody asked for -- still has to hold.
    """
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))

    # The greeting is already speaking.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert doubles.states(ws)[-1] == "GREETING"

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    # Gemini interrupts its own greeting because of the injected text.
    asyncio.run(session._handle_message(doubles.message(doubles.content(interrupted=True))))
    print("states after the interruption:", doubles.states(ws))
    print("announcing still set:", session.announcing)
    assert session.announcing is True

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states after the announcement audio:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"

    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    assert doubles.states(ws)[-1] == "LISTENING"
    assert session.announcing is False
    assert session.announcing_turn is False
    doubles.validate(ws)


def test_an_interrupted_announcement_does_not_label_the_next_turn():
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session.announce({"id": 27, "guest_name": None}))
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert doubles.states(ws)[-1] == "ANNOUNCING"

    # The guest talks over the announcement itself.
    asyncio.run(session._handle_message(doubles.message(doubles.content(interrupted=True))))
    assert session.announcing is False

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states after an interrupted announcement:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "SPEAKING"


def test_an_ordinary_turn_is_not_announcing():
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00\x01"))))
    print("states without an announcement:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "SPEAKING"


# ------------------------------- Phase 4: the gentler announcement (2d item 3)


ANNOUNCEMENT_27 = (
    "An order just became ready: order #27 for Ahmed. "
    "Let the guests know, briefly and naturally, even if it is not their order."
)
ANNOUNCEMENT_28 = (
    "An order just became ready: order #28 for a guest. "
    "Let the guests know, briefly and naturally, even if it is not their order."
)


def speaking_session():
    """A session in the middle of a turn that is already producing audio."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert doubles.states(ws)[-1] == "SPEAKING"
    assert session.first_audio_sent is True
    return session, ws


def test_an_announcement_during_audio_waits_for_the_end_of_that_turn():
    session, ws = speaking_session()

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("Gemini inputs while the turn is still speaking:", session.session.inputs)
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert session.session.inputs == []
    assert session.announcing is False
    assert [order["id"] for order in session.pending_announcements] == [27]

    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))

    print("Gemini inputs after turn_complete:", session.session.inputs)
    print("states:", doubles.states(ws))
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.announcing is True
    assert session.pending_announcements == []
    # It leaves only after the resting state of the finished turn is set.
    assert doubles.states(ws) == ["LISTENING", "SPEAKING", "LISTENING"]

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states on the announcing turn:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_two_pending_announcements_go_out_one_per_turn():
    session, ws = speaking_session()

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    asyncio.run(session.announce({"id": 28, "guest_name": None}))
    # The same order again is not queued twice.
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert [order["id"] for order in session.pending_announcements] == [27, 28]

    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("after the first turn end:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert [order["id"] for order in session.pending_announcements] == [28]

    # The announcing turn plays and ends; the second announcement follows it.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))

    print("after the second turn end:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}, {"text": ANNOUNCEMENT_28}]
    assert session.pending_announcements == []
    assert session.announcing is True

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x02"))))
    print("states:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_a_pending_announcement_is_dropped_at_session_end():
    session, ws = speaking_session()
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    assert session.pending_announcements

    asyncio.run(session.stop())

    print("pending after stop:", session.pending_announcements)
    print("Gemini inputs after stop:", session.session.inputs)
    assert session.pending_announcements == []
    assert session.session.inputs == []
    assert doubles.states(ws)[-1] == "IDLE"


def test_an_announcement_with_no_turn_in_flight_still_goes_out_at_once():
    session, _ = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("Gemini inputs:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.pending_announcements == []
    assert session.announcing is True


def test_the_deferral_is_logged_without_the_guest_name(caplog):
    session, _ = speaking_session()
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
        asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))

    messages = [record.getMessage() for record in caplog.records]
    print("log lines:", messages)
    assert f"announce deferred session {session_id} order 27" in messages
    assert f"announce session {session_id} order 27" in messages
    assert "Ahmed" not in "\n".join(messages)


# ---------------------------- Phase 5: the corrected deferral (2e item 1)


def test_the_order_12_sequence_defers_until_the_turn_really_ends(caplog):
    """The Phase 4 check, order #12: a tool response resets first_audio_sent, so
    the turn looked idle and the announcement cut Gemini's own reply off.

    `turn_in_progress` survives the tool response, so nothing reaches Gemini
    before `turn_complete` and the template leaves after it.
    """
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        # The model calls a tool; live_session answers it.
        asyncio.run(
            session._handle_message(
                doubles.message(
                    tool_call=doubles.call("check_item_availability", {"item": "Chicken Burger"})
                )
            )
        )
        print("first_audio_sent after the tool response:", session.first_audio_sent)
        print("turn_in_progress after the tool response:", session.turn_in_progress)
        assert session.first_audio_sent is False
        assert session.turn_in_progress is True

        # The operator marks an order READY in exactly that gap.
        asyncio.run(session.announce({"id": 12, "guest_name": "Ahmed"}))
        print("Gemini inputs in the gap:", session.session.inputs)
        assert session.session.inputs == []
        assert session.announcing is False
        assert [order["id"] for order in session.pending_announcements] == [12]

        # The model's own reply plays out and the turn ends.
        asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
        print("Gemini inputs while the reply plays:", session.session.inputs)
        assert session.session.inputs == []

        asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))

    print("Gemini inputs after turn_complete:", session.session.inputs)
    assert session.session.inputs == [
        {
            "text": (
                "An order just became ready: order #12 for Ahmed. "
                "Let the guests know, briefly and naturally, even if it is not their order."
            )
        }
    ]
    assert session.turn_in_progress is False
    messages = [record.getMessage() for record in caplog.records]
    for line in messages:
        print("log:", line)
    assert f"announce deferred session {session_id} order 12" in messages
    assert f"announce session {session_id} order 12" in messages
    assert messages.index(f"announce deferred session {session_id} order 12") < messages.index(
        f"announce session {session_id} order 12"
    )
    assert "Ahmed" not in "\n".join(messages)

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_an_announcement_while_the_guest_is_mid_sentence_is_deferred(caplog):
    """2e item 1: a non-empty visitor buffer means the guest is still talking."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session._handle_message(doubles.message(doubles.content(visitor="can I get"))))
    print("visitor buffer:", repr(session.transcripts["visitor"]))
    print("turn_in_progress:", session.turn_in_progress)
    assert session.transcripts["visitor"] == "can I get"
    assert session.turn_in_progress is False

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("Gemini inputs while the guest talks:", session.session.inputs)
    assert session.session.inputs == []
    assert [order["id"] for order in session.pending_announcements] == [27]
    assert any("announce deferred" in record.getMessage() for record in caplog.records)

    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("Gemini inputs after the turn ends:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    doubles.validate(ws)


def test_an_output_transcription_fragment_alone_marks_the_turn_in_progress():
    """Gemini's text can arrive before its audio; that is still a live turn."""
    session, _ = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session._handle_message(doubles.message(doubles.content(agent="Sure,"))))
    print("turn_in_progress after an agent fragment:", session.turn_in_progress)
    assert session.turn_in_progress is True

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    print("Gemini inputs:", session.session.inputs)
    assert session.session.inputs == []
    assert [order["id"] for order in session.pending_announcements] == [27]


def test_turn_in_progress_is_cleared_by_an_interruption_as_well():
    session, _ = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert session.turn_in_progress is True
    asyncio.run(session._handle_message(doubles.message(doubles.content(interrupted=True))))
    print("turn_in_progress after an interruption:", session.turn_in_progress)
    assert session.turn_in_progress is False

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    print("Gemini inputs:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]


# ------------------- Phase 5: the connect window (16 section 2e item 1a)


ANNOUNCEMENT_20 = (
    "An order just became ready: order #20 for a guest. "
    "Let the guests know, briefly and naturally, even if it is not their order."
)


class FailingLiveApiSession(doubles.FakeLiveApiSession):
    """A Gemini session whose socket has gone away mid-call."""

    async def send_realtime_input(self, **kwargs):
        raise RuntimeError("the live socket is gone")


def test_an_announcement_during_the_gemini_connect_is_deferred(caplog):
    """The 10 Oct live check: `main` publishes ACTIVE the moment the socket opens,
    so `self.session` is still None for the whole Gemini connect. The announcement
    used to hit None, be lost, and leave `announcing` true, which mislabelled the
    greeting as ANNOUNCING (16 section 2e item 1a).
    """
    session, ws = doubles.new_session()
    # _start() has not assigned the Live API session yet.
    session.session = None
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        # Nothing may be raised: the operator's call still has to succeed.
        asyncio.run(session.announce({"id": 20, "guest_name": None}))

    messages = [record.getMessage() for record in caplog.records]
    print("log lines:", messages)
    print("pending:", [order["id"] for order in session.pending_announcements])
    print("announcing:", session.announcing)
    assert f"announce deferred session {session_id} order 20" in messages
    assert [order["id"] for order in session.pending_announcements] == [20]
    assert session.announcing is False
    assert session.announcing_turn is False

    # The connect finishes and the session starts for real.
    session.session = doubles.FakeLiveApiSession()
    asyncio.run(session._send_state("LISTENING"))

    # The first audio of the session is the greeting, not the announcement.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    print("state on the first audio:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "GREETING"
    assert session.session.inputs == []

    # The announcement leaves at that turn's end.
    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))
    print("Gemini inputs after the greeting ended:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_20}]
    assert session.announcing is True
    assert session.pending_announcements == []

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_a_failed_send_leaves_the_next_turn_unlabelled():
    """2e item 1a (ii): nothing was said, so nothing may be called ANNOUNCING."""
    session, ws = doubles.new_session()
    session.session = FailingLiveApiSession()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    with pytest.raises(RuntimeError):
        asyncio.run(session.announce({"id": 20, "guest_name": None}))

    print("announcing:", session.announcing, "announcing_turn:", session.announcing_turn)
    assert session.announcing is False
    assert session.announcing_turn is False

    # A later turn is an ordinary one.
    session.session = doubles.FakeLiveApiSession()
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    print("states after the failed announcement:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "SPEAKING"


def test_a_failed_send_does_not_clear_an_announcement_already_in_flight():
    """A send that fails must not cancel the announcing turn that is already live."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True

    # One announcement is spoken and its turn is under way.
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    assert session.announcing_turn is True

    # The operator's repeat fails on a dead socket.
    session.session = FailingLiveApiSession()
    with pytest.raises(RuntimeError):
        asyncio.run(session._announce_now({"id": 28, "guest_name": None}))

    print("announcing:", session.announcing, "announcing_turn:", session.announcing_turn)
    # The flags are cleared because this send said nothing; the turn that is
    # already playing keeps its ANNOUNCING label, which was sent long ago.
    assert session.announcing is False
    assert doubles.states(ws)[-1] == "ANNOUNCING"


def test_the_operator_announce_endpoint_survives_the_connect_window(served, monkeypatch):
    """End to end: the endpoint still returns 200 and order_ready still goes out."""
    order_id = confirmed()
    advance(served, order_id, "PREPARING")
    advance(served, order_id, "READY")

    session, ws = doubles.new_session()
    session.session = None
    monkeypatch.setattr(main, "ACTIVE", session)

    event_bus.PUBLISHED.clear()
    response = served.post(
        "/api/operator/announce", json={"order_id": order_id}, headers=AUTH
    )
    print("POST /api/operator/announce ->", response.status_code)
    print("published:", [event["type"] for event in event_bus.PUBLISHED])
    assert response.status_code == 200
    assert of_type("order_ready")[0]["order_id"] == order_id
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert [order["id"] for order in session.pending_announcements] == [order_id]
    assert session.announcing is False


def test_ready_with_no_session_publishes_order_ready_and_says_nothing(served):
    assert main.ACTIVE is None
    session, ws = doubles.new_session()
    order_id = confirmed()
    advance(served, order_id, "PREPARING")

    assert advance(served, order_id, "READY").status_code == 200
    ready_events = of_type("order_ready")
    print("order_ready with no session:", ready_events)
    assert len(ready_events) == 1
    assert ready_events[0] == {
        **ready_events[0],
        "order_id": order_id,
        "customer_name": "Ahmed",
        "session_id": None,
    }
    print("sent to Gemini:", session.session.inputs)
    assert session.session.inputs == []
    assert ws.sent == []


# ------------------------------------------------------------------------- (d)


def test_an_announcement_that_raises_still_returns_200(served, monkeypatch, caplog):
    monkeypatch.setattr(main, "ACTIVE", FailingSession())
    order_id = confirmed()
    advance(served, order_id, "PREPARING")

    with caplog.at_level(logging.ERROR, logger="main"):
        response = advance(served, order_id, "READY")

    print("status:", response.status_code, "body:", response.json()["order"]["status"])
    assert response.status_code == 200
    assert response.json()["order"]["status"] == "READY"
    assert of_type("order_ready") != []
    messages = [record.getMessage() for record in caplog.records]
    print("logged:", messages)
    assert "the order-ready announcement could not be spoken" in messages
    assert "RuntimeError" in caplog.text


# ------------------------------------------------------------------------- (e)


def test_marking_an_item_sold_out_and_available_again(served):
    event_bus.PUBLISHED.clear()
    sold_out = served.post(
        "/api/menu/Blue Lemonade/availability", json={"available": False}, headers=AUTH
    )
    print("sold out ->", sold_out.status_code, json.dumps(sold_out.json(), indent=2))
    print("published:", [event["type"] for event in event_bus.PUBLISHED])
    assert sold_out.status_code == 200
    assert sold_out.json()["item"] == {
        "name": "Blue Lemonade",
        "category": "Drinks",
        "price": "Rs. 250",
        "description": "Butterfly-pea lemonade, lightly sweet.",
        "image_url": "/menu/blue-lemonade.jpg",
        "available": False,
        "prep_seconds": 60,
    }
    assert of_type("menu_updated")[0]["item"] == "Blue Lemonade"
    assert of_type("menu_updated")[0]["available"] is False
    assert of_type("menu_updated")[0]["session_id"] is None
    assert of_type("agent_activity")[0]["label"] == "Marked Blue Lemonade sold out"
    assert of_type("agent_activity")[0]["kind"] == "operator"
    assert of_type("agent_activity")[0]["detail"] is None

    # The agent reads availability from the database on every call.
    checked = tools.check_item_availability(item="Blue Lemonade")
    print("check_item_availability while sold out:", json.dumps(checked, indent=2))
    assert checked["items"][0]["available"] is False
    assert [item["available"] for item in served.get("/api/menu").json()["menu"]
            if item["name"] == "Blue Lemonade"] == [False]

    event_bus.PUBLISHED.clear()
    back = served.post(
        "/api/menu/Blue Lemonade/availability", json={"available": True}, headers=AUTH
    )
    print("available again ->", back.status_code, json.dumps(back.json(), indent=2))
    assert back.status_code == 200
    assert back.json()["item"]["available"] is True
    assert of_type("menu_updated")[0]["available"] is True
    assert of_type("agent_activity")[0]["label"] == "Marked Blue Lemonade available"
    assert tools.check_item_availability(item="Blue Lemonade")["items"][0]["available"] is True

    actions = system_events("operator_action")
    print("operator_action rows:", actions)
    assert [json.loads(row["detail"]) for row in actions] == [
        {"action": "menu_availability", "item": "Blue Lemonade", "available": False},
        {"action": "menu_availability", "item": "Blue Lemonade", "available": True},
    ]


def test_the_availability_endpoint_rejects_an_unknown_item_a_bad_body_and_no_token(served):
    unknown = served.post(
        "/api/menu/Lobster Roll/availability", json={"available": False}, headers=AUTH
    )
    print("unknown item ->", unknown.status_code, unknown.json())
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "That item isn't on the menu."}

    for body in ({"available": "no"}, {"available": 1}, {"available": "true"}, {}, [True]):
        bad = served.post(
            "/api/menu/Blue Lemonade/availability", json=body, headers=AUTH
        )
        print(f"bad body {body!r} ->", bad.status_code, bad.json())
        assert bad.status_code == 400
        assert bad.json() == {"detail": "Invalid availability update."}

    no_token = served.post("/api/menu/Blue Lemonade/availability", json={"available": False})
    print("no token ->", no_token.status_code, no_token.json())
    assert no_token.status_code == 401

    # Nothing above changed the row.
    assert data.get_menu_item("Blue Lemonade")["available"] == 1


# ------------------------------------------------------------------------- (f)


def test_the_public_display_receives_order_ready_and_menu_updated(served):
    order_id = confirmed()
    data.update_order_status(order_id, "PREPARING")

    with served.websocket_connect("/ws/events?role=smd") as smd:
        assert smd.receive_json()["type"] == "state_snapshot"

        served.post(f"/api/orders/{order_id}/status", json={"status": "READY"}, headers=AUTH)
        updated = smd.receive_json()
        ready = smd.receive_json()
        print("smd order_updated:", updated)
        print("smd order_ready:", ready)

        served.post(
            "/api/menu/Blue Lemonade/availability", json={"available": False}, headers=AUTH
        )
        menu = smd.receive_json()
        print("smd menu_updated:", menu)

    assert updated["type"] == "order_updated"
    assert "guest_name" not in updated["order"]
    assert ready["type"] == "order_ready"
    assert ready["order_id"] == order_id
    assert ready["customer_name"] == "Ahmed"
    assert menu == {**menu, "type": "menu_updated", "item": "Blue Lemonade", "available": False}


# ------------------------------------------------------------------------- (g)


def test_the_access_log_redacts_the_operator_token(caplog):
    for name in ("uvicorn.access", "uvicorn.error"):
        assert main.REDACT_TOKEN in logging.getLogger(name).filters

    access = logging.getLogger("uvicorn.access")
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        access.info(
            '%s - "WebSocket %s" [accepted]',
            "127.0.0.1:60121",
            "/ws/events?role=dashboard&token=abc",
        )
        access.info('%s - "%s %s HTTP/1.1" %d', "127.0.0.1:1", "GET", "/x?token=abc&y=1", 200)
        access.info("a literal line with token=abc in the message itself")

    lines = [record.getMessage() for record in caplog.records]
    for line in lines:
        print("access log:", line)
    assert lines == [
        '127.0.0.1:60121 - "WebSocket /ws/events?role=dashboard&token=[REDACTED]" [accepted]',
        '127.0.0.1:1 - "GET /x?token=[REDACTED]&y=1 HTTP/1.1" 200',
        "a literal line with token=[REDACTED] in the message itself",
    ]
    assert not any("abc" in line for line in lines)


def test_the_filter_leaves_an_ordinary_record_alone(caplog):
    logger = logging.getLogger("uvicorn.error")
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logger.info("Application startup complete.")
        logger.info("%s items", 5)
    assert [record.getMessage() for record in caplog.records] == [
        "Application startup complete.",
        "5 items",
    ]


# -------------------------------------------------------------- mark_announced


def test_mark_announced_is_true_only_for_the_first_caller():
    order_id = confirmed()
    assert data.mark_announced(order_id) is True
    assert data.mark_announced(order_id) is False
    assert order_row(order_id)["announced"] == 1
    assert data.mark_announced(9999) is False
