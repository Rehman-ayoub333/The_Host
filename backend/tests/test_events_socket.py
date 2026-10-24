import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import config
import data
import event_bus
import main
from doubles import FakeLiveApiSession, FakeWebSocket, SlowWebSocket, call, content, message
from live_session import LiveSession


TOKEN = "operator-token-for-tests"


@pytest.fixture
def served(monkeypatch):
    """The real app, with the lifespan running, so event_bus has the app's loop."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


def on_app_loop(coro, timeout=10):
    """Run a coroutine on the app's event loop from the test thread."""
    return asyncio.run_coroutine_threadsafe(coro, event_bus._loop).result(timeout=timeout)


def sentinel():
    """A heartbeat both roles receive, used to mark the end of a burst."""
    on_app_loop(asyncio.sleep(0.25))
    on_app_loop(_publish_heartbeat())


async def _publish_heartbeat():
    event_bus.publish({"type": "heartbeat"})


def drain(socket):
    received = []
    while True:
        event = socket.receive_json()
        if event["type"] == "heartbeat":
            return received
        received.append(event)


async def fake_conversation():
    """A session that orders, is told a name, confirms, and speaks."""
    ws = FakeWebSocket()
    session = LiveSession(ws, "button")
    session.session = FakeLiveApiSession()
    await session._send_state("LISTENING")
    await session._handle_message(
        message(tool_call=call("build_order", {"items": [{"name": "Chicken Burger"}]}))
    )
    await session._handle_message(
        message(tool_call=call("remember_visitor", {"name": "Sara"}))
    )
    order_id = session.ctx["pending_order_id"]
    await session._handle_message(
        message(tool_call=call("confirm_order", {"order_id": order_id}))
    )
    await session._handle_message(message(content(visitor="I want")))
    await session._handle_message(message(content(turn_complete=True)))
    return session.ctx["session_id"]


# ------------------------------------------------------------------------- (a)


def test_both_roles_get_their_filtered_stream(served):
    with served.websocket_connect(f"/ws/events?role=dashboard&token={TOKEN}") as dash, \
         served.websocket_connect("/ws/events?role=smd") as smd:
        assert dash.receive_json()["type"] == "state_snapshot"
        assert smd.receive_json()["type"] == "state_snapshot"

        on_app_loop(fake_conversation())
        sentinel()
        dashboard_events = drain(dash)
        smd_events = drain(smd)

    dashboard_types = [event["type"] for event in dashboard_events]
    smd_types = [event["type"] for event in smd_events]

    print("DASHBOARD STREAM:")
    for event in dashboard_events:
        print(f"  {event}")
    print("SMD STREAM:")
    for event in smd_events:
        print(f"  {event}")

    # The dashboard sees the private events.
    assert "memory_updated" in dashboard_types
    assert "agent_activity" in dashboard_types
    assert "visitor_identified" in dashboard_types
    assert "order_created" in dashboard_types

    # The public display never sees them.
    for private in (
        "memory_updated", "agent_activity", "vision_update", "system_status_changed",
        "speech_transcript",
    ):
        assert private not in smd_types

    # The dashboard gets both transcript kinds; smd gets none at all
    # (16 section 2o item 2).
    assert any(not event["final"] for event in dashboard_events if event["type"] == "speech_transcript")
    assert any(event["final"] for event in dashboard_events if event["type"] == "speech_transcript")

    # No guest_name anywhere in an smd order object.
    for event in smd_events:
        if event["type"] in ("order_created", "order_updated"):
            assert "guest_name" not in event["order"]
    assert any(
        "guest_name" in event["order"]
        for event in dashboard_events
        if event["type"] in ("order_created", "order_updated")
    )

    # visitor_identified is reduced to name and returning.
    smd_identified = [event for event in smd_events if event["type"] == "visitor_identified"][0]
    assert set(smd_identified) == {"type", "name", "returning", "event_id", "timestamp", "session_id"}
    dashboard_identified = [
        event for event in dashboard_events if event["type"] == "visitor_identified"
    ][0]
    assert "visits" in dashboard_identified and "favorite_item" in dashboard_identified


# ------------------------------------------------------------------------- (b)


def test_a_wrong_dashboard_token_is_closed_4401(served):
    with pytest.raises(WebSocketDisconnect) as failure:
        with served.websocket_connect("/ws/events?role=dashboard&token=wrong") as socket:
            socket.receive_json()
    assert failure.value.code == 4401


def test_a_missing_dashboard_token_is_closed_4401(served):
    with pytest.raises(WebSocketDisconnect) as failure:
        with served.websocket_connect("/ws/events?role=dashboard") as socket:
            socket.receive_json()
    assert failure.value.code == 4401


def test_a_missing_or_unknown_role_is_closed_4400(served):
    for query in ("", "?role=", "?role=operator"):
        with pytest.raises(WebSocketDisconnect) as failure:
            with served.websocket_connect(f"/ws/events{query}") as socket:
                socket.receive_json()
        assert failure.value.code == 4400


def test_an_empty_operator_token_refuses_the_dashboard_and_rest(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", "")

    with caplog.at_level(logging.WARNING, logger="main"):
        with TestClient(main.app) as client:
            with pytest.raises(WebSocketDisconnect) as failure:
                with client.websocket_connect("/ws/events?role=dashboard&token=anything") as s:
                    s.receive_json()
            assert failure.value.code == 4401

            # The public role still works: it needs no token.
            with client.websocket_connect("/ws/events?role=smd") as smd:
                assert smd.receive_json()["type"] == "state_snapshot"

            refused = client.get("/api/orders", headers={"X-Operator-Token": "anything"})
            assert refused.status_code == 401
            assert refused.json() == {"detail": "Operator token required."}

    warnings = [record.getMessage() for record in caplog.records]
    assert any("OPERATOR_TOKEN is not set" in line for line in warnings)
    print("STARTUP WARNING:", [line for line in warnings if "OPERATOR_TOKEN" in line])


# ------------------------------------------------------------------------- (c)


def test_a_blocking_observer_never_delays_the_audio_socket(monkeypatch):
    monkeypatch.setattr(config, "EVENT_SEND_TIMEOUT_S", 0.1)

    async def scenario():
        event_bus.set_loop(asyncio.get_running_loop())
        slow = SlowWebSocket(delay=5.0)
        event_bus.register(slow, "dashboard")

        ws = FakeWebSocket()
        session = LiveSession(ws, "button")
        session.session = FakeLiveApiSession()

        started = time.perf_counter()
        await session._send_state("LISTENING")
        await session._handle_message(message(content(visitor="hello")))
        await session._handle_message(message(content(turn_complete=True)))
        elapsed = time.perf_counter() - started

        registered_during = slow in event_bus.sockets()
        await asyncio.sleep(config.EVENT_SEND_TIMEOUT_S + 0.3)
        return elapsed, registered_during, slow in event_bus.sockets(), len(ws.sent), slow.attempts

    elapsed, registered_during, still_registered, sent, attempts = asyncio.run(scenario())

    print(f"audio-socket work took {elapsed:.4f}s for {sent} messages")
    print(f"blocking observer registered during the burst: {registered_during}")
    print(f"blocking observer still registered afterwards: {still_registered}")
    print(f"send attempts against the blocking socket: {attempts}")

    assert elapsed < 0.5, "a blocking observer delayed the audio socket"
    assert registered_during is True
    assert still_registered is False
    assert sent >= 3


def test_a_dead_observer_is_unregistered(monkeypatch):
    from doubles import DeadWebSocket

    monkeypatch.setattr(config, "EVENT_SEND_TIMEOUT_S", 0.5)

    async def scenario():
        event_bus.set_loop(asyncio.get_running_loop())
        dead = DeadWebSocket()
        event_bus.register(dead, "dashboard")
        event_bus.publish({"type": "agent_state_changed", "state": "LISTENING", "session_id": None})
        await asyncio.sleep(0.1)
        return dead.attempts, dead in event_bus.sockets(), dead.closed

    attempts, still_registered, closed = asyncio.run(scenario())
    print(f"attempts={attempts} still_registered={still_registered} closed={closed}")
    assert attempts == 1
    assert still_registered is False
    assert closed is True


# ------------------------------------------------------------------------- (d)


def test_the_first_message_is_a_state_snapshot_for_both_roles(served):
    order_id = data.create_order_draft(
        [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}], "Ahmed", "s-snap"
    )["order_id"]
    data.update_order_status(order_id, "CONFIRMED")

    with served.websocket_connect(f"/ws/events?role=dashboard&token={TOKEN}") as dash:
        dashboard_snapshot = dash.receive_json()
    with served.websocket_connect("/ws/events?role=smd") as smd:
        smd_snapshot = smd.receive_json()

    print("DASHBOARD SNAPSHOT:", dashboard_snapshot)
    print("SMD SNAPSHOT:", smd_snapshot)

    for snapshot in (dashboard_snapshot, smd_snapshot):
        assert snapshot["type"] == "state_snapshot"
        assert len(snapshot["boot_id"]) == 6
        assert snapshot["operational_mode"] == "ONLINE"
        assert snapshot["conversation_state"] == "IDLE"
        assert snapshot["session_id"] is None
        assert snapshot["present"] is False
        assert [order["id"] for order in snapshot["active_orders"]] == [order_id]
        assert isinstance(snapshot["event_id"], int)

    assert dashboard_snapshot["active_orders"][0]["guest_name"] == "Ahmed"
    assert "guest_name" not in smd_snapshot["active_orders"][0]


def test_a_restart_gives_a_different_boot_id(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    boot_ids = []
    for _ in range(2):
        with TestClient(main.app) as client:
            with client.websocket_connect("/ws/events?role=smd") as smd:
                boot_ids.append(smd.receive_json()["boot_id"])
    print("boot_ids across two starts:", boot_ids)
    assert boot_ids[0] != boot_ids[1]


# ------------------------------------------------------------------------- (e)


def test_heartbeat_has_a_timestamp_but_no_event_id(monkeypatch):
    """16 section 2zb item 9: read frames until each one has been seen.

    The heartbeat interval is shortened to 50 ms here, which is short enough
    that a beat can win the race to the socket and arrive before the snapshot.
    Assuming the first frame is the snapshot made this test fail once in 7i-c
    with `assert 'heartbeat' == 'state_snapshot'`, so neither frame's order is
    assumed any more: both must simply turn up.
    """
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(config, "HEARTBEAT_INTERVAL_S", 0.05)

    seen = []
    beat = None
    snapshot = None
    with TestClient(main.app) as client:
        with client.websocket_connect("/ws/events?role=smd") as smd:
            # Ten frames is far more than the two this needs, and it ends as
            # soon as both have arrived.
            for _ in range(10):
                frame = smd.receive_json()
                seen.append(frame["type"])
                if frame["type"] == "heartbeat" and beat is None:
                    beat = frame
                elif frame["type"] == "state_snapshot" and snapshot is None:
                    snapshot = frame
                if beat is not None and snapshot is not None:
                    break

    print("frames in the order they arrived:", seen)
    print("HEARTBEAT:", beat)
    assert snapshot is not None, seen
    assert beat is not None, seen
    assert beat["type"] == "heartbeat"
    assert "event_id" not in beat
    assert beat["timestamp"]
