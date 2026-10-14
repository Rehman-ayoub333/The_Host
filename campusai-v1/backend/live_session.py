import asyncio
import base64
import contextlib
import json
import logging
import time
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

# The audio socket carries only these five event types (03 section 2);
# capture_request is the fifth, added in Phase 4.
AUDIO_SOCKET_EVENTS = frozenset(
    {"agent_state_changed", "speech_transcript", "interrupted", "error", "capture_request"}
)

# 07 section 2 rule 2: while a draft is pending these never replace TAKING_ORDER.
HELD_WHILE_ORDERING = frozenset({"THINKING", "SPEAKING", "GREETING", "RECOMMENDING"})

# 16 section 2a item 3: the state each tool call announces before it runs.
TOOL_STATES = {
    "remember_visitor": "REMEMBERING",
    "recommend_item": "RECOMMENDING",
    "request_operator_help": "NEEDS_HELP",
    # 09 section 17: rule 2 lets SEEING interrupt TAKING_ORDER.
    "look_at_camera": "SEEING",
}

# 16 section 2a item 11: the source tag a tool result falls back to.
MENU_TOOLS = ("check_item_availability", "get_business_info")
UNSOURCED_TOOLS = ("recommend_item", "signal_confirmation_request")

# 16 section 2g item 4: how often the watcher looks at a pending announcement.
ANNOUNCE_WATCH_INTERVAL_S = 1

# 16 section 2h item 5: cleared for the rest of the process the first time a
# connect carrying proactive audio is refused, so the next guest does not pay
# for the same refusal again. `config.PROACTIVE_AUDIO` decides whether it is
# tried at all; at build time gemini-3.8-live rejected the field outright.
_proactive_audio_ok = True
_proactive_unsupported_logged = False


class PageEnded(Exception):
    """16 section 2j item 2: the browser ended the conversation during the connect.

    Not a failure: nobody is left to show an error to, so `run` treats it exactly
    like the socket closing and goes straight to `stop()`.
    """


class LiveDropped(Exception):
    """16 section 2j item 4: the Gemini connection went away mid-conversation.

    `kind` is what goes in the log line: the exception type for a real drop,
    `stall` for the watchdog, `GoAway` for the server saying goodbye.
    """

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


def _now() -> float:
    """The monotonic clock, in one place so a test can wind it forward."""
    return time.monotonic()


# The connection-closed errors the Live API can raise at us. The google-genai
# SDK speaks websockets, so these are its exceptions; the names are matched as
# well as the classes, because a drop that reaches us wrapped in something else
# is still a drop (16 section 2j item 4 says any connection-closed error).
_CLOSED_NAMES = frozenset(
    {
        "ConnectionClosed",
        "ConnectionClosedError",
        "ConnectionClosedOK",
        "ConnectionResetError",
        "IncompleteReadError",
        "WebSocketException",
    }
)


def is_connection_closed(exc: BaseException) -> bool:
    """True when `exc` means the Gemini connection itself has gone."""
    if isinstance(exc, LiveDropped):
        return True
    for klass in type(exc).__mro__:
        if klass.__name__ in _CLOSED_NAMES:
            return True
    return False


def goaway_seconds(go_away) -> float:
    """The seconds left in a GoAway, 0.0 when the server did not say.

    `time_left` arrives as a duration string ("9.5s"). An unreadable or absent
    value counts as no time left, so the connection is rebuilt at once rather
    than gambling on a turn finishing first (16 section 2j item 4).
    """
    raw = getattr(go_away, "time_left", None)
    if raw is None:
        return 0.0
    try:
        return float(str(raw).strip().rstrip("s") or 0.0)
    except ValueError:
        return 0.0


def redact(text: str) -> str:
    """The API key never reaches a log line or an error message."""
    if config.GEMINI_API_KEY:
        return text.replace(config.GEMINI_API_KEY, "[REDACTED]")
    return text


def failure_message(exc: Exception) -> str:
    """The honest, human-readable message for a failure (03 section 4, messages unchanged)."""
    lowered = str(exc).lower()
    if "429" in lowered or "resource_exhausted" in lowered or "quota" in lowered:
        return "The AI service is busy right now. Please try again in a minute."
    if isinstance(exc, asyncio.TimeoutError):
        return "I couldn't reach my brain in time. Please try again."
    return "Something went wrong. Please try again."


def build_live_config(
    now: datetime, proactive: bool = False, resume_handle: str | None = None
) -> types.LiveConnectConfig:
    settings = dict(
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
        # 16 section 2j item 4: a handle lets a rebuilt connection carry on the
        # same conversation. `handle=None` is the fresh connect: it asks the
        # server to start issuing handles, which is what makes a resume possible
        # at all. Handles stay valid for two hours.
        session_resumption=types.SessionResumptionConfig(handle=resume_handle),
        # 16 section 2j item 6: the server waits about 800 ms of silence before it
        # decides the guest has finished, which is most of the pause Rehman heard
        # before every reply. START_SENSITIVITY_LOW is deliberately gone (it was
        # 2h item 5): with the handheld microphone it is not needed, and it may be
        # why short replies went unheard. Every other VAD field, the end-of-speech
        # sensitivity included, stays at the server default.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                silence_duration_ms=config.SILENCE_DURATION_MS,
            )
        ),
    )
    if proactive:
        # 16 section 2h item 5: only when the model accepts it. The field is
        # documented for the Live API but not supported on every model.
        settings["proactivity"] = types.ProactivityConfig(proactive_audio=True)
    return types.LiveConnectConfig(**settings)


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
        # 16 section 2e item 1: true from the first piece of model output of a
        # turn until that turn ends. Unlike first_audio_sent it survives a tool
        # response, so an announcement cannot be injected into the gap between a
        # tool result and the audio it produces (the order #12 sequence).
        self.turn_in_progress = False
        # 16 section 2f item 3: what the voice page's mic meter reports. The
        # backend's own evidence that the guest is talking (an input
        # transcription fragment) arrives a second or more after the first
        # syllable, which is too late to stop an announcement.
        self.guest_voice_active = False
        # 16 section 2g item 4: when the flag last turned true, and when Gemini
        # last proved the guest really is talking. A flag that stays true with
        # no transcription behind it is room noise, not a guest.
        self.voice_active_since = None
        self.last_input_transcript_at = None
        self.voice_stale_logged = False
        self.greeted = False
        self.recommended_this_turn = False
        self.announcing = False
        self.announcing_turn = False
        # 16 section 2d item 3: announcements that arrived mid-turn, newest last.
        self.pending_announcements = []
        # 16 section 2g item 4: order id -> when it was first deferred, and the
        # one task that makes sure none of them waits for ever.
        self.pending_deferred_at = {}
        self.announce_watcher = None
        # 09 section 17: the timer waiting for a picture we asked the page for.
        self.look_timer = None
        self.transcripts = {"visitor": "", "agent": ""}
        self.last_state = None
        self.closed = False
        # 16 section 2j item 2: the Gemini connect blocks for seconds, and until
        # now nothing read the browser socket while it did, so a guest who left
        # in that window was only noticed afterwards. `prebuffer` holds whatever
        # the page sent during the connect so the uplink still gets it in order.
        self.client = None
        self.prebuffer = []
        self.page_ended = False
        # 16 section 2j item 4: the newest resumable handle, and the live client
        # kept so a reconnect does not need the caller again.
        self.resume_handle = None
        # 2j item 4: set from inside message handling, acted on by the pump --
        # recovery belongs to the one task that owns the Gemini stream.
        self.recover_pending = None
        self.go_away_waiting = False
        # 16 section 2j item 5: the stall watchdog's two clocks. `awaiting_model_
        # since` runs when Gemini owes us output (it heard the guest, or it has a
        # tool result); `last_audio_chunk_at` catches a turn that stops mid-word
        # and never completes. Both are None when nothing is owed, which is how
        # silence alone can never trigger the watchdog.
        self.awaiting_model_since = None
        self.last_audio_chunk_at = None
        # 16 section 2j item 9: one latency line per turn, and no words in it.
        self.turn_latency_logged = False

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

    async def _open(self, client, proactive: bool, handle: str | None = None):
        return await asyncio.wait_for(
            self.stack.enter_async_context(
                client.aio.live.connect(
                    model=config.GEMINI_LIVE_MODEL,
                    config=build_live_config(datetime.now(), proactive, handle),
                )
            ),
            timeout=config.CONNECT_TIMEOUT_S,
        )

    async def _connect(self, client, handle: str | None = None):
        """One connect, with the 2h item 5 proactive-audio fall-back around it."""
        global _proactive_audio_ok, _proactive_unsupported_logged

        proactive = config.PROACTIVE_AUDIO and _proactive_audio_ok
        try:
            return await self._open(client, proactive, handle)
        except Exception as exc:
            if not proactive:
                raise
            # 16 section 2h item 5: the model refused the setup, so proactive
            # audio goes off and the guest still gets their conversation.
            _proactive_audio_ok = False
            if not _proactive_unsupported_logged:
                _proactive_unsupported_logged = True
                log.info("proactive_audio unsupported")
            log.info("proactive_audio refused: %s", redact(str(exc)))
            return await self._open(client, False, handle)

    async def _watch_page_end(self) -> None:
        """16 section 2j item 2: read the browser socket while the connect runs.

        Only two things end the conversation here -- the socket closing and a
        `session_end` message. Everything else the page sent during the connect
        is kept in order for the uplink, which is the only reader once the
        conversation is actually live.
        """
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                self.page_ended = True
                return
            text = message.get("text")
            if text is not None:
                payload = None
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    log.warning("ignored invalid JSON from browser")
                    continue
                if isinstance(payload, dict) and payload.get("type") == "session_end":
                    try:
                        end_message = schemas.SessionEndMessage.model_validate(payload)
                    except ValidationError:
                        log.warning("ignored invalid session_end message")
                        continue
                    log.info(
                        "session end requested session %s reason=%s",
                        self.ctx["session_id"],
                        end_message.reason,
                    )
                    self.page_ended = True
                    return
            self.prebuffer.append(message)

    async def _start(self):
        self.client = genai.Client(api_key=config.GEMINI_API_KEY)
        self.stack = contextlib.AsyncExitStack()
        # 16 section 2j item 2: the connect and the browser socket are watched
        # together. The connect task is created first, so a page that has
        # already gone can never cancel a connect that has already finished.
        connecting = asyncio.create_task(self._connect(self.client))
        watching = asyncio.create_task(self._watch_page_end())

        async def cancel_on_page_end():
            try:
                await watching
            except asyncio.CancelledError:
                return
            connecting.cancel()

        canceller = asyncio.create_task(cancel_on_page_end())
        try:
            self.session = await connecting
        except asyncio.CancelledError:
            if not self.page_ended:
                raise
            # The guest ended it while we were still connecting: nothing failed,
            # so health is left alone and `stop()` does the rest.
            log.info("session cancelled during connect session %s", self.ctx["session_id"])
            raise PageEnded from None
        except Exception as exc:
            health.connect_failed(failure_message(exc))
            raise
        finally:
            watching.cancel()
            canceller.cancel()
            await asyncio.gather(watching, canceller, return_exceptions=True)
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
            # 16 section 2h item 3: `voice` means the guest was already talking,
            # so the opening line asks them to say it again instead of welcoming.
            text=prompts.OPENING_INSTRUCTIONS.get(self.trigger, prompts.GREETING_BUTTON)
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
        except (WebSocketDisconnect, PageEnded):
            # 16 section 2j item 2: the page ending during the connect is as
            # ordinary an end as the socket closing, and just as silent.
            pass
        except Exception as exc:
            await self._fail(exc)
        finally:
            await self.stop()

    async def _fail(self, exc: Exception) -> None:
        log.error("Live session failed: %s: %s", type(exc).__name__, redact(str(exc)))

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
        self._cancel_look_timer()
        self._cancel_announce_watcher()
        # 16 section 2d item 3: a deferred announcement does not survive the
        # session -- but 2g item 4 says it is logged and handed to the display
        # rather than dropped in silence.
        self._drop_pending_announcements()
        self.guest_voice_active = False
        self.voice_active_since = None
        self.voice_stale_logged = False
        # 16 section 2j items 4 and 5: nothing is owed to a session that is over,
        # and a reconnect this session asked for is no longer wanted.
        self.awaiting_model_since = None
        self.last_audio_chunk_at = None
        self.recover_pending = None
        self.go_away_waiting = False
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

    # ------------------------------------------------------------------ vision

    async def _send_vision(self, image_bytes: bytes) -> None:
        """16 section 2d item 4: the one path a snapshot takes to Gemini.

        Both the "Show It Something" button and a look_at_camera capture come
        through here. `client_content` sends the picture and the prompt as a single
        user turn, so the model cannot answer before it has looked; `realtime` is
        the older two-call path, kept so the better of the two can be measured.
        """
        if config.VISION_SEND_MODE == "realtime":
            await self.session.send_realtime_input(
                video=types.Blob(data=image_bytes, mime_type="image/jpeg")
            )
            await self._send_state("SEEING")
            await self.session.send_realtime_input(text=prompts.VISION_PROMPT)
            return
        await self._send_state("SEEING")
        await self.session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[
                    types.Part(
                        inline_data=types.Blob(data=image_bytes, mime_type="image/jpeg")
                    ),
                    types.Part(text=prompts.VISION_PROMPT),
                ],
            ),
            turn_complete=True,
        )

    # ---------------------------------------------------------- camera request

    def _cancel_look_timer(self) -> None:
        if self.look_timer is not None and not self.look_timer.done():
            self.look_timer.cancel()
        self.look_timer = None

    async def _request_capture(self) -> None:
        """09 section 17: ask the voice page for one picture, then wait for it."""
        self._cancel_look_timer()
        await self._send_control({"type": "capture_request"})
        summaries.emit_row(summaries.LOOKED_AT_CAMERA, self.ctx["session_id"])
        self.look_timer = asyncio.create_task(self._look_timeout())

    async def _look_timeout(self) -> None:
        """LOOK_TIMEOUT_S passed with no frame: say so honestly (09 section 17)."""
        await asyncio.sleep(config.LOOK_TIMEOUT_S)
        self.look_timer = None
        log.info("camera picture failed session %s", self.ctx["session_id"])
        try:
            await self.session.send_realtime_input(text=prompts.LOOK_FAILED_PROMPT)
        except Exception:
            log.exception("could not tell the model the camera picture failed")
        summaries.emit_row(summaries.CAMERA_FAILED, self.ctx["session_id"])

    # ------------------------------------------------------------------ uplink

    async def _uplink(self):
        while not self.closed:
            if self.prebuffer:
                # 16 section 2j item 2: whatever arrived during the connect, in
                # the order the page sent it.
                message = self.prebuffer.pop(0)
            elif self.page_ended:
                # The page said goodbye while we were connecting. Starlette
                # refuses a second receive() after a disconnect anyway.
                return
            else:
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
                # A valid frame is the answer to any capture_request still waiting
                # (09 section 17), whoever actually took the picture.
                self._cancel_look_timer()
                await self._send_vision(image_bytes)
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
            elif message_type == "voice_activity":
                try:
                    voice_message = schemas.VoiceActivityMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid voice_activity message")
                    continue
                log.info(
                    "voice_activity session %s active=%s",
                    self.ctx["session_id"],
                    "true" if voice_message.active else "false",
                )
                was_active = self.guest_voice_active
                self.guest_voice_active = voice_message.active
                if voice_message.active:
                    # A new latch starts its own clock and may log once (2g item 4).
                    if not was_active:
                        self.voice_active_since = _now()
                        self.voice_stale_logged = False
                else:
                    self.voice_active_since = None
                    self.voice_stale_logged = False
                    await self._announce_on_silence()
            elif message_type == "wrap_up":
                try:
                    schemas.WrapUpMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid wrap_up message")
                    continue
                # 16 section 2i item 3: the conversation has reached its cap, so
                # THE HOST says goodbye itself. Any open draft is left to the
                # existing end-of-session rules (2a item 17).
                log.info("wrap_up session %s", self.ctx["session_id"])
                await self.session.send_realtime_input(text=prompts.WRAP_UP_PROMPT)
            elif message_type == "session_end":
                try:
                    end_message = schemas.SessionEndMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid session_end message")
                    continue
                # 16 section 2g item 3: recorded only. The socket close that
                # follows is what actually ends the conversation.
                log.info(
                    "session end requested session %s reason=%s",
                    self.ctx["session_id"],
                    end_message.reason,
                )
            else:
                log.warning("ignored unknown browser message type: %s", message_type)

    # ---------------------------------------------------------------- downlink

    async def _downlink(self):
        """16 section 2j item 4: the one task that owns the Gemini stream.

        Because it owns it, it is also the only place a connection is rebuilt:
        a drop, a stall or a GoAway comes out of `_pump` as `LiveDropped`, and
        the conversation carries on over a new connection if one can be had.
        """
        while True:
            try:
                await self._pump()
            except Exception as exc:
                if self.closed or not is_connection_closed(exc):
                    raise
                if not await self._recover(exc):
                    raise

    def _stall_deadline(self) -> float | None:
        """16 section 2j item 5: when the watchdog runs out of patience, or None.

        None means nothing is owed to us, which is the whole of "never on
        silence alone": a guest who says nothing arms neither clock.
        """
        deadlines = []
        if self.awaiting_model_since is not None:
            deadlines.append(self.awaiting_model_since + config.STALL_S)
        if self.turn_in_progress and self.last_audio_chunk_at is not None:
            deadlines.append(self.last_audio_chunk_at + config.STALL_S)
        return min(deadlines) if deadlines else None

    async def _pump(self) -> None:
        """Read one connection until it drops, stalls or is told to go away."""
        stream = self.session.receive().__aiter__()
        got_any = False
        while True:
            nxt = asyncio.ensure_future(stream.__anext__())
            deadline = self._stall_deadline()
            timeout = None if deadline is None else max(0.0, deadline - _now())
            done, _pending = await asyncio.wait({nxt}, timeout=timeout)
            if not done:
                # Nothing arrived inside STALL_S of output being owed. Nothing
                # can have changed the clocks either: they only move when a
                # message is handled, which is this loop's own work.
                nxt.cancel()
                await asyncio.gather(nxt, return_exceptions=True)
                log.info("live stalled session %s", self.ctx["session_id"])
                raise LiveDropped("stall")
            try:
                message = nxt.result()
            except StopAsyncIteration:
                if not got_any:
                    raise RuntimeError("Live session ended") from None
                # The stream ended under us mid-conversation: a drop by any
                # other name (2j item 4).
                raise LiveDropped("StopAsyncIteration") from None
            got_any = True
            await self._handle_message(message)
            if self.recover_pending is not None:
                kind, self.recover_pending = self.recover_pending, None
                raise LiveDropped(kind)

    async def _close_live(self) -> None:
        """Drop the dead connection. It is already gone, so errors are expected."""
        old, self.stack = self.stack, contextlib.AsyncExitStack()
        self.session = None
        if old is not None:
            with contextlib.suppress(Exception):
                await old.aclose()

    async def _recover(self, exc: Exception) -> bool:
        """16 section 2j item 4: rebuild the connection instead of ending.

        The browser socket is never touched: as far as the guest is concerned
        this is the same conversation, and `self.ctx` -- the draft, the visitor,
        the announcements still pending -- travels with it, because it is.
        """
        kind = exc.kind if isinstance(exc, LiveDropped) else type(exc).__name__
        await self._send_control({"type": "interrupted"})
        # Whatever either side was half-way through saying was cut off, exactly
        # as in the ordinary `interrupted` path: an unfinished agent line is
        # marked, and a half-finished visitor line does not sit there afterwards
        # looking like a guest still mid-sentence.
        await self._flush_transcripts(interrupted=True)
        log.info("live dropped session %s: %s", self.ctx["session_id"], kind)
        health.recovering()
        await self._close_live()
        self.turn_in_progress = False
        self.first_audio_sent = False
        self.awaiting_model_since = None
        self.last_audio_chunk_at = None
        self.go_away_waiting = False
        self.recover_pending = None

        # Once with the handle, then once without it. A fresh connection has
        # none of the conversation behind it, so the draft is handed back in the
        # opening turn (step 4).
        handles = [self.resume_handle, None] if self.resume_handle else [None]
        for handle in handles:
            try:
                self.session = await self._connect(self.client, handle)
            except Exception as retry_exc:
                log.info(
                    "live reconnect attempt failed session %s resumed=%s: %s",
                    self.ctx["session_id"],
                    "true" if handle else "false",
                    redact(str(retry_exc)),
                )
                await self._close_live()
                continue
            resumed = handle is not None
            log.info(
                "live reconnected session %s resumed=%s",
                self.ctx["session_id"],
                "true" if resumed else "false",
            )
            health.connect_ok()
            await self.session.send_realtime_input(text=await self._reconnect_text(resumed))
            return True

        # Both attempts failed: the existing failure path takes it from here
        # (NEEDS_HELP, then IDLE), and the mode follows 07 section 3's other
        # exit from RECOVERING.
        health.connect_failed(failure_message(exc))
        return False

    async def _reconnect_text(self, resumed: bool) -> str:
        """The apology, plus the draft when the new connection has no history."""
        text = prompts.RECONNECT_PROMPT
        pending = self.ctx.get("pending_order_id")
        if resumed or not pending:
            return text
        try:
            order = await asyncio.to_thread(data.get_order, pending)
        except Exception:
            log.exception("could not read the open draft for the reconnect turn")
            return text
        if order is None or order["status"] != "PENDING_CONFIRMATION":
            return text
        items = ", ".join(
            f"{entry.get('quantity')} x {entry.get('name')}"
            for entry in order.get("items") or []
            if entry
        )
        if not items:
            return text
        return text + " " + prompts.RECONNECT_DRAFT_TEMPLATE.format(
            order_id=order["id"], items=items
        )

    def _model_output(self) -> None:
        """16 section 2j item 5: Gemini has answered, so nothing is owed to us."""
        self.awaiting_model_since = None

    def _log_turn_latency(self) -> None:
        """16 section 2j item 9: the first output of a turn, timed from the guest.

        Only the number is written. There is nothing to measure before the first
        fragment of a conversation (the opening instruction, an announcement),
        and nothing to add after the first output of a turn.
        """
        if self.turn_latency_logged or self.last_input_transcript_at is None:
            return
        self.turn_latency_logged = True
        log.info(
            "turn latency session %s from_visitor=%.2f",
            self.ctx["session_id"],
            _now() - self.last_input_transcript_at,
        )

    async def _handle_message(self, message):
        # 16 section 2j item 4: the newest handle the server has given us, kept
        # so a rebuilt connection can carry on the same conversation.
        update = message.session_resumption_update
        if update is not None and update.resumable and update.new_handle:
            self.resume_handle = update.new_handle

        if message.go_away is not None:
            left = goaway_seconds(message.go_away)
            if left > config.GOAWAY_TURN_GRACE_S and self.turn_in_progress:
                # There is time: let THE HOST finish its sentence first.
                log.info(
                    "live go_away session %s seconds_left=%.1f, waiting for the turn",
                    self.ctx["session_id"],
                    left,
                )
                self.go_away_waiting = True
            else:
                log.info(
                    "live go_away session %s seconds_left=%.1f",
                    self.ctx["session_id"],
                    left,
                )
                self.recover_pending = "GoAway"

        server_content = message.server_content
        if server_content is not None:
            if server_content.interrupted:
                log.info("interrupted session %s", self.ctx["session_id"])
                await self._send_control({"type": "interrupted"})
                await self._end_of_turn(interrupted=True)

            if server_content.model_turn:
                for part in server_content.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        self.turn_in_progress = True
                        self._model_output()
                        self._log_turn_latency()
                        self.last_audio_chunk_at = _now()
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
                # 16 section 2g item 4: Gemini's own proof that the guest really
                # is talking, which is what keeps the voice flag believable.
                self.last_input_transcript_at = _now()
                # 2j item 5: it has heard the guest, so it owes us an answer.
                self.awaiting_model_since = _now()
                await self._on_transcript_fragment(
                    "visitor", server_content.input_transcription.text
                )

            if (
                server_content.output_transcription
                and server_content.output_transcription.text
            ):
                self.turn_in_progress = True
                self._model_output()
                self._log_turn_latency()
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
        self.turn_in_progress = False
        self.recommended_this_turn = False
        # 16 section 2j items 5 and 9: the turn is over, so nothing is owed and
        # the next turn gets its own latency line.
        self.awaiting_model_since = None
        self.last_audio_chunk_at = None
        self.turn_latency_logged = False
        if self.go_away_waiting:
            # 2j item 4: the server gave us time to finish the turn, and we have.
            self.go_away_waiting = False
            self.recover_pending = "GoAway"
        # Only the announcing turn's own end clears the flag (2c item 3).
        # Injecting the announcement mid-turn makes Gemini interrupt itself, and
        # that earlier turn's end must not cancel the announcement it caused.
        if self.announcing_turn:
            self.announcing = False
            self.announcing_turn = False
        if self.pending_announcements and not self.voice_active_effective():
            # 16 section 2d item 3: one deferred announcement per turn end, after
            # the resting state is set. Injecting it mid-turn made Gemini cut its
            # own greeting off at the booth, so it waits for a gap instead.
            # 2f item 4: the end of THE HOST's turn is not a gap at all if the
            # guest has already started talking into it.
            order = self.pending_announcements.pop(0)
            self.pending_deferred_at.pop(order["id"], None)
            try:
                await self._announce_now(order)
            except Exception:
                # The order is READY and order_ready already reached both screens;
                # a failed injection must never end the conversation (2c item 3).
                log.exception("the deferred order-ready announcement could not be spoken")

    # ------------------------------------------------------------ announcement

    def voice_active_effective(self) -> bool:
        """16 section 2g item 4: the voice flag, with a latched one disbelieved.

        `C.VOICE_ACTIVE_LEVEL` is low enough that room noise holds the page's
        flag true indefinitely (seen at the booth: 45 s in session 334855a7,
        which swallowed an announcement). A flag that has been true for
        `VOICE_ACTIVE_STALE_S` with no input transcription in that window is
        noise, so the deferral stops believing it.
        """
        if not self.guest_voice_active:
            return False
        if self.voice_active_since is None:
            return True
        now = _now()
        if now - self.voice_active_since < config.VOICE_ACTIVE_STALE_S:
            return True
        last = self.last_input_transcript_at
        if last is not None and now - last < config.VOICE_ACTIVE_STALE_S:
            return True
        if not self.voice_stale_logged:
            # Once per latch, not once per check.
            self.voice_stale_logged = True
            log.info(
                "voice_activity stale session %s, treated as inactive",
                self.ctx["session_id"],
            )
        return False

    def _announcement_blocked(self) -> bool:
        """Everything that makes this moment the wrong one to speak into.

        A model turn counts as in progress from its first output until its
        `turn_complete`, tool responses included; a non-empty visitor buffer
        means the guest is still in the middle of a sentence. `self.session` is
        None for the whole Gemini connect, because `main` publishes `ACTIVE` as
        soon as the socket opens (16 section 2e item 1a: the connect window is
        not a gap either, and `ACTIVE` deliberately stays where it is so the
        one-conversation guard keeps working). `guest_voice_active` is the voice
        page's mic meter (2f item 4), which hears the guest before Gemini
        transcribes them.
        """
        return bool(
            self.session is None
            or self.turn_in_progress
            or self.transcripts["visitor"]
            or self.voice_active_effective()
        )

    def _defer_announcement(self, order) -> None:
        log.info(
            "announce deferred session %s order %s",
            self.ctx["session_id"],
            order["id"],
        )
        if all(pending["id"] != order["id"] for pending in self.pending_announcements):
            self.pending_announcements.append(order)
            self.pending_deferred_at[order["id"]] = _now()
        self._start_announce_watcher()

    async def announce(self, order) -> None:
        """16 section 2e items 1 and 1a and 2f items 4 and 5: speak it now only
        if nothing is in the way, and only if nothing turns up during the grace.

        A deferred announcement leaves from the next end of turn, or from the
        `voice_activity` message that says the guest has stopped talking.
        """
        if self._announcement_blocked():
            self._defer_announcement(order)
            return
        # 2f item 5: a guest who has only just started speaking is still
        # invisible here, so wait a moment and look at every condition again.
        await asyncio.sleep(config.ANNOUNCE_GRACE_S)
        if self._announcement_blocked():
            self._defer_announcement(order)
            return
        await self._announce_now(order)

    async def _announce_on_silence(self) -> None:
        """2f item 4: the guest stopped talking, so this is a gap to speak into."""
        if self.turn_in_progress or not self.pending_announcements:
            return
        order = self.pending_announcements.pop(0)
        self.pending_deferred_at.pop(order["id"], None)
        try:
            await self._announce_now(order)
        except Exception:
            # The order is READY and order_ready already reached both screens;
            # a failed injection must never end the conversation (2c item 3).
            log.exception("the deferred order-ready announcement could not be spoken")

    # -------------------------------------------------- the deferral watchdog

    def _start_announce_watcher(self) -> None:
        if self.announce_watcher is not None and not self.announce_watcher.done():
            return
        if self.closed or not self.pending_announcements:
            return
        self.announce_watcher = asyncio.create_task(self._watch_pending())

    def _cancel_announce_watcher(self) -> None:
        if self.announce_watcher is not None and not self.announce_watcher.done():
            self.announce_watcher.cancel()
        self.announce_watcher = None

    async def _watch_pending(self) -> None:
        """16 section 2g item 4: one task per session, so nothing waits for ever.

        `_end_of_turn` and the `active: false` message are still the ordinary
        ways out; this only catches the case where neither ever happens --
        a latched voice flag, or a guest who simply never stops making noise.
        """
        try:
            while self.pending_announcements and not self.closed:
                await asyncio.sleep(ANNOUNCE_WATCH_INTERVAL_S)
                if self.closed or not self.pending_announcements:
                    break
                order = self.pending_announcements[0]
                waited = _now() - self.pending_deferred_at.get(order["id"], _now())
                a_real_gap = (
                    self.session is not None
                    and not self.turn_in_progress
                    and not self.transcripts["visitor"]
                    and not self.voice_active_effective()
                )
                # Past the cap the guest's noise no longer counts, but a model
                # turn still does: cutting Gemini off is what 2e item 1 fixed.
                overdue = (
                    waited >= config.ANNOUNCE_MAX_DEFER_S
                    and self.session is not None
                    and not self.turn_in_progress
                )
                if not (a_real_gap or overdue):
                    continue
                if await self._announce_pending(order, overdue=overdue):
                    self.pending_announcements.remove(order)
                    self.pending_deferred_at.pop(order["id"], None)
        finally:
            self.announce_watcher = None

    async def _announce_pending(self, order, *, overdue: bool) -> bool:
        """The 2f item 5 grace, then speak. True if the order is finished with.

        Past `ANNOUNCE_MAX_DEFER_S` the re-check deliberately ignores the
        visitor buffer and the voice flag -- 2g item 4 says they are ignored at
        the cap, and believing them again here is what let order #2 be lost.
        `session is None` and a running turn are always respected.
        """
        await asyncio.sleep(config.ANNOUNCE_GRACE_S)
        if self.session is None or self.turn_in_progress:
            return False
        if not overdue and (self.transcripts["visitor"] or self.voice_active_effective()):
            return False
        try:
            await self._announce_now(order)
        except Exception:
            log.exception("the deferred order-ready announcement could not be spoken")
        return True

    def _drop_pending_announcements(self) -> None:
        """16 section 2g item 4: nothing is lost silently. The order is READY, so
        the public display shows and speaks it instead (04 section 5).
        """
        for order in self.pending_announcements:
            log.info(
                "announce dropped session %s order %s, handed to display",
                self.ctx["session_id"],
                order["id"],
            )
            event_bus.publish(
                {
                    "type": "order_ready",
                    "order_id": order["id"],
                    "customer_name": order.get("guest_name"),
                    "session_id": None,
                }
            )
        self.pending_announcements.clear()
        self.pending_deferred_at.clear()

    async def _announce_now(self, order) -> None:
        """2c item 3 / 04 section 5 step 3: THE HOST's own voice, this turn only."""
        log.info(
            "announce session %s order %s", self.ctx["session_id"], order["id"]
        )
        try:
            await self.session.send_realtime_input(
                text=prompts.ANNOUNCE_TEMPLATE.format(
                    order_id=order["id"], name=order.get("guest_name") or "a guest"
                )
            )
        except Exception:
            # 2e item 1a (ii): nothing was said, so the next turn must not be
            # labelled ANNOUNCING. The caller logs and swallows (2c item 3).
            self.announcing = False
            self.announcing_turn = False
            raise
        # Only a send that really left sets the flag.
        self.announcing = True

    # -------------------------------------------------------------- tool calls

    def _drain_activity_queue(self) -> None:
        """16 section 2d item 1: publish the rows the tool queued (09 section 1)."""
        queue = self.ctx.get("activity_queue")
        while queue:
            summaries.emit_row(queue.pop(0), self.ctx["session_id"])

    async def _handle_tool_call(self, tool_call):
        # A tool call is model output: the turn is running and stays running
        # across the tool response below (16 section 2e item 1).
        self.turn_in_progress = True
        self._model_output()
        self._log_turn_latency()
        # 16 section 2j item 5: from here the turn is waiting on us, not on
        # Gemini, so the audio clock is parked until the response goes back.
        self.last_audio_chunk_at = None
        function_responses = []
        look_requested = False
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
            if name == "look_at_camera":
                # Its row goes out with the capture_request, after the response
                # below has been sent (09 section 17).
                look_requested = look_requested or "error" not in result
            else:
                summaries.emit_tool_activity(name, args, result, self.ctx["session_id"])
            # The tool's own row first, then anything only the tool could compute.
            self._drain_activity_queue()
            function_responses.append(
                types.FunctionResponse(
                    id=function_call.id,
                    name=name,
                    response=result,
                )
            )
        self.first_audio_sent = False
        await self.session.send_tool_response(function_responses=function_responses)
        # 16 section 2j item 5: Gemini has its result; something must come back.
        self.awaiting_model_since = _now()
        if look_requested:
            # 09 section 17: the page is asked for the picture only after the model
            # has its tool response, and a second call restarts the whole wait.
            await self._request_capture()

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
