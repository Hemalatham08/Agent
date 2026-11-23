"""Thread-safe voice control state machine (Stage 4).

Coordinates the Stage 3 microphone recorder with a TTS player while enforcing:

* recording and playback never run simultaneously;
* duplicate starts are no-ops;
* stop/cleanup failures never leave the controller stuck in a busy state.

Hardware and models are injected, so automated tests use fakes only.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional, Protocol, Tuple

import numpy as np

from .states import VoiceControlError, VoiceState
from .tts_player import KokoroTTSPlayer

logger = logging.getLogger(__name__)

AudioResult = Tuple[np.ndarray, int]


class RecorderProtocol(Protocol):
    """Minimal recorder interface used by the controller (Stage 3 compatible)."""

    @property
    def is_recording(self) -> bool: ...

    def start(self) -> None: ...

    def stop(self) -> AudioResult: ...


class VoiceController:
    """State machine that owns listening and speaking.

    Example:
        controller = VoiceController(device_index=0)
        controller.start_listening()
        audio, sample_rate = controller.stop_listening()
        controller.begin_processing()
        controller.finish_processing()
        controller.start_speaking("Hello")
        controller.stop_speaking()
        controller.return_to_idle()
    """

    def __init__(
        self,
        recorder_factory: Optional[Callable[[], RecorderProtocol]] = None,
        tts_player=None,
        device_index: Optional[int] = None,
    ):
        self._recorder_factory = recorder_factory
        self._device_index = device_index
        self._player = tts_player if tts_player is not None else KokoroTTSPlayer()

        self._lock = threading.RLock()
        self._state = VoiceState.IDLE
        self._recorder: Optional[RecorderProtocol] = None
        self._last_error: Optional[VoiceControlError] = None
        self._token = 0

    @property
    def state(self) -> VoiceState:
        """Current voice state."""
        with self._lock:
            return self._state

    @property
    def last_error(self) -> Optional[VoiceControlError]:
        """Most recent error, cleared when returning to idle."""
        with self._lock:
            return self._last_error

    @property
    def is_busy(self) -> bool:
        """Whether the controller is actively listening, processing, or speaking."""
        with self._lock:
            return self._state in (
                VoiceState.LISTENING,
                VoiceState.PROCESSING,
                VoiceState.SPEAKING,
            )

    def _default_recorder_factory(self) -> RecorderProtocol:
        from ..audio import RecordingSession, get_default_microphone

        device_index = self._device_index
        if device_index is None:
            microphone = get_default_microphone()
            if microphone is None:
                raise VoiceControlError(
                    "NO_MICROPHONE",
                    "No default microphone is available",
                )
            device_index = microphone.index

        return RecordingSession(device_index=device_index)

    def _fail_locked(self, error: VoiceControlError) -> None:
        self._last_error = error
        self._state = VoiceState.ERROR

    def _close_recorder_locked(self, recorder: Optional[RecorderProtocol]) -> None:
        if recorder is None:
            return
        try:
            if getattr(recorder, "is_recording", False):
                recorder.stop()
        except Exception:
            logger.exception("Failed to clean up recorder")

    def _stop_player(self) -> None:
        try:
            self._player.stop()
        except Exception:
            logger.exception("Failed to stop TTS player")

    def start_listening(self) -> bool:
        """Start microphone recording.

        Returns:
            True if recording started, False if already listening.

        Raises:
            VoiceControlError: If speaking/processing, or if recording fails.
        """
        with self._lock:
            if self._state is VoiceState.LISTENING:
                return False
            if self._state in (VoiceState.SPEAKING, VoiceState.PROCESSING):
                raise VoiceControlError(
                    "BUSY",
                    f"Cannot start listening while {self._state.value}",
                )

            self._last_error = None
            self._token += 1

            self._stop_player()
            self._close_recorder_locked(self._recorder)
            self._recorder = None

            recorder = None
            try:
                factory = self._recorder_factory or self._default_recorder_factory
                recorder = factory()
                recorder.start()
            except VoiceControlError as exc:
                self._close_recorder_locked(recorder)
                self._fail_locked(exc)
                raise
            except Exception as exc:
                self._close_recorder_locked(recorder)
                error = VoiceControlError(
                    "START_FAILED",
                    "Failed to start listening",
                    str(exc),
                )
                self._fail_locked(error)
                raise error from exc

            self._recorder = recorder
            self._state = VoiceState.LISTENING
            return True

    def stop_listening(self) -> Optional[AudioResult]:
        """Stop recording and return captured audio.

        Returns:
            ``(audio, sample_rate)`` if recording was active, otherwise None.

        Stop failures set ERROR but do not raise, so interruption paths stay safe.
        """
        with self._lock:
            if self._state is not VoiceState.LISTENING:
                return None

            recorder = self._recorder
            self._recorder = None

            try:
                result = recorder.stop() if recorder is not None else None
            except Exception as exc:
                self._close_recorder_locked(recorder)
                self._fail_locked(
                    VoiceControlError(
                        "STOP_FAILED",
                        "Failed to stop listening",
                        str(exc),
                    )
                )
                return None

            self._close_recorder_locked(recorder)
            self._state = VoiceState.IDLE
            return result

    def start_speaking(self, text: str) -> bool:
        """Start speech playback.

        Returns:
            True if playback started, False if already speaking.

        Raises:
            VoiceControlError: If listening/processing, text is empty, or
                playback fails to start.
        """
        with self._lock:
            if self._state is VoiceState.SPEAKING:
                return False
            if self._state in (VoiceState.LISTENING, VoiceState.PROCESSING):
                raise VoiceControlError(
                    "BUSY",
                    f"Cannot start speaking while {self._state.value}",
                )
            if not isinstance(text, str) or not text.strip():
                raise VoiceControlError(
                    "INVALID_TEXT",
                    "Text to speak must be a non-empty string",
                )

            self._close_recorder_locked(self._recorder)
            self._recorder = None
            self._last_error = None
            self._token += 1
            token = self._token
            self._state = VoiceState.SPEAKING

        try:
            self._player.speak(
                text,
                on_complete=lambda: self._on_playback_complete(token),
            )
        except Exception as exc:
            with self._lock:
                is_current = self._token == token
                if is_current:
                    self._stop_player()
            if not is_current:
                return False

            error = VoiceControlError(
                "SPEAK_FAILED",
                "Failed to start speech playback",
                str(exc),
            )
            with self._lock:
                self._fail_locked(error)
            raise error from exc

        with self._lock:
            cancelled = self._token != token or self._state is not VoiceState.SPEAKING

        if cancelled:
            self._stop_player()

        return True

    def stop_speaking(self) -> bool:
        """Stop speech playback immediately.

        Returns:
            True if playback was active, otherwise False.

        Stop failures set ERROR but do not raise, so interruption paths stay safe.
        """
        with self._lock:
            was_speaking = self._state is VoiceState.SPEAKING
            self._token += 1
            if was_speaking:
                self._state = VoiceState.IDLE

        try:
            self._player.stop()
        except Exception as exc:
            logger.exception("Failed to stop TTS player")
            if was_speaking:
                with self._lock:
                    self._fail_locked(
                        VoiceControlError(
                            "STOP_FAILED",
                            "Failed to stop speech playback",
                            str(exc),
                        )
                    )
            return was_speaking

        return was_speaking

    def _on_playback_complete(self, token: int) -> None:
        with self._lock:
            if token == self._token and self._state is VoiceState.SPEAKING:
                self._token += 1
                self._state = VoiceState.IDLE

    def begin_processing(self) -> bool:
        """Mark the controller as processing (e.g. while STT runs).

        Returns:
            True if the state changed to PROCESSING, False if already processing.

        Raises:
            VoiceControlError: If listening/speaking, or recovering from ERROR.
        """
        with self._lock:
            if self._state is VoiceState.PROCESSING:
                return False
            if self._state in (VoiceState.LISTENING, VoiceState.SPEAKING):
                raise VoiceControlError(
                    "BUSY",
                    f"Cannot begin processing while {self._state.value}",
                )
            if self._state is VoiceState.ERROR:
                raise VoiceControlError(
                    "INVALID_STATE",
                    "Return to idle before beginning processing",
                )

            self._last_error = None
            self._state = VoiceState.PROCESSING
            return True

    def finish_processing(self) -> bool:
        """Finish processing and return to IDLE.

        Returns:
            True if the state changed, False if not processing.
        """
        with self._lock:
            if self._state is not VoiceState.PROCESSING:
                return False
            self._state = VoiceState.IDLE
            return True

    def stop_all(self) -> None:
        """Stop listening and playback, then enter STOPPED."""
        with self._lock:
            self._close_recorder_locked(self._recorder)
            self._recorder = None
            self._token += 1
            self._state = VoiceState.STOPPED

        self._stop_player()

    def return_to_idle(self) -> None:
        """Safely stop all activity and reset to IDLE."""
        with self._lock:
            self._close_recorder_locked(self._recorder)
            self._recorder = None
            self._token += 1
            self._state = VoiceState.IDLE
            self._last_error = None

        self._stop_player()

    def __enter__(self) -> "VoiceController":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.return_to_idle()
        return False
