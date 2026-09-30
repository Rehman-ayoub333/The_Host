import json
import logging
import sqlite3
from contextlib import closing

import config
from normalize import normalize_day, normalize_room, normalize_time


log = logging.getLogger(__name__)
TIMETABLE: list[dict] = []


def init_db() -> None:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                room TEXT NOT NULL,
                issue TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Submitted'
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS room_overrides (
                room TEXT NOT NULL,
                display_room TEXT NOT NULL,
                day TEXT NOT NULL,
                time TEXT NOT NULL,
                available INTEGER NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (room, day, time)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                input_args TEXT NOT NULL,
                result TEXT NOT NULL
            )"""
        )
        override_count = conn.execute(
            "SELECT COUNT(*) FROM room_overrides"
        ).fetchone()[0]
        if override_count == 0:
            with config.DEMO_DATA_JSON_PATH.open(encoding="utf-8") as file:
                demo_rows = json.load(file)
            for row_number, row in enumerate(demo_rows, start=1):
                try:
                    room = normalize_room(row["room"])
                    day = normalize_day(row["day"])
                    time = normalize_time(row["time"])
                    if not room or not day or not time:
                        raise ValueError("invalid room, day, or time")
                    conn.execute(
                        """INSERT OR IGNORE INTO room_overrides
                           (room, display_room, day, time, available, note)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            room,
                            row["room"],
                            day,
                            time,
                            int(bool(row["available"])),
                            str(row.get("note", "")),
                        ),
                    )
                except (AttributeError, KeyError, TypeError, ValueError) as exc:
                    log.warning("skipped demo override row %s: %s", row_number, exc)
        conn.commit()


def load_timetable() -> int:
    global TIMETABLE

    try:
        with config.TIMETABLE_JSON_PATH.open(encoding="utf-8") as file:
            rows = json.load(file)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load timetable: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("Unable to load timetable: expected a JSON array.")

    valid_rows = []
    required = (
        "course",
        "teacher",
        "day",
        "start_time",
        "end_time",
        "room",
        "section",
    )
    for row_number, row in enumerate(rows, start=1):
        try:
            if not isinstance(row, dict) or any(key not in row for key in required):
                raise ValueError("missing required key")
            day = normalize_day(row["day"])
            start = normalize_time(row["start_time"])
            end = normalize_time(row["end_time"])
            if not day or not start or not end:
                raise ValueError("day or time could not be normalised")
            normalized = {key: row[key] for key in required}
            normalized["day"] = day
            normalized["start_time"] = start
            normalized["end_time"] = end
            normalized["_day"] = day
            normalized["_start"] = start
            normalized["_end"] = end
            normalized["_room"] = normalize_room(row["room"])
            valid_rows.append(normalized)
        except (AttributeError, TypeError, ValueError) as exc:
            log.warning("skipped timetable row %s: %s", row_number, exc)

    if not valid_rows:
        raise RuntimeError("Unable to load timetable: zero valid rows.")
    TIMETABLE = valid_rows
    return len(TIMETABLE)