"""Standalone test for Speech-to-Text functionality."""

import sys
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voice_module.stt import FasterWhisperSTT, STTError
from voice_module.config import DEFAULT_STT_CONFIG

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def run_stt_test(audio_path: str) -> None:
    """Test transcription with a given audio file."""
    print(f"\n{'='*60}")
    print(f"Testing STT with: {audio_path}")
    print(f"{'='*60}")

    stt = FasterWhisperSTT(DEFAULT_STT_CONFIG)

    try:
        result = stt.transcribe_file(audio_path)

        print(f"\nLanguage: {result.language} (probability: {result.language_probability:.3f})")
        print(f"Duration: {result.duration:.2f}s")
        print(f"Segments: {len(result.segments)}")
        print(f"\nFull Text:")
        print(f"  {result.text}")
        print(f"\nSegments:")
        for seg in result.segments:
            print(f"  [{seg.start:.2f}s - {seg.end:.2f}s] (p={seg.probability:.3f}): {seg.text}")

    except STTError as e:
        print(f"\nSTT Error [{e.code}]: {e.message}")
        if e.details:
            print(f"  Details: {e.details}")
        sys.exit(1)
    except Exception as e:
        logger.exception("Unexpected error")
        print(f"\nUnexpected error: {e}")
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m tests.test_stt <audio_file>")
        print("\nSupported formats: .wav, .mp3, .m4a, .flac, .ogg, .aac, .wma")
        print("\nExample: python -m tests.test_stt sample.wav")
        sys.exit(1)

    audio_file = sys.argv[1]
    run_stt_test(audio_file)


if __name__ == "__main__":
    main()
