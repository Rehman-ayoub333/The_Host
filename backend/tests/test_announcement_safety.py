"""Phase 5c: nothing a latched voice flag can do may lose an announcement
(16 section 2g item 4).

The booth case these come from: in session 334855a7 room noise held the page's
voice flag true for 45 seconds, order #2's announcement was deferred, and it was
then thrown away in silence when the session ended.
"""

import asyncio
import logging

import pytest

import config
import doubles
import event_bus
import live_session
import prompts


ORDER_27 = {"id": 27, "guest_name": "Ahmed"}
ORDER_28 = {"id": 28, "guest_name": None}
ANNOUNCEMENT_27 = prompts.ANNOUNCE_TEMPLATE.format(order_number=27, name=" for Ahmed")


class Clock:
    """A monotonic clock the test winds forward, so 20 s costs nothing."""

    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(live_session, "_now", fake)
    # The grace is 2f item 5's business and is tested in test_voice_activity.py.
    monkeypatch.setattr(config, "ANNOUNCE_GRACE_S", 0)
    return fake


def of_type(event_type):
    return [event for event in event_bus.PUBLISHED if event["type"] == event_type]


# ------------------------------------------------------------- the stale flag


def test_a_latched_flag_goes_stale_and_the_announcement_leaves(clock, caplog):
    """Latched true for VOICE_ACTIVE_STALE_S with no transcript behind it."""

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        # Room noise, not a guest: the flag latches and no transcription follows.
        session.guest_voice_active = True
        session.voice_active_since = clock()
        print("believed at 0 s:", session.voice_active_effective())
        assert session.voice_active_effective() is True

        await session.announce(ORDER_27)
        print("pending:", [order["id"] for order in session.pending_announcements])
        assert [order["id"] for order in session.pending_announcements] == [27]
        assert session.session.inputs == []

        clock.advance(config.VOICE_ACTIVE_STALE_S + 1)
        print("believed at 11 s:", session.voice_active_effective())
        assert session.voice_active_effective() is False
        # Asked twice, logged once.
        assert session.voice_active_effective() is False

        # The ordinary exit works again now the flag is disbelieved.
        await session._end_of_turn()
        # 16 section 2v item 4: sent, but still pending until THE HOST has
        # finished saying it.
        assert [order["id"] for order in session.pending_announcements] == [27]
        await doubles.announcing_turn(session)
        return session, ws

    with caplog.at_level(logging.INFO, logger="live_session"):
        session, ws = asyncio.run(scenario())

    messages = [record.getMessage() for record in caplog.records]
    stale = [line for line in messages if "voice_activity stale" in line]
    for line in messages:
        print("log:", line)
    print("Gemini inputs:", session.session.inputs)
    assert stale == [
        f"voice_activity stale session {session.ctx['session_id']}, treated as inactive"
    ]
    assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
    assert session.pending_announcements == []
    assert session.announced == {27}
    assert session.guest_voice_active is True  # the flag itself is not rewritten


def test_a_fresh_transcript_keeps_the_flag_believed(clock):
    async def scenario():
        session, _ = doubles.new_session()
        session.greeted = True
        session.guest_voice_active = True
        session.voice_active_since = clock()

        clock.advance(config.VOICE_ACTIVE_STALE_S + 1)
        # Gemini proved the guest really is talking, 1 s ago.
        session.last_input_transcript_at = clock() - 1
        print("believed with a fresh transcript:", session.voice_active_effective())
        assert session.voice_active_effective() is True

        # The same transcript, now older than the window.
        clock.advance(config.VOICE_ACTIVE_STALE_S)
        print("believed with a stale transcript:", session.voice_active_effective())
        assert session.voice_active_effective() is False
        return session

    asyncio.run(scenario())


def test_an_input_transcription_fragment_records_its_arrival(clock):
    async def scenario():
        session, _ = doubles.new_session()
        session.greeted = True
        assert session.last_input_transcript_at is None
        await session._handle_message(
            doubles.message(doubles.content(visitor="can I get"))
        )
        print("last_input_transcript_at:", session.last_input_transcript_at)
        assert session.last_input_transcript_at == clock()
        return session

    asyncio.run(scenario())


# --------------------------------------------------------- the deferral cap


def test_the_cap_releases_an_announcement_after_twenty_seconds(clock, monkeypatch):
    """A latched flag with fresh transcripts never goes stale, so only the cap
    can release this one -- and never while a model turn is running."""
    monkeypatch.setattr(live_session, "ANNOUNCE_WATCH_INTERVAL_S", 0.01)

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        session.guest_voice_active = True
        session.voice_active_since = clock()
        session.last_input_transcript_at = clock()

        await session.announce(ORDER_27)
        assert [order["id"] for order in session.pending_announcements] == [27]
        print("watcher running:", session.announce_watcher is not None)
        assert session.announce_watcher is not None

        # 10 s in, still talking for real: the flag is believed, nothing is sent.
        clock.advance(10)
        session.last_input_transcript_at = clock()
        await asyncio.sleep(0.05)
        print("Gemini inputs at 10 s:", session.session.inputs)
        assert session.session.inputs == []

        # Past the cap, but Gemini is mid-turn: still nothing (2e item 1).
        clock.advance(11)
        session.last_input_transcript_at = clock()
        session.turn_in_progress = True
        await asyncio.sleep(0.05)
        print("Gemini inputs past the cap, mid-turn:", session.session.inputs)
        assert session.session.inputs == []
        assert [order["id"] for order in session.pending_announcements] == [27]

        # The turn ends. The cap now wins over the guest's noise.
        session.turn_in_progress = False
        await asyncio.sleep(0.05)
        print("Gemini inputs after the turn ended:", session.session.inputs)
        assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
        # 16 section 2v item 4: it leaves the list when THE HOST has said it.
        assert [order["id"] for order in session.pending_announcements] == [27]
        await doubles.announcing_turn(session)
        assert session.pending_announcements == []
        assert session.announced == {27}

        # The list is empty, so the watcher is finished.
        await asyncio.sleep(0.05)
        print("watcher after the list emptied:", session.announce_watcher)
        assert session.announce_watcher is None
        return session, ws

    session, ws = asyncio.run(scenario())
    # The announcing turn has been played out, so the flag it set is clear again
    # and ANNOUNCING was the state the turn was labelled with.
    assert session.announcing is False
    assert "ANNOUNCING" in doubles.states(ws)
    doubles.validate(ws)


def test_the_watcher_also_takes_an_ordinary_gap(clock, monkeypatch):
    """The cap is the backstop; a real gap still releases it at once."""
    monkeypatch.setattr(live_session, "ANNOUNCE_WATCH_INTERVAL_S", 0.01)

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        session.turn_in_progress = True

        await session.announce(ORDER_27)
        assert [order["id"] for order in session.pending_announcements] == [27]

        # No cap has passed, but the turn finishes and nothing else is in the way.
        session.turn_in_progress = False
        await asyncio.sleep(0.05)
        print("Gemini inputs:", session.session.inputs)
        assert session.session.inputs == [{"text": ANNOUNCEMENT_27}]
        # 16 section 2v item 4: still pending while THE HOST says it, gone after.
        assert [order["id"] for order in session.pending_announcements] == [27]
        await doubles.announcing_turn(session)
        assert session.pending_announcements == []
        # The list emptied at the end of the announcing turn rather than inside
        # the watcher's own step, so it ends on its next look.
        await asyncio.sleep(0.05)
        assert session.announce_watcher is None
        return session

    asyncio.run(scenario())


def test_the_watcher_stops_when_the_session_stops(clock, monkeypatch):
    monkeypatch.setattr(live_session, "ANNOUNCE_WATCH_INTERVAL_S", 0.01)

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        session.guest_voice_active = True
        session.voice_active_since = clock()
        session.last_input_transcript_at = clock()

        await session.announce(ORDER_27)
        task = session.announce_watcher
        assert task is not None

        await session.stop()
        await asyncio.sleep(0.02)
        print("watcher attribute after stop:", session.announce_watcher)
        print("task done after stop:", task.done())
        assert session.announce_watcher is None
        assert task.done()
        return session, ws

    session, ws = asyncio.run(scenario())
    assert doubles.states(ws)[-1] == "IDLE"


# -------------------------------------------------- nothing is lost silently


def test_a_dropped_announcement_is_logged_and_handed_to_the_display(clock, caplog):
    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        session.turn_in_progress = True

        await session.announce(ORDER_27)
        await session.announce(ORDER_28)
        assert [order["id"] for order in session.pending_announcements] == [27, 28]

        event_bus.PUBLISHED.clear()
        await session.stop()
        return session, ws

    with caplog.at_level(logging.INFO, logger="live_session"):
        session, ws = asyncio.run(scenario())

    session_id = session.ctx["session_id"]
    messages = [record.getMessage() for record in caplog.records]
    dropped = [line for line in messages if "announce dropped" in line]
    ready = of_type("order_ready")
    for line in dropped:
        print("log:", line)
    print("order_ready republished:", ready)
    assert dropped == [
        f"announce dropped session {session_id} order 27, handed to display",
        f"announce dropped session {session_id} order 28, handed to display",
    ]
    assert [event["order_id"] for event in ready] == [27, 28]
    assert ready[0]["customer_name"] == "Ahmed"
    assert ready[1]["customer_name"] is None
    # The display is not part of any conversation, so it carries no session id.
    assert all(event["session_id"] is None for event in ready)
    assert session.pending_announcements == []
    assert session.pending_deferred_at == {}
    # Nothing was said: the order was never injected into Gemini.
    assert session.session.inputs == []
    assert "Ahmed" not in "\n".join(dropped)


def test_a_stop_with_nothing_pending_publishes_no_order_ready(clock):
    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        event_bus.PUBLISHED.clear()
        await session.stop()
        return session

    session = asyncio.run(scenario())
    print("order_ready events:", of_type("order_ready"))
    assert of_type("order_ready") == []


# ------------------------------------- 2v item 4: never handed over twice


def test_an_announced_order_is_not_handed_to_the_display_at_session_end(clock, caplog):
    """16 section 2v items 1 and 4.

    The 23 Oct case: the operator asked for order #27 again (`POST
    /api/operator/announce` bypasses the `announced` guard on purpose), the
    repeat was deferred because the guest was talking, and the session then
    ended with it still pending. Handing it to the display announced an order
    THE HOST had already announced -- and until 2v item 3 the display said it
    out loud in a voice that was not THE HOST's.
    """

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True

        # THE HOST announces #27 and finishes saying it.
        await session.announce(ORDER_27)
        await doubles.announcing_turn(session)
        assert session.pending_announcements == []
        assert session.announced == {27}

        # The operator asks for it again, and this time the guest is talking.
        session.guest_voice_active = True
        session.voice_active_since = clock()
        session.last_input_transcript_at = clock()
        await session.announce(ORDER_27)
        assert [order["id"] for order in session.pending_announcements] == [27]

        event_bus.PUBLISHED.clear()
        await session.stop()
        return session, ws

    with caplog.at_level(logging.INFO, logger="live_session"):
        session, ws = asyncio.run(scenario())

    session_id = session.ctx["session_id"]
    messages = [record.getMessage() for record in caplog.records]
    for line in messages:
        if "announce" in line:
            print("log:", line)
    print("order_ready republished:", of_type("order_ready"))
    # Nothing was handed over, and the log says why in so many words.
    assert [line for line in messages if "handed to display" in line] == []
    assert (
        f"announce not handed over session {session_id} order 27, already announced"
        in messages
    )
    assert of_type("order_ready") == []
    assert session.pending_announcements == []
    assert session.pending_deferred_at == {}


def test_an_order_that_was_never_spoken_is_handed_over_exactly_once(clock, caplog):
    """16 section 2v item 4: the other half. An order THE HOST never got to
    announce is still the display's to show, once and only once."""

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True
        # A turn is running, so both announcements are deferred and neither is
        # ever spoken.
        session.turn_in_progress = True

        await session.announce(ORDER_27)
        await session.announce(ORDER_28)
        # The operator asks for #27 again: it is already pending, so it is not
        # queued twice.
        await session.announce(ORDER_27)
        assert [order["id"] for order in session.pending_announcements] == [27, 28]
        assert session.announced == set()

        event_bus.PUBLISHED.clear()
        await session.stop()
        return session, ws

    with caplog.at_level(logging.INFO, logger="live_session"):
        session, ws = asyncio.run(scenario())

    session_id = session.ctx["session_id"]
    messages = [record.getMessage() for record in caplog.records]
    dropped = [line for line in messages if "handed to display" in line]
    ready = of_type("order_ready")
    for line in dropped:
        print("log:", line)
    print("order_ready republished:", ready)
    assert dropped == [
        f"announce dropped session {session_id} order 27, handed to display",
        f"announce dropped session {session_id} order 28, handed to display",
    ]
    # Exactly once each, not once per announce call.
    assert [event["order_id"] for event in ready] == [27, 28]
    assert session.session.inputs == []
    # The hand-over line never carries a guest's name (12 section 1).
    assert "Ahmed" not in "\n".join(dropped)


def test_an_interrupted_announcement_is_still_remembered_as_announced(clock, caplog):
    """THE HOST started saying it and the guest talked over it. It was said, so
    the display must not say it again at the end of the session."""

    async def scenario():
        session, ws = doubles.new_session()
        await session._send_state("LISTENING")
        session.greeted = True

        await session.announce(ORDER_27)
        assert session.announced == {27}
        # The announcing turn starts and is cut off by the guest.
        await session._handle_message(doubles.message(doubles.content(audio=b"\x00")))
        assert doubles.states(ws)[-1] == "ANNOUNCING"
        await session._handle_message(doubles.message(doubles.content(interrupted=True)))

        # The operator asks for it again and it is deferred behind a new turn.
        session.turn_in_progress = True
        await session.announce(ORDER_27)
        assert [order["id"] for order in session.pending_announcements] == [27]

        event_bus.PUBLISHED.clear()
        await session.stop()
        return session, ws

    with caplog.at_level(logging.INFO, logger="live_session"):
        session, ws = asyncio.run(scenario())

    print("order_ready republished:", of_type("order_ready"))
    assert of_type("order_ready") == []
    assert session.announced == {27}
