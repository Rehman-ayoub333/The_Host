"""Phase 5f: real-outage recovery, identity, and orders that outlive a
broken conversation (16 section 2k items 2-7 and 10, section 2l items 2-6).

The booth problems these cover, all from the 5e live test: Rehman switched the
Wi-Fi off for three seconds twice and both conversations were lost outright
(sessions ced7bcbf and 03db21d2), with the unconfirmed order going with them; a
question in Urdu came back in Punjabi in Gurmukhi script; a long off-topic chat
drifted into an emotional-support persona; and asked about itself THE HOST
credited Google and did not know its own team.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import pytest

import config
import data
import doubles
import health
import live_session
import main
import prompts
import tools
from live_session import LiveDropped, LiveSession


BURGER = {"name": "Chicken Burger", "quantity": 2, "price": "Rs. 650"}


def texts(session):
    return [
        sent["text"]
        for sent in session.session.inputs
        if isinstance(sent.get("text"), str)
    ]


def events(ws, kind):
    return [sent for sent in ws.sent if sent["type"] == kind]


class Connects:
    """Scripted connects. `None` fails; anything else is the new connection."""

    def __init__(self, results):
        self.results = list(results)
        self.handles = []
        self.at = []

    def hook(self):
        async def _connect(_session, _client, handle=None):
            self.handles.append(handle)
            self.at.append(live_session._now())
            result = self.results.pop(0) if self.results else None
            if result is None:
                raise RuntimeError("the network is down")
            return result

        return _connect


def dropped_session(results, *, handle="handle-1"):
    session, ws = doubles.new_session()
    session.resume_handle = handle
    session.greeted = True
    return session, ws, Connects(results)


# ------------------------------- 2k item 2: the 30-second recovery window


def test_it_keeps_trying_every_three_seconds_for_thirty(monkeypatch, caplog):
    """The 5e failure: both attempts were spent in the first ten seconds."""
    clock = [1000.0]
    monkeypatch.setattr(live_session, "_now", lambda: clock[0])

    async def fake_sleep(seconds):
        clock[0] += seconds

    monkeypatch.setattr(live_session.asyncio, "sleep", fake_sleep)
    session, _ws, connects = dropped_session([])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    with caplog.at_level(logging.INFO, logger="live_session"):
        assert asyncio.run(session._recover(LiveDropped("APIError"))) is False

    # One at once, then one every RECOVER_RETRY_S while the window is open: at
    # 0, 3, 6 ... 27 seconds. The next would fall on 30, by which time the
    # window has passed, so it is not made.
    assert len(connects.at) == 10
    gaps = [round(b - a, 3) for a, b in zip(connects.at, connects.at[1:])]
    assert gaps == [float(config.RECOVER_RETRY_S)] * 9
    assert connects.at[0] == 1000.0
    assert connects.at[-1] - connects.at[0] == config.RECOVER_WINDOW_S - config.RECOVER_RETRY_S
    assert clock[0] - 1000.0 == config.RECOVER_WINDOW_S
    assert "attempts=10" in caplog.text


def test_the_window_is_thirty_seconds_and_the_gap_three():
    assert config.RECOVER_WINDOW_S == 30
    assert config.RECOVER_RETRY_S == 3
    assert config.ORPHAN_DRAFT_S == 180


def test_an_outage_that_clears_inside_the_window_is_survived(monkeypatch, caplog):
    """Exactly Rehman's case: the network comes back a few seconds later."""
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, ws, connects = dropped_session(
        [None, None, None, doubles.FakeLiveApiSession()]
    )
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    with caplog.at_level(logging.INFO, logger="live_session"):
        assert asyncio.run(session._recover(LiveDropped("APIError"))) is True

    assert len(connects.handles) == 4
    assert "live reconnected session" in caplog.text
    assert "live recovery failed" not in caplog.text
    # The guest was never shown an error, and the socket is still open.
    assert events(ws, "error") == []
    assert ws.closed is False


def test_every_attempt_is_logged_with_its_number_and_result(monkeypatch, caplog):
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, _ws, connects = dropped_session([None, doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session._recover(LiveDropped("APIError")))

    lines = [line for line in caplog.text.splitlines() if "live reconnect attempt" in line]
    assert len(lines) == 2
    assert "n=1 resumed=true result=RuntimeError" in lines[0]
    assert "n=2 resumed=true result=ok" in lines[1]


def test_the_handle_goes_on_every_attempt(monkeypatch):
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, _ws, connects = dropped_session(
        [None, None, doubles.FakeLiveApiSession()]
    )
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    asyncio.run(session._recover(LiveDropped("APIError")))

    assert connects.handles == ["handle-1", "handle-1", "handle-1"]


def test_a_network_failure_never_throws_the_handle_away(monkeypatch):
    """Only the server's own refusal says anything about the handle."""
    assert live_session.handle_rejected(OSError("getaddrinfo failed")) is False
    assert live_session.handle_rejected(asyncio.TimeoutError()) is False
    assert live_session.handle_rejected(RuntimeError("timed out")) is False


def test_the_server_refusing_the_handle_is_recognised():
    from google.genai import errors

    def api_error(code):
        try:
            errors.APIError.raise_error(code, {"code": code, "message": "no"}, None)
        except Exception as exc:
            return exc
        raise AssertionError

    assert live_session.handle_rejected(api_error(400)) is True
    assert live_session.handle_rejected(api_error(404)) is True
    # A websocket close code is a drop, not a refused handle.
    assert live_session.handle_rejected(api_error(1011)) is False


# ----------------- 2k item 2: exactly one outcome line for every drop


OUTCOMES = ("live reconnected session", "live recovery failed session")


def outcome_lines(caplog):
    return [
        line
        for line in caplog.text.splitlines()
        if any(outcome in line for outcome in OUTCOMES)
    ]


@pytest.mark.parametrize(
    "results, expected",
    [
        ([doubles.FakeLiveApiSession()], "live reconnected session"),
        ([None, doubles.FakeLiveApiSession()], "live reconnected session"),
        ([], "live recovery failed session"),
    ],
    ids=["straight-away", "second-attempt", "never"],
)
def test_every_drop_ends_in_exactly_one_outcome_line(
    monkeypatch, caplog, results, expected
):
    """16 section 2k item 2: "A test enforces it."

    Neither of the two Wi-Fi drops wrote one: 03db21d2 ran out of attempts with
    no line at all, and ced7bcbf never reached the loop.
    """
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    monkeypatch.setattr(config, "RECOVER_WINDOW_S", 0.05)
    session, _ws, connects = dropped_session(results)
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session._recover(LiveDropped("APIError")))

    lines = outcome_lines(caplog)
    assert len(lines) == 1
    assert expected in lines[0]
    # And the drop itself is on the record exactly once too.
    assert caplog.text.count("live dropped session") == 1


def test_an_uplink_send_on_a_dying_connection_does_not_end_the_session(caplog):
    """Session ced7bcbf, 19 ms after RECOVERING and with no attempt made.

    The page streams audio; a send already in flight when the connection died
    raised the close error at the uplink, run() took the failure path, and the
    downlink was cancelled before recovery could try anything.
    """
    session, ws = doubles.new_session()

    class Dying(doubles.FakeLiveApiSession):
        async def send_realtime_input(self, **kwargs):
            from websockets.exceptions import ConnectionClosedError

            raise ConnectionClosedError(None, None)

    session.session = Dying()
    ws.messages.append({"type": "websocket.receive", "bytes": b"a frame mid-drop"})

    with caplog.at_level(logging.INFO, logger="live_session"):
        # No exception escapes: the uplink runs on to the disconnect.
        asyncio.run(session._uplink())

    assert "browser input dropped on a dying connection" in caplog.text


# --------------------------------- 2k item 3: the reconnecting messages


def test_reconnecting_is_true_then_false_on_success(monkeypatch):
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    session, ws, connects = dropped_session([doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    asyncio.run(session._recover(LiveDropped("APIError")))

    assert [sent["active"] for sent in events(ws, "reconnecting")] == [True, False]
    doubles.validate(ws)


def test_reconnecting_is_true_then_false_when_it_gives_up(monkeypatch):
    """"either way" -- a page left on "Reconnecting…" for ever is worse."""
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    monkeypatch.setattr(config, "RECOVER_WINDOW_S", 0.05)
    session, ws, connects = dropped_session([])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    asyncio.run(session._recover(LiveDropped("APIError")))

    assert [sent["active"] for sent in events(ws, "reconnecting")] == [True, False]


def test_the_reconnecting_event_is_allowed_on_the_audio_socket():
    assert "reconnecting" in live_session.AUDIO_SOCKET_EVENTS
    import schemas

    schemas.ReconnectingEvent.model_validate(
        {
            "type": "reconnecting",
            "active": True,
            "event_id": 1,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "session_id": "a1b2c3d4",
        }
    )


# ------------------------------------- 2k item 7: identity, exactly as written


IDENTITY_TOPICS = ("about_the_host", "team", "how_it_works", "project")

EXACT = {
    "about_the_host": (
        "I'm THE HOST, the AI host of Bite & Pour. I'm not a chatbot that waits for "
        "messages: I notice guests arriving, listen, understand what they need, and act on "
        "it. I take real orders, track them, and announce them when they're ready, while "
        "our team oversees everything. I work on one simple loop: see, understand, act."
    ),
    "team": (
        "I was designed and built by three BS Computer Science students at GCUF Samundri "
        "Campus, supervised by Ma'am Marva. Rehman Ayoub is the project lead: he designed "
        "my agent architecture, my backend, and how I combine vision, speech and reasoning. "
        "Saad Saleem built my business logic: order management, system integration and the "
        "stall's operational workflow. Umair Saddiqui built the operator dashboard and the "
        "public display, and led system testing."
    ),
    "project": (
        "The project is called THE HOST: A Real-Time Multimodal Agentic AI Host for "
        "Intelligent Customer Interaction and Order Management. It comes from the "
        "Department of Computer Science, Government College University Faisalabad, "
        "Samundri Campus, and runs here at the Bite & Pour stall at the GCUF Business "
        "Gala. Our tagline is: See. Understand. Act."
    ),
}


def test_the_identity_topics_are_served_with_the_exact_text(ctx):
    for topic, wanted in EXACT.items():
        result = tools.get_business_info(topic)
        assert result["found"] is True, topic
        answers = {row["topic"]: row["answer"] for row in result["answers"]}
        assert answers[topic] == wanted, topic


def test_how_it_works_credits_the_team_and_names_gemini(ctx):
    answer = tools.get_business_info("how_it_works")["answers"][0]["answer"]
    assert "Google's Gemini model gives me language and voice" in answer
    assert "was built by our team" in answer
    assert "One AI agent, real-world actions, two synchronized interfaces." in answer


def test_the_topics_reach_a_database_that_already_had_the_old_two(host_data):
    """The live failure this nearly shipped with.

    Seeding only an empty table meant the booth laptop's existing database never
    got the identity topics: get_business_info returned found=False and THE HOST
    answered "powered by Google's Gemini model" -- 2k item 1(d) all over again.
    """
    with host_data.closing(host_data._connect()) as conn:
        conn.execute("DELETE FROM business_info WHERE topic NOT IN ('hours', 'stall')")
        conn.commit()
        assert conn.execute("SELECT COUNT(*) FROM business_info").fetchone()[0] == 2

    host_data.init_db()

    listed = {row["topic"] for row in host_data.get_business_info()}
    for topic in IDENTITY_TOPICS:
        assert topic in listed, topic


def test_every_identity_topic_exists(ctx):
    listed = {row["topic"] for row in tools.get_business_info()["answers"]}
    for topic in IDENTITY_TOPICS:
        assert topic in listed
    # The older two are still there.
    assert {"hours", "stall"} <= listed


def test_the_prompt_carries_the_identity_rule():
    built = prompts.build_system_instruction(datetime.now())
    for topic in IDENTITY_TOPICS:
        assert topic in built
    assert "never say Google built you, and never deny using Gemini" in built
    assert "Vice Chancellor" in built


# --------------------------------- 2k items 5 and 6: language and personality


def test_the_prompt_carries_the_language_rule():
    built = prompts.build_system_instruction(datetime.now())
    assert "If the guest speaks Urdu or Punjabi, reply in Urdu" in built
    assert "never Hindi, never Punjabi, never Gurmukhi or Devanagari script" in built
    assert "A change of language is never a reason to call a team member" in built


def test_the_prompt_carries_the_personality_rule():
    built = prompts.build_system_instruction(datetime.now())
    assert "keep small talk to one or two short replies" in built
    assert "You are a host, not a counsellor" in built
    assert "do not offer emotional support" in built
    assert "Do not flatter the guest or comment on their personality" in built


def test_the_prompt_no_longer_offers_to_chat_about_anything():
    built = prompts.build_system_instruction(datetime.now())
    assert "chat about anything" not in built


# ------------------------------------------------ 2l item 2: the greeting


def test_the_greeting_is_one_short_varied_line():
    for instruction in (prompts.GREETING_PRESENCE, prompts.GREETING_BUTTON):
        assert "ONE warm, natural line" in instruction
        assert "twelve words" in instruction
        assert "Vary the wording" in instruction


def test_the_greeting_lists_nothing_and_never_mentions_the_camera():
    for instruction in (prompts.GREETING_PRESENCE, prompts.GREETING_BUTTON):
        assert "Do not list what you can do" in instruction
        assert "do not mention the camera" in instruction
        # The old greeting invited the guest to use the camera; this one must not.
        assert "show you something on the camera" not in instruction


def test_presence_and_the_button_share_the_greeting_and_voice_keeps_its_own():
    assert prompts.GREETING_PRESENCE == prompts.GREETING_BUTTON
    assert prompts.OPENING_INSTRUCTIONS["voice"] == prompts.GREETING_VOICE
    assert prompts.GREETING_VOICE != prompts.GREETING_PRESENCE


# ------------------------------- 2l item 3: a first name on every order


def test_build_order_stores_the_name(ctx):
    result = tools.build_order([{"name": "Chicken Burger"}], guest_name="Rehman")
    assert "error" not in result
    assert data.get_order(result["order_id"])["guest_name"] == "Rehman"


def test_the_name_is_trimmed_and_capped_at_thirty(ctx):
    result = tools.build_order([{"name": "Chicken Burger"}], guest_name="   Rehman   ")
    assert data.get_order(result["order_id"])["guest_name"] == "Rehman"
    # A second build_order in the same conversation replaces that draft and
    # keeps its name, so this one needs a draft of its own.
    tools.cancel_order(result["order_id"])

    long_name = "R" * 50
    second = tools.build_order([{"name": "Club Sandwich"}], guest_name=long_name)
    stored = data.get_order(second["order_id"])["guest_name"]
    assert stored == "R" * 30
    assert len(stored) == 30


def test_a_name_given_after_the_items_still_lands_on_the_order(ctx):
    """The real flow, and a live defect: THE HOST asks for the name AFTER the
    order is clear, so it arrives on a later build_order for the same draft.

    Updating only the items threw it away -- live order #19 was confirmed with
    no name on it after the guest had given one, so the announcement could not
    say it.
    """
    first = tools.build_order([{"name": "Chicken Burger"}])
    assert data.get_order(first["order_id"])["guest_name"] is None

    # Same draft, same items, now with the name the guest just gave.
    again = tools.build_order([{"name": "Chicken Burger"}], guest_name="Rehman")
    assert again["order_id"] == first["order_id"]
    assert data.get_order(first["order_id"])["guest_name"] == "Rehman"

    # And a later call with no name does not wipe it.
    tools.build_order(
        [{"name": "Chicken Burger"}, {"name": "Blue Lemonade"}]
    )
    assert data.get_order(first["order_id"])["guest_name"] == "Rehman"


def test_an_order_with_no_name_stays_without_one(ctx):
    result = tools.build_order([{"name": "Chicken Burger"}])
    assert data.get_order(result["order_id"])["guest_name"] is None


def test_the_prompt_asks_for_a_name_once_before_confirming():
    built = prompts.build_system_instruction(datetime.now())
    assert "Can I get a first name for the order?" in built
    assert "before the confirmation question" in built
    assert "place the order without one and do not ask again" in built


def test_the_announcement_uses_the_name_when_there_is_one():
    with_name = prompts.ANNOUNCE_TEMPLATE.format(order_id=5, name=" for Rehman")
    assert "Order number 5 for Rehman is ready!" in with_name
    without = prompts.ANNOUNCE_TEMPLATE.format(order_id=5, name="")
    assert "Order number 5 is ready!" in without
    assert "Rehman" not in without


# ------------------- 2l item 4: a draft survives a broken conversation


def draft_for(session_id="broken-1", name="Rehman"):
    return data.create_order_draft([BURGER], name, session_id)["order_id"]


def test_a_failure_end_keeps_the_draft(host_data):
    session, _ws = doubles.new_session()
    order_id = draft_for()
    session.ctx["pending_order_id"] = order_id

    # No session_end reason ever arrived: the conversation broke.
    asyncio.run(session.stop())

    row = host_data.get_order(order_id)
    assert row["status"] == "PENDING_CONFIRMATION"
    assert row["orphaned_at"] is not None


def test_a_normal_end_still_cancels_the_draft(host_data):
    for reason in ("user", "timeout", "cap", "absent"):
        session, _ws = doubles.new_session()
        order_id = draft_for(session_id=f"normal-{reason}")
        session.ctx["pending_order_id"] = order_id
        session.end_reason = reason

        asyncio.run(session.stop())

        row = host_data.get_order(order_id)
        assert row["status"] == "CANCELLED", reason
        assert row["cancel_reason"] == "session_ended", reason


def test_a_new_conversation_inside_the_window_is_offered_the_draft(host_data):
    order_id = draft_for()
    host_data.orphan_draft(order_id)

    session, _ws = doubles.new_session()
    opening = asyncio.run(session._opening_text())

    assert opening.startswith(prompts.GREETING_BUTTON)
    assert f"#{order_id}" in opening
    assert "2 x Chicken Burger" in opening
    assert "Rs. 1,300" in opening
    assert "for Rehman" in opening
    assert "ask whether they want to continue that order" in opening
    # The new conversation owns it, so every ordinary order rule applies.
    assert session.ctx["pending_order_id"] == order_id
    assert host_data.get_order(order_id)["session_id"] == session.ctx["session_id"]


def test_an_unclaimed_draft_is_cancelled_as_abandoned(host_data, caplog):
    order_id = draft_for()
    host_data.orphan_draft(order_id)
    # Wind the orphan back past the window.
    stale = (datetime.now() - timedelta(seconds=config.ORPHAN_DRAFT_S + 5)).isoformat(
        timespec="seconds"
    )
    with host_data.closing(host_data._connect()) as conn:
        conn.execute("UPDATE orders SET orphaned_at = ? WHERE id = ?", (stale, order_id))
        conn.commit()

    session, _ws = doubles.new_session()
    with caplog.at_level(logging.INFO, logger="data"):
        opening = asyncio.run(session._opening_text())

    row = host_data.get_order(order_id)
    assert row["status"] == "CANCELLED"
    assert row["cancel_reason"] == "abandoned"
    assert f"draft abandoned order {order_id}" in caplog.text
    # Nothing is offered, so the greeting is just the greeting.
    assert opening == prompts.GREETING_BUTTON
    assert session.ctx["pending_order_id"] is None


def test_the_abandoned_draft_publishes_its_activity_row(host_data):
    import event_bus

    order_id = draft_for()
    host_data.orphan_draft(order_id)
    stale = (datetime.now() - timedelta(seconds=config.ORPHAN_DRAFT_S + 5)).isoformat(
        timespec="seconds"
    )
    with host_data.closing(host_data._connect()) as conn:
        conn.execute("UPDATE orders SET orphaned_at = ? WHERE id = ?", (stale, order_id))
        conn.commit()
    event_bus.PUBLISHED.clear()

    host_data.abandon_orphan_drafts()

    labels = [
        event["label"]
        for event in event_bus.PUBLISHED
        if event["type"] == "agent_activity"
    ]
    assert f"Order #{order_id} cancelled" in labels


def test_only_the_most_recent_orphan_is_offered(host_data):
    first = draft_for(session_id="broken-1", name="Sara")
    second = draft_for(session_id="broken-2", name="Rehman")
    host_data.orphan_draft(first)
    host_data.orphan_draft(second)
    # Make the first one unambiguously older.
    older = (datetime.now() - timedelta(seconds=30)).isoformat(timespec="seconds")
    with host_data.closing(host_data._connect()) as conn:
        conn.execute("UPDATE orders SET orphaned_at = ? WHERE id = ?", (older, first))
        conn.commit()

    session, _ws = doubles.new_session()
    opening = asyncio.run(session._opening_text())

    assert f"#{second}" in opening
    assert f"#{first}" not in opening
    assert session.ctx["pending_order_id"] == second


def test_a_claimed_draft_is_not_offered_to_the_next_conversation_too(host_data):
    order_id = draft_for()
    host_data.orphan_draft(order_id)

    first, _ws = doubles.new_session()
    assert f"#{order_id}" in asyncio.run(first._opening_text())

    second, _ws2 = doubles.new_session()
    assert asyncio.run(second._opening_text()) == prompts.GREETING_BUTTON


def test_the_voice_trigger_also_offers_the_draft(host_data):
    order_id = draft_for()
    host_data.orphan_draft(order_id)

    session, _ws = doubles.new_session(trigger="voice")
    opening = asyncio.run(session._opening_text())

    assert opening.startswith(prompts.GREETING_VOICE)
    assert f"#{order_id}" in opening


# ------------------------- 2l item 5: order questions from the database


def test_get_order_status_by_number_covers_every_status(ctx, host_data):
    order_id = tools.build_order([{"name": "Chicken Burger"}])["order_id"]

    waiting = tools.get_order_status(order_id)["orders"][0]
    assert waiting["status"] == "PENDING_CONFIRMATION"
    assert waiting["status_text"] == "waiting for your confirmation"

    tools.confirm_order(order_id)
    for status, text in (
        ("PREPARING", "being prepared"),
        ("READY", "ready to collect"),
        ("COLLECTED", "collected"),
    ):
        host_data.update_order_status(order_id, status)
        found = tools.get_order_status(order_id)["orders"][0]
        assert found["status"] == status
        assert found["status_text"] == text


def test_get_order_status_by_name_finds_todays_orders(ctx, host_data):
    first = tools.build_order([{"name": "Chicken Burger"}], guest_name="Rehman")["order_id"]
    tools.confirm_order(first)
    second = tools.build_order([{"name": "Blue Lemonade"}], guest_name="Rehman")["order_id"]

    result = tools.get_order_status(guest_name="Rehman")

    assert result["found"] is True
    ids = [order["order_id"] for order in result["orders"]]
    assert sorted(ids) == sorted([first, second])
    # Both statuses, including the one still waiting.
    texts_by_id = {order["order_id"]: order["status_text"] for order in result["orders"]}
    assert texts_by_id[first] == "confirmed and queued"
    assert texts_by_id[second] == "waiting for your confirmation"


def test_get_order_status_by_name_is_case_and_space_insensitive(ctx):
    order_id = tools.build_order([{"name": "Chicken Burger"}], guest_name="Rehman")["order_id"]
    found = tools.get_order_status(guest_name="  rehman ")["orders"]
    assert [order["order_id"] for order in found] == [order_id]


def test_get_order_status_by_an_unknown_name_finds_nothing(ctx):
    tools.build_order([{"name": "Chicken Burger"}], guest_name="Rehman")
    assert tools.get_order_status(guest_name="Nobody") == {
        "source": "order",
        "found": False,
        "orders": [],
    }


def test_the_prompt_sends_every_order_question_to_the_tool():
    built = prompts.build_system_instruction(datetime.now())
    assert (
        "For any question about an order -- its status, whether it was placed, or what is "
        "in it -- call get_order_status and answer from the result, never from memory."
    ) in built


# ------------------------------------ 2k item 4: the draft after a reconnect


def test_the_apology_carries_the_draft_read_from_the_database(monkeypatch, host_data):
    monkeypatch.setattr(config, "RECOVER_RETRY_S", 0)
    order_id = draft_for(session_id="a1b2c3d4", name="Rehman")
    session, _ws, connects = dropped_session([doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())
    session.ctx["pending_order_id"] = order_id

    asyncio.run(session._recover(LiveDropped("APIError")))

    sent = texts(session)
    assert len(sent) == 1
    assert sent[0].startswith(prompts.RECONNECT_PROMPT)
    assert f"#{order_id}" in sent[0]
    assert "2 x Chicken Burger" in sent[0]
    assert "Rs. 1,300" in sent[0]
    assert "for Rehman" in sent[0]
    assert "still waiting for confirmation" in sent[0]
