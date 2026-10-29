"""Phase 7i-c: the confirmation guard (16 section 2zb item 3, 09 section 5).

In the 7i-b live test THE HOST asked "Shall I confirm this, Ali?" and called
`confirm_order` in the same turn, before Ali had answered: order 57 was
CONFIRMED without a yes. The prompt said not to; the prompt is not a guarantee.
So `live_session` now checks, before it dispatches `confirm_order`, that a guest
line has arrived since the draft was built or offered and that the line contains
the guest's own yes. This is the fallback 09 section 5 documented and left
unbuilt until testing showed it was needed.

Nothing here logs or asserts a word of what the guest said: the guard keeps the
line in memory and logs only a reason.
"""

import asyncio
import json
import logging

import pytest

import data
import live_session as ls
from live_session import CONFIRM_REFUSAL, has_affirmative

import doubles


BURGER = {"name": "Chicken Burger", "quantity": 1}


def listening():
    """A session that has just connected, as test_live_session has it."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    return session, ws


def feed(session, *messages):
    async def go():
        for item in messages:
            await session._handle_message(item)

    asyncio.run(go())


def guest_said(session, line):
    """A visitor input-transcription fragment: the guest spoke."""
    feed(session, doubles.message(doubles.content(visitor=line)))


def guest_typed(session, ws, line):
    """A text_input from the page: the typed path every scenario test uses.

    The uplink runs to the disconnect, exactly as test_always_ready drives it.
    """
    ws.messages.append(
        {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": line})}
    )
    asyncio.run(session._uplink())


def built_draft(session):
    """A draft built in this session, as a tool call from Gemini."""
    feed(session, doubles.message(tool_call=doubles.call("build_order", {"items": [BURGER]})))
    return session.ctx["pending_order_id"]


def confirm(session, order_id, call_id="call-confirm", payment="CASH"):
    """16 §2zf item 3(b): placing an ordinary order now says how it will be paid.

    The guard is unchanged by that -- it still asks whether the guest spoke
    after the draft and whether they said yes -- so every test here passes the
    method the model would have passed and watches the guard, not the payment.
    """
    feed(
        session,
        doubles.message(
            tool_call=doubles.call(
                "confirm_order",
                {"draft_id": order_id, "payment_method": payment},
                call_id,
            )
        ),
    )


def last_response(session):
    return session.session.responses[-1]["function_responses"][-1]


# ------------------------------------------------- the word list itself


@pytest.mark.parametrize(
    "line",
    [
        "Yes.",
        "yeah",
        "Yep!",
        "yup",
        "Sure, go for it",
        "confirm",
        "Confirmed",
        "okay",
        "OK",
        "alright",
        "go ahead",
        "please do",
        "place it",
        "mhm",
        "mm-hmm",
        "uh-huh",
        "haan",
        "han ji",
        "ji",
        "jee",
        "theek hai",
        "thik hai",
        "bilkul",
        "kar do",
        "kardo",
        "ہاں",
        "جی",
        "ٹھیک ہے",
        "Haan ji, confirm kar do",
    ],
)
def test_every_affirmative_counts(line):
    assert has_affirmative(line) is True


@pytest.mark.parametrize(
    "line",
    [
        "",
        "No thanks.",
        "Not yet.",
        "Maybe later",
        # The words must be whole: a yes inside another word is not a yes.
        "yesterday",
        "jingle",
        "okayish",
        "Can you repeat that?",
        "nahi",
    ],
)
def test_a_line_without_an_affirmative_does_not_count(line):
    assert has_affirmative(line) is False


# ---------------------------------------------- the guard, through the session


def test_a_confirm_in_the_same_turn_as_the_build_is_refused(caplog):
    """E19 and E35: the model asks and confirms in one breath. Refused."""
    session, ws = listening()
    guest_said(session, "One Chicken Burger.")
    order_id = built_draft(session)

    with caplog.at_level(logging.INFO, logger="live_session"):
        confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "PENDING_CONFIRMATION"
    assert last_response(session).response == {
        "source": "order",
        "error": "Please confirm first.",
    }
    lines = [record.getMessage() for record in caplog.records]
    print("log lines:", lines)
    assert f"confirm refused session {session.ctx['session_id']} order {order_id} reason=no_new_line" in lines
    doubles.validate(ws)


def test_a_confirm_after_a_later_yes_passes():
    session, ws = listening()
    order_id = built_draft(session)

    guest_said(session, "Yes.")
    confirm(session, order_id)

    # 16 §2zf item 3(b): a guest's yes places the order; the money makes it
    # CONFIRMED. The guard's job ends at the yes.
    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"
    assert last_response(session).response["status"] == "AWAITING_PAYMENT"
    doubles.validate(ws)


def test_a_confirm_after_a_no_is_refused(caplog):
    """A new line, but not a yes: 'no thanks' must never place an order."""
    session, ws = listening()
    order_id = built_draft(session)

    guest_said(session, "No thanks.")
    with caplog.at_level(logging.INFO, logger="live_session"):
        confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "PENDING_CONFIRMATION"
    assert last_response(session).response == dict(CONFIRM_REFUSAL)
    assert (
        f"confirm refused session {session.ctx['session_id']} order {order_id} "
        "reason=no_affirmative" in [record.getMessage() for record in caplog.records]
    )
    doubles.validate(ws)


def test_a_haan_ji_passes():
    """16 section 2zb item 3(b): Urdu counts, in Roman and in script."""
    session, _ws = listening()
    order_id = built_draft(session)

    guest_said(session, "Haan ji.")
    confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"


def test_a_typed_yes_counts_as_a_guest_line():
    """A text_input is a guest line too (the demo path and every scenario test)."""
    session, ws = listening()
    order_id = built_draft(session)

    guest_typed(session, ws, "Yes.")
    confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"


def test_an_orphaned_draft_is_confirmed_after_the_offer_and_a_yes(host_data):
    """E36: the draft was built in the conversation that broke (2l item 4).

    There is no build in this session, so the reference point is the end of the
    opening turn -- the turn in which THE HOST offers the order back.
    """
    order_id = host_data.create_order_draft([BURGER], "Hamza", "broken-1")["order_id"]
    host_data.orphan_draft(order_id)
    session, _ws = listening()
    # The opening instruction claims the draft for this session and sets
    # pending_order_id, exactly as live_session does (live_session.py:665-667).
    host_data.claim_orphan_draft(order_id, session.ctx["session_id"])
    session.ctx["pending_order_id"] = order_id

    # The opening turn: THE HOST names the items and asks.
    feed(session, doubles.message(doubles.content(audio=b"\x01")))
    feed(session, doubles.message(doubles.content(turn_complete=True)))
    # The guest answers it.
    guest_said(session, "Yes.")
    confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "AWAITING_PAYMENT"


def test_an_orphaned_draft_is_refused_before_the_offer_has_been_made(caplog):
    """A yes that arrived before the offer cannot confirm an inherited draft."""
    order_id = data.create_order_draft([BURGER], "Hamza", "broken-1")["order_id"]
    data.orphan_draft(order_id)
    session, _ws = listening()
    data.claim_orphan_draft(order_id, session.ctx["session_id"])
    session.ctx["pending_order_id"] = order_id

    guest_said(session, "Yes.")
    with caplog.at_level(logging.INFO, logger="live_session"):
        confirm(session, order_id)

    assert data.get_order(order_id)["status"] == "PENDING_CONFIRMATION"
    assert last_response(session).response == dict(CONFIRM_REFUSAL)
    assert (
        f"confirm refused session {session.ctx['session_id']} order {order_id} "
        "reason=no_new_line" in [record.getMessage() for record in caplog.records]
    )


def test_a_rebuilt_draft_needs_a_fresh_yes(caplog):
    """The draft changed after the yes, so the yes no longer covers it."""
    session, _ws = listening()
    order_id = built_draft(session)
    guest_said(session, "Yes.")
    # The guest changes their mind and the draft is rebuilt.
    feed(
        session,
        doubles.message(tool_call=doubles.call(
            "build_order", {"items": [{"name": "Blue Lemonade", "quantity": 1}]}, "call-rebuild"
        )),
    )
    rebuilt = session.ctx["pending_order_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        confirm(session, rebuilt)

    assert data.get_order(rebuilt)["status"] == "PENDING_CONFIRMATION"
    assert last_response(session).response == dict(CONFIRM_REFUSAL)


# --------------------------------------------- what a refusal must not do


def test_a_refusal_writes_no_activity_row_and_no_text(caplog):
    """16 section 2zb item 3: nothing happened to an order, so no row."""
    import event_bus

    session, _ws = listening()
    order_id = built_draft(session)
    event_bus.PUBLISHED.clear()

    with caplog.at_level(logging.INFO, logger="live_session"):
        confirm(session, order_id)

    rows = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("activity rows after a refusal:", rows)
    assert rows == []
    # The refusal is not an order event either.
    assert [event for event in event_bus.PUBLISHED if event["type"] == "order_updated"] == []

    logged = " | ".join(record.getMessage() for record in caplog.records)
    print("every log line:", logged)
    for word in ("Chicken", "Burger", "Yes", "yes", "No thanks", "Please confirm first"):
        assert word not in logged, word


def test_the_refusal_response_is_exactly_as_written():
    assert CONFIRM_REFUSAL == {"source": "order", "error": "Please confirm first."}
    # A copy goes back each time, so a mutation cannot leak between turns.
    session, _ws = listening()
    order_id = built_draft(session)
    confirm(session, order_id)
    response = last_response(session).response
    assert response == CONFIRM_REFUSAL
    assert response is not CONFIRM_REFUSAL


def test_the_word_list_is_the_one_the_spec_names():
    """16 section 2zb item 3(b), with 2zf item 3(c)'s four payment words.

    Under pay-first the one question is "Shall I place it -- cash or QR?", so
    the guest answers it with the payment and not with a yes. Those four words
    are the guest's own consent to the order being placed.

    16 section 2zh item 3(b) separates the two: `AFFIRMATIVES` is the 2zb list
    on its own, because the cancel guard takes that and not the payment words.
    """
    assert ls.AFFIRMATIVES == (
        "yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "okay", "ok",
        "alright", "go ahead", "please do", "place it", "mhm", "mm-hmm", "uh-huh",
        "haan", "han", "ji", "jee", "theek hai", "thik hai", "bilkul", "kar do",
        "kardo", "ہاں", "جی", "ٹھیک ہے",
    )
    assert ls.PAYMENT_WORDS == ("cash", "qr", "online", "scan")
    assert ls.CONFIRM_WORDS == ls.AFFIRMATIVES + ls.PAYMENT_WORDS


def test_a_cancel_is_never_guarded():
    """Only confirm_order is checked: a guest saying no must still be obeyed."""
    session, _ws = listening()
    order_id = built_draft(session)

    feed(
        session,
        doubles.message(tool_call=doubles.call("cancel_order", {"draft_id": order_id}, "call-c")),
    )

    assert data.get_order(order_id)["status"] == "CANCELLED"
