import asyncio
import base64
import contextlib
import json
import logging
from datetime import datetime
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from pydantic import ValidationError

import config
import data
import event_bus
import health
import prompts
import schemas
import summaries
import tools


log = logging.getLogger(__name__)

# The audio socket carries only these four event types (03 section 2).
AUDIO_SOCKET_EVENTS = frozenset(
    {"agent_state_changed", "speech_transcript", "interrupted", "error"}
)

# 07 section 2 rule 2: while a draft is pending these never replace TAKING_ORDER.
HELD_WHILE_ORDERING = frozenset({"THINKING", "SPEAKING", "GREETING", "RECOMMENDING"})

# 16 section 2a item 3: the state each tool call announces before it runs.
TOOL_STATES = {
    "remember_visitor": "REMEMBERING",
    "recommend_item": "RECOMMENDING",
    "request_operator_help": "NEEDS_HELP",
}

# 16 section 2a item 11: the source tag a tool result falls back to.
MENU_TOOLS = ("check_item_availability", "get_business_info")
UNSOURCED_TOOLS = ("recommend_item", "signal_confirmation_request")


def failure_message(exc: Exception) -> str:
    """The honest, human-readable message for a failure (03 section 4, messages unchanged)."""
    lowered = str(exc).lower()
    if "429" in lowered or "resource_exhausted" in lowered or "quota" in lowered:
        return "The AI service is busy right now. Please try again in a minute."
    if isinstance(exc, asyncio.TimeoutError):
        return "I couldn't reach my brain in time. Please try again."
    return "Something went wrong. Please try again."


def build_live_config(now: datetime) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=types.Content(
            parts=[types.Part(text=prompts.build_system_instruction(now))]
        ),
        tools=[types.Tool(function_declarations=tools.TOOL_DECLARATIONS)],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=config.GEMINI_VOICE
                )
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )


class LiveSession:
    def __init__(self, ws: WebSocket, trigger: str):
        self.ws = ws
        self.trigger = trigger
        self.session = None
        self.stack = None
        self.tasks = []
        self.ctx = {
            "session_id": uuid4().hex[:8],
            "visitor_name": None,
            "pending_order_id": None,
            "awaiting_confirmation": False,
        }
        self.first_audio_sent = False
        self.greeted = False
        self.recommended_this_turn = False
        self.announcing = False
        self.announcing_turn = False
        self.transcripts = {"visitor": "", "agent": ""}
        self.last_state = None
        self.closed = False

    # ---------------------------------------------------------------- sending

    async def _send_control(self, event: dict) -> None:
        if "session_id" not in event:
            event["session_id"] = self.ctx["session_id"]
        event_bus.stamp(event)
        if event["type"] in AUDIO_SOCKET_EVENTS and not self.closed:
            try:
                await self.ws.send_text(json.dumps(event))
            except Exception:
                self.closed = True
                for task in self.tasks:
                    if not task.done():
                        task.cancel()
        event_bus.publish(event)

    async def _send_state(self, value: str) -> None:
        if value != self.last_state:
            log.info("state %s session %s", value, self.ctx["session_id"])
            await self._send_control({"type": "agent_state_changed", "state": value})
            self.last_state = value

    async def _maybe_send_state(self, value: str) -> None:
        """07 section 2 rule 2: hold TAKING_ORDER through the order exchange."""
        if self.ctx["pending_order_id"] and value in HELD_WHILE_ORDERING:
            return
        await self._send_state(value)

    def resting_state(self) -> str:
        return "TAKING_ORDER" if self.ctx["pending_order_id"] else "LISTENING"

    def _first_audio_state(self) -> str:
        # 07 section 2 rule 3, in order.
        if self.announcing:
            return "ANNOUNCING"
        if not self.greeted:
            return "GREETING"
        if self.recommended_this_turn:
            return "RECOMMENDING"
        return "SPEAKING"

    # ------------------------------------------------------------ transcripts

    async def _emit_transcript(self, role: str, text: str, final: bool) -> None:
        await self._send_control(
            {"type": "speech_transcript", "role": role, "text": text, "final": final}
        )

    async def _flush_transcript(self, role: str, suffix: str = "") -> None:
        text = self.transcripts[role]
        if not text:
            return
        self.transcripts[role] = ""
        await self._emit_transcript(role, text + suffix, True)

    async def _flush_transcripts(self, interrupted: bool = False) -> None:
        await self._flush_transcript("visitor")
        # 16 section 2a item 16: the transcription runs ahead of the audio the
        # guest actually heard, so a cut-off agent line is marked with an ellipsis.
        await self._flush_transcript("agent", " …" if interrupted else "")

    async def _on_transcript_fragment(self, role: str, fragment: str) -> None:
        """03 section 4: the other speaker's line is finalised first; text is the whole line."""
        other = "agent" if role == "visitor" else "visitor"
        await self._flush_transcript(other)
        self.transcripts[role] += fragment
        await self._emit_transcript(role, self.transcripts[role], False)

    # --------------------------------------------------------------- lifecycle

    async def _start(self):
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stack = contextlib.AsyncExitStack()
        try:
            self.session = await asyncio.wait_for(
                self.stack.enter_async_context(
                    client.aio.live.connect(
                        model=config.GEMINI_LIVE_MODEL,
                        config=build_live_config(datetime.now()),
                    )
                ),
                timeout=config.CONNECT_TIMEOUT_S,
            )
        except Exception as exc:
            health.connect_failed(failure_message(exc))
            raise
        health.connect_ok()
        await self._send_state("LISTENING")
        await asyncio.to_thread(
            data.log_system_event,
            "session_started",
            "system",
            {"session_id": self.ctx["session_id"]},
        )
        summaries.emit_activity(
            "system", "Conversation started", None, self.ctx["session_id"]
        )
        await self.session.send_realtime_input(
            text=(
                prompts.GREETING_PRESENCE
                if self.trigger == "presence"
                else prompts.GREETING_BUTTON
            )
        )
        self.tasks = [
            asyncio.create_task(self._uplink()),
            asyncio.create_task(self._downlink()),
        ]

    async def run(self):
        try:
            await self._start()
            done, pending = await asyncio.wait(
                self.tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                # A cancelled uplink/downlink is a normal end (16 section 2a item 14):
                # never let its CancelledError surface as an ASGI traceback. A
                # cancellation of run() itself still propagates.
                if task.cancelled():
                    continue
                task.result()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            await self._fail(exc)
        finally:
            await self.stop()

    async def _fail(self, exc: Exception) -> None:
        error_text = str(exc)
        if config.GEMINI_API_KEY:
            error_text = error_text.replace(config.GEMINI_API_KEY, "[REDACTED]")
        log.error("Live session failed: %s: %s", type(exc).__name__, error_text)

        message = failure_message(exc)
        await self._send_state("NEEDS_HELP")
        await self._send_control(
            {"type": "error", "message": message, "recoverable": True}
        )

    async def _cancel_pending_draft(self) -> None:
        """16 section 2a item 17: an unconfirmed draft dies with the session."""
        pending = self.ctx.get("pending_order_id")
        if not pending:
            return
        try:
            order = await asyncio.to_thread(data.get_order, pending)
            if order is not None and order["status"] == "PENDING_CONFIRMATION":
                result = await asyncio.to_thread(
                    data.update_order_status, pending, "CANCELLED", "session_ended"
                )
                if result["ok"]:
                    event_bus.publish(
                        {
                            "type": "order_updated",
                            "order": data.order_view(result["order"]),
                            "session_id": self.ctx["session_id"],
                        }
                    )
        except Exception:
            log.exception("could not cancel the pending draft at session end")
        finally:
            self.ctx["pending_order_id"] = None

    async def stop(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.stack is not None:
            try:
                await self.stack.aclose()
            except Exception:
                log.exception("failed to close Gemini Live session")
            self.stack = None
        await self._cancel_pending_draft()
        self.ctx["awaiting_confirmation"] = False
        await self._send_state("IDLE")
        self.closed = True
        try:
            await self.ws.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ uplink

    async def _uplink(self):
        while not self.closed:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            if message.get("bytes") is not None:
                await self.session.send_realtime_input(
                    audio=types.Blob(
                        data=message["bytes"],
                        mime_type=config.INPUT_AUDIO_MIME,
                    )
                )
                continue
            if message.get("text") is None:
                continue
            try:
                payload = json.loads(message["text"])
            except json.JSONDecodeError:
                log.warning("ignored invalid JSON from browser")
                continue
            if not isinstance(payload, dict):
                log.warning("ignored non-object browser message")
                continue

            message_type = payload.get("type")
            if message_type == "vision_frame":
                try:
                    vision_message = schemas.VisionFrameMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid vision_frame message")
                    continue
                if len(vision_message.image_base64) > config.MAX_IMAGE_BASE64_CHARS:
                    log.warning("ignored oversized vision_frame")
                    continue
                try:
                    image_bytes = base64.b64decode(
                        vision_message.image_base64,
                        validate=True,
                    )
                except (ValueError, TypeError):
                    log.warning("ignored invalid vision_frame encoding")
                    continue
                log.info("vision_frame session %s", self.ctx["session_id"])
                await self.session.send_realtime_input(
                    video=types.Blob(data=image_bytes, mime_type="image/jpeg")
                )
                await self._send_state("SEEING")
                await self.session.send_realtime_input(text=prompts.VISION_PROMPT)
            elif message_type == "text_input":
                try:
                    text_message = schemas.TextInputMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid text_input message")
                    continue
                text = text_message.text.strip()[:config.MAX_TEXT_INPUT_CHARS]
                if text:
                    log.info(
                        "text_input session %s chars=%s", self.ctx["session_id"], len(text)
                    )
                    # Both buffers close first, agent then visitor, so a partial
                    # spoken line is never overwritten by the typed one.
                    await self._flush_transcript("agent")
                    await self._flush_transcript("visitor")
                    await self._emit_transcript("visitor", text, True)
                    await self.session.send_realtime_input(text=text)
            else:
                log.warning("ignored unknown browser message type: %s", message_type)

    # ---------------------------------------------------------------- downlink

    async def _downlink(self):
        while True:
            got_any = False
            async for message in self.session.receive():
                got_any = True
                await self._handle_message(message)
            if not got_any:
                raise RuntimeError("Live session ended")

    async def _handle_message(self, message):
        server_content = message.server_content
        if server_content is not None:
            if server_content.interrupted:
                log.info("interrupted session %s", self.ctx["session_id"])
                await self._send_control({"type": "interrupted"})
                await self._end_of_turn(interrupted=True)

            if server_content.model_turn:
                for part in server_content.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        if not self.first_audio_sent:
                            self.first_audio_sent = True
                            state = self._first_audio_state()
                            if state == "ANNOUNCING":
                                # This is the announcing turn, so this is the
                                # turn whose end clears the flag (2c item 3).
                                self.announcing_turn = True
                            await self._maybe_send_state(state)
                        await self.ws.send_bytes(part.inline_data.data)

            if (
                server_content.input_transcription
                and server_content.input_transcription.text
            ):
                await self._on_transcript_fragment(
                    "visitor", server_content.input_transcription.text
                )

            if (
                server_content.output_transcription
                and server_content.output_transcription.text
            ):
                await self._on_transcript_fragment(
                    "agent", server_content.output_transcription.text
                )

            if server_content.turn_complete:
                await self._end_of_turn()

        if message.tool_call:
            await self._handle_tool_call(message.tool_call)
        if message.tool_call_cancellation:
            log.info("Live API cancelled a tool call")

    async def _end_of_turn(self, interrupted: bool = False) -> None:
        """16 section 2a item 6 and 07 section 2 rule 1."""
        # The opening greeting is over at the first turn_complete OR interrupted
        # (16 section 2a item 5), so a greeting talked over is not greeted again.
        self.greeted = True
        spoken = self.transcripts["agent"]
        await self._flush_transcripts(interrupted=interrupted)
        if spoken and not interrupted:
            summaries.emit_activity(
                "speech",
                "Responding",
                spoken[:summaries.MAX_DETAIL_SPEECH],
                self.ctx["session_id"],
            )
        pending = self.ctx["pending_order_id"]
        if pending:
            order = await asyncio.to_thread(data.get_order, pending)
            if order is None or order["status"] != "PENDING_CONFIRMATION":
                self.ctx["pending_order_id"] = None
        await self._send_state(self.resting_state())
        self.first_audio_sent = False
        self.recommended_this_turn = False
        # Only the announcing turn's own end clears the flag (2c item 3).
        # Injecting the announcement mid-turn makes Gemini interrupt itself, and
        # that earlier turn's end must not cancel the announcement it caused.
        if self.announcing_turn:
            self.announcing = False
            self.announcing_turn = False

    # ------------------------------------------------------------ announcement

    async def announce(self, order) -> None:
        """2c item 3 / 04 section 5 step 3: THE HOST's own voice, this turn only."""
        self.announcing = True
        log.info(
            "announce session %s order %s", self.ctx["session_id"], order["id"]
        )
        await self.session.send_realtime_input(
            text=prompts.ANNOUNCE_TEMPLATE.format(
                order_id=order["id"], name=order.get("guest_name") or "a guest"
            )
        )

    # -------------------------------------------------------------- tool calls

    async def _handle_tool_call(self, tool_call):
        function_responses = []
        for function_call in tool_call.function_calls:
            args = function_call.args or {}
            name = function_call.name
            if name == "signal_confirmation_request":
                # A pure UI signal: no state message, no activity, no logging.
                self.ctx["awaiting_confirmation"] = True
                result = tools.signal_confirmation_request(**args)
            else:
                if name == "recommend_item":
                    self.recommended_this_turn = True
                await self._maybe_send_state(TOOL_STATES.get(name, "THINKING"))
                result = await self._run_tool(name, args)
                if "error" not in result:
                    if name == "build_order":
                        self.ctx["awaiting_confirmation"] = False
                        await self._send_state("TAKING_ORDER")
                    elif name in ("confirm_order", "cancel_order", "report_feedback"):
                        self.ctx["awaiting_confirmation"] = False
            log.info(
                "tool %s session %s error=%s",
                name,
                self.ctx["session_id"],
                "true" if "error" in result else "false",
            )
            summaries.emit_tool_activity(name, args, result, self.ctx["session_id"])
            function_responses.append(
                types.FunctionResponse(
                    id=function_call.id,
                    name=name,
                    response=result,
                )
            )
        self.first_audio_sent = False
        await self.session.send_tool_response(function_responses=function_responses)

    async def _run_tool(self, name, args):
        function = tools.TOOL_FUNCTIONS.get(name)
        if function is None:
            result = {"error": f"Unknown tool: {name}"}
        else:
            try:
                tools.SESSION_CTX.set(self.ctx)
                result = await asyncio.wait_for(
                    asyncio.to_thread(function, **(args or {})),
                    timeout=config.TOOL_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                result = {"error": "That took too long."}
            except Exception:
                log.exception("tool failed: %s", name)
                result = {"error": "That didn't work."}
        if name not in UNSOURCED_TOOLS:
            result.setdefault(
                "source",
                "web" if name == "web_search" else "menu" if name in MENU_TOOLS else "order",
            )
        return result
