import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest

import conftest
import config
import data
import event_bus


def _rows(sql, params=()):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _backdate(order_id, seconds):
    stamp = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stamp, order_id))
        conn.commit()


def _draft(items, guest_name=None, session_id="s-1"):
    return data.create_order_draft(items, guest_name, session_id)


BURGER = {"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}
LEMONADE = {"name": "Blue Lemonade", "quantity": 1, "price": "Rs. 250"}


def test_init_db_creates_every_table_and_keeps_agent_log():
    names = {row["name"] for row in _rows("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "menu_items",
        "orders",
        "feedback",
        "visitors",
        "business_info",
        "system_events",
        "agent_log",
    } <= names
    columns = {row["name"] for row in _rows("PRAGMA table_info(agent_log)")}
    # 16 section 2t item 7 added session_id to this table.
    assert columns == {"id", "timestamp", "tool", "input_args", "result", "session_id"}


def test_seeds_menu_and_business_info_and_keeps_the_sold_out_toggle():
    """16 section 2zb item 8: the menu follows the JSON now, like the topics.

    The operator's sold-out toggle still survives a restart, which is what the
    second half of this test has always guarded.
    """
    assert data.load_menu() == 5
    # 16 section 2k item 7 added the four identity topics to the seed file,
    # 2m item 5 the guest-of-honour one, and 21 Part B privacy, technical,
    # payment and halal.
    assert len(data.get_business_info()) == 11
    data.set_menu_availability("Blue Lemonade", False)
    data.init_db()
    assert data.get_menu_item("Blue Lemonade")["available"] == 0


# -------------------- 16 section 2zb item 8: the menu follows the JSON


def menu_seed(**changes):
    """The five real items, with one of them altered for the test."""
    rows = [dict(row) for row in conftest.MENU_SEED]
    for row in rows:
        if row["name"] in changes:
            row.update(changes[row["name"]])
    return rows


def write_menu(path, rows):
    path.write_text(json.dumps(rows), encoding="utf-8")


def test_a_changed_price_applies_at_the_next_startup(tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    data.init_db()
    assert data.get_menu_item("Chicken Burger")["price"] == "Rs. 650"

    write_menu(menu, menu_seed(**{"Chicken Burger": {"price": "Rs. 700"}}))
    changes = data.init_db()

    item = data.get_menu_item("Chicken Burger")
    print("after the price change:", item)
    assert item["price"] == "Rs. 700"
    assert ("Chicken Burger", True) in changes
    # Nothing else moved.
    assert data.get_menu_item("Blue Lemonade")["price"] == "Rs. 250"


def test_a_sold_out_item_stays_sold_out_across_a_restart(tmp_path, monkeypatch):
    """The operator's toggle wins over the file, even when the file changes."""
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    data.init_db()
    data.set_menu_availability("Blue Lemonade", False)

    write_menu(menu, menu_seed(**{"Blue Lemonade": {"description": "Now with mint."}}))
    data.init_db()

    item = data.get_menu_item("Blue Lemonade")
    print("after the restart:", item)
    assert item["available"] == 0
    assert item["description"] == "Now with mint."


def test_a_new_item_appears_and_starts_available(tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    data.init_db()

    rows = [dict(row) for row in conftest.MENU_SEED]
    rows.append({
        "name": "Mint Margarita",
        "category": "Drinks",
        "price": "Rs. 300",
        "description": "Fresh mint, blended cold.",
        "image_url": "/menu/mint-margarita.jpg",
        "prep_seconds": 90,
    })
    write_menu(menu, rows)
    changes = data.init_db()

    item = data.get_menu_item("Mint Margarita")
    print("the new item:", item)
    assert item["available"] == 1
    assert item["price"] == "Rs. 300"
    assert ("Mint Margarita", True) in changes
    assert data.load_menu() == 6


def test_an_item_no_longer_in_the_file_disappears(tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    data.init_db()

    write_menu(menu, [row for row in conftest.MENU_SEED if row["name"] != "Patty Burger"])
    changes = data.init_db()

    print("menu after the removal:", [row["name"] for row in data.get_menu()])
    assert data.get_menu_item("Patty Burger") is None
    assert ("Patty Burger", False) in changes
    assert data.load_menu() == 4


def test_an_existing_order_keeps_the_price_it_was_bought_at(tmp_path, monkeypatch):
    """Nothing references a menu row by id: an order carries its own copy."""
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    data.init_db()
    # The shape build_order stores: the item's name and the price it was bought
    # at, copied into the order, never a reference to the menu row.
    draft = data.create_order_draft(
        [{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}], "Ali", "session-1"
    )
    order_id = draft["order_id"]

    # The price doubles and the item the order names is removed entirely.
    rows = menu_seed(**{"Chicken Burger": {"price": "Rs. 1,300"}})
    write_menu(menu, [row for row in rows if row["name"] != "Club Sandwich"])
    data.init_db()

    order = data.get_order(order_id)
    items = order["items"]
    print("the order after the menu moved:", items)
    assert items[0]["price"] == "Rs. 650"
    assert data.compute_total(items) == "Rs. 650"


def test_nothing_changed_means_nothing_to_announce(tmp_path, monkeypatch):
    menu = tmp_path / "menu.json"
    write_menu(menu, conftest.MENU_SEED)
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu)
    first = data.init_db()
    second = data.init_db()

    print("first startup changed:", len(first), "second:", second)
    assert second == []


# ------------------ 16 section 2za item 8: the topics follow the JSON


def test_a_changed_topic_text_replaces_the_stored_answer_on_startup(tmp_path, monkeypatch):
    """The JSON is the source of truth for every topic it carries.

    Until this, the row was inserted only when absent, so 21 Part B's new
    complimentary_guests text never reached a database that already had that
    topic: the stall would have gone on telling guests the chief guest is on
    the house.
    """
    seed = tmp_path / "business_info.json"
    seed.write_text(
        json.dumps([{"topic": "hours", "answer": "The old hours."}]), encoding="utf-8"
    )
    monkeypatch.setattr(config, "BUSINESS_INFO_JSON_PATH", seed)
    data.init_db()
    assert data.get_business_info("hours")[0]["answer"] == "The old hours."

    seed.write_text(
        json.dumps([{"topic": "hours", "answer": "The new hours."}]), encoding="utf-8"
    )
    data.init_db()

    rows = data.get_business_info("hours")
    print("after the second startup:", rows)
    assert len(rows) == 1
    assert rows[0]["answer"] == "The new hours."


def test_a_stored_topic_missing_from_the_json_is_left_alone(tmp_path, monkeypatch):
    """An operator's own topic is not deleted by a seed file that omits it."""
    seed = tmp_path / "business_info.json"
    seed.write_text(
        json.dumps(
            [
                {"topic": "hours", "answer": "The gala hours."},
                {"topic": "parking", "answer": "Behind the hall."},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "BUSINESS_INFO_JSON_PATH", seed)
    data.init_db()
    assert data.get_business_info("parking")[0]["answer"] == "Behind the hall."

    seed.write_text(
        json.dumps([{"topic": "hours", "answer": "The gala hours."}]), encoding="utf-8"
    )
    data.init_db()

    topics = {row["topic"]: row["answer"] for row in data.get_business_info()}
    print("topics after the seed file dropped one:", sorted(topics))
    assert topics["parking"] == "Behind the hall."
    assert topics["hours"] == "The gala hours."


def test_init_db_skips_invalid_rows_and_rejects_bad_json(tmp_path, monkeypatch):
    bad_menu = tmp_path / "bad_menu.json"
    bad_menu.write_text(
        json.dumps([{"name": "Good Item", "price": "Rs. 100"}, {"price": "Rs. 1"}, {"name": "  "}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "MENU_JSON_PATH", bad_menu)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "skipped.db")
    data.init_db()
    assert [row["name"] for row in data.get_menu()] == ["Good Item"]

    not_a_list = tmp_path / "object.json"
    not_a_list.write_text(json.dumps({"name": "Nope"}), encoding="utf-8")
    monkeypatch.setattr(config, "MENU_JSON_PATH", not_a_list)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "object.db")
    with pytest.raises(RuntimeError, match="expected a JSON array"):
        data.init_db()

    monkeypatch.setattr(config, "MENU_JSON_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    with pytest.raises(RuntimeError, match="Unable to load the menu"):
        data.init_db()


def test_load_menu_raises_when_the_menu_is_empty():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("DELETE FROM menu_items")
        conn.commit()
    with pytest.raises(RuntimeError, match="The menu is empty"):
        data.load_menu()


def test_get_menu_filters_and_sorts_by_category_then_name():
    assert [row["name"] for row in data.get_menu()] == [
        "Blue Lemonade",
        "Mixed Fruit Shake",
        "Chicken Burger",
        "Club Sandwich",
        "Patty Burger",
    ]
    assert [row["name"] for row in data.get_menu(item="burger")] == [
        "Chicken Burger",
        "Patty Burger",
    ]
    assert [row["name"] for row in data.get_menu(category="drinks")] == [
        "Blue Lemonade",
        "Mixed Fruit Shake",
    ]
    assert data.get_menu(item="pizza") == []


def test_get_menu_item_exact_then_unique_substring():
    assert data.get_menu_item("chicken burger")["name"] == "Chicken Burger"
    assert data.get_menu_item("lemonade")["name"] == "Blue Lemonade"
    assert data.get_menu_item("burger") is None
    assert data.get_menu_item("pizza") is None
    assert data.get_menu_item("") is None


def test_set_menu_availability_round_trip():
    assert data.set_menu_availability("blue lemonade", False)["available"] == 0
    assert data.get_menu_item("Blue Lemonade")["available"] == 0
    assert data.set_menu_availability("Blue Lemonade", True)["available"] == 1
    assert data.set_menu_availability("Pizza", False) is None


def test_compute_total_formats_and_refuses_prices_without_digits():
    assert data.compute_total([BURGER, LEMONADE]) == "Rs. 900"
    assert data.compute_total([{"name": "Chicken Burger", "quantity": 2, "price": "Rs. 650"}]) == "Rs. 1,300"
    assert data.compute_total([{"name": "x", "quantity": 1, "price": "free"}]) is None


def test_create_order_draft_keeps_one_draft_per_session():
    first = _draft([BURGER])
    assert first["action"] == "created"

    updated = _draft([BURGER, LEMONADE])
    assert updated == {"order_id": first["order_id"], "action": "updated"}

    existing = _draft([BURGER, LEMONADE])
    assert existing == {"order_id": first["order_id"], "action": "existing"}

    pending = _rows("SELECT id, items FROM orders WHERE status = 'PENDING_CONFIRMATION'")
    assert len(pending) == 1
    assert [item["name"] for item in json.loads(pending[0]["items"])] == [
        "Chicken Burger",
        "Blue Lemonade",
    ]

    other_session = _draft([BURGER], session_id="s-2")
    assert other_session["action"] == "created"
    assert other_session["order_id"] != first["order_id"]


# 16 section 2o item 11: a late name or a late "on the house" has to reach the
# dashboard, so the draft reports `updated` whenever this call really changed
# one of them. Only a call that changes nothing stays `existing`.


def test_a_late_name_on_an_unchanged_draft_is_an_update():
    first = _draft([BURGER])
    assert first["action"] == "created"
    assert data.get_order(first["order_id"])["guest_name"] is None

    named = _draft([BURGER], guest_name="Ahmed")

    assert named == {"order_id": first["order_id"], "action": "updated"}
    assert data.get_order(first["order_id"])["guest_name"] == "Ahmed"


def test_the_same_name_again_changes_nothing():
    first = _draft([BURGER], guest_name="Ahmed")
    assert first["action"] == "created"

    again = _draft([BURGER], guest_name="Ahmed")

    assert again == {"order_id": first["order_id"], "action": "existing"}
    assert data.get_order(first["order_id"])["guest_name"] == "Ahmed"


def test_a_different_name_on_an_unchanged_draft_is_an_update():
    first = _draft([BURGER], guest_name="Ahmed")

    corrected = _draft([BURGER], guest_name="Ayesha")

    assert corrected == {"order_id": first["order_id"], "action": "updated"}
    assert data.get_order(first["order_id"])["guest_name"] == "Ayesha"


def test_a_call_with_no_name_keeps_the_stored_one_and_changes_nothing():
    first = _draft([BURGER], guest_name="Ahmed")

    nameless = _draft([BURGER])

    assert nameless == {"order_id": first["order_id"], "action": "existing"}
    assert data.get_order(first["order_id"])["guest_name"] == "Ahmed"


def _complimentary(order_id):
    """The flag as every order event carries it: a real boolean."""
    return data.order_view(data.get_order(order_id))["complimentary"]


def test_on_the_house_arriving_later_is_an_update_once():
    first = data.create_order_draft([BURGER], "Ahmed", "s-1")
    assert first["action"] == "created"
    assert _complimentary(first["order_id"]) is False

    on_the_house = data.create_order_draft([BURGER], "Ahmed", "s-1", complimentary=True)

    assert on_the_house == {"order_id": first["order_id"], "action": "updated"}
    assert _complimentary(first["order_id"]) is True

    # The flag is already 1: setting it again is not a change.
    again = data.create_order_draft([BURGER], "Ahmed", "s-1", complimentary=True)

    assert again == {"order_id": first["order_id"], "action": "existing"}
    assert _complimentary(first["order_id"]) is True


def test_a_later_call_that_does_not_say_on_the_house_leaves_the_flag_alone():
    first = data.create_order_draft([BURGER], "Ahmed", "s-1", complimentary=True)

    ordinary = data.create_order_draft([BURGER], "Ahmed", "s-1")

    assert ordinary == {"order_id": first["order_id"], "action": "existing"}
    assert _complimentary(first["order_id"]) is True


def test_changed_items_are_still_an_update_whatever_else_the_call_brings():
    first = _draft([BURGER])

    more = _draft([BURGER, LEMONADE])

    assert more == {"order_id": first["order_id"], "action": "updated"}
    assert data.get_order(first["order_id"])["items"] == [BURGER, LEMONADE]


def test_changed_items_and_a_new_name_together_are_one_update():
    first = _draft([BURGER])

    both = _draft([BURGER, LEMONADE], guest_name="Ahmed")

    assert both == {"order_id": first["order_id"], "action": "updated"}
    order = data.get_order(first["order_id"])
    assert order["guest_name"] == "Ahmed"
    assert order["items"] == [BURGER, LEMONADE]


def test_create_order_draft_starts_a_new_row_once_the_draft_is_gone():
    first = _draft([BURGER])
    data.update_order_status(first["order_id"], "CONFIRMED")
    second = _draft([LEMONADE])
    assert second["action"] == "created"
    assert second["order_id"] != first["order_id"]


def test_order_view_and_get_order_parse_items():
    order_id = _draft([BURGER, LEMONADE], guest_name="Ahmed")["order_id"]
    order = data.get_order(order_id)
    assert order["items"] == [BURGER, LEMONADE]
    view = data.order_view(order)
    assert view == {
        "id": order_id,
        "items": [BURGER, LEMONADE],
        "status": "PENDING_CONFIRMATION",
        "guest_name": "Ahmed",
        "total": "Rs. 900",
        "timestamp": order["timestamp"],
        "estimated_ready_at": None,
        "ready_at": None,
        # 16 section 2m item 5: in the view, and so in every order event.
        "complimentary": False,
    }
    assert data.get_order(order_id + 500) is None


def test_update_order_status_refuses_skipped_steps_and_changes_nothing():
    order_id = _draft([BURGER])["order_id"]
    data.update_order_status(order_id, "CONFIRMED")

    refused = data.update_order_status(order_id, "READY")
    assert refused == {
        "ok": False,
        "error": "Order is CONFIRMED; mark it PREPARING before READY.",
    }
    after = data.get_order(order_id)
    assert after["status"] == "CONFIRMED"
    assert after["ready_at"] is None
    assert after["estimated_ready_at"] is None

    assert data.update_order_status(order_id, "CONFIRMED")["error"] == "Order is already CONFIRMED."
    assert data.update_order_status(order_id, "NOPE")["error"] == "'NOPE' isn't an order status."
    assert (
        data.update_order_status(order_id + 500, "CONFIRMED")["error"]
        == "There is no order with that number."
    )


def test_update_order_status_sets_estimate_then_ready_at():
    order_id = _draft([BURGER, LEMONADE])["order_id"]
    data.update_order_status(order_id, "CONFIRMED")

    before = datetime.now()
    preparing = data.update_order_status(order_id, "PREPARING")["order"]
    estimated = datetime.fromisoformat(preparing["estimated_ready_at"])
    # The largest prep_seconds among the items: Chicken Burger, 300 s.
    assert timedelta(seconds=299) <= estimated - before <= timedelta(seconds=302)
    assert preparing["ready_at"] is None
    assert data.minutes_left(preparing) == 5

    ready = data.update_order_status(order_id, "READY")["order"]
    assert ready["ready_at"] is not None
    assert data.minutes_left(ready) is None
    assert data.update_order_status(order_id, "COLLECTED")["order"]["status"] == "COLLECTED"


def test_update_order_status_leaves_the_estimate_null_when_no_prep_time_is_known():
    data.set_menu_availability("Blue Lemonade", True)
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE menu_items SET prep_seconds = 0 WHERE name = 'Blue Lemonade'")
        conn.commit()
    order_id = _draft([LEMONADE])["order_id"]
    data.update_order_status(order_id, "CONFIRMED")
    preparing = data.update_order_status(order_id, "PREPARING")["order"]
    assert preparing["estimated_ready_at"] is None
    assert data.minutes_left(preparing) is None


def test_update_order_status_cancel_attention_failed_and_final_states():
    cancelled_id = _draft([BURGER])["order_id"]
    cancelled = data.update_order_status(cancelled_id, "CANCELLED", reason="changed mind")["order"]
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "changed mind"
    assert (
        data.update_order_status(cancelled_id, "CONFIRMED")["error"]
        == "Order is CANCELLED; it can't change any more."
    )

    flagged_id = _draft([BURGER], session_id="s-flag")["order_id"]
    data.update_order_status(flagged_id, "CONFIRMED")
    assert data.update_order_status(flagged_id, "REQUIRES_ATTENTION")["ok"] is True
    assert data.update_order_status(flagged_id, "PREPARING")["ok"] is True

    failed_id = _draft([BURGER], session_id="s-fail")["order_id"]
    data.update_order_status(failed_id, "CONFIRMED")
    assert data.update_order_status(failed_id, "FAILED")["ok"] is True
    assert (
        data.update_order_status(failed_id, "PREPARING")["error"]
        == "Order is FAILED; it can't change any more."
    )

    backwards_id = _draft([BURGER], session_id="s-back")["order_id"]
    data.update_order_status(backwards_id, "CONFIRMED")
    data.update_order_status(backwards_id, "PREPARING")
    data.update_order_status(backwards_id, "READY")
    assert (
        data.update_order_status(backwards_id, "PREPARING")["error"]
        == "Order is READY; it can't be marked PREPARING."
    )


def test_expire_pending_orders_cancels_and_publishes_with_a_null_session_id():
    order_id = _draft([BURGER])["order_id"]
    _backdate(order_id, config.PENDING_ORDER_TTL_S + 30)
    event_bus.PUBLISHED.clear()

    assert data.expire_pending_orders() == [order_id]

    expired = _rows("SELECT status, cancel_reason FROM orders WHERE id = ?", (order_id,))[0]
    assert expired == {"status": "CANCELLED", "cancel_reason": "expired"}
    assert len(event_bus.PUBLISHED) == 1
    event = event_bus.PUBLISHED[0]
    assert event["type"] == "order_updated"
    assert event["session_id"] is None
    assert event["order"]["status"] == "CANCELLED"
    assert isinstance(event["event_id"], int)
    assert event["timestamp"]

    # Already cancelled: nothing more to expire and nothing more published.
    assert data.expire_pending_orders() == []
    assert len(event_bus.PUBLISHED) == 1


def test_a_fresh_draft_is_not_expired():
    order_id = _draft([BURGER])["order_id"]
    assert data.expire_pending_orders() == []
    assert data.get_order(order_id)["status"] == "PENDING_CONFIRMATION"


def test_attach_guest_name_only_fills_unnamed_live_orders():
    unnamed = _draft([BURGER])["order_id"]
    data.update_order_status(unnamed, "CONFIRMED")
    cancelled = _draft([BURGER])["order_id"]
    data.update_order_status(cancelled, "CANCELLED", reason="no")
    named = _draft([LEMONADE], guest_name="Ahmed")["order_id"]

    updated = data.attach_guest_name("s-1", "Sara")

    assert [order["id"] for order in updated] == [unnamed]
    assert data.get_order(unnamed)["guest_name"] == "Sara"
    assert data.get_order(named)["guest_name"] == "Ahmed"
    assert data.get_order(cancelled)["guest_name"] is None
    assert data.attach_guest_name("s-1", "  ") == []
    assert data.attach_guest_name(None, "Sara") == []


def test_find_orders_for_includes_a_flagged_order():
    flagged = _draft([BURGER], guest_name="Ahmed", session_id="s-flagged")["order_id"]
    data.update_order_status(flagged, "CONFIRMED")
    data.update_order_status(flagged, "REQUIRES_ATTENTION")

    assert [o["id"] for o in data.find_orders_for("s-flagged", None)] == [flagged]
    assert [o["id"] for o in data.find_orders_for(None, "ahmed")] == [flagged]


def test_find_orders_for_matches_session_or_name_newest_first():
    older = _draft([BURGER], guest_name="Ahmed", session_id="s-old")["order_id"]
    data.update_order_status(older, "CONFIRMED")
    newer = _draft([LEMONADE], session_id="s-new")["order_id"]
    data.update_order_status(newer, "CONFIRMED")
    draft_only = _draft([BURGER], session_id="s-new")["order_id"]

    assert [o["id"] for o in data.find_orders_for("s-new", None)] == [newer]
    assert [o["id"] for o in data.find_orders_for("s-new", "ahmed")] == [newer, older]
    assert [o["id"] for o in data.find_orders_for(None, "AHMED")] == [older]
    assert data.find_orders_for(None, None) == []
    assert draft_only not in [o["id"] for o in data.find_orders_for("s-new", None)]


def test_list_orders_scopes_and_counts():
    active = _draft([BURGER], session_id="s-a")["order_id"]
    data.update_order_status(active, "CONFIRMED")
    done = _draft([LEMONADE], session_id="s-b")["order_id"]
    data.update_order_status(done, "CANCELLED", reason="no")
    _draft([BURGER], session_id="s-c")

    assert [o["id"] for o in data.list_orders("active")["orders"]] == [active]
    assert [o["id"] for o in data.list_orders("completed")["orders"]] == [done]
    assert data.list_orders("all")["counts"] == {"active": 1, "completed": 1, "all": 3}
    assert len(data.list_orders("all", limit=2)["orders"]) == 2


def test_list_orders_counts_a_flagged_order_as_active():
    flagged = _draft([BURGER], session_id="s-flag")["order_id"]
    data.update_order_status(flagged, "CONFIRMED")
    data.update_order_status(flagged, "REQUIRES_ATTENTION")

    assert [o["id"] for o in data.list_orders("active")["orders"]] == [flagged]
    assert data.list_orders("all")["counts"] == {"active": 1, "completed": 0, "all": 1}
    assert data.list_orders("completed")["orders"] == []


def test_feedback_is_stored_with_only_a_real_rating():
    feedback_id = data.create_feedback("chicken burger", "Loved it", 5, "Ahmed")
    row = _rows("SELECT * FROM feedback WHERE id = ?", (feedback_id,))[0]
    assert row["subject"] == "chicken burger"
    assert row["rating"] == 5
    assert row["guest_name"] == "Ahmed"
    assert _rows(
        "SELECT rating FROM feedback WHERE id = ?",
        (data.create_feedback("service", "Fine", None, None),),
    )[0]["rating"] is None


def test_visitor_profile_create_visit_and_corrections():
    assert data.get_visitor("ahmed") is None
    created = data.create_visitor("ahmed", "Ahmed")
    assert created["visits"] == 1
    assert created["first_seen"] == created["last_seen"]

    assert data.record_visit("ahmed")["visits"] == 2
    assert data.update_visitor("ahmed", display_name="Ahmad")["display_name"] == "Ahmad"
    assert data.update_visitor("ahmed", favorite_item="Blue Lemonade")["favorite_item"] == "Blue Lemonade"
    assert data.update_visitor("nobody", display_name="X") is None

    assert [v["name_key"] for v in data.list_visitors()] == ["ahmed"]
    assert data.list_visitors()[0]["returning"] is True
    assert data.delete_visitor("ahmed") is True
    assert data.delete_visitor("ahmed") is False
    assert data.get_visitor("ahmed") is None


def test_refresh_visitor_after_order_picks_the_highest_quantity_favourite():
    data.create_visitor("ahmed", "Ahmed")
    first = _draft(
        [{"name": "Blue Lemonade", "quantity": 2, "price": "Rs. 250"}],
        guest_name="Ahmed",
        session_id="s-1",
    )["order_id"]
    data.update_order_status(first, "CONFIRMED")
    profile = data.refresh_visitor_after_order(data.get_order(first))
    assert profile["favorite_item"] == "Blue Lemonade"
    assert profile["last_order"] == "Blue Lemonade"

    second = _draft([BURGER], guest_name="Ahmed", session_id="s-2")["order_id"]
    data.update_order_status(second, "CONFIRMED")
    profile = data.refresh_visitor_after_order(data.get_order(second))
    # Blue Lemonade still leads on total quantity (2 against 1).
    assert profile["favorite_item"] == "Blue Lemonade"
    assert profile["last_order"] == "Chicken Burger"

    third = _draft(
        [{"name": "Chicken Burger", "quantity": 3, "price": "Rs. 650"}],
        guest_name="Ahmed",
        session_id="s-3",
    )["order_id"]
    data.update_order_status(third, "CONFIRMED")
    assert data.refresh_visitor_after_order(data.get_order(third))["favorite_item"] == "Chicken Burger"


def test_refresh_visitor_after_order_needs_a_name_and_a_profile():
    order_id = _draft([BURGER])["order_id"]
    assert data.refresh_visitor_after_order(data.get_order(order_id)) is None
    named = _draft([BURGER], guest_name="Ghost", session_id="s-g")["order_id"]
    assert data.refresh_visitor_after_order(data.get_order(named)) is None


def test_refresh_visitor_after_order_ignores_unconfirmed_orders():
    data.create_visitor("sara", "Sara")
    draft_id = _draft([BURGER], guest_name="Sara")["order_id"]
    assert data.refresh_visitor_after_order(data.get_order(draft_id))["favorite_item"] is None


def test_memory_event_shape():
    data.create_visitor("ahmed", "Ahmed")
    data.record_visit("ahmed")
    profile = data.get_visitor("ahmed")
    event = data.memory_event(profile)
    assert event["type"] == "memory_updated"
    assert event["name"] == "Ahmed"
    assert event["visits"] == 2
    assert event["returning"] is True
    assert event["last_seen"] == profile["last_seen"]
    assert "session_id" not in event


def test_get_business_info_substring_and_all():
    assert [row["topic"] for row in data.get_business_info()] == [
        "about_the_host", "complimentary_guests", "halal", "hours", "how_it_works",
        "payment", "privacy", "project", "stall", "team", "technical",
    ]
    assert data.get_business_info("HOUR")[0]["answer"].startswith("We're open")
    assert data.get_business_info("parking") == []


def test_log_action_and_log_system_event_never_raise(monkeypatch):
    data.log_action("build_order", {"items": []}, {"source": "order"})
    logged = _rows("SELECT tool, input_args, result FROM agent_log")[0]
    assert logged["tool"] == "build_order"
    assert json.loads(logged["input_args"]) == {"items": []}

    data.log_system_event(
        "agent_activity",
        "system",
        {"kind": "order", "label": "Order #1 created", "detail": "Chicken Burger"},
    )
    data.log_system_event("session_started", "system", {})
    activity = data.list_activity()
    assert len(activity) == 1
    assert activity[0]["kind"] == "order"
    assert activity[0]["label"] == "Order #1 created"
    assert activity[0]["detail"] == "Chicken Burger"
    assert activity[0]["timestamp"]

    monkeypatch.setattr(config, "DB_PATH", "Z:/nowhere/missing.db")
    data.log_action("build_order", {}, {})
    data.log_system_event("failure", "system", {"detail": "x"})


def test_get_analytics_reports_only_real_numbers():
    assert data.get_analytics() == {
        "date": datetime.now().date().isoformat(),
        "orders": 0,
        "interactions": 0,
        "named_visitors": 0,
        "returning_visitors": 0,
        "popular_items": [],
        "average_order_to_ready_seconds": None,
    }

    data.create_visitor("ahmed", "Ahmed")
    data.record_visit("ahmed")
    data.create_visitor("sara", "Sara")
    data.log_system_event("session_started", "system", {})
    counted = _draft(
        [{"name": "Blue Lemonade", "quantity": 3, "price": "Rs. 250"}, BURGER],
        guest_name="Ahmed",
    )["order_id"]
    data.update_order_status(counted, "CONFIRMED")
    ignored = _draft([BURGER], session_id="s-ignored")["order_id"]
    data.update_order_status(ignored, "CANCELLED", reason="no")

    analytics = data.get_analytics()
    assert analytics["orders"] == 1
    assert analytics["interactions"] == 1
    assert analytics["named_visitors"] == 2
    assert analytics["returning_visitors"] == 1
    assert analytics["popular_items"] == [
        {"name": "Blue Lemonade", "percent": 75},
        {"name": "Chicken Burger", "percent": 25},
    ]
    assert analytics["average_order_to_ready_seconds"] is None

    data.update_order_status(counted, "PREPARING")
    data.update_order_status(counted, "READY")
    assert data.get_analytics()["average_order_to_ready_seconds"] is not None
