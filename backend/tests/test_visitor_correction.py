"""Phase 5: PATCH and DELETE /api/visitors/{name_key} (11 section 5, 16 2e item 5)."""

import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import data
import event_bus
import main


TOKEN = "operator-token-for-tests"
AUTH = {"X-Operator-Token": TOKEN}
BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}


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


def a_visitor(name="Lala"):
    """A visitor with a mis-heard name, a favourite and one order behind them."""
    key = name.lower()
    data.create_visitor(key, name)
    order_id = data.create_order_draft([BURGER], name, "s-1")["order_id"]
    data.update_order_status(order_id, "CONFIRMED")
    data.refresh_visitor_after_order(data.get_order(order_id))
    event_bus.PUBLISHED.clear()
    return key, order_id


def patch(client, key, body):
    event_bus.PUBLISHED.clear()
    response = client.patch(f"/api/visitors/{key}", json=body, headers=AUTH)
    print(f"PATCH /api/visitors/{key} {body!r} -> {response.status_code} {response.text}")
    print("    published:", [event["type"] for event in event_bus.PUBLISHED])
    return response


# ------------------------------------------------------------------- PATCH, ok


def test_correcting_a_mis_heard_name(served):
    key, _ = a_visitor()

    response = patch(served, key, {"display_name": "  Laila  "})

    print("response JSON:", json.dumps(response.json(), indent=2))
    assert response.status_code == 200
    visitor = response.json()["visitor"]
    assert visitor == {
        "name_key": "lala",
        "name": "Laila",
        "visits": 1,
        "favorite_item": "Chicken Burger",
        "last_order": "Chicken Burger",
        "first_seen": visitor["first_seen"],
        "last_seen": visitor["last_seen"],
        "returning": False,
    }
    # The same object GET /api/visitors returns.
    assert served.get("/api/visitors", headers=AUTH).json()["visitors"] == [visitor]

    memory = of_type("memory_updated")[0]
    print("memory_updated:", json.dumps(memory, indent=2))
    assert memory["name"] == "Laila"
    assert memory["visits"] == 1
    assert memory["favorite_item"] == "Chicken Burger"
    assert memory["last_order"] == "Chicken Burger"
    assert memory["returning"] is False
    assert memory["session_id"] is None
    assert "Operator: corrected a visitor" in activity_labels()
    assert of_type("agent_activity")[0]["kind"] == "operator"
    assert of_type("agent_activity")[0]["detail"] is None
    print("operator_action rows:", operator_actions())
    assert operator_actions() == [{"action": "visitor_update", "name_key": "lala"}]


def test_correcting_the_favourite_and_clearing_it(served):
    key, _ = a_visitor()

    changed = patch(served, key, {"favorite_item": "Blue Lemonade"})
    assert changed.status_code == 200
    assert changed.json()["visitor"]["favorite_item"] == "Blue Lemonade"
    assert changed.json()["visitor"]["name"] == "Lala"

    cleared = patch(served, key, {"favorite_item": None})
    print("after clearing:", json.dumps(cleared.json(), indent=2))
    assert cleared.status_code == 200
    assert cleared.json()["visitor"]["favorite_item"] is None
    assert data.get_visitor(key)["favorite_item"] is None
    assert of_type("memory_updated")[0]["favorite_item"] is None


def test_both_fields_at_once(served):
    key, _ = a_visitor()
    response = patch(served, key, {"display_name": "Laila", "favorite_item": "Club Sandwich"})
    assert response.status_code == 200
    assert response.json()["visitor"]["name"] == "Laila"
    assert response.json()["visitor"]["favorite_item"] == "Club Sandwich"


def test_the_longest_accepted_values(served):
    key, _ = a_visitor()
    assert patch(served, key, {"display_name": "x" * 60}).status_code == 200
    assert patch(served, key, {"favorite_item": "y" * 80}).status_code == 200
    assert data.get_visitor(key)["display_name"] == "x" * 60


# -------------------------------------------------------------- PATCH, refused


def test_an_invalid_patch_body_is_refused_and_changes_nothing(served):
    key, _ = a_visitor()
    before = data.get_visitor(key)

    bodies = (
        {},
        {"display_name": ""},
        {"display_name": "   "},
        {"display_name": "x" * 61},
        {"display_name": 7},
        {"display_name": None},
        {"favorite_item": "y" * 81},
        {"favorite_item": 7},
        {"visits": 9},
        {"display_name": "Laila", "visits": 9},
        [1, 2],
        "Laila",
    )
    for body in bodies:
        response = served.patch(f"/api/visitors/{key}", json=body, headers=AUTH)
        print(f"bad body {body!r} -> {response.status_code} {response.json()}")
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid visitor update."}

    invalid_json = served.patch(
        f"/api/visitors/{key}",
        content=b"{not json",
        headers={**AUTH, "Content-Type": "application/json"},
    )
    print("invalid JSON ->", invalid_json.status_code, invalid_json.json())
    assert invalid_json.status_code == 400

    print("row afterwards:", data.get_visitor(key))
    assert data.get_visitor(key) == before
    assert operator_actions() == []


def test_patching_an_unknown_visitor_is_404(served):
    response = patch(served, "nobody", {"display_name": "Laila"})
    print("unknown ->", response.status_code, response.json())
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no visitor with that name."}
    assert of_type("memory_updated") == []
    assert operator_actions() == []


# ------------------------------------------------------------------- DELETE


def test_forgetting_a_visitor_leaves_the_orders_alone(served):
    key, order_id = a_visitor()
    event_bus.PUBLISHED.clear()

    response = served.delete(f"/api/visitors/{key}", headers=AUTH)
    print(f"DELETE /api/visitors/{key} -> {response.status_code} {response.text!r}")
    print("    published:", [event["type"] for event in event_bus.PUBLISHED])

    assert response.status_code == 204
    assert response.content == b""
    assert data.get_visitor(key) is None
    assert served.get("/api/visitors", headers=AUTH).json() == {"visitors": []}
    # The order and its guest name are untouched.
    print("order after the deletion:", data.get_order(order_id))
    assert data.get_order(order_id)["guest_name"] == "Lala"
    assert data.get_order(order_id)["status"] == "CONFIRMED"
    assert "Operator: forgot a visitor" in activity_labels()
    print("operator_action rows:", operator_actions())
    assert operator_actions() == [{"action": "visitor_delete", "name_key": "lala"}]


def test_forgetting_an_unknown_visitor_is_404(served):
    response = served.delete("/api/visitors/nobody", headers=AUTH)
    print("unknown ->", response.status_code, response.json())
    assert response.status_code == 404
    assert response.json() == {"detail": "There is no visitor with that name."}
    assert operator_actions() == []


def test_update_visitor_tells_an_absent_field_from_an_explicit_null():
    data.create_visitor("ahmed", "Ahmed")
    data.update_visitor("ahmed", favorite_item="Chicken Burger")

    # display_name only: the favourite survives.
    assert data.update_visitor("ahmed", display_name="Ahmad")["favorite_item"] == (
        "Chicken Burger"
    )
    # An explicit null clears it.
    assert data.update_visitor("ahmed", favorite_item=None)["favorite_item"] is None
