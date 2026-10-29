"""Phase 7j: the money (16 section 2z), so there is no confusion at the end of the day.

Rehman wants to see exactly what the orders brought in and from where. The
figures are computed on request from each order's own stored prices, so a later
menu change never alters history, and a draft is never counted: nothing was
ordered until the guest said yes.

Operator only. Nothing here reaches /display, and THE HOST has no tool for it.
"""

import csv
import io
import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import data
import event_bus
import main


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}

BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}
LEMONADE = {"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}
SHAKE = {"name": "Mixed Fruit Shake", "quantity": 1, "price": "Rs. 350"}


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    with TestClient(main.app) as client:
        yield client


def order(items, status=None, complimentary=False, name="Ali", payment=None):
    """One order in the database, advanced to `status` the ordinary way.

    16 section 2zf item 3: with pay-first a real order reaches CONFIRMED
    through AWAITING_PAYMENT, and `payment` is what the team marked it paid
    with. The old route -- straight to CONFIRMED and a payment at COLLECTED --
    is what an order from before this phase looks like, so it is kept here
    under `legacy=True` and is the only thing `earned_unrecorded` can mean.
    """
    draft = data.create_order_draft(items, name, "session-1", complimentary=complimentary)
    order_id = draft["order_id"]
    for step in {
        None: (),
        "AWAITING_PAYMENT": ("AWAITING_PAYMENT",),
        "CONFIRMED": ("AWAITING_PAYMENT", "CONFIRMED"),
        "PREPARING": ("AWAITING_PAYMENT", "CONFIRMED", "PREPARING"),
        "READY": ("AWAITING_PAYMENT", "CONFIRMED", "PREPARING", "READY"),
        "COLLECTED": (
            "AWAITING_PAYMENT", "CONFIRMED", "PREPARING", "READY", "COLLECTED",
        ),
        "CANCELLED": ("CANCELLED",),
    }[status]:
        if step == "CONFIRMED" and not complimentary:
            data.update_order_status(order_id, step, payment_method=payment or "CASH")
        else:
            data.update_order_status(order_id, step)
    return order_id


def legacy_order(items, status, complimentary=False, name="Ali", payment=None):
    """An order as it looked before pay-first: no payment step, no `paid_at`."""
    draft = data.create_order_draft(items, name, "session-old", complimentary=complimentary)
    order_id = draft["order_id"]
    for step in {
        "CONFIRMED": ("CONFIRMED",),
        "READY": ("CONFIRMED", "PREPARING", "READY"),
        "COLLECTED": ("CONFIRMED", "PREPARING", "READY", "COLLECTED"),
    }[status]:
        if step == "COLLECTED" and payment is not None:
            data.update_order_status(order_id, step, payment_method=payment)
        else:
            data.update_order_status(order_id, step)
    return order_id


def paid_then_cancelled(items, name="Ali", payment="CASH"):
    """The operator cancels an order the guest had already paid for."""
    order_id = order(items, "CONFIRMED", name=name, payment=payment)
    data.update_order_status(order_id, "CANCELLED", reason="operator")
    return order_id


# --------------------------------------------- 2z item 2: the column and the API


def test_the_migration_adds_payment_method(tmp_path, monkeypatch):
    """A database from an earlier phase gains the column, NULL on every row."""
    db_path = tmp_path / "old.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    with closing(sqlite3.connect(db_path)) as conn:
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
                ready_at TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO orders (timestamp, items, status) VALUES (?, ?, 'COLLECTED')",
            (data._now(), json.dumps([BURGER])),
        )
        conn.commit()

    data.init_db()

    with closing(sqlite3.connect(db_path)) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
        print("columns after the migration:", sorted(columns))
        assert "payment_method" in columns
        stored = conn.execute("SELECT payment_method FROM orders").fetchone()[0]
    assert stored is None


@pytest.mark.parametrize("method", ["CASH", "QR"])
def test_collected_with_a_payment_method_is_stored_and_published(served, method):
    order_id = legacy_order([BURGER], "READY")
    event_bus.PUBLISHED.clear()

    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "COLLECTED", "payment_method": method},
        headers=AUTH,
    )

    print(method, "->", response.status_code, response.json())
    assert response.status_code == 200
    assert response.json()["order"]["payment_method"] == method
    assert data.get_order(order_id)["payment_method"] == method
    updated = [e for e in event_bus.PUBLISHED if e["type"] == "order_updated"][0]
    assert updated["order"]["payment_method"] == method
    # 2z item 2: the audit row carries it too.
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            json.loads(row["detail"])
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'operator_action' "
                "ORDER BY id"
            )
        ]
    print("audit rows:", rows)
    assert rows[-1] == {
        "action": "order_status",
        "order_id": order_id,
        "status": "COLLECTED",
        "payment_method": method,
    }


def test_an_order_view_without_a_payment_carries_null(served):
    # 16 §2ze item 6(a): a paid order can no longer reach COLLECTED with no
    # payment type at all, so the collected order that carries null is the one
    # on the house -- which is the only order that should ever have carried it.
    order_id = order([SHAKE], "READY", complimentary=True, name="Vice Chancellor")
    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json()["order"]["payment_method"] is None


@pytest.mark.parametrize("status", ["CONFIRMED", "PREPARING", "READY", "CANCELLED"])
def test_a_payment_method_on_any_other_status_is_refused(served, status):
    # 16 section 2zf item 3(d): CONFIRMED on an order that is waiting for
    # payment IS the payment, so the order under test here is one that never
    # waited -- an order from before pay-first, carrying no method at all.
    order_id = legacy_order([BURGER], "CONFIRMED")
    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": status, "payment_method": "CASH"},
        headers=AUTH,
    )
    print(status, "->", response.status_code, response.json())
    assert response.status_code == 400
    assert response.json()["detail"] == "Payment is recorded at collection."
    assert data.get_order(order_id)["payment_method"] is None


def test_an_unknown_payment_method_is_refused(served):
    order_id = legacy_order([BURGER], "READY")
    response = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "COLLECTED", "payment_method": "CARD"},
        headers=AUTH,
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Payment is recorded at collection."
    assert data.get_order(order_id)["status"] == "READY"


def test_a_complimentary_order_never_takes_a_payment_method(served):
    order_id = order([SHAKE], "READY", complimentary=True, name="Vice Chancellor")

    refused = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "COLLECTED", "payment_method": "CASH"},
        headers=AUTH,
    )
    print("on the house ->", refused.status_code, refused.json())
    assert refused.status_code == 400
    assert refused.json()["detail"] == "This order is on the house."
    assert data.get_order(order_id)["status"] == "READY"

    # Collected without one is how an on-the-house order is finished.
    allowed = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )
    assert allowed.status_code == 200
    assert allowed.json()["order"]["payment_method"] is None


# ------------------------------- 2ze item 6(a): Cash or QR, or not collected


def test_a_paid_order_is_not_collected_without_cash_or_qr(served):
    """Order #101 reached COLLECTED with no payment type, so the sale was lost.

    16 section 2zf item 3(h): under pay-first the method is already on the
    order by the time it is handed over, so the order that can still hit this
    refusal is one from before pay-first, which never recorded one.
    """
    order_id = legacy_order([BURGER], "READY")

    refused = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )
    print("no payment type ->", refused.status_code, refused.json())

    assert refused.status_code == 400
    assert refused.json()["detail"] == "Choose Cash or QR."
    # Nothing moved: the order is still waiting to be handed over.
    assert data.get_order(order_id)["status"] == "READY"
    assert data.get_order(order_id)["payment_method"] is None


@pytest.mark.parametrize("sent", [{}, {"payment_method": None}, {"payment_method": ""}])
def test_a_missing_blank_or_null_payment_type_is_all_the_same_refusal(served, sent):
    """A caller that leaves it out, sends null or sends "" is refused alike."""
    order_id = legacy_order([BURGER], "READY")

    refused = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "COLLECTED", **sent},
        headers=AUTH,
    )
    print(sent, "->", refused.status_code, refused.json())

    assert refused.status_code == 400
    assert refused.json()["detail"] == "Choose Cash or QR."
    assert data.get_order(order_id)["status"] == "READY"


@pytest.mark.parametrize("method", ["CASH", "QR"])
def test_either_payment_type_collects_a_paid_order(served, method):
    order_id = legacy_order([BURGER], "READY")

    allowed = served.post(
        f"/api/orders/{order_id}/status",
        json={"status": "COLLECTED", "payment_method": method},
        headers=AUTH,
    )

    assert allowed.status_code == 200
    assert allowed.json()["order"]["status"] == "COLLECTED"
    assert data.get_order(order_id)["payment_method"] == method


def test_an_order_on_the_house_is_still_collected_with_nothing(served):
    """The refusal is for paid orders only; the VC's order has nothing to record."""
    order_id = order([SHAKE], "READY", complimentary=True, name="Vice Chancellor")

    allowed = served.post(
        f"/api/orders/{order_id}/status", json={"status": "COLLECTED"}, headers=AUTH
    )

    assert allowed.status_code == 200
    assert data.get_order(order_id)["status"] == "COLLECTED"


@pytest.mark.parametrize("status", ["PREPARING", "READY", "CANCELLED", "FAILED"])
def test_every_other_status_still_needs_no_payment_type(served, status):
    order_id = order([BURGER], "CONFIRMED" if status != "FAILED" else "PREPARING")
    # The payment is already on it: these presses carry nothing of their own.
    if status == "READY":
        served.post(
            f"/api/orders/{order_id}/status", json={"status": "PREPARING"}, headers=AUTH
        )

    response = served.post(
        f"/api/orders/{order_id}/status", json={"status": status}, headers=AUTH
    )
    print(status, "->", response.status_code)

    assert response.status_code == 200
    assert data.get_order(order_id)["status"] == status


# ------------------------------------------- 2z item 4: the numbers themselves


@pytest.fixture
def mixed_day():
    """A day with one of everything 16 section 2zf item 9 names, by hand.

    cash         : 1 x Chicken Burger       650   (paid CASH, then COLLECTED)
    qr           : 1 x Blue Lemonade        250   (paid QR, still CONFIRMED)
    unrecorded   : 3 x Mixed Fruit Shake  1,050   (an order from before
                                                   pay-first: COLLECTED with
                                                   no method and no paid_at)
    awaiting     : 1 x Chicken Burger       650   (placed, nobody has paid)
    on the house : 1 x Mixed Fruit Shake    350   (complimentary, COLLECTED)
    cancelled    : 1 x Chicken Burger        --   (never paid, never counted)
    refunded     : 1 x Blue Lemonade        250   (paid CASH, then cancelled
                                                   by the operator)
    a draft      : 1 x Blue Lemonade         --   (never counted)
    unpriced     : 1 x Mystery Item          --   (excluded, warned about)
    """
    return {
        "cash": order([BURGER], "COLLECTED", payment="CASH"),
        "qr": order([LEMONADE], "CONFIRMED", payment="QR"),
        "unrecorded": legacy_order([{**SHAKE, "quantity": 3}], "COLLECTED"),
        "awaiting": order([BURGER], "AWAITING_PAYMENT"),
        "house": order([SHAKE], "COLLECTED", complimentary=True, name="Vice Chancellor"),
        "cancelled": order([BURGER], "CANCELLED"),
        "refunded": paid_then_cancelled([LEMONADE]),
        "draft": order([LEMONADE], None),
        "unpriced": legacy_order(
            [{"name": "Mystery Item", "quantity": 1, "price": "ask the team"}],
            "COLLECTED",
        ),
    }


def test_the_earnings_add_up_for_a_mixed_day(mixed_day):
    earnings = data.get_earnings()

    print("earnings:", json.dumps(earnings, indent=2))
    assert earnings["earned_cash"] == 650
    assert earnings["earned_qr"] == 250
    assert earnings["earned_unrecorded"] == 1050
    # The three parts add up to the whole, which is the point of the breakdown.
    assert earnings["earned"] == 650 + 250 + 1050 == 1950
    # 16 section 2zf item 3(i): `awaiting_payment` replaces `to_collect`.
    assert earnings["awaiting_payment"] == 650
    assert "to_collect" not in earnings
    assert earnings["on_the_house"] == 350
    assert earnings["on_the_house_orders"] == 1
    # 16 §2zh item 3(c): the orders counted in `earned`, which here are the
    # cash one, the QR one and the legacy unrecorded one. The QR order is paid
    # but still with the kitchen: its money is in the box, so it counts.
    assert earnings["paid_orders"] == 3
    # The order nobody paid for, and the one the operator cancelled after it
    # had been paid.
    assert earnings["cancelled_orders"] == 2
    assert earnings["refunded"] == 250
    assert earnings["refunded_orders"] == 1
    assert earnings["unpriced_orders"] == 1
    assert earnings["date"] == data._today()


# ----------------------- 2zh item 3(c): paid_orders is the orders in earned


def test_paid_orders_counts_every_order_that_made_up_earned():
    """16 §2zh item 3(c). The money and the count describe the same orders.

    Three paid orders at three different points in the kitchen: one still
    waiting to be made, one ready, one handed over. All three are money in the
    box, so all three count -- before this, only the collected one did.
    """
    order([BURGER], "CONFIRMED", payment="CASH")
    order([LEMONADE], "READY", payment="QR")
    order([SHAKE], "COLLECTED", payment="CASH")

    earnings = data.get_earnings()

    print("earnings:", json.dumps(earnings, indent=2))
    assert earnings["earned"] == 650 + 250 + 350 == 1250
    assert earnings["paid_orders"] == 3


def test_paid_orders_leaves_out_everything_earned_leaves_out():
    """An order on the house, one nobody has paid for, a draft, a refund."""
    order([SHAKE], "COLLECTED", complimentary=True, name="Vice Chancellor")
    order([BURGER], "AWAITING_PAYMENT")
    order([LEMONADE], None)
    paid_then_cancelled([LEMONADE])

    earnings = data.get_earnings()

    print("earnings:", json.dumps(earnings, indent=2))
    assert earnings["earned"] == 0
    assert earnings["paid_orders"] == 0
    # The money that has to go back is still reported, on its own line.
    assert earnings["refunded_orders"] == 1
    assert earnings["on_the_house_orders"] == 1


def test_an_unpriced_order_is_in_neither_figure():
    """It is warned about separately: counting it would imply an amount."""
    legacy_order(
        [{"name": "Mystery Item", "quantity": 1, "price": "ask the team"}], "COLLECTED"
    )

    earnings = data.get_earnings()

    assert earnings["paid_orders"] == 0
    assert earnings["unpriced_orders"] == 1


def test_money_paid_and_then_cancelled_is_reported_as_a_refund():
    """2zf item 3(i): it leaves `earned` and turns up under `refunded`."""
    paid_then_cancelled([BURGER])

    earnings = data.get_earnings()

    print("after the operator cancelled a paid order:", earnings)
    assert earnings["earned"] == 0
    assert earnings["refunded"] == 650
    assert earnings["refunded_orders"] == 1
    assert earnings["cancelled_orders"] == 1


def test_an_order_cancelled_before_it_was_paid_is_not_a_refund():
    order([BURGER], "CANCELLED")

    earnings = data.get_earnings()

    assert earnings["refunded"] == 0
    assert earnings["refunded_orders"] == 0
    assert earnings["cancelled_orders"] == 1


def test_an_order_is_earned_as_soon_as_it_is_paid_not_when_it_is_handed_over():
    """2zf item 3(i): the money is in the box long before the food goes out."""
    order([BURGER], "CONFIRMED", payment="QR")

    earnings = data.get_earnings()

    assert earnings["earned"] == 650
    assert earnings["earned_qr"] == 650
    assert earnings["awaiting_payment"] == 0


def test_an_unpaid_order_is_money_still_at_the_counter():
    order([BURGER], "AWAITING_PAYMENT")

    earnings = data.get_earnings()

    assert earnings["earned"] == 0
    assert earnings["awaiting_payment"] == 650


def test_by_item_is_ordered_by_amount(mixed_day):
    rows = data.get_earnings()["by_item"]

    print("by_item:", rows)
    # Only paid, not complimentary: the shake's three, the burger, the
    # lemonade. The unpriced order and the refunded one contribute nothing.
    assert rows == [
        {"name": "Mixed Fruit Shake", "quantity": 3, "amount": 1050},
        {"name": "Chicken Burger", "quantity": 1, "amount": 650},
        {"name": "Blue Lemonade", "quantity": 1, "amount": 250},
    ]


def test_a_draft_is_counted_nowhere(mixed_day):
    earnings = data.get_earnings()
    # The draft is a Blue Lemonade: if it leaked it would show up in
    # awaiting_payment, which the hand-worked figure above pins to 650.
    assert earnings["awaiting_payment"] == 650
    assert earnings["cancelled_orders"] == 2


def test_an_empty_day_is_all_zeros():
    earnings = data.get_earnings()
    print("an empty day:", earnings)
    assert earnings["earned"] == 0
    assert earnings["by_item"] == []
    assert earnings["unpriced_orders"] == 0


def test_the_earnings_endpoint_needs_the_token(served, mixed_day):
    assert served.get("/api/earnings").status_code == 401
    assert served.get("/api/earnings", headers={"X-Operator-Token": "wrong"}).status_code == 401

    response = served.get("/api/earnings", headers=AUTH)
    assert response.status_code == 200
    assert response.json()["earned"] == 1950


# ----------------------------------------------------- 2z item 6: the CSV


def test_the_csv_has_the_header_and_one_row_exactly(served):
    order_id = order([{**BURGER, "quantity": 2}, LEMONADE], "COLLECTED", payment="QR")

    response = served.get("/api/earnings.csv", headers=AUTH)

    print("CSV:\n" + response.text)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert f'bite-and-pour-sales-{data._today()}.csv' in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0] == [
        "order_id",
        "time",
        "guest_name",
        "items",
        "total_rs",
        "status",
        "payment_method",
        # 16 section 2zf item 3(i): the CSV gains the time of the payment.
        "paid_at",
        "on_the_house",
    ]
    assert len(rows) == 2
    row = rows[1]
    assert row[0] == str(order_id)
    assert len(row[1]) == 8 and row[1].count(":") == 2
    assert row[2] == "Ali"
    assert row[3] == "2x Chicken Burger; 1x Blue Lemonade"
    assert row[4] == "1550"
    assert row[5] == "COLLECTED"
    assert row[6] == "QR"
    assert row[7] == data.get_order(order_id)["paid_at"]
    assert row[7] != ""
    assert row[8] == "no"


def test_the_csv_leaves_out_drafts_and_marks_the_house(served):
    order([LEMONADE], None)
    house = order([SHAKE], "COLLECTED", complimentary=True, name="Chief Guest")

    rows = list(csv.reader(io.StringIO(served.get("/api/earnings.csv", headers=AUTH).text)))

    print("rows:", rows)
    assert len(rows) == 2
    assert rows[1][0] == str(house)
    assert rows[1][8] == "yes"
    assert rows[1][6] == ""


def test_the_csv_endpoint_needs_the_token(served):
    assert served.get("/api/earnings.csv").status_code == 401
    assert (
        served.get("/api/earnings.csv", headers={"X-Operator-Token": "nope"}).status_code
        == 401
    )


def test_neither_endpoint_carries_a_transcript_or_a_session(served, mixed_day):
    """2z item 6: no transcript, no session data, in either answer."""
    body = served.get("/api/earnings", headers=AUTH).text
    csv_text = served.get("/api/earnings.csv", headers=AUTH).text

    for text in (body, csv_text):
        assert "session" not in text.lower()
        assert "transcript" not in text.lower()
