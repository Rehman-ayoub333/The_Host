import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime

import config
from normalize import DAY_ORDER, add_minutes, normalize_day, normalize_room, normalize_time, time_in_range


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


def timetable_row_count() -> int:
    return len(TIMETABLE)


def query_timetable_data(
    day=None,
    time=None,
    room=None,
    teacher=None,
    course=None,
) -> list[dict]:
    normalized_day = normalize_day(day) if day is not None else None
    normalized_time = normalize_time(time) if time is not None else None
    if day is not None and normalized_day is None:
        return []
    if time is not None and normalized_time is None:
        return []

    room_key = normalize_room(str(room)) if room is not None else None
    teacher_query = str(teacher).casefold() if teacher is not None else None
    course_query = str(course).casefold() if course is not None else None

    rows = []
    for entry in TIMETABLE:
        if normalized_day is not None and entry["_day"] != normalized_day:
            continue
        if normalized_time is not None and not time_in_range(
            normalized_time, entry["_start"], entry["_end"]
        ):
            continue
        if room_key is not None and entry["_room"] != room_key:
            continue
        if teacher_query is not None and teacher_query not in str(entry["teacher"]).casefold():
            continue
        if course_query is not None and course_query not in str(entry["course"]).casefold():
            continue
        rows.append({key: entry[key] for key in (
            "course", "teacher", "day", "start_time", "end_time", "room", "section"
        )})

    rows.sort(key=lambda row: (DAY_ORDER.index(row["day"]), row["start_time"]))
    return rows


def known_room_display(room_raw: str) -> str | None:
    room_key = normalize_room(room_raw)
    if not room_key:
        return None
    for entry in TIMETABLE:
        if entry["_room"] == room_key:
            return entry["room"]

    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT display_room FROM room_overrides WHERE room = ? LIMIT 1",
            (room_key,),
        ).fetchone()
    return row["display_room"] if row else None


def find_class(room_raw: str, day_raw: str, time_raw: str) -> dict | None:
    room_key = normalize_room(room_raw)
    day = normalize_day(day_raw)
    time = normalize_time(time_raw)
    if not room_key or not day or not time:
        return None
    for entry in TIMETABLE:
        if (
            entry["_room"] == room_key
            and entry["_day"] == day
            and time_in_range(time, entry["_start"], entry["_end"])
        ):
            return {key: entry[key] for key in (
                "course", "teacher", "day", "start_time", "end_time", "room", "section"
            )}
    return None


def check_override(room_raw: str, day_raw: str, time_raw: str) -> dict | None:
    room_key = normalize_room(room_raw)
    day = normalize_day(day_raw)
    time = normalize_time(time_raw)
    if not room_key or not day or not time:
        return None

    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT time, available, note FROM room_overrides WHERE room = ? AND day = ? ORDER BY time",
            (room_key, day),
        ).fetchall()
    for row in rows:
        if time_in_range(time, row["time"], add_minutes(row["time"], 60)):
            return {"available": bool(row["available"]), "note": row["note"]}
    return None


def log_action(tool: str, input_args: dict, result: dict) -> None:
    try:
        with closing(sqlite3.connect(config.DB_PATH)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute(
                "INSERT INTO agent_log (timestamp, tool, input_args, result) VALUES (?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"),
                    tool,
                    json.dumps(input_args, default=str),
                    json.dumps(result, default=str),
                ),
            )
            conn.commit()
    except Exception:
        log.exception("failed to log tool action: %s", tool)


def create_complaint_record(room: str, issue: str) -> int:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "INSERT INTO complaints (timestamp, room, issue) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), room, issue),
        )
        conn.commit()
        return int(cursor.lastrowid)


def get_complaint(ticket_number: int) -> dict | None:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, timestamp, room, issue, status FROM complaints WHERE id = ?",
            (ticket_number,),
        ).fetchone()
    return dict(row) if row else None


def get_recent_complaints(limit: int) -> list[dict]:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, timestamp, room, issue, status FROM complaints ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_recent_log(limit: int) -> list[dict]:
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, timestamp, tool, input_args, result FROM agent_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    records = []
    for row in rows:
        record = dict(row)
        record["input_args"] = json.loads(record["input_args"])
        record["result"] = json.loads(record["result"])
        records.append(record)
    return records