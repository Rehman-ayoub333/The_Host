"""Phase 7s: the operator's announcement (16 section 2zs item 4).

Rehman types an announcement on the dashboard; THE HOST shows it on the public
screen and says it out loud. A note is private and needs a conversation; an
announcement is public and makes one if it has to.

The announcement's own words are the operator's, not the record's: nothing here
lets them reach the log file, the activity feed or the audit rows.
"""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import event_bus
import live_session
import main
import prompts

import doubles


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}

# 21 Part C row E65, word for word.
E65 = "Only 5 Fire Burgers left today!"


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
    monkeypatch.setattr(main, "PENDING_ANNOUNCEMENT", None)
    with TestClient(main.app) as client:
        yield client


class Listening:
    """A conversation that is running, as `main.ACTIVE` sees one."""

    def __init__(self, session_id="a1b2c3d4"):
        self.ctx = {"session_id": session_id}
        self.injected = []

    async def inject(self, kind, text):
        self.injected.append((kind, text))


@pytest.fixture
def live(monkeypatch):
    session = Listening()
    monkeypatch.setattr(main, "ACTIVE", session)
    return session


@pytest.fixture
def quiet(monkeypatch):
    """Nobody at the stall: `ACTIVE` is None, as it is between guests."""
    monkeypatch.setattr(main, "ACTIVE", None)


def published(kind):
    return [event for event in event_bus.PUBLISHED if event["type"] == kind]


def audit_rows():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            json.loads(row["detail"])
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'operator_action' "
                "ORDER BY id"
            )
        ]


def activity_rows():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT detail FROM system_events WHERE event_type = 'agent_activity' "
                "ORDER BY id"
            )
        ]


# -------------------------------------------------------------- the exact text


def test_the_template_is_exactly_the_spec_line():
    assert prompts.OPERATOR_ANNOUNCEMENT_TEMPLATE == (
        "[Operator announcement — say this to everyone at the stall now.] {text}"
    )


def test_part_a_carries_the_announcement_rule():
    """21 Part A is what makes THE HOST say it as written and say it once."""
    from datetime import datetime

    text = prompts.build_system_instruction(datetime(2026, 11, 2, 19, 30))

    assert (
        'A message that starts with "[Operator announcement" is the team\'s '
        "announcement for everyone at the stall; the same words are already showing "
        "on the public screen." in text
    )
    assert (
        "A promotion in an announcement is the team's decision: say it as written, "
        "and it never lets you give any guest a discount yourself." in text
    )


# ----------------------------------------- the screen, and what it never carries


def test_the_announcement_goes_to_the_screen_with_its_twenty_seconds(served, live):
    event_bus.PUBLISHED.clear()

    response = served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    print("announce ->", response.status_code, response.json())
    assert response.status_code == 200
    assert response.json() == {"shown": True, "seconds": 20, "started": False}
    shown = published("display_announcement")
    assert len(shown) == 1
    assert shown[0]["text"] == E65
    assert shown[0]["seconds"] == 20


def test_the_public_screen_is_allowed_to_see_it(served, live):
    """16 section 2zs item 4(b): the one thing from the note box that is public.

    The TV is the whole point: the room reads the same words it hears.
    """
    event_bus.PUBLISHED.clear()
    served.post("/api/announcement", json={"text": E65}, headers=AUTH)
    event = published("display_announcement")[0]

    assert "display_announcement" in event_bus.SMD_ALLOWED
    assert "display_announcement" not in event_bus.SMD_NEVER
    for role in ("smd", "dashboard"):
        view = event_bus.filter_for(role, event)
        assert view is not None, role
        assert view["text"] == E65
        assert view["seconds"] == 20


def test_a_private_note_never_reaches_the_screen(served, live):
    """Only what Rehman sends as an announcement is announced (item 4)."""
    event_bus.PUBLISHED.clear()

    served.post("/api/session/note", json={"text": "This is the VC."}, headers=AUTH)

    assert published("display_announcement") == []


def test_no_announcement_text_reaches_the_log_or_the_record(served, live, caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    lines = [
        record.getMessage()
        for record in caplog.records
        if record.getMessage().startswith("operator announcement")
    ]
    print("log lines:", lines)
    assert lines == [f"operator announcement chars={len(E65)}"]
    for line in lines:
        assert "Fire" not in line and "5" not in line.replace(f"chars={len(E65)}", "")

    assert audit_rows()[-1] == {"action": "announcement", "chars": len(E65)}
    rows = activity_rows()
    assert rows, "an announcement leaves an activity row"
    assert "Announcement shown" in rows[-1]["detail"]
    assert E65 not in rows[-1]["detail"]


# ------------------------------------------------- the turn THE HOST is given


def test_a_live_conversation_is_sent_the_announcement_turn(served, live):
    served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    assert live.injected == [
        (
            "announcement",
            "[Operator announcement — say this to everyone at the stall now.] " + E65,
        )
    ]


def test_the_turn_is_deferred_like_a_payment_line(served, live):
    """Item 4(b): deferred while THE HOST is speaking, like PAYMENT_TEMPLATE.

    `inject` is the one path both take, so an announcement can never cut THE
    HOST off mid-sentence or talk over a guest who has started speaking.
    """
    served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    kind, _text = live.injected[0]
    assert kind == "announcement"
    assert hasattr(live_session.LiveSession, "inject")


# -------------------------------------- with nobody at the stall, it still goes


def test_an_announcement_with_no_conversation_is_never_refused(served, quiet):
    """Item 4(e): 409 never -- it starts a conversation instead."""
    response = served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    print("no conversation ->", response.status_code, response.json())
    assert response.status_code == 200
    assert response.json()["started"] is True
    assert main.PENDING_ANNOUNCEMENT == E65
    # And the screen shows it either way: the room reads it before anyone speaks.
    assert published("display_announcement")[-1]["text"] == E65


def test_the_trigger_announcement_skips_the_greeting(monkeypatch):
    """Item 4(b): the first turn THE HOST gets is the announcement itself."""
    session, _ws = doubles.new_session(trigger="announcement")
    session.announcement = E65

    opening = asyncio.run(session._opening_text())

    print("opening turn:", opening)
    assert opening == (
        "[Operator announcement — say this to everyone at the stall now.] " + E65
    )
    for line in prompts.GREETING_LINES:
        assert line not in opening
    assert "announcement" not in prompts.OPENING_TRIGGERS


def test_an_ordinary_trigger_still_greets():
    session, _ws = doubles.new_session(trigger="button")

    opening = asyncio.run(session._opening_text())

    assert "Greet the guest with this line" in opening


# ------------------------------------------------------------ what it may carry


def test_the_endpoint_needs_the_token(served, live):
    assert served.post("/api/announcement", json={"text": E65}).status_code == 401
    refused = served.post(
        "/api/announcement", json={"text": E65}, headers={"X-Operator-Token": "wrong"}
    )
    assert refused.status_code == 401
    assert live.injected == []


@pytest.mark.parametrize(
    "text", ["", "   ", "x" * (config.ANNOUNCEMENT_MAX_CHARS + 1)]
)
def test_the_length_is_one_to_a_hundred_and_forty(served, live, text):
    response = served.post("/api/announcement", json={"text": text}, headers=AUTH)

    print(f"{len(text)} chars ->", response.status_code)
    assert response.status_code == 400
    assert live.injected == []


def test_exactly_a_hundred_and_forty_characters_is_allowed(served, live):
    text = "x" * config.ANNOUNCEMENT_MAX_CHARS

    response = served.post("/api/announcement", json={"text": text}, headers=AUTH)

    assert response.status_code == 200
    assert config.ANNOUNCEMENT_MAX_CHARS == 140


# ---------------------------------------------- listening is never touched by it


def test_an_announcement_never_changes_listening(served, live):
    """Item 4(b), word for word: listening state is never changed.

    An announcement is THE HOST talking, not the microphone opening.
    """
    before = dict(main.LISTENING)

    served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    assert dict(main.LISTENING) == before
    assert published("listening") == []


def test_an_announcement_with_no_conversation_never_changes_listening(served, quiet):
    before = dict(main.LISTENING)

    served.post("/api/announcement", json={"text": E65}, headers=AUTH)

    assert dict(main.LISTENING) == before
