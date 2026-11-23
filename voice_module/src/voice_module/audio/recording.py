"""Audio recording session management."""

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import sounddevice as sd

from ..utils.audio import save_audio_file

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecordingError(Exception):
    """Error during audio recording."""
    code: str
    message: str
    details: str = None


class RecordingSession:
    """
    Manages an audio recording session with start/stop control.

    Records at 16kHz mono by default (compatible with Faster-Whisper).

    Usage:
        # Manual start/stop
        session = RecordingSession(device_index=0)
        session.start()
        audio, sr = session.stop()
        
        # Or save directly to file
        session = RecordingSession(device_index=0)
        session.start()
        session.save("recording.wav")
        
        # Context manager
        with RecordingSession(device_index=0) as session:
            time.sleep(5)
        # Automatically stops on exit
    """

    def __init__(
        self,
        device_index: int,
        sample_rate: int = 16000,
        channels: int = 1,
        dtype: str = "int16"
    ):
        """
        Initialize a recording session.

        Args:
            device_index: Microphone device index (from list_microphones).
            sample_rate: Sample rate in Hz (default 16000 for Whisper).
            channels: Number of channels (default 1 for mono).
            dtype: Data type for recording (default int16).
        """
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._channels = channels
        self._dtype = dtype

        self._stream: Optional[sd.InputStream] = None
        self._audio_buffer: list = []
        self._lock = threading.Lock()
        self._is_recording = False
        self._start_time: Optional[float] = None
        self._final_duration: float = 0.0
        self._last_audio: Optional[np.ndarray] = None  # Cache for save() after stop()

    @property
    def is_recording(self) -> bool:
        """Whether the session is currently recording."""
        return self._is_recording

    @property
    def sample_rate(self) -> int:
        """Sample rate in Hz."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Number of audio channels."""
        return self._channels

    @property
    def duration(self) -> float:
        """Current recording duration in seconds."""
        if self._start_time is None:
            return 0.0
        if self._is_recording:
            return time.time() - self._start_time
        return self._final_duration

    def start(self) -> None:
        """
        Start recording audio.

        Raises:
            RecordingError: If already recording, device invalid, or PortAudio error.
        """
        with self._lock:
            if self._is_recording:
                raise RecordingError(
                    code="ALREADY_RECORDING",
                    message="Recording session already started"
                )

            try:
                self._audio_buffer = []
                self._start_time = time.time()
                self._is_recording = True
                self._last_audio = None  # Clear cached audio on new recording

                def callback(indata, frames, time_info, status):
                    if status:
                        logger.warning("Recording status: %s", status)
                    with self._lock:
                        if self._is_recording:
                            self._audio_buffer.append(indata.copy())

                self._stream = sd.InputStream(
                    device=self._device_index,
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype=self._dtype,
                    callback=callback,
                )
                self._stream.start()
                logger.info("Recording started on device %d at %d Hz", self._device_index, self._sample_rate)

            except Exception as e:
                self._is_recording = False
                self._start_time = None
                logger.exception("Failed to start recording")
                raise RecordingError(
                    code="START_FAILED",
                    message="Failed to start recording",
                    details=str(e)
                )

    def stop(self) -> Tuple[np.ndarray, int]:
        """
        Stop recording and return the captured audio.

        Returns:
            Tuple of (audio_data, sample_rate) where audio_data is float32 mono array.

        Raises:
            RecordingError: If not currently recording.
        """
        with self._lock:
            if not self._is_recording:
                raise RecordingError(
                    code="NOT_RECORDING",
                    message="No active recording to stop"
                )

            self._is_recording = False
            self._final_duration = time.time() - self._start_time if self._start_time else 0.0

        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
        except Exception as e:
            logger.exception("Error stopping stream")
            raise RecordingError(
                code="STOP_FAILED",
                message="Failed to stop recording stream",
                details=str(e)
            )

        if not self._audio_buffer:
            logger.warning("No audio data captured")
            self._last_audio = np.array([], dtype=np.float32)
            return self._last_audio, self._sample_rate

        audio_int16 = np.concatenate(self._audio_buffer, axis=0)
        audio_float32 = audio_int16.astype(np.float32) / 32768.0

        if self._channels > 1:
            audio_float32 = np.mean(audio_float32, axis=1)

        self._last_audio = audio_float32
        logger.info("Recording stopped: %.2fs, %d samples", self._final_duration, len(audio_float32))
        return audio_float32, self._sample_rate

    def save(self, filepath: str) -> str:
        """
        Stop recording (if still active) and save to WAV file.

        If recording was already stopped via stop(), uses the cached audio data.

        Args:
            filepath: Output file path (will be created with .wav extension).

        Returns:
            Path to saved file.

        Raises:
            RecordingError: If no audio data available or save fails.
        """
        # If still recording, stop first
        if self._is_recording:
            audio_data, sr = self.stop()
        else:
            # Use cached audio from previous stop()
            if self._last_audio is None:
                raise RecordingError(
                    code="NO_AUDIO_DATA",
                    message="No audio data available. Call start() and stop() first, or call save() while recording."
                )
            audio_data = self._last_audio
            sr = self._sample_rate

        if len(audio_data) == 0:
            raise RecordingError(
                code="EMPTY_RECORDING",
                message="No audio data to save"
            )

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            save_audio_file(audio_data, str(path), sr)
            logger.info("Recording saved to %s", path)
            return str(path)
        except Exception as e:
            logger.exception("Failed to save recording")
            raise RecordingError(
                code="SAVE_FAILED",
                message="Failed to save recording",
                details=str(e)
            )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._is_recording:
            self.stop()


def record_fixed_duration(
    device_index: int,
    duration_sec: float,
    sample_rate: int = 16000,
    channels: int = 1
) -> Tuple[np.ndarray, int]:
    """
    Record audio for a fixed duration and return the data.

    Convenience function for simple blocking recordings.

    Args:
        device_index: Microphone device index.
        duration_sec: Recording duration in seconds.
        sample_rate: Sample rate in Hz (default 16000).
        channels: Number of channels (default 1).

    Returns:
        Tuple of (audio_data, sample_rate).

    Raises:
        RecordingError: If recording fails.
    """
    session = RecordingSession(device_index, sample_rate, channels)
    session.start()
    time.sleep(duration_sec)
    return session.stop()


def validate_recording(
    audio_data: np.ndarray,
    sample_rate: int = 16000,
    min_duration_sec: float = 0.5
) -> Tuple[bool, Optional[str]]:
    """
    Validate that a recording contains usable audio.

    Args:
        audio_data: Audio array (float32), can be 1D (mono) or 2D (n, channels).
        sample_rate: Sample rate in Hz (default 16000).
        min_duration_sec: Minimum duration to be valid.

    Returns:
        (is_valid, error_message).
    """
    if audio_data is None or audio_data.size == 0:
        return False, "Recording is empty"

    # Handle both 1D (mono) and 2D (multi-channel) arrays
    n_samples = audio_data.shape[0]
    duration = n_samples / sample_rate
    if duration < min_duration_sec:
        return False, f"Recording too short: {duration:.2f}s (minimum {min_duration_sec}s)"

    # For stereo, check RMS across all channels
    rms = np.sqrt(np.mean(audio_data ** 2))
    if rms < 1e-4:
        return False, "Recording appears to be silent"

    return True, None