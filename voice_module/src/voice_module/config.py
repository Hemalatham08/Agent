"""Configuration for the voice module."""

from dataclasses import dataclass


@dataclass(frozen=True)
class STTConfig:
    """Speech-to-Text configuration."""
    model_size: str = "small"
    compute_type: str = "int8"
    device: str = "cpu"
    language: str = "en"
    beam_size: int = 5
    vad_filter: bool = True
    vad_parameters: dict = None

    def __post_init__(self):
        if self.vad_parameters is None:
            object.__setattr__(self, "vad_parameters", {
                "min_silence_duration_ms": 500,
                "speech_pad_ms": 400
            })


DEFAULT_STT_CONFIG = STTConfig()