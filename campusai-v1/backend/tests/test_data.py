def test_query_timetable_filters_and_sorts(campus_data):
    rows = campus_data.query_timetable_data(day="Monday")
    assert [row["course"] for row in rows] == [
        "Data Structures",
        "Operating Systems",
        "Database Systems",
    ]
    assert campus_data.query_timetable_data(room="Lab 3", time="2pm")[0]["course"] == "Database Systems"
    assert campus_data.query_timetable_data(room="Lab 1", time="11am") == []
    assert campus_data.query_timetable_data(course="engineering")[0]["course"] == "Web Engineering"
    assert campus_data.query_timetable_data(teacher="sadia")[0]["course"] == "Database Systems"
    assert campus_data.query_timetable_data(day="noday") == []
    assert campus_data.query_timetable_data(time="25:00") == []


def test_room_lookup_uses_timetable_and_overrides(campus_data):
    assert campus_data.timetable_row_count() == 4
    assert campus_data.known_room_display("lab-3") == "Lab 3"
    assert campus_data.known_room_display("Seminar A") == "Seminar A"
    assert campus_data.known_room_display("Lab 4") is None
    assert campus_data.find_class("Lab 3", "Monday", "14:00")["course"] == "Database Systems"
    assert campus_data.find_class("Lab 3", "Monday", "15:00") is None
    assert campus_data.check_override("Lab 1", "Monday", "15:59") == {
        "available": False,
        "note": "reserved for a demo event",
    }
    assert campus_data.check_override("Lab 1", "Monday", "16:00") is None
    assert campus_data.check_override("Lab 1", "bad day", "3pm") is None


def test_complaints_and_recent_log_persist(campus_data):
    ticket = campus_data.create_complaint_record("Room 12", "broken projector")
    record = campus_data.get_complaint(ticket)
    assert record["id"] == ticket
    assert record["room"] == "Room 12"
    assert record["status"] == "Submitted"
    assert campus_data.get_complaint(ticket + 1) is None
    assert campus_data.get_recent_complaints(5)[0]["id"] == ticket

    campus_data.log_action("query_timetable", {"day": "Monday"}, {"source": "real"})
    log = campus_data.get_recent_log(1)[0]
    assert log["input_args"] == {"day": "Monday"}
    assert log["result"] == {"source": "real"}