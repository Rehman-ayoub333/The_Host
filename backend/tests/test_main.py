import importlib
import os

import dotenv
import pytest
from fastapi.testclient import TestClient

import config
import data
import main


def test_health_reports_the_menu_row_count(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "model": config.GEMINI_LIVE_MODEL,
        "menu_items": 5,
        "operational_mode": "ONLINE",
        "db": "ok",
        "components": {"backend": "online", "ai_agent": "online", "database": "ok"},
    }


def test_startup_refuses_to_open_with_an_empty_menu(monkeypatch, tmp_path):
    empty_menu = tmp_path / "empty_menu.json"
    empty_menu.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(config, "MENU_JSON_PATH", empty_menu)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "empty.db")

    with pytest.raises(RuntimeError, match="The menu is empty"):
        with TestClient(main.app):
            pass


def test_the_default_voice_is_sulafat():
    """16 section 2e item 3. Reloaded with the .env loader disabled, so the test
    reads nothing out of the real .env and a value there still wins at runtime.
    """
    saved = os.environ.pop("GEMINI_VOICE", None)
    original_loader = dotenv.load_dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    try:
        importlib.reload(config)
        print("GEMINI_VOICE with nothing configured:", config.GEMINI_VOICE)
        assert config.GEMINI_VOICE == "Sulafat"

        os.environ["GEMINI_VOICE"] = "Puck"
        importlib.reload(config)
        print("GEMINI_VOICE with the environment set:", config.GEMINI_VOICE)
        assert config.GEMINI_VOICE == "Puck"
    finally:
        dotenv.load_dotenv = original_loader
        os.environ.pop("GEMINI_VOICE", None)
        if saved is not None:
            os.environ["GEMINI_VOICE"] = saved
        importlib.reload(config)


def test_the_example_env_ships_the_new_default():
    lines = (config.BASE_DIR / ".env.example").read_text(encoding="utf-8").splitlines()
    print("GEMINI_VOICE line:", [line for line in lines if line.startswith("GEMINI_VOICE")])
    assert "GEMINI_VOICE=Sulafat" in lines


def test_the_root_page_says_where_the_display_is(monkeypatch):
    """16 section 2v item 5: the old voice page is retired.

    Ported from test_the_voice_page_is_never_cached (2e item 2, a stale app.js).
    The backend serves no static files at all now, so there is nothing left to
    cache; the one thing `/` has to do is say where THE HOST actually is.
    """
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        response = client.get("/")
        print(f"GET / -> {response.status_code} {response.headers.get('content-type')!r}")
        print("body:", response.text.strip())
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert response.headers["cache-control"] == "no-store"
        assert "THE HOST backend is running" in response.text
        assert "http://localhost:8080/display" in response.text

        # Nothing static is served any more, so a file of the retired page is a
        # plain 404 rather than a hit.
        for path in ("/app.js", "/index.html", "/no-such-file.js"):
            missing = client.get(path)
            print(f"GET {path} -> {missing.status_code}")
            assert missing.status_code == 404


def test_the_retired_records_endpoint_is_gone(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        response = client.get("/api/records")

    # The static frontend mount answers unknown paths, so the point is only that
    # no records payload is served any more.
    assert "records" not in response.text
    assert not hasattr(data, "get_recent_log")
