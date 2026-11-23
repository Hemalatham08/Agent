"""Real end-to-end integration test for Stage 4 voice controls.

Runs the real ``VoiceController`` with the real ``KokoroTTSPlayer`` and plays a
short message through the computer's default output device. No microphone and
no Whisper are used.

Because ``.venv_tts`` does not include pytest, run this as a module:

    .venv_tts\\Scripts\\python.exe -m tests.test_voice_integration

The test also runs under pytest when ``kokoro_onnx`` and ``sounddevice`` are
available in the active interpreter.
"""

import importlib.util
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice_module.control import KokoroTTSPlayer, VoiceController, VoiceState

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = BASE_DIR / "models" / "kokoro-v1.0.int8.onnx"
VOICES_PATH = BASE_DIR / "models" / "voices-v1.0.bin"
VOICE = "af_heart"
MESSAGE = (
    "Hello! This is the ABC Fasteners voice assistant. "
    "The voice controller integration test is successful."
)
MAX_WAIT_SECONDS = 60.0


class CountingKokoroTTSPlayer(KokoroTTSPlayer):
    """Real Kokoro player that counts completion callbacks."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.completion_count = 0
        self.synthesized_duration = 0.0
        self.synthesized_sample_rate = 0
        self._count_lock = threading.Lock()

    def _synthesize(self, text):
        audio, sample_rate = super()._synthesize(text)
        self.synthesized_sample_rate = sample_rate
        self.synthesized_duration = len(audio) / sample_rate if sample_rate else 0.0
        return audio, sample_rate

    def speak(self, text, on_complete=None):
        def wrapped_complete():
            with self._count_lock:
                self.completion_count += 1
            if on_complete is not None:
                on_complete()

        super().speak(text, wrapped_complete)


def _forbid_microphone(*args, **kwargs):
    raise AssertionError("Microphone must not be used by the integration test")


def test_voice_controller_kokoro_integration():
    if importlib.util.find_spec("kokoro_onnx") is None:
        raise unittest.SkipTest("kokoro_onnx is not available in this interpreter")
    if importlib.util.find_spec("sounddevice") is None:
        raise unittest.SkipTest("sounddevice is not available in this interpreter")

    import sounddevice as sd

    assert MODEL_PATH.is_file(), f"Kokoro model not found: {MODEL_PATH}"
    assert VOICES_PATH.is_file(), f"Kokoro voices not found: {VOICES_PATH}"

    output_device = sd.query_devices(3)
    print(f"Output device: {output_device.get('name', '<unknown>')}")
    print(f"Output default sample rate: {output_device.get('default_samplerate')} Hz")
    print(f"Model: {MODEL_PATH}")
    print(f"Voice: {VOICE}")

    player = CountingKokoroTTSPlayer(
        model_path=str(MODEL_PATH),
        voices_path=str(VOICES_PATH),
        voice=VOICE,
    )
    controller = VoiceController(
        recorder_factory=_forbid_microphone,
        tts_player=player,
    )

    try:
        started = controller.start_speaking(MESSAGE)
        state_after_start = controller.state
        playing_after_start = player.is_playing

        print(f"start_speaking returned: {started}")
        print(f"State after start: {state_after_start.value}")
        print(f"Player is_playing after start: {playing_after_start}")
        print(
            "Synthesized audio: "
            f"{player.synthesized_duration:.2f}s @ {player.synthesized_sample_rate} Hz"
        )

        assert started is True
        assert state_after_start is VoiceState.SPEAKING
        assert playing_after_start is True
        assert player.synthesized_duration > 0.0

        playback_thread = player._thread
        deadline = time.monotonic() + MAX_WAIT_SECONDS
        saw_speaking = state_after_start is VoiceState.SPEAKING
        while controller.state is VoiceState.SPEAKING and time.monotonic() < deadline:
            time.sleep(0.05)
            if playback_thread is not None and not playback_thread.is_alive():
                time.sleep(0.1)
                break

        print(f"Final state: {controller.state.value}")
        print(f"Completion callbacks: {player.completion_count}")

        assert saw_speaking
        assert controller.state is VoiceState.IDLE, (
            f"Expected IDLE after playback, got {controller.state.value} "
            f"(last_error={controller.last_error}); check the default speaker "
            "and its supported sample rate"
        )
        assert player.is_playing is False
        assert controller.last_error is None
        assert player.completion_count == 1

        print("PASS: real Kokoro speech played and controller returned to IDLE")
    finally:
        controller.return_to_idle()
        player.stop()
        print(f"Post-cleanup state: {controller.state.value}")
        print(f"Post-cleanup completion callbacks: {player.completion_count}")


if __name__ == "__main__":
    test_voice_controller_kokoro_integration()





