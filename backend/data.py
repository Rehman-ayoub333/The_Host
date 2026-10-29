import json
import logging
import math
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import config
import event_bus


log = logging.getLogger(__name__)

# A REQUIRES_ATTENTION order still needs the operator, so it counts as active
# everywhere (03 section 8, 15 section 4).
#
# 16 section 2zf item 3(a): AWAITING_PAYMENT joins both groups. It is a placed
# order -- the team has to take money for it, so the Orders panel must show it
# -- and it counts towards a guest's favourite like any other order they placed,
# which is what `confirm_order` refreshes the moment it is placed.
ACTIVE_STATUSES = (
    "AWAITING_PAYMENT", "CONFIRMED", "PREPARING", "READY", "REQUIRES_ATTENTION",
)
COMPLETED_STATUSES = ("COLLECTED", "CANCELLED", "FAILED")
CONFIRMED_OR_LATER = (
    "AWAITING_PAYMENT", "CONFIRMED", "PREPARING", "READY", "COLLECTED",
)
FINAL_STATUSES = ("COLLECTED", "CANCELLED", "FAILED")

# 08 section 5 / 15 section 4: the only allowed order-status transitions.
#
# 16 section 2zf item 3(a) amends both: an order is placed before it is paid, so
# a draft that is not on the house stops at AWAITING_PAYMENT and only reaches
# CONFIRMED -- the status the kitchen works from -- once the team has marked the
# money taken. A complimentary order still goes straight to CONFIRMED.
ALLOWED_TRANSITIONS = {
    "PENDING_CONFIRMATION": (
        "AWAITING_PAYMENT",
        "CONFIRMED",
        "CANCELLED",
        "REQUIRES_ATTENTION",
    ),
    "AWAITING_PAYMENT": ("CONFIRMED", "CANCELLED", "REQUIRES_ATTENTION"),
    "CONFIRMED": ("PREPARING", "CANCELLED", "REQUIRES_ATTENTION", "FAILED"),
    "PREPARING": ("READY", "CANCELLED", "REQUIRES_ATTENTION", "FAILED"),
    "READY": ("COLLECTED", "REQUIRES_ATTENTION", "FAILED"),
    "REQUIRES_ATTENTION": ("PREPARING", "READY", "COLLECTED", "CANCELLED"),
    "COLLECTED": (),
    "CANCELLED": (),
    "FAILED": (),
}
ORDER_STATUSES = tuple(ALLOWED_TRANSITIONS)

# The forward chain, used only to word a refusal ("mark it PREPARING before
# READY"). 16 section 2zf item 3(a) puts the payment step into it, so a kitchen
# press on an order nobody has paid for says which step was skipped.
_STATUS_CHAIN = (
    "PENDING_CONFIRMATION",
    "AWAITING_PAYMENT",
    "CONFIRMED",
    "PREPARING",
    "READY",
    "COLLECTED",
)

_MENU_COLUMNS = (
    "name, category, price, description, image_url, available, prep_seconds, "
    "ingredients, allergens, tags, add_ons"
)
# 16 section 2i item 4: the four optional facts guests ask about, stored as JSON
# text. NULL means "unknown", which is never the same as "none" -- the five
# current items carry no invented values, so they simply leave these out.
MENU_OPTIONAL_FIELDS = ("ingredients", "allergens", "tags", "add_ons")
MENU_TAGS = ("spicy", "sweet", "vegetarian", "cold", "hot")
_ORDER_COLUMNS = (
    "id, timestamp, guest_name, items, status, announced, session_id, "
    "cancel_reason, estimated_ready_at, ready_at, orphaned_at, complimentary, "
    "payment_method, placed_at, paid_at, order_no"
)

# 16 section 2z item 2: how the guest paid. Since 2zf item 3 it is recorded
# twice: the method the guest said they would use, stored when the order is
# placed, and the one the team really took, stored when they mark it paid.
PAYMENT_METHODS = ("CASH", "QR")

# 16 section 2zf item 3(d): when the team marked the money taken. NULL on every
# order from before this phase, including ones already collected -- their
# payment was never timed, and guessing a time would be inventing history.
# The statuses that may carry a payment_method at all.
PAYMENT_STATUSES = ("AWAITING_PAYMENT", "CONFIRMED", "COLLECTED")

# 16 section 2l item 5: how each status is described to a guest. A draft is not
# a placed order, and THE HOST must never let one sound like one.
STATUS_TEXT = {
    "PENDING_CONFIRMATION": "waiting for your confirmation",
    # 16 section 2zf item 3(a): placed, but not with the kitchen until the guest
    # has paid at the counter and the team has marked it.
    "AWAITING_PAYMENT": "waiting for payment at the counter",
    "CONFIRMED": "confirmed and queued",
    "PREPARING": "being prepared",
    "READY": "ready to collect",
    "COLLECTED": "collected",
    "CANCELLED": "cancelled",
    "FAILED": "failed",
    "REQUIRES_ATTENTION": "with a team member",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def now_iso() -> str:
    """The same booth-local stamp every row and event carries (03 section 3)."""
    return _now()


def _today() -> str:
    return datetime.now().date().isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _like(value: str) -> str:
    escaped = str(value).lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _encode_menu_list(field: str, value, row_number: int) -> str | None:
    """16 section 2i item 4: a list of real strings, or NULL for "unknown"."""
    if value is None:
        return None
    if not isinstance(value, list):
        log.warning("menu row %s: %s is not a list, ignored", row_number, field)
        return None
    cleaned: list[str] = []
    for entry in value:
        text = " ".join(str(entry).split())
        if not text:
            continue
        if field == "tags":
            text = text.lower()
            if text not in MENU_TAGS:
                log.warning("menu row %s: unknown tag %r, ignored", row_number, text)
                continue
        if text not in cleaned:
            cleaned.append(text)
    # An empty result would claim the stall has none of these, which is a
    # different statement from not knowing. It stays unknown.
    return json.dumps(cleaned) if cleaned else None


def _menu_from_row(row) -> dict:
    """The menu row as the tools see it: an optional field absent when unknown."""
    item = dict(row)
    for field in MENU_OPTIONAL_FIELDS:
        raw = item.pop(field, None)
        if raw is None:
            continue
        try:
            value = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("menu item %r: unreadable %s, ignored", item.get("name"), field)
            continue
        if isinstance(value, list) and value:
            item[field] = value
    return item


def _load_json_list(path, label: str) -> list:
    try:
        with path.open(encoding="utf-8") as file:
            rows = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load {label}: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError(f"Unable to load {label}: expected a JSON array.")
    return rows


def init_db() -> list[tuple[str, bool]]:
    with closing(_connect()) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS menu_items (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL DEFAULT '',
                price TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                available INTEGER NOT NULL DEFAULT 1,
                prep_seconds INTEGER NOT NULL DEFAULT 0,
                ingredients TEXT,
                allergens TEXT,
                tags TEXT,
                add_ons TEXT
            )"""
        )
        # 16 section 2i item 4: a database from an earlier phase has none of the
        # optional columns yet. They arrive NULL, which reads as unknown.
        existing = {
            row["name"] for row in conn.execute("PRAGMA table_info(menu_items)")
        }
        for field in MENU_OPTIONAL_FIELDS:
            if field not in existing:
                conn.execute(f"ALTER TABLE menu_items ADD COLUMN {field} TEXT")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS orders (
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
                payment_method TEXT,
                placed_at TEXT,
                paid_at TEXT,
                order_no INTEGER
            )"""
        )
        # 16 section 2l item 4: when a conversation broke and left this draft
        # behind. NULL for every order that ended its conversation normally.
        order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        if "orphaned_at" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN orphaned_at TEXT")
        # 16 section 2m item 5: on the house for a guest of honour. The default
        # carries the migration: every order already in the database is an
        # ordinary, paid one, so existing rows arrive 0.
        if "complimentary" not in order_columns:
            conn.execute(
                "ALTER TABLE orders ADD COLUMN complimentary INTEGER NOT NULL DEFAULT 0"
            )
        # 16 section 2z item 2: cash or QR, recorded at collection. It arrives
        # NULL on every existing row, which the Earnings panel reports as
        # "collected without a payment type" rather than guessing.
        if "payment_method" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN payment_method TEXT")
        # 16 section 2zf item 3(d): when the team marked the money taken. It
        # arrives NULL, and stays NULL on orders that are already past CONFIRMED
        # with a payment_method on them: those were collected before pay-first
        # existed, and their payment was never timed. The Earnings panel counts
        # them from their status instead of inventing a time for them.
        if "paid_at" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN paid_at TEXT")
        # 16 section 2zh item 3(a): when the order was placed. It arrives NULL,
        # and stays NULL on every order placed before this phase: those were
        # timed from their `timestamp`, and the sweeper still falls back to it.
        if "placed_at" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN placed_at TEXT")
        # 16 section 2zi item 3(a): the number the guest is given, 1, 2, 3 and so
        # on through the day. Existing rows stay NULL: they were never numbered,
        # and the only number anyone knew them by was their id.
        if "order_no" not in order_columns:
            conn.execute("ALTER TABLE orders ADD COLUMN order_no INTEGER")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                subject TEXT NOT NULL,
                comment TEXT NOT NULL,
                rating INTEGER,
                guest_name TEXT
            )"""
        )
        # 16 section 2zi item 4(b): the guests' own feedback forms, pulled in
        # from Netlify. Kept apart from the `feedback` table above, which is
        # what a guest asked THE HOST to pass on: the two are different things
        # and the dashboard shows them on separate tabs. `netlify_id` is
        # unique, so importing the same submission twice changes nothing.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS form_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                netlify_id TEXT NOT NULL UNIQUE,
                created_at TEXT,
                item TEXT,
                overall_rating INTEGER,
                taste_rating INTEGER,
                presentation_rating INTEGER,
                value_rating TEXT,
                liked_most TEXT,
                improvement TEXT,
                buy_again TEXT,
                one_word TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS visitors (
                name_key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                visits INTEGER NOT NULL DEFAULT 1,
                favorite_item TEXT,
                last_order TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS business_info (
                topic TEXT PRIMARY KEY,
                answer TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS system_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT 'system',
                detail TEXT NOT NULL
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                input_args TEXT NOT NULL,
                result TEXT NOT NULL,
                session_id TEXT
            )"""
        )
        # 16 section 2t item 7: which conversation a tool call belongs to. The
        # 22 Oct retest could only be read by matching timestamps by eye, because
        # this table had no session of its own. NULL for every row logged before
        # the column existed.
        agent_log_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(agent_log)")
        }
        if "session_id" not in agent_log_columns:
            conn.execute("ALTER TABLE agent_log ADD COLUMN session_id TEXT")

        # 16 section 2zb item 8: the menu follows menu.json at every startup, as
        # the stall information already does. Until this it was seeded once,
        # whole-table (`COUNT(*) == 0`), so editing the file changed nothing on
        # a laptop that already had a menu -- and Rehman's real menu is still to
        # go in. Each item is inserted or updated **by name**; nothing anywhere
        # references a menu row by id or by foreign key (the table's primary key
        # IS the name, there is no id column and no REFERENCES in the schema;
        # an order keeps its own copy of the item names and the prices they were
        # bought at, in orders.items). The operator's sold-out toggle wins over
        # the file: for an item already stored, `available` is left exactly as it
        # is, so a restart mid-gala does not put a finished item back on sale.
        # A new item starts with whatever the file says, available by default,
        # and an item no longer in the file is removed.
        menu_changes = []
        stored = {
            row["name"].lower(): row
            for row in conn.execute(f"SELECT {_MENU_COLUMNS} FROM menu_items")
        }
        in_file = set()
        rows = _load_json_list(config.MENU_JSON_PATH, "the menu")
        for row_number, row in enumerate(rows, start=1):
            try:
                name = str(row["name"]).strip()
                if not name:
                    raise ValueError("empty name")
                fields = (
                    str(row.get("category", "")),
                    str(row.get("price", "")),
                    str(row.get("description", "")),
                    str(row.get("image_url", "")),
                    max(0, int(row.get("prep_seconds", 0))),
                    *(
                        _encode_menu_list(field, row.get(field), row_number)
                        for field in MENU_OPTIONAL_FIELDS
                    ),
                )
                current = stored.get(name.lower())
                in_file.add(name.lower())
                if current is None:
                    conn.execute(
                        f"""INSERT INTO menu_items ({_MENU_COLUMNS})
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            name,
                            *fields[:4],
                            int(bool(row.get("available", True))),
                            *fields[4:],
                        ),
                    )
                    menu_changes.append((name, bool(row.get("available", True))))
                    continue
                was = (
                    current["category"],
                    current["price"],
                    current["description"],
                    current["image_url"],
                    current["prep_seconds"],
                    *(current[field] for field in MENU_OPTIONAL_FIELDS),
                )
                if was == fields and current["name"] == name:
                    continue
                conn.execute(
                    """UPDATE menu_items SET name = ?, category = ?, price = ?,
                       description = ?, image_url = ?, prep_seconds = ?,
                       ingredients = ?, allergens = ?, tags = ?, add_ons = ?
                       WHERE LOWER(name) = ?""",
                    (name, *fields, name.lower()),
                )
                menu_changes.append((name, bool(current["available"])))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                log.warning("skipped menu row %s: %s", row_number, exc)

        for key, current in stored.items():
            if key in in_file:
                continue
            conn.execute("DELETE FROM menu_items WHERE LOWER(name) = ?", (key,))
            # Gone from the menu, so nothing can order it any more.
            menu_changes.append((current["name"], False))
        if menu_changes:
            log.info("menu synced from the file: %s changed", len(menu_changes))

        # 16 section 2k item 7 added four topics to the seed file, and a booth
        # laptop already has a database with the first two in it. Seeding only
        # an empty table left the identity topics unreachable: `get_business_info`
        # returned found=False and THE HOST answered from its own idea of itself,
        # which is the 2k item 1(d) failure that phase existed to fix.
        #
        # 16 section 2za item 8: the JSON is the source of truth, so a topic in
        # it now overwrites the stored answer at every startup. Until this, the
        # row was inserted only when absent, which is why 21 Part B's new
        # complimentary_guests text never reached a database that already had
        # that topic -- the stall would have gone on saying the chief guest is on
        # the house. A stored topic that the JSON does not mention is left alone.
        # Nothing else writes this table: the only other access is the read in
        # `get_business_info`, and no endpoint or dashboard control edits it.
        rows = _load_json_list(config.BUSINESS_INFO_JSON_PATH, "the stall information")
        for row_number, row in enumerate(rows, start=1):
            try:
                topic = str(row["topic"]).strip()
                answer = str(row["answer"]).strip()
                if not topic or not answer:
                    raise ValueError("empty topic or answer")
                conn.execute(
                    "INSERT INTO business_info (topic, answer) VALUES (?, ?) "
                    "ON CONFLICT(topic) DO UPDATE SET answer = excluded.answer",
                    (topic, answer),
                )
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
                log.warning("skipped stall information row %s: %s", row_number, exc)

        conn.commit()
    # 16 section 2zb item 8: what the menu sync changed, for the one
    # `menu_updated` the caller publishes once the event loop exists. An empty
    # list means the file and the database already agreed, and nothing is
    # published.
    return menu_changes


def load_menu() -> int:
    with closing(_connect()) as conn:
        count = int(conn.execute("SELECT COUNT(*) FROM menu_items").fetchone()[0])
    if count == 0:
        raise RuntimeError(
            "The menu is empty. Add items to data/menu.json and restart; "
            "the stall must never open without a menu."
        )
    return count


def get_menu(item=None, category=None) -> list[dict]:
    clauses, params = [], []
    if item:
        clauses.append("LOWER(name) LIKE ? ESCAPE '\\'")
        params.append(_like(item))
    if category:
        clauses.append("LOWER(category) = ?")
        params.append(str(category).strip().lower())
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_MENU_COLUMNS} FROM menu_items{where} ORDER BY LOWER(category), LOWER(name)",
            params,
        ).fetchall()
    return [_menu_from_row(row) for row in rows]


def get_menu_item(name) -> dict | None:
    needle = str(name or "").strip()
    if not needle:
        return None
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_MENU_COLUMNS} FROM menu_items WHERE LOWER(name) = ?",
            (needle.lower(),),
        ).fetchone()
        if row is not None:
            return _menu_from_row(row)
        rows = conn.execute(
            f"SELECT {_MENU_COLUMNS} FROM menu_items WHERE LOWER(name) LIKE ? ESCAPE '\\'",
            (_like(needle),),
        ).fetchall()
    return _menu_from_row(rows[0]) if len(rows) == 1 else None


def set_menu_availability(name, available) -> dict | None:
    needle = str(name or "").strip()
    if not needle:
        return None
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE menu_items SET available = ? WHERE LOWER(name) = ?",
            (int(bool(available)), needle.lower()),
        )
        conn.commit()
        row = conn.execute(
            f"SELECT {_MENU_COLUMNS} FROM menu_items WHERE LOWER(name) = ?",
            (needle.lower(),),
        ).fetchone()
    return _menu_from_row(row) if row else None


def compute_total(items) -> str | None:
    total = 0
    for entry in items or []:
        digits = re.sub(r"[^0-9]", "", str((entry or {}).get("price") or ""))
        if not digits:
            return None
        try:
            quantity = int((entry or {}).get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        total += int(digits) * max(1, quantity)
    return f"Rs. {total:,}"


def _order_from_row(row) -> dict:
    order = dict(row)
    try:
        items = json.loads(order["items"])
    except (TypeError, ValueError):
        items = []
    order["items"] = items if isinstance(items, list) else []
    return order


def order_view(order) -> dict:
    items = [
        {
            "name": (entry or {}).get("name"),
            "quantity": (entry or {}).get("quantity"),
            "price": (entry or {}).get("price"),
        }
        for entry in order.get("items") or []
    ]
    return {
        "id": order["id"],
        # 16 section 2zi item 3(b): the guest-facing number, null while the
        # order is still a draft. The id stays, because the operator API and the
        # dashboard key on it (item 3(d)); `number` is the only thing shown.
        "number": order.get("order_no"),
        "items": items,
        "status": order["status"],
        "guest_name": order.get("guest_name"),
        "total": compute_total(items),
        "timestamp": order.get("timestamp"),
        "estimated_ready_at": order.get("estimated_ready_at"),
        "ready_at": order.get("ready_at"),
        # 16 section 2m item 5: on the house, in the view and so in every order
        # event. The prices and the total are the stored ones either way, for
        # the record.
        "complimentary": bool(order.get("complimentary")),
        # 16 section 2z item 2: in the view, so every order event carries it.
        # Since 2zf item 3(b) it is set the moment the order is placed -- the
        # method the guest said they would use -- and replaced by the one the
        # team really took when they mark it paid.
        "payment_method": order.get("payment_method"),
        # 16 section 2zf item 3(d): when the team marked it paid, or null. This
        # is what tells a card "Paid · Cash" from "Waiting for payment", and
        # what the Earnings panel counts.
        "paid_at": order.get("paid_at"),
    }


def minutes_left(order) -> int | None:
    if order.get("status") != "PREPARING" or not order.get("estimated_ready_at"):
        return None
    try:
        target = datetime.fromisoformat(order["estimated_ready_at"])
    except (TypeError, ValueError):
        return None
    return max(0, math.ceil((target - datetime.now()).total_seconds() / 60))


def expire_pending_orders(ttl_seconds: int = config.PENDING_ORDER_TTL_S) -> list[int]:
    cutoff = (datetime.now() - timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        stale = conn.execute(
            "SELECT id FROM orders WHERE status = 'PENDING_CONFIRMATION' AND timestamp < ?",
            (cutoff,),
        ).fetchall()
        if not stale:
            return []
        ids = [int(row["id"]) for row in stale]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE orders SET status = 'CANCELLED', cancel_reason = 'expired' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    for row in rows:
        event_bus.publish_threadsafe(
            {
                "type": "order_updated",
                "order": order_view(_order_from_row(row)),
                "session_id": None,
            }
        )
    return ids


def expire_unpaid_orders(ttl_seconds: int = None) -> list[int]:
    """16 section 2zf item 3(f): a placed order nobody ever paid for.

    Pay-first means an order can sit AWAITING_PAYMENT for ever if the guest
    never reaches the counter, holding a slot in the Orders panel and a figure
    in "Waiting for payment". One this old is cancelled with the reason
    `unpaid`, by the same sweeper that expires abandoned drafts.

    16 section 2zh item 3(a): the age is measured from `placed_at`, the moment
    the guest was told to go and pay. It used to be measured from `timestamp`,
    when the draft was first built, so a guest who spent minutes deciding
    before placing the order got less than the full ten to reach the counter --
    and a draft rebuilt from an earlier conversation could be swept almost at
    once. An order placed before this phase has no `placed_at`, so for those
    `timestamp` is still the only evidence there is and the fallback uses it.
    The activity row belongs to the caller (`main`), because `summaries` reads
    this module and cannot be imported from it.
    """
    window = config.PAYMENT_TTL_S if ttl_seconds is None else ttl_seconds
    cutoff = (datetime.now() - timedelta(seconds=window)).isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        stale = conn.execute(
            "SELECT id FROM orders WHERE status = 'AWAITING_PAYMENT' "
            "AND COALESCE(placed_at, timestamp) < ?",
            (cutoff,),
        ).fetchall()
        if not stale:
            return []
        ids = [int(row["id"]) for row in stale]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE orders SET status = 'CANCELLED', cancel_reason = 'unpaid' "
            f"WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    for row in rows:
        log.info("order unpaid order %s", int(row["id"]))
        event_bus.publish_threadsafe(
            {
                "type": "order_updated",
                "order": order_view(_order_from_row(row)),
                "session_id": None,
            }
        )
    return ids


def orphan_draft(order_id) -> bool:
    """16 section 2l item 4: a conversation broke; keep this draft and note when.

    It stays PENDING_CONFIRMATION, so it is still a draft and nothing else about
    it changes. 2a item 17 still cancels a draft whose conversation ended
    normally -- this is only for an end by failure.
    """
    with closing(_connect()) as conn:
        changed = conn.execute(
            "UPDATE orders SET orphaned_at = ? "
            "WHERE id = ? AND status = 'PENDING_CONFIRMATION'",
            (_now(), int(order_id)),
        ).rowcount
        conn.commit()
    return bool(changed)


def latest_orphan_draft(within_seconds: int = None) -> dict | None:
    """The most recent unclaimed orphan, if it is still inside the window.

    2l item 4: only the most recent one is ever offered.
    """
    window = config.ORPHAN_DRAFT_S if within_seconds is None else within_seconds
    cutoff = (datetime.now() - timedelta(seconds=window)).isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders "
            "WHERE status = 'PENDING_CONFIRMATION' AND orphaned_at IS NOT NULL "
            "AND orphaned_at >= ? ORDER BY orphaned_at DESC, id DESC LIMIT 1",
            (cutoff,),
        ).fetchone()
    return _order_from_row(row) if row is not None else None


def claim_orphan_draft(order_id, session_id) -> dict | None:
    """Hand the orphan to the conversation that is about to offer it.

    The new session takes the draft over, so every existing order rule -- who
    owns it, confirming it, cancelling it -- applies unchanged.
    """
    with closing(_connect()) as conn:
        changed = conn.execute(
            "UPDATE orders SET orphaned_at = NULL, session_id = ? "
            "WHERE id = ? AND status = 'PENDING_CONFIRMATION'",
            (session_id, int(order_id)),
        ).rowcount
        conn.commit()
        if not changed:
            return None
        row = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id = ?", (int(order_id),)
        ).fetchone()
    return _order_from_row(row) if row is not None else None


def abandon_orphan_drafts(within_seconds: int = None) -> list[int]:
    """2l item 4: an orphan nobody came back for is cancelled as `abandoned`."""
    window = config.ORPHAN_DRAFT_S if within_seconds is None else within_seconds
    cutoff = (datetime.now() - timedelta(seconds=window)).isoformat(timespec="seconds")
    with closing(_connect()) as conn:
        stale = conn.execute(
            "SELECT id FROM orders WHERE status = 'PENDING_CONFIRMATION' "
            "AND orphaned_at IS NOT NULL AND orphaned_at < ?",
            (cutoff,),
        ).fetchall()
        if not stale:
            return []
        ids = [int(row["id"]) for row in stale]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            "UPDATE orders SET status = 'CANCELLED', cancel_reason = 'abandoned', "
            f"orphaned_at = NULL WHERE id IN ({placeholders})",
            ids,
        )
        conn.commit()
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    for row in rows:
        order = _order_from_row(row)
        log.info("draft abandoned order %s", order["id"])
        event_bus.publish_threadsafe(
            {"type": "order_updated", "order": order_view(order), "session_id": None}
        )
        _abandoned_row(order)
    return ids


def _abandoned_row(order) -> None:
    """The `Order #<n> cancelled` activity row 2l item 4 asks for.

    `summaries` is imported here rather than at module scope because it reads
    this module, and a top-level import would be circular.
    """
    import summaries

    summaries.emit_activity("order", f"Order #{order['id']} cancelled", None, None)


def find_orders_today(guest_name) -> list[dict]:
    """16 section 2l item 5: today's orders under this name, every status."""
    name = " ".join(str(guest_name or "").split()).lower()
    if not name:
        return []
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders "
            "WHERE LOWER(guest_name) = ? AND DATE(timestamp) = ? ORDER BY id DESC",
            (name, _today()),
        ).fetchall()
    return [_order_from_row(row) for row in rows]


def create_order_draft(items, guest_name, session_id, complimentary=False) -> dict:
    expire_pending_orders()
    payload = json.dumps(items)
    on_the_house = 1 if complimentary else 0
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT id, items, guest_name, complimentary FROM orders "
            "WHERE session_id = ? AND status = 'PENDING_CONFIRMATION' "
            "ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is not None:
            # 16 section 2o item 11: a late name or a late "on the house" has to
            # reach the dashboard, so the caller is told the draft was `updated`
            # whenever this call really changed one of them. Only a call that
            # changes nothing at all is `existing`, which publishes no event.
            changed = False
            # 16 section 2l item 3: the name usually arrives on a LATER
            # build_order than the items, because THE HOST asks for it after the
            # order is clear and before the confirmation question. Updating only
            # the items threw that name away -- live order #19 was confirmed
            # with no name on it after the guest had given one. A call that
            # brings no name leaves the one already there alone, and the same
            # name again is not a change.
            if guest_name and guest_name != row["guest_name"]:
                conn.execute(
                    "UPDATE orders SET guest_name = ? WHERE id = ?",
                    (guest_name, row["id"]),
                )
                conn.commit()
                changed = True
            # 16 section 2zf item 1(b), amending 2m item 5: the flag is no
            # longer sticky. Until this phase a call that did not ask for it
            # left a flag already set alone, so a draft built for the Vice
            # Chancellor and then rebuilt under another name stayed on the
            # house. Every build now writes the answer the caller computed from
            # this call's name (2ze item 3), in both directions, and only a
            # value that really moves counts as a change.
            if int(bool(row["complimentary"])) != on_the_house:
                conn.execute(
                    "UPDATE orders SET complimentary = ? WHERE id = ?",
                    (on_the_house, row["id"]),
                )
                conn.commit()
                changed = True
            try:
                current = json.loads(row["items"])
            except (TypeError, ValueError):
                current = None
            if current == items:
                return {
                    "order_id": int(row["id"]),
                    "action": "updated" if changed else "existing",
                }
            conn.execute("UPDATE orders SET items = ? WHERE id = ?", (payload, row["id"]))
            conn.commit()
            return {"order_id": int(row["id"]), "action": "updated"}
        cursor = conn.execute(
            "INSERT INTO orders (timestamp, guest_name, items, status, session_id, "
            "complimentary) VALUES (?, ?, ?, 'PENDING_CONFIRMATION', ?, ?)",
            (_now(), guest_name, payload, session_id, on_the_house),
        )
        conn.commit()
        return {"order_id": int(cursor.lastrowid), "action": "created"}


def get_order(order_id) -> dict | None:
    expire_pending_orders()
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    return _order_from_row(row) if row else None


def get_order_by_number(order_no) -> dict | None:
    """16 section 2zi item 3(c): the order a guest means by "order three".

    Today's only. Numbers restart at 1 each morning, so without the date a
    guest asking about order 3 could be handed yesterday's.
    """
    expire_pending_orders()
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders "
            "WHERE order_no = ? AND substr(timestamp, 1, 10) = ?",
            (int(order_no), _today()),
        ).fetchone()
    return _order_from_row(row) if row else None


def _refusal(current: str, new_status: str) -> str:
    if current == new_status:
        return f"Order is already {current}."
    if current in FINAL_STATUSES:
        return f"Order is {current}; it can't change any more."
    if current in _STATUS_CHAIN and new_status in _STATUS_CHAIN:
        current_step = _STATUS_CHAIN.index(current)
        if _STATUS_CHAIN.index(new_status) > current_step + 1:
            needed = _STATUS_CHAIN[current_step + 1]
            return f"Order is {current}; mark it {needed} before {new_status}."
    return f"Order is {current}; it can't be marked {new_status}."


def _next_order_no(conn) -> int:
    """16 section 2zi item 3(a): 1 + the highest number given out today.

    Today's orders only, so the stall starts at 1 each morning. `max` ignores
    the NULLs, which is every draft and every order from before the column
    existed, so neither can push the count along. A number is never reused: it
    comes from the maximum, not from a count of rows, so cancelling order 3
    leaves the next order as 4.
    """
    row = conn.execute(
        "SELECT MAX(order_no) AS highest FROM orders WHERE substr(timestamp, 1, 10) = ?",
        (_today(),),
    ).fetchone()
    return int((row["highest"] or 0)) + 1


def update_order_status(order_id, new_status, reason=None, payment_method=None) -> dict:
    expire_pending_orders()
    status = str(new_status or "").strip().upper()
    if status not in ORDER_STATUSES:
        return {"ok": False, "error": f"'{new_status}' isn't an order status."}
    # 16 section 2z item 2, as amended by 2zf item 3: a payment belongs to one
    # of three moments and to no other, and never to an order that is on the
    # house. AWAITING_PAYMENT carries the method the guest said they would use,
    # CONFIRMED the one the team really took, and COLLECTED is the pre-pay-first
    # path that still has to work for an order placed before this phase. The
    # endpoint says the same in the words the operator reads; this is the floor
    # under it.
    method = str(payment_method or "").strip().upper() or None
    if method is not None:
        if method not in PAYMENT_METHODS or status not in PAYMENT_STATUSES:
            return {"ok": False, "error": "Payment is recorded at collection."}

    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "There is no order with that number."}
        order = _order_from_row(row)
        current = order["status"]
        if status not in ALLOWED_TRANSITIONS.get(current, ()):
            return {"ok": False, "error": _refusal(current, status)}
        if method is not None and order.get("complimentary"):
            return {"ok": False, "error": "This order is on the house."}

        assignments = ["status = ?"]
        params: list = [status]
        if method is not None:
            assignments.append("payment_method = ?")
            params.append(method)
        # 16 section 2zh item 3(a): the moment the order was placed, which is
        # the step into AWAITING_PAYMENT -- what `confirm_order` does for every
        # order that has to be paid for. Only once, so a second pass over the
        # same step could never restart the guest's clock.
        if status == "AWAITING_PAYMENT" and not order.get("placed_at"):
            assignments.append("placed_at = ?")
            params.append(_now())
        # 16 section 2zi item 3(a): the guest's order number, given out the
        # moment the order is placed -- which is the step out of
        # PENDING_CONFIRMATION, to AWAITING_PAYMENT, or straight to CONFIRMED
        # when the order is on the house and never waits for money. Drafts are
        # deliberately skipped: every draft used to consume an id, which is why
        # a fresh database still showed 1, 2, 5. Read and written inside this
        # same connection and commit, so two orders placed at once cannot be
        # handed the same number.
        if (
            current == "PENDING_CONFIRMATION"
            and status in ("AWAITING_PAYMENT", "CONFIRMED")
            and order.get("order_no") is None
        ):
            assignments.append("order_no = ?")
            params.append(_next_order_no(conn))
        # 16 section 2zf item 3(d): the moment the money was taken. Only the
        # step out of AWAITING_PAYMENT is that moment, and only once: an order
        # already carrying a paid_at keeps the time it was really paid.
        if (
            current == "AWAITING_PAYMENT"
            and status == "CONFIRMED"
            and not order.get("paid_at")
        ):
            assignments.append("paid_at = ?")
            params.append(_now())
        if status == "PREPARING":
            names = [
                str((entry or {}).get("name") or "").lower()
                for entry in order["items"]
                if (entry or {}).get("name")
            ]
            longest = 0
            if names:
                placeholders = ",".join("?" * len(names))
                prep_rows = conn.execute(
                    f"SELECT prep_seconds FROM menu_items WHERE LOWER(name) IN ({placeholders})",
                    names,
                ).fetchall()
                longest = max([int(prep["prep_seconds"]) for prep in prep_rows] or [0])
            assignments.append("estimated_ready_at = ?")
            params.append(
                (datetime.now() + timedelta(seconds=longest)).isoformat(timespec="seconds")
                if longest > 0
                else None
            )
        elif status == "READY":
            assignments.append("ready_at = ?")
            params.append(_now())
        elif status == "CANCELLED":
            assignments.append("cancel_reason = ?")
            params.append(reason)

        params.append(order_id)
        conn.execute(f"UPDATE orders SET {', '.join(assignments)} WHERE id = ?", params)
        conn.commit()
        updated = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    return {"ok": True, "order": _order_from_row(updated)}


def mark_announced(order_id) -> bool:
    """04 section 5 step 1: the atomic guard. True only for the first caller."""
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "UPDATE orders SET announced = 1 WHERE id = ? AND announced = 0",
            (order_id,),
        )
        conn.commit()
    return cursor.rowcount == 1


def list_orders(status="all", limit=20) -> dict:
    expire_pending_orders()
    scope = str(status or "all").strip().lower()
    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = 20
    if scope == "active":
        wanted = ACTIVE_STATUSES
    elif scope == "completed":
        wanted = COMPLETED_STATUSES
    else:
        wanted = None

    with closing(_connect()) as conn:
        if wanted is None:
            rows = conn.execute(
                f"SELECT {_ORDER_COLUMNS} FROM orders ORDER BY id DESC LIMIT ?",
                (cap,),
            ).fetchall()
        else:
            placeholders = ",".join("?" * len(wanted))
            rows = conn.execute(
                f"SELECT {_ORDER_COLUMNS} FROM orders WHERE status IN ({placeholders}) "
                f"ORDER BY id DESC LIMIT ?",
                (*wanted, cap),
            ).fetchall()
        counts = {
            "active": int(
                conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE status IN "
                    f"({','.join('?' * len(ACTIVE_STATUSES))})",
                    ACTIVE_STATUSES,
                ).fetchone()[0]
            ),
            "completed": int(
                conn.execute(
                    "SELECT COUNT(*) FROM orders WHERE status IN "
                    f"({','.join('?' * len(COMPLETED_STATUSES))})",
                    COMPLETED_STATUSES,
                ).fetchone()[0]
            ),
            "all": int(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]),
        }
    return {"orders": [order_view(_order_from_row(row)) for row in rows], "counts": counts}


def attach_guest_name(session_id, display_name) -> list[dict]:
    name = str(display_name or "").strip()
    if not session_id or not name:
        return []
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders "
            "WHERE session_id = ? AND guest_name IS NULL "
            "AND status NOT IN ('CANCELLED', 'FAILED') ORDER BY id",
            (session_id,),
        ).fetchall()
        if not rows:
            return []
        ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" * len(ids))
        conn.execute(
            f"UPDATE orders SET guest_name = ? WHERE id IN ({placeholders})",
            [name, *ids],
        )
        conn.commit()
        updated = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE id IN ({placeholders}) ORDER BY id",
            ids,
        ).fetchall()
    return [_order_from_row(row) for row in updated]


def find_orders_for(session_id, visitor_name) -> list[dict]:
    expire_pending_orders()
    name = str(visitor_name or "").strip().lower()
    clauses, params = [], []
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if name:
        clauses.append("LOWER(guest_name) = ?")
        params.append(name)
    if not clauses:
        return []
    placeholders = ",".join("?" * len(ACTIVE_STATUSES))
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders "
            f"WHERE status IN ({placeholders}) AND ({' OR '.join(clauses)}) "
            "ORDER BY id DESC",
            (*ACTIVE_STATUSES, *params),
        ).fetchall()
    return [_order_from_row(row) for row in rows]


def create_feedback(subject, comment, rating, guest_name) -> int:
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "INSERT INTO feedback (timestamp, subject, comment, rating, guest_name) "
            "VALUES (?, ?, ?, ?, ?)",
            (_now(), subject, comment, rating, guest_name),
        )
        conn.commit()
        return int(cursor.lastrowid)


# 16 section 2zi item 4(b)/(c): the guests' form, in the order the dashboard
# and the CSV both show it.
FORM_FEEDBACK_COLUMNS = (
    "netlify_id", "created_at", "item", "overall_rating", "taste_rating",
    "presentation_rating", "value_rating", "liked_most", "improvement",
    "buy_again", "one_word",
)

# 16 section 2zi item 4(c): `buy_again_yes_pct` is the share of these two.
BUY_AGAIN_YES = ("definitely", "probably")


def insert_form_feedback(row: dict) -> bool:
    """One Netlify submission. False when it was already here.

    16 section 2zi item 4(b): `netlify_id` is unique, so a re-import of the
    same submission is a no-op rather than a duplicate -- the import re-reads
    the whole form every minute and has no idea what it fetched last time.
    """
    netlify_id = str(row.get("netlify_id") or "").strip()
    if not netlify_id:
        return False
    values = [netlify_id] + [row.get(name) for name in FORM_FEEDBACK_COLUMNS[1:]]
    placeholders = ",".join("?" * len(FORM_FEEDBACK_COLUMNS))
    with closing(_connect()) as conn:
        cursor = conn.execute(
            f"INSERT OR IGNORE INTO form_feedback ({', '.join(FORM_FEEDBACK_COLUMNS)}) "
            f"VALUES ({placeholders})",
            values,
        )
        conn.commit()
    return cursor.rowcount == 1


def list_form_feedback(limit: int = 200) -> list[dict]:
    """Newest first (16 section 2zi item 4(c))."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT id, {', '.join(FORM_FEEDBACK_COLUMNS)} FROM form_feedback "
            "ORDER BY COALESCE(created_at, '') DESC, id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def list_spoken_feedback(limit: int = 200) -> list[dict]:
    """The `feedback` table: what a guest asked THE HOST to pass on."""
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT id, timestamp, subject, comment, rating, guest_name "
            "FROM feedback ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def _average(values) -> float | None:
    numbers = [value for value in values if isinstance(value, (int, float))]
    return round(sum(numbers) / len(numbers), 2) if numbers else None


def form_feedback_summary() -> dict:
    """16 section 2zi item 4(c): the tiles above the two tabs.

    An average over no ratings is `null`, never 0: nobody has said anything yet
    is not the same as everybody said zero.
    """
    rows = list_form_feedback(limit=100000)
    answered = [
        str(row.get("buy_again") or "").strip().lower()
        for row in rows
        if str(row.get("buy_again") or "").strip()
    ]
    yes = [value for value in answered if value in BUY_AGAIN_YES]
    return {
        "count": len(rows),
        "avg_overall": _average([row.get("overall_rating") for row in rows]),
        "avg_taste": _average([row.get("taste_rating") for row in rows]),
        "avg_presentation": _average([row.get("presentation_rating") for row in rows]),
        "buy_again_yes_pct": (
            round(100 * len(yes) / len(answered)) if answered else None
        ),
    }


def get_visitor(key) -> dict | None:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT name_key, display_name, visits, favorite_item, last_order, "
            "first_seen, last_seen FROM visitors WHERE name_key = ?",
            (str(key or "").lower(),),
        ).fetchone()
    return dict(row) if row else None


def create_visitor(key, display_name) -> dict | None:
    stamp = _now()
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO visitors "
            "(name_key, display_name, visits, first_seen, last_seen) VALUES (?, ?, 1, ?, ?)",
            (str(key or "").lower(), str(display_name or "").strip(), stamp, stamp),
        )
        conn.commit()
    return get_visitor(key)


def record_visit(key) -> dict | None:
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE visitors SET visits = visits + 1, last_seen = ? WHERE name_key = ?",
            (_now(), str(key or "").lower()),
        )
        conn.commit()
    return get_visitor(key)


def refresh_visitor_after_order(order) -> dict | None:
    name = str(order.get("guest_name") or "").strip()
    if not name:
        return None
    key = name.lower()
    with closing(_connect()) as conn:
        if conn.execute(
            "SELECT 1 FROM visitors WHERE name_key = ?", (key,)
        ).fetchone() is None:
            return None
        placeholders = ",".join("?" * len(CONFIRMED_OR_LATER))
        rows = conn.execute(
            f"SELECT id, items FROM orders WHERE LOWER(guest_name) = ? "
            f"AND status IN ({placeholders}) ORDER BY id",
            (key, *CONFIRMED_OR_LATER),
        ).fetchall()
        totals: dict[str, int] = {}
        latest: dict[str, int] = {}
        for row in rows:
            try:
                items = json.loads(row["items"])
            except (TypeError, ValueError):
                items = []
            for entry in items if isinstance(items, list) else []:
                item_name = (entry or {}).get("name")
                if not item_name:
                    continue
                try:
                    quantity = max(1, int((entry or {}).get("quantity", 1)))
                except (TypeError, ValueError):
                    quantity = 1
                totals[item_name] = totals.get(item_name, 0) + quantity
                latest[item_name] = int(row["id"])
        favorite = (
            max(totals, key=lambda item: (totals[item], latest[item])) if totals else None
        )
        last_order = ", ".join(
            str((entry or {}).get("name"))
            for entry in order.get("items") or []
            if (entry or {}).get("name")
        ) or None
        conn.execute(
            "UPDATE visitors SET favorite_item = ?, last_order = ? WHERE name_key = ?",
            (favorite, last_order, key),
        )
        conn.commit()
    return get_visitor(key)


def memory_event(profile) -> dict:
    return {
        "type": "memory_updated",
        "name": profile["display_name"],
        "visits": profile["visits"],
        "favorite_item": profile["favorite_item"],
        "last_order": profile["last_order"],
        "last_seen": profile["last_seen"],
        "returning": int(profile["visits"]) > 1,
    }


def visitor_view(profile) -> dict:
    """One visitor as GET /api/visitors returns it (03 section 8)."""
    return {
        "name_key": profile["name_key"],
        "name": profile["display_name"],
        "visits": profile["visits"],
        "favorite_item": profile["favorite_item"],
        "last_order": profile["last_order"],
        "first_seen": profile["first_seen"],
        "last_seen": profile["last_seen"],
        "returning": int(profile["visits"]) > 1,
    }


def list_visitors(limit=20) -> list[dict]:
    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = 20
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT name_key, display_name, visits, favorite_item, last_order, "
            "first_seen, last_seen FROM visitors ORDER BY last_seen DESC LIMIT ?",
            (cap,),
        ).fetchall()
    return [visitor_view(row) for row in rows]


# `None` is a real value for favorite_item (11 section 5 lets the operator clear
# it), so "leave this column alone" needs a marker of its own.
UNCHANGED = object()


def update_visitor(key, display_name=None, favorite_item=UNCHANGED) -> dict | None:
    name_key = str(key or "").lower()
    assignments, params = [], []
    if display_name is not None:
        assignments.append("display_name = ?")
        params.append(str(display_name).strip())
    if favorite_item is not UNCHANGED:
        assignments.append("favorite_item = ?")
        params.append(None if favorite_item is None else str(favorite_item).strip())
    if not assignments:
        return get_visitor(name_key)
    with closing(_connect()) as conn:
        if conn.execute(
            "SELECT 1 FROM visitors WHERE name_key = ?", (name_key,)
        ).fetchone() is None:
            return None
        params.append(name_key)
        conn.execute(f"UPDATE visitors SET {', '.join(assignments)} WHERE name_key = ?", params)
        conn.commit()
    return get_visitor(name_key)


def delete_visitor(key) -> bool:
    with closing(_connect()) as conn:
        cursor = conn.execute(
            "DELETE FROM visitors WHERE name_key = ?", (str(key or "").lower(),)
        )
        conn.commit()
        return cursor.rowcount > 0


def get_business_info(topic=None) -> list[dict]:
    clause, params = "", []
    if topic:
        clause = " WHERE LOWER(topic) LIKE ? ESCAPE '\\'"
        params.append(_like(topic))
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT topic, answer FROM business_info{clause} ORDER BY topic", params
        ).fetchall()
    return [dict(row) for row in rows]


def log_action(tool: str, input_args: dict, result: dict, session_id=None) -> None:
    try:
        with closing(_connect()) as conn:
            conn.execute(
                "INSERT INTO agent_log (timestamp, tool, input_args, result, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    _now(),
                    tool,
                    json.dumps(input_args, default=str),
                    json.dumps(result, default=str),
                    str(session_id) if session_id else None,
                ),
            )
            conn.commit()
    except Exception:
        log.exception("failed to log tool action: %s", tool)


def log_system_event(event_type: str, actor: str, detail) -> None:
    try:
        with closing(_connect()) as conn:
            conn.execute(
                "INSERT INTO system_events (timestamp, event_type, actor, detail) "
                "VALUES (?, ?, ?, ?)",
                (_now(), event_type, actor, json.dumps(detail, default=str)),
            )
            conn.commit()
    except Exception:
        log.exception("failed to log system event: %s", event_type)


def list_activity(limit=30) -> list[dict]:
    try:
        cap = max(1, int(limit))
    except (TypeError, ValueError):
        cap = 30
    with closing(_connect()) as conn:
        rows = conn.execute(
            "SELECT timestamp, detail FROM system_events WHERE event_type = 'agent_activity' "
            "ORDER BY id DESC LIMIT ?",
            (cap,),
        ).fetchall()
    activity = []
    for row in rows:
        try:
            payload = json.loads(row["detail"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        activity.append(
            {
                "kind": payload.get("kind"),
                "label": payload.get("label"),
                "detail": payload.get("detail"),
                "timestamp": row["timestamp"],
            }
        )
    return activity


def get_metrics() -> dict:
    """12 section 3 / 16 section 2e item 6: computed on request, today only.

    No latency figure: nothing already logged makes one cheaply derivable, and
    an invented number is worse than no number.
    """
    today = _today()
    not_counted = ("CANCELLED", "FAILED", "PENDING_CONFIRMATION")
    placeholders = ",".join("?" * len(not_counted))
    with closing(_connect()) as conn:
        sessions = int(
            conn.execute(
                "SELECT COUNT(*) FROM system_events WHERE event_type = 'session_started' "
                "AND substr(timestamp, 1, 10) = ?",
                (today,),
            ).fetchone()[0]
        )
        orders = int(
            conn.execute(
                f"SELECT COUNT(*) FROM orders WHERE substr(timestamp, 1, 10) = ? "
                f"AND status NOT IN ({placeholders})",
                (today, *not_counted),
            ).fetchone()[0]
        )
        results = conn.execute(
            "SELECT result FROM agent_log WHERE substr(timestamp, 1, 10) = ?", (today,)
        ).fetchall()
        connection_failures = int(
            conn.execute(
                "SELECT COUNT(*) FROM system_events WHERE event_type = 'connect_failed' "
                "AND substr(timestamp, 1, 10) = ?",
                (today,),
            ).fetchone()[0]
        )

    failed_tool_calls = 0
    for row in results:
        try:
            result = json.loads(row["result"])
        except (TypeError, ValueError):
            continue
        if isinstance(result, dict) and "error" in result:
            failed_tool_calls += 1

    return {
        "date": today,
        "sessions_today": sessions,
        "orders_today": orders,
        "failed_tool_calls_today": failed_tool_calls,
        "connection_failures_today": connection_failures,
    }


def order_rupees(items) -> int | None:
    """16 section 2z item 4: whole rupees from the stored prices, or None.

    The same digits rule as `compute_total`, so an order whose prices carry no
    digits is unpriced rather than zero -- it is excluded from every sum and
    shown as a warning instead of quietly flattering the takings. The price is
    the one stored on the order, so a later menu change never alters history.
    """
    total = 0
    for entry in items or []:
        digits = re.sub(r"[^0-9]", "", str((entry or {}).get("price") or ""))
        if not digits:
            return None
        try:
            quantity = int((entry or {}).get("quantity", 1))
        except (TypeError, ValueError):
            quantity = 1
        total += int(digits) * max(1, quantity)
    return total


# 16 section 2zf item 3(i), replacing 2z item 4's `to_collect`: with pay-first
# the money is either taken or it is still at the counter, and the only status
# that means "still at the counter" is this one.
_AWAITING_PAYMENT_STATUSES = ("AWAITING_PAYMENT",)


def _is_paid(order) -> bool:
    """16 section 2zf item 3(i): whether this order's money was really taken.

    `paid_at` is the pay-first answer. A COLLECTED order from before this phase
    has no `paid_at` at all -- the column was added NULL and nothing went back
    to fill it in -- so its status is the only evidence there is, and it still
    counts as paid: the team took the money, they just did it under the old
    rules. Both are "paid orders" wherever 3(i) uses the word.
    """
    return bool(order.get("paid_at")) or order.get("status") == "COLLECTED"


def earnings_rows() -> list[dict]:
    """Today's orders that are not drafts, oldest first (16 section 2z items 4, 6).

    One place to read them, so the JSON and the CSV can never disagree.
    """
    today = _today()
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_ORDER_COLUMNS} FROM orders WHERE substr(timestamp, 1, 10) = ? "
            "AND status != 'PENDING_CONFIRMATION' ORDER BY id",
            (today,),
        ).fetchall()
    return [_order_from_row(row) for row in rows]


def get_earnings() -> dict:
    """16 section 2z item 4: today's money, computed on request like the metrics.

    Every figure is an integer number of rupees except `date`. Drafts are never
    counted anywhere: nothing was ordered until the guest said yes.
    """
    orders = earnings_rows()
    earned = {"CASH": 0, "QR": 0, None: 0}
    awaiting_payment = 0
    on_the_house = 0
    on_the_house_orders = 0
    paid_orders = 0
    cancelled_orders = 0
    refunded = 0
    refunded_orders = 0
    unpriced_orders = 0
    by_item: dict[str, dict] = {}

    for order in orders:
        status = order["status"]
        amount = order_rupees(order["items"])
        if status in ("CANCELLED", "FAILED"):
            cancelled_orders += 1
            # 16 section 2zf item 3(i): an order the guest paid for and the team
            # then cancelled is money that has to go back, so it is reported on
            # its own instead of simply vanishing from the day's figures.
            if (
                amount is not None
                and not order.get("complimentary")
                and _is_paid(order)
            ):
                refunded += amount
                refunded_orders += 1
            continue
        if amount is None:
            unpriced_orders += 1
            continue
        if order.get("complimentary"):
            # The menu value of what the team gave away, not money taken.
            on_the_house += amount
            on_the_house_orders += 1
            continue
        if _is_paid(order):
            # 16 section 2zf item 3(i): earned is now every paid order, whatever
            # the kitchen has done with it since -- with pay-first the money is
            # in the box long before the food is handed over, and a day's
            # takings that only counted COLLECTED would read far too low.
            method = order.get("payment_method")
            earned[method if method in PAYMENT_METHODS else None] += amount
            # 16 section 2zh item 3(c): the count of the orders that made up
            # `earned`, so the two figures describe the same set. It used to
            # count only COLLECTED ones, which under pay-first meant the money
            # in the box was divided by a smaller number of orders than had
            # paid it -- an average order value that was simply wrong.
            paid_orders += 1
            for entry in order["items"] or []:
                name = (entry or {}).get("name")
                if not name:
                    continue
                digits = re.sub(r"[^0-9]", "", str((entry or {}).get("price") or ""))
                try:
                    quantity = max(1, int((entry or {}).get("quantity", 1)))
                except (TypeError, ValueError):
                    quantity = 1
                row = by_item.setdefault(name, {"name": name, "quantity": 0, "amount": 0})
                row["quantity"] += quantity
                row["amount"] += int(digits) * quantity
        elif status in _AWAITING_PAYMENT_STATUSES:
            awaiting_payment += amount

    return {
        "date": _today(),
        "earned": earned["CASH"] + earned["QR"] + earned[None],
        "earned_cash": earned["CASH"],
        "earned_qr": earned["QR"],
        "earned_unrecorded": earned[None],
        # 16 section 2zf item 3(i): `awaiting_payment` replaces `to_collect`.
        "awaiting_payment": awaiting_payment,
        "on_the_house": on_the_house,
        "on_the_house_orders": on_the_house_orders,
        "paid_orders": paid_orders,
        "cancelled_orders": cancelled_orders,
        "refunded": refunded,
        "refunded_orders": refunded_orders,
        "by_item": sorted(
            by_item.values(), key=lambda row: (-row["amount"], row["name"])
        ),
        "unpriced_orders": unpriced_orders,
    }


def get_analytics() -> dict:
    today = _today()
    counted = ("CANCELLED", "FAILED", "PENDING_CONFIRMATION")
    placeholders = ",".join("?" * len(counted))
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT items FROM orders WHERE substr(timestamp, 1, 10) = ? "
            f"AND status NOT IN ({placeholders})",
            (today, *counted),
        ).fetchall()
        interactions = int(
            conn.execute(
                "SELECT COUNT(*) FROM system_events WHERE event_type = 'session_started' "
                "AND substr(timestamp, 1, 10) = ?",
                (today,),
            ).fetchone()[0]
        )
        visitor_rows = conn.execute(
            "SELECT visits FROM visitors WHERE substr(last_seen, 1, 10) = ?", (today,)
        ).fetchall()
        ready_rows = conn.execute(
            "SELECT timestamp, ready_at FROM orders WHERE substr(timestamp, 1, 10) = ? "
            "AND ready_at IS NOT NULL",
            (today,),
        ).fetchall()

    quantities: dict[str, int] = {}
    for row in rows:
        try:
            items = json.loads(row["items"])
        except (TypeError, ValueError):
            items = []
        for entry in items if isinstance(items, list) else []:
            name = (entry or {}).get("name")
            if not name:
                continue
            try:
                quantity = max(1, int((entry or {}).get("quantity", 1)))
            except (TypeError, ValueError):
                quantity = 1
            quantities[name] = quantities.get(name, 0) + quantity
    total_quantity = sum(quantities.values())
    popular = [
        {"name": name, "percent": round(count * 100 / total_quantity)}
        for name, count in sorted(quantities.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
    ] if total_quantity else []

    durations = []
    for row in ready_rows:
        try:
            durations.append(
                (
                    datetime.fromisoformat(row["ready_at"])
                    - datetime.fromisoformat(row["timestamp"])
                ).total_seconds()
            )
        except (TypeError, ValueError):
            continue

    return {
        "date": today,
        "orders": len(rows),
        "interactions": interactions,
        "named_visitors": len(visitor_rows),
        "returning_visitors": sum(1 for row in visitor_rows if int(row["visits"]) > 1),
        "popular_items": popular,
        "average_order_to_ready_seconds": (
            round(sum(durations) / len(durations)) if durations else None
        ),
    }
