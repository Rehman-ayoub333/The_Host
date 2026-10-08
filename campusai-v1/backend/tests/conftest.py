import json

import pytest

import config
import data
import event_bus
import health
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

BUSINESS_INFO_SEED = [
    {"topic": "hours", "answer": "We're open for the full duration of the gala."},
    {"topic": "stall", "answer": "Bite & Pour serves fresh burgers, sandwiches, and cold drinks, made to order."},
]


@pytest.fixture(autouse=True)
def fresh_backend(tmp_path, monkeypatch):
    """Every test gets its own database and seed files, and an empty event bus."""
    menu_path = tmp_path / "menu.json"
    business_info_path = tmp_path / "business_info.json"
    menu_path.write_text(json.dumps(MENU_SEED), encoding="utf-8")
    business_info_path.write_text(json.dumps(BUSINESS_INFO_SEED), encoding="utf-8")
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu_path)
    monkeypatch.setattr(config, "BUSINESS_INFO_JSON_PATH", business_info_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "campus_ai.db")
    event_bus.PUBLISHED.clear()
    event_bus._sockets.clear()
    event_bus.set_loop(None)
    health._mode = "ONLINE"
    data.init_db()
    yield
    event_bus.PUBLISHED.clear()
    event_bus._sockets.clear()
    event_bus.set_loop(None)
    health._mode = "ONLINE"


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
