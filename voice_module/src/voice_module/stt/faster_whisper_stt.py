"""Faster-Whisper Speech-to-Text implementation."""

import logging
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel

from ..config import DEFAULT_STT_CONFIG, STTConfig
from .models import Segment, TranscriptionResult, STTError

logger = logging.getLogger(__name__)


class FasterWhisperSTT:
    """Wrapper for Faster-Whisper transcription."""

    def __init__(self, config: Optional[STTConfig] = None):
        self.config = config or DEFAULT_STT_CONFIG
        self._model: Optional[WhisperModel] = None

    def _load_model(self) -> WhisperModel:
        """Load or return cached Whisper model."""
        if self._model is None:
            logger.info(
                "Loading Whisper model: %s (device=%s, compute_type=%s)",
                self.config.model_size, self.config.device, self.config.compute_type
            )
            self._model = WhisperModel(
                self.config.model_size,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        return self._model

    def transcribe_file(self, audio_path: str) -> TranscriptionResult:
        """
        Transcribe an audio file to text.

        Args:
            audio_path: Path to audio file (wav, mp3, m4a, flac, etc.)

        Returns:
            TranscriptionResult with text, language, segments, and metadata.

        Raises:
            STTError: If audio file is invalid or transcription fails.
        """
        path = Path(audio_path)
        if not path.exists():
            raise STTError(
                code="FILE_NOT_FOUND",
                message=f"Audio file not found: {audio_path}"
            )

        if not path.is_file():
            raise STTError(
                code="NOT_A_FILE",
                message=f"Path is not a file: {audio_path}"
            )

        try:
            model = self._load_model()
            segments, info = model.transcribe(
                str(path),
                language=self.config.language,
                beam_size=self.config.beam_size,
                vad_filter=self.config.vad_filter,
                vad_parameters=self.config.vad_parameters,
            )

            segment_list = []
            full_text_parts = []
            for segment in segments:
                seg = Segment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                    probability=segment.avg_logprob
                )
                segment_list.append(seg)
                full_text_parts.append(seg.text)

            return TranscriptionResult(
                text=" ".join(full_text_parts).strip(),
                language=info.language,
                language_probability=info.language_probability,
                segments=segment_list,
                duration=info.duration
            )

        except STTError:
            raise
        except Exception as e:
            logger.exception("Transcription failed")
            raise STTError(
                code="TRANSCRIPTION_FAILED",
                message="Failed to transcribe audio",
                details=str(e)
            )

    def transcribe_audio(self, audio_data: bytes, sample_rate: int = 16000) -> TranscriptionResult:
        """
        Transcribe raw audio bytes (16-bit PCM, mono).

        Args:
            audio_data: Raw 16-bit PCM audio bytes at sample_rate.
            sample_rate: Sample rate of audio data (default 16000).

        Returns:
            TranscriptionResult with text, language, segments, and metadata.

        Raises:
            STTError: If transcription fails.
        """
        import tempfile
        import soundfile as sf
        import numpy as np

        try:
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                sf.write(tmp.name, audio_array, sample_rate)
                tmp_path = tmp.name

            return self.transcribe_file(tmp_path)

        except STTError:
            raise
        except Exception as e:
            logger.exception("Audio transcription failed")
            raise STTError(
                code="AUDIO_PROCESSING_FAILED",
                message="Failed to process audio data",
                details=str(e)
            )
        finally:
            if 'tmp_path' in locals():
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass