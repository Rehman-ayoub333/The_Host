import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

import config
import data
import main
import summaries


TOKEN = "operator-token-for-tests"
AUTH = {"X-Operator-Token": TOKEN}
BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}
LEMONADE = {"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


def seed_orders():
    active = data.create_order_draft([BURGER], "Ahmed", "s-1")["order_id"]
    data.update_order_status(active, "CONFIRMED")
    done = data.create_order_draft([LEMONADE], None, "s-2")["order_id"]
    data.update_order_status(done, "CANCELLED", reason="changed mind")
    draft = data.create_order_draft([BURGER], None, "s-3")["order_id"]
    return active, done, draft


# ------------------------------------------------------------------------- (f)


def test_orders_endpoint_shape_and_counts(served):
    active, done, draft = seed_orders()

    body = served.get("/api/orders", headers=AUTH).json()
    print("GET /api/orders:", json.dumps(body, indent=2))

    assert body["counts"] == {"active": 1, "completed": 1, "all": 3}
    assert [order["id"] for order in body["orders"]] == [draft, done, active]
    first = body["orders"][-1]
    assert set(first) == {
        "id", "items", "status", "guest_name", "total", "timestamp",
        "estimated_ready_at", "ready_at",
    }
    assert first["total"] == "Rs. 650"

    assert [o["id"] for o in served.get("/api/orders?status=active", headers=AUTH).json()["orders"]] == [active]
    assert [o["id"] for o in served.get("/api/orders?status=completed", headers=AUTH).json()["orders"]] == [done]
    assert len(served.get("/api/orders?limit=1", headers=AUTH).json()["orders"]) == 1
    # limit is clamped to 1..100
    assert len(served.get("/api/orders?limit=0", headers=AUTH).json()["orders"]) == 1
    assert len(served.get("/api/orders?limit=9999", headers=AUTH).json()["orders"]) == 3


def test_visitors_endpoint_shape(served):
    data.create_visitor("ahmed", "Ahmed")
    data.record_visit("ahmed")

    body = served.get("/api/visitors", headers=AUTH).json()
    print("GET /api/visitors:", json.dumps(body, indent=2))

    assert set(body["visitors"][0]) == {
        "name_key", "name", "visits", "favorite_item", "last_order",
        "first_seen", "last_seen", "returning",
    }
    assert body["visitors"][0]["returning"] is True


def test_activity_endpoint_shape(served):
    summaries.emit_activity("order", "Order #1 created", "Chicken Burger", "s-1")

    body = served.get("/api/activity", headers=AUTH).json()
    print("GET /api/activity:", json.dumps(body, indent=2))

    assert set(body["activity"][0]) == {"kind", "label", "detail", "timestamp"}
    assert body["activity"][0]["label"] == "Order #1 created"
    assert body["activity"][0]["detail"] == "Chicken Burger"


def test_analytics_endpoint_shape(served):
    active, _, _ = seed_orders()
    data.log_system_event("session_started", "system", {"session_id": "s-1"})

    body = served.get("/api/analytics", headers=AUTH).json()
    print("GET /api/analytics:", json.dumps(body, indent=2))

    assert set(body) == {
        "date", "orders", "interactions", "named_visitors",
        "returning_visitors", "popular_items", "average_order_to_ready_seconds",
    }
    assert body["orders"] == 1
    assert body["interactions"] == 1
    assert body["popular_items"] == [{"name": "Chicken Burger", "percent": 100}]
    assert body["average_order_to_ready_seconds"] is None


def test_menu_endpoint_needs_no_token_and_returns_booleans(served):
    body = served.get("/api/menu").json()
    print("GET /api/menu:", json.dumps(body, indent=2))

    assert len(body["menu"]) == 5
    assert set(body["menu"][0]) == {
        "name", "category", "price", "description", "image_url", "available", "prep_seconds",
    }
    assert all(isinstance(item["available"], bool) for item in body["menu"])
    assert [item["name"] for item in body["menu"]][:2] == ["Blue Lemonade", "Mixed Fruit Shake"]


def test_every_protected_endpoint_refuses_a_missing_or_wrong_token(served):
    for path in ("/api/orders", "/api/visitors", "/api/activity", "/api/analytics"):
        without = served.get(path)
        wrong = served.get(path, headers={"X-Operator-Token": "nope"})
        print(f"{path}: no token -> {without.status_code} {without.json()}")
        assert without.status_code == 401
        assert without.json() == {"detail": "Operator token required."}
        assert wrong.status_code == 401
    # The menu is public by design.
    assert served.get("/api/menu").status_code == 200


def test_a_database_error_gives_503_with_a_plain_message(served, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main.data, "list_orders", fail)
    response = served.get("/api/orders", headers=AUTH)
    print("forced sqlite error:", response.status_code, response.json())

    assert response.status_code == 503
    assert response.json() == {"detail": "The database could not be read."}


# ------------------------------------------------------------------------- (g)


def test_vision_accepts_a_valid_report_and_publishes_presence(served):
    with served.websocket_connect(f"/ws/events?role=dashboard&token={TOKEN}") as dash:
        assert dash.receive_json()["type"] == "state_snapshot"

        arrived = served.post(
            "/api/vision",
            json={"present": True, "people": 2, "objects": [{"label": "cup", "confidence": 0.81}]},
        )
        print("POST /api/vision (present) ->", arrived.status_code, repr(arrived.text))
        assert arrived.status_code == 204
        assert arrived.text == ""

        detected = dash.receive_json()
        activity = dash.receive_json()
        update = dash.receive_json()
        print("person_detected:", detected)
        print("activity:", activity)
        print("vision_update:", update)

        left_response = served.post("/api/vision", json={"present": False, "people": 0})
        assert left_response.status_code == 204
        left = dash.receive_json()
        print("person_left:", left)

    assert detected["type"] == "person_detected"
    assert detected["person_id"].startswith("p-")
    assert detected["session_id"] is None
    assert update["type"] == "vision_update"
    assert update["present"] is True
    assert update["people"] == 2
    assert update["objects"] == [{"label": "cup", "confidence": 0.81}]
    assert activity["type"] == "agent_activity"
    assert activity["label"] == "Visitor detected"
    assert left["type"] == "person_left"
    assert left["person_id"] == detected["person_id"]


def test_vision_rejects_invalid_reports_with_400(served):
    cases = {
        "people too high": {"present": True, "people": 99},
        "people negative": {"present": True, "people": -1},
        "present missing": {"people": 1},
        "present not a boolean": {"present": "maybe", "people": 1},
        "present is a list": {"present": [], "people": 1},
        "people not a number": {"present": True, "people": "two"},
        "body is not an object": [1, 2, 3],
        "too many objects": {
            "present": True,
            "people": 1,
            "objects": [{"label": "cup", "confidence": 0.5}] * 11,
        },
        "label too long": {
            "present": True, "people": 1,
            "objects": [{"label": "x" * 41, "confidence": 0.5}],
        },
        "confidence out of range": {
            "present": True, "people": 1,
            "objects": [{"label": "cup", "confidence": 1.5}],
        },
    }
    for label, body in cases.items():
        response = served.post("/api/vision", json=body)
        print(f"{label}: {response.status_code} {response.json()}")
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid vision report."}

    raw = served.post(
        "/api/vision", content="{not json", headers={"Content-Type": "application/json"}
    )
    print("invalid JSON:", raw.status_code, raw.json())
    assert raw.status_code == 400
    assert raw.json() == {"detail": "Invalid vision report."}


def test_vision_only_announces_a_real_transition(served):
    with served.websocket_connect(f"/ws/events?role=dashboard&token={TOKEN}") as dash:
        dash.receive_json()
        served.post("/api/vision", json={"present": True, "people": 1})
        first = [dash.receive_json()["type"] for _ in range(3)]
        served.post("/api/vision", json={"present": True, "people": 1})
        second = dash.receive_json()["type"]

    print("first post:", first)
    print("second post with no transition:", second)
    assert first == ["person_detected", "agent_activity", "vision_update"]
    assert second == "vision_update"


# ------------------------------------------------------------------------- (h)


def test_cors_allows_the_configured_origin_only(served):
    allowed = served.options(
        "/api/orders",
        headers={
            "Origin": "http://localhost:8080",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Operator-Token",
        },
    )
    print("preflight from http://localhost:8080 ->", allowed.status_code)
    for header, value in allowed.headers.items():
        if header.lower().startswith("access-control"):
            print(f"  {header}: {value}")

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert "x-operator-token" in allowed.headers["access-control-allow-headers"].lower()

    refused = served.options(
        "/api/orders",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Operator-Token",
        },
    )
    print("preflight from http://evil.example ->", refused.status_code, repr(refused.text))
    for header, value in refused.headers.items():
        if header.lower().startswith("access-control"):
            print(f"  {header}: {value}")

    assert "access-control-allow-origin" not in refused.headers


# ------------------------------------------------------------------------- (i)


def test_the_sweep_cancels_an_expired_draft_with_no_other_call(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(config, "PENDING_SWEEP_INTERVAL_S", 0.1)

    def raw_row():
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            return dict(
                conn.execute(
                    "SELECT status, cancel_reason FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
            )

    order_id = data.create_order_draft([BURGER], None, "s-sweep")["order_id"]
    with sqlite3.connect(config.DB_PATH) as conn:
        stale = "2026-10-01T00:00:00"
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stale, order_id))
        conn.commit()
    # Read with raw SQL: data.get_order would itself trigger the lazy expiry,
    # which is the very thing this test must not rely on.
    print("row before the sweep:", raw_row())
    assert raw_row()["status"] == "PENDING_CONFIRMATION"

    with TestClient(main.app):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = raw_row()
            if row["status"] == "CANCELLED":
                break
            time.sleep(0.1)

    print("row after the sweep:", row)
    assert row == {"status": "CANCELLED", "cancel_reason": "expired"}
