"""Audio utility functions."""

import logging
from pathlib import Path
from typing import Tuple, Optional

import soundfile as sf
import numpy as np
from pydub import AudioSegment

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".wma"}


def validate_audio_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate that a file exists and is a supported audio format.

    Returns:
        (is_valid, error_message)
    """
    path = Path(file_path)
    if not path.exists():
        return False, f"File not found: {file_path}"
    if not path.is_file():
        return False, f"Not a file: {file_path}"
    if path.suffix.lower() not in SUPPORTED_FORMATS:
        return False, f"Unsupported format: {path.suffix}. Supported: {', '.join(SUPPORTED_FORMATS)}"
    return True, None


def load_audio_file(file_path: str, target_sr: int = 16000) -> Tuple[np.ndarray, int]:
    """
    Load audio file and resample to target sample rate.

    Returns:
        (audio_array, sample_rate) where audio_array is float32 mono at target_sr.
    """
    valid, error = validate_audio_file(file_path)
    if not valid:
        raise ValueError(error)

    try:
        audio, sr = sf.read(file_path, dtype="float32")
    except Exception as e:
        raise ValueError(f"Failed to read audio file: {e}")

    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)

    if sr != target_sr:
        audio = resample_audio(audio, sr, target_sr)
        sr = target_sr

    return audio, sr


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample audio using pydub for better quality."""
    if orig_sr == target_sr:
        return audio

    audio_int16 = (audio * 32767).astype(np.int16)
    segment = AudioSegment(
        audio_int16.tobytes(),
        frame_rate=orig_sr,
        sample_width=2,
        channels=1
    )
    segment = segment.set_frame_rate(target_sr)
    resampled = np.array(segment.get_array_of_samples(), dtype=np.float32) / 32768.0
    return resampled


def save_audio_file(audio: np.ndarray, file_path: str, sample_rate: int = 16000) -> None:
    """Save audio array to file."""
    sf.write(file_path, audio, sample_rate)