"""Phase 4: the voice-triggered look (09 section 17, 03 section 4, 16 section 2d).

`look_at_camera` is the 13th tool. It takes no picture itself: live_session asks the
display screen for one with `capture_request`, waits `LOOK_TIMEOUT_S`, and says so
honestly if nothing arrives. Both the button and this request send the snapshot to
Gemini through the one function `_send_vision`, in either `VISION_SEND_MODE`.
"""

import asyncio
import base64
import json

import config
import data
import doubles
import event_bus
import prompts
import schemas
import tools


IMAGE = base64.b64encode(b"fake-jpeg-bytes").decode()
FRAME = {
    "type": "websocket.receive",
    "text": json.dumps({"type": "vision_frame", "image_base64": IMAGE}),
}
DISCONNECT = {"type": "websocket.disconnect"}


def sent_types(ws):
    return [message["type"] for message in ws.sent]


def activity_labels():
    return [
        event["label"] for event in event_bus.PUBLISHED if event["type"] == "agent_activity"
    ]


def model_texts(session):
    return [payload["text"] for payload in session.session.inputs if "text" in payload]


async def look(session, args=None, call_id="call-1"):
    await session._handle_message(
        doubles.message(tool_call=doubles.call("look_at_camera", args or {}, call_id))
    )


# ------------------------------------------------------------------ the tool


def test_look_at_camera_is_a_pure_signal(ctx, monkeypatch):
    def fail_if_logged(*args, **kwargs):
        raise AssertionError("look_at_camera must not be logged")

    monkeypatch.setattr(tools.data, "log_action", fail_if_logged)

    result = tools.look_at_camera("the mug I am holding")

    print("look_at_camera returned:", result)
    assert result == {
        "source": "camera",
        "requested": True,
        "note": "A picture is being taken now. Describe nothing until it arrives, "
                "then describe only what is in it.",
    }
    assert list(event_bus.PUBLISHED) == []


def test_the_declaration_is_registered_once():
    assert tools.TOOL_FUNCTIONS["look_at_camera"] is tools.look_at_camera
    declarations = [
        declaration
        for declaration in tools.TOOL_DECLARATIONS
        if declaration["name"] == "look_at_camera"
    ]
    print("declaration:", declarations)
    assert len(declarations) == 1
    assert declarations[0]["behavior"] == "BLOCKING"
    assert declarations[0]["parameters"]["required"] == []
    assert list(declarations[0]["parameters"]["properties"]) == ["reason"]


# -------------------------------------------------------------- happy path


def test_the_happy_path_asks_for_a_picture_and_uses_the_one_that_arrives(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, ws = doubles.new_session([FRAME, DISCONNECT])

    async def go():
        await session._send_state("LISTENING")
        await look(session, {"reason": "this mug"})
        print("socket messages after the tool call:", ws.sent)
        assert session.look_timer is not None
        # The display screen answers with a normal vision_frame.
        await session._uplink()
        print("timer after the frame arrived:", session.look_timer)
        assert session.look_timer is None
        # Long enough for the cancelled timer to have fired, had it survived.
        await asyncio.sleep(0.2)

    asyncio.run(go())

    print("socket message types:", sent_types(ws))
    print("states:", doubles.states(ws))
    print("activity rows:", activity_labels())
    print("send_realtime_input calls:", session.session.inputs)
    print("send_client_content calls:", session.session.client_content)
    print("tool responses:", session.session.responses)

    assert sent_types(ws) == ["agent_state_changed", "agent_state_changed", "capture_request"]
    assert doubles.states(ws) == ["LISTENING", "SEEING"]
    assert activity_labels() == ["Looked at the camera"]
    assert "Camera picture failed" not in activity_labels()
    assert model_texts(session) == []
    assert len(session.session.client_content) == 1
    doubles.validate(ws)


def test_the_capture_request_goes_out_after_the_tool_response():
    """09 section 17: the model has its answer before the page is asked."""
    session, ws = doubles.new_session()
    order = []

    original_send_tool_response = session.session.send_tool_response

    async def recording_send_tool_response(**kwargs):
        order.append("tool_response")
        await original_send_tool_response(**kwargs)

    session.session.send_tool_response = recording_send_tool_response

    original_send_text = ws.send_text

    async def recording_send_text(message):
        if json.loads(message)["type"] == "capture_request":
            order.append("capture_request")
        await original_send_text(message)

    ws.send_text = recording_send_text

    async def go():
        await look(session)
        session._cancel_look_timer()

    asyncio.run(go())

    print("order of events:", order)
    assert order == ["tool_response", "capture_request"]


def test_the_capture_request_reaches_the_bus_with_the_same_event_id():
    session, ws = doubles.new_session()

    async def go():
        await look(session)
        session._cancel_look_timer()

    asyncio.run(go())

    on_socket = [message for message in ws.sent if message["type"] == "capture_request"]
    on_bus = [event for event in event_bus.PUBLISHED if event["type"] == "capture_request"]
    print("capture_request on the audio socket:", on_socket)
    print("capture_request on the bus:", on_bus)
    assert len(on_socket) == 1 and len(on_bus) == 1
    assert on_socket[0]["event_id"] == on_bus[0]["event_id"]
    assert on_socket[0]["session_id"] == session.ctx["session_id"]


# ------------------------------------------------------------ timeout path


def test_the_timeout_tells_the_model_and_the_operator(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, ws = doubles.new_session()

    async def go():
        await session._send_state("LISTENING")
        await look(session)
        await asyncio.sleep(0.2)

    asyncio.run(go())

    print("socket message types:", sent_types(ws))
    print("Gemini inputs:", session.session.inputs)
    print("activity rows:", activity_labels())

    assert model_texts(session) == [prompts.LOOK_FAILED_PROMPT]
    assert activity_labels() == ["Looked at the camera", "Camera picture failed"]
    assert session.look_timer is None
    # The failure is reported honestly, never invented as a description.
    assert prompts.VISION_PROMPT not in model_texts(session)
    assert session.session.client_content == []
    doubles.validate(ws)


def test_the_failure_row_is_the_03_section_4_row(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, _ = doubles.new_session()

    async def go():
        await look(session)
        await asyncio.sleep(0.2)

    asyncio.run(go())

    rows = [event for event in event_bus.PUBLISHED if event["type"] == "agent_activity"]
    print("rows as published:", rows)
    assert [(row["kind"], row["label"], row["detail"]) for row in rows] == [
        ("vision", "Looked at the camera", None),
        ("vision", "Camera picture failed", None),
    ]
    assert [row["kind"] for row in data.list_activity(limit=10)] == ["vision", "vision"]


def test_a_frame_that_arrives_late_still_goes_through_the_vision_path(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, ws = doubles.new_session([FRAME, DISCONNECT])

    async def go():
        await session._send_state("LISTENING")
        await look(session)
        await asyncio.sleep(0.2)          # the timer fires first
        await session._uplink()           # the picture turns up anyway

    asyncio.run(go())

    print("activity rows:", activity_labels())
    print("Gemini inputs:", session.session.inputs)
    assert activity_labels() == ["Looked at the camera", "Camera picture failed"]
    assert len(session.session.client_content) == 1
    assert doubles.states(ws) == ["LISTENING", "SEEING"]


# ------------------------------------------------------------ second call


def test_a_second_call_restarts_the_wait(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.1)
    session, ws = doubles.new_session()

    async def go():
        await session._send_state("LISTENING")
        await look(session, call_id="call-1")
        first = session.look_timer
        await asyncio.sleep(0.06)
        await look(session, call_id="call-2")
        await asyncio.sleep(0)
        print("the first timer was cancelled:", first.cancelled())
        assert first.cancelled()
        assert session.look_timer is not first
        # The first timer would have fired by now; only the second one may.
        await asyncio.sleep(0.07)
        print("activity rows mid-wait:", activity_labels())
        assert "Camera picture failed" not in activity_labels()
        await asyncio.sleep(0.1)

    asyncio.run(go())

    print("socket message types:", sent_types(ws))
    print("activity rows:", activity_labels())
    print("Gemini inputs:", session.session.inputs)
    assert sent_types(ws).count("capture_request") == 2
    assert activity_labels() == [
        "Looked at the camera",
        "Looked at the camera",
        "Camera picture failed",
    ]
    assert model_texts(session) == [prompts.LOOK_FAILED_PROMPT]
    doubles.validate(ws)


def test_the_timer_dies_with_the_session(monkeypatch):
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, ws = doubles.new_session()

    async def go():
        await look(session)
        await session.stop()
        await asyncio.sleep(0.2)

    asyncio.run(go())

    print("activity rows:", activity_labels())
    assert "Camera picture failed" not in activity_labels()
    assert session.look_timer is None


# ------------------------------------------------------- VISION_SEND_MODE


def test_client_content_sends_the_picture_and_the_prompt_as_one_turn(monkeypatch):
    monkeypatch.setattr(config, "VISION_SEND_MODE", "client_content")
    session, ws = doubles.new_session()

    asyncio.run(session._send_vision(b"jpeg-bytes"))

    print("send_realtime_input calls:", session.session.inputs)
    print("send_client_content calls:", session.session.client_content)
    assert session.session.inputs == []
    [sent] = session.session.client_content
    assert sent["turn_complete"] is True
    turns = sent["turns"]
    assert turns.role == "user"
    assert turns.parts[0].inline_data.data == b"jpeg-bytes"
    assert turns.parts[0].inline_data.mime_type == "image/jpeg"
    assert turns.parts[1].text == prompts.VISION_PROMPT
    assert doubles.states(ws) == ["SEEING"]


def test_realtime_sends_the_frame_and_then_the_prompt(monkeypatch):
    monkeypatch.setattr(config, "VISION_SEND_MODE", "realtime")
    session, ws = doubles.new_session()

    asyncio.run(session._send_vision(b"jpeg-bytes"))

    print("send_realtime_input calls:", session.session.inputs)
    print("send_client_content calls:", session.session.client_content)
    assert session.session.client_content == []
    assert [key for payload in session.session.inputs for key in payload] == ["video", "text"]
    assert session.session.inputs[0]["video"].data == b"jpeg-bytes"
    assert session.session.inputs[0]["video"].mime_type == "image/jpeg"
    assert session.session.inputs[1] == {"text": prompts.VISION_PROMPT}
    assert doubles.states(ws) == ["SEEING"]


def test_the_default_mode_is_client_content():
    assert config.VISION_SEND_MODE == "client_content"


def test_the_button_and_the_camera_request_use_the_one_function(monkeypatch):
    """16 section 2d item 4: one vision-send function, whoever took the picture."""
    monkeypatch.setattr(config, "LOOK_TIMEOUT_S", 0.05)
    session, _ = doubles.new_session([FRAME, DISCONNECT])
    calls = []

    original = session._send_vision

    async def recording(image_bytes):
        calls.append(image_bytes)
        await original(image_bytes)

    session._send_vision = recording

    async def go():
        await look(session)
        await session._uplink()

    asyncio.run(go())

    print("_send_vision calls:", calls)
    assert calls == [b"fake-jpeg-bytes"]


# ---------------------------------------------------------- contract checks


def test_the_capture_request_event_matches_its_schema():
    session, ws = doubles.new_session()

    async def go():
        await look(session)
        session._cancel_look_timer()

    asyncio.run(go())

    [message] = [sent for sent in ws.sent if sent["type"] == "capture_request"]
    print("capture_request as sent:", message)
    model = schemas.CaptureRequestEvent.model_validate(message)
    assert model.type == "capture_request"
    assert model.session_id == session.ctx["session_id"]
    assert isinstance(model.event_id, int)
    assert model.timestamp


def test_smd_never_receives_a_capture_request():
    event = event_bus.stamp(
        {"type": "capture_request", "session_id": "a1b2c3d4"}
    )

    print("dashboard sees:", event_bus.filter_for("dashboard", event))
    print("smd sees:", event_bus.filter_for("smd", event))
    assert event_bus.filter_for("smd", event) is None
    assert event_bus.filter_for("dashboard", event) == event
    assert "capture_request" not in event_bus.SMD_ALLOWED
