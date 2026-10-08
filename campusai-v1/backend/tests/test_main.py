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


def test_the_retired_records_endpoint_is_gone(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")

    with TestClient(main.app) as client:
        response = client.get("/api/records")

    # The static frontend mount answers unknown paths, so the point is only that
    # no records payload is served any more.
    assert "records" not in response.text
    assert not hasattr(data, "get_recent_log")
