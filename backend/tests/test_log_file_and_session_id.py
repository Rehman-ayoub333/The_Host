"""16 section 2t item 7: evidence that outlives the terminal.

The log file carries the same INFO lines the console gets, and `agent_log` says
which conversation each tool call belonged to. Before this, the 22 Oct retest
could only be read by matching timestamps by eye.
"""

import logging
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest

import config
import data
import main
import tools


def _agent_log_columns():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return {row["name"] for row in conn.execute("PRAGMA table_info(agent_log)")}


def _rows():
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in conn.execute(
                "SELECT tool, session_id FROM agent_log ORDER BY id"
            ).fetchall()
        ]


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Keep every test's handler out of the real logs directory, and off the root
    logger once the test is over: a handler left attached would write the rest of
    the suite's lines into a temporary file that pytest then deletes."""
    directory = tmp_path / "logs"
    monkeypatch.setattr(config, "LOG_DIR", directory)
    root = logging.getLogger()
    before, level = list(root.handlers), root.level
    # The lifespan calls basicConfig(level=INFO) before setting the file up, so
    # INFO has to reach the handlers here too or the test proves nothing.
    root.setLevel(logging.INFO)
    yield directory
    for handler in list(root.handlers):
        if handler not in before:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(level)


# ------------------------------------------------------------ the log file


def test_the_log_file_is_named_for_the_day():
    path = main.log_file_path("/tmp/logs", now=datetime(2026, 10, 23, 18, 4, 2))
    assert path.name == "the_host-2026-10-23.log"


def test_the_log_file_is_created_and_takes_the_info_lines(log_dir):
    path = main.setup_file_logging()
    assert path.parent == log_dir and path.exists()

    logging.getLogger("test.the_host").info("tool done session abc12345 name=confirm_order ms=4")

    assert "tool done session abc12345 name=confirm_order ms=4" in path.read_text(
        encoding="utf-8"
    )


def test_the_log_file_carries_the_console_format(log_dir):
    path = main.setup_file_logging()

    logging.getLogger("test.the_host").info("live reconnected session abc12345 resumed=True")

    line = [
        entry
        for entry in path.read_text(encoding="utf-8").splitlines()
        if "live reconnected" in entry
    ][-1]
    assert " INFO test.the_host: live reconnected session abc12345 resumed=True" in line


def test_a_debug_line_stays_out_of_the_log_file(log_dir):
    path = main.setup_file_logging()
    logger = logging.getLogger("test.the_host")
    logger.setLevel(logging.DEBUG)

    logger.debug("a frame of audio nobody needs on disk")

    assert "nobody needs on disk" not in path.read_text(encoding="utf-8")


def test_the_operator_token_is_redacted_in_the_log_file(log_dir):
    """A redaction that holds only on the console is no redaction on disk."""
    path = main.setup_file_logging()

    logging.getLogger("uvicorn.access").info(
        'GET /ws/events?role=smd&token=THE-SECRET-VALUE HTTP/1.1'
    )

    written = path.read_text(encoding="utf-8")
    assert "THE-SECRET-VALUE" not in written
    assert "token=[REDACTED]" in written


def test_the_app_logs_into_the_configured_directory_and_detaches_on_shutdown(
    tmp_path, monkeypatch
):
    """The lifespan opened the file but never closed it, so every later test in
    the session wrote into that run's file -- and the doubles' numbers landed in
    a phase's evidence. The real backend/logs/ must stay untouched by a test."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    directory = tmp_path / "its-own-logs"
    monkeypatch.setattr(config, "LOG_DIR", directory)

    with TestClient(main.app):
        attached = [
            handler
            for handler in logging.getLogger().handlers
            if getattr(handler, "_the_host_log_file", False)
        ]
        assert len(attached) == 1
        assert main.log_file_path(directory).exists()

    assert not [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_the_host_log_file", False)
    ]


def test_setting_up_twice_leaves_one_log_file_handler(log_dir):
    main.setup_file_logging()
    main.setup_file_logging()

    attached = [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_the_host_log_file", False)
    ]
    assert len(attached) == 1


# -------------------------------------------------------- agent_log.session_id


def test_agent_log_has_a_session_id_column():
    assert "session_id" in _agent_log_columns()


def test_the_migration_adds_session_id_and_old_rows_read_null():
    """A booth laptop's database was written before the column existed."""
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("DROP TABLE agent_log")
        conn.execute(
            """CREATE TABLE agent_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                tool TEXT NOT NULL,
                input_args TEXT NOT NULL,
                result TEXT NOT NULL
            )"""
        )
        conn.execute(
            "INSERT INTO agent_log (timestamp, tool, input_args, result) VALUES (?, ?, ?, ?)",
            ("2026-10-21T18:19:07", "confirm_order", "{}", "{}"),
        )
        conn.commit()
    assert "session_id" not in _agent_log_columns()

    data.init_db()

    assert "session_id" in _agent_log_columns()
    assert _rows() == [{"tool": "confirm_order", "session_id": None}]


def test_log_action_stores_the_session_id():
    data.log_action("confirm_order", {"order_id": 1}, {"status": "CONFIRMED"}, session_id="09c90c15")

    assert _rows() == [{"tool": "confirm_order", "session_id": "09c90c15"}]


def test_log_action_without_a_session_stores_null():
    data.log_action("check_item_availability", {}, {"total": 5})

    assert _rows() == [{"tool": "check_item_availability", "session_id": None}]


def test_every_tool_call_carries_the_conversation_it_came_from(ctx):
    tools.check_item_availability()
    tools.build_order([{"name": "Blue Lemonade", "quantity": 1}], guest_name="Rehman")

    assert _rows() == [
        {"tool": "check_item_availability", "session_id": ctx["session_id"]},
        {"tool": "build_order", "session_id": ctx["session_id"]},
    ]


def test_a_tool_call_outside_a_session_still_logs(monkeypatch):
    """The default context is empty and shared (09 section 1); a NULL session is
    the right answer there, never a crash in the logging path."""
    tools.check_item_availability()

    assert _rows() == [{"tool": "check_item_availability", "session_id": None}]
