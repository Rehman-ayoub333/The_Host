import pytest

from normalize import add_minutes, normalize_day, normalize_room, normalize_time, time_in_range


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10am", "10:00"),
        ("10 am", "10:00"),
        ("10:00", "10:00"),
        ("10", "10:00"),
        ("2pm", "14:00"),
        ("2 pm", "14:00"),
        ("2:00 pm", "14:00"),
        ("14:00", "14:00"),
        ("1400", "14:00"),
        ("2:00", "14:00"),
        ("2", "14:00"),
        ("2:30", "14:30"),
        ("12", "12:00"),
        ("noon", "12:00"),
        ("12am", "00:00"),
        ("midnight", "00:00"),
        ("9:05 a.m.", "09:05"),
        ("25:00", None),
        ("abc", None),
        ("", None),
    ],
)
def test_normalize_time(value, expected):
    assert normalize_time(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Lab 3", "lab3"),
        ("lab-3", "lab3"),
        ("Room 12", "12"),
        ("room12", "12"),
        ("Seminar A", "seminara"),
        ("", ""),
    ],
)
def test_normalize_room(value, expected):
    assert normalize_room(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("monday", "Monday"),
        ("mon", "Monday"),
        ("tuesday", "Tuesday"),
        ("tue", "Tuesday"),
        ("tues", "Tuesday"),
        ("wednesday", "Wednesday"),
        ("wed", "Wednesday"),
        ("thursday", "Thursday"),
        ("thu", "Thursday"),
        ("thur", "Thursday"),
        ("thurs", "Thursday"),
        ("friday", "Friday"),
        ("fri", "Friday"),
        ("saturday", "Saturday"),
        ("sat", "Saturday"),
        ("sunday", "Sunday"),
        ("sun", "Sunday"),
        ("Mondays", "Monday"),
        ("Monday,", "Monday"),
        ("today", None),
        ("tomorrow", None),
    ],
)
def test_normalize_day(value, expected):
    assert normalize_day(value) == expected


def test_time_in_range_includes_start_excludes_end():
    assert time_in_range("10:00", "10:00", "11:00")
    assert time_in_range("10:59", "10:00", "11:00")
    assert not time_in_range("11:00", "10:00", "11:00")


def test_add_minutes_and_caps_at_end_of_day():
    assert add_minutes("14:00", 60) == "15:00"
    assert add_minutes("23:30", 60) == "23:59"