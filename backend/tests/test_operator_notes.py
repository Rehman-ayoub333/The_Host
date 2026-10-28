"""Phase 7l: the operator's note (16 section 2zf item 6).

Rehman asked for "a text box on the dashboard to guide THE HOST during a
conversation". The note reaches THE HOST as a user turn behind the bracketed
prefix of `prompts.OPERATOR_NOTE_TEMPLATE`, and `21` Part A's OPERATOR NOTES
section is what stops it ever being read out.

The note's own words are the operator's, not the record's: nothing here lets
them reach the log, the activity feed or the database.
"""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

import config
import data
import event_bus
import main
import prompts

import doubles


TOKEN = "test-operator-token"
AUTH = {"X-Operator-Token": TOKEN}

NOTE = "This guest is the Vice Chancellor."


@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPERATOR_TOKEN", TOKEN)
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


# ---------------------------------------------------------- the exact text


def test_the_template_is_exactly_the_spec_line():
    assert prompts.OPERATOR_NOTE_TEMPLATE == (
        "[Operator note — from the team's dashboard, not the guest. Never read it "
        "aloud or mention it; act on it naturally.] {text}"
    )


def test_the_note_is_wrapped_in_the_prefix(served, live):
    served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    assert live.injected == [
        (
            "note",
            "[Operator note — from the team's dashboard, not the guest. Never read it "
            "aloud or mention it; act on it naturally.] " + NOTE,
        )
    ]


# -------------------------------------------------- when nobody is talking


def test_a_note_with_no_conversation_is_refused(served, monkeypatch):
    monkeypatch.setattr(main, "ACTIVE", None)

    response = served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    print("no conversation ->", response.status_code, response.json())
    assert response.status_code == 409
    assert response.json()["detail"] == "No conversation is running."


def test_the_endpoint_needs_the_token(served, live):
    assert served.post("/api/session/note", json={"text": NOTE}).status_code == 401
    refused = served.post(
        "/api/session/note", json={"text": NOTE}, headers={"X-Operator-Token": "wrong"}
    )
    assert refused.status_code == 401
    assert live.injected == []


# ------------------------------------------------------- what it will take


def test_a_note_is_accepted_and_reports_it_was_sent(served, live):
    response = served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"sent": True}


@pytest.mark.parametrize(
    "sent",
    [{}, {"text": ""}, {"text": "   "}, {"text": None}, {"text": 5}, {"text": "x" * 301}],
    ids=["missing", "empty", "blank", "null", "a number", "too long"],
)
def test_anything_outside_one_to_three_hundred_characters_is_refused(served, live, sent):
    response = served.post("/api/session/note", json=sent, headers=AUTH)

    print(sent if "text" not in sent else str(sent["text"])[:20], "->", response.status_code)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid note."
    assert live.injected == []


def test_three_hundred_characters_is_accepted(served, live):
    response = served.post("/api/session/note", json={"text": "x" * 300}, headers=AUTH)

    assert response.status_code == 200
    assert len(live.injected) == 1


def test_whitespace_is_tidied_before_it_goes(served, live):
    served.post("/api/session/note", json={"text": "  pay   at  the counter  "}, headers=AUTH)

    assert live.injected[0][1].endswith("] pay at the counter")


# ------------------------------------- the text is the operator's, not ours


def test_the_log_counts_the_characters_and_quotes_none_of_them(served, live, caplog):
    with caplog.at_level(logging.INFO, logger="main"):
        served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    lines = [record.getMessage() for record in caplog.records]
    print("log lines:", lines)
    assert f"operator note session a1b2c3d4 chars={len(NOTE)}" in lines
    for line in lines:
        assert "Vice Chancellor" not in line
        assert NOTE not in line


def test_the_activity_row_says_only_that_a_note_was_sent(served, live):
    event_bus.PUBLISHED.clear()

    served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    rows = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("activity rows:", rows)
    assert len(rows) == 1
    assert rows[0]["kind"] == "operator"
    assert rows[0]["label"] == "Operator note sent"
    assert rows[0]["detail"] is None
    assert rows[0]["session_id"] == "a1b2c3d4"


def test_the_audit_row_records_the_length_and_no_words(served, live):
    served.post("/api/session/note", json={"text": NOTE}, headers=AUTH)

    rows = audit_rows()
    print("audit rows:", rows)
    assert rows[-1] == {"action": "session_note", "chars": len(NOTE)}


def test_no_table_anywhere_keeps_the_note(served, live):
    # A phrase nothing else in the database could contain, so finding it
    # anywhere would mean the note itself was stored.
    marker = "zqx-operator-note-marker-7l"
    served.post("/api/session/note", json={"text": marker}, headers=AUTH)

    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        for table in tables:
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                for value in row:
                    assert marker not in str(value), table


# ------------------------------------------ it waits, like an announcement


def test_a_note_waits_while_the_host_is_speaking():
    session, _ws = doubles.new_session()
    session.turn_in_progress = True

    asyncio.run(session.inject("note", prompts.OPERATOR_NOTE_TEMPLATE.format(text=NOTE)))

    assert session.session.inputs == []
    assert session.pending_injections[0]["kind"] == "note"


def test_a_deferred_note_leaves_at_the_end_of_the_turn():
    session, _ws = doubles.new_session()
    session.turn_in_progress = True

    async def go():
        await session.inject("note", prompts.OPERATOR_NOTE_TEMPLATE.format(text=NOTE))
        session._cancel_announce_watcher()
        await session._end_of_turn()

    asyncio.run(go())

    assert len(session.session.inputs) == 1
    assert session.session.inputs[0]["text"].startswith("[Operator note")
    assert session.pending_injections == []


def test_a_note_dropped_with_the_session_is_counted_and_never_quoted(caplog):
    session, _ws = doubles.new_session()
    session.turn_in_progress = True
    asyncio.run(session.inject("note", prompts.OPERATOR_NOTE_TEMPLATE.format(text=NOTE)))

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session.stop())

    logged = " | ".join(record.getMessage() for record in caplog.records)
    print("log lines:", logged)
    assert f"injections dropped session {session.ctx['session_id']} n=1" in logged
    assert "Vice Chancellor" not in logged


# ------------------------------------------------- the prompt's own section


def test_the_prompt_tells_the_host_what_a_note_is():
    text = prompts.build_system_instruction(data.datetime.now())

    assert "\nOPERATOR NOTES\n" in text
    # The prefix the note really carries is the one the prompt names.
    assert '"[Operator note"' in text
    assert prompts.OPERATOR_NOTE_TEMPLATE.startswith("[Operator note")
