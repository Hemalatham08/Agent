"""Data models for Speech-to-Text."""

from dataclasses import dataclass
from typing import Optional, List


@dataclass
class Segment:
    """A transcribed segment with timestamps."""
    start: float
    end: float
    text: str
    probability: float


@dataclass
class TranscriptionResult:
    """Result of speech transcription."""
    text: str
    language: str
    language_probability: float
    segments: List[Segment]
    duration: float


@dataclass
class STTError(Exception):
    """Error during transcription."""
    code: str
    message: str
    details: Optional[str] = None