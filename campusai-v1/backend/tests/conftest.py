import json

import pytest

import config
import data


@pytest.fixture
def campus_data(tmp_path, monkeypatch):
    timetable_path = tmp_path / "timetable.json"
    demo_path = tmp_path / "demo_data.json"
    db_path = tmp_path / "campus_ai.db"
    timetable_path.write_text(
        json.dumps(
            [
                {"course": "Data Structures", "teacher": "Dr. Ahmed", "day": "Monday", "start_time": "10:00", "end_time": "11:00", "room": "Lab 1", "section": "BSCS-6A"},
                {"course": "Operating Systems", "teacher": "Dr. Bilal", "day": "Monday", "start_time": "11:00", "end_time": "12:00", "room": "Lab 3", "section": "BSCS-6A"},
                {"course": "Database Systems", "teacher": "Ms. Sadia", "day": "Monday", "start_time": "14:00", "end_time": "15:00", "room": "Lab 3", "section": "BSCS-6B"},
                {"course": "Web Engineering", "teacher": "Dr. Farah", "day": "Wednesday", "start_time": "11:00", "end_time": "12:00", "room": "Lab 2", "section": "BSCS-6B"},
            ]
        ),
        encoding="utf-8",
    )
    demo_path.write_text(
        json.dumps(
            [
                {"room": "Lab 1", "day": "Monday", "time": "15:00", "available": False, "note": "reserved for a demo event"},
                {"room": "Seminar A", "day": "Tuesday", "time": "14:00", "available": False, "note": "reserved for a demo event"},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "TIMETABLE_JSON_PATH", timetable_path)
    monkeypatch.setattr(config, "DEMO_DATA_JSON_PATH", demo_path)
    monkeypatch.setattr(config, "DB_PATH", db_path)
    data.TIMETABLE = []
    data.init_db()
    assert data.load_timetable() == 4
    return data