import json
import logging

import httpx

import config
import data
from normalize import normalize_day, normalize_time


log = logging.getLogger(__name__)


def _finish(tool: str, args: dict, result: dict) -> dict:
    data.log_action(tool, args, result)
    return result


def query_timetable(day=None, time=None, room=None, teacher=None, course=None) -> dict:
    args = {"day": day, "time": time, "room": room, "teacher": teacher, "course": course}
    try:
        if day and not normalize_day(day):
            return _finish("query_timetable", args, {"source": "real", "error": "I couldn't understand that day."})
        if time and not normalize_time(time):
            return _finish("query_timetable", args, {"source": "real", "error": "I couldn't understand that time."})
        rows = data.query_timetable_data(day=day, time=time, room=room, teacher=teacher, course=course)
        cap = config.MAX_TIMETABLE_MATCHES_RETURNED
        result = {"source": "real", "total": len(rows), "truncated": len(rows) > cap, "matches": rows[:cap]}
        return _finish("query_timetable", args, result)
    except Exception:
        log.exception("query_timetable failed")
        return _finish("query_timetable", args, {"source": "real", "error": "The timetable lookup failed."})


def check_room_availability(room, day, time) -> dict:
    args = {"room": room, "day": day, "time": time}
    try:
        normalized_day = normalize_day(str(day or ""))
        normalized_time = normalize_time(str(time or ""))
        if not normalized_day or not normalized_time:
            return _finish(
                "check_room_availability",
                args,
                {"source": "real", "error": "I couldn't understand that day or time."},
            )
        display = data.known_room_display(str(room or ""))
        if display is None:
            return _finish(
                "check_room_availability",
                args,
                {
                    "source": "real",
                    "known_room": False,
                    "room": str(room),
                    "day": normalized_day,
                    "time": normalized_time,
                    "available": None,
                },
            )
        override = data.check_override(room, normalized_day, normalized_time)
        if override is not None:
            result = {
                "source": "demo",
                "known_room": True,
                "room": display,
                "day": normalized_day,
                "time": normalized_time,
                "available": override["available"],
                "reason": override["note"],
            }
        else:
            class_entry = data.find_class(room, normalized_day, normalized_time)
            result = {
                "source": "real",
                "known_room": True,
                "room": display,
                "day": normalized_day,
                "time": normalized_time,
                "available": class_entry is None,
                "class": None
                if class_entry is None
                else {
                    key: class_entry[key]
                    for key in ("course", "teacher", "start_time", "end_time")
                },
            }
        return _finish("check_room_availability", args, result)
    except Exception:
        log.exception("check_room_availability failed")
        return _finish("check_room_availability", args, {"source": "real", "error": "The room check failed."})


def create_complaint(room, issue) -> dict:
    args = {"room": room, "issue": issue}
    try:
        normalized_room = str(room or "").strip()[:config.MAX_COMPLAINT_ROOM_CHARS]
        normalized_issue = str(issue or "").strip()[:config.MAX_COMPLAINT_ISSUE_CHARS]
        if not normalized_room or not normalized_issue:
            return _finish(
                "create_complaint",
                args,
                {"source": "demo", "error": "I need both the room and the issue."},
            )
        ticket = data.create_complaint_record(normalized_room, normalized_issue)
        return _finish(
            "create_complaint",
            {"room": normalized_room, "issue": normalized_issue},
            {
                "source": "demo",
                "ticket_number": ticket,
                "room": normalized_room,
                "issue": normalized_issue,
                "status": "Submitted",
            },
        )
    except Exception:
        log.exception("create_complaint failed")
        return _finish("create_complaint", args, {"source": "demo", "error": "I couldn't log the complaint."})


def get_complaint_status(ticket_number) -> dict:
    args = {"ticket_number": ticket_number}
    try:
        number = int(float(ticket_number))
    except (TypeError, ValueError, OverflowError):
        return _finish(
            "get_complaint_status",
            args,
            {"source": "demo", "error": "I couldn't understand that ticket number."},
        )
    try:
        record = data.get_complaint(number)
        return _finish(
            "get_complaint_status",
            {"ticket_number": number},
            {
                "source": "demo",
                "ticket_number": number,
                "found": record is not None,
                "record": record,
            },
        )
    except Exception:
        log.exception("get_complaint_status failed")
        return _finish("get_complaint_status", args, {"source": "demo", "error": "The lookup failed."})


def list_recent_complaints(limit=5) -> dict:
    args = {"limit": limit}
    try:
        try:
            number = max(1, min(10, int(float(limit))))
        except (TypeError, ValueError):
            number = 5
        rows = data.get_recent_complaints(number)
        return _finish(
            "list_recent_complaints",
            {"limit": number},
            {"source": "demo", "total": len(rows), "complaints": rows},
        )
    except Exception:
        log.exception("list_recent_complaints failed")
        return _finish("list_recent_complaints", args, {"source": "demo", "error": "I couldn't fetch the complaints."})


def signal_confirmation_request(summary) -> dict:
    return {"acknowledged": True}


def web_search(query) -> dict:
    normalized_query = str(query or "").strip()
    args = {"query": normalized_query}
    if not normalized_query:
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": normalized_query,
                "found": False,
                "summary": "",
                "error": "What should I look up?",
            },
        )
    try:
        response = httpx.get(
            "https://api.duckduckgo.com/",
            params={"q": normalized_query, "format": "json", "no_html": 1, "skip_disambig": 1},
            headers={"User-Agent": "CampusAI-Exhibition/1.0"},
            timeout=config.WEB_SEARCH_TIMEOUT_S,
            follow_redirects=True,
        )
        payload = json.loads(response.text)
        summary = (
            payload.get("AbstractText")
            or payload.get("Answer")
            or payload.get("Definition")
            or ""
        ).strip()
        if not summary:
            for item in payload.get("RelatedTopics", []):
                if isinstance(item, dict) and item.get("Text"):
                    summary = item["Text"].strip()
                    break
                for subtopic in item.get("Topics", []) if isinstance(item, dict) else []:
                    if subtopic.get("Text"):
                        summary = subtopic["Text"].strip()
                        break
                if summary:
                    break
        summary = summary[:500]
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": normalized_query,
                "found": bool(summary),
                "summary": summary,
                "url": payload.get("AbstractURL", ""),
            },
        )
    except Exception:
        log.exception("web_search failed")
        return _finish(
            "web_search",
            args,
            {
                "source": "web",
                "query": normalized_query,
                "found": False,
                "summary": "",
                "error": "Web lookup is unavailable right now.",
            },
        )


TOOL_FUNCTIONS = {
    "query_timetable": query_timetable,
    "check_room_availability": check_room_availability,
    "create_complaint": create_complaint,
    "get_complaint_status": get_complaint_status,
    "list_recent_complaints": list_recent_complaints,
    "signal_confirmation_request": signal_confirmation_request,
    "web_search": web_search,
}

TOOL_DECLARATIONS = [
    {
        "name": "query_timetable",
        "description": "Search the REAL class timetable by any combination of day, time, room, teacher, or course name. Provide only the fields the visitor mentioned. Returns matching classes with course, teacher, day, start_time, end_time, room and section.",
        "parameters": {
            "type": "object",
            "properties": {
                "day": {"type": "string", "description": "Day of the week, e.g. 'Monday'."},
                "time": {"type": "string", "description": "A time of day, e.g. '10am', '2 pm' or '14:00'. Matches classes running at that time."},
                "room": {"type": "string", "description": "Room or lab name, e.g. 'Lab 3'."},
                "teacher": {"type": "string", "description": "Teacher's name or part of it."},
                "course": {"type": "string", "description": "Course name or part of it."},
            },
            "required": [],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "check_room_availability",
        "description": "Check whether a room is free at a specific day and time. Uses the real timetable, except where a staged demo override exists. If the room is booked by a class, the class is included. If known_room is false the room is not in the timetable.",
        "parameters": {
            "type": "object",
            "properties": {
                "room": {"type": "string", "description": "Room or lab name, e.g. 'Lab 3'."},
                "day": {"type": "string", "description": "Day of the week, e.g. 'Monday'."},
                "time": {"type": "string", "description": "Time of day, e.g. '2pm' or '14:00'."},
            },
            "required": ["room", "day", "time"],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "create_complaint",
        "description": "Log a facilities complaint in the DEMONSTRATION complaint system. Only call this AFTER calling signal_confirmation_request and after the visitor has clearly confirmed the room and issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "room": {"type": "string", "description": "Where the problem is, e.g. 'Room 12'."},
                "issue": {"type": "string", "description": "What is wrong, e.g. 'air conditioner not working'."},
            },
            "required": ["room", "issue"],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "get_complaint_status",
        "description": "Look up the status of a complaint in the demonstration system by ticket number.",
        "parameters": {
            "type": "object",
            "properties": {"ticket_number": {"type": "integer"}},
            "required": ["ticket_number"],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "list_recent_complaints",
        "description": "List the most recently logged complaints in the demonstration system.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 5, "maximum": 10}
            },
            "required": [],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "signal_confirmation_request",
        "description": "Call this immediately before asking the visitor to confirm a write action such as logging a complaint. Pass a one-sentence summary of what you are about to confirm. It does not perform the action.",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "One sentence, e.g. 'Log a complaint about the air conditioner in Room 12.'"}
            },
            "required": ["summary"],
        },
        "behavior": "BLOCKING",
    },
    {
        "name": "web_search",
        "description": "Look up general knowledge on the web: definitions, well-known facts, people, places or things. This is a limited instant-answer lookup, not a full search engine, so it may find nothing. Do not use it for timetable, room or complaint questions.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up, e.g. 'photosynthesis'."}
            },
            "required": ["query"],
        },
        "behavior": "BLOCKING",
    },
]