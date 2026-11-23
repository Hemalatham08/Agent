"""Speech-to-Text module."""

from .faster_whisper_stt import FasterWhisperSTT
from .models import Segment, TranscriptionResult, STTError

__all__ = [
    "FasterWhisperSTT",
    "Segment",
    "TranscriptionResult",
    "STTError",
]