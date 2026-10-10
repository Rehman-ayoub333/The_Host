"""Phase 5b: voice activity from the voice page, the deferral it adds and the
grace check (16 section 2f items 3, 4 and 5).

The booth problem these cover: the backend learns the guest is talking only when
Gemini returns an input-transcription fragment, a second or more after the first
syllable, so an announcement in that window talks over them.
"""

import asyncio
import json
import logging

import pytest

import config
import doubles
import schemas


ANNOUNCEMENT_27 = (
    "An order just became ready: order #27 for Ahmed. "
    "Let the guests know, briefly and naturally, even if it is not their order."
)


def listening():
    """A session that has greeted, with no turn in flight: a real gap."""
    session, ws = doubles.new_session()
    asyncio.run(session._send_state("LISTENING"))
    session.greeted = True
    return session, ws


def feed(session, ws, payload):
    """Hand the uplink one browser message and let it run to the disconnect."""
    ws.messages.append({"type": "websocket.receive", "text": json.dumps(payload)})
    asyncio.run(session._uplink())


def feed_voice(session, ws, active):
    feed(session, ws, {"type": "voice_activity", "active": active})


def no_wait(monkeypatch, on_wait=None):
    """Mock the clock: the 0.8 s grace must not cost the suite 0.8 s.

    `on_wait` is what happens at the booth during the wait -- the guest starting
    to speak, the model starting to answer -- so the re-check has something to
    find.
    """
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)
        if on_wait is not None:
            on_wait()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


# --------------------------------------------- item 3: the message and the flag


def test_the_message_model_takes_only_the_flag():
    valid = schemas.VoiceActivityMessage.model_validate(
        {"type": "voice_activity", "active": True}
    )
    print("validated:", valid.model_dump())
    assert valid.active is True
    for bad in (
        {"type": "voice_activity"},
        {"type": "voice_activity", "active": "maybe"},
        {"type": "voice_activity", "active": None},
        {"type": "voice_frame", "active": True},
    ):
        with pytest.raises(Exception) as caught:
            schemas.VoiceActivityMessage.model_validate(bad)
        print(f"rejected {bad}: {type(caught.value).__name__}")


def test_a_voice_activity_message_sets_the_flag_and_is_logged(caplog):
    session, ws = listening()
    session_id = session.ctx["session_id"]
    print("guest_voice_active at the start:", session.guest_voice_active)
    assert session.guest_voice_active is False

    with caplog.at_level(logging.INFO, logger="live_session"):
        feed_voice(session, ws, True)
        print("after active:true ->", session.guest_voice_active)
        assert session.guest_voice_active is True
        feed_voice(session, ws, False)
        print("after active:false ->", session.guest_voice_active)
        assert session.guest_voice_active is False

    messages = [record.getMessage() for record in caplog.records]
    for line in messages:
        print("log:", line)
    assert f"voice_activity session {session_id} active=true" in messages
    assert f"voice_activity session {session_id} active=false" in messages
    doubles.validate(ws)


def test_an_invalid_voice_activity_message_is_ignored(caplog):
    session, ws = listening()
    session.guest_voice_active = True

    with caplog.at_level(logging.WARNING, logger="live_session"):
        for bad in (
            {"type": "voice_activity"},
            {"type": "voice_activity", "active": "maybe"},
            {"type": "voice_activity", "active": None},
            {"type": "voice_activity", "active": 0.5},
        ):
            feed(session, ws, bad)

    messages = [record.getMessage() for record in caplog.records]
    print("warnings:", messages)
    print("guest_voice_active unchanged:", session.guest_voice_active)
    assert messages == ["ignored invalid voice_activity message"] * 4
    # An ignored message changes nothing and says nothing to Gemini.
    assert session.guest_voice_active is True
    assert session.session.inputs == []
    assert session.pending_announcements == []


def test_stop_resets_guest_voice_active():
    session, ws = listening()
    feed_voice(session, ws, True)
    assert session.guest_voice_active is True

    asyncio.run(session.stop())

    print("guest_voice_active after stop:", session.guest_voice_active)
    assert session.guest_voice_active is False
    assert doubles.states(ws)[-1] == "IDLE"


# -------------------------------------------------- item 4: the extra deferral


def test_an_announcement_while_the_guest_speaks_is_deferred_then_leaves_on_silence(caplog):
    session, ws = listening()
    session_id = session.ctx["session_id"]
    feed_voice(session, ws, True)

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("Gemini inputs while the guest speaks:", session.session.inputs)
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert session.session.inputs == []
    assert session.announcing is False
    assert [order["id"] for order in session.pending_announcements] == [27]
    messages = [record.getMessage() for record in caplog.records]
    assert f"announce deferred session {session_id} order 27" in messages

    # The guest stops. No turn is in progress, so this is the gap.
    feed_voice(session, ws, False)

    print("Gemini inputs after the silence:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.pending_announcements == []
    assert session.announcing is True

    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x01"))))
    print("states:", doubles.states(ws))
    assert doubles.states(ws)[-1] == "ANNOUNCING"
    doubles.validate(ws)


def test_silence_does_not_interrupt_a_turn_that_is_running(monkeypatch):
    """A falling mic level means the guest stopped, not that THE HOST did."""
    session, ws = listening()
    no_wait(monkeypatch)
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]

    # A second announcement arrives while the announcing turn is speaking.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert session.turn_in_progress is True
    asyncio.run(session.announce({"id": 28, "guest_name": None}))
    assert [order["id"] for order in session.pending_announcements] == [28]

    feed_voice(session, ws, True)
    feed_voice(session, ws, False)

    print("Gemini inputs:", session.session.inputs)
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert [order["id"] for order in session.pending_announcements] == [28]


def test_a_pending_announcement_is_not_sent_at_the_end_of_turn_while_the_guest_speaks():
    """2f item 4: the end of THE HOST's own turn is not a gap if the guest has
    already started talking into it."""
    session, ws = listening()

    # THE HOST is speaking and the operator marks an order READY.
    asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"\x00"))))
    assert session.turn_in_progress is True
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))
    assert [order["id"] for order in session.pending_announcements] == [27]

    # The guest talks over the end of that turn.
    feed_voice(session, ws, True)
    asyncio.run(session._handle_message(doubles.message(doubles.content(turn_complete=True))))

    print("Gemini inputs at the end of the turn:", session.session.inputs)
    print("pending:", [order["id"] for order in session.pending_announcements])
    assert session.session.inputs == []
    assert session.announcing is False
    assert [order["id"] for order in session.pending_announcements] == [27]
    assert doubles.states(ws) == ["LISTENING", "SPEAKING", "LISTENING"]

    # It leaves as soon as the guest is quiet again.
    feed_voice(session, ws, False)
    print("Gemini inputs after the silence:", session.session.inputs)
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.pending_announcements == []
    doubles.validate(ws)


# ------------------------------------------------------ item 5: the grace check


def test_an_idle_session_still_announces_after_the_grace(monkeypatch):
    session, ws = listening()
    waits = no_wait(monkeypatch)

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("grace waits:", waits)
    print("Gemini inputs:", session.session.inputs)
    assert waits == [config.ANNOUNCE_GRACE_S]
    assert config.ANNOUNCE_GRACE_S == 0.8
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.pending_announcements == []
    assert session.announcing is True


def test_the_guest_starting_to_speak_during_the_grace_defers_it(monkeypatch, caplog):
    """The 10 Oct booth report: the announcement talked over a guest who had only
    just started. The `voice_activity` message arrives inside the grace window.
    """
    session, ws = listening()
    session_id = session.ctx["session_id"]

    def the_guest_starts_speaking():
        session.guest_voice_active = True

    waits = no_wait(monkeypatch, on_wait=the_guest_starts_speaking)

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    messages = [record.getMessage() for record in caplog.records]
    print("grace waits:", waits)
    print("Gemini inputs:", session.session.inputs)
    print("log lines:", messages)
    assert waits == [config.ANNOUNCE_GRACE_S]
    assert session.session.inputs == []
    assert session.announcing is False
    assert [order["id"] for order in session.pending_announcements] == [27]
    assert f"announce deferred session {session_id} order 27" in messages
    assert "Ahmed" not in "\n".join(messages)


def test_a_turn_starting_during_the_grace_defers_it_as_well(monkeypatch):
    """The other half of the window: Gemini begins answering mid-grace."""
    session, ws = listening()

    def the_model_starts_answering():
        session.turn_in_progress = True

    waits = no_wait(monkeypatch, on_wait=the_model_starts_answering)
    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("grace waits:", waits)
    print("Gemini inputs:", session.session.inputs)
    assert waits == [config.ANNOUNCE_GRACE_S]
    assert session.session.inputs == []
    assert [order["id"] for order in session.pending_announcements] == [27]


def test_a_blocked_announcement_never_waits_at_all(monkeypatch):
    """A deferral that is already certain must not delay the operator's call."""
    session, ws = listening()
    session.guest_voice_active = True
    waits = no_wait(monkeypatch)

    asyncio.run(session.announce({"id": 27, "guest_name": "Ahmed"}))

    print("grace waits:", waits)
    assert waits == []
    assert [order["id"] for order in session.pending_announcements] == [27]
