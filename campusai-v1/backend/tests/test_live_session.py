import asyncio
import base64
import json
import logging
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta
from types import SimpleNamespace

import config
import event_bus
import main
import prompts
import schemas
import tools
from live_session import LiveSession


EVENT_MODELS = {
    "agent_state_changed": schemas.AgentStateChangedEvent,
    "speech_transcript": schemas.SpeechTranscriptEvent,
    "interrupted": schemas.InterruptedEvent,
    "error": schemas.ErrorEvent,
    "capture_request": schemas.CaptureRequestEvent,
    # 16 section 2k item 3
    "reconnecting": schemas.ReconnectingEvent,
}

BURGER = {"name": "Chicken Burger", "quantity": 1}


# --------------------------------------------------------------------- doubles


class FakeWebSocket:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.sent = []
        self.binary = []
        self.closed = False
        self.query_params = {}
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive(self):
        if self.messages:
            return self.messages.pop(0)
        return {"type": "websocket.disconnect"}

    async def send_text(self, message):
        self.sent.append(json.loads(message))

    async def send_bytes(self, payload):
        self.binary.append(payload)

    async def close(self):
        self.closed = True


class FakeLiveApiSession:
    def __init__(self):
        self.inputs = []
        self.responses = []
        self.client_content = []

    async def send_realtime_input(self, **kwargs):
        self.inputs.append(kwargs)

    async def send_client_content(self, **kwargs):
        self.client_content.append(kwargs)

    async def send_tool_response(self, **kwargs):
        self.responses.append(kwargs)


# --------------------------------------------------------------------- helpers


def new_session(messages=(), trigger="button"):
    ws = FakeWebSocket(messages)
    session = LiveSession(ws, trigger)
    session.session = FakeLiveApiSession()
    return session, ws


def listening(messages=(), trigger="button"):
    """A session that has just connected: _start() has sent LISTENING."""
    session, ws = new_session(messages, trigger)
    asyncio.run(session._send_state("LISTENING"))
    return session, ws


def content(
    *,
    interrupted=False,
    audio=None,
    visitor=None,
    agent=None,
    turn_complete=False,
    generation_complete=False,
):
    parts = [SimpleNamespace(inline_data=SimpleNamespace(data=audio))] if audio else None
    return SimpleNamespace(
        interrupted=interrupted,
        model_turn=SimpleNamespace(parts=parts) if parts else None,
        input_transcription=SimpleNamespace(text=visitor) if visitor else None,
        output_transcription=SimpleNamespace(text=agent) if agent else None,
        turn_complete=turn_complete,
        # 16 section 2j item 5: the real API sends this when the model has
        # finished producing a turn, about one audio-duration before
        # turn_complete arrives.
        generation_complete=generation_complete,
    )


def message(server_content=None, tool_call=None, go_away=None, resumption=None):
    return SimpleNamespace(
        server_content=server_content,
        tool_call=tool_call,
        tool_call_cancellation=None,
        # 16 section 2j item 4: the SDK always carries these two, and
        # live_session reads them on every message.
        go_away=go_away,
        session_resumption_update=resumption,
    )


def call(name, args=None, call_id="call-1"):
    return SimpleNamespace(
        function_calls=[SimpleNamespace(name=name, args=args or {}, id=call_id)]
    )


def feed(session, messages):
    async def go():
        for item in messages:
            await session._handle_message(item)

    asyncio.run(go())


def states(ws):
    return [sent["state"] for sent in ws.sent if sent["type"] == "agent_state_changed"]


def transcripts(ws):
    return [
        {"role": sent["role"], "text": sent["text"], "final": sent["final"]}
        for sent in ws.sent
        if sent["type"] == "speech_transcript"
    ]


def validate(ws):
    """Every JSON message the audio socket sent must match schemas.py."""
    for sent in ws.sent:
        assert sent["type"] in EVENT_MODELS, f"unexpected type on the audio socket: {sent['type']}"
        EVENT_MODELS[sent["type"]].model_validate(sent)


def order_row(order_id):
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, status, items, guest_name, cancel_reason FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    return dict(row)


def backdate(order_id, seconds):
    stamp = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.execute("UPDATE orders SET timestamp = ? WHERE id = ?", (stamp, order_id))
        conn.commit()


# ------------------------------------------------------------------- (a) start


def test_start_sends_listening_and_the_greeting_prompt(monkeypatch):
    live_api = FakeLiveApiSession()

    class FakeConnect:
        async def __aenter__(self):
            return live_api

        async def __aexit__(self, *args):
            return False

    class FakeLive:
        def connect(self, **kwargs):
            return FakeConnect()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "live_session.genai.Client",
        lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(live=FakeLive())),
    )
    session, ws = new_session(trigger="presence")

    async def go():
        await session._start()
        for task in session.tasks:
            task.cancel()
        await asyncio.gather(*session.tasks, return_exceptions=True)

    asyncio.run(go())

    assert states(ws) == ["LISTENING"]
    assert live_api.inputs == [{"text": prompts.GREETING_PRESENCE}]
    validate(ws)


def test_greeting_on_the_first_turn_then_speaking_on_the_next():
    session, ws = listening()

    feed(
        session,
        [
            message(content(audio=b"\x01\x02")),
            message(content(turn_complete=True)),
            message(content(audio=b"\x03\x04")),
            message(content(turn_complete=True)),
        ],
    )

    assert states(ws) == ["LISTENING", "GREETING", "LISTENING", "SPEAKING", "LISTENING"]
    assert ws.binary == [b"\x01\x02", b"\x03\x04"]
    validate(ws)


# ------------------------------------------------------------------- (b) order


def test_an_order_turn_holds_taking_order_throughout():
    session, ws = listening()

    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER"]
    assert order_id is not None
    assert session.ctx["awaiting_confirmation"] is False

    feed(session, [message(tool_call=call("signal_confirmation_request", {"summary": "One burger?"}))])
    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER"]
    assert session.ctx["awaiting_confirmation"] is True

    # The read-back: audio must not replace TAKING_ORDER with SPEAKING.
    feed(session, [message(content(audio=b"\x01")), message(content(turn_complete=True))])
    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER"]
    assert session.ctx["pending_order_id"] == order_id

    feed(session, [message(tool_call=call("confirm_order", {"order_id": order_id}))])
    assert session.ctx["pending_order_id"] is None
    assert session.ctx["awaiting_confirmation"] is False

    feed(session, [message(content(audio=b"\x02")), message(content(turn_complete=True))])
    assert states(ws) == [
        "LISTENING",
        "THINKING",
        "TAKING_ORDER",
        "SPEAKING",
        "LISTENING",
    ]
    assert order_row(order_id)["status"] == "CONFIRMED"
    validate(ws)


def test_build_order_failure_sends_no_taking_order():
    session, ws = listening()

    feed(session, [message(tool_call=call("build_order", {"items": [{"name": "Pizza"}]}))])

    assert states(ws) == ["LISTENING", "THINKING"]
    assert session.ctx["pending_order_id"] is None
    response = session.session.responses[0]["function_responses"][0]
    assert response.response["error"] == "'Pizza' isn't on the menu."
    validate(ws)


# ------------------------------------------------------------------ (c) a "no"


def test_cancelling_a_draft_returns_to_listening():
    session, ws = listening()

    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    feed(session, [message(tool_call=call("signal_confirmation_request", {"summary": "One burger?"}))])
    feed(session, [message(tool_call=call("cancel_order", {"order_id": order_id}))])

    assert session.ctx["pending_order_id"] is None
    assert session.ctx["awaiting_confirmation"] is False

    feed(session, [message(content(turn_complete=True))])

    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER", "LISTENING"]
    assert order_row(order_id)["status"] == "CANCELLED"
    validate(ws)


# --------------------------------------------------------------- (d) expiry


def test_a_draft_that_expired_behind_the_session_is_cleared_at_turn_complete():
    session, ws = listening()

    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    backdate(order_id, config.PENDING_ORDER_TTL_S + 30)

    feed(session, [message(content(turn_complete=True))])

    assert session.ctx["pending_order_id"] is None
    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER", "LISTENING"]
    assert order_row(order_id)["status"] == "CANCELLED"
    assert order_row(order_id)["cancel_reason"] == "expired"
    validate(ws)


# ----------------------------------------------------------- (e) other states


def test_recommend_item_sets_recommending_for_the_whole_turn():
    session, ws = listening()
    feed(session, [message(content(turn_complete=True))])  # the greeting turn is over

    feed(
        session,
        [
            message(tool_call=call("recommend_item", {"item": "Chicken Burger", "reason": "It's great."})),
            message(content(audio=b"\x01")),
            message(content(turn_complete=True)),
        ],
    )

    assert states(ws) == ["LISTENING", "RECOMMENDING", "LISTENING"]
    validate(ws)


def test_remember_visitor_and_operator_help_have_their_own_states():
    session, ws = listening()

    feed(session, [message(tool_call=call("remember_visitor", {"name": "Ahmed"}))])
    assert states(ws)[-1] == "REMEMBERING"
    assert session.ctx["visitor_name"] == "Ahmed"

    feed(session, [message(content(turn_complete=True))])
    assert states(ws)[-1] == "LISTENING"

    feed(session, [message(tool_call=call("request_operator_help", {"reason": "refund"}))])
    assert states(ws)[-1] == "NEEDS_HELP"

    feed(session, [message(content(turn_complete=True))])
    assert states(ws)[-1] == "LISTENING"
    validate(ws)


def test_a_vision_frame_sends_seeing_before_the_vision_prompt():
    image = base64.b64encode(b"fake-jpeg-bytes").decode()
    session, ws = listening(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "vision_frame", "image_base64": image}),
            },
            {"type": "websocket.disconnect"},
        ]
    )

    asyncio.run(session._uplink())

    # The default VISION_SEND_MODE sends the picture and the prompt as one turn
    # (16 section 2d item 4); both modes are covered in test_look_at_camera.py.
    assert states(ws) == ["LISTENING", "SEEING"]
    assert session.session.inputs == []
    assert len(session.session.client_content) == 1
    parts = session.session.client_content[0]["turns"].parts
    assert parts[0].inline_data.mime_type == "image/jpeg"
    assert parts[1].text == prompts.VISION_PROMPT
    validate(ws)


def test_only_some_states_may_interrupt_a_pending_order():
    image = base64.b64encode(b"fake-jpeg-bytes").decode()
    session, ws = listening(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "vision_frame", "image_base64": image}),
            },
            {"type": "websocket.disconnect"},
        ]
    )

    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER"]

    # SEEING may interrupt, and turn_complete returns to TAKING_ORDER.
    asyncio.run(session._uplink())
    assert states(ws)[-1] == "SEEING"
    feed(session, [message(content(turn_complete=True))])
    assert states(ws)[-1] == "TAKING_ORDER"

    # REMEMBERING may interrupt.
    feed(session, [message(tool_call=call("remember_visitor", {"name": "Sara"}))])
    assert states(ws)[-1] == "REMEMBERING"
    feed(session, [message(content(turn_complete=True))])
    assert states(ws)[-1] == "TAKING_ORDER"

    # NEEDS_HELP may interrupt.
    feed(session, [message(tool_call=call("request_operator_help", {"reason": "refund"}))])
    assert states(ws)[-1] == "NEEDS_HELP"
    feed(session, [message(content(turn_complete=True))])
    assert states(ws)[-1] == "TAKING_ORDER"

    # THINKING, RECOMMENDING, SPEAKING and GREETING do not show.
    feed(
        session,
        [
            message(tool_call=call("check_item_availability", {"item": "burger"})),
            message(tool_call=call("recommend_item", {"item": "Blue Lemonade", "reason": "Cold."})),
            message(content(audio=b"\x01")),
        ],
    )
    assert states(ws)[-1] == "TAKING_ORDER"
    assert states(ws) == [
        "LISTENING",
        "THINKING",
        "TAKING_ORDER",
        "SEEING",
        "TAKING_ORDER",
        "REMEMBERING",
        "TAKING_ORDER",
        "NEEDS_HELP",
        "TAKING_ORDER",
    ]
    validate(ws)


# ------------------------------------------------------------ (f) transcripts


def test_transcript_fragments_grow_in_place_and_finalise():
    session, ws = listening()

    feed(
        session,
        [
            message(content(visitor="I'd")),
            message(content(visitor=" like")),
            message(content(visitor=" a burger")),
            message(content(agent="Of course")),
            message(content(turn_complete=True)),
        ],
    )

    assert transcripts(ws) == [
        {"role": "visitor", "text": "I'd", "final": False},
        {"role": "visitor", "text": "I'd like", "final": False},
        {"role": "visitor", "text": "I'd like a burger", "final": False},
        {"role": "visitor", "text": "I'd like a burger", "final": True},
        {"role": "agent", "text": "Of course", "final": False},
        {"role": "agent", "text": "Of course", "final": True},
    ]
    assert session.transcripts == {"visitor": "", "agent": ""}
    validate(ws)


def test_typed_text_is_echoed_once_as_a_final_visitor_line():
    session, ws = listening(
        [
            {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "hello"})},
            {"type": "websocket.disconnect"},
        ]
    )

    asyncio.run(session._uplink())

    assert transcripts(ws) == [{"role": "visitor", "text": "hello", "final": True}]
    assert session.session.inputs == [{"text": "hello"}]
    validate(ws)


def test_typed_text_closes_both_buffers_agent_first():
    """16 section 2a item 8: both buffers are flushed before the typed line."""
    session, ws = listening(
        [
            {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "two burgers"})},
            {"type": "websocket.disconnect"},
        ]
    )
    session.transcripts["agent"] = "Sure thing"
    session.transcripts["visitor"] = "I want"

    asyncio.run(session._uplink())

    assert transcripts(ws) == [
        {"role": "agent", "text": "Sure thing", "final": True},
        {"role": "visitor", "text": "I want", "final": True},
        {"role": "visitor", "text": "two burgers", "final": True},
    ]
    assert session.transcripts == {"visitor": "", "agent": ""}
    validate(ws)


def test_a_partial_spoken_line_is_closed_before_the_typed_line():
    session, ws = listening(
        [
            {"type": "websocket.receive", "text": json.dumps({"type": "text_input", "text": "two burgers"})},
            {"type": "websocket.disconnect"},
        ]
    )

    feed(session, [message(content(visitor="I want"))])
    asyncio.run(session._uplink())

    assert transcripts(ws) == [
        {"role": "visitor", "text": "I want", "final": False},
        {"role": "visitor", "text": "I want", "final": True},
        {"role": "visitor", "text": "two burgers", "final": True},
    ]
    validate(ws)


# ------------------------------------------------------------ (g) interrupted


def test_interrupted_flushes_the_buffers_and_returns_to_the_resting_state():
    session, ws = listening()

    feed(
        session,
        [
            message(content(audio=b"\x01", agent="Let me just")),
            message(content(interrupted=True)),
        ],
    )

    assert [sent["type"] for sent in ws.sent] == [
        "agent_state_changed",
        "agent_state_changed",
        "speech_transcript",
        "interrupted",
        "speech_transcript",
        "agent_state_changed",
    ]
    assert states(ws) == ["LISTENING", "GREETING", "LISTENING"]
    # 16 section 2a item 16: a cut-off agent line is marked with an ellipsis.
    assert transcripts(ws) == [
        {"role": "agent", "text": "Let me just", "final": False},
        {"role": "agent", "text": "Let me just …", "final": True},
    ]
    assert session.transcripts == {"visitor": "", "agent": ""}
    validate(ws)


def test_an_interrupted_greeting_is_not_greeted_a_second_time():
    """16 section 2a item 5: greeted is set at the first turn_complete OR interrupted."""
    session, ws = listening()

    feed(
        session,
        [
            message(content(audio=b"\x01")),
            message(content(interrupted=True)),
            message(content(audio=b"\x02")),
        ],
    )

    assert states(ws) == ["LISTENING", "GREETING", "LISTENING", "SPEAKING"]
    assert session.greeted is True
    validate(ws)


def test_interrupted_during_an_order_rests_in_taking_order():
    session, ws = listening()
    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])

    feed(
        session,
        [
            message(content(agent="So that's")),
            message(content(interrupted=True)),
        ],
    )

    assert states(ws) == ["LISTENING", "THINKING", "TAKING_ORDER"]
    assert transcripts(ws)[-1] == {"role": "agent", "text": "So that's …", "final": True}
    assert session.ctx["pending_order_id"] is not None
    validate(ws)


# ----------------------------------------------------------------- (h) errors


def test_a_connect_timeout_gives_needs_help_then_a_recoverable_error(monkeypatch):
    class FailingConnect:
        async def __aenter__(self):
            raise asyncio.TimeoutError

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeLive:
        def connect(self, **kwargs):
            return FailingConnect()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "live_session.genai.Client",
        lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(live=FakeLive())),
    )
    session, ws = new_session()
    session.session = None

    asyncio.run(session.run())

    assert [sent["type"] for sent in ws.sent] == [
        "agent_state_changed",
        "error",
        "agent_state_changed",
    ]
    assert states(ws) == ["NEEDS_HELP", "IDLE"]
    assert ws.sent[1]["message"] == "I couldn't reach my brain in time. Please try again."
    assert ws.sent[1]["recoverable"] is True
    assert ws.sent[1]["session_id"] == session.ctx["session_id"]
    validate(ws)


def test_a_cancelled_task_ends_run_without_raising(monkeypatch):
    """16 section 2a item 14: a cancelled uplink/downlink is a normal end."""
    live_api = FakeLiveApiSession()

    class FakeConnect:
        async def __aenter__(self):
            return live_api

        async def __aexit__(self, *args):
            return False

    class FakeLive:
        def connect(self, **kwargs):
            return FakeConnect()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "live_session.genai.Client",
        lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(live=FakeLive())),
    )
    session, ws = new_session()

    async def self_cancelling_downlink():
        asyncio.current_task().cancel()
        await asyncio.sleep(0)

    async def never_ending_uplink():
        await asyncio.Event().wait()

    session._downlink = self_cancelling_downlink
    session._uplink = never_ending_uplink

    # Must complete: no CancelledError may escape to the caller (uvicorn).
    asyncio.run(session.run())

    assert states(ws) == ["LISTENING", "IDLE"]
    assert session.ctx["awaiting_confirmation"] is False
    assert ws.closed is True
    validate(ws)


def test_the_evidence_log_lines_never_carry_the_text(caplog):
    """16 section 2a item 15."""
    image = base64.b64encode(b"fake-jpeg-bytes").decode()
    session, ws = listening(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "vision_frame", "image_base64": image}),
            },
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "text_input", "text": "two burgers please"}),
            },
            {"type": "websocket.disconnect"},
        ]
    )
    session_id = session.ctx["session_id"]

    with caplog.at_level(logging.INFO, logger="live_session"):
        feed(session, [message(content(interrupted=True))])
        asyncio.run(session._uplink())

    messages = [record.getMessage() for record in caplog.records]
    assert f"interrupted session {session_id}" in messages
    assert f"vision_frame session {session_id}" in messages
    assert f"text_input session {session_id} chars=18" in messages

    joined = "\n".join(messages)
    assert "two burgers please" not in joined
    assert "burger" not in joined
    assert image not in joined
    assert "fake-jpeg" not in joined


def test_a_second_session_is_refused_with_the_new_error_shape(monkeypatch):
    monkeypatch.setattr(main, "ACTIVE", object())
    ws = FakeWebSocket()

    asyncio.run(main.websocket_session(ws))

    assert len(ws.sent) == 1
    refusal = ws.sent[0]
    assert refusal["type"] == "error"
    assert refusal["message"] == "Another conversation is already active."
    assert refusal["recoverable"] is True
    assert refusal["session_id"] is None
    assert isinstance(refusal["event_id"], int)
    assert ws.closed is True
    schemas.ErrorEvent.model_validate(refusal)


def test_a_tool_timeout_keeps_an_honest_source(monkeypatch):
    def slow_tool(**kwargs):
        time.sleep(0.05)
        return {"source": "web"}

    monkeypatch.setattr(config, "TOOL_TIMEOUT_S", 0.01)
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "web_search", slow_tool)
    session, _ = new_session()

    result = asyncio.run(session._run_tool("web_search", {}))

    assert result == {"error": "That took too long.", "source": "web"}


def test_an_unknown_tool_is_reported_without_a_source():
    session, _ = new_session()

    result = asyncio.run(session._run_tool("no_such_tool", {}))

    assert result == {"error": "Unknown tool: no_such_tool", "source": "order"}


def test_tool_results_get_their_fallback_source(monkeypatch):
    session, _ = new_session()
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "check_item_availability", lambda **k: {})
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "get_business_info", lambda **k: {})
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "web_search", lambda **k: {})
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "build_order", lambda **k: {})
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "recommend_item", lambda **k: {})

    async def go():
        return [
            await session._run_tool("check_item_availability", {}),
            await session._run_tool("get_business_info", {}),
            await session._run_tool("web_search", {}),
            await session._run_tool("build_order", {}),
            await session._run_tool("recommend_item", {}),
        ]

    menu, info, web, order, recommendation = asyncio.run(go())

    assert menu == {"source": "menu"}
    assert info == {"source": "menu"}
    assert web == {"source": "web"}
    assert order == {"source": "order"}
    assert recommendation == {}


# ---------------------------------------------------------------- (i) envelope


def test_one_event_carries_one_id_on_both_paths():
    session, ws = listening()

    feed(session, [message(content(visitor="hi")), message(content(turn_complete=True))])

    assert [sent["event_id"] for sent in ws.sent] == [
        event["event_id"] for event in event_bus.PUBLISHED
    ]
    for sent in ws.sent:
        assert sent["session_id"] == session.ctx["session_id"]
        assert sent["timestamp"]
    for event in event_bus.PUBLISHED:
        assert event["session_id"] == session.ctx["session_id"]
    validate(ws)


def test_the_audio_socket_never_carries_an_event_type_it_should_not():
    session, ws = listening()

    feed(
        session,
        [
            message(tool_call=call("build_order", {"items": [BURGER]})),
            message(content(visitor="yes", turn_complete=True)),
        ],
    )

    assert {sent["type"] for sent in ws.sent} <= set(EVENT_MODELS)
    validate(ws)


# -------------------------------------------------------------------- (j) stop


def test_a_pending_draft_is_cancelled_when_the_session_ends():
    """16 section 2a item 17, for a conversation that ended normally.

    2l item 4 keeps the draft only when the conversation broke; a `session_end`
    reason is what says it did not.
    """
    session, ws = listening()
    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    session.end_reason = "user"
    event_bus.PUBLISHED.clear()

    asyncio.run(session.stop())

    row = order_row(order_id)
    print("order row after the session ended:", row)
    assert row["status"] == "CANCELLED"
    assert row["cancel_reason"] == "session_ended"
    assert session.ctx["pending_order_id"] is None

    updates = [event for event in event_bus.PUBLISHED if event["type"] == "order_updated"]
    print("order_updated published:", updates)
    assert len(updates) == 1
    assert updates[0]["order"]["id"] == order_id
    assert updates[0]["order"]["status"] == "CANCELLED"
    assert updates[0]["session_id"] == session.ctx["session_id"]
    assert states(ws)[-1] == "IDLE"


def test_a_confirmed_order_survives_the_session_ending():
    session, ws = listening()
    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    feed(session, [message(tool_call=call("confirm_order", {"order_id": order_id}))])

    asyncio.run(session.stop())

    assert order_row(order_id)["status"] == "CONFIRMED"


def test_a_session_start_logs_its_row_and_activity(monkeypatch):
    live_api = FakeLiveApiSession()

    class FakeConnect:
        async def __aenter__(self):
            return live_api

        async def __aexit__(self, *args):
            return False

    class FakeLive:
        def connect(self, **kwargs):
            return FakeConnect()

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(
        "live_session.genai.Client",
        lambda **kwargs: SimpleNamespace(aio=SimpleNamespace(live=FakeLive())),
    )
    session, ws = new_session()

    async def go():
        await session._start()
        for task in session.tasks:
            task.cancel()
        await asyncio.gather(*session.tasks, return_exceptions=True)

    asyncio.run(go())

    with closing(sqlite3.connect(config.DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT event_type, detail FROM system_events ORDER BY id"
            ).fetchall()
        ]
    print("system_events rows:", rows)
    started = [row for row in rows if row["event_type"] == "session_started"]
    assert len(started) == 1
    assert json.loads(started[0]["detail"]) == {"session_id": session.ctx["session_id"]}

    activity = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("activity published:", activity)
    assert activity[0]["label"] == "Conversation started"
    assert activity[0]["kind"] == "system"
    assert activity[0]["session_id"] == session.ctx["session_id"]


def test_a_finished_turn_publishes_the_responding_activity():
    session, ws = listening()

    feed(
        session,
        [
            message(content(agent="Of course, one Club Sandwich coming up")),
            message(content(turn_complete=True)),
        ],
    )

    activity = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("activity published:", activity)
    assert len(activity) == 1
    assert activity[0]["kind"] == "speech"
    assert activity[0]["label"] == "Responding"
    assert activity[0]["detail"] == "Of course, one Club Sandwich coming up"


def test_an_interrupted_turn_publishes_no_responding_activity():
    session, ws = listening()

    feed(
        session,
        [
            message(content(agent="Of course, one Club")),
            message(content(interrupted=True)),
        ],
    )

    activity = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    assert activity == []
    assert transcripts(ws)[-1]["text"] == "Of course, one Club …"


def test_a_tool_call_publishes_its_activity():
    session, ws = listening()

    feed(session, [message(tool_call=call("build_order", {"items": [BURGER]}))])
    order_id = session.ctx["pending_order_id"]
    feed(session, [message(tool_call=call("confirm_order", {"order_id": order_id}))])

    activity = [
        (event["kind"], event["label"], event["detail"])
        for event in event_bus.PUBLISHED
        if event["type"] == "agent_activity"
    ]
    print("activity published:", activity)
    assert activity == [
        ("order", f"Order draft #{order_id} prepared", None),
        ("order", f"Order #{order_id} created", "Chicken Burger"),
    ]


def test_signal_confirmation_request_publishes_no_activity():
    session, ws = listening()

    feed(session, [message(tool_call=call("signal_confirmation_request", {"summary": "ok?"}))])

    assert [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"] == []


def test_stop_sends_idle_and_clears_the_confirmation_flag():
    session, ws = listening()
    session.ctx["awaiting_confirmation"] = True

    asyncio.run(session.stop())

    assert states(ws) == ["LISTENING", "IDLE"]
    assert session.ctx["awaiting_confirmation"] is False
    assert session.closed is True
    assert ws.closed is True
    validate(ws)


# ------------------------------------------------------------- (k) tool context


def test_a_tool_sees_the_very_same_context_dict(monkeypatch):
    seen = {}

    def spy_tool(**kwargs):
        own = tools.SESSION_CTX.get()
        seen["id"] = id(own)
        seen["is_same"] = own is CTX_HOLDER["ctx"]
        own["visitor_name"] = "Mutated"
        return {"ok": True}

    session, _ = new_session()
    CTX_HOLDER = {"ctx": session.ctx}
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "web_search", spy_tool)

    asyncio.run(session._run_tool("web_search", {}))

    assert seen["id"] == id(session.ctx)
    assert seen["is_same"] is True
    assert session.ctx["visitor_name"] == "Mutated"
