"""Phase 7l: an order is placed only when it is paid (16 section 2zf item 3).

Rehman's rule is short: the kitchen gets an order after the money, not before.
So a draft that is not on the house now stops at AWAITING_PAYMENT carrying the
method the guest named, the team marks it paid on the dashboard, and only that
press sends it to the kitchen -- and tells THE HOST to say so.

Everything that protects money is tested here against the real code paths: the
status machine, the two tools, the operator endpoint, the sweeper that cancels
an order nobody paid for, and the guards that still require the guest's own
words first.
"""

import asyncio
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import config
import data
import event_bus
import live_session
import main
import prompts
import summaries
import tools

import doubles
from doubles import new_session


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


def placed(ctx, items=BURGER, name="Ali", method="cash", complimentary=None):
    """A draft built and placed the way THE HOST places one."""
    draft = tools.build_order(items, guest_name=name, complimentary=complimentary)
    return tools.confirm_order(draft["order_id"], payment_method=method)


def statuses_of(order_id):
    return data.get_order(order_id)["status"]


def backdate(order_id, seconds):
    """Age an order in this test's own throwaway database, as test_data does."""
    stamp = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stamp, order_id))
        conn.commit()


# ------------------------------------- item 3(a): the status and its transitions


def test_awaiting_payment_is_a_status_with_its_own_wording():
    assert "AWAITING_PAYMENT" in data.ORDER_STATUSES
    assert data.STATUS_TEXT["AWAITING_PAYMENT"] == "waiting for payment at the counter"


def test_a_draft_may_go_to_awaiting_payment_or_straight_to_confirmed():
    assert data.ALLOWED_TRANSITIONS["PENDING_CONFIRMATION"] == (
        "AWAITING_PAYMENT",
        "CONFIRMED",
        "CANCELLED",
        "REQUIRES_ATTENTION",
    )


def test_an_unpaid_order_can_only_be_paid_cancelled_or_handed_to_the_team():
    assert data.ALLOWED_TRANSITIONS["AWAITING_PAYMENT"] == (
        "CONFIRMED",
        "CANCELLED",
        "REQUIRES_ATTENTION",
    )


def test_the_kitchen_cannot_start_on_an_order_that_is_not_paid(ctx):
    order_id = placed(ctx)["order_id"]

    refused = data.update_order_status(order_id, "PREPARING")

    assert refused["ok"] is False
    assert refused["error"] == (
        "Order is AWAITING_PAYMENT; mark it CONFIRMED before PREPARING."
    )
    assert statuses_of(order_id) == "AWAITING_PAYMENT"


def test_an_unpaid_order_is_active_and_counts_towards_a_favourite(ctx):
    """It is a placed order: the Orders panel shows it, and memory counts it."""
    assert "AWAITING_PAYMENT" in data.ACTIVE_STATUSES
    assert "AWAITING_PAYMENT" in data.CONFIRMED_OR_LATER


# --------------------------------------------------- item 3(d): the migration


def test_paid_at_is_added_to_a_database_from_an_earlier_phase(tmp_path, monkeypatch):
    old = tmp_path / "old.db"
    with closing(sqlite3.connect(old)) as conn:
        conn.execute(
            """CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                guest_name TEXT,
                items TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING_CONFIRMATION',
                announced INTEGER NOT NULL DEFAULT 0,
                session_id TEXT,
                cancel_reason TEXT,
                estimated_ready_at TEXT,
                ready_at TEXT,
                orphaned_at TEXT,
                complimentary INTEGER NOT NULL DEFAULT 0,
                payment_method TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO orders (timestamp, guest_name, items, status, payment_method) "
            "VALUES ('2026-10-20T19:00:00', 'Ali', ?, 'COLLECTED', 'CASH')",
            (json.dumps([{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}]),),
        )
        conn.commit()
    monkeypatch.setattr(config, "DB_PATH", old)

    data.init_db()

    order = data.get_order(1)
    # 16 §2zf item 3(d): an order already past CONFIRMED with a payment_method
    # keeps a NULL paid_at -- its payment was never timed, and a made-up time
    # would be invented history.
    assert order["status"] == "COLLECTED"
    assert order["payment_method"] == "CASH"
    assert order["paid_at"] is None


def test_the_order_view_carries_paid_at(ctx):
    order_id = placed(ctx)["order_id"]

    view = data.order_view(data.get_order(order_id))

    assert view["status"] == "AWAITING_PAYMENT"
    assert view["payment_method"] == "CASH"
    assert view["paid_at"] is None


# -------------------------------------------- item 3(b): confirm_order places it


def test_confirm_order_with_cash_places_the_order_and_waits_for_the_money(ctx):
    result = placed(ctx, method="cash")

    assert result["status"] == "AWAITING_PAYMENT"
    assert result["payment_method"] == "CASH"
    assert result["total"] == "Rs. 650"
    assert "error" not in result
    stored = data.get_order(result["order_id"])
    assert stored["status"] == "AWAITING_PAYMENT"
    assert stored["payment_method"] == "CASH"
    assert stored["paid_at"] is None


@pytest.mark.parametrize("said", ["QR", "qr", "Online", "ONLINE"])
def test_qr_and_online_both_mean_the_qr_code(ctx, said):
    result = placed(ctx, method=said)

    assert result["payment_method"] == "QR"


@pytest.mark.parametrize("said", ["CASH", "cash", "Cash"])
def test_cash_is_read_whatever_the_case(ctx, said):
    assert placed(ctx, method=said)["payment_method"] == "CASH"


def test_an_order_with_no_payment_answer_is_not_placed_at_all(ctx):
    draft = tools.build_order(BURGER, guest_name="Ali")

    result = tools.confirm_order(draft["order_id"])

    assert result == {"source": "order", "error": "Ask the guest: cash or QR?"}
    # Nothing changed: it is still a draft, and it can still be placed.
    assert statuses_of(draft["order_id"]) == "PENDING_CONFIRMATION"
    assert data.get_order(draft["order_id"])["payment_method"] is None


def test_a_payment_word_that_is_not_cash_or_qr_is_treated_as_no_answer(ctx):
    draft = tools.build_order(BURGER, guest_name="Ali")

    result = tools.confirm_order(draft["order_id"], payment_method="card")

    assert result["error"] == "Ask the guest: cash or QR?"
    assert statuses_of(draft["order_id"]) == "PENDING_CONFIRMATION"


def test_the_chief_guest_is_placed_without_being_asked_how_they_will_pay(ctx):
    draft = tools.build_order(BURGER, guest_name="Chief Guest")

    result = tools.confirm_order(draft["order_id"])

    assert result["status"] == "AWAITING_PAYMENT"
    assert result["payment_method"] is None
    assert "error" not in result
    # And never on the house: 2ze item 3 is unchanged by pay-first.
    assert data.get_order(draft["order_id"])["complimentary"] == 0


def test_the_vice_chancellor_goes_straight_to_the_kitchen_and_is_never_asked(ctx):
    """E52: no payment question, CONFIRMED at once, on the house."""
    draft = tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)

    result = tools.confirm_order(draft["order_id"])

    assert result["status"] == "CONFIRMED"
    assert result["payment_method"] is None
    assert result["complimentary"] is True
    assert statuses_of(draft["order_id"]) == "CONFIRMED"


def test_a_payment_method_sent_with_a_complimentary_order_is_ignored(ctx):
    draft = tools.build_order(LEMONADE, guest_name="Dr. Rauf-i-Azam", complimentary=True)

    result = tools.confirm_order(draft["order_id"], payment_method="CASH")

    assert result["status"] == "CONFIRMED"
    assert result["payment_method"] is None
    assert data.get_order(draft["order_id"])["payment_method"] is None


def test_the_tool_declaration_offers_cash_or_qr_and_does_not_demand_it():
    declaration = next(
        item for item in tools.TOOL_DECLARATIONS if item["name"] == "confirm_order"
    )
    field = declaration["parameters"]["properties"]["payment_method"]

    assert field["enum"] == ["CASH", "QR"]
    assert declaration["parameters"]["required"] == ["order_id"]


# ------------------------------------------------- item 3(d): marking it paid


def test_marking_an_unpaid_order_paid_needs_cash_or_qr(served, ctx):
    order_id = placed(ctx)["order_id"]

    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": "CONFIRMED"}, headers=AUTH
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Choose Cash or QR."
    assert statuses_of(order_id) == "AWAITING_PAYMENT"


def test_marking_it_paid_stores_the_method_and_the_time(served, ctx):
    order_id = placed(ctx, method="cash")["order_id"]

    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert response.status_code == 200
    order = response.json()["order"]
    assert order["status"] == "CONFIRMED"
    assert order["payment_method"] == "CASH"
    assert order["paid_at"] is not None


def test_the_team_may_take_a_different_payment_from_the_one_the_guest_named(served, ctx):
    """2zf item 3(d): the guest said cash and paid by QR at the counter."""
    order_id = placed(ctx, method="cash")["order_id"]

    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "QR"},
        headers=AUTH,
    )

    assert data.get_order(order_id)["payment_method"] == "QR"


def test_the_payment_gets_its_own_activity_row(served, ctx, monkeypatch):
    rows = []
    monkeypatch.setattr(
        summaries,
        "emit_activity",
        lambda kind, label, detail=None, session_id=None: rows.append(label),
    )
    order_id = placed(ctx, method="qr")["order_id"]

    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "QR"},
        headers=AUTH,
    )

    assert f"Order #{order_id} paid (QR)" in rows


def test_a_cash_payment_says_cash_in_the_feed(served, ctx, monkeypatch):
    rows = []
    monkeypatch.setattr(
        summaries,
        "emit_activity",
        lambda kind, label, detail=None, session_id=None: rows.append(label),
    )
    order_id = placed(ctx, method="cash")["order_id"]

    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert f"Order #{order_id} paid (cash)" in rows


def test_an_order_on_the_house_never_takes_a_payment(served, ctx):
    draft = tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)
    tools.confirm_order(draft["order_id"])

    response = served.post(
        f"/api/orders/{draft['order_id']}/status",
        json={"status": "PREPARING", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Payment is recorded at collection."


def test_a_payment_type_is_refused_on_a_status_that_is_not_a_payment(served, ctx):
    order_id = placed(ctx)["order_id"]
    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "PREPARING", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Payment is recorded at collection."


# -------------------------------------- item 3(h): collection is one button again


def test_a_paid_order_is_collected_with_one_press(served, ctx):
    order_id = placed(ctx, method="cash")["order_id"]
    for body in (
        {"status": "CONFIRMED", "payment_method": "CASH"},
        {"status": "PREPARING"},
        {"status": "READY"},
    ):
        served.post(f"/api/orders/{order_id}/status", json=body, headers=AUTH)

    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )

    assert response.status_code == 200
    collected = response.json()["order"]
    assert collected["status"] == "COLLECTED"
    # The payment is already on the order, which is why one button is enough.
    assert collected["payment_method"] == "CASH"


def test_an_order_with_no_payment_at_all_still_cannot_be_collected(served):
    """The 7k rule holds for anything that reached READY the old way."""
    draft = data.create_order_draft(
        [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}],
        "Ali",
        "session-old",
    )
    order_id = draft["order_id"]
    for step in ("CONFIRMED", "PREPARING", "READY"):
        data.update_order_status(order_id, step)

    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Choose Cash or QR."


# ------------------------------------------- item 3(f): nobody came to the counter


def test_an_order_nobody_paid_for_is_cancelled_as_unpaid(ctx):
    order_id = placed(ctx)["order_id"]
    backdate(order_id, config.PAYMENT_TTL_S + 30)

    cancelled = data.expire_unpaid_orders()

    assert cancelled == [order_id]
    order = data.get_order(order_id)
    assert order["status"] == "CANCELLED"
    assert order["cancel_reason"] == "unpaid"


def test_a_fresh_unpaid_order_is_left_alone(ctx):
    order_id = placed(ctx)["order_id"]

    assert data.expire_unpaid_orders() == []
    assert statuses_of(order_id) == "AWAITING_PAYMENT"


def test_the_expiry_publishes_the_order_so_both_screens_see_it(ctx):
    order_id = placed(ctx)["order_id"]
    backdate(order_id, config.PAYMENT_TTL_S + 30)
    event_bus.PUBLISHED.clear()

    data.expire_unpaid_orders()

    updates = [
        event
        for event in event_bus.PUBLISHED
        if event["type"] == "order_updated" and event["order"]["id"] == order_id
    ]
    assert updates and updates[-1]["order"]["status"] == "CANCELLED"


def test_a_paid_order_is_never_swept(served, ctx):
    order_id = placed(ctx, method="cash")["order_id"]
    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )
    backdate(order_id, config.PAYMENT_TTL_S + 30)

    assert data.expire_unpaid_orders() == []
    assert statuses_of(order_id) == "CONFIRMED"


def test_the_ttl_is_ten_minutes():
    assert config.PAYMENT_TTL_S == 600


# ------------------------------------------- item 3(g): cancelling by voice


def test_the_guest_can_cancel_an_order_that_is_still_waiting_for_payment(ctx):
    order_id = placed(ctx)["order_id"]

    result = tools.cancel_order(order_id)

    assert result["status"] == "CANCELLED"
    assert statuses_of(order_id) == "CANCELLED"


def test_a_paid_order_is_the_teams_to_undo(ctx, served):
    order_id = placed(ctx, method="cash")["order_id"]
    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    result = tools.cancel_order(order_id)

    assert result == {
        "source": "order",
        "error": "That order is already paid — the team can help.",
    }
    assert statuses_of(order_id) == "CONFIRMED"


@pytest.mark.parametrize("status", ["PREPARING", "READY"])
def test_an_order_in_the_kitchen_gets_the_same_answer(ctx, served, status):
    order_id = placed(ctx, method="cash")["order_id"]
    for body in (
        {"status": "CONFIRMED", "payment_method": "CASH"},
        {"status": "PREPARING"},
        {"status": "READY"},
    ):
        served.post(f"/api/orders/{order_id}/status", json=body, headers=AUTH)
        if body["status"] == status:
            break

    result = tools.cancel_order(order_id)

    assert result["error"] == "That order is already paid — the team can help."
    assert statuses_of(order_id) == status


def test_a_draft_is_still_cancelled_by_voice(ctx):
    draft = tools.build_order(BURGER, guest_name="Ali")

    assert tools.cancel_order(draft["order_id"])["status"] == "CANCELLED"


def test_the_operator_can_still_cancel_a_paid_order(served, ctx):
    order_id = placed(ctx, method="cash")["order_id"]
    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": "CANCELLED"}, headers=AUTH
    )

    assert response.status_code == 200
    assert statuses_of(order_id) == "CANCELLED"


# ------------------------------------ item 3(c): a payment answer is a consent


@pytest.mark.parametrize("word", ["cash", "QR", "online", "scan"])
def test_the_payment_words_count_as_the_guests_own_yes(word):
    assert live_session.has_affirmative(f"{word}, please") is True


def test_a_payment_word_inside_another_word_is_not_a_yes():
    assert live_session.has_affirmative("cashew nuts") is False
    assert live_session.has_affirmative("scanner") is False


def test_a_confirm_in_the_same_turn_as_the_build_is_still_refused(ctx):
    session, _ = new_session()
    session.ctx = dict(ctx)
    session.draft_built_id = 7
    session.draft_built_at = live_session._now()

    assert session._confirm_refusal({"order_id": 7}) == "no_new_line"


def test_a_cash_answer_after_the_build_lets_the_order_through(ctx):
    session, _ = new_session()
    session.ctx = dict(ctx)
    session.draft_built_id = 7
    session.draft_built_at = live_session._now()
    session._note_guest_line("Cash.")

    assert session._confirm_refusal({"order_id": 7}) is None


def test_the_cancel_guard_now_watches_an_order_waiting_for_payment(ctx):
    order_id = placed(ctx)["order_id"]
    session, _ = new_session()
    session.ctx = dict(ctx)
    session.confirmed_at[order_id] = live_session._now()

    assert asyncio.run(session._cancel_refusal({"order_id": order_id})) == "no_new_line"

    session._note_guest_line("Cancel it.")
    assert asyncio.run(session._cancel_refusal({"order_id": order_id})) is None


def test_a_line_with_no_consent_still_refuses_a_cancel(ctx):
    order_id = placed(ctx)["order_id"]
    session, _ = new_session()
    session.ctx = dict(ctx)
    session.confirmed_at[order_id] = live_session._now()
    session._note_guest_line("What is in it?")

    assert asyncio.run(session._cancel_refusal({"order_id": order_id})) == "no_consent"


# ------------------------------------ item 3(e): THE HOST is told it is paid


def test_the_payment_template_names_the_order():
    text = prompts.PAYMENT_TEMPLATE.format(order_id=12)

    assert text == (
        "Order #12 has just been paid. Tell the guest in one short line that it "
        "is paid and the kitchen is on it."
    )


def test_the_line_is_sent_at_once_when_nothing_is_in_the_way():
    session, _ = new_session()
    session.turn_in_progress = False

    asyncio.run(session.inject("payment", "Order #3 has just been paid."))

    assert session.session.inputs == [{"text": "Order #3 has just been paid."}]
    assert session.pending_injections == []


def test_the_line_waits_while_the_host_is_speaking():
    session, _ = new_session()
    session.turn_in_progress = True

    asyncio.run(session.inject("payment", "Order #3 has just been paid."))

    assert session.session.inputs == []
    assert session.pending_injections == [
        {"kind": "payment", "text": "Order #3 has just been paid."}
    ]


def test_a_deferred_line_leaves_at_the_end_of_the_turn():
    session, _ = new_session()
    session.turn_in_progress = True

    async def go():
        await session.inject("payment", "Order #3 has just been paid.")
        session._cancel_announce_watcher()
        await session._end_of_turn()

    asyncio.run(go())

    assert session.session.inputs == [{"text": "Order #3 has just been paid."}]
    assert session.pending_injections == []


def test_a_ready_order_is_announced_before_a_paid_order_line():
    session, _ = new_session()
    session.turn_in_progress = True

    async def go():
        await session.inject("payment", "Order #3 has just been paid.")
        session._defer_announcement({"id": 9, "guest_name": "Ali"})
        session._cancel_announce_watcher()
        await session._end_of_turn()

    asyncio.run(go())

    assert session.session.inputs == [
        {"text": prompts.ANNOUNCE_TEMPLATE.format(order_id=9, name=" for Ali")}
    ]
    assert session.pending_injections


def test_the_session_knows_which_orders_are_this_guests():
    session, _ = new_session()
    session.ctx["session_id"] = "abc123"
    session.ctx["visitor_name"] = "Rehman"

    assert session.owns_order({"session_id": "abc123", "guest_name": None}) is True
    assert session.owns_order({"session_id": "other", "guest_name": "rehman"}) is True
    assert session.owns_order({"session_id": "other", "guest_name": "Saad"}) is False


def test_marking_it_paid_speaks_to_the_guest_whose_order_it_is(served, ctx, monkeypatch):
    spoken = []

    class Listening:
        def owns_order(self, order):
            return True

        async def inject(self, kind, text):
            spoken.append((kind, text))

    order_id = placed(ctx, method="cash")["order_id"]
    monkeypatch.setattr(main, "ACTIVE", Listening())

    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert spoken == [
        ("payment", prompts.PAYMENT_TEMPLATE.format(order_id=order_id))
    ]


def test_another_guests_order_is_never_spoken_about(served, ctx, monkeypatch):
    spoken = []

    class Listening:
        def owns_order(self, order):
            return False

        async def inject(self, kind, text):
            spoken.append(text)

    order_id = placed(ctx, method="cash")["order_id"]
    monkeypatch.setattr(main, "ACTIVE", Listening())

    served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert spoken == []


def test_nothing_is_spoken_when_no_conversation_is_running(served, ctx, monkeypatch):
    monkeypatch.setattr(main, "ACTIVE", None)
    order_id = placed(ctx, method="cash")["order_id"]

    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "CONFIRMED", "payment_method": "CASH"},
        headers=AUTH,
    )

    assert response.status_code == 200


def test_no_guest_words_reach_the_log(ctx, caplog):
    """The guard logs a reason and an order number, never a line of speech."""
    order_id = placed(ctx)["order_id"]
    backdate(order_id, config.PAYMENT_TTL_S + 30)
    with caplog.at_level("INFO"):
        data.expire_unpaid_orders()

    for record in caplog.records:
        assert "Cash" not in record.getMessage()


# --------------------------------- item 1(b): complimentary is no longer sticky


def test_a_renamed_draft_loses_the_house(ctx):
    """16 §2zf item 1(b), amending 2m item 5: every build decides it again."""
    first = tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)
    assert data.get_order(first["order_id"])["complimentary"] == 1

    again = tools.build_order(LEMONADE, guest_name="Ali", complimentary=True)

    assert again["order_id"] == first["order_id"]
    assert data.get_order(first["order_id"])["complimentary"] == 0
    assert again["complimentary"] is False
    assert again["note"] == tools.COMPLIMENTARY_NOTE


def test_a_draft_rebuilt_without_the_flag_is_no_longer_on_the_house(ctx):
    first = tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)

    tools.build_order(LEMONADE, guest_name="Vice Chancellor")

    assert data.get_order(first["order_id"])["complimentary"] == 0


def test_the_vice_chancellors_draft_stays_on_the_house_while_it_is_asked_for(ctx):
    first = tools.build_order(BURGER, guest_name="Vice Chancellor", complimentary=True)

    again = tools.build_order(
        BURGER + LEMONADE, guest_name="Vice Chancellor", complimentary=True
    )

    assert again["order_id"] == first["order_id"]
    assert data.get_order(first["order_id"])["complimentary"] == 1
    assert again["complimentary"] is True


def test_a_draft_renamed_to_the_vice_chancellor_becomes_on_the_house(ctx):
    """E41: the name arrives after the items."""
    first = tools.build_order(LEMONADE)

    again = tools.build_order(
        LEMONADE, guest_name="Dr. Rauf-i-Azam", complimentary=True
    )

    assert again["order_id"] == first["order_id"]
    assert data.get_order(first["order_id"])["complimentary"] == 1
