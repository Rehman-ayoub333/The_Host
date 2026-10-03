import asyncio
import base64
import contextlib
import json
import logging
from datetime import datetime

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types
from pydantic import ValidationError

import config
import prompts
import schemas
import summaries
import tools


log = logging.getLogger(__name__)


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
        self.awaiting_confirmation = False
        self.first_audio_sent = False
        self.last_state = None
        self.closed = False

    async def _start(self):
        client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stack = contextlib.AsyncExitStack()
        self.session = await asyncio.wait_for(
            self.stack.enter_async_context(
                client.aio.live.connect(
                    model=config.GEMINI_LIVE_MODEL,
                    config=build_live_config(datetime.now()),
                )
            ),
            timeout=config.CONNECT_TIMEOUT_S,
        )
        await self._send_state("listening")
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

        lowered = str(exc).lower()
        if "429" in lowered or "resource_exhausted" in lowered or "quota" in lowered:
            message = "The AI service is busy right now. Please try again in a minute."
        elif isinstance(exc, asyncio.TimeoutError):
            message = "I couldn't reach my brain in time. Please try again."
        else:
            message = "Something went wrong. Please try again."
        await self._send_state("error")
        await self._send_control(schemas.ControlMessage(type="error", message=message))

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
                await self.session.send_realtime_input(
                    video=types.Blob(data=image_bytes, mime_type="image/jpeg")
                )
                await self.session.send_realtime_input(text=prompts.VISION_PROMPT)
            elif message_type == "text_input":
                try:
                    text_message = schemas.TextInputMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid text_input message")
                    continue
                text = text_message.text.strip()[:config.MAX_TEXT_INPUT_CHARS]
                if text:
                    await self.session.send_realtime_input(text=text)
            else:
                log.warning("ignored unknown browser message type: %s", message_type)

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
                await self._send_control(
                    schemas.ControlMessage(type="interrupted")
                )
                self.first_audio_sent = False
                await self._send_state("listening")

            if server_content.model_turn:
                for part in server_content.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        if not self.first_audio_sent:
                            self.first_audio_sent = True
                            await self._send_state("speaking")
                        await self.ws.send_bytes(part.inline_data.data)

            if (
                server_content.input_transcription
                and server_content.input_transcription.text
            ):
                await self._send_control(
                    schemas.ControlMessage(
                        type="transcript",
                        role="user",
                        text=server_content.input_transcription.text,
                    )
                )
                if self.awaiting_confirmation:
                    self.awaiting_confirmation = False
                    await self._send_state("listening")

            if (
                server_content.output_transcription
                and server_content.output_transcription.text
            ):
                await self._send_control(
                    schemas.ControlMessage(
                        type="transcript",
                        role="agent",
                        text=server_content.output_transcription.text,
                    )
                )

            if server_content.turn_complete:
                self.first_audio_sent = False
                await self._send_state(
                    "waiting_confirmation" if self.awaiting_confirmation else "listening"
                )

        if message.tool_call:
            await self._handle_tool_call(message.tool_call)
        if message.tool_call_cancellation:
            log.info("Live API cancelled a tool call")

    async def _handle_tool_call(self, tool_call):
        function_responses = []
        for function_call in tool_call.function_calls:
            args = function_call.args or {}
            if function_call.name == "signal_confirmation_request":
                self.awaiting_confirmation = True
                result = tools.signal_confirmation_request(**args)
            else:
                await self._send_state("thinking")
                await self._send_control(
                    schemas.ControlMessage(
                        type="tool_event",
                        tool=function_call.name,
                        status="running",
                        summary=summaries.summarize_running(function_call.name, args),
                        source=summaries.default_source(function_call.name),
                    )
                )
                result = await self._run_tool(function_call.name, args)
                await self._send_control(
                    schemas.ControlMessage(
                        type="tool_event",
                        tool=function_call.name,
                        status="done",
                        summary=summaries.summarize_done(
                            function_call.name,
                            args,
                            result,
                        ),
                        source=result.get(
                            "source",
                            summaries.default_source(function_call.name),
                        ),
                    )
                )
            if function_call.name == "create_complaint" and "error" not in result:
                self.awaiting_confirmation = False
            function_responses.append(
                types.FunctionResponse(
                    id=function_call.id,
                    name=function_call.name,
                    response=result,
                )
            )
        self.first_audio_sent = False
        await self.session.send_tool_response(function_responses=function_responses)

    async def _run_tool(self, name, args):
        function = tools.TOOL_FUNCTIONS.get(name)
        if function is None:
            return {"error": f"Unknown tool: {name}", "source": "demo"}
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(function, **(args or {})),
                timeout=config.TOOL_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            result = {"error": "That took too long."}
        except Exception:
            log.exception("tool failed: %s", name)
            result = {"error": "That didn't work."}
        result.setdefault("source", summaries.default_source(name))
        return result

    async def _send_control(self, message: schemas.ControlMessage):
        if self.closed:
            return
        try:
            await self.ws.send_text(message.model_dump_json(exclude_none=True))
        except Exception:
            self.closed = True
            for task in self.tasks:
                if not task.done():
                    task.cancel()

    async def _send_state(self, value: str):
        if value != self.last_state:
            await self._send_control(
                schemas.ControlMessage(type="state", value=value)
            )
            self.last_state = value

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
        self.closed = True
        try:
            await self.ws.close()
        except Exception:
            pass