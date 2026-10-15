"""Shared test doubles: a fake browser socket, a fake Gemini Live session, and
builders for the message shapes the SDK hands to live_session._handle_message.
"""

import asyncio
import json
from types import SimpleNamespace

import schemas
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

    async def close(self, code=1000):
        self.closed = True


class SlowWebSocket(FakeWebSocket):
    """An observer that never accepts a send in time."""

    def __init__(self, delay=5.0):
        super().__init__()
        self.delay = delay
        self.attempts = 0

    async def send_text(self, message):
        self.attempts += 1
        await asyncio.sleep(self.delay)


class DeadWebSocket(FakeWebSocket):
    """An observer whose socket is already gone."""

    def __init__(self):
        super().__init__()
        self.attempts = 0

    async def send_text(self, message):
        self.attempts += 1
        raise RuntimeError("socket is closed")


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


def new_session(messages=(), trigger="button"):
    ws = FakeWebSocket(messages)
    session = LiveSession(ws, trigger)
    session.session = FakeLiveApiSession()
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
        # 16 section 2j item 4: the two fields the SDK always carries and
        # live_session now reads on every message.
        go_away=go_away,
        session_resumption_update=resumption,
    )


def go_away(time_left="1s"):
    return SimpleNamespace(time_left=time_left)


def resumption(new_handle="handle-1", resumable=True):
    return SimpleNamespace(
        new_handle=new_handle, resumable=resumable, last_consumed_client_message_index=None
    )


def call(name, args=None, call_id="call-1"):
    return SimpleNamespace(
        function_calls=[SimpleNamespace(name=name, args=args or {}, id=call_id)]
    )


def states(ws):
    return [sent["state"] for sent in ws.sent if sent["type"] == "agent_state_changed"]


def transcripts(ws):
    return [
        {"role": sent["role"], "text": sent["text"], "final": sent["final"]}
        for sent in ws.sent
        if sent["type"] == "speech_transcript"
    ]


def validate(ws):
    for sent in ws.sent:
        assert sent["type"] in EVENT_MODELS, f"unexpected type on the audio socket: {sent['type']}"
        EVENT_MODELS[sent["type"]].model_validate(sent)
