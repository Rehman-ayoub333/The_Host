import asyncio
import base64
import contextlib
import json
import logging
import re
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

# The audio socket carries only these six event types (03 section 2);
# capture_request is the fifth, added in Phase 4, and `reconnecting` the sixth,
# added in Phase 5f for 16 section 2k item 3.
AUDIO_SOCKET_EVENTS = frozenset(
    {
        "agent_state_changed",
        "speech_transcript",
        "interrupted",
        "error",
        "capture_request",
        "reconnecting",
    }
)

# 07 section 2 rule 2: while a draft is pending these never replace TAKING_ORDER.
HELD_WHILE_ORDERING = frozenset({"THINKING", "SPEAKING", "GREETING", "RECOMMENDING"})

# 16 section 2zb item 3, building the fallback documented in 09 section 5: the
# words that count as the guest's own yes. In the 7i-b live test THE HOST asked
# "Shall I confirm this, Ali?" and called confirm_order in the same turn, before
# Ali had answered, so the confirmation is no longer left to the prompt alone.
# "mhm" is here because it was a real, accepted confirmation in the 8 Oct voice
# test. The list is exactly 2zb item 3(b)'s.
AFFIRMATIVES = (
    "yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "okay", "ok",
    "alright", "go ahead", "please do", "place it", "mhm", "mm-hmm", "uh-huh",
    "haan", "han", "ji", "jee", "theek hai", "thik hai", "bilkul", "kar do",
    "kardo", "ہاں", "جی", "ٹھیک ہے",
)

# Whole word, case-insensitive: "yes" in "yesterday" is not a yes, and the
# hyphens in "mm-hmm" and "uh-huh" are not word characters, so the guards hold
# at both ends. Urdu letters are word characters to `re`, so the same rule works
# for ہاں, جی and ٹھیک ہے.
_AFFIRMATIVE_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(word) for word in AFFIRMATIVES) + r")(?!\w)",
    re.IGNORECASE | re.UNICODE,
)

# 16 section 2zc item 2(b): the cancel guard takes the affirmatives above and
# these as well, because a guest asked "Shall I cancel order number 12?" answers
# either with a yes or by saying again what they want gone.
CANCEL_PHRASES = (
    "cancel", "remove", "don't want", "do not want", "nahi chahiye",
    "nahin chahiye", "cancel kar do", "hata do",
)

_CANCEL_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(re.escape(word) for word in AFFIRMATIVES + CANCEL_PHRASES)
    + r")(?!\w)",
    re.IGNORECASE | re.UNICODE,
)

# The refusal 2zb item 3 requires, word for word. It goes back to Gemini as the
# tool's result, so THE HOST asks the guest again instead of placing an order.
CONFIRM_REFUSAL = {"source": "order", "error": "Please confirm first."}

# 16 section 2zc item 2(b), word for word: a confirmed order is only cancelled
# once the guest has said so themselves.
CANCEL_REFUSAL = {
    "source": "order",
    "error": "Please ask the guest to confirm the cancellation first.",
}


def has_affirmative(line: str) -> bool:
    """True when the guest's line contains one of AFFIRMATIVES as a whole word."""
    return bool(_AFFIRMATIVE_RE.search(line or ""))


def has_cancel_consent(line: str) -> bool:
    """True for a yes or for the guest naming the cancellation themselves."""
    return bool(_CANCEL_RE.search(line or ""))

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

# 16 section 2ze item 6(b): the shortest gap between two lines about dropped
# browser input, in one session. Everything dropped inside the gap is counted
# and reported on the next line.
DROP_LOG_INTERVAL_S = 1

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


# The connection-closed errors the Live API can raise at us (16 section 2j item
# 4: any connection-closed error). Verified at build time on 14 Oct 2026 by
# force-closing a real connection: google-genai does not let the websockets
# exception through at all. `AsyncSession._receive` catches ConnectionClosed and
# re-raises it as `errors.APIError` carrying the websocket close code --
#   APIError: 1006 None. abnormal closure [internal]
# for an aborted transport, and 1011 for the keepalive timeout Rehman's session
# d9386dcc died of. The names below are kept for a raw one reaching us by some
# other path; the close-code range below is what actually fires.
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

# RFC 6455 close codes. An APIError carrying one of these is the websocket
# closing; an HTTP status (429, 500) is a different animal and keeps the
# existing failure path, 429's "the AI service is busy" message included.
WS_CLOSE_CODE_MIN = 1000
WS_CLOSE_CODE_MAX = 1015


def is_connection_closed(exc: BaseException) -> bool:
    """True when `exc` means the Gemini connection itself has gone."""
    if isinstance(exc, LiveDropped):
        return True
    for klass in type(exc).__mro__:
        if klass.__name__ in _CLOSED_NAMES:
            return True
    code = getattr(exc, "code", None)
    if isinstance(code, int) and WS_CLOSE_CODE_MIN <= code <= WS_CLOSE_CODE_MAX:
        return True
    return False


def handle_rejected(exc: BaseException) -> bool:
    """True when a connect failed because the server refused the handle itself.

    16 section 2k item 2 keeps the handle on every attempt but drops it once the
    server rejects it. The distinction is where the refusal came from: an HTTP
    status means we reached the server and it said no (a handle is only valid
    for two hours), while a network-level failure -- DNS, a handshake timeout --
    says nothing about the handle and must not throw it away.
    """
    code = getattr(exc, "code", None)
    return isinstance(code, int) and 400 <= code < 500


def is_api_error(exc: BaseException) -> bool:
    """True for a google-genai `APIError` (or a subclass), matched by name.

    By name for the same reason `is_connection_closed` does it: the SDK's own
    classes are not imported here, and a test double may carry its own.
    """
    return any(klass.__name__ == "APIError" for klass in type(exc).__mro__)


def drops_the_handle(exc: BaseException) -> bool:
    """16 section 2m item 2: after this failure the handle goes no further.

    This amends 2k item 2, which dropped the handle only on an HTTP 4xx. At the
    5f live test both long outages failed first with `gaierror` (the network was
    down) and then kept failing with `APIError` once DNS worked again, every
    time with the stored handle -- so an `APIError` means the server answered
    and refused, and the next attempt goes without the handle. A network error
    (`gaierror`, another `OSError`, a timeout) is none of those classes, so it
    keeps the handle: it never reached the server to be refused.
    """
    return is_api_error(exc) or handle_rejected(exc)


def attempt_result(exc: BaseException) -> str:
    """The `result=` value for a failed attempt (16 section 2m item 2).

    The error type plus its close code or HTTP status, for example
    `APIError:1008`. The error's own text is redacted rather than logged: it can
    repeat anything the request carried, and 12 section 2's rule is that nothing
    but the type and the code is ever written. Capped at 80 characters.
    """
    code = getattr(exc, "code", None)
    name = type(exc).__name__
    return (f"{name}:{code}" if isinstance(code, int) else name)[:80]


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


def join_fragments(text: str, fragment: str) -> str:
    """16 section 2m item 7: one space between a finished sentence and the next.

    Gemini's output transcription splits a reply into fragments and does not
    always carry the space between two sentences with it, which put
    "today.Can I" on the booth screen. A single space goes in where a fragment
    ends a sentence and the next one starts a word; nothing else is touched, so
    a fragment that splits mid-word still joins up as it arrives.
    """
    if text.endswith((".", "!", "?")) and fragment[:1].isalpha():
        return text + " " + fragment
    return text + fragment


def orphan_age_seconds(order) -> int:
    """How long ago the conversation carrying this draft broke, in seconds."""
    try:
        broke = datetime.fromisoformat(order["orphaned_at"])
    except (KeyError, TypeError, ValueError):
        return 0
    return max(0, int((datetime.now() - broke).total_seconds()))


def first_item(items) -> str:
    """The name of the first thing in the order, for the 2l item 7c example."""
    for entry in items or []:
        name = str((entry or {}).get("name") or "").strip()
        if name:
            return name
    return ""


def describe_total(items) -> str:
    """", total Rs. 1,300" -- or nothing at all when a price is missing.

    `compute_total` returns None if any item has no price, and a prompt that
    says "total Rs. None" would have THE HOST read that out loud.
    """
    total = data.compute_total(items or [])
    return f", total {total}" if total else ""


def describe_items(items) -> str:
    """"2 x Chicken Burger, 1 x Blue Lemonade" -- for a prompt, never a log."""
    return ", ".join(
        f"{entry.get('quantity')} x {entry.get('name')}"
        for entry in items or []
        if entry
    )


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
        # before every reply.
        # 2r item 5: and short replies have to be heard. The handheld microphone
        # keeps the room out, so the server may start listening more readily
        # (START_SENSITIVITY_HIGH), and 300 ms of prefix padding keeps the first
        # syllable of a quiet "yes" or a name instead of clipping it. The
        # end-of-speech sensitivity stays at the server default.
        realtime_input_config=types.RealtimeInputConfig(
            automatic_activity_detection=types.AutomaticActivityDetection(
                start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_HIGH,
                prefix_padding_ms=config.PREFIX_PADDING_MS,
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
        # 16 section 2f item 3: what the display screen's mic meter reports. The
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
        # 16 section 2v item 4: an order is never handed over twice. `announced`
        # is every order id THE HOST has spoken in this session, and
        # `announcing_id` is the one whose announcement is in the air right now:
        # sent to Gemini, and not yet finished.
        self.announced = set()
        self.announcing_id = None
        # 09 section 17: the timer waiting for a picture we asked the page for.
        self.look_timer = None
        # 16 section 2zb item 3: what the confirmation guard needs. The guest's
        # latest line and when it arrived (a visitor transcription fragment or a
        # text_input), when a draft was last built or changed in this session and
        # which order that was, and when this session's opening turn ended --
        # the reference point for a draft inherited from a cut-off conversation
        # (2l item 4). The line is held in memory only and never logged.
        self.last_guest_line = ""
        self.last_guest_line_at = None
        self.draft_built_at = None
        self.draft_built_id = None
        self.opening_turn_done_at = None
        # 16 section 2zc item 2(b): when each order was confirmed in this
        # session, so a cancel can be measured against its own confirmation.
        # An order confirmed before this conversation is not in here, and the
        # session's own start stands in: every line of it came afterwards.
        self.confirmed_at = {}
        self.session_started_at = _now()
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
        # 16 section 2ze item 6(b): how many pieces of browser input have been
        # dropped since the last line about it, and when that line was written.
        self.dropped_inputs = 0
        self.dropped_logged_at = None
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
        # 16 section 2s item 2: the tool response Gemini has not answered yet,
        # as (tool name, the moment it was sent). It is what the "tool to
        # output" line measures, and it carries a name and a number, nothing
        # else. None means no tool response is waiting on an answer.
        self.tool_response_pending = None
        # 16 section 2j item 9: one latency line per turn, and no words in it.
        self.turn_latency_logged = False
        # 16 section 2l item 4: how this conversation ended decides what happens
        # to an open draft. A reason only ever arrives from the page's
        # `session_end`; a socket that closes without one, or a failure, is an
        # end by failure, and the draft is kept for the guest to come back to.
        self.end_reason = None
        self.failed = False

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

    def _note_guest_line(self, line: str) -> None:
        """16 section 2zb item 3: the guest's latest line, for the confirm guard.

        Kept in memory for the length of the session and never written anywhere:
        the guard logs a reason, never a word of what was said.
        """
        if line:
            self.last_guest_line = line
            self.last_guest_line_at = _now()

    async def _on_transcript_fragment(self, role: str, fragment: str) -> None:
        """03 section 4: the other speaker's line is finalised first; text is the whole line."""
        other = "agent" if role == "visitor" else "visitor"
        await self._flush_transcript(other)
        if role == "agent":
            self.transcripts[role] = join_fragments(self.transcripts[role], fragment)
        else:
            self.transcripts[role] += fragment
            # The line so far, not just this fragment: a "yes" can arrive split.
            self._note_guest_line(self.transcripts[role])
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
                    self.end_reason = end_message.reason
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
        await self.session.send_realtime_input(text=await self._opening_text())
        self.tasks = [
            asyncio.create_task(self._uplink()),
            asyncio.create_task(self._downlink()),
        ]

    async def _opening_text(self) -> str:
        """The greeting instruction, plus an order left behind by a broken one.

        16 section 2h item 3: `voice` means the guest was already talking, so
        that trigger keeps its own line. 2l item 4: whatever the trigger, a
        draft orphaned less than `config.ORPHAN_DRAFT_S` ago is offered back,
        and this conversation takes it over so the ordinary order rules apply.
        """
        # 16 section 2l item 7a: the greeting line is chosen here, per session,
        # and is never the one the previous session was given.
        text = prompts.opening_instruction(self.trigger)
        try:
            # Anything older than the window is cancelled rather than offered.
            await asyncio.to_thread(data.abandon_orphan_drafts)
            orphan = await asyncio.to_thread(data.latest_orphan_draft)
        except Exception:
            log.exception("could not look for an order left behind by a broken conversation")
            return text
        if orphan is None:
            return text
        items = describe_items(orphan.get("items"))
        if not items:
            return text
        claimed = await asyncio.to_thread(
            data.claim_orphan_draft, orphan["id"], self.ctx["session_id"]
        )
        if claimed is None:
            return text
        self.ctx["pending_order_id"] = claimed["id"]
        who = str(claimed.get("guest_name") or "").strip() or None
        if who:
            # The guest named the order, so this conversation knows them too.
            self.ctx["visitor_name"] = self.ctx.get("visitor_name") or who
        log.info(
            "draft offered session %s order %s",
            self.ctx["session_id"],
            claimed["id"],
        )
        return text + " " + prompts.ORPHAN_DRAFT_TEMPLATE.format(
            seconds=orphan_age_seconds(orphan),
            order_id=claimed["id"],
            items=items,
            total=describe_total(claimed.get("items")),
            name=f", for {who}" if who else "",
            # 2l item 7c: the example line is filled in with this guest's own
            # order, so the model has nothing to invent.
            name_example=f", {who}" if who else "",
            first_item=first_item(claimed.get("items")) or "order",
        )

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
        # 16 section 2l item 4: this end is a failure, so the draft is kept.
        self.failed = True

        message = failure_message(exc)
        await self._send_state("NEEDS_HELP")
        await self._send_control(
            {"type": "error", "message": message, "recoverable": True}
        )

    def _ended_by_failure(self) -> bool:
        """16 section 2l item 4: recovery gave up, or the socket went silently.

        The page sends `session_end` with a reason for every end it means --
        `user`, `timeout`, `cap`, `absent`. No reason at all means the browser
        went away without saying goodbye, which is exactly the broken
        conversation whose draft the guest should be able to come back to.
        """
        return bool(self.failed or self.end_reason is None)

    async def _cancel_pending_draft(self) -> None:
        """16 section 2a item 17: an unconfirmed draft dies with the session.

        2l item 4 carves out the exception: a conversation that broke keeps its
        draft, orphaned with the time, for `config.ORPHAN_DRAFT_S` seconds.
        """
        pending = self.ctx.get("pending_order_id")
        if not pending:
            return
        if self._ended_by_failure():
            try:
                kept = await asyncio.to_thread(data.orphan_draft, pending)
            except Exception:
                log.exception("could not keep the open draft after a broken conversation")
            else:
                if kept:
                    log.info(
                        "draft kept session %s order %s, the conversation broke",
                        self.ctx["session_id"],
                        pending,
                    )
                    self.ctx["pending_order_id"] = None
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
        # 2s item 2: nothing is waiting on an answer either.
        self.tool_response_pending = None
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
        """09 section 17: ask the display screen for one picture, then wait for it."""
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

    async def _to_live(self, awaitable) -> bool:
        """Hand the browser's input to Gemini, surviving the connection dying.

        16 section 2k item 8: a send that is already in flight when the
        connection goes raises the close error here, in the uplink. That error
        killed session `ced7bcbf` 19 ms into its own recovery -- `run()` saw the
        uplink task finish with an exception and took the failure path, which
        cancelled the downlink before it could make a single attempt. The drop
        belongs to the downlink; all the uplink may do is lose the input.
        """
        try:
            await awaitable
            return True
        except Exception as exc:
            if not is_connection_closed(exc):
                raise
            self._log_dropped_input()
            return False

    def _log_dropped_input(self) -> None:
        """One line a second at most, carrying how many were dropped (2ze 6(b)).

        A dying connection drops the page's audio frame by frame, so the old
        line-per-drop filled the 26 Oct log with hundreds of copies of itself
        and buried everything else. The first drop is still reported at once;
        after that the count is carried to the next line a second later, so
        nothing is lost and nothing floods.
        """
        self.dropped_inputs += 1
        now = _now()
        if (
            self.dropped_logged_at is not None
            and now - self.dropped_logged_at < DROP_LOG_INTERVAL_S
        ):
            return
        log.info(
            "browser input dropped on a dying connection session %s dropped n=%s",
            self.ctx["session_id"],
            self.dropped_inputs,
        )
        self.dropped_logged_at = now
        self.dropped_inputs = 0

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
                # 16 section 2j item 4: the browser socket deliberately stays
                # open across a reconnect, so the page goes on streaming audio
                # while there is no connection to put it on. Those few hundred
                # milliseconds are dropped -- the reconnect turn asks the guest
                # to say it again anyway -- and must never end the session.
                if self.session is not None:
                    await self._to_live(
                        self.session.send_realtime_input(
                            audio=types.Blob(
                                data=message["bytes"],
                                mime_type=config.INPUT_AUDIO_MIME,
                            )
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
            # Same reconnect window as the audio above: a message that needs
            # Gemini waits for nothing, because the whole point of 2j item 4 is
            # that the conversation survives. `voice_activity` and `session_end`
            # need no connection at all, so they are always handled.
            if (
                self.session is None
                and message_type in ("vision_frame", "text_input", "wrap_up")
            ):
                log.info(
                    "browser message %s dropped during a reconnect session %s",
                    message_type,
                    self.ctx["session_id"],
                )
                continue
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
                await self._to_live(self._send_vision(image_bytes))
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
                    # 16 section 2zb item 3: a typed line is a guest line too.
                    self._note_guest_line(text)
                    await self._emit_transcript("visitor", text, True)
                    await self._to_live(self.session.send_realtime_input(text=text))
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
                await self._to_live(
                    self.session.send_realtime_input(text=prompts.WRAP_UP_PROMPT)
                )
            elif message_type == "session_end":
                try:
                    end_message = schemas.SessionEndMessage.model_validate(payload)
                except ValidationError:
                    log.warning("ignored invalid session_end message")
                    continue
                # 16 section 2g item 3: recorded only. The socket close that
                # follows is what actually ends the conversation. 2l item 4 is
                # why it is remembered: this is the one signal that the end was
                # a normal one, so an open draft may be cancelled.
                log.info(
                    "session end requested session %s reason=%s",
                    self.ctx["session_id"],
                    end_message.reason,
                )
                self.end_reason = end_message.reason
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
        """Read one connection until it drops, stalls or is told to go away.

        `session.receive()` is **one turn**, not the conversation: the SDK's
        generator yields until the turn is complete and then ends, so a new one
        is opened for every turn. That outer loop is not optional -- reading a
        single generator to its end and calling that a dropped connection is
        what made every conversation end after the greeting. A fresh generator
        that yields nothing at all is the connection really being finished, and
        that is the pre-existing `Live session ended` case.
        """
        while True:
            stream = self.session.receive().__aiter__()
            got_any = False
            while True:
                nxt = asyncio.ensure_future(stream.__anext__())
                deadline = self._stall_deadline()
                timeout = None if deadline is None else max(0.0, deadline - _now())
                done, _pending = await asyncio.wait({nxt}, timeout=timeout)
                if not done:
                    # Nothing arrived inside STALL_S of output being owed.
                    # Nothing can have changed the clocks either: they only move
                    # when a message is handled, which is this loop's own work.
                    nxt.cancel()
                    await asyncio.gather(nxt, return_exceptions=True)
                    log.info("live stalled session %s", self.ctx["session_id"])
                    raise LiveDropped("stall")
                try:
                    message = nxt.result()
                except StopAsyncIteration:
                    # The end of this turn. The conversation carries on.
                    break
                got_any = True
                await self._handle_message(message)
                if self.recover_pending is not None:
                    kind, self.recover_pending = self.recover_pending, None
                    raise LiveDropped(kind)
            if not got_any:
                raise RuntimeError("Live session ended")

    async def _close_live(self) -> None:
        """Drop the dead connection. It is already gone, so errors are expected."""
        old, self.stack = self.stack, contextlib.AsyncExitStack()
        self.session = None
        if old is not None:
            with contextlib.suppress(Exception):
                await old.aclose()

    async def _recover(self, exc: Exception) -> bool:
        """16 section 2k item 2: keep rebuilding the connection for 30 seconds.

        The browser socket is never touched: as far as the guest is concerned
        this is the same conversation, and `self.ctx` -- the draft, the visitor,
        the announcements still pending -- travels with it, because it is.

        This supersedes 2j item 4's "once with the handle, once without": in the
        Wi-Fi tests both of those attempts were spent inside ten seconds of the
        network going down, so the conversation was lost to an outage it should
        have sat through (sessions ced7bcbf and 03db21d2).
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
        # 2k item 3: the page stops its clocks and says "Reconnecting…".
        await self._send_control({"type": "reconnecting", "active": True})
        await self._close_live()
        self.turn_in_progress = False
        self.first_audio_sent = False
        self.awaiting_model_since = None
        self.last_audio_chunk_at = None
        # 2s item 2: the connection that owed the answer is gone with it.
        self.tool_response_pending = None
        self.go_away_waiting = False
        self.recover_pending = None
        try:
            return await self._reconnect_loop(exc)
        finally:
            # Either way: a page left on "Reconnecting…" for ever would be worse
            # than the drop (2k item 3 -- "when it ends, either way").
            await self._send_control({"type": "reconnecting", "active": False})

    async def _reconnect_loop(self, exc: Exception) -> bool:
        """Attempt at once, then every RECOVER_RETRY_S until the window closes.

        Exactly one of `live reconnected` or `live recovery failed` is logged
        for every drop (2k item 2), whatever happens in between.
        """
        started = _now()
        attempt = 0
        while True:
            attempt += 1
            # 2k item 2: the handle goes on every attempt, not just the first.
            handle = self.resume_handle
            resumed = "true" if handle else "false"
            try:
                self.session = await self._connect(self.client, handle)
            except Exception as retry_exc:
                log.info(
                    "live reconnect attempt session %s n=%s resumed=%s result=%s",
                    self.ctx["session_id"],
                    attempt,
                    resumed,
                    # 2m item 2: the type and its close code or status, redacted.
                    attempt_result(retry_exc),
                )
                await self._close_live()
                if handle and drops_the_handle(retry_exc):
                    # The server answered and refused, so every attempt after
                    # this one goes without the handle (2m item 2).
                    log.info(
                        "live resumption handle refused session %s",
                        self.ctx["session_id"],
                    )
                    self.resume_handle = None
                if _now() - started >= config.RECOVER_WINDOW_S:
                    break
                await asyncio.sleep(config.RECOVER_RETRY_S)
                if _now() - started >= config.RECOVER_WINDOW_S:
                    break
                continue
            log.info(
                "live reconnect attempt session %s n=%s resumed=%s result=ok",
                self.ctx["session_id"],
                attempt,
                resumed,
            )
            log.info(
                "live reconnected session %s resumed=%s",
                self.ctx["session_id"],
                resumed,
            )
            health.connect_ok()
            await self.session.send_realtime_input(
                text=await self._reconnect_text(handle is not None)
            )
            return True

        log.info(
            "live recovery failed session %s attempts=%s",
            self.ctx["session_id"],
            attempt,
        )
        # The existing failure path takes it from here (NEEDS_HELP, then IDLE),
        # and the mode follows 07 section 3's other exit from RECOVERING.
        health.connect_failed(failure_message(exc))
        return False

    async def _reconnect_text(self, resumed: bool) -> str:
        """The apology, always carrying the open draft (16 section 2k item 4).

        `resumed` no longer decides this. Resumption is not trusted to have
        restored the order: in the Wi-Fi tests the next conversation knew nothing
        about the order the guest had just placed, so the draft is restated after
        **every** successful reconnect. It is re-read from the database with its
        current status (2l item 5), never taken from this session's memory.
        """
        text = prompts.RECONNECT_PROMPT
        pending = self.ctx.get("pending_order_id")
        if not pending:
            return text
        try:
            order = await asyncio.to_thread(data.get_order, pending)
        except Exception:
            log.exception("could not read the open draft for the reconnect turn")
            return text
        if order is None or order["status"] != "PENDING_CONFIRMATION":
            return text
        items = describe_items(order.get("items"))
        if not items:
            return text
        who = str(order.get("guest_name") or "").strip() or None
        return text + " " + prompts.RECONNECT_DRAFT_TEMPLATE.format(
            order_id=order["id"],
            items=items,
            total=describe_total(order.get("items")),
            # The guest's name when the order carries one (2k item 4).
            name=f", for {who}" if who else "",
        )

    def _model_output(self) -> None:
        """16 section 2j item 5: Gemini has answered, so nothing is owed to us."""
        self.awaiting_model_since = None
        # 16 section 2s item 2: this output is the one a waiting tool response
        # was waiting for, so the gap is measured here and the wait is over.
        # Any model output counts -- audio, an output transcription, a further
        # tool call, or generation_complete -- because each one is Gemini
        # answering. Only the tool's name and the number are written.
        pending = self.tool_response_pending
        if pending is not None:
            self.tool_response_pending = None
            name, sent_at = pending
            log.info(
                "tool to output session %s name=%s s=%.2f",
                self.ctx["session_id"],
                name,
                _now() - sent_at,
            )

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
                # 16 section 2u item 2: whether THE HOST's own audio was in
                # flight when Gemini cut the turn. `first_audio_sent` is true
                # from this turn's first audio chunk until the turn ends, which
                # is exactly the window in which THE HOST can hear itself.
                log.info(
                    "interrupted session %s while_speaking=%s",
                    self.ctx["session_id"],
                    "true" if self.first_audio_sent else "false",
                )
                await self._send_control({"type": "interrupted"})
                await self._end_of_turn(interrupted=True)

            if server_content.model_turn:
                for part in server_content.model_turn.parts or []:
                    # 16 section 2zb item 4b: a thinking model can mark a part
                    # as its reasoning. That part is never forwarded,
                    # transcribed, captioned, logged or stored -- the guest
                    # hears answers, never the thinking behind them. A model
                    # turn's TEXT parts are ignored here in any case: THE HOST's
                    # words reach the page only through output_transcription
                    # below, which is the transcript of the audio it really
                    # spoke.
                    if getattr(part, "thought", None):
                        log.info(
                            "thought part dropped session %s", self.ctx["session_id"]
                        )
                        continue
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

            if server_content.generation_complete:
                # 16 section 2j item 5: the model has finished producing this
                # turn, so nothing is owed and the audio clock stops. What is
                # left is the server pacing `turn_complete` to the answer's
                # real-time duration -- measured at build time on
                # gemini-3.8-live: 1.77 s after the last chunk of a 1.8 s
                # greeting, and about 8.5 s after a 57-chunk answer. Leaving the
                # audio clock running through that made the watchdog fire on
                # every reply longer than STALL_S, which is a healthy
                # conversation, not the dead connection item 5 is about.
                self._model_output()
                self.last_audio_chunk_at = None

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
        if not self.greeted:
            # 16 section 2zb item 3: a draft inherited from a cut-off
            # conversation (2l item 4) was offered in this turn, so a yes only
            # counts if it arrives after the offer has been made.
            self.opening_turn_done_at = _now()
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
        # 16 section 2s item 2: a turn cut short by an interruption can end with
        # a tool response still unanswered. That wait is over with the turn, and
        # measuring it against the next turn's output would invent a long gap.
        self.tool_response_pending = None
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
            # 16 section 2v item 4: THE HOST has finished saying it, so now the
            # order leaves the pending list. It stayed there through the whole
            # announcement so that nothing could lose it in between.
            self._announcement_finished()
        if (
            self.pending_announcements
            and self.announcing_id is None
            and not self.voice_active_effective()
        ):
            # 16 section 2d item 3: one deferred announcement per turn end, after
            # the resting state is set. Injecting it mid-turn made Gemini cut its
            # own greeting off at the booth, so it waits for a gap instead.
            # 2f item 4: the end of THE HOST's turn is not a gap at all if the
            # guest has already started talking into it.
            # 2v item 4: and never while an announcement is still in the air --
            # the order it belongs to is still at the head of this list.
            order = self.pending_announcements[0]
            try:
                await self._announce_now(order)
            except Exception:
                # The order is READY and order_ready already reached both screens;
                # a failed injection must never end the conversation (2c item 3).
                # It stays pending, so the watcher or the session's end still has
                # it (2v item 4).
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
        if self.session is None or self.turn_in_progress:
            # No connection to speak over: mid-reconnect (2j item 4). The
            # announcement stays pending, and the watcher takes it from there.
            return
        if not self.pending_announcements or self.announcing_id is not None:
            return
        order = self.pending_announcements[0]
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
                # 16 section 2v item 4: the head is still being announced, so
                # there is nothing here to rescue yet.
                if self.announcing_id is not None:
                    continue
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
                await self._announce_pending(order, overdue=overdue)
        finally:
            self.announce_watcher = None

    async def _announce_pending(self, order, *, overdue: bool) -> None:
        """The 2f item 5 grace, then speak.

        Past `ANNOUNCE_MAX_DEFER_S` the re-check deliberately ignores the
        visitor buffer and the voice flag -- 2g item 4 says they are ignored at
        the cap, and believing them again here is what let order #2 be lost.
        `session is None` and a running turn are always respected.

        16 section 2v item 4: the order is not removed here. It leaves the
        pending list when its announcement finishes, so a send that fails leaves
        it for the next look instead of dropping it.
        """
        await asyncio.sleep(config.ANNOUNCE_GRACE_S)
        if self.session is None or self.turn_in_progress:
            return
        if not overdue and (self.transcripts["visitor"] or self.voice_active_effective()):
            return
        try:
            await self._announce_now(order)
        except Exception:
            log.exception("the deferred order-ready announcement could not be spoken")

    def _announcement_finished(self) -> None:
        """16 section 2v item 4: the announcing turn is over, so the order goes.

        Called from the end of the announcing turn only. The id stays in
        `self.announced` for the rest of the session, which is what stops
        `_drop_pending_announcements` handing it to the display a second time.
        """
        order_id = self.announcing_id
        self.announcing_id = None
        if order_id is None:
            return
        self.pending_announcements[:] = [
            order for order in self.pending_announcements if order["id"] != order_id
        ]
        self.pending_deferred_at.pop(order_id, None)

    def _drop_pending_announcements(self) -> None:
        """16 section 2g item 4: nothing is lost silently. The order is READY, so
        the public display shows it instead (04 section 5).

        16 section 2v item 4: except one THE HOST has already announced in this
        session. Handing that to the display announced it twice -- and until
        2v item 3 the display said it out loud, in a voice that was not THE
        HOST's.
        """
        for order in self.pending_announcements:
            if order["id"] in self.announced:
                log.info(
                    "announce not handed over session %s order %s, already announced",
                    self.ctx["session_id"],
                    order["id"],
                )
                continue
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
        self.announcing_id = None

    async def _announce_now(self, order) -> None:
        """2c item 3 / 04 section 5 step 3: THE HOST's own voice, this turn only."""
        log.info(
            "announce session %s order %s", self.ctx["session_id"], order["id"]
        )
        try:
            await self.session.send_realtime_input(
                text=prompts.ANNOUNCE_TEMPLATE.format(
                    order_id=order["id"],
                    # 16 section 2l item 3: "Order number 5 for Rehman is ready!"
                    # -- and just the number when the order has no name on it.
                    name=(
                        f" for {order['guest_name'].strip()}"
                        if str(order.get("guest_name") or "").strip()
                        else ""
                    ),
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
        # 16 section 2v item 4: THE HOST is saying this one now, and this session
        # remembers that it did for as long as it lasts.
        self.announcing_id = order["id"]
        self.announced.add(order["id"])

    # -------------------------------------------------------------- tool calls

    def _drain_activity_queue(self) -> None:
        """16 section 2d item 1: publish the rows the tool queued (09 section 1)."""
        queue = self.ctx.get("activity_queue")
        while queue:
            summaries.emit_row(queue.pop(0), self.ctx["session_id"])

    def _confirm_refusal(self, args) -> str | None:
        """16 section 2zb item 3: why this confirm_order may not run, or None.

        (a) a guest line must have arrived after this order's draft was last
        built or changed in this session. For a draft inherited from a cut-off
        conversation (2l item 4) there is no build in this session, so the
        reference point is the end of this session's opening turn -- the offer
        the guest is answering.
        (b) that latest line must contain the guest's own yes.
        """
        try:
            order_id = int(float(args.get("order_id")))
        except (TypeError, ValueError):
            # Not a number: let the tool itself answer, as 09 section 5 has it.
            return None
        if self.draft_built_id is not None and order_id == self.draft_built_id:
            since = self.draft_built_at
        else:
            since = self.opening_turn_done_at
        if (
            since is None
            or self.last_guest_line_at is None
            or self.last_guest_line_at <= since
        ):
            return "no_new_line"
        if not has_affirmative(self.last_guest_line):
            return "no_affirmative"
        return None

    async def _cancel_refusal(self, args) -> str | None:
        """16 section 2zc item 2(b): why this cancel_order may not run, or None.

        It guards a CONFIRMED order only. A draft is never guarded, because a
        "no" to the confirmation question has to cancel it, and the statuses
        past CONFIRMED are the tool's own business (2zc item 2(a) refuses
        PREPARING outright). For a confirmed order the guest must have spoken
        after it was confirmed, and that line must carry their consent -- a yes,
        or the cancellation in their own words.
        """
        try:
            order_id = int(float(args.get("order_id")))
        except (TypeError, ValueError):
            # Not a number: let the tool itself answer, as 09 section 6 has it.
            return None
        order = await asyncio.to_thread(data.get_order, order_id)
        if order is None or order["status"] != "CONFIRMED":
            return None
        since = self.confirmed_at.get(order_id, self.session_started_at)
        if self.last_guest_line_at is None or self.last_guest_line_at <= since:
            return "no_new_line"
        if not has_cancel_consent(self.last_guest_line):
            return "no_consent"
        return None

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
            # 16 section 2zb item 3 and 2zc item 2(b): the two guards. Each
            # names the word the log uses and the answer Gemini is given.
            refusal = None
            if name == "confirm_order":
                refusal, verb, payload = (
                    self._confirm_refusal(args), "confirm", CONFIRM_REFUSAL
                )
            elif name == "cancel_order":
                refusal, verb, payload = (
                    await self._cancel_refusal(args), "cancel", CANCEL_REFUSAL
                )
            if refusal is not None:
                # The tool never runs, Gemini is told to ask the guest, and the
                # activity feed gets no row -- nothing happened to an order.
                # Only the reason is logged, never a word of what the guest said.
                log.info(
                    "%s refused session %s order %s reason=%s",
                    verb,
                    self.ctx["session_id"],
                    args.get("order_id"),
                    refusal,
                )
                function_responses.append(
                    types.FunctionResponse(
                        id=function_call.id,
                        name=name,
                        response=dict(payload),
                    )
                )
                continue
            if name == "signal_confirmation_request":
                # A pure UI signal: no state message, no activity, no logging.
                self.ctx["awaiting_confirmation"] = True
                started = _now()
                result = tools.signal_confirmation_request(**args)
                tool_ms = (_now() - started) * 1000
            else:
                if name == "recommend_item":
                    self.recommended_this_turn = True
                await self._maybe_send_state(TOOL_STATES.get(name, "THINKING"))
                # 16 section 2s item 2: the tool's own time, timed around the
                # call itself. The state message above is ours, not the tool's,
                # so it is deliberately outside the measurement.
                started = _now()
                result = await self._run_tool(name, args)
                tool_ms = (_now() - started) * 1000
                if "error" not in result:
                    if name == "build_order":
                        self.ctx["awaiting_confirmation"] = False
                        # 16 section 2zb item 3: the draft changed, so the guest
                        # has to speak again before it can be confirmed.
                        self.draft_built_at = _now()
                        self.draft_built_id = result.get("order_id")
                        await self._send_state("TAKING_ORDER")
                    elif name in ("confirm_order", "cancel_order", "report_feedback"):
                        self.ctx["awaiting_confirmation"] = False
                        if name == "confirm_order" and result.get("order_id"):
                            # 16 section 2zc item 2(b): from here a cancel of
                            # this order needs the guest to speak again.
                            self.confirmed_at[result["order_id"]] = _now()
            log.info(
                "tool %s session %s error=%s",
                name,
                self.ctx["session_id"],
                "true" if "error" in result else "false",
            )
            # 16 section 2s item 2: how long the tool itself took. No arguments
            # and no result text, on every tool call.
            log.info(
                "tool done session %s name=%s ms=%.0f",
                self.ctx["session_id"],
                name,
                tool_ms,
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
        # 16 section 2s item 2: the clock for "tool to output" starts when the
        # response really leaves. One response carries the whole batch, so the
        # name recorded is the last tool in it -- the one the response waited on.
        self.tool_response_pending = (name, self.awaiting_model_since)
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
