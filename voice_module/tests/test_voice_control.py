"""Tests for the Stage 4 voice control layer (all hardware/models mocked)."""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from voice_module.control import (
    KokoroTTSPlayer,
    VoiceControlError,
    VoiceController,
    VoiceState,
)


class FakeRecorder:
    """Fake Stage 3 recorder with controllable failures."""

    def __init__(self, fail_start=False, fail_stop=False):
        self.is_recording = False
        self.start_count = 0
        self.stop_count = 0
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.audio = np.full(1600, 0.1, dtype=np.float32)
        self.sample_rate = 16000

    def start(self):
        self.start_count += 1
        if self.fail_start:
            raise RuntimeError("microphone open failed")
        self.is_recording = True

    def stop(self):
        self.stop_count += 1
        self.is_recording = False
        if self.fail_stop:
            raise RuntimeError("microphone close failed")
        return self.audio, self.sample_rate


class FakeRecorderFactory:
    """Factory that records every created recorder and can force failures."""

    def __init__(self):
        self.created = []
        self.fail_start = False
        self.fail_stop = False

    def __call__(self):
        recorder = FakeRecorder(
            fail_start=self.fail_start,
            fail_stop=self.fail_stop,
        )
        self.created.append(recorder)
        return recorder


class FakePlayer:
    """Fake TTS player whose playback completion is manually triggered."""

    def __init__(self):
        self.speak_calls = []
        self.stop_calls = 0
        self.is_playing = False
        self.fail_speak = False
        self.fail_stop = False
        self._on_complete = None

    def speak(self, text, on_complete=None):
        if self.fail_speak:
            raise RuntimeError("TTS synthesis failed")
        self.speak_calls.append(text)
        self._on_complete = on_complete
        self.is_playing = True

    def stop(self):
        self.stop_calls += 1
        self._on_complete = None
        self.is_playing = False
        if self.fail_stop:
            raise RuntimeError("TTS stop failed")

    def complete(self):
        callback = self._on_complete
        self._on_complete = None
        self.is_playing = False
        if callback is not None:
            callback()


def make_controller():
    factory = FakeRecorderFactory()
    player = FakePlayer()
    controller = VoiceController(recorder_factory=factory, tts_player=player)
    return controller, factory, player


def test_initial_state_is_idle():
    controller, _, _ = make_controller()

    assert controller.state is VoiceState.IDLE
    assert controller.last_error is None
    assert controller.is_busy is False


def test_state_enum_values():
    assert VoiceState.IDLE.value == "idle"
    assert VoiceState.LISTENING.value == "listening"
    assert VoiceState.PROCESSING.value == "processing"
    assert VoiceState.SPEAKING.value == "speaking"
    assert VoiceState.STOPPED.value == "stopped"
    assert VoiceState.ERROR.value == "error"


def test_start_listening_transitions_to_listening():
    controller, factory, _ = make_controller()

    assert controller.start_listening() is True
    assert controller.state is VoiceState.LISTENING
    assert controller.is_busy is True
    assert len(factory.created) == 1
    assert factory.created[0].start_count == 1
    assert factory.created[0].is_recording is True


def test_stop_listening_returns_audio_and_returns_to_idle():
    controller, factory, _ = make_controller()
    controller.start_listening()

    result = controller.stop_listening()

    assert result is not None
    audio, sample_rate = result
    assert isinstance(audio, np.ndarray)
    assert sample_rate == 16000
    assert controller.state is VoiceState.IDLE
    assert factory.created[0].is_recording is False


def test_duplicate_start_listening_is_noop():
    controller, factory, _ = make_controller()

    assert controller.start_listening() is True
    assert controller.start_listening() is False

    assert len(factory.created) == 1
    assert factory.created[0].start_count == 1
    assert controller.state is VoiceState.LISTENING


def test_concurrent_start_listening_starts_once():
    controller, factory, _ = make_controller()
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(controller.start_listening())

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert sorted(results) == [False, True]
    assert len(factory.created) == 1
    assert factory.created[0].start_count == 1


def test_stop_listening_when_idle_is_noop():
    controller, _, _ = make_controller()

    assert controller.stop_listening() is None
    assert controller.state is VoiceState.IDLE


def test_start_speaking_transitions_to_speaking():
    controller, _, player = make_controller()

    assert controller.start_speaking("Hello there") is True

    assert controller.state is VoiceState.SPEAKING
    assert controller.is_busy is True
    assert player.speak_calls == ["Hello there"]


def test_stop_speaking_returns_to_idle():
    controller, _, player = make_controller()
    controller.start_speaking("Hello")

    assert controller.stop_speaking() is True

    assert controller.state is VoiceState.IDLE
    assert player.stop_calls >= 1
    assert player.is_playing is False


def test_stop_speaking_when_idle_is_noop():
    controller, _, _ = make_controller()

    assert controller.stop_speaking() is False
    assert controller.state is VoiceState.IDLE


def test_duplicate_start_speaking_is_noop():
    controller, _, player = make_controller()

    assert controller.start_speaking("First") is True
    assert controller.start_speaking("Second") is False

    assert player.speak_calls == ["First"]
    assert controller.state is VoiceState.SPEAKING


def test_playback_completion_returns_to_idle():
    controller, _, player = make_controller()
    controller.start_speaking("Done soon")

    player.complete()

    assert controller.state is VoiceState.IDLE


def test_stale_completion_after_stop_does_not_change_state():
    controller, _, player = make_controller()
    controller.start_speaking("First")
    stale_callback = player._on_complete

    controller.stop_speaking()
    controller.start_speaking("Second")
    stale_callback()

    assert controller.state is VoiceState.SPEAKING
    assert player.speak_calls == ["First", "Second"]


def test_start_speaking_empty_text_rejected():
    controller, _, player = make_controller()

    with pytest.raises(VoiceControlError) as exc:
        controller.start_speaking("   ")

    assert exc.value.code == "INVALID_TEXT"
    assert controller.state is VoiceState.IDLE
    assert player.speak_calls == []


def test_cannot_listen_while_speaking():
    controller, factory, player = make_controller()
    controller.start_speaking("Talking")

    with pytest.raises(VoiceControlError) as exc:
        controller.start_listening()

    assert exc.value.code == "BUSY"
    assert controller.state is VoiceState.SPEAKING
    assert len(factory.created) == 0
    assert player.speak_calls == ["Talking"]


def test_cannot_speak_while_listening():
    controller, factory, player = make_controller()
    controller.start_listening()

    with pytest.raises(VoiceControlError) as exc:
        controller.start_speaking("Talking")

    assert exc.value.code == "BUSY"
    assert controller.state is VoiceState.LISTENING
    assert player.speak_calls == []
    assert factory.created[0].is_recording is True


def test_processing_transitions():
    controller, _, _ = make_controller()

    assert controller.begin_processing() is True
    assert controller.state is VoiceState.PROCESSING
    assert controller.begin_processing() is False
    assert controller.finish_processing() is True
    assert controller.state is VoiceState.IDLE
    assert controller.finish_processing() is False


def test_cannot_start_while_processing():
    controller, factory, player = make_controller()
    controller.begin_processing()

    with pytest.raises(VoiceControlError) as listen_exc:
        controller.start_listening()
    with pytest.raises(VoiceControlError) as speak_exc:
        controller.start_speaking("Talking")

    assert listen_exc.value.code == "BUSY"
    assert speak_exc.value.code == "BUSY"
    assert controller.state is VoiceState.PROCESSING
    assert len(factory.created) == 0
    assert player.speak_calls == []


def test_cannot_begin_processing_while_listening_or_speaking():
    controller, _, _ = make_controller()
    controller.start_listening()
    with pytest.raises(VoiceControlError) as exc:
        controller.begin_processing()
    assert exc.value.code == "BUSY"
    controller.stop_listening()

    controller.start_speaking("Talking")
    with pytest.raises(VoiceControlError) as exc:
        controller.begin_processing()
    assert exc.value.code == "BUSY"


def test_recorder_start_failure_enters_error_and_recovers():
    controller, factory, _ = make_controller()
    factory.fail_start = True

    with pytest.raises(VoiceControlError) as exc:
        controller.start_listening()

    assert exc.value.code == "START_FAILED"
    assert controller.state is VoiceState.ERROR
    assert controller.last_error is exc.value

    factory.fail_start = False
    controller.return_to_idle()
    assert controller.state is VoiceState.IDLE
    assert controller.last_error is None

    assert controller.start_listening() is True
    assert controller.state is VoiceState.LISTENING


def test_recorder_stop_failure_enters_error_and_recovers():
    controller, factory, _ = make_controller()
    factory.fail_stop = True
    controller.start_listening()

    result = controller.stop_listening()

    assert result is None
    assert controller.state is VoiceState.ERROR
    assert controller.last_error.code == "STOP_FAILED"

    controller.return_to_idle()
    assert controller.state is VoiceState.IDLE
    assert controller.last_error is None


def test_speak_failure_enters_error_and_recovers():
    controller, _, player = make_controller()
    player.fail_speak = True

    with pytest.raises(VoiceControlError) as exc:
        controller.start_speaking("Hello")

    assert exc.value.code == "SPEAK_FAILED"
    assert controller.state is VoiceState.ERROR
    assert controller.last_error is exc.value
    assert player.stop_calls >= 1

    player.fail_speak = False
    controller.return_to_idle()
    assert controller.state is VoiceState.IDLE

    assert controller.start_speaking("Hello again") is True
    assert controller.state is VoiceState.SPEAKING


def test_player_stop_failure_does_not_leave_speaking_state():
    controller, _, player = make_controller()
    controller.start_speaking("Hello")
    player.fail_stop = True

    assert controller.stop_speaking() is True

    assert controller.state is VoiceState.ERROR
    assert controller.last_error.code == "STOP_FAILED"
    assert controller.state is not VoiceState.SPEAKING

    player.fail_stop = False
    controller.return_to_idle()
    assert controller.state is VoiceState.IDLE


def test_return_to_idle_stops_listening():
    controller, factory, _ = make_controller()
    controller.start_listening()

    controller.return_to_idle()

    assert controller.state is VoiceState.IDLE
    assert factory.created[0].is_recording is False


def test_return_to_idle_stops_playback():
    controller, _, player = make_controller()
    controller.start_speaking("Hello")

    controller.return_to_idle()

    assert controller.state is VoiceState.IDLE
    assert player.is_playing is False
    assert player.stop_calls >= 1


def test_stop_all_enters_stopped_and_stops_activity():
    controller, factory, player = make_controller()
    controller.start_listening()
    controller.stop_all()

    assert controller.state is VoiceState.STOPPED
    assert factory.created[0].is_recording is False

    controller.start_speaking("Hello")
    controller.stop_all()
    assert controller.state is VoiceState.STOPPED
    assert player.is_playing is False


def test_stop_listening_is_idempotent():
    controller, _, _ = make_controller()
    controller.start_listening()

    assert controller.stop_listening() is not None
    assert controller.stop_listening() is None
    assert controller.state is VoiceState.IDLE


def test_context_manager_returns_to_idle():
    with make_controller()[0] as controller:
        controller.start_listening()
        assert controller.state is VoiceState.LISTENING

    assert controller.state is VoiceState.IDLE


def test_tts_player_does_not_import_model_lazily():
    if "kokoro_onnx" in sys.modules:
        pytest.skip("kokoro_onnx was already imported by another test")

    player = KokoroTTSPlayer()

    assert player.is_playing is False
    assert "kokoro_onnx" not in sys.modules


def _speak_and_join(player, on_complete):
    player.speak("hello", on_complete=on_complete)

    assert player._thread is not None
    player._thread.join(timeout=2)
    assert not player._thread.is_alive()


def test_playback_import_failure_resets_is_playing_and_skips_completion():
    player = KokoroTTSPlayer()
    callback = MagicMock()

    with patch.object(
        player,
        "_synthesize",
        return_value=(np.zeros(1600, dtype=np.float32), 16000),
    ):
        with patch.dict(sys.modules, {"sounddevice": None}):
            _speak_and_join(player, callback)

    assert player.is_playing is False
    callback.assert_not_called()


def test_playback_output_stream_failure_resets_is_playing_and_skips_completion():
    player = KokoroTTSPlayer()
    callback = MagicMock()
    failing_sounddevice = SimpleNamespace(
        OutputStream=MagicMock(side_effect=RuntimeError("no output device"))
    )

    with patch.object(
        player,
        "_synthesize",
        return_value=(np.zeros(1600, dtype=np.float32), 16000),
    ):
        with patch.dict(sys.modules, {"sounddevice": failing_sounddevice}):
            _speak_and_join(player, callback)

    assert player.is_playing is False
    callback.assert_not_called()
    failing_sounddevice.OutputStream.assert_called_once()
