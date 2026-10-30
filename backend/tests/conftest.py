import json
from pathlib import Path

import pytest

import config
import data
import event_bus
import health
import netlify_feedback
import tools


# Mirrors backend/data/menu.json and backend/data/business_info.json (15 sections 2 and 2a)
# so the tests exercise the same items the stall actually starts with.
MENU_SEED = [
    {"name": "Chicken Burger", "category": "Mains", "price": "Rs. 650", "description": "Crispy chicken, signature sauce, freshly assembled.", "image_url": "/menu/chicken-burger.jpg", "available": True, "prep_seconds": 300},
    {"name": "Club Sandwich", "category": "Mains", "price": "Rs. 550", "description": "Triple-layered, grilled, served with fries.", "image_url": "/menu/club-sandwich.jpg", "available": True, "prep_seconds": 240},
    {"name": "Patty Burger", "category": "Mains", "price": "Rs. 500", "description": "Classic beef patty, fresh-baked bun.", "image_url": "/menu/patty-burger.jpg", "available": True, "prep_seconds": 300},
    {"name": "Blue Lemonade", "category": "Drinks", "price": "Rs. 250", "description": "Butterfly-pea lemonade, lightly sweet.", "image_url": "/menu/blue-lemonade.jpg", "available": True, "prep_seconds": 60},
    {"name": "Mixed Fruit Shake", "category": "Drinks", "price": "Rs. 350", "description": "Seasonal fruit, blended fresh.", "image_url": "/menu/fruit-shake.jpg", "available": True, "prep_seconds": 120},
]

# 16 section 2k item 7 requires four identity topics with EXACT text, so the
# real seed file is the fixture: inlining a copy here would let the two drift
# and the exactness test would be checking the copy.
BUSINESS_INFO_SEED = json.loads(
    (Path(__file__).resolve().parent.parent / "data" / "business_info.json").read_text(
        encoding="utf-8"
    )
)


@pytest.fixture(autouse=True)
def fresh_backend(tmp_path, monkeypatch):
    """Every test gets its own database and seed files, and an empty event bus."""
    menu_path = tmp_path / "menu.json"
    business_info_path = tmp_path / "business_info.json"
    menu_path.write_text(json.dumps(MENU_SEED), encoding="utf-8")
    business_info_path.write_text(json.dumps(BUSINESS_INFO_SEED), encoding="utf-8")
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu_path)
    monkeypatch.setattr(config, "BUSINESS_INFO_JSON_PATH", business_info_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "the_host.db")
    # 16 section 2t item 7: a test that starts the app runs the lifespan, which
    # opens the log file. Without this every such test writes into the real
    # backend/logs/ file and mixes its doubles' numbers into a phase's evidence.
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    event_bus.PUBLISHED.clear()
    event_bus._sockets.clear()
    event_bus.set_loop(None)
    health._mode = "ONLINE"
    health._override = None
    # 16 section 2zi item 4(b): the import status is one module-level object, so
    # a test that imported something would otherwise leave "ok" behind for the
    # /health tests to trip over.
    netlify_feedback.STATUS.__init__()
    netlify_feedback._off_logged = False
    # 16 section 2zj item 7: the lifespan starts the feedback importer as a
    # background task (main.py: "at startup then every minute"). With a real
    # NETLIFY_TOKEN in backend/.env that task is live, so it reached Netlify
    # while the test ran and wrote its outcome into the one module-level STATUS
    # object -- which is exactly what the /health tests assert is pristine. On
    # 30 Oct that made test_main and test_metrics fail with
    # last_error="ConnectError" in a full run and pass on their own: the result
    # depended on whether the laptop's network answered inside the window.
    #
    # The loop is replaced rather than the token, so the importer's own tests
    # keep exercising import_once and only the background task is neutralised.
    # It is reset for every test, so no test can start the real one by accident.
    async def no_import_loop() -> None:
        return None

    monkeypatch.setattr(netlify_feedback, "import_loop", no_import_loop)
    data.init_db()
    yield
    event_bus.PUBLISHED.clear()
    event_bus._sockets.clear()
    event_bus.set_loop(None)
    health._mode = "ONLINE"
    health._override = None
    netlify_feedback.STATUS.__init__()
    netlify_feedback._off_logged = False


@pytest.fixture
def host_data():
    return data


@pytest.fixture
def ctx():
    """A session context of this test's own, as 09 section 1 requires."""
    own = {
        "session_id": "a1b2c3d4",
        "visitor_name": None,
        "pending_order_id": None,
        "awaiting_confirmation": False,
    }
    token = tools.SESSION_CTX.set(own)
    yield own
    tools.SESSION_CTX.reset(token)
