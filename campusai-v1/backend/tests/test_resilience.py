"""Phase 5e: connection resilience and speed (16 section 2j items 2 to 11).

The booth problems these cover, all three from the 5d live test: a guest's end
was only noticed after the Gemini connect had finished, so the next wake-up was
refused for six seconds (session e36a3f44); a mid-session drop and a silent
34-second stall both ended the conversation instead of recovering (sessions
d9386dcc and 2b4d1ebc); and every reply arrived about three seconds after the
guest stopped speaking.
"""

import asyncio
import json
import logging
from datetime import datetime

import pytest

import config
import doubles
import health
import live_session
import main
import prompts
from live_session import LiveDropped, LiveSession, PageEnded


BURGER = {"name": "Chicken Burger", "quantity": 2}


def texts(session):
    """Every text instruction the backend sent Gemini, in order."""
    return [
        sent["text"]
        for sent in session.session.inputs
        if isinstance(sent.get("text"), str)
    ]


def end_message(reason="user"):
    return {"type": "websocket.receive", "text": json.dumps(
        {"type": "session_end", "reason": reason}
    )}


# ------------------------------------- 2j item 7: the connect config it asks for


def test_the_connect_config_enables_session_resumption():
    built = live_session.build_live_config(datetime.now())
    # A fresh connect sends no handle: that is what asks the server to start
    # issuing them, which is what makes a later resume possible at all.
    assert built.session_resumption is not None
    assert built.session_resumption.handle is None


def test_the_connect_config_carries_the_handle_when_there_is_one():
    built = live_session.build_live_config(datetime.now(), False, "handle-7")
    assert built.session_resumption.handle == "handle-7"


def test_the_connect_config_shortens_the_silence_before_a_reply():
    built = live_session.build_live_config(datetime.now())
    detection = built.realtime_input_config.automatic_activity_detection
    assert config.SILENCE_DURATION_MS == 500
    assert detection.silence_duration_ms == 500
    # 2j item 6: and the start sensitivity is gone, not merely defaulted.
    assert detection.start_of_speech_sensitivity is None


def test_the_stall_and_goaway_limits_are_the_ones_the_spec_sets():
    assert config.STALL_S == 8
    assert config.GOAWAY_TURN_GRACE_S == 5


# ----------------------------- 2j item 2: the page's end during the connect


class _HangingConnect:
    """A connect that never finishes, like the real one for 6.4 seconds.

    `hook()` hands back a plain function, so monkeypatch puts it on the class as
    a method and the real call signature is the one being exercised.
    """

    def __init__(self):
        self.started = 0
        self.cancelled = 0

    def hook(self):
        async def _open(_session, _client, _proactive=False, _handle=None):
            self.started += 1
            try:
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            return doubles.FakeLiveApiSession()

        return _open


def test_a_session_end_during_the_connect_cancels_it(monkeypatch, caplog):
    connect = _HangingConnect()
    monkeypatch.setattr(LiveSession, "_open", connect.hook())
    session, ws = doubles.new_session([end_message("user")])
    session.session = None

    with caplog.at_level(logging.INFO, logger="live_session"):
        with pytest.raises(PageEnded):
            asyncio.run(session._start())

    assert connect.started == 1
    assert connect.cancelled == 1
    assert "session cancelled during connect session" in caplog.text
    # 2g item 3's line still goes out: the reason the guest gave is on the record.
    assert "session end requested session" in caplog.text
    assert "reason=user" in caplog.text


def test_a_closed_socket_during_the_connect_cancels_it(monkeypatch, caplog):
    connect = _HangingConnect()
    monkeypatch.setattr(LiveSession, "_open", connect.hook())
    # An empty FakeWebSocket returns a disconnect, which is what a page that has
    # gone looks like from here.
    session, _ws = doubles.new_session()
    session.session = None

    with caplog.at_level(logging.INFO, logger="live_session"):
        with pytest.raises(PageEnded):
            asyncio.run(session._start())

    assert connect.cancelled == 1
    assert "session cancelled during connect session" in caplog.text


def test_the_cancelled_connect_is_not_counted_as_a_failure(monkeypatch):
    monkeypatch.setattr(LiveSession, "_open", _HangingConnect().hook())
    session, _ws = doubles.new_session()
    session.session = None

    with pytest.raises(PageEnded):
        asyncio.run(session._start())

    # Nothing is wrong with the AI service: the guest simply left.
    assert health.mode() == "ONLINE"


def test_cancelling_during_the_connect_releases_the_guard(monkeypatch, caplog):
    """The 5d failure itself: a wake-up in that gap was refused for six seconds."""
    monkeypatch.setattr(LiveSession, "_open", _HangingConnect().hook())
    ws = doubles.FakeWebSocket([end_message("absent")])

    async def go():
        await main.websocket_session(ws)

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(go())

    # The guard is free for the next guest, and IDLE went out.
    assert main.ACTIVE is None
    assert doubles.states(ws)[-1] == "IDLE"
    assert ws.closed is True
    assert "session cancelled during connect session" in caplog.text
    # No error was shown: there is nobody there to show one to.
    assert [sent for sent in ws.sent if sent["type"] == "error"] == []


def test_what_the_page_sent_during_the_connect_is_not_lost(monkeypatch):
    """A message that is not an ending waits for the uplink, in order."""
    session, ws = doubles.new_session()
    ws.messages.extend([
        {"type": "websocket.receive", "text": json.dumps({"type": "voice_activity", "active": True})},
        {"type": "websocket.receive", "bytes": b"audio-from-the-connect-window"},
        end_message("user"),
    ])

    async def go():
        await session._watch_page_end()
        # Everything before the ending is kept, and the ending is not.
        assert len(session.prebuffer) == 2
        assert session.page_ended is True
        await session._uplink()

    asyncio.run(go())

    assert session.guest_voice_active is True
    assert session.session.inputs[0]["audio"].data == b"audio-from-the-connect-window"


def test_the_uplink_stops_at_a_page_that_has_already_gone():
    session, ws = doubles.new_session()
    session.page_ended = True

    class Exploding(doubles.FakeWebSocket):
        async def receive(self):
            raise RuntimeError("Cannot call receive once a disconnect has been received")

    session.ws = Exploding()
    # It returns rather than reading a socket that is already finished with.
    asyncio.run(session._uplink())


# --------------------------------------- 2j item 4: resume with a handle


class _Reconnecting:
    """Scripted connects: each result in turn, `None` meaning this one fails."""

    def __init__(self, results):
        self.results = list(results)
        self.handles = []
        self.modes = []

    def hook(self):
        async def _connect(_session, _client, handle=None):
            self.handles.append(handle)
            self.modes.append(health.mode())
            result = self.results.pop(0) if self.results else None
            if result is None:
                raise RuntimeError("the connection could not be rebuilt")
            return result

        return _connect


def recovering_session(results, *, handle="handle-1", messages=()):
    session, ws = doubles.new_session(messages)
    session.resume_handle = handle
    session.greeted = True
    connects = _Reconnecting(results)
    return session, ws, connects


def test_a_drop_resumes_with_the_handle(monkeypatch, caplog):
    fresh = doubles.FakeLiveApiSession()
    session, ws, connects = recovering_session([fresh])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    with caplog.at_level(logging.INFO, logger="live_session"):
        recovered = asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    assert recovered is True
    assert connects.handles == ["handle-1"]
    assert session.session is fresh
    assert "live dropped session" in caplog.text
    assert "ConnectionClosedError" in caplog.text
    assert "live reconnected session" in caplog.text
    assert "resumed=true" in caplog.text
    # The page is told to flush what it was playing, and is never closed.
    assert any(sent["type"] == "interrupted" for sent in ws.sent)
    assert ws.closed is False
    # One text turn: the apology, and nothing else.
    assert texts(session) == [prompts.RECONNECT_PROMPT]


def test_the_handle_is_kept_from_every_resumable_update():
    session, _ws = doubles.new_session()

    async def go():
        await session._handle_message(
            doubles.message(resumption=doubles.resumption("handle-A"))
        )
        await session._handle_message(
            doubles.message(resumption=doubles.resumption("handle-B"))
        )
        # Not resumable: it is not a handle we could come back with.
        await session._handle_message(
            doubles.message(resumption=doubles.resumption("handle-C", resumable=False))
        )

    asyncio.run(go())
    assert session.resume_handle == "handle-B"


def test_the_session_keeps_its_context_across_a_reconnect(monkeypatch):
    session, _ws, connects = recovering_session([doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())
    session.ctx["visitor_name"] = "Sara"
    session.pending_announcements.append({"id": 4, "guest_name": "Sara"})

    asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    # It is the same conversation, so it is the same context.
    assert session.ctx["visitor_name"] == "Sara"
    assert [order["id"] for order in session.pending_announcements] == [4]


# ------------------- 2j item 4: the fall-back connect, carrying the draft


def test_the_fallback_connect_drops_the_handle_and_carries_the_draft(
    monkeypatch, caplog, host_data
):
    order_id = host_data.create_order_draft(
        [BURGER], "Sara", "a1b2c3d4"
    )["order_id"]
    session, _ws, connects = recovering_session([None, doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())
    session.ctx["pending_order_id"] = order_id

    with caplog.at_level(logging.INFO, logger="live_session"):
        recovered = asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    assert recovered is True
    # With the handle first, then without it.
    assert connects.handles == ["handle-1", None]
    assert "resumed=false" in caplog.text
    # The new connection has none of the conversation, so the draft comes with
    # the apology: its number and what is in it.
    sent = texts(session)
    assert len(sent) == 1
    assert sent[0].startswith(prompts.RECONNECT_PROMPT)
    assert f"#{order_id}" in sent[0]
    assert "2 x Chicken Burger" in sent[0]


def test_the_fallback_connect_says_nothing_about_a_draft_that_is_not_there(monkeypatch):
    session, _ws, connects = recovering_session([None, doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    assert texts(session) == [prompts.RECONNECT_PROMPT]


def test_a_resumed_connection_does_not_repeat_the_draft(monkeypatch, host_data):
    """It has the conversation behind it, so handing the draft back would confuse."""
    order_id = host_data.create_order_draft(
        [BURGER], "Sara", "a1b2c3d4"
    )["order_id"]
    session, _ws, connects = recovering_session([doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())
    session.ctx["pending_order_id"] = order_id

    asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    assert texts(session) == [prompts.RECONNECT_PROMPT]


def test_a_confirmed_order_is_not_handed_back_as_a_draft(monkeypatch, host_data):
    order_id = host_data.create_order_draft(
        [BURGER], "Sara", "a1b2c3d4"
    )["order_id"]
    host_data.update_order_status(order_id, "CONFIRMED", "test")
    session, _ws, connects = recovering_session([None, doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())
    session.ctx["pending_order_id"] = order_id

    asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    assert texts(session) == [prompts.RECONNECT_PROMPT]


# ------------------------- 2j item 4: both attempts failing, and health


def test_both_attempts_failing_falls_back_to_the_failure_path(monkeypatch):
    session, ws, connects = recovering_session([None, None])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    async def go():
        assert await session._recover(LiveDropped("ConnectionClosedError")) is False
        # The downlink re-raises, which is the existing failure path.
        await session._fail(LiveDropped("ConnectionClosedError"))

    asyncio.run(go())

    assert connects.handles == ["handle-1", None]
    assert doubles.states(ws)[-1] == "NEEDS_HELP"
    assert any(sent["type"] == "error" for sent in ws.sent)
    # 07 section 3: RECOVERING's other exit.
    assert health.mode() == "OFFLINE"


def test_health_shows_recovering_while_the_attempt_runs(monkeypatch):
    session, _ws, connects = recovering_session([doubles.FakeLiveApiSession()])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    asyncio.run(session._recover(LiveDropped("ConnectionClosedError")))

    # `modes` is what health said at the moment the attempt was made.
    assert connects.modes == ["RECOVERING"]
    assert health.mode() == "ONLINE"


def test_the_downlink_recovers_a_dropped_connection_and_carries_on(monkeypatch):
    """The whole of item 4, driven the way a real drop arrives: from the stream."""

    class FirstConnection(doubles.FakeLiveApiSession):
        async def receive(self):
            yield doubles.message(doubles.content(agent="Hello"))
            raise _closed_error()

    class SecondConnection(doubles.FakeLiveApiSession):
        async def receive(self):
            yield doubles.message(doubles.content(agent="Sorry about that"))

    second = SecondConnection()
    session, ws = doubles.new_session()
    session.session = FirstConnection()
    session.greeted = True
    session.resume_handle = "handle-1"
    # The second connection's stream ends as well, and by then there is nothing
    # left to rebuild with, so the conversation finally does end.
    connects = _Reconnecting([second])
    monkeypatch.setattr(LiveSession, "_connect", connects.hook())

    async def go():
        with pytest.raises(LiveDropped):
            await session._downlink()

    asyncio.run(go())

    # It did not stop at the first drop: the apology went out over the rebuilt
    # connection, and that connection's own message was handled.
    assert connects.handles[0] == "handle-1"
    assert [sent["text"] for sent in second.inputs] == [prompts.RECONNECT_PROMPT]
    assert any(
        sent["type"] == "speech_transcript" and "Sorry about that" in sent["text"]
        for sent in ws.sent
    )


def _closed_error():
    """A websockets ConnectionClosedError, exactly as the SDK raises it."""
    from websockets.exceptions import ConnectionClosedError

    return ConnectionClosedError(None, None)


def test_a_connection_closed_error_is_recognised():
    assert live_session.is_connection_closed(_closed_error()) is True
    assert live_session.is_connection_closed(LiveDropped("stall")) is True
    # A tool blowing up is not the connection going away.
    assert live_session.is_connection_closed(ValueError("bad menu item")) is False


# ------------------------------------------------- 2j item 4: GoAway, both ways


def test_a_goaway_with_little_time_left_reconnects_at_once():
    session, _ws = doubles.new_session()

    async def go():
        session.turn_in_progress = True
        await session._handle_message(doubles.message(go_away=doubles.go_away("4s")))

    asyncio.run(go())
    assert session.recover_pending == "GoAway"
    assert session.go_away_waiting is False


def test_a_goaway_with_time_left_waits_for_the_turn_to_finish():
    session, _ws = doubles.new_session()

    async def go():
        session.turn_in_progress = True
        await session._handle_message(doubles.message(go_away=doubles.go_away("20s")))
        # Nothing yet: THE HOST is in the middle of a sentence.
        assert session.go_away_waiting is True
        assert session.recover_pending is None
        await session._handle_message(doubles.message(doubles.content(turn_complete=True)))

    asyncio.run(go())
    assert session.recover_pending == "GoAway"
    assert session.go_away_waiting is False


def test_a_goaway_between_turns_reconnects_at_once_however_much_time_is_left():
    session, _ws = doubles.new_session()
    asyncio.run(session._handle_message(doubles.message(go_away=doubles.go_away("20s"))))
    # There is no turn to wait for.
    assert session.recover_pending == "GoAway"


def test_an_unreadable_goaway_does_not_gamble_on_the_turn():
    session, _ws = doubles.new_session()

    async def go():
        session.turn_in_progress = True
        await session._handle_message(doubles.message(go_away=doubles.go_away(None)))

    asyncio.run(go())
    assert session.recover_pending == "GoAway"


def test_the_goaway_duration_is_read_as_seconds():
    assert live_session.goaway_seconds(doubles.go_away("9.5s")) == 9.5
    assert live_session.goaway_seconds(doubles.go_away("10")) == 10.0
    assert live_session.goaway_seconds(doubles.go_away(None)) == 0.0
    assert live_session.goaway_seconds(doubles.go_away("soon")) == 0.0


# ------------------------------------------------- 2j item 5: the stall watchdog


def test_silence_alone_never_arms_the_watchdog():
    """The whole point: a guest who says nothing is not a stall."""
    session, _ws = doubles.new_session()
    assert session._stall_deadline() is None
    # A quiet session, however long it sits there.
    asyncio.run(session._handle_message(doubles.message(doubles.content())))
    assert session._stall_deadline() is None


def test_a_fragment_from_the_guest_arms_the_watchdog(monkeypatch):
    session, _ws = doubles.new_session()
    monkeypatch.setattr(live_session, "_now", lambda: 1000.0)

    asyncio.run(session._handle_message(doubles.message(doubles.content(visitor="hello"))))

    assert session._stall_deadline() == 1000.0 + config.STALL_S


def test_model_output_disarms_the_watchdog():
    session, _ws = doubles.new_session()

    async def go():
        await session._handle_message(doubles.message(doubles.content(visitor="hello")))
        await session._handle_message(doubles.message(doubles.content(agent="hi there")))

    asyncio.run(go())
    # Gemini answered, so nothing is owed.
    assert session.awaiting_model_since is None


def test_a_tool_response_arms_the_watchdog(monkeypatch):
    session, _ws = doubles.new_session()
    clock = [1000.0]
    monkeypatch.setattr(live_session, "_now", lambda: clock[0])

    asyncio.run(
        session._handle_message(doubles.message(tool_call=doubles.call("get_business_info")))
    )

    # The tool call itself is output; it is the response going back that starts
    # the clock, because from there Gemini owes us the answer.
    assert session.awaiting_model_since == 1000.0
    assert session.last_audio_chunk_at is None


def test_the_watchdog_fires_when_nothing_comes_back(monkeypatch, caplog):
    # The real STALL_S is asserted on its own above; here it is shortened so the
    # watchdog's own wait is the thing being tested, not the clock.
    monkeypatch.setattr(config, "STALL_S", 0.05)
    session, _ws = doubles.new_session()

    class Silent:
        async def receive(self):
            # Heard the guest, then nothing at all -- session 2b4d1ebc.
            yield doubles.message(doubles.content(visitor="can I get a burger"))
            await asyncio.sleep(30)
            yield doubles.message(doubles.content(agent="too late"))

    session.session = Silent()

    with caplog.at_level(logging.INFO, logger="live_session"):
        with pytest.raises(LiveDropped) as caught:
            asyncio.run(session._pump())

    assert caught.value.kind == "stall"
    assert "live stalled session" in caplog.text


def test_a_turn_that_stops_mid_word_is_a_stall(monkeypatch, caplog):
    """Session d9386dcc: 34 seconds in SPEAKING with no turn_complete."""
    monkeypatch.setattr(config, "STALL_S", 0.05)
    session, _ws = doubles.new_session()

    class Trailing:
        async def receive(self):
            yield doubles.message(doubles.content(audio=b"chunk"))
            await asyncio.sleep(30)

    session.session = Trailing()

    with caplog.at_level(logging.INFO, logger="live_session"):
        with pytest.raises(LiveDropped):
            asyncio.run(session._pump())

    assert "live stalled session" in caplog.text


def test_a_finished_turn_disarms_both_clocks():
    session, _ws = doubles.new_session()

    async def go():
        await session._handle_message(doubles.message(doubles.content(visitor="hello")))
        await session._handle_message(doubles.message(doubles.content(audio=b"chunk")))
        await session._handle_message(doubles.message(doubles.content(turn_complete=True)))

    asyncio.run(go())
    assert session._stall_deadline() is None


def test_the_pump_waits_for_ever_when_nothing_is_owed():
    """An armed watchdog is the exception; the ordinary state is no deadline."""
    session, _ws = doubles.new_session()

    class Quiet:
        async def receive(self):
            yield doubles.message(doubles.content())
            await asyncio.sleep(0.2)

    session.session = Quiet()
    # No stall, and no deadline: it ends because the stream ended.
    with pytest.raises(LiveDropped) as caught:
        asyncio.run(session._pump())
    assert caught.value.kind == "StopAsyncIteration"


# ------------------------------------------- 2j item 9: the latency log line


def test_the_latency_line_is_logged_once_a_turn_with_no_words(monkeypatch, caplog):
    session, _ws = doubles.new_session()
    clock = [1000.0]
    monkeypatch.setattr(live_session, "_now", lambda: clock[0])

    async def go():
        await session._handle_message(
            doubles.message(doubles.content(visitor="can I get a burger"))
        )
        clock[0] += 1.25
        await session._handle_message(doubles.message(doubles.content(audio=b"chunk")))
        await session._handle_message(doubles.message(doubles.content(agent="Of course")))

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(go())

    lines = [line for line in caplog.text.splitlines() if "turn latency" in line]
    assert len(lines) == 1
    assert f"from_visitor=1.25" in lines[0]
    # The guest's words are nowhere in it, and nor are THE HOST's.
    assert "burger" not in lines[0]
    assert "Of course" not in lines[0]


def test_each_turn_gets_its_own_latency_line(monkeypatch, caplog):
    session, _ws = doubles.new_session()
    clock = [1000.0]
    monkeypatch.setattr(live_session, "_now", lambda: clock[0])

    async def go():
        for gap in (0.5, 2.0):
            await session._handle_message(doubles.message(doubles.content(visitor="hello")))
            clock[0] += gap
            await session._handle_message(doubles.message(doubles.content(audio=b"chunk")))
            await session._handle_message(
                doubles.message(doubles.content(turn_complete=True))
            )

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(go())

    lines = [line for line in caplog.text.splitlines() if "turn latency" in line]
    assert len(lines) == 2
    assert "from_visitor=0.50" in lines[0]
    assert "from_visitor=2.00" in lines[1]


def test_nothing_is_timed_before_the_guest_has_said_anything(caplog):
    """The opening greeting answers an instruction, not a guest."""
    session, _ws = doubles.new_session()

    with caplog.at_level(logging.INFO, logger="live_session"):
        asyncio.run(session._handle_message(doubles.message(doubles.content(audio=b"chunk"))))

    assert "turn latency" not in caplog.text


def test_no_log_line_in_the_whole_turn_carries_the_transcript(caplog):
    """2j item 9 and the standing rule: no transcript text reaches any log."""
    session, _ws = doubles.new_session()
    secret = "I would like a Club Sandwich please"

    with caplog.at_level(logging.DEBUG, logger="live_session"):
        async def go():
            await session._handle_message(doubles.message(doubles.content(visitor=secret)))
            await session._handle_message(doubles.message(doubles.content(audio=b"chunk")))
            await session._handle_message(
                doubles.message(doubles.content(agent="Of course, coming up"))
            )
            await session._handle_message(
                doubles.message(doubles.content(turn_complete=True))
            )

        asyncio.run(go())

    assert secret not in caplog.text
    assert "Club Sandwich" not in caplog.text
    assert "coming up" not in caplog.text
