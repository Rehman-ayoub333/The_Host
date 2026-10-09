"""Phase 5: the seven operator controls and the paused /ws/session refusal
(16 section 2e item 4, 12 section 1, 07 section 3).
"""

import json
import logging
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import config
import data
import doubles
import event_bus
import health
import main


TOKEN = "operator-token-for-tests"
AUTH = {"X-Operator-Token": TOKEN}
BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}

# Every endpoint added in Phase 5 that takes the token.
NEW_ENDPOINTS = (
    ("POST", "/api/operator/pause"),
    ("POST", "/api/operator/resume"),
    ("POST", "/api/operator/takeover"),
    ("POST", "/api/operator/takeover/end"),
    ("POST", "/api/operator/end-session"),
    ("POST", "/api/operator/retry-connection"),
    ("POST", "/api/operator/announce"),
    ("PATCH", "/api/visitors/ahmed"),
    ("DELETE", "/api/visitors/ahmed"),
    ("GET", "/api/metrics"),
)


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(main, "ACTIVE", None)
    with TestClient(main.app) as client:
        yield client


def of_type(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


def activity_labels():
    return [event["label"] for event in of_type("agent_activity")]


def operator_actions():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            json.loads(row["detail"])
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'operator_action' "
                "ORDER BY id"
            ).fetchall()
        ]


def order_row(order_id):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return dict(
            conn.execute(
                "SELECT id, status, announced, cancel_reason FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        )


def post(client, path, **kwargs):
    event_bus.PUBLISHED.clear()
    response = client.post(path, headers=AUTH, **kwargs)
    print(f"POST {path} -> {response.status_code} {response.text}")
    print("    published:", [event["type"] for event in event_bus.PUBLISHED])
    print("    activity :", activity_labels())
    return response


def fake_probe(monkeypatch, *, status_code=None, error=None):
    """Stands in for httpx.AsyncClient so no real request is ever made."""
    captured = {}

    class Client:
        def __init__(self, **kwargs):
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        async def get(self, url, headers=None):
            captured["url"] = url
            captured["header_names"] = sorted(headers or {})
            captured["header_value"] = (headers or {}).get("x-goog-api-key")
            if error is not None:
                raise error
            return SimpleNamespace(status_code=status_code, text="SECRET-RESPONSE-BODY")

    monkeypatch.setattr(main.httpx, "AsyncClient", Client)
    return captured


# ------------------------------------------------------------- pause / resume


def test_pause_overrides_the_mode_and_resume_gives_it_back(served):
    paused = post(served, "/api/operator/pause")
    assert paused.status_code == 200
    assert paused.json() == {"operational_mode": "PAUSED"}
    assert health.mode() == "PAUSED"
    assert of_type("operational_mode_changed")[0]["mode"] == "PAUSED"
    assert "System mode: PAUSED" in activity_labels()
    assert "Operator: paused THE HOST" in activity_labels()
    assert of_type("agent_activity")[-1]["kind"] == "operator"
    assert of_type("agent_activity")[-1]["detail"] is None

    resumed = post(served, "/api/operator/resume")
    assert resumed.status_code == 200
    assert resumed.json() == {"operational_mode": "ONLINE"}
    assert health.mode() == "ONLINE"
    assert of_type("operational_mode_changed")[0]["mode"] == "ONLINE"
    assert "Operator: resumed THE HOST" in activity_labels()

    print("operator_action rows:", operator_actions())
    assert operator_actions() == [{"action": "pause"}, {"action": "resume"}]


def test_takeover_and_its_end(served):
    took_over = post(served, "/api/operator/takeover")
    assert took_over.status_code == 200
    assert took_over.json() == {"operational_mode": "OPERATOR_TAKEOVER"}
    assert "Operator: took over" in activity_labels()
    assert "System mode: OPERATOR_TAKEOVER" in activity_labels()

    ended = post(served, "/api/operator/takeover/end")
    assert ended.status_code == 200
    assert ended.json() == {"operational_mode": "ONLINE"}
    assert "Operator: ended the takeover" in activity_labels()

    print("operator_action rows:", operator_actions())
    assert operator_actions() == [{"action": "takeover"}, {"action": "takeover_end"}]


def test_pause_ends_an_active_session_and_kills_its_draft(served, monkeypatch):
    session, ws = doubles.new_session()
    order_id = data.create_order_draft([BURGER], "Ahmed", session.ctx["session_id"])[
        "order_id"
    ]
    session.ctx["pending_order_id"] = order_id
    monkeypatch.setattr(main, "ACTIVE", session)

    response = post(served, "/api/operator/pause")

    print("socket messages:", ws.sent)
    print("order row after the pause:", order_row(order_id))
    print("socket closed:", ws.closed)
    assert response.json() == {"operational_mode": "PAUSED"}
    assert doubles.states(ws) == ["IDLE"]
    assert ws.closed is True
    assert order_row(order_id)["status"] == "CANCELLED"
    assert order_row(order_id)["cancel_reason"] == "session_ended"
    assert of_type("order_updated")[0]["order"]["status"] == "CANCELLED"


def test_takeover_ends_an_active_session_too(served, monkeypatch):
    session, ws = doubles.new_session()
    monkeypatch.setattr(main, "ACTIVE", session)

    post(served, "/api/operator/takeover")

    print("socket messages:", ws.sent)
    assert doubles.states(ws) == ["IDLE"]


# ---------------------------------------------------------------- end-session


def test_end_session_reports_whether_there_was_one(served, monkeypatch):
    nothing = post(served, "/api/operator/end-session")
    assert nothing.status_code == 200
    assert nothing.json() == {"ended": False}
    assert "Operator: ended the conversation" in activity_labels()

    session, ws = doubles.new_session()
    monkeypatch.setattr(main, "ACTIVE", session)
    ended = post(served, "/api/operator/end-session")
    print("socket messages:", ws.sent)
    assert ended.json() == {"ended": True}
    assert doubles.states(ws) == ["IDLE"]
    assert health.mode() == "ONLINE"

    print("operator_action rows:", operator_actions())
    assert operator_actions() == [
        {"action": "end_session", "ended": False},
        {"action": "end_session", "ended": True},
    ]


# ----------------------------------------------------------- retry-connection


def test_retry_connection_reaching_the_service_returns_online(served, monkeypatch, caplog):
    health.connect_failed("Something went wrong. Please try again.")
    assert health.mode() == "OFFLINE"
    captured = fake_probe(monkeypatch, status_code=200)

    with caplog.at_level(logging.INFO):
        response = post(served, "/api/operator/retry-connection")

    print("probe url:", captured["url"])
    print("probe header names:", captured["header_names"])
    print("probe timeout:", captured["timeout"])
    assert response.status_code == 200
    assert response.json() == {"operational_mode": "ONLINE", "reachable": True}
    assert health.mode() == "ONLINE"
    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
    )
    assert captured["header_names"] == ["x-goog-api-key"]
    assert captured["header_value"] == "test-key"
    assert captured["timeout"] == config.CONNECT_TIMEOUT_S
    assert "Operator: retried the connection" in activity_labels()
    # Neither the key nor the body may appear anywhere.
    assert "test-key" not in caplog.text
    assert "test-key" not in response.text
    assert "SECRET-RESPONSE-BODY" not in caplog.text
    assert "SECRET-RESPONSE-BODY" not in response.text


def test_retry_connection_with_a_refused_status_goes_offline(served, monkeypatch, caplog):
    captured = fake_probe(monkeypatch, status_code=403)

    with caplog.at_level(logging.INFO):
        response = post(served, "/api/operator/retry-connection")

    print("response:", response.json())
    assert response.json() == {"operational_mode": "OFFLINE", "reachable": False}
    assert health.mode() == "OFFLINE"
    mode_event = of_type("operational_mode_changed")[0]
    print("operational_mode_changed:", mode_event)
    assert mode_event["reason"] == "The AI service answered 403."
    assert "test-key" not in caplog.text
    assert "SECRET-RESPONSE-BODY" not in caplog.text
    assert captured["header_value"] == "test-key"


def test_retry_connection_with_a_network_error_goes_offline(served, monkeypatch, caplog):
    fake_probe(monkeypatch, error=OSError("getaddrinfo failed for key test-key"))

    with caplog.at_level(logging.INFO):
        response = post(served, "/api/operator/retry-connection")

    print("response:", response.json())
    assert response.json() == {"operational_mode": "OFFLINE", "reachable": False}
    reason = of_type("operational_mode_changed")[0]["reason"]
    print("reason:", reason)
    assert reason == "The AI service could not be reached (OSError)."
    # The exception text itself is never repeated, so nothing inside it leaks.
    assert "getaddrinfo" not in caplog.text
    assert "test-key" not in caplog.text
    assert "test-key" not in response.text

    print("operator_action rows:", operator_actions())
    assert operator_actions() == [{"action": "retry_connection", "reachable": False}]


# ------------------------------------------------------------------- announce


def ready_order(client, guest_name="Ahmed"):
    order_id = data.create_order_draft([BURGER], guest_name, "s-1")["order_id"]
    data.update_order_status(order_id, "CONFIRMED")
    data.update_order_status(order_id, "PREPARING")
    client.post(f"/api/orders/{order_id}/status", json={"status": "READY"}, headers=AUTH)
    return order_id


def test_announce_repeats_a_ready_order_even_though_it_was_announced(served, monkeypatch):
    order_id = ready_order(served)
    print("announced flag before the repeat:", order_row(order_id)["announced"])
    assert order_row(order_id)["announced"] == 1
    session, ws = doubles.new_session()
    monkeypatch.setattr(main, "ACTIVE", session)

    response = post(served, "/api/operator/announce", json={"order_id": order_id})

    print("response JSON:", json.dumps(response.json(), indent=2))
    print("order_ready:", of_type("order_ready"))
    print("sent to Gemini:", session.session.inputs)
    assert response.status_code == 200
    assert response.json()["order"]["id"] == order_id
    assert response.json()["order"]["status"] == "READY"
    assert len(of_type("order_ready")) == 1
    assert of_type("order_ready")[0]["order_id"] == order_id
    assert of_type("order_ready")[0]["customer_name"] == "Ahmed"
    assert of_type("order_ready")[0]["session_id"] is None
    assert session.session.inputs == [
        {
            "text": (
                f"An order just became ready: order #{order_id} for Ahmed. "
                "Let the guests know, briefly and naturally, even if it is not their order."
            )
        }
    ]
    assert f"Operator: repeated the announcement for order #{order_id}" in activity_labels()
    assert operator_actions()[-1] == {"action": "announce", "order_id": order_id}


def test_announce_with_no_session_only_publishes_order_ready(served):
    order_id = ready_order(served, guest_name=None)
    response = post(served, "/api/operator/announce", json={"order_id": order_id})

    assert response.status_code == 200
    print("order_ready:", of_type("order_ready"))
    assert of_type("order_ready")[0]["customer_name"] is None


def test_announce_refuses_an_order_that_is_not_ready(served):
    order_id = data.create_order_draft([BURGER], "Ahmed", "s-1")["order_id"]
    data.update_order_status(order_id, "CONFIRMED")

    response = post(served, "/api/operator/announce", json={"order_id": order_id})
    print("not READY ->", response.status_code, response.json())
    assert response.status_code == 400
    assert response.json() == {"detail": "Only a READY order can be announced again."}
    assert of_type("order_ready") == []
    assert operator_actions() == []


def test_announce_rejects_an_unknown_id_and_a_bad_body(served):
    unknown = post(served, "/api/operator/announce", json={"order_id": 9999})
    print("unknown ->", unknown.status_code, unknown.json())
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "There is no order with that number."}

    for body in ({}, {"order_id": "7"}, {"order_id": 1.5}, {"order_id": None}, [1], "x"):
        bad = served.post("/api/operator/announce", json=body, headers=AUTH)
        print(f"bad body {body!r} ->", bad.status_code, bad.json())
        assert bad.status_code == 400
        assert bad.json() == {"detail": "Invalid announcement request."}


# ---------------------------------------------------- the /ws/session refusal


def test_a_session_is_refused_while_paused(served):
    post(served, "/api/operator/pause")
    event_bus.PUBLISHED.clear()

    with served.websocket_connect("/ws/session") as socket:
        refusal = socket.receive_json()
        print("refusal:", json.dumps(refusal, indent=2))
        closing_frame = socket.receive()
        print("next frame:", closing_frame)

    assert refusal == {
        **refusal,
        "type": "error",
        "message": "THE HOST is paused right now. Please ask the team.",
        "recoverable": True,
        "session_id": None,
    }
    assert isinstance(refusal["event_id"], int)
    assert refusal["timestamp"]
    assert closing_frame["type"] == "websocket.close"
    assert main.ACTIVE is None


def test_a_session_is_refused_during_a_takeover(served):
    post(served, "/api/operator/takeover")

    with served.websocket_connect("/ws/session") as socket:
        refusal = socket.receive_json()
        print("refusal:", refusal)
        socket.receive()

    assert refusal["message"] == "THE HOST is paused right now. Please ask the team."


def test_a_session_is_accepted_again_after_a_resume(served, monkeypatch):
    post(served, "/api/operator/pause")
    post(served, "/api/operator/resume")
    assert health.mode() == "ONLINE"

    # A session is no longer refused by the override; it is refused here only
    # because this test refuses to open a real Gemini connection.
    monkeypatch.setattr(main, "ACTIVE", object())
    with served.websocket_connect("/ws/session") as socket:
        refusal = socket.receive_json()
        print("refusal after the resume:", refusal)
        socket.receive()

    assert refusal["message"] == "Another conversation is already active."


# --------------------------------------------------------------------- tokens


def test_every_new_endpoint_refuses_a_missing_or_wrong_token(served):
    for method, path in NEW_ENDPOINTS:
        without = served.request(method, path, json={})
        wrong = served.request(method, path, json={}, headers={"X-Operator-Token": "no"})
        print(f"{method} {path}: no token -> {without.status_code} {without.json()}")
        assert without.status_code == 401
        assert without.json() == {"detail": "Operator token required."}
        assert wrong.status_code == 401
        assert wrong.json() == {"detail": "Operator token required."}

    # Nothing above was allowed to change the mode or write an audit row.
    assert health.mode() == "ONLINE"
    assert operator_actions() == []
