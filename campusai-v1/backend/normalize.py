import re


DAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

_DAYS = {
    "monday": "Monday",
    "mon": "Monday",
    "tuesday": "Tuesday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "wednesday": "Wednesday",
    "wed": "Wednesday",
    "thursday": "Thursday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "friday": "Friday",
    "fri": "Friday",
    "saturday": "Saturday",
    "sat": "Saturday",
    "sunday": "Sunday",
    "sun": "Sunday",
}


def normalize_day(s: str) -> str | None:
    day = s.strip().lower()
    if day in _DAYS:
        return _DAYS[day]
    candidate = day.rstrip(".,")
    if candidate in _DAYS:
        return _DAYS[candidate]
    if candidate.endswith("s") and candidate[:-1] in _DAYS:
        return _DAYS[candidate[:-1]]
    return None


def normalize_time(s: str) -> str | None:
    t = s.strip().lower()
    t = re.sub(r"\b([ap])\.m\.?", r"\1m", t)
    t = t.replace(".", ":")
    t = re.sub(r"\b(o'clock|oclock|sharp|hours|hrs)\b", "", t)
    t = t.strip()
    if t == "noon":
        return "12:00"
    if t == "midnight":
        return "00:00"

    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        suffix = match.group(3)
    else:
        compact_match = re.fullmatch(r"\d{3,4}", t)
        if not compact_match:
            return None
        hour = int(t[:-2])
        minute = int(t[-2:])
        suffix = None

    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    elif suffix is None and 1 <= hour <= 7:
        hour += 12

    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def normalize_room(s: str) -> str:
    room = re.sub(r"[\s\-_]+", "", s.strip().lower())
    if room.startswith("room") and len(room) > 4:
        room = room[4:]
    return room


def time_in_range(t: str, start: str, end: str) -> bool:
    return start <= t < end


def add_minutes(t: str, minutes: int) -> str:
    hour, minute = map(int, t.split(":"))
    total = min(hour * 60 + minute + minutes, 23 * 60 + 59)
    return f"{total // 60:02d}:{total % 60:02d}"