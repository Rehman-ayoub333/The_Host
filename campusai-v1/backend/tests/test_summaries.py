import json
import sqlite3

import config
import event_bus
import summaries


def activity_rows():
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT event_type, actor, detail FROM system_events ORDER BY id"
            ).fetchall()
        ]


def test_the_label_table_for_every_tool():
    cases = [
        (
            "check_item_availability", {}, {"source": "menu", "total": 1, "items": []},
            {"kind": "order", "label": "Checked menu", "detail": None},
        ),
        (
            "build_order", {}, {"order_id": 27, "status": "PENDING_CONFIRMATION"},
            {"kind": "order", "label": "Order draft #27 prepared", "detail": None},
        ),
        (
            "build_order", {}, {"error": "'Pizza' isn't on the menu."},
            {"kind": "order", "label": "Order could not be prepared", "detail": None},
        ),
        (
            "confirm_order", {},
            {
                "order_id": 27, "status": "CONFIRMED",
                "items": [{"name": "Chicken Burger"}, {"name": "Blue Lemonade"}],
            },
            {
                "kind": "order", "label": "Order #27 created",
                "detail": "Chicken Burger, Blue Lemonade",
            },
        ),
        (
            "confirm_order", {}, {"error": "I couldn't confirm that."},
            {"kind": "order", "label": "Order could not be confirmed", "detail": None},
        ),
        (
            "cancel_order", {"order_id": 27}, {"order_id": 27, "status": "CANCELLED"},
            {"kind": "order", "label": "Order #27 cancelled", "detail": None},
        ),
        (
            "get_order_status", {}, {"found": True, "orders": [{"order_id": 27}]},
            {"kind": "order", "label": "Order #27 checked", "detail": None},
        ),
        (
            "get_order_status", {}, {"found": False, "orders": []},
            {"kind": "order", "label": "Order status checked", "detail": None},
        ),
        (
            "get_order_status", {},
            {"found": True, "orders": [{"order_id": 27}, {"order_id": 28}]},
            {"kind": "order", "label": "Order status checked", "detail": None},
        ),
        (
            "report_feedback", {}, {"feedback_id": 3, "subject": "chicken burger"},
            {"kind": "order", "label": "Feedback logged", "detail": "chicken burger"},
        ),
        (
            "remember_visitor", {},
            {"returning": False, "name": "Sara", "visits": 1},
            {"kind": "visitor", "label": "New visitor noted", "detail": "Sara"},
        ),
        (
            "remember_visitor", {},
            {"returning": True, "name": "Ahmed", "visits": 3},
            {"kind": "visitor", "label": "Visitor identified", "detail": "Ahmed · visit 3"},
        ),
        (
            "get_business_info", {}, {"found": True, "answers": []},
            {"kind": "system", "label": "Checked stall information", "detail": None},
        ),
        (
            "web_search", {}, {"found": True, "summary": "..."},
            {"kind": "system", "label": "Looked something up online", "detail": None},
        ),
        (
            "recommend_item", {}, {"item": "Chicken Burger", "price": "Rs. 650"},
            {"kind": "speech", "label": "Recommended: Chicken Burger", "detail": None},
        ),
        (
            "request_operator_help", {}, {"acknowledged": True, "reason": "wants a refund"},
            {"kind": "operator", "label": "Operator help requested", "detail": "wants a refund"},
        ),
    ]
    for name, args, result, expected in cases:
        actual = summaries.activity_for_tool(name, args, result)
        print(f"{name:26} {result.get('error', 'ok')!r:34} -> {actual}")
        assert actual == expected


def test_signal_confirmation_request_produces_no_activity():
    assert summaries.activity_for_tool("signal_confirmation_request", {"summary": "x"}, {}) is None


def test_an_operator_help_reason_is_cut_to_eighty_characters():
    entry = summaries.activity_for_tool(
        "request_operator_help", {}, {"acknowledged": True, "reason": "x" * 200}
    )
    assert len(entry["detail"]) == 80


def test_emit_activity_logs_a_system_events_row_and_publishes():
    summaries.emit_activity("order", "Order #27 created", "Chicken Burger", "a1b2c3d4")

    rows = activity_rows()
    print("system_events row:", rows[-1])
    assert rows[-1]["event_type"] == "agent_activity"
    assert rows[-1]["actor"] == "system"
    assert json.loads(rows[-1]["detail"]) == {
        "kind": "order",
        "label": "Order #27 created",
        "detail": "Chicken Burger",
    }

    event = event_bus.PUBLISHED[-1]
    print("published event:", event)
    assert event["type"] == "agent_activity"
    assert event["kind"] == "order"
    assert event["label"] == "Order #27 created"
    assert event["detail"] == "Chicken Burger"
    assert event["session_id"] == "a1b2c3d4"
    assert isinstance(event["event_id"], int)


def test_emit_tool_activity_skips_a_tool_with_no_row():
    assert summaries.emit_tool_activity("signal_confirmation_request", {}, {}, "s-1") is None
    assert list(event_bus.PUBLISHED) == []

    entry = summaries.emit_tool_activity(
        "check_item_availability", {}, {"source": "menu", "total": 1}, "s-1"
    )
    assert entry == {"kind": "order", "label": "Checked menu", "detail": None}
    assert len(event_bus.PUBLISHED) == 1
