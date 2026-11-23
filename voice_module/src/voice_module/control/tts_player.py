"""Interruptible TTS playback adapter (Stage 4).

Stage 2 exposed Kokoro-82M only through ``tests/test_tts.py``; there was no
importable module. This adapter wraps that exact usage behind a small
interface and adds interruptible playback.

Both ``kokoro_onnx`` and ``sounddevice`` are imported lazily, so importing this
module does not load a model, require a specific virtual environment, or touch
audio hardware.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

Audio = Tuple[np.ndarray, int]

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODEL_PATH = _PROJECT_ROOT / "models" / "kokoro-v1.0.int8.onnx"
_DEFAULT_VOICES_PATH = _PROJECT_ROOT / "models" / "voices-v1.0.bin"


class KokoroTTSPlayer:
    """Synthesize with Kokoro-82M and play through sounddevice.

    Args:
        model_path: Path to the Kokoro ONNX model (defaults to ``models/``).
        voices_path: Path to the Kokoro voices file (defaults to ``models/``).
        voice: Kokoro voice name.
        speed: Speech speed.
        lang: Kokoro language code.
        chunk_ms: Playback chunk size in milliseconds. Smaller values allow
            faster interruption of playback.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        voices_path: Optional[str] = None,
        voice: str = "af_heart",
        speed: float = 0.9,
        lang: str = "en-us",
        chunk_ms: int = 60,
    ):
        self._model_path = Path(model_path) if model_path else _DEFAULT_MODEL_PATH
        self._voices_path = Path(voices_path) if voices_path else _DEFAULT_VOICES_PATH
        self._voice = voice
        self._speed = speed
        self._lang = lang
        self._chunk_ms = max(10, int(chunk_ms))

        self._kokoro = None
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_playing = False
        self._speak_generation = 0
        self._playback_token = 0

    @property
    def is_playing(self) -> bool:
        """Whether audio playback is currently active."""
        with self._lock:
            return self._is_playing

    def _load_engine(self):
        if not self._model_path.is_file():
            raise FileNotFoundError(f"Kokoro model not found: {self._model_path}")
        if not self._voices_path.is_file():
            raise FileNotFoundError(f"Kokoro voices file not found: {self._voices_path}")

        try:
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise RuntimeError(
                "kokoro_onnx is not installed. Run TTS in the .venv_tts environment."
            ) from exc

        logger.info("Loading Kokoro model: %s", self._model_path)
        self._kokoro = Kokoro(str(self._model_path), str(self._voices_path))
        return self._kokoro

    def _synthesize(self, text: str) -> Audio:
        engine = self._kokoro if self._kokoro is not None else self._load_engine()
        audio, sample_rate = engine.create(
            text,
            voice=self._voice,
            speed=self._speed,
            lang=self._lang,
        )
        return np.asarray(audio, dtype=np.float32).reshape(-1), int(sample_rate)

    def speak(
        self,
        text: str,
        on_complete: Optional[Callable[[], None]] = None,
    ) -> None:
        """Synthesize ``text`` and start playback in a background thread.

        Synthesis is synchronous so errors propagate to the caller. Playback is
        asynchronous and can be interrupted with :meth:`stop`.

        Raises:
            ValueError: If ``text`` is empty.
            RuntimeError/FileNotFoundError: If synthesis cannot be performed.
        """
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        with self._lock:
            self._speak_generation += 1
            generation = self._speak_generation
            self._stop_event.clear()

        audio, sample_rate = self._synthesize(text)

        with self._lock:
            if generation != self._speak_generation or self._stop_event.is_set():
                return
            self._playback_token += 1
            token = self._playback_token
            self._is_playing = True
            self._thread = threading.Thread(
                target=self._playback_loop,
                args=(audio, sample_rate, token, on_complete),
                name="voice-tts-playback",
                daemon=True,
            )
            self._thread.start()

    def _playback_loop(
        self,
        audio: np.ndarray,
        sample_rate: int,
        token: int,
        on_complete: Optional[Callable[[], None]],
    ) -> None:
        stream = None
        playback_succeeded = False
        try:
            import sounddevice as sd

            stream = sd.OutputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=3,
            )
            stream.start()

            chunk_size = max(1, int(sample_rate * self._chunk_ms / 1000.0))
            for offset in range(0, len(audio), chunk_size):
                if self._stop_event.is_set() or token != self._playback_token:
                    break
                block = audio[offset:offset + chunk_size]
                if block.ndim == 1:
                    block = block.reshape(-1, 1)
                stream.write(np.ascontiguousarray(block, dtype=np.float32))

            playback_succeeded = True
        except Exception:
            logger.exception("TTS playback failed")
        finally:
            if stream is not None:
                try:
                    stream.stop()
                except Exception:
                    logger.exception("Failed to stop TTS output stream")
                try:
                    stream.close()
                except Exception:
                    logger.exception("Failed to close TTS output stream")

            with self._lock:
                if token == self._playback_token:
                    self._is_playing = False

            cancelled = self._stop_event.is_set() or token != self._playback_token
            if playback_succeeded and not cancelled and on_complete is not None:
                try:
                    on_complete()
                except Exception:
                    logger.exception("TTS completion callback failed")

    def stop(self) -> None:
        """Stop playback immediately and invalidate any in-flight synthesis."""
        with self._lock:
            self._speak_generation += 1
            self._playback_token += 1
            self._stop_event.set()
            self._is_playing = False
            thread = self._thread

        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)

