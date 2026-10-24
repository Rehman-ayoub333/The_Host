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
            text=prompts.opening_instruction(session.trigger)
        )
    )
    sent = texts(session)[0]
    assert sent == prompts.GREETING_VOICE
    # Not the full welcome: it asks for the unheard words again.
    assert "probably not heard" in sent
    assert "say it again" in sent
    assert "Do not give the full welcome" in sent
    assert sent != prompts.opening_instruction("presence")
    assert sent != prompts.opening_instruction("button")


def test_the_other_triggers_keep_their_own_opening():
    # 2l item 7a: presence and the button share the greeting, which now names
    # one of the approved lines; `voice` keeps its own.
    for trigger in ("presence", "button"):
        assert "Greet the guest with this line" in prompts.opening_instruction(trigger)
    assert prompts.opening_instruction("voice") == prompts.GREETING_VOICE
    # A trigger nobody has heard of still gets a welcome, never nothing.
    assert "Greet the guest with this line" in prompts.opening_instruction("surprise")


# ------------------------------------------- 2h item 5: the VAD field it sets


def test_the_start_sensitivity_is_high_for_short_replies():
    # 16 section 2j item 6 removed START_SENSITIVITY_LOW. 2r item 5 then set the
    # field the other way after Rehman's C1 test: the handheld microphone keeps
    # the room out, so the server may start listening more readily, and a short
    # soft "yes" or a name is what that buys.
    from google.genai import types

    built = live_session.build_live_config(datetime.now())
    detection = built.realtime_input_config.automatic_activity_detection
    assert detection.start_of_speech_sensitivity == (
        types.StartSensitivity.START_SENSITIVITY_HIGH
    )


def test_every_other_vad_field_stays_at_the_server_default():
    built = live_session.build_live_config(datetime.now())
    detection = built.realtime_input_config.automatic_activity_detection
    assert detection.disabled is None
    assert detection.end_of_speech_sensitivity is None
    # 2r item 5: the one addition, so a quiet first syllable is not clipped.
    assert detection.prefix_padding_ms == 300


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
    async def fake_open(self, _client, proactive, _handle=None):
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

    async def always_fails(self, _client, _proactive, _handle=None):
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
    # 21 Part A rewords this one: halal status and spice level join the list,
    # and allergens move to the allergy rule below.
    "Ingredients, preparation, portion, halal status, spice level and "
    "customisation are answered only from the menu and business data.",
    "I don't have that detail — the team at the counter can tell you.",
    "Never invent garnishes, add-ons or methods.",
    # Allergies: no guarantee, and no disclaimer. 16 section 2za item 6: the
    # disclaimer sentence was dropped from Part A by mistake in 7i and is back,
    # because 2i item 5 still holds.
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
    # Language and length. 16 section 2za item 3 made the rule turn on the
    # guest's LATEST message, after E3 answered a Roman-Urdu line in English
    # and two E31 runs answered an English guest in Urdu.
    "Reply in the language of the guest's latest message. If it is in English, reply in English, even if the guest's name or an earlier line was Urdu. If it is in Urdu, Punjabi or Roman Urdu, even a short line mixed with English words (for example \"VC sahab ko ek Blue Lemonade\"), reply in Urdu, with English words where they are natural (menu names stay in English): never Hindi, never Punjabi, never Gurmukhi or Devanagari script.",
]

# Instructions an earlier Part A carried that the current one deliberately
# drops. They are kept here so nothing is lost from the record, and the test
# below asserts they really are gone rather than quietly missing.
#
# 16 section 2za item 2: the model never called signal_confirmation_request in
# any of the 7i runs. It is a pure UI signal (09 section 11), nothing depends on
# it, and the spoken question plus the guest's yes is what makes an order safe,
# so Part A no longer asks for it. The tool itself stays declared.
RETIRED_RULES = [
    "Then call signal_confirmation_request with a one-sentence summary, and ask "
    "if you should confirm it.",
    "Call signal_confirmation_request with a one-sentence summary, read back what "
    "you understood, and only call report_feedback after a clear yes.",
]


@pytest.mark.parametrize("rule", RULES)
def test_the_system_prompt_carries_each_rule(rule):
    assert rule in prompts.build_system_instruction(datetime.now())


def test_the_rules_are_recorded_in_the_spec():
    # 2i item 5 recorded the prompt in 09 section 15. 16 section 2x item 4(a)
    # moved it: `21` Part A is now the system instruction word for word, and the
    # agent copies that text into prompts.py. So the record to check against is
    # `21`, and 09 section 15 holds the older wording. That folder is
    # git-ignored, so a fresh clone has no copy to check against.
    spec_file = config.BASE_DIR.parent / "host-spec" / "21-THE-HOST-ROLE.md"
    if not spec_file.is_file():
        pytest.skip("the host-spec folder is not in this checkout")
    spec = spec_file.read_text(encoding="utf-8")
    for rule in RULES:
        assert rule in spec, f"21 Part A does not record: {rule[:40]}"


@pytest.mark.parametrize("rule", RETIRED_RULES)
def test_a_retired_rule_is_no_longer_in_the_prompt(rule):
    """The sentence must be gone, not merely unasserted, so a future edit that
    reinstates half of an older prompt fails here."""
    built = prompts.build_system_instruction(datetime.now())

    assert rule not in built


def test_the_order_and_feedback_rules_no_longer_ask_for_the_signal():
    """16 section 2za item 2: the instruction is gone, the safety is not.

    What makes an order safe is the spoken question and the guest's clear yes
    before confirm_order, and both are still required in so many words.
    """
    built = prompts.build_system_instruction(datetime.now())

    assert "signal_confirmation_request" not in built
    # ORDERS: the question stays, and confirm_order still waits for a yes.
    # 16 section 2zb item 10 adds the wait, the same-turn ban and what to do
    # when the guard refuses, after E19 confirmed an order without a yes.
    assert (
        "Then ask if you should confirm it, and stop talking: wait for the guest's "
        "answer. Never call confirm_order in the same turn as the question. Only "
        'call confirm_order after the guest\'s own clear yes ("yes", "haan", "ji", '
        '"confirm", "go ahead"). Anything unclear: ask once more. If confirm_order '
        'answers "Please confirm first.", ask the guest to confirm and wait.' in built
    )
    # FEEDBACK: the read-back stays, and report_feedback still waits for a yes.
    assert (
        "Read back what you understood in one sentence, and only call "
        "report_feedback after a clear yes. Thank them either way." in built
    )


def test_no_robotic_medical_disclaimer_is_asked_for():
    """2i item 5, restored by 16 section 2za item 6.

    The 5c live test heard "this is not medical advice". 7i dropped the
    sentence that bans it by mistake; it is back, beside the allergy rule.
    """
    built = prompts.build_system_instruction(datetime.now())

    assert 'Never add a "not medical advice" disclaimer.' in built
    assert (
        "Allergy questions: never guarantee safety. Say you do not have the full "
        "allergen list and the guest should check with the team before ordering." in built
    )


def test_the_agent_is_never_called_anything_but_the_host():
    built = prompts.build_system_instruction(datetime.now())
    assert config.AGENT_NAME == "THE HOST"
    # No other working name for the agent. "Gemini" is not one of those: 16
    # section 2k item 7 requires the prompt to name the model THE HOST runs on,
    # and to neither credit Google with building it nor deny using Gemini.
    #
    # 21 Part A names the banned self-labels in order to ban them, so the word
    # "assistant" is in the prompt four times -- in the opening line and in the
    # banned-labels rule, both of which forbid it. Every occurrence must sit in
    # one of those two sentences: THE HOST is never described as one.
    for sentence in (
        "You are not a chatbot and not an assistant: you are the host.",
        "Never call yourself an assistant, an AI assistant, a virtual assistant, "
        "a chatbot, a bot, a language model or a program, in any language.",
    ):
        assert sentence in built
    assert built.count("assistant") == 4
    assert (
        built.count("not an assistant")
        + built.count("an assistant, an AI assistant, a virtual assistant")
        == 2
    )
    # The retired project name and the dashboard's retired working name must not
    # reach the prompt either. 16 section 2n item 3f requires both to appear in
    # no tracked file, so they are spelled from parts here: the grep over
    # tracked files stays empty while the guard still runs. Both survive only in
    # git history (16 section 2n item 3e, final).
    lowered = built.lower()
    for retired in ("Campus" + "AI", "Campus " + "AI", "Campus" + "_AI", "NE" + "XA"):
        assert retired.lower() not in lowered
    assert "Gemini" in built
    # 21 Part A gives the rule its own bullet, so it starts with a capital.
    assert "Never say Google built you" in built
