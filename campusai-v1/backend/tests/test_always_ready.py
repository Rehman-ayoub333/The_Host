"""Phase 5d: always-ready hosting (16 section 2h items 3, 5 and 8) and the
additions from the 5c live test (16 section 2i items 3, 4, 5 and 7).

The booth problems these cover: a guest had to tap "Tap to Talk" when their face
never left the camera; nearby people talking to each other started turns; the
five-minute cap cut a conversation while the guest waited for an answer; and
THE HOST invented ingredients and add-ons that are not in the data.
"""

import asyncio
import json
import logging
from datetime import datetime

import pytest
from google.genai import types
from pydantic import ValidationError

import config
import data
import doubles
import live_session
import prompts
import schemas
import tools
from live_session import LiveSession


def feed(session, ws, payload):
    """Hand the uplink one browser message and let it run to the disconnect."""
    ws.messages.append({"type": "websocket.receive", "text": json.dumps(payload)})
    asyncio.run(session._uplink())


def texts(session):
    """Every text instruction the backend sent Gemini, in order."""
    return [
        sent["text"]
        for sent in session.session.inputs
        if isinstance(sent.get("text"), str)
    ]


# ------------------------------------- 2h item 3: trigger=voice and its opening


def test_the_socket_accepts_voice_as_a_trigger():
    import main

    assert main.websocket_session is not None
    # The query-parameter narrowing main.py applies, with the same inputs the
    # page can produce.
    def narrow(value):
        trigger = value
        if trigger not in ("presence", "voice"):
            trigger = "button"
        return trigger

    assert narrow("voice") == "voice"
    assert narrow("presence") == "presence"
    assert narrow("button") == "button"
    assert narrow("nonsense") == "button"


def test_voice_trigger_sends_the_say_it_again_opening():
    session, _ws = doubles.new_session(trigger="voice")
    asyncio.run(
        session.session.send_realtime_input(
            text=prompts.OPENING_INSTRUCTIONS.get(
                session.trigger, prompts.GREETING_BUTTON
            )
        )
    )
    sent = texts(session)[0]
    assert sent == prompts.GREETING_VOICE
    # Not the full welcome: it asks for the unheard words again.
    assert "probably not heard" in sent
    assert "say it again" in sent
    assert "Do not give the full welcome" in sent
    assert sent != prompts.GREETING_PRESENCE
    assert sent != prompts.GREETING_BUTTON


def test_the_other_triggers_keep_their_own_opening():
    assert prompts.OPENING_INSTRUCTIONS["presence"] == prompts.GREETING_PRESENCE
    assert prompts.OPENING_INSTRUCTIONS["button"] == prompts.GREETING_BUTTON
    assert prompts.OPENING_INSTRUCTIONS["voice"] == prompts.GREETING_VOICE
    # A trigger nobody has heard of still gets a welcome, never nothing.
    assert (
        prompts.OPENING_INSTRUCTIONS.get("surprise", prompts.GREETING_BUTTON)
        == prompts.GREETING_BUTTON
    )


# ------------------------------------------- 2h item 5: the VAD field it sets


def test_the_connect_config_asks_for_low_start_sensitivity():
    built = live_session.build_live_config(datetime.now())
    detection = built.realtime_input_config.automatic_activity_detection
    assert (
        detection.start_of_speech_sensitivity
        == types.StartSensitivity.START_SENSITIVITY_LOW
    )


def test_every_other_vad_field_stays_at_the_server_default():
    built = live_session.build_live_config(datetime.now())
    detection = built.realtime_input_config.automatic_activity_detection
    assert detection.disabled is None
    assert detection.end_of_speech_sensitivity is None
    assert detection.prefix_padding_ms is None
    assert detection.silence_duration_ms is None


# ------------------------------- 2h item 5: proactive audio, both paths


def test_proactive_audio_is_absent_unless_it_is_asked_for():
    assert live_session.build_live_config(datetime.now()).proactivity is None
    assert (
        live_session.build_live_config(datetime.now(), False).proactivity is None
    )


def test_proactive_audio_is_set_when_it_is_asked_for():
    built = live_session.build_live_config(datetime.now(), True)
    assert built.proactivity is not None
    assert built.proactivity.proactive_audio is True


def test_it_is_left_off_after_the_build_time_check():
    # 2h item 5: gemini-3.8-live rejects the field, so the built system does not
    # pay for a refused connect on every conversation.
    assert config.PROACTIVE_AUDIO is False


class _Refusing:
    """A client whose first connect is refused and whose second one works."""

    def __init__(self, fail_while_proactive=True):
        self.fail_while_proactive = fail_while_proactive
        self.attempts = []

    def attempt(self, proactive):
        self.attempts.append(proactive)
        if proactive and self.fail_while_proactive:
            raise RuntimeError(
                'Invalid JSON payload received. Unknown name "proactivity" at '
                "'setup': Cannot find field."
            )
        return doubles.FakeLiveApiSession()


def _patch_open(monkeypatch, client):
    async def fake_open(self, _client, proactive):
        return client.attempt(proactive)

    monkeypatch.setattr(LiveSession, "_open", fake_open)


def _reset_proactive_state(monkeypatch, enabled):
    monkeypatch.setattr(config, "PROACTIVE_AUDIO", enabled)
    monkeypatch.setattr(live_session, "_proactive_audio_ok", True)
    monkeypatch.setattr(live_session, "_proactive_unsupported_logged", False)


def test_a_refused_setup_falls_back_and_the_conversation_still_happens(
    monkeypatch, caplog
):
    _reset_proactive_state(monkeypatch, True)
    client = _Refusing()
    _patch_open(monkeypatch, client)
    session, _ws = doubles.new_session()
    session.session = None

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session._start())

    # Tried with it, then without it, and the session is live either way.
    assert client.attempts == [True, False]
    assert session.session is not None
    assert "proactive_audio unsupported" in caplog.text
    # The raw refusal is kept, so the reason is on the record.
    assert "Cannot find field" in caplog.text
    asyncio.run(session.stop())


def test_the_refusal_is_logged_once_for_the_whole_process(monkeypatch, caplog):
    _reset_proactive_state(monkeypatch, True)
    client = _Refusing()
    _patch_open(monkeypatch, client)

    with caplog.at_level(logging.INFO, logger="live_session"):
        for _ in range(3):
            session, _ws = doubles.new_session()
            session.session = None
            asyncio.run(session._start())
            asyncio.run(session.stop())

    assert caplog.text.count("proactive_audio unsupported") == 1
    # Only the first conversation pays for the refused attempt; the rest go
    # straight to a plain connect.
    assert client.attempts == [True, False, False, False]


def test_nothing_is_attempted_when_it_is_switched_off(monkeypatch, caplog):
    _reset_proactive_state(monkeypatch, False)
    client = _Refusing()
    _patch_open(monkeypatch, client)
    session, _ws = doubles.new_session()
    session.session = None

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session._start())

    assert client.attempts == [False]
    assert "proactive_audio" not in caplog.text
    asyncio.run(session.stop())


def test_a_real_connect_failure_is_not_swallowed(monkeypatch):
    _reset_proactive_state(monkeypatch, False)

    async def always_fails(self, _client, _proactive):
        raise RuntimeError("the network is down")

    monkeypatch.setattr(LiveSession, "_open", always_fails)
    session, _ws = doubles.new_session()
    session.session = None

    with pytest.raises(RuntimeError, match="the network is down"):
        asyncio.run(session._start())


# ------------------------------------------------ 2i item 3: the polite wrap-up


def test_the_wrap_up_message_takes_nothing_but_its_type():
    assert schemas.WrapUpMessage.model_validate({"type": "wrap_up"}).type == "wrap_up"
    with pytest.raises(ValidationError):
        schemas.WrapUpMessage.model_validate({"type": "wrap_down"})


def test_wrap_up_sends_the_goodbye_instruction_and_logs_it(caplog):
    session, ws = doubles.new_session()
    with caplog.at_level(logging.INFO, logger="live_session"):
        feed(session, ws, {"type": "wrap_up"})

    assert texts(session) == [prompts.WRAP_UP_PROMPT]
    assert "help other visitors now" in prompts.WRAP_UP_PROMPT
    assert "goodbye in one short sentence" in prompts.WRAP_UP_PROMPT
    assert f"wrap_up session {session.ctx['session_id']}" in caplog.text


def test_a_wrong_type_never_validates_as_a_wrap_up():
    # The uplink dispatches on the type, so this is the only way the model can
    # refuse a payload: wrap_up carries nothing else to get wrong.
    for payload in ({"type": "wrap_down"}, {"type": ""}, {}):
        with pytest.raises(ValidationError):
            schemas.WrapUpMessage.model_validate(payload)


def test_a_stray_extra_field_is_ignored_like_every_other_browser_message():
    session, ws = doubles.new_session()
    feed(session, ws, {"type": "wrap_up", "reason": []})
    # Same tolerance as voice_activity and session_end: unknown keys are
    # dropped rather than throwing the conversation away.
    assert texts(session) == [prompts.WRAP_UP_PROMPT]


def test_an_unknown_browser_message_is_still_refused(caplog):
    session, ws = doubles.new_session()
    with caplog.at_level(logging.WARNING, logger="live_session"):
        feed(session, ws, {"type": "wrap_up_please"})

    assert texts(session) == []
    assert "ignored unknown browser message type" in caplog.text


def test_wrap_up_does_not_touch_the_order_draft():
    session, ws = doubles.new_session()
    session.ctx["pending_order_id"] = 41
    feed(session, ws, {"type": "wrap_up"})
    # 2i item 3: the draft is left to the existing end-of-session rules.
    assert session.ctx["pending_order_id"] == 41


# ------------------------------------------ 2i item 4: the optional menu fields


RICH_ITEM = {
    "name": "Mint Lemonade",
    "category": "Drinks",
    "price": "Rs. 300",
    "description": "Fresh mint, pressed lemon.",
    "image_url": "",
    "available": True,
    "prep_seconds": 60,
    "ingredients": ["lemon", "mint", "sugar"],
    "allergens": ["none known"],
    "tags": ["cold", "sweet"],
    "add_ons": ["extra mint"],
}


def seed_with(monkeypatch, tmp_path, rows):
    menu_path = tmp_path / "rich_menu.json"
    menu_path.write_text(json.dumps(rows), encoding="utf-8")
    monkeypatch.setattr(config, "MENU_JSON_PATH", menu_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "rich.db")
    data.init_db()


def test_the_five_current_items_carry_none_of_the_optional_fields():
    # 2i item 4: no invented values. Rehman supplies real ones with the real menu.
    for row in data.get_menu():
        for field in data.MENU_OPTIONAL_FIELDS:
            assert field not in row, f"{row['name']} invented a {field}"


def test_the_fields_come_back_when_the_menu_really_has_them(monkeypatch, tmp_path):
    seed_with(monkeypatch, tmp_path, [RICH_ITEM])
    item = data.get_menu_item("Mint Lemonade")
    assert item["ingredients"] == ["lemon", "mint", "sugar"]
    assert item["allergens"] == ["none known"]
    assert item["tags"] == ["cold", "sweet"]
    assert item["add_ons"] == ["extra mint"]


def test_a_tool_returns_the_fields_when_present_and_omits_them_when_absent(
    monkeypatch, tmp_path, ctx
):
    plain = dict(RICH_ITEM, name="Plain Water", price="Rs. 50")
    for field in data.MENU_OPTIONAL_FIELDS:
        plain.pop(field)
    seed_with(monkeypatch, tmp_path, [RICH_ITEM, plain])

    returned = {
        item["name"]: item
        for item in tools.check_item_availability()["items"]
    }
    assert returned["Mint Lemonade"]["tags"] == ["cold", "sweet"]
    assert returned["Mint Lemonade"]["ingredients"] == ["lemon", "mint", "sugar"]
    for field in data.MENU_OPTIONAL_FIELDS:
        # Missing means unknown, so the model is told nothing rather than "none".
        assert field not in returned["Plain Water"]


def test_an_unknown_tag_is_dropped_and_an_all_unknown_list_stays_unknown(
    monkeypatch, tmp_path
):
    rows = [
        dict(RICH_ITEM, name="Half Known", tags=["cold", "fizzy"]),
        dict(RICH_ITEM, name="None Known", tags=["fizzy"]),
    ]
    seed_with(monkeypatch, tmp_path, rows)
    assert data.get_menu_item("Half Known")["tags"] == ["cold"]
    # Not an empty list: an empty list would claim the item has no tags at all.
    assert "tags" not in data.get_menu_item("None Known")


def test_a_field_of_the_wrong_shape_is_ignored_not_crashed(monkeypatch, tmp_path):
    seed_with(monkeypatch, tmp_path, [dict(RICH_ITEM, name="Odd", ingredients="lemon")])
    item = data.get_menu_item("Odd")
    assert item is not None
    assert "ingredients" not in item


def test_an_older_database_gains_the_columns(monkeypatch, tmp_path):
    # A database from an earlier phase has none of the four columns.
    db_path = tmp_path / "old.db"
    monkeypatch.setattr(config, "DB_PATH", db_path)
    import sqlite3

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE menu_items (
                name TEXT PRIMARY KEY,
                category TEXT NOT NULL DEFAULT '',
                price TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                image_url TEXT NOT NULL DEFAULT '',
                available INTEGER NOT NULL DEFAULT 1,
                prep_seconds INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            "INSERT INTO menu_items (name, price) VALUES ('Old Item', 'Rs. 10')"
        )

    data.init_db()
    item = data.get_menu_item("Old Item")
    assert item["price"] == "Rs. 10"
    for field in data.MENU_OPTIONAL_FIELDS:
        assert field not in item


# ------------------------------------------------- 2i item 5: the prompt rules


RULES = [
    # Answered only from the data, with the exact words for a missing detail.
    "Ingredients, preparation, allergens, portion and customisation questions "
    "are answered only from the menu and business data.",
    "I don't have that detail — the team at the counter can tell you.",
    "Never invent garnishes, add-ons or methods.",
    # Allergies: no guarantee, no disclaimer.
    "Allergy questions: never guarantee safety.",
    "should check with the team before ordering",
    'Never add a "not medical advice" disclaimer.',
    # Categories are reasoned over, not refused.
    'Category questions ("something sweet", "spicy", "cold")',
    'say what fits instead of "we don\'t have any"',
    # The closest real item, never "could not find it".
    "offer the closest real item",
    "Our Chicken Burger is the crispy one — would you like that?",
    # One welcome per conversation.
    "Welcome a guest only once per conversation, even if later speech sounds "
    "like a greeting.",
    # Language and length.
    "Reply in the language the guest uses (English or Urdu); if unsure, English.",
]


@pytest.mark.parametrize("rule", RULES)
def test_the_system_prompt_carries_each_rule(rule):
    assert rule in prompts.build_system_instruction(datetime.now())


def test_the_rules_are_recorded_in_the_spec():
    # 2i item 5: 09 section 15 is where the prompt is written down. That folder
    # is git-ignored, so a fresh clone has no copy to check against.
    spec_file = config.BASE_DIR.parent.parent / "host-spec" / "09-TOOL-ARCHITECTURE.md"
    if not spec_file.is_file():
        pytest.skip("the host-spec folder is not in this checkout")
    spec = spec_file.read_text(encoding="utf-8")
    for rule in RULES:
        assert rule in spec, f"09 section 15 does not record: {rule[:40]}"


def test_no_robotic_medical_disclaimer_is_asked_for():
    built = prompts.build_system_instruction(datetime.now())
    # The 5c test heard one; the rule forbids it rather than inviting it.
    assert "not medical advice" in built
    assert "Never add a" in built


def test_the_agent_is_never_called_anything_but_the_host():
    built = prompts.build_system_instruction(datetime.now())
    assert config.AGENT_NAME == "THE HOST"
    for other in ("CampusAI", "Campus AI", "Gemini", "assistant"):
        assert other not in built
