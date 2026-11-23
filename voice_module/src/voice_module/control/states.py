"""Voice control states and errors."""

from enum import Enum
from typing import Optional


class VoiceState(str, Enum):
    """State of the voice control layer."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    STOPPED = "stopped"
    ERROR = "error"


class VoiceControlError(Exception):
    """Error raised by the voice controller."""

    def __init__(self, code: str, message: str, details: Optional[str] = None):
        self.code = code
        self.message = message
        self.details = details
        super().__init__(f"[{code}] {message}")
