import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx

import config
import data
import event_bus
import tools


def _published(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


def _pending_rows(session_id):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT id, status, items, session_id FROM orders "
                "WHERE session_id = ? AND status = 'PENDING_CONFIRMATION'",
                (session_id,),
            ).fetchall()
        ]


def _backdate(order_id, seconds):
    stamp = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stamp, order_id))
        conn.commit()


def test_check_item_availability_reads_the_real_menu(ctx):
    everything = tools.check_item_availability()
    assert everything["source"] == "menu"
    assert everything["total"] == 5
    assert [item["name"] for item in everything["items"]][:2] == [
        "Blue Lemonade",
        "Mixed Fruit Shake",
    ]

    burgers = tools.check_item_availability(item="burger")
    assert burgers["total"] == 2
    assert burgers["items"][0]["price"] == "Rs. 650"

    drinks = tools.check_item_availability(category="Drinks")
    assert [item["name"] for item in drinks["items"]] == ["Blue Lemonade", "Mixed Fruit Shake"]
    assert tools.check_item_availability(item="pizza")["items"] == []


def test_check_item_availability_reports_an_unavailable_item(ctx):
    data.set_menu_availability("Blue Lemonade", False)
    result = tools.check_item_availability(item="Blue Lemonade")
    assert result["items"] == [
        {
            "name": "Blue Lemonade",
            "category": "Drinks",
            "price": "Rs. 250",
            "description": "Butterfly-pea lemonade, lightly sweet.",
            "available": False,
        }
    ]


def test_check_item_availability_handles_a_database_failure(ctx, monkeypatch):
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("database unavailable")

    monkeypatch.setattr(tools.data, "get_menu", fail)
    result = tools.check_item_availability()
    assert result == {"source": "menu", "error": "I couldn't check the menu right now."}


def test_recommend_item_validates_against_the_menu_and_is_not_logged(ctx, monkeypatch):
    def fail_if_logged(*args, **kwargs):
        raise AssertionError("recommend_item must not be logged")

    monkeypatch.setattr(tools.data, "log_action", fail_if_logged)

    assert tools.recommend_item("Pizza", "any reason") == {"error": "That item isn't on the menu."}

    result = tools.recommend_item("Chicken Burger", "  If you're hungry,\n I'd start here. ")
    assert result == {
        "item": "Chicken Burger",
        "price": "Rs. 650",
        "reason": "If you're hungry, I'd start here.",
    }
    assert "source" not in result
    event = _published("recommendation")[0]
    assert event["item"] == "Chicken Burger"
    assert event["session_id"] == ctx["session_id"]

    data.set_menu_availability("Blue Lemonade", False)
    assert tools.recommend_item("Blue Lemonade", "nice") == {
        "error": "That item isn't available right now."
    }


def test_build_order_keeps_one_draft_and_publishes_created_then_updated(ctx):
    first = tools.build_order([{"name": "chicken burger", "quantity": 1}])
    assert first == {
        "source": "order",
        "order_id": first["order_id"],
        "items": [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}],
        "total": "Rs. 650",
        "status": "PENDING_CONFIRMATION",
    }
    assert ctx["pending_order_id"] == first["order_id"]
    assert _published("order_created")[0]["order"]["id"] == first["order_id"]

    second = tools.build_order(
        [{"name": "Chicken Burger", "quantity": 2}, {"name": "Blue Lemonade"}]
    )
    assert second["order_id"] == first["order_id"]
    assert second["total"] == "Rs. 1,550"
    assert len(_pending_rows(ctx["session_id"])) == 1
    assert _published("order_updated")[0]["order"]["items"] == [
        {"name": "Chicken Burger", "quantity": 2, "price": "Rs. 650"},
        {"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"},
    ]

    # Identical items again: no new event, same row.
    before = len(event_bus.PUBLISHED)
    third = tools.build_order(
        [{"name": "Chicken Burger", "quantity": 2}, {"name": "Blue Lemonade"}]
    )
    assert third["order_id"] == first["order_id"]
    assert len(event_bus.PUBLISHED) == before


def test_build_order_rejects_unknown_unavailable_and_empty_items(ctx):
    assert tools.build_order([{"name": "Pizza"}]) == {
        "source": "order",
        "error": "'Pizza' isn't on the menu.",
    }
    data.set_menu_availability("Blue Lemonade", False)
    assert tools.build_order([{"name": "Blue Lemonade"}]) == {
        "source": "order",
        "error": "'Blue Lemonade' isn't available right now.",
    }
    assert tools.build_order([]) == {"source": "order", "error": "I didn't catch any items."}
    assert _pending_rows(ctx["session_id"]) == []


def test_build_order_clamps_quantity_and_takes_a_name(ctx):
    result = tools.build_order(
        [{"name": "Chicken Burger", "quantity": 99}, {"name": "Blue Lemonade", "quantity": "two"}],
        guest_name="  Ahmed  ",
    )
    assert [item["quantity"] for item in result["items"]] == [20, 1]
    assert data.get_order(result["order_id"])["guest_name"] == "Ahmed"


def test_confirm_order_is_idempotent(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]

    confirmed = tools.confirm_order(order_id)
    assert confirmed == {
        "source": "order",
        "order_id": order_id,
        "status": "CONFIRMED",
        "items": [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}],
        "total": "Rs. 650",
    }
    assert ctx["pending_order_id"] is None
    assert _published("order_updated")[0]["order"]["status"] == "CONFIRMED"

    again = tools.confirm_order(order_id)
    assert again == {"source": "order", "error": "That order isn't waiting on confirmation."}
    assert data.get_order(order_id)["status"] == "CONFIRMED"


def test_confirm_order_rejects_bad_numbers_and_other_guests_orders(ctx):
    assert tools.confirm_order("abc") == {
        "source": "order",
        "error": "I couldn't understand that order number.",
    }
    assert tools.confirm_order(4242) == {
        "source": "order",
        "error": "I don't have an order to confirm.",
    }

    stranger = data.create_order_draft(
        [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}], None, "someone-else"
    )["order_id"]
    assert tools.confirm_order(stranger) == {
        "source": "order",
        "error": "I don't have an order to confirm.",
    }
    assert data.get_order(stranger)["status"] == "PENDING_CONFIRMATION"


def test_an_expired_draft_is_cancelled_and_cannot_be_confirmed(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    _backdate(order_id, config.PENDING_ORDER_TTL_S + 30)
    event_bus.PUBLISHED.clear()

    result = tools.confirm_order(order_id)

    assert result == {
        "source": "order",
        "error": "That order expired before it was confirmed. Shall I put it together again?",
    }
    expired = data.get_order(order_id)
    assert expired["status"] == "CANCELLED"
    assert expired["cancel_reason"] == "expired"
    expiry_events = [
        event for event in _published("order_updated") if event["session_id"] is None
    ]
    assert len(expiry_events) == 1
    assert expiry_events[0]["order"]["id"] == order_id


def test_cancel_order_before_ready_only(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    assert tools.cancel_order(order_id, reason="  changed  mind ") == {
        "source": "order",
        "order_id": order_id,
        "status": "CANCELLED",
    }
    assert data.get_order(order_id)["cancel_reason"] == "changed mind"
    assert ctx["pending_order_id"] is None

    ready_id = tools.build_order([{"name": "Club Sandwich"}])["order_id"]
    tools.confirm_order(ready_id)
    data.update_order_status(ready_id, "PREPARING")
    data.update_order_status(ready_id, "READY")
    assert tools.cancel_order(ready_id) == {
        "source": "order",
        "error": "That order can't be cancelled here any more.",
    }
    assert data.get_order(ready_id)["status"] == "READY"
    assert tools.cancel_order(9999) == {"source": "order", "error": "I couldn't find that order."}
    assert tools.cancel_order("abc") == {
        "source": "order",
        "error": "I couldn't understand that order number.",
    }


def test_cancel_order_without_a_reason_stores_null(ctx):
    """09 section 6: no reason given means NULL, never an empty string."""
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.cancel_order(order_id)
    assert data.get_order(order_id)["cancel_reason"] is None

    blank = tools.build_order([{"name": "Club Sandwich"}])["order_id"]
    tools.cancel_order(blank, reason="   ")
    assert data.get_order(blank)["cancel_reason"] is None

    given = tools.build_order([{"name": "Patty Burger"}])["order_id"]
    tools.cancel_order(given, reason="changed mind")
    assert data.get_order(given)["cancel_reason"] == "changed mind"


def test_get_order_status_with_an_id_is_scoped_to_the_owner(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.confirm_order(order_id)

    mine = tools.get_order_status(order_id)
    assert mine["found"] is True
    assert mine["orders"] == [
        {
            "order_id": order_id,
            "status": "CONFIRMED",
            "items": [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}],
            "estimated_minutes_left": None,
        }
    ]

    stranger = data.create_order_draft(
        [{"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}], None, "someone-else"
    )["order_id"]
    data.update_order_status(stranger, "CONFIRMED")
    assert tools.get_order_status(stranger) == {
        "source": "order",
        "found": False,
        "orders": [],
    }
    assert tools.get_order_status("abc")["error"] == "I couldn't understand that order number."


def test_get_order_status_without_an_id_finds_this_sessions_orders(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.confirm_order(order_id)
    data.update_order_status(order_id, "PREPARING")

    result = tools.get_order_status()

    assert result["found"] is True
    assert result["orders"][0]["order_id"] == order_id
    assert result["orders"][0]["estimated_minutes_left"] == 5


def test_get_order_status_finds_an_earlier_order_by_name_in_a_new_session(ctx):
    tools.remember_visitor("Ahmed")
    first = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.confirm_order(first)

    later = {
        "session_id": "ffffffff",
        "visitor_name": None,
        "pending_order_id": None,
        "awaiting_confirmation": False,
    }
    token = tools.SESSION_CTX.set(later)
    try:
        # A different session, before any name is given: nothing of its own.
        assert tools.get_order_status() == {"source": "order", "found": False, "orders": []}
        assert tools.remember_visitor("Ahmed")["returning"] is True
        found = tools.get_order_status()
    finally:
        tools.SESSION_CTX.reset(token)

    assert found["found"] is True
    assert found["orders"][0]["order_id"] == first


def test_report_feedback_stores_only_a_real_rating(ctx):
    result = tools.report_feedback("chicken burger", "  Really   good  ", rating=5)
    assert result["source"] == "order"
    assert result["subject"] == "chicken burger"
    assert result["rating"] == 5

    assert tools.report_feedback("service", "fine", rating=9)["rating"] is None
    assert tools.report_feedback("service", "fine", rating="great")["rating"] is None
    assert tools.report_feedback("", "fine") == {
        "source": "order",
        "error": "I need to know what it's about and what you'd like to say.",
    }


def test_report_feedback_attaches_the_known_visitor_name(ctx):
    tools.remember_visitor("Ahmed")
    feedback_id = tools.report_feedback("service", "quick")["feedback_id"]
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT guest_name FROM feedback WHERE id = ?", (feedback_id,)
        ).fetchone()
    assert row["guest_name"] == "Ahmed"


def test_remember_visitor_counts_visits_and_publishes_identity(ctx):
    first = tools.remember_visitor("  Ahmed  ")
    assert first == {
        "source": "order",
        "returning": False,
        "name": "Ahmed",
        "visits": 1,
        "favorite_item": None,
        "last_order": None,
    }
    assert ctx["visitor_name"] == "Ahmed"
    identified = _published("visitor_identified")[0]
    assert identified["returning"] is False
    assert identified["session_id"] == ctx["session_id"]
    assert _published("memory_updated")[0]["name"] == "Ahmed"

    # The same name again in this session must not count another visit.
    assert tools.remember_visitor("ahmed")["visits"] == 1

    assert tools.remember_visitor("   ") == {"source": "order", "error": "I didn't catch a name."}


def test_remember_visitor_in_a_new_session_counts_a_return(ctx):
    tools.remember_visitor("Ahmed")
    later = {
        "session_id": "99999999",
        "visitor_name": None,
        "pending_order_id": None,
        "awaiting_confirmation": False,
    }
    token = tools.SESSION_CTX.set(later)
    try:
        again = tools.remember_visitor("AHMED")
    finally:
        tools.SESSION_CTX.reset(token)
    assert again["returning"] is True
    assert again["visits"] == 2
    assert again["name"] == "Ahmed"


def test_a_name_given_after_ordering_reaches_the_draft_and_the_profile(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    assert data.get_order(order_id)["guest_name"] is None

    tools.remember_visitor("Sara")

    assert data.get_order(order_id)["guest_name"] == "Sara"
    assert any(
        event["order"]["id"] == order_id and event["order"]["guest_name"] == "Sara"
        for event in _published("order_updated")
    )

    tools.confirm_order(order_id)
    profile = data.get_visitor("sara")
    assert profile["favorite_item"] == "Chicken Burger"
    assert profile["last_order"] == "Chicken Burger"


def test_signal_confirmation_request_is_a_pure_signal(ctx, monkeypatch):
    def fail_if_logged(*args, **kwargs):
        raise AssertionError("signal_confirmation_request must not log")

    monkeypatch.setattr(tools.data, "log_action", fail_if_logged)
    result = tools.signal_confirmation_request("Confirm one chicken burger.")
    assert result == {"acknowledged": True}
    assert "source" not in result
    assert event_bus.PUBLISHED == []


def test_tools_never_touch_awaiting_confirmation(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.signal_confirmation_request("Confirm it?")
    tools.confirm_order(order_id)
    tools.remember_visitor("Ahmed")
    assert ctx["awaiting_confirmation"] is False


def test_get_business_info_found_and_missing(ctx):
    result = tools.get_business_info("hours")
    assert result["source"] == "menu"
    assert result["found"] is True
    assert result["answers"] == [
        {"topic": "hours", "answer": "We're open for the full duration of the gala."}
    ]
    assert len(tools.get_business_info()["answers"]) == 2
    assert tools.get_business_info("parking") == {
        "source": "menu",
        "found": False,
        "answers": [],
    }


def test_request_operator_help_acknowledges_a_trimmed_reason(ctx):
    assert tools.request_operator_help("  guest wants  a refund ") == {
        "source": "order",
        "acknowledged": True,
        "reason": "guest wants a refund",
    }
    assert tools.request_operator_help("")["reason"] == "Help requested"


def test_web_search_parses_an_instant_answer_and_handles_failure(ctx, monkeypatch):
    response = SimpleNamespace(
        text=json.dumps(
            {
                "AbstractText": "Plants convert light into chemical energy.",
                "AbstractURL": "https://example.test/photosynthesis",
            }
        )
    )
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: response)
    result = tools.web_search("photosynthesis")
    assert result["source"] == "web"
    assert result["found"] is True
    assert result["summary"] == "Plants convert light into chemical energy."

    nested = SimpleNamespace(
        text=json.dumps({"RelatedTopics": [{"Topics": [{"Text": "A nested answer."}]}]})
    )
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: nested)
    assert tools.web_search("something")["summary"] == "A nested answer."

    def fail(*args, **kwargs):
        raise httpx.ConnectError("network unavailable")

    monkeypatch.setattr(tools.httpx, "get", fail)
    broken = tools.web_search("photosynthesis")
    assert broken["found"] is False
    assert broken["error"] == "Web lookup is unavailable right now."

    empty = tools.web_search(" ")
    assert empty["found"] is False
    assert empty["error"] == "What should I look up?"


def test_every_published_event_carries_the_envelope_the_bus_owns(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]
    tools.confirm_order(order_id)

    assert [event["type"] for event in event_bus.PUBLISHED] == [
        "order_created",
        "order_updated",
    ]
    for event in event_bus.PUBLISHED:
        assert isinstance(event["event_id"], int)
        assert event["event_id"] >= 1
        assert event["timestamp"]
        assert event["session_id"] == ctx["session_id"]


def test_registries_have_exact_tool_order():
    expected = [
        "check_item_availability",
        "recommend_item",
        "build_order",
        "confirm_order",
        "cancel_order",
        "get_order_status",
        "report_feedback",
        "remember_visitor",
        "signal_confirmation_request",
        "get_business_info",
        "request_operator_help",
        "web_search",
    ]
    assert list(tools.TOOL_FUNCTIONS) == expected
    assert [declaration["name"] for declaration in tools.TOOL_DECLARATIONS] == expected
    for declaration in tools.TOOL_DECLARATIONS:
        assert declaration["behavior"] == "BLOCKING"
        assert declaration["parameters"]["type"] == "object"
    required = {
        declaration["name"]: declaration["parameters"]["required"]
        for declaration in tools.TOOL_DECLARATIONS
    }
    assert required["build_order"] == ["items"]
    assert required["recommend_item"] == ["item", "reason"]
    assert required["get_order_status"] == []
