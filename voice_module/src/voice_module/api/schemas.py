"""Pydantic schemas for the voice API."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..control.states import VoiceState


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "ifive-voice-api"
    version: str = "0.1.0"


class ErrorDetail(BaseModel):
    """Structured error information."""

    code: str
    message: str
    details: Optional[str] = None


class ErrorResponse(BaseModel):
    """Envelope for API errors."""

    error: ErrorDetail


class VoiceStatusResponse(BaseModel):
    """Current voice controller status."""

    state: VoiceState
    busy: bool
    last_error: Optional[ErrorDetail] = None


class VoiceActionResponse(BaseModel):
    """Result of a voice start/stop action."""

    success: bool = True
    changed: bool
    state: VoiceState
    message: str


class ListenStopResponse(BaseModel):
    """Result of stopping microphone recording."""

    success: bool
    captured: bool
    state: VoiceState
    message: str


class SpeakRequest(BaseModel):
    """Request body for speech playback."""

    text: str = Field(
        ...,
        min_length=1,
        description="Text to synthesize and speak aloud.",
    )

    @field_validator("text")
    @classmethod
    def _text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty or whitespace")
        return value
