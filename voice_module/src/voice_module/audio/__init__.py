"""Audio recording and microphone utilities."""

from .microphone import (
    list_microphones,
    get_default_microphone,
    validate_device,
    get_device_info,
    MicrophoneInfo,
    MicrophoneError,
)

from .recording import (
    RecordingSession,
    record_fixed_duration,
    RecordingError,
    validate_recording,
)

__all__ = [
    "list_microphones",
    "get_default_microphone",
    "validate_device",
    "get_device_info",
    "MicrophoneInfo",
    "MicrophoneError",
    "RecordingSession",
    "record_fixed_duration",
    "RecordingError",
    "validate_recording",
]