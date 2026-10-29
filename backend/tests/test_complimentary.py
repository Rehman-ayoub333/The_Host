"""Phase 7k: only the Vice Chancellor is on the house (16 section 2ze item 3).

Rehman's chaos test C6 ended with a "chief guest" order on the house, stored
under the name "Vice Chancellor" (order #108), so the prompt is no longer the
only thing standing between a guest and a free order: `tools.build_order`
decides from the name on the order, and a refused request is logged.

Nothing here contains a transcript or a secret.
"""

import logging
import sqlite3
from contextlib import closing

import pytest

import config
import summaries
import tools


BURGER = {"name": "Chicken Burger", "quantity": 1}

# 16 section 2ze item 3: the exact note the tool result carries.
NOTE = "Only the Vice Chancellor is on the house."

# The names item 3 names, and the answer each must get.
ON_THE_HOUSE = ["Vice Chancellor", "Dr. Rauf-i-Azam", "rauf e azam", "RAUF-E-AZAM"]
PAYING = ["Chief Guest", "Ali", ""]


def order_row(order_id):
    """The raw database row, read without data.py's parsing or lazy expiry."""
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, guest_name, complimentary FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


def refusals(caplog) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("complimentary refused")
    ]


# ------------------------------------- the four names that are on the house


@pytest.mark.parametrize("name", ON_THE_HOUSE)
def test_the_vice_chancellors_own_name_is_on_the_house(ctx, caplog, name):
    caplog.set_level(logging.INFO)

    result = tools.build_order([BURGER], guest_name=name, complimentary=True)

    assert result["complimentary"] is True
    assert "note" not in result
    assert order_row(result["draft_id"])["complimentary"] == 1
    assert order_row(result["draft_id"])["guest_name"] == name
    assert refusals(caplog) == []


# ------------------------------------------- every other name is a paid order


@pytest.mark.parametrize("name", PAYING)
def test_any_other_name_is_stored_as_a_paid_order(ctx, caplog, name):
    caplog.set_level(logging.INFO)

    result = tools.build_order([BURGER], guest_name=name, complimentary=True)

    assert result["complimentary"] is False
    assert result["note"] == NOTE
    assert order_row(result["draft_id"])["complimentary"] == 0
    # 16 section 2ze item 3: the reason and the session, and no text at all.
    assert refusals(caplog) == ["complimentary refused session a1b2c3d4"]
    for line in refusals(caplog):
        for word in ("Chief Guest", "Ali", "Chicken Burger"):
            assert word not in line


def test_no_name_at_all_is_stored_as_a_paid_order(ctx, caplog):
    """"An empty name" (item 3): the argument omitted, not merely blank."""
    caplog.set_level(logging.INFO)

    result = tools.build_order([BURGER], complimentary=True)

    assert result["complimentary"] is False
    assert result["note"] == NOTE
    assert order_row(result["draft_id"])["complimentary"] == 0
    assert refusals(caplog) == ["complimentary refused session a1b2c3d4"]


def test_the_name_tested_is_the_one_that_goes_on_the_order(ctx, caplog):
    """The order's own name, so the stored row and the flag can never disagree.

    THE HOST may already know the guest's name from this conversation and leave
    `guest_name` out of a later call; the name on the order is still the one
    the team sees beside "on the house".
    """
    caplog.set_level(logging.INFO)
    ctx["visitor_name"] = "Dr. Rauf-i-Azam"

    remembered = tools.build_order([BURGER], complimentary=True)

    assert remembered["complimentary"] is True
    assert order_row(remembered["draft_id"])["complimentary"] == 1
    assert refusals(caplog) == []

    # A name given on the call wins over the remembered one, in both directions.
    ctx["session_id"] = "e5f6a7b8"
    ctx["pending_order_id"] = None
    overridden = tools.build_order([BURGER], guest_name="Ali", complimentary=True)

    assert overridden["complimentary"] is False
    assert overridden["note"] == NOTE
    assert refusals(caplog) == ["complimentary refused session e5f6a7b8"]


# --------------------------------- an ordinary order is told nothing about it


@pytest.mark.parametrize("sent", [None, False, "false"])
def test_an_order_that_never_asked_is_told_nothing(ctx, caplog, sent):
    caplog.set_level(logging.INFO)

    result = tools.build_order([BURGER], guest_name="Ali", complimentary=sent)

    assert "complimentary" not in result
    assert "note" not in result
    assert order_row(result["draft_id"])["complimentary"] == 0
    assert refusals(caplog) == []


# ------------------------------ the activity label the team reads (item 3)


def test_the_on_the_house_label_appears_only_for_a_stored_flag(ctx):
    free = tools.build_order([BURGER], guest_name="Vice Chancellor", complimentary=True)
    confirmed = tools.confirm_order(free["draft_id"])
    row = summaries.activity_for_tool("confirm_order", {}, confirmed)

    assert row["label"] == (
        f"Order #{confirmed['order_number']} created (on the house)"
    )

    ctx["session_id"] = "b2c3d4e5"
    ctx["pending_order_id"] = None
    refused = tools.build_order([BURGER], guest_name="Chief Guest", complimentary=True)
    placed = tools.confirm_order(refused["draft_id"])
    plain = summaries.activity_for_tool("confirm_order", {}, placed)

    assert plain["label"] == f"Order #{placed['order_number']} created"
    assert "on the house" not in plain["label"]


# ------------------------------------------------- the name check in isolation


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Vice Chancellor", True),
        ("vice chancellor", True),
        ("  VICE  CHANCELLOR  ", True),
        ("Dr. Rauf-i-Azam", True),
        ("rauf e azam", True),
        ("RAUF-E-AZAM", True),
        ("Rauf Azam", True),
        ("Azam Rauf", True),
        ("Chief Guest", False),
        ("Ali", False),
        ("Sir", False),
        ("Rauf", False),
        ("Azam", False),
        ("Vice Chancellor's friend", False),
        ("The Vice Chancellor", False),
        ("", False),
        (None, False),
    ],
)
def test_the_name_check_reads_letters_only(name, expected):
    assert tools._is_the_vice_chancellor(name) is expected
