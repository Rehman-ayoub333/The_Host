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


def test_the_voice_page_is_never_cached(monkeypatch):
    """16 section 2e item 2: a stale app.js silently disabled a whole phase."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        for path in ("/", "/app.js", "/no-such-file.js"):
            response = client.get(path)
            print(
                f"GET {path} -> {response.status_code} "
                f"Cache-Control: {response.headers.get('cache-control')!r}"
            )
            assert response.headers["cache-control"] == "no-store"

        assert client.get("/").status_code == 200
        assert client.get("/app.js").status_code == 200
        missing = client.get("/no-such-file.js")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "Not Found"}

    assert isinstance(main.app.routes[-1].app, main.NoStoreStaticFiles)


def test_the_retired_records_endpoint_is_gone(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        response = client.get("/api/records")

    # The static frontend mount answers unknown paths, so the point is only that
    # no records payload is served any more.
    assert "records" not in response.text
    assert not hasattr(data, "get_recent_log")
