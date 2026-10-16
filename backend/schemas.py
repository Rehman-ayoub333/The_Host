from typing import Literal, Optional

from pydantic import BaseModel


AGENT_STATES = (
    "IDLE",
    "GREETING",
    "SEEING",
    "LISTENING",
    "THINKING",
    "SPEAKING",
    "RECOMMENDING",
    "TAKING_ORDER",
    "ANNOUNCING",
    "REMEMBERING",
    "NEEDS_HELP",
)


class EventEnvelope(BaseModel):
    """The common envelope every event carries (03 section 3)."""

    event_id: int
    timestamp: str
    session_id: Optional[str] = None


class AgentStateChangedEvent(EventEnvelope):
    type: Literal["agent_state_changed"]
    state: Literal[
        "IDLE",
        "GREETING",
        "SEEING",
        "LISTENING",
        "THINKING",
        "SPEAKING",
        "RECOMMENDING",
        "TAKING_ORDER",
        "ANNOUNCING",
        "REMEMBERING",
        "NEEDS_HELP",
    ]


class SpeechTranscriptEvent(EventEnvelope):
    type: Literal["speech_transcript"]
    role: Literal["visitor", "agent"]
    text: str
    final: bool


class InterruptedEvent(EventEnvelope):
    type: Literal["interrupted"]


class CaptureRequestEvent(EventEnvelope):
    """03 section 4: the fifth audio-socket event (Phase 4). The smd role never sees it."""

    type: Literal["capture_request"]


class ReconnectingEvent(EventEnvelope):
    """16 section 2k item 3: the sixth audio-socket event (Phase 5f).

    True when recovery starts, false when it ends either way, so the voice page
    can say "Reconnecting…" and hold its clocks instead of timing the guest out
    while the backend is rebuilding the connection.
    """

    type: Literal["reconnecting"]
    active: bool


class ErrorEvent(EventEnvelope):
    type: Literal["error"]
    message: str
    recoverable: bool


class OperationalModeMessage(BaseModel):
    """07 section 5. Its emitter arrives with health.py in Phase 3."""

    type: Literal["operational_mode_changed"]
    mode: Literal["ONLINE", "DEGRADED", "RECOVERING", "OFFLINE", "PAUSED", "OPERATOR_TAKEOVER"]
    reason: str
    timestamp: str


class VisionFrameMessage(BaseModel):
    """Browser -> backend."""

    type: Literal["vision_frame"]
    image_base64: str


class TextInputMessage(BaseModel):
    """Browser -> backend."""

    type: Literal["text_input"]
    text: str


class VoiceActivityMessage(BaseModel):
    """Browser -> backend (16 section 2f item 3). The flag only, never a level."""

    type: Literal["voice_activity"]
    active: bool


class SessionEndMessage(BaseModel):
    """Browser -> backend (16 section 2g item 3). Why the page ended the session;
    the socket close is still what ends it."""

    type: Literal["session_end"]
    reason: Literal["timeout", "cap", "user", "absent"]


class WrapUpMessage(BaseModel):
    """Browser -> backend (16 section 2i item 3). At the session cap THE HOST says
    goodbye itself instead of the page cutting the conversation off."""

    type: Literal["wrap_up"]
