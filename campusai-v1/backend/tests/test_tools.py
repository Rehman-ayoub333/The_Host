import json
from types import SimpleNamespace

import tools
import summaries


def test_query_timetable_returns_real_results_and_errors(campus_data):
    result = tools.query_timetable(day="Monday")
    assert result["source"] == "real"
    assert result["total"] == 3
    assert [row["course"] for row in result["matches"]] == [
        "Data Structures",
        "Operating Systems",
        "Database Systems",
    ]
    assert tools.query_timetable(day="noday")["error"] == "I couldn't understand that day."
    assert tools.query_timetable(time="25:00")["error"] == "I couldn't understand that time."


def test_check_room_availability_real_demo_unknown_and_bad_input(campus_data):
    available = tools.check_room_availability("Lab 2", "Monday", "3pm")
    assert available["source"] == "real"
    assert available["available"] is True

    booked = tools.check_room_availability("Lab 3", "Monday", "2pm")
    assert booked["source"] == "real"
    assert booked["class"]["course"] == "Database Systems"

    override = tools.check_room_availability("Lab 1", "Monday", "3pm")
    assert override["source"] == "demo"
    assert override["available"] is False
    assert override["reason"] == "reserved for a demo event"

    unknown = tools.check_room_availability("Lab 4", "Sunday", "2pm")
    assert unknown["source"] == "real"
    assert unknown["known_room"] is False
    assert tools.check_room_availability("Lab 2", "noday", "3pm")["error"] == "I couldn't understand that day or time."
    assert tools.check_room_availability("Lab 2", "Monday", "25:00")["error"] == "I couldn't understand that day or time."


def test_complaint_tools_return_demo_results(campus_data):
    created = tools.create_complaint("Room 12", " broken projector ")
    assert created["source"] == "demo"
    assert created["room"] == "Room 12"
    assert created["issue"] == "broken projector"
    status = tools.get_complaint_status(created["ticket_number"])
    assert status["source"] == "demo"
    assert status["found"] is True
    assert status["record"]["id"] == created["ticket_number"]
    assert tools.get_complaint_status("not-a-ticket")["error"] == "I couldn't understand that ticket number."
    assert tools.create_complaint("", "issue")["error"] == "I need both the room and the issue."


def test_list_recent_complaints_returns_demo_source(campus_data):
    tools.create_complaint("Room 1", "leak")
    result = tools.list_recent_complaints(limit=1)
    assert result["source"] == "demo"
    assert result["total"] == 1
    assert result["complaints"][0]["issue"] == "leak"
    fallback = tools.list_recent_complaints(limit="bad")
    assert fallback["source"] == "demo"
    assert fallback["total"] == 1


def test_signal_confirmation_request_is_not_logged(campus_data, monkeypatch):
    def fail_if_logged(*args, **kwargs):
        raise AssertionError("signal_confirmation_request must not log")

    monkeypatch.setattr(tools.data, "log_action", fail_if_logged)
    result = tools.signal_confirmation_request("Log the issue")
    assert result == {"acknowledged": True}
    assert "source" not in result


def test_web_search_parses_instant_answer_and_handles_empty_query(campus_data, monkeypatch):
    response = SimpleNamespace(
        text=json.dumps({"AbstractText": "Plants convert light into chemical energy.", "AbstractURL": "https://example.test/photosynthesis"})
    )
    monkeypatch.setattr(tools.httpx, "get", lambda *args, **kwargs: response)
    result = tools.web_search("photosynthesis")
    assert result["source"] == "web"
    assert result["found"] is True
    assert result["summary"] == "Plants convert light into chemical energy."

    empty = tools.web_search(" ")
    assert empty["source"] == "web"
    assert empty["found"] is False
    assert empty["error"] == "What should I look up?"


def test_registries_have_exact_tool_order():
    expected = [
        "query_timetable",
        "check_room_availability",
        "create_complaint",
        "get_complaint_status",
        "list_recent_complaints",
        "signal_confirmation_request",
        "web_search",
    ]
    assert list(tools.TOOL_FUNCTIONS) == expected
    assert [declaration["name"] for declaration in tools.TOOL_DECLARATIONS] == expected


def test_summaries_use_exact_templates():
    assert summaries.default_source("query_timetable") == "real"
    assert summaries.default_source("create_complaint") == "demo"
    assert summaries.default_source("web_search") == "web"
    assert summaries.default_source("unknown") == "demo"
    assert summaries.summarize_running("query_timetable", {}) == "Searching the timetable…"
    assert summaries.summarize_running(
        "check_room_availability", {"room": "Lab 2", "day": "Monday", "time": "15:00"}
    ) == "Checking Lab 2 on Monday at 15:00…"
    assert summaries.summarize_running(
        "check_room_availability", {"day": "Monday"}
    ) == "Checking Monday…"
    assert summaries.summarize_done(
        "check_room_availability",
        {"room": "Lab 3", "day": "Monday", "time": "14:00"},
        {
            "source": "real",
            "known_room": True,
            "room": "Lab 3",
            "day": "Monday",
            "time": "14:00",
            "available": False,
            "class": {"course": "Database Systems"},
        },
    ) == "Lab 3 is booked — Monday 14:00 (Database Systems)"