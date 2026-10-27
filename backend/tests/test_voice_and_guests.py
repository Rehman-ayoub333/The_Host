"""Phase 5g: THE HOST's voice, guests of honour, and the handle fallback
(16 section 2m items 2-8).

What these cover, all from the final backend voice test: both long outages ended
in `live recovery failed` after every attempt was refused with an `APIError`
carrying the stored handle; the greetings read as generic; there was no protocol
for the Vice Chancellor or the chief guest; a question about the team's roles
got a few words each; and "today.Can I" appeared on the screen.
"""

import asyncio
import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime

import pytest
from google.genai import errors

import config
import data
import doubles
import event_bus
import live_session
import prompts
import summaries
import tools
from live_session import LiveDropped, LiveSession


BURGER = {"name": "Chicken Burger", "quantity": 1}

# 16 section 2m item 3: the filler THE HOST may never use. The STYLE section
# names them to forbid them, so the system instruction is deliberately not one
# of the strings scanned below.
BANNED_FILLER = (
    "Great question",
    "Absolutely!",
    "I can definitely help with that",
    "How can I assist you today?",
    "As an AI",
    "I'm just an AI",
)

# 16 section 2m item 4, exactly: the twelve approved greeting lines.
GREETING_LINES_2M = (
    "Assalam-o-Alaikum, and welcome to Bite & Pour! I'm THE HOST — what are we having today?",
    "Welcome to Bite & Pour. I'm THE HOST — I never take a break, so you have my full attention.",
    "You found us! I'm THE HOST. Tell me what you're craving, and I'll make it happen.",
    "Welcome to Bite & Pour — where the food is hot and the host is artificial. What'll it be?",
    "Good to see you! I'm THE HOST. Something to eat, something cold to drink, or both?",
    "Step right up — I'm THE HOST, and the kitchen is ready when you are.",
    "Welcome! I'm THE HOST — I don't eat, but I know exactly what's good here.",
    "Assalam-o-Alaikum! I'm THE HOST. Hungry, thirsty, or just here to meet an AI?",
    "Welcome to Bite & Pour. I'm THE HOST — see, understand, act. Let's start with your order.",
    "Ah, a new guest! I'm THE HOST. What can Bite & Pour get started for you?",
    "Welcome in! I'm THE HOST — one AI, one stall, and a kitchen waiting for your order.",
    "Hello and welcome. I'm THE HOST — you talk, I take care of the rest. What would you like?",
)


def api_error(code):
    """The exception google-genai raises for `code`, as the SDK builds it."""
    try:
        errors.APIError.raise_error(code, {"code": code, "message": "no"}, None)
    except Exception as exc:
        return exc
    raise AssertionError("raise_error did not raise")


def order_events():
    return [
        event
        for event in event_bus.PUBLISHED
        if event["type"] in ("order_created", "order_updated")
    ]


def order_row(order_id):
    """The raw database row, read without data.py's parsing or lazy expiry."""
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, status, guest_name, complimentary FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    return dict(row) if row else None


# --------------------------------------------- 2m item 4: the greeting list


def test_the_greeting_list_is_exactly_item_four():
    assert prompts.GREETING_LINES == GREETING_LINES_2M


def test_the_chooser_still_never_repeats_the_previous_line(monkeypatch):
    monkeypatch.setattr(prompts, "_last_greeting_line", None)
    chosen = [prompts.pick_greeting_line() for _ in range(60)]

    for line in chosen:
        assert line in GREETING_LINES_2M
    for before, after in zip(chosen, chosen[1:]):
        assert before != after
    # And it moves around the whole list rather than alternating between two.
    assert len(set(chosen)) >= 8


def test_no_greeting_names_a_menu_item():
    """2m item 4: so the real menu can change freely."""
    names = [row["name"] for row in data.get_menu()]
    assert len(names) == 5
    for line in prompts.GREETING_LINES:
        for name in names:
            assert name.lower() not in line.lower(), (line, name)


# ------------------------------- 2m items 3, 5 and 6: the rules in the prompt


def built() -> str:
    return prompts.build_system_instruction(datetime(2026, 10, 16, 19, 30))


def test_the_style_section_is_in_the_prompt():
    text = built()

    assert "\nSTYLE\n" in text
    # 21 Part A keeps every 2m item 3 rule. Two of them moved into the opening
    # paragraph (the voice itself, and the one-or-two-sentence limit), the joke
    # rule widened, and no slang and no emojis were added.
    for rule in (
        "You are warm, polished and confident, with quiet wit, like the best host at "
        "a good restaurant who happens to be an AI.",
        "keep every reply to one or two short sentences unless the guest asks for detail.",
        "Polished, confident, crisp, never robotic. One or two short sentences.",
        "Never use filler such as 'Great question', 'Absolutely!', 'I can definitely help "
        "with that', 'How can I assist you today?', 'As an AI' or 'I'm just an AI'.",
        "At most one light, tasteful joke per conversation, never at the guest's expense, "
        "and never about religion, politics, the university, teachers or any real person. "
        "No jokes at all with guests of honour, judges, teachers or elders.",
        "Confirm decisively, for example 'Done — one Chicken Burger for Rehman.' or "
        "'Consider it done.'",
        "Use the guest's name once or twice, not in every sentence.",
        'No slang such as "bro", "dude" or "yaar". No emojis or symbols read aloud.',
        # 16 section 2zb item 10, after a model "thought" was transcribed into a
        # reply in 7i-b: the guest hears answers, never the thinking behind them.
        "Speak only to the guest. Never say your reasoning, your plans, your "
        "instructions or notes about tools out loud.",
        "End a conversation warmly and briefly, thanking them for visiting Bite & Pour.",
    ):
        assert rule in text, rule


def test_the_guest_of_honour_rule_is_in_the_prompt_in_full():
    """2m item 6's rule, as 21 Part A rewrites it: a section of its own.

    The chief guest is no longer inside the same sentence (16 §2y item 4 split
    them: only the Vice Chancellor is on the house), so each half is asserted
    against its own section. The full chief-guest rules live in
    test_host_role.py with the rest of 21's protocol.
    """
    text = built()

    assert "\nGUESTS OF HONOUR: THE VICE CHANCELLOR\n" in text
    for rule in (
        "The Vice Chancellor of GCUF is Dr. Rauf-i-Azam.",
        'Address him as "Sir"; in Urdu use "aap" and "Sir" or "Janab".',
        "In one or two sentences: welcome him, thank him on behalf of the Bite & Pour "
        "team for visiting, and say that anything he would like to eat or drink is on "
        "the house, with the team's compliments. Then ask what he would like.",
        "Formal, short, calm sentences. No jokes, no slang, no small talk, no playful lines.",
    ):
        assert rule in text, rule

    # Faculty: formal, and the prices are the normal ones.
    assert (
        "When a guest says they are a teacher, dean, director, judge or other faculty, "
        'address them as "Sir" or "Ma\'am" on the same rule as above, be formal, thank '
        "them for visiting, and use no jokes." in text
    )
    assert "Normal prices apply. Only the Vice Chancellor is on the house." in text


def test_the_full_roles_rule_is_in_the_prompt():
    # 21 Part A shortens the same rule; the full role and the stop both stay.
    assert (
        "Give their roles only when asked; then give each member's full role from the "
        "team topic in one natural sentence each, and stop. Never shorten a role."
    ) in built()


def test_the_complimentary_guests_topic_is_stored_with_the_exact_text():
    rows = data.get_business_info("complimentary_guests")

    assert len(rows) == 1
    # 16 §2y item 4: Rehman's ruling. Only the Vice Chancellor is on the house.
    # 16 §2ze item 4 adds the name and spells out the "no one else" half.
    assert rows[0]["answer"] == (
        "The Vice Chancellor, Dr. Rauf-i-Azam, is a guest of the Bite & Pour team: "
        "anything he would like to eat or drink is on the house. No one else is on "
        "the house."
    )
    # It is served by the existing tool, inside the 2y item 2 cap of 12.
    answers = {row["topic"]: row["answer"] for row in tools.get_business_info()["answers"]}
    assert answers["complimentary_guests"] == rows[0]["answer"]


# ------------------------------------------- 2m item 3: no filler anywhere


def greetings_and_templates() -> dict:
    """Every greeting and prompt template the module hands to the model.

    Deliberately not `_SYSTEM_INSTRUCTION_TEMPLATE`: the STYLE section has to
    quote the banned phrases in order to ban them.
    """
    strings = {
        f"GREETING_LINES[{index}]": line
        for index, line in enumerate(prompts.GREETING_LINES)
    }
    for name in dir(prompts):
        if name.startswith("_SYSTEM_INSTRUCTION"):
            continue
        value = getattr(prompts, name)
        if isinstance(value, str) and name.isupper():
            strings[name] = value
    strings["greeting_instruction"] = prompts.greeting_instruction(
        prompts.GREETING_LINES[0]
    )
    for trigger in prompts.OPENING_TRIGGERS:
        strings[f"opening_instruction({trigger})"] = prompts.opening_instruction(trigger)
    return strings


def test_no_banned_filler_appears_in_any_greeting_or_template():
    scanned = greetings_and_templates()

    # The scan really did reach the greetings and the templates.
    assert len(scanned) >= 20
    assert any(name.startswith("GREETING_LINES[") for name in scanned)
    assert "ORPHAN_DRAFT_TEMPLATE" in scanned

    for name, text in scanned.items():
        for phrase in BANNED_FILLER:
            assert phrase.lower() not in text.lower(), (name, phrase)


# ------------------------------------ 2m item 5: an order on the house


def test_the_complimentary_flag_is_stored_and_defaults_to_off(ctx):
    ordinary = tools.build_order([BURGER])
    assert "complimentary" not in ordinary
    assert order_row(ordinary["order_id"])["complimentary"] == 0

    free = data.create_order_draft(
        [{"name": "Mixed Fruit Shake", "quantity": 1, "price": "Rs. 350"}],
        "Sir",
        "vc-session",
        complimentary=True,
    )
    assert order_row(free["order_id"])["complimentary"] == 1


def test_build_order_takes_the_complimentary_argument(ctx):
    # 16 §2ze item 3: the name decides, so the title goes with the flag.
    result = tools.build_order([BURGER], guest_name="Vice Chancellor", complimentary=True)

    assert result["complimentary"] is True
    assert "note" not in result
    assert order_row(result["order_id"])["complimentary"] == 1
    assert data.order_view(data.get_order(result["order_id"]))["complimentary"] is True
    # The stored prices and the total are untouched, for the record.
    assert result["total"] == "Rs. 650"


def test_a_later_build_order_does_not_throw_the_flag_away(ctx):
    """The same trap 2l item 3 hit with the name: it arrives on a later call."""
    first = tools.build_order([BURGER], guest_name="Vice Chancellor", complimentary=True)
    second = tools.build_order([BURGER, {"name": "Blue Lemonade", "quantity": 1}])

    assert second["order_id"] == first["order_id"]
    assert order_row(first["order_id"])["complimentary"] == 1
    assert order_row(first["order_id"])["guest_name"] == "Vice Chancellor"


@pytest.mark.parametrize(
    "sent, stored",
    [(None, 0), (False, 0), (True, 1), ("false", 0), ("true", 1)],
    ids=["omitted", "json-false", "json-true", "string-false", "string-true"],
)
def test_a_boolean_the_model_spells_out_is_read_correctly(ctx, sent, stored):
    # Under the Vice Chancellor's own name, so this still tests the boolean and
    # not the 2ze item 3 name check.
    result = tools.build_order([BURGER], guest_name="Vice Chancellor", complimentary=sent)

    assert order_row(result["order_id"])["complimentary"] == stored


def test_the_complimentary_column_is_migrated_with_a_default_of_zero(tmp_path, monkeypatch):
    """A database from before 2m item 5 has orders but no column."""
    older = tmp_path / "pre_2m.db"
    monkeypatch.setattr(config, "DB_PATH", older)
    with closing(sqlite3.connect(older)) as conn:
        conn.execute(
            """CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                guest_name TEXT,
                items TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING_CONFIRMATION',
                announced INTEGER NOT NULL DEFAULT 0,
                session_id TEXT,
                cancel_reason TEXT,
                estimated_ready_at TEXT,
                ready_at TEXT
            )"""
        )
        conn.execute(
            "INSERT INTO orders (timestamp, guest_name, items, status) "
            "VALUES ('2026-10-16T19:00:00', 'Rehman', ?, 'CONFIRMED')",
            (json.dumps([{"name": "Chicken Burger", "quantity": 1, "price": "Rs. 650"}]),),
        )
        conn.commit()

    data.init_db()

    with closing(sqlite3.connect(older)) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
        print("orders columns after the migration:", sorted(columns))
        assert "complimentary" in columns
        assert "orphaned_at" in columns
        row = dict(conn.execute("SELECT * FROM orders WHERE id = 1").fetchone())
    print("the migrated row:", row)
    assert row["complimentary"] == 0
    # The order itself is untouched.
    assert row["guest_name"] == "Rehman" and row["status"] == "CONFIRMED"
    assert data.order_view(data.get_order(1))["complimentary"] is False


def test_every_order_event_carries_the_flag(ctx):
    order_id = tools.build_order(
        [BURGER], guest_name="Vice Chancellor", complimentary=True
    )["order_id"]
    tools.confirm_order(order_id)

    carried = order_events()
    assert [event["type"] for event in carried] == ["order_created", "order_updated"]
    for event in carried:
        print(event["type"], json.dumps(event["order"]))
        assert event["order"]["complimentary"] is True

    # And the operator's own status change, whose event body main.py builds from
    # the same view.
    moved = data.update_order_status(order_id, "PREPARING")
    print("after PREPARING:", json.dumps(data.order_view(moved["order"])))
    assert data.order_view(moved["order"])["complimentary"] is True

    # And the public display still sees the flag, with the name stripped.
    smd = event_bus.filter_for("smd", carried[0])
    assert smd["order"]["complimentary"] is True
    assert "guest_name" not in smd["order"]


def test_an_ordinary_order_says_so_in_its_events(ctx):
    tools.confirm_order(tools.build_order([BURGER])["order_id"])

    assert order_events()
    for event in order_events():
        assert event["order"]["complimentary"] is False


def test_the_activity_label_says_on_the_house(ctx):
    order_id = tools.build_order(
        [BURGER], guest_name="Vice Chancellor", complimentary=True
    )["order_id"]
    result = tools.confirm_order(order_id)

    row = summaries.activity_for_tool("confirm_order", {"order_id": order_id}, result)
    print("the activity row:", row)
    assert row == {
        "kind": "order",
        "label": f"Order #{order_id} created (on the house)",
        "detail": "Chicken Burger",
    }


def test_an_ordinary_order_keeps_the_plain_label(ctx):
    order_id = tools.build_order([BURGER])["order_id"]
    result = tools.confirm_order(order_id)

    row = summaries.activity_for_tool("confirm_order", {"order_id": order_id}, result)
    assert row["label"] == f"Order #{order_id} created"


def test_the_tool_declaration_offers_the_complimentary_argument():
    declaration = next(
        item for item in tools.TOOL_DECLARATIONS if item["name"] == "build_order"
    )
    argument = declaration["parameters"]["properties"]["complimentary"]

    assert argument["type"] == "boolean"
    assert "complimentary_guests" in argument["description"]
    # It is optional: only the items are ever required.
    assert declaration["parameters"]["required"] == ["items"]


# ----------------------------- 2m item 2: the handle fallback and result=


class Connects:
    """Scripted connects. An exception instance is raised; anything else is the
    new connection. Records the handle each attempt was given."""

    def __init__(self, results):
        self.results = list(results)
        self.handles = []

    def hook(self):
        async def _connect(_session, _client, handle=None):
            self.handles.append(handle)
            result = self.results.pop(0) if self.results else RuntimeError("down")
            if isinstance(result, BaseException):
                raise result
            return result

        return _connect

    def install(self, monkeypatch):
        monkeypatch.setattr(LiveSession, "_connect", self.hook())


def dropped(results, *, handle="handle-1"):
    session, ws = doubles.new_session()
    session.resume_handle = handle
    session.greeted = True
    return session, ws, Connects(results)


def test_an_api_error_means_the_next_attempt_has_no_handle(monkeypatch, caplog):
    """The 5f outages: refused with the handle, over and over."""
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, _ws, connects = dropped(
        [api_error(1008), api_error(1008), doubles.FakeLiveApiSession()]
    )
    connects.install(monkeypatch)

    with caplog.at_level(logging.INFO, logger="live_session"):
        assert asyncio.run(session._recover(LiveDropped("APIError"))) is True

    # First with it; every attempt after it without, as item 2 requires.
    assert connects.handles == ["handle-1", None, None]
    assert session.resume_handle is None
    assert "live resumption handle refused session" in caplog.text
    assert "n=3 resumed=false result=ok" in caplog.text


def test_a_network_error_keeps_the_handle(monkeypatch):
    """gaierror, another OSError, a timeout: the server was never reached."""
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, _ws, connects = dropped(
        [
            OSError("[Errno 11001] getaddrinfo failed"),
            asyncio.TimeoutError(),
            doubles.FakeLiveApiSession(),
        ]
    )
    connects.install(monkeypatch)

    asyncio.run(session._recover(LiveDropped("APIError")))

    assert connects.handles == ["handle-1", "handle-1", "handle-1"]
    assert session.resume_handle == "handle-1"


def test_the_two_rules_together_are_the_live_outage(monkeypatch, caplog):
    """2m item 1's finding: gaierror first, then APIError once DNS worked."""
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, _ws, connects = dropped(
        [
            OSError("[Errno 11001] getaddrinfo failed"),
            OSError("[Errno 11001] getaddrinfo failed"),
            api_error(1008),
            doubles.FakeLiveApiSession(),
        ]
    )
    connects.install(monkeypatch)

    with caplog.at_level(logging.INFO, logger="live_session"):
        assert asyncio.run(session._recover(LiveDropped("APIError"))) is True

    assert connects.handles == ["handle-1", "handle-1", "handle-1", None]
    lines = [line for line in caplog.text.splitlines() if "live reconnect attempt" in line]
    for line in lines:
        print(line.strip())
    assert "n=1 resumed=true result=OSError" in lines[0]
    assert "n=2 resumed=true result=OSError" in lines[1]
    assert "n=3 resumed=true result=APIError:1008" in lines[2]
    assert "n=4 resumed=false result=ok" in lines[3]


def test_the_result_shows_the_error_type_and_its_code():
    assert live_session.attempt_result(api_error(1008)) == "APIError:1008"
    assert live_session.attempt_result(api_error(400)) == "ClientError:400"
    assert live_session.attempt_result(api_error(503)) == "ServerError:503"
    assert live_session.attempt_result(OSError("getaddrinfo failed")) == "OSError"
    assert live_session.attempt_result(asyncio.TimeoutError()) == "TimeoutError"


def test_the_result_never_carries_the_error_text_and_is_capped():
    secret = "key=AIzaSECRETSECRET and " + "x" * 400
    result = live_session.attempt_result(RuntimeError(secret))

    assert result == "RuntimeError"
    assert "AIza" not in result
    assert len(live_session.attempt_result(api_error(1008))) <= 80


def test_which_failures_drop_the_handle():
    assert live_session.drops_the_handle(api_error(1008)) is True
    assert live_session.drops_the_handle(api_error(400)) is True
    assert live_session.drops_the_handle(api_error(503)) is True
    assert live_session.drops_the_handle(OSError("getaddrinfo failed")) is False
    assert live_session.drops_the_handle(asyncio.TimeoutError()) is False
    assert live_session.drops_the_handle(RuntimeError("timed out")) is False


# --------------------------------------- 2m item 7: the transcript spacing


@pytest.mark.parametrize(
    "first, second, joined",
    [
        ("Enjoy your day today.", "Can I get you anything else?",
         "Enjoy your day today. Can I get you anything else?"),
        ("Done!", "One Chicken Burger.", "Done! One Chicken Burger."),
        ("Shall I confirm?", "Yes?", "Shall I confirm? Yes?"),
        # Mid-word and mid-sentence fragments are untouched.
        ("Chicken Bur", "ger", "Chicken Burger"),
        ("one moment,", " checking", "one moment, checking"),
        # A fragment that already brings its own space needs no second one.
        ("today.", " Can I", "today. Can I"),
        ("Rs. ", "650", "Rs. 650"),
        ("today.", "", "today."),
    ],
)
def test_a_sentence_boundary_gets_one_space(first, second, joined):
    assert live_session.join_fragments(first, second) == joined


def test_the_booth_screen_line_is_fixed():
    """"today.Can I" is what Rehman saw at the final voice test."""
    session, ws = doubles.new_session()

    async def go():
        await session._on_transcript_fragment("agent", "Enjoy your day today.")
        await session._on_transcript_fragment("agent", "Can I get you anything else?")

    asyncio.run(go())

    assert session.transcripts["agent"] == (
        "Enjoy your day today. Can I get you anything else?"
    )
    assert doubles.transcripts(ws)[-1]["text"] == (
        "Enjoy your day today. Can I get you anything else?"
    )
    doubles.validate(ws)


def test_the_guest_s_own_words_are_joined_as_they_arrive():
    """Item 7 is about the output transcription: the input is left alone."""
    session, _ws = doubles.new_session()

    async def go():
        await session._on_transcript_fragment("visitor", "I'll have a burger.")
        await session._on_transcript_fragment("visitor", "And a lemonade.")

    asyncio.run(go())

    assert session.transcripts["visitor"] == "I'll have a burger.And a lemonade."
