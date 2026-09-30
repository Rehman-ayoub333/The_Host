from pydantic import BaseModel
from typing import Literal, Optional


class ControlMessage(BaseModel):
    """Backend -> browser JSON messages."""

    type: Literal["state", "transcript", "tool_event", "interrupted", "error"]
    value: Optional[str] = None
    role: Optional[Literal["user", "agent"]] = None
    text: Optional[str] = None
    tool: Optional[str] = None
    status: Optional[Literal["running", "done"]] = None
    summary: Optional[str] = None
    source: Optional[Literal["real", "demo", "web"]] = None
    message: Optional[str] = None


class VisionFrameMessage(BaseModel):
    """Browser -> backend."""

    type: Literal["vision_frame"]
    image_base64: str


class TextInputMessage(BaseModel):
    """Browser -> backend."""

    type: Literal["text_input"]
    text: str