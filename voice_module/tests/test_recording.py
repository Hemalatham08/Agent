"""Tests for audio recording (mocked and manual)."""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from voice_module.audio import (
    RecordingSession,
    record_fixed_duration,
    validate_recording,
    RecordingError,
)
from voice_module.utils.audio import save_audio_file


class MockStream:
    """Mock sounddevice InputStream that captures and can invoke the callback."""

    def __init__(self, *, samplerate=16000, channels=1, dtype="int16", callback=None, device=None, **kwargs):
        self.started = False
        self.stopped = False
        self.closed = False
        self._callback = callback
        self._sample_rate = samplerate
        self._channels = channels
        self._dtype = dtype
        self._device = device
        self._callback_thread = None

    def start(self):
        self.started = True
        # Simulate callback being called by sounddevice in a background thread
        if self._callback:
            def run_callbacks():
                for _ in range(3):
                    if not self.started:  # Allow early termination
                        break
                    indata = np.random.randint(-1000, 1000, (1024, self._channels), dtype=np.int16)
                    self._callback(indata, 1024, None, MagicMock())
                    time.sleep(0.01)  # Small delay between chunks
            
            self._callback_thread = threading.Thread(target=run_callbacks, daemon=True)
            self._callback_thread.start()

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True
        if self._callback_thread and self._callback_thread.is_alive():
            self._callback_thread.join(timeout=0.5)


def test_recording_session_start_stop():
    """Test basic start/stop recording cycle with callback simulation."""
    with patch("sounddevice.InputStream", side_effect=MockStream) as mock_class:
        session = RecordingSession(device_index=0, sample_rate=16000)
        session.start()
        mock_stream = session._stream  # Capture before stop() sets it to None
        # Give the mock callback time to populate the buffer
        time.sleep(0.1)
        audio_data, sr = session.stop()

    assert mock_stream.started
    assert mock_stream.stopped
    assert mock_stream.closed
    assert sr == 16000
    assert isinstance(audio_data, np.ndarray)
    assert audio_data.dtype == np.float32
    assert len(audio_data) > 0


def test_recording_session_double_start_raises():
    """Test that starting twice raises error."""
    with patch("sounddevice.InputStream", side_effect=MockStream):
        session = RecordingSession(device_index=0)
        session.start()
        with pytest.raises(RecordingError) as exc:
            session.start()
        assert exc.value.code == "ALREADY_RECORDING"


def test_recording_session_stop_without_start_raises():
    """Test that stopping without starting raises error."""
    session = RecordingSession(device_index=0)
    with pytest.raises(RecordingError) as exc:
        session.stop()
    assert exc.value.code == "NOT_RECORDING"


def test_recording_session_context_manager():
    """Test RecordingSession as context manager."""
    with patch("sounddevice.InputStream", side_effect=MockStream):
        with RecordingSession(device_index=0) as session:
            assert session.is_recording
            time.sleep(0.1)

    assert not session.is_recording


def test_record_fixed_duration():
    """Test record_fixed_duration convenience function."""
    with patch("sounddevice.InputStream", side_effect=MockStream):
        audio_data, sr = record_fixed_duration(device_index=0, duration_sec=0.2)

    assert sr == 16000
    assert isinstance(audio_data, np.ndarray)
    assert audio_data.dtype == np.float32
    assert len(audio_data) > 0


def test_validate_recording_empty():
    """Test validate_recording rejects empty array."""
    empty = np.array([], dtype=np.float32)
    valid, error = validate_recording(empty)
    assert valid is False
    assert "empty" in error.lower()


def test_validate_recording_too_short():
    """Test validate_recording rejects too short audio."""
    short = np.zeros(1600, dtype=np.float32)
    valid, error = validate_recording(short, min_duration_sec=0.5)
    assert valid is False
    assert "short" in error.lower()


def test_validate_recording_silent():
    """Test validate_recording rejects silent audio."""
    silent = np.zeros(16000, dtype=np.float32)
    valid, error = validate_recording(silent, min_duration_sec=0.5)
    assert valid is False
    assert "silent" in error.lower()


def test_validate_recording_valid():
    """Test validate_recording accepts valid audio."""
    audio = np.random.randn(16000).astype(np.float32) * 0.1
    valid, error = validate_recording(audio, min_duration_sec=0.5)
    assert valid is True
    assert error is None


def test_validate_recording_stereo():
    """Test validate_recording accepts stereo audio (duration from first dim)."""
    audio = np.random.randn(16000, 2).astype(np.float32) * 0.1
    valid, error = validate_recording(audio, min_duration_sec=0.5)
    assert valid is True
    assert error is None


def test_validate_recording_mono_2d():
    """Test validate_recording accepts 2D mono audio (n, 1)."""
    audio = np.random.randn(16000, 1).astype(np.float32) * 0.1
    valid, error = validate_recording(audio, min_duration_sec=0.5)
    assert valid is True
    assert error is None


def test_recording_save(tmp_path):
    """Test saving recording to file."""
    with patch("sounddevice.InputStream", side_effect=MockStream):
        session = RecordingSession(device_index=0)
        session.start()
        time.sleep(0.1)
        filepath = session.save(str(tmp_path / "test_recording.wav"))

    assert Path(filepath).exists()
    assert Path(filepath).suffix == ".wav"


def manual_microphone_recording_test():
    """
    Manual test: Record 5 seconds from default microphone.

    Run with: python -m tests.test_recording --manual
    """
    import argparse

    parser = argparse.ArgumentParser(description="Manual microphone recording test")
    parser.add_argument("--device", type=int, default=None, help="Device index (default: auto)")
    parser.add_argument("--duration", type=float, default=5.0, help="Recording duration in seconds")
    parser.add_argument("--output", type=str, default=None, help="Output file path")
    args = parser.parse_args()

    from voice_module.audio import list_microphones, get_default_microphone, validate_device

    print("=" * 60)
    print("Manual Microphone Recording Test")
    print("=" * 60)

    mics = list_microphones()
    print(f"\nAvailable microphones ({len(mics)}):")
    for mic in mics:
        print(f"  [{mic.index}] {mic.name} ({mic.max_input_channels}ch, {mic.default_sample_rate:.0f}Hz) [{mic.hostapi}]")

    if args.device is not None:
        device_idx = args.device
        if not validate_device(device_idx):
            print(f"\nError: Device {device_idx} is not a valid input device")
            sys.exit(1)
    else:
        default = get_default_microphone()
        if default is None:
            print("\nError: No default microphone found")
            sys.exit(1)
        device_idx = default.index
        print(f"\nUsing default microphone: [{device_idx}] {default.name}")

    output_path = args.output or str(Path(__file__).parent.parent / "recordings" / f"manual_test_{int(time.time())}.wav")

    print(f"\nRecording for {args.duration} seconds...")
    print("Speak into your microphone now!")

    try:
        session = RecordingSession(device_index=device_idx, sample_rate=16000)
        session.start()
        time.sleep(args.duration)
        filepath = session.save(output_path)
    except RecordingError as e:
        print(f"\nRecording error [{e.code}]: {e.message}")
        if e.details:
            print(f"  Details: {e.details}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nRecording interrupted by user")
        session.stop()
        sys.exit(1)

    print(f"\nRecording saved to: {filepath}")
    print(f"Duration: {session.duration:.2f}s")

    # Validate
    import soundfile as sf
    audio, sr = sf.read(filepath)
    print(f"File sample rate: {sr}Hz")
    print(f"File channels: {audio.ndim if audio.ndim > 1 else 1}")
    print(f"File duration: {len(audio) / sr:.2f}s")

    valid, error = validate_recording(audio if audio.ndim == 1 else audio[:, 0])
    if valid:
        print("Validation: PASSED - Recording is usable for STT")
    else:
        print(f"Validation: FAILED - {error}")

    # Test STT compatibility
    print("\nTesting STT compatibility...")
    try:
        from voice_module.stt import FasterWhisperSTT
        from voice_module.config import DEFAULT_STT_CONFIG

        stt = FasterWhisperSTT(DEFAULT_STT_CONFIG)
        print("STT model loaded, transcribing...")
        result = stt.transcribe_file(filepath)
        print(f"Transcription: {result.text}")
    except Exception as e:
        print(f"STT test skipped/error: {e}")


if __name__ == "__main__":
    import sys
    if "--manual" in sys.argv:
        sys.argv.remove("--manual")
        manual_microphone_recording_test()
    else:
        pytest.main([__file__, "-v"])