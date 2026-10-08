import asyncio
import json
import time
from types import SimpleNamespace

import config
from live_session import LiveSession
import tools


class FakeWebSocket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []

    async def receive(self):
        return next(self.messages)

    async def send_text(self, message):
        self.sent.append(json.loads(message))

    async def close(self):
        pass


class FakeLiveApiSession:
    def __init__(self):
        self.inputs = []
        self.responses = []

    async def send_realtime_input(self, **kwargs):
        self.inputs.append(kwargs)

    async def send_tool_response(self, **kwargs):
        self.responses.append(kwargs)


def test_typed_confirmation_resets_waiting_state():
    websocket = FakeWebSocket(
        [
            {
                "type": "websocket.receive",
                "text": json.dumps({"type": "text_input", "text": "no"}),
            },
            {"type": "websocket.disconnect"},
        ]
    )
    live_api_session = FakeLiveApiSession()
    live_session = LiveSession(websocket, "button")
    live_session.session = live_api_session
    live_session.awaiting_confirmation = True

    asyncio.run(live_session._uplink())

    assert live_session.awaiting_confirmation is False
    assert live_api_session.inputs == [{"text": "no"}]
    assert websocket.sent == [{"type": "state", "value": "listening"}]


def test_tool_timeout_returns_error_and_keeps_source(monkeypatch):
    def slow_tool(**kwargs):
        time.sleep(0.05)
        return {"source": "web"}

    monkeypatch.setattr(config, "TOOL_TIMEOUT_S", 0.01)
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "web_search", slow_tool)
    live_session = LiveSession(FakeWebSocket([]), "button")

    result = asyncio.run(live_session._run_tool("web_search", {}))

    assert result == {"error": "That took too long.", "source": "web"}


def test_confirmation_request_sets_waiting_state():
    websocket = FakeWebSocket([])
    live_api_session = FakeLiveApiSession()
    live_session = LiveSession(websocket, "button")
    live_session.session = live_api_session
    function_call = SimpleNamespace(
        name="signal_confirmation_request",
        args={"summary": "Log the report"},
        id="confirmation-1",
    )
    tool_call = SimpleNamespace(function_calls=[function_call])

    asyncio.run(live_session._handle_tool_call(tool_call))

    assert live_session.awaiting_confirmation is True
    assert websocket.sent == [{"type": "state", "value": "waiting_confirmation"}]


def test_gemini_connect_timeout_sends_error_and_closes(monkeypatch):
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
        lambda **kwargs: SimpleNamespace(
            aio=SimpleNamespace(live=FakeLive()),
        ),
    )
    websocket = FakeWebSocket([])
    live_session = LiveSession(websocket, "button")

    asyncio.run(live_session.run())

    assert websocket.sent == [
        {"type": "state", "value": "error"},
        {
            "type": "error",
            "message": "I couldn't reach my brain in time. Please try again.",
        },
    ]
