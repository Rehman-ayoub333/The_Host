"""Phase 5: GET /api/metrics and the /health components (12 section 3, 2e items 6-7)."""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import config
import data
import health
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


def backdate(table, column="timestamp"):
    """Pushes every row of a table one day into the past."""
    yesterday = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute(f"UPDATE {table} SET {column} = ?", (yesterday,))
        conn.commit()


def test_an_empty_day_counts_zero(served):
    response = served.get("/api/metrics", headers=AUTH)
    print("GET /api/metrics:", json.dumps(response.json(), indent=2))
    assert response.status_code == 200
    assert response.json() == {
        "date": datetime.now().date().isoformat(),
        "sessions_today": 0,
        "orders_today": 0,
        "failed_tool_calls_today": 0,
        "connection_failures_today": 0,
    }


def test_every_counter_counts_the_right_rows(served):
    # Two conversations.
    data.log_system_event("session_started", "system", {"session_id": "a1b2c3d4"})
    data.log_system_event("session_started", "system", {"session_id": "e5f6a7b8"})

    # Three orders, of which one cancelled and one still a draft: one counts.
    counted = data.create_order_draft([BURGER], "Ahmed", "s-1")["order_id"]
    data.update_order_status(counted, "CONFIRMED")
    cancelled = data.create_order_draft([BURGER], "Ahmed", "s-2")["order_id"]
    data.update_order_status(cancelled, "CANCELLED", reason="changed mind")
    data.create_order_draft([BURGER], None, "s-3")

    # Two failed tool calls and one that worked.
    data.log_action("build_order", {"items": []}, {"error": "That didn't work."})
    data.log_action("web_search", {"query": "x"}, {"error": "That took too long."})
    data.log_action("check_item_availability", {"item": "x"}, {"items": []})

    # Two connection failures.
    health.connect_failed("Something went wrong. Please try again.")
    health.connect_failed("I couldn't reach my brain in time. Please try again.")

    body = served.get("/api/metrics", headers=AUTH).json()
    print("GET /api/metrics:", json.dumps(body, indent=2))
    assert body == {
        "date": datetime.now().date().isoformat(),
        "sessions_today": 2,
        "orders_today": 1,
        "failed_tool_calls_today": 2,
        "connection_failures_today": 2,
    }
    # The same orders rule as /api/analytics.
    assert served.get("/api/analytics", headers=AUTH).json()["orders"] == body["orders_today"]
    assert served.get("/api/analytics", headers=AUTH).json()["interactions"] == (
        body["sessions_today"]
    )


def test_yesterdays_rows_do_not_count(served):
    data.log_system_event("session_started", "system", {"session_id": "a1b2c3d4"})
    data.log_action("build_order", {}, {"error": "That didn't work."})
    health.connect_failed("Something went wrong. Please try again.")
    order_id = data.create_order_draft([BURGER], "Ahmed", "s-1")["order_id"]
    data.update_order_status(order_id, "CONFIRMED")
    assert served.get("/api/metrics", headers=AUTH).json()["sessions_today"] == 1

    backdate("system_events")
    backdate("agent_log")
    backdate("orders")

    body = served.get("/api/metrics", headers=AUTH).json()
    print("after back-dating every row:", json.dumps(body, indent=2))
    assert body == {
        "date": datetime.now().date().isoformat(),
        "sessions_today": 0,
        "orders_today": 0,
        "failed_tool_calls_today": 0,
        "connection_failures_today": 0,
    }


def test_metrics_needs_the_token_and_reports_a_database_error(served, monkeypatch):
    without = served.get("/api/metrics")
    print("no token ->", without.status_code, without.json())
    assert without.status_code == 401
    assert without.json() == {"detail": "Operator token required."}

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main.data, "get_metrics", fail)
    broken = served.get("/api/metrics", headers=AUTH)
    print("forced sqlite error ->", broken.status_code, broken.json())
    assert broken.status_code == 503
    assert broken.json() == {"detail": "The database could not be read."}


# ------------------------------------------------------------ /health components


def test_health_reports_its_components(served):
    body = served.get("/health").json()
    print("GET /health:", json.dumps(body, indent=2))
    assert body == {
        "status": "ok",
        "model": config.GEMINI_LIVE_MODEL,
        "menu_items": 5,
        "operational_mode": "ONLINE",
        "db": "ok",
        "components": {"backend": "online", "ai_agent": "online", "database": "ok"},
    }
    # No camera, microphone or speaker: the backend cannot see them.
    assert set(body["components"]) == {"backend", "ai_agent", "database"}


def test_an_offline_ai_agent_shows_in_both_places(served):
    health.connect_failed("Something went wrong. Please try again.")

    body = served.get("/health").json()
    print("GET /health while offline:", json.dumps(body, indent=2))
    assert body["operational_mode"] == "OFFLINE"
    assert body["components"]["ai_agent"] == "offline"


def test_a_pause_does_not_make_the_ai_agent_offline(served):
    served.post("/api/operator/pause", headers=AUTH)

    body = served.get("/health").json()
    print("GET /health while paused:", json.dumps(body, indent=2))
    assert body["operational_mode"] == "PAUSED"
    assert body["components"]["ai_agent"] == "online"

    # A failure underneath the pause still shows on the component.
    health.connect_failed("Something went wrong. Please try again.")
    body = served.get("/health").json()
    print("GET /health while paused and offline:", json.dumps(body, indent=2))
    assert body["operational_mode"] == "PAUSED"
    assert body["components"]["ai_agent"] == "offline"


def test_a_broken_database_shows_in_the_components(served, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", "Z:/nowhere/at/all/campus_ai.db")
    body = served.get("/health").json()
    print("GET /health with an unreachable database:", json.dumps(body, indent=2))
    assert body["db"] == "error"
    assert body["components"]["database"] == "error"
