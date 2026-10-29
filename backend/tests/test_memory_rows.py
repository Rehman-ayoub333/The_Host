"""Phase 4: the `Memory updated` activity row (09 section 15a, 03 section 4).

The row needs the favourite from *before* the order was linked, so only the tool
can build it. It is queued on `ctx["activity_queue"]` (09 section 1) and drained by
`live_session` right after the tool returns (16 section 2d item 1); tools still
never publish `agent_activity` themselves.
"""

import asyncio

import data
import doubles
import event_bus
import tools


def queued(ctx):
    return ctx.get("activity_queue") or []


def confirm(items, guest_name="Ahmed"):
    order_id = tools.build_order(list(items), guest_name=guest_name)["draft_id"]
    # 16 section 2zf item 3(b): an ordinary order is placed with a payment.
    return tools.confirm_order(order_id, payment_method="CASH")


def activity_rows():
    return [
        (event["kind"], event["label"], event["detail"])
        for event in event_bus.PUBLISHED
        if event["type"] == "agent_activity"
    ]


# ------------------------------------------------------- the three row variants


def test_a_first_favourite_is_named_as_a_new_favourite(ctx):
    data.create_visitor("ahmed", "Ahmed")

    confirm([{"name": "Chicken Burger"}])

    print("queued rows:", queued(ctx))
    assert queued(ctx) == [
        {
            "kind": "memory",
            "label": "Memory updated",
            "detail": "Ahmed: new favourite, Chicken Burger",
        }
    ]
    assert data.get_visitor("ahmed")["favorite_item"] == "Chicken Burger"


def test_ordering_the_same_favourite_again_says_so(ctx):
    data.create_visitor("ahmed", "Ahmed")
    confirm([{"name": "Chicken Burger", "quantity": 2}])
    queued(ctx).clear()

    confirm([{"name": "Chicken Burger"}])

    print("queued rows:", queued(ctx))
    assert queued(ctx) == [
        {
            "kind": "memory",
            "label": "Memory updated",
            "detail": "Ahmed: ordered Chicken Burger again",
        }
    ]


def test_an_order_that_leaves_the_favourite_alone_updates_the_last_order(ctx):
    data.create_visitor("ahmed", "Ahmed")
    confirm([{"name": "Chicken Burger", "quantity": 3}])
    queued(ctx).clear()

    # The favourite stays the burger, but it is not in this order at all.
    confirm([{"name": "Blue Lemonade"}])

    print("queued rows:", queued(ctx))
    assert queued(ctx) == [
        {"kind": "memory", "label": "Memory updated", "detail": "Ahmed: last order updated"}
    ]
    profile = data.get_visitor("ahmed")
    assert profile["favorite_item"] == "Chicken Burger"
    assert profile["last_order"] == "Blue Lemonade"


def test_a_visit_with_no_order_linked_produces_no_memory_row(ctx):
    """09 section 15a: the `visitor` row already covers a plain visit."""
    tools.remember_visitor("Sara")

    print("queued rows:", queued(ctx))
    assert queued(ctx) == []


def test_a_name_given_after_a_confirmed_order_queues_the_row(ctx):
    """09 section 10: the attach loop links the order, so the row belongs there."""
    order_id = tools.build_order([{"name": "Club Sandwich"}])["draft_id"]
    tools.confirm_order(order_id, payment_method="CASH")
    assert queued(ctx) == []

    tools.remember_visitor("Sara")

    print("queued rows:", queued(ctx))
    assert queued(ctx) == [
        {
            "kind": "memory",
            "label": "Memory updated",
            "detail": "Sara: new favourite, Club Sandwich",
        }
    ]


# ------------------------------------------------- live_session drains the queue


def test_live_session_publishes_each_queued_row_after_the_tool():
    session, ws = doubles.new_session()
    data.create_visitor("ahmed", "Ahmed")

    async def go():
        await session._handle_message(
            doubles.message(
                tool_call=doubles.call(
                    "build_order",
                    {"items": [{"name": "Chicken Burger"}], "guest_name": "Ahmed"},
                    "call-build",
                )
            )
        )
        order_id = session.ctx["pending_order_id"]
        # 16 section 2zb item 3: the guard needs the guest's own yes after the
        # draft was built before confirm_order may run.
        await session._handle_message(doubles.message(doubles.content(visitor="Yes.")))
        await session._handle_message(
            doubles.message(
                tool_call=doubles.call(
                    "confirm_order",
                    {"draft_id": order_id, "payment_method": "CASH"},
                    "call-confirm",
                )
            )
        )
        return order_id

    order_id = asyncio.run(go())

    print("published activity rows:", activity_rows())
    assert activity_rows() == [
        # 16 §2zi item 3(b): a draft has no number to show.
        ("order", "Draft prepared", None),
        ("order", f"Order #{data.get_order(order_id)['order_no']} created", "Chicken Burger"),
        ("memory", "Memory updated", "Ahmed: new favourite, Chicken Burger"),
    ]
    # Drained, and stamped with the session that caused it.
    assert session.ctx["activity_queue"] == []
    memory_row = [
        event
        for event in event_bus.PUBLISHED
        if event["type"] == "agent_activity" and event["kind"] == "memory"
    ][-1]
    print("the memory row as published:", memory_row)
    assert memory_row["session_id"] == session.ctx["session_id"]
    assert isinstance(memory_row["event_id"], int)
    doubles.validate(ws)


def test_the_queue_is_drained_even_when_the_tool_returned_an_error():
    """16 section 2d item 1. A failing tool leaves nothing behind in the queue."""
    session, _ = doubles.new_session()

    async def go():
        session.ctx.setdefault("activity_queue", []).append(
            {"kind": "memory", "label": "Memory updated", "detail": "Ahmed: last order updated"}
        )
        # 16 section 2zb item 3: the opening turn and a yes, so the guard lets
        # the call through and the tool's own error is what the test sees.
        await session._handle_message(doubles.message(doubles.content(turn_complete=True)))
        await session._handle_message(doubles.message(doubles.content(visitor="Yes.")))
        await session._handle_message(
            doubles.message(tool_call=doubles.call("confirm_order", {"draft_id": 999}, "call-x"))
        )

    asyncio.run(go())

    print("published activity rows:", activity_rows())
    assert session.ctx["activity_queue"] == []
    assert ("order", "Order could not be confirmed", None) in activity_rows()
    assert ("memory", "Memory updated", "Ahmed: last order updated") in activity_rows()


def test_the_system_events_history_keeps_the_memory_row():
    """16 section 2b item 7: every agent_activity is also a system_events row."""
    session, _ = doubles.new_session()
    data.create_visitor("ahmed", "Ahmed")

    async def go():
        await session._handle_message(
            doubles.message(
                tool_call=doubles.call(
                    "build_order",
                    {"items": [{"name": "Blue Lemonade"}], "guest_name": "Ahmed"},
                    "call-build",
                )
            )
        )
        await session._handle_message(doubles.message(doubles.content(visitor="Yes.")))
        await session._handle_message(
            doubles.message(
                tool_call=doubles.call(
                    "confirm_order",
                    {
                        "draft_id": session.ctx["pending_order_id"],
                        "payment_method": "CASH",
                    },
                    "call-confirm",
                )
            )
        )

    asyncio.run(go())

    rows = [row for row in data.list_activity(limit=20) if row["kind"] == "memory"]
    print("activity history, memory rows:", rows)
    assert [row["detail"] for row in rows] == ["Ahmed: new favourite, Blue Lemonade"]
