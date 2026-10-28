"""Phase 7j: the cancel guard (16 section 2zc item 2), mirroring the confirm one.

Rehman asked whether a guest can change an order after placing it. They can,
while the money has not been taken -- which opens two ways to lose food: a
misheard line cancelling a real order, and a voice cancel of something already
paid for. `tools.cancel_order` closes the second (anything from CONFIRMED on is
refused, tested in test_tools.py and test_pay_first.py); this file is the first.
Before `cancel_order` runs against a placed order, the guest must have spoken
since it was placed, and that line must carry their consent.

16 section 2zf item 3(g) moves the guarded status from CONFIRMED to
AWAITING_PAYMENT: under pay-first that is what "placed, but not yet the
kitchen's" means, and it is the only placed status a voice cancel can reach.

A draft is deliberately not guarded: "no" to the final question has to cancel
it. Nothing here logs a word of what the guest said.
"""

import asyncio
import json
import logging

import pytest

import data
import event_bus
import live_session as ls
from live_session import CANCEL_REFUSAL, has_cancel_consent

import doubles


BURGER = {"name": "Chicken Burger", "quantity": 1}


def listening():
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    return session, ws


def feed(session, *messages):
    async def go():
        for item in messages:
            await session._handle_message(item)

    asyncio.run(go())


def guest_said(session, line):
    feed(session, doubles.message(doubles.content(visitor=line)))


def host_replied(session, line="Of course."):
    """THE HOST answers, which closes the guest's line.

    A visitor transcript accumulates until the other speaker's turn finalises
    it (03 section 4), so a conversation where THE HOST never answers would
    read as one long guest line. Live, it always answers; these tests say so
    rather than relying on the buffer.
    """
    feed(
        session,
        doubles.message(doubles.content(audio=b"\x01", agent=line)),
        doubles.message(doubles.content(turn_complete=True)),
    )


def guest_typed(session, ws, line):
    ws.messages.append(
        {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": line})}
    )
    asyncio.run(session._uplink())


def placed_order(session, items=(BURGER,)):
    """A draft built and placed in this session, the ordinary pay-first way."""
    feed(
        session,
        doubles.message(tool_call=doubles.call("build_order", {"items": list(items)})),
    )
    order_id = session.ctx["pending_order_id"]
    guest_said(session, "Cash.")
    feed(
        session,
        doubles.message(
            tool_call=doubles.call(
                "confirm_order", {"order_id": order_id, "payment_method": "CASH"}
            )
        ),
    )
    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"
    # "Order 12 — pay at the counter." The answer is finished business now.
    host_replied(session, "Done — pay at the counter and the kitchen starts.")
    return order_id


def paid(order_id):
    """The team marks the money taken, as the operator endpoint does."""
    data.update_order_status(order_id, "CONFIRMED", payment_method="CASH")


def cancel(session, order_id, call_id="call-cancel"):
    feed(
        session,
        doubles.message(tool_call=doubles.call("cancel_order", {"order_id": order_id}, call_id)),
    )


def last_response(session):
    return session.session.responses[-1]["function_responses"][-1]


# ------------------------------------------------ the consent words themselves


@pytest.mark.parametrize(
    "line",
    [
        "Yes.",
        "Haan ji.",
        "Cancel it.",
        "Please cancel my order.",
        "Remove the shake.",
        "I don't want it any more.",
        "I do not want that order.",
        "Mujhe nahi chahiye.",
        "Nahin chahiye.",
        "Cancel kar do.",
        "Hata do.",
        "Go ahead.",
        "ٹھیک ہے",
    ],
)
def test_every_consent_line_counts(line):
    assert has_cancel_consent(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "",
        "What's in it?",
        "How long will it take?",
        "Not yet.",
        # Whole words only: a cancel inside another word is not consent.
        "cancellation policy",
        "removal",
    ],
)
def test_a_line_without_consent_does_not_count(line):
    assert has_cancel_consent(line) is False


# ------------------------------------------------- the guard, through a session


def test_a_cancel_in_the_same_turn_as_the_confirmation_is_refused(caplog):
    """The guest said yes to placing the order, not to cancelling it."""
    session, ws = listening()
    order_id = placed_order(session)

    with caplog.at_level(logging.INFO, logger="live_session"):
        cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"
    assert last_response(session).response == {
        "source": "order",
        "error": "Please ask the guest to confirm the cancellation first.",
    }
    lines = [record.getMessage() for record in caplog.records]
    print("log lines:", lines)
    assert (
        f"cancel refused session {session.ctx['session_id']} order {order_id} "
        "reason=no_new_line" in lines
    )
    doubles.validate(ws)


def test_a_cancel_after_a_line_without_consent_is_refused(caplog):
    session, ws = listening()
    order_id = placed_order(session)

    guest_said(session, "How long will it take?")
    with caplog.at_level(logging.INFO, logger="live_session"):
        cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"
    assert last_response(session).response == dict(CANCEL_REFUSAL)
    assert (
        f"cancel refused session {session.ctx['session_id']} order {order_id} "
        "reason=no_consent" in [record.getMessage() for record in caplog.records]
    )
    doubles.validate(ws)


def test_a_cancel_after_a_yes_passes():
    session, ws = listening()
    order_id = placed_order(session)

    guest_said(session, "Yes.")
    cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "CANCELLED"
    assert last_response(session).response["status"] == "CANCELLED"
    doubles.validate(ws)


def test_a_cancel_after_a_haan_ji_passes():
    session, _ws = listening()
    order_id = placed_order(session)

    guest_said(session, "Haan ji.")
    cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "CANCELLED"


def test_a_cancel_after_the_guest_says_cancel_it_passes():
    """2zc item 2(b): the guest naming the cancellation is consent too."""
    session, _ws = listening()
    order_id = placed_order(session)

    guest_said(session, "Cancel it, please.")
    cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "CANCELLED"


def test_a_typed_consent_line_counts():
    session, ws = listening()
    order_id = placed_order(session)

    guest_typed(session, ws, "Cancel my order.")
    cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "CANCELLED"


def test_a_draft_is_never_guarded():
    """A no to the confirmation question has to cancel the draft at once."""
    session, _ws = listening()
    feed(session, doubles.message(tool_call=doubles.call("build_order", {"items": [BURGER]})))
    order_id = session.ctx["pending_order_id"]
    assert data.get_order(order_id)["status"] == "PENDING_CONFIRMATION"

    # No guest line at all since the draft was built, and no consent word.
    cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "CANCELLED"
    assert session.ctx["pending_order_id"] is None


def test_a_paid_order_is_the_tools_business_not_the_guards(caplog):
    """The guard steps aside; cancel_order itself refuses (2zf item 3(g))."""
    session, _ws = listening()
    order_id = placed_order(session)
    paid(order_id)
    data.update_order_status(order_id, "PREPARING")

    guest_said(session, "Cancel it.")
    with caplog.at_level(logging.INFO, logger="live_session"):
        cancel(session, order_id)

    assert data.get_order(order_id)["status"] == "PREPARING"
    assert last_response(session).response == {
        "source": "order",
        "error": "That order is already paid — the team can help.",
    }
    # The guard did not refuse it: the tool did, so the tool's lines are logged.
    assert "cancel refused" not in " ".join(
        record.getMessage() for record in caplog.records
    )


def test_an_order_placed_before_this_conversation_needs_a_line_in_it(caplog):
    """A cancel of an order from an earlier session still needs consent now."""
    order_id = data.create_order_draft([BURGER], "Ali", "earlier-1")["order_id"]
    data.update_order_status(order_id, "AWAITING_PAYMENT", payment_method="CASH")
    session, _ws = listening()
    # The guest gave their name, so the order is theirs by name (09 section 1's
    # ownership rule); the order itself was placed before this session.
    session.ctx["visitor_name"] = "Ali"

    with caplog.at_level(logging.INFO, logger="live_session"):
        cancel(session, order_id)
    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"
    assert (
        f"cancel refused session {session.ctx['session_id']} order {order_id} "
        "reason=no_new_line" in [record.getMessage() for record in caplog.records]
    )

    guest_said(session, "Cancel it.")
    cancel(session, order_id, "call-cancel-2")
    assert data.get_order(order_id)["status"] == "CANCELLED"


# --------------------------------------- 2zc item 2(c): a change is new-first


def test_a_change_confirms_the_new_order_before_cancelling_the_old():
    session, _ws = listening()
    old_id = placed_order(session, [BURGER, {"name": "Mixed Fruit Shake", "quantity": 1}])

    # "Remove the shake": a new draft with the corrected items.
    guest_said(session, "Remove the shake.")
    feed(session, doubles.message(tool_call=doubles.call(
        "build_order", {"items": [BURGER]}, "call-rebuild"
    )))
    new_id = session.ctx["pending_order_id"]
    assert new_id != old_id

    guest_said(session, "Cash.")
    feed(session, doubles.message(tool_call=doubles.call(
        "confirm_order", {"order_id": new_id, "payment_method": "CASH"}, "call-confirm-new"
    )))
    assert data.get_order(new_id)["status"] == "AWAITING_PAYMENT"
    cancel(session, old_id)

    print("old:", data.get_order(old_id)["status"], "new:", data.get_order(new_id)["status"])
    assert data.get_order(old_id)["status"] == "CANCELLED"
    assert data.get_order(new_id)["status"] == "AWAITING_PAYMENT"


def test_when_the_new_confirm_fails_the_old_order_is_untouched():
    """2zc item 2(c): new-first means a failure leaves the guest with an order."""
    session, _ws = listening()
    old_id = placed_order(session)

    guest_said(session, "Make it a Club Sandwich instead.")
    feed(session, doubles.message(tool_call=doubles.call(
        "build_order", {"items": [{"name": "Club Sandwich", "quantity": 1}]}, "call-rebuild"
    )))
    new_id = session.ctx["pending_order_id"]
    # The confirm fails: the draft expired under the guest (09 section 5).
    data.update_order_status(new_id, "CANCELLED", reason="expired")
    guest_said(session, "Cash.")
    feed(session, doubles.message(tool_call=doubles.call(
        "confirm_order", {"order_id": new_id, "payment_method": "CASH"}, "call-confirm-new"
    )))

    response = last_response(session).response
    print("the failed confirm:", response)
    assert "error" in response
    assert data.get_order(old_id)["status"] == "AWAITING_PAYMENT"


# ----------------------------------------------- what a refusal must not do


def test_a_refusal_writes_no_activity_row_and_no_text(caplog):
    session, _ws = listening()
    order_id = placed_order(session)
    event_bus.PUBLISHED.clear()

    with caplog.at_level(logging.INFO, logger="live_session"):
        cancel(session, order_id)

    rows = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("activity rows after a refusal:", rows)
    assert rows == []
    assert [event for event in event_bus.PUBLISHED if event["type"] == "order_updated"] == []

    logged = " | ".join(record.getMessage() for record in caplog.records)
    print("every log line:", logged)
    for word in ("Chicken", "Burger", "Cash", "cash", "Cancel it", "confirm the cancellation"):
        assert word not in logged, word


def test_the_refusal_response_is_exactly_as_written():
    assert CANCEL_REFUSAL == {
        "source": "order",
        "error": "Please ask the guest to confirm the cancellation first.",
    }
    session, _ws = listening()
    order_id = placed_order(session)
    cancel(session, order_id)
    response = last_response(session).response
    assert response == CANCEL_REFUSAL
    assert response is not CANCEL_REFUSAL


def test_the_cancel_phrases_are_the_ones_the_spec_names():
    assert ls.CANCEL_PHRASES == (
        "cancel", "remove", "don't want", "do not want", "nahi chahiye",
        "nahin chahiye", "cancel kar do", "hata do",
    )
