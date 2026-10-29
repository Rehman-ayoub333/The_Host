"""Phase 7n: the guest's order number (16 section 2zi item 3).

Rehman asked for orders numbered 1, 2, 3 at the gala. Order ids come from
SQLite and every draft takes one, so a guest who changed their mind twice
pushed the next real order to 5 -- and a fresh database still showed gaps. The
number is given out when an order is PLACED, which is the only moment the
guest is told something to remember.

Item 3(e) names each case below.
"""

import csv
import io
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import config
import data
import event_bus
import main
import prompts
import tools


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}

BURGER = [{"name": "Chicken Burger", "quantity": 1}]
LEMONADE = [{"name": "Blue Lemonade", "quantity": 1}]


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


def place(items=BURGER, name="Ali", method="cash", complimentary=None):
    """A draft built and placed the way THE HOST places one."""
    draft = tools.build_order(items, guest_name=name, complimentary=complimentary)
    return tools.confirm_order(draft["draft_id"], payment_method=method)


def number_of(order_id):
    return data.get_order(order_id)["order_no"]


def backdate_a_day(order_id):
    stamp = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stamp, order_id))
        conn.commit()


# ------------------------------------ item 3(a): drafts do not consume numbers


def test_two_cancelled_drafts_then_the_placed_orders_get_one_and_two(ctx):
    """16 §2zi item 3(e), the case Rehman saw: 1, 2, 5 on a fresh database."""
    first_draft = tools.build_order(BURGER, guest_name="Ali")["draft_id"]
    tools.cancel_order(draft_id=first_draft)
    second_draft = tools.build_order(LEMONADE, guest_name="Ali")["draft_id"]
    tools.cancel_order(draft_id=second_draft)

    one = place(BURGER, name="Sara")
    two = place(LEMONADE, name="Umair")

    assert one["order_number"] == 1
    assert two["order_number"] == 2
    # The internal ids really did move on, which is the whole point.
    assert one["draft_id"] > second_draft


def test_a_draft_has_no_number_at_all(ctx):
    draft = tools.build_order(BURGER, guest_name="Ali")

    assert "order_number" not in draft
    assert draft["draft"] is True
    assert number_of(draft["draft_id"]) is None


def test_numbers_follow_the_order_of_placing_not_of_drafting(ctx):
    """Two drafts open at once: the one placed first is number 1."""
    first = tools.build_order(BURGER, guest_name="Ali")["draft_id"]
    second = data.create_order_draft(
        [{"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}],
        "Sara",
        "another-session",
    )["order_id"]
    assert second > first

    data.update_order_status(second, "AWAITING_PAYMENT", payment_method="CASH")
    placed_first_draft = tools.confirm_order(first, payment_method="CASH")

    assert number_of(second) == 1
    assert placed_first_draft["order_number"] == 2


def test_an_order_on_the_house_gets_a_number(ctx):
    """It never waits for payment, so it is numbered on its way to the kitchen."""
    free = place(BURGER, name="Vice Chancellor", complimentary=True)

    assert free["status"] == "CONFIRMED"
    assert free["order_number"] == 1
    assert free["complimentary"] is True


def test_a_number_is_never_reused_once_it_is_given_out(ctx):
    one = place(BURGER, name="Ali")
    tools.cancel_order(order_number=one["order_number"])

    two = place(LEMONADE, name="Sara")

    # Cancelling number 1 does not hand number 1 to the next guest.
    assert two["order_number"] == 2


def test_a_number_never_changes_once_it_is_given(ctx, served):
    order_id = place(BURGER, name="Ali")["draft_id"]
    given = number_of(order_id)

    for status in ("CONFIRMED", "PREPARING", "READY", "COLLECTED"):
        body = {"status": status}
        if status == "CONFIRMED":
            body["payment_method"] = "CASH"
        served.post(f"/api/orders/{order_id}/status", json=body, headers=AUTH)
        assert number_of(order_id) == given


def test_a_new_day_starts_at_one(ctx):
    yesterday = place(BURGER, name="Ali")
    assert yesterday["order_number"] == 1
    backdate_a_day(yesterday["draft_id"])

    today = place(LEMONADE, name="Sara")

    assert today["order_number"] == 1


def test_an_order_from_before_this_phase_has_no_number_and_pushes_nothing(ctx):
    """The migration leaves old rows NULL, so they cannot move the count."""
    legacy = data.create_order_draft(
        [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}],
        "Ali",
        "old-session",
    )["order_id"]
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute(
            "UPDATE orders SET status = 'COLLECTED', order_no = NULL WHERE id = ?",
            (legacy,),
        )
        conn.commit()

    assert place(BURGER, name="Sara")["order_number"] == 1


# ------------------------------------------- item 3(b): what a person sees


def test_the_order_view_carries_the_number_and_null_for_a_draft(ctx):
    draft_id = tools.build_order(BURGER, guest_name="Ali")["draft_id"]
    assert data.order_view(data.get_order(draft_id))["number"] is None

    tools.confirm_order(draft_id, payment_method="CASH")

    view = data.order_view(data.get_order(draft_id))
    assert view["number"] == 1
    # The internal id is still there: the operator API keys on it (item 3(d)).
    assert view["id"] == draft_id


def test_the_ready_event_carries_the_number(ctx, served):
    order_id = place(BURGER, name="Ali")["draft_id"]
    for status, extra in (
        ("CONFIRMED", {"payment_method": "CASH"}),
        ("PREPARING", {}),
        ("READY", {}),
    ):
        served.post(
            f"/api/orders/{order_id}/status",
            json={"status": status, **extra},
            headers=AUTH,
        )

    ready = [event for event in event_bus.PUBLISHED if event["type"] == "order_ready"]
    assert ready and ready[-1]["order_number"] == 1
    # order_id stays for the dashboard, which keys on it (item 3(d)).
    assert ready[-1]["order_id"] == order_id


def test_the_csv_leads_with_the_order_number(ctx, served):
    order_id = place(BURGER, name="Ali")["draft_id"]

    rows = list(
        csv.reader(io.StringIO(served.get("/api/earnings.csv", headers=AUTH).text))
    )

    assert rows[0][0] == "order_no"
    assert rows[0][1] == "order_id"
    assert rows[1][0] == "1"
    assert rows[1][1] == str(order_id)


def test_no_internal_id_reaches_a_spoken_template(ctx):
    """16 §2zi item 3(e): the announcement and the payment line use the number."""
    number = place(BURGER, name="Ali")["order_number"]

    announcement = prompts.ANNOUNCE_TEMPLATE.format(
        order_number=number, name=" for Ali"
    )
    payment = prompts.PAYMENT_TEMPLATE.format(order_number=number)

    assert f"order #{number}" in announcement
    assert f"Order #{number}" in payment
    assert "order_id" not in prompts.ANNOUNCE_TEMPLATE
    assert "order_id" not in prompts.PAYMENT_TEMPLATE


def test_the_activity_feed_says_draft_before_it_says_a_number(ctx):
    import summaries

    draft = tools.build_order(BURGER, guest_name="Ali")
    drafted = summaries.activity_for_tool("build_order", {}, draft)
    assert drafted["label"] == "Draft prepared"

    placed = tools.confirm_order(draft["draft_id"], payment_method="CASH")
    created = summaries.activity_for_tool("confirm_order", {}, placed)

    assert created["label"] == "Order #1 created"


# ------------------------------------ item 3(c): the tools map both directions


def test_build_order_returns_a_draft_id_and_confirm_order_a_number(ctx):
    draft = tools.build_order(BURGER, guest_name="Ali")
    assert set(draft) >= {"draft_id", "draft", "items", "total", "status"}
    assert "order_id" not in draft

    placed = tools.confirm_order(draft["draft_id"], payment_method="CASH")

    assert placed["order_number"] == 1
    assert placed["draft_id"] == draft["draft_id"]
    assert "order_id" not in placed


def test_get_order_status_takes_the_number_a_guest_can_say(ctx):
    place(BURGER, name="Ali")

    found = tools.get_order_status(order_number=1)

    assert found["found"] is True
    assert found["orders"][0]["order_number"] == 1
    assert "order_id" not in found["orders"][0]


def test_cancel_order_takes_a_number_for_a_placed_order(ctx):
    place(BURGER, name="Ali")

    result = tools.cancel_order(order_number=1)

    assert result == {"source": "order", "status": "CANCELLED", "order_number": 1}


def test_cancel_order_takes_a_draft_id_for_a_draft(ctx):
    draft_id = tools.build_order(BURGER, guest_name="Ali")["draft_id"]

    result = tools.cancel_order(draft_id=draft_id)

    assert result == {
        "source": "order",
        "status": "CANCELLED",
        "draft": True,
        "draft_id": draft_id,
    }


def test_an_unreadable_identifier_is_answered_not_crashed(ctx):
    for call in (
        lambda: tools.cancel_order(order_number="abc"),
        lambda: tools.cancel_order(draft_id="abc"),
        lambda: tools.get_order_status(order_number="abc"),
    ):
        assert call()["error"] == "I couldn't understand that order number."


def test_yesterdays_number_is_not_this_guests_order(ctx):
    """Numbers restart daily, so the date is part of the lookup."""
    order_id = place(BURGER, name="Ali")["draft_id"]
    backdate_a_day(order_id)

    assert data.get_order_by_number(1) is None
    assert tools.get_order_status(order_number=1)["found"] is False


def test_another_guests_number_still_reveals_nothing(ctx):
    """The ownership rule of 09 section 6 is unchanged by the new argument."""
    stranger = data.create_order_draft(
        [{"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}],
        "Someone",
        "someone-else",
    )["order_id"]
    data.update_order_status(stranger, "AWAITING_PAYMENT", payment_method="CASH")

    assert number_of(stranger) == 1
    assert tools.get_order_status(order_number=1) == {
        "source": "order",
        "found": False,
        "orders": [],
    }
    assert tools.cancel_order(order_number=1)["error"] == "I couldn't find that order."


def test_the_declarations_name_the_new_arguments(ctx):
    by_name = {item["name"]: item for item in tools.TOOL_DECLARATIONS}

    confirm = by_name["confirm_order"]["parameters"]
    assert set(confirm["properties"]) == {"draft_id", "payment_method"}
    assert confirm["required"] == ["draft_id"]

    cancel = by_name["cancel_order"]["parameters"]
    assert set(cancel["properties"]) == {"order_number", "draft_id", "reason"}
    # Either one identifies an order, so neither is required on its own.
    assert cancel["required"] == []

    status = by_name["get_order_status"]["parameters"]
    assert set(status["properties"]) == {"order_number", "guest_name"}
