"""Tests for the Stage 5 FastAPI voice API (all hardware/models mocked)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient

from voice_module.api import create_app
from voice_module.api.app import app as default_app
from voice_module.control import (
    VoiceControlError,
    VoiceController,
    VoiceState,
)


class FakeRecorder:
    """Fake Stage 3 recorder."""

    def __init__(self, fail_start=False, fail_stop=False):
        self.is_recording = False
        self.fail_start = fail_start
        self.fail_stop = fail_stop

    def start(self):
        if self.fail_start:
            raise RuntimeError("microphone open failed")
        self.is_recording = True

    def stop(self):
        self.is_recording = False
        if self.fail_stop:
            raise RuntimeError("microphone close failed")
        return [], 16000


class FakeRecorderFactory:
    """Factory that records created recorders."""

    def __init__(self, fail_start=False, fail_stop=False):
        self.created = []
        self.fail_start = fail_start
        self.fail_stop = fail_stop

    def __call__(self):
        recorder = FakeRecorder(
            fail_start=self.fail_start,
            fail_stop=self.fail_stop,
        )
        self.created.append(recorder)
        return recorder


class FakePlayer:
    """Fake TTS player."""

    def __init__(self):
        self.speak_calls = []
        self.stop_calls = 0
        self.is_playing = False
        self.fail_stop = False

    def speak(self, text, on_complete=None):
        self.speak_calls.append(text)
        self.is_playing = True

    def stop(self):
        self.stop_calls += 1
        self.is_playing = False
        if self.fail_stop:
            raise RuntimeError("speaker stop failed")


def build_app(fail_start=False, fail_stop=False):
    factory = FakeRecorderFactory(fail_start=fail_start, fail_stop=fail_stop)
    player = FakePlayer()
    controller = VoiceController(recorder_factory=factory, tts_player=player)
    app = create_app(controller_factory=lambda: controller)
    return app, controller, factory, player


_MODEL_OR_AUDIO_MODULES = {"kokoro_onnx", "faster_whisper", "sounddevice"}


def test_health_does_not_create_controller_or_load_models():
    holder = default_app.state.controller_holder
    assert holder._controller is None
    modules_before = _MODEL_OR_AUDIO_MODULES & set(sys.modules)

    client = TestClient(default_app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "ifive-voice-api",
        "version": "0.1.0",
    }
    assert holder._controller is None
    assert (_MODEL_OR_AUDIO_MODULES & set(sys.modules)) == modules_before


def test_health_does_not_call_injected_factory():
    calls = []

    def factory():
        calls.append(True)
        return VoiceController(recorder_factory=FakeRecorderFactory())

    app = create_app(controller_factory=factory)
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert calls == []


def test_status_initial():
    app, _, _, _ = build_app()

    response = TestClient(app).get("/voice/status")

    assert response.status_code == 200
    assert response.json() == {
        "state": "idle",
        "busy": False,
        "last_error": None,
    }


def test_start_and_stop_listening():
    app, _, factory, _ = build_app()
    client = TestClient(app)

    start = client.post("/voice/listen/start")
    assert start.status_code == 200
    assert start.json()["success"] is True
    assert start.json()["changed"] is True
    assert start.json()["state"] == "listening"
    assert factory.created[0].is_recording is True

    status = client.get("/voice/status")
    assert status.json()["state"] == "listening"
    assert status.json()["busy"] is True

    stop = client.post("/voice/listen/stop")
    assert stop.status_code == 200
    assert stop.json()["success"] is True
    assert stop.json()["captured"] is True
    assert stop.json()["state"] == "idle"
    assert factory.created[0].is_recording is False


def test_duplicate_start_listening_reports_no_change():
    app, _, factory, _ = build_app()
    client = TestClient(app)

    client.post("/voice/listen/start")
    duplicate = client.post("/voice/listen/start")

    assert duplicate.status_code == 200
    assert duplicate.json()["changed"] is False
    assert duplicate.json()["state"] == "listening"
    assert len(factory.created) == 1


def test_stop_listening_when_idle_reports_no_audio():
    app, _, _, _ = build_app()
    client = TestClient(app)

    response = client.post("/voice/listen/stop")

    assert response.status_code == 200
    assert response.json()["captured"] is False
    assert response.json()["state"] == "idle"


def test_start_and_stop_speaking():
    app, _, _, player = build_app()
    client = TestClient(app)

    start = client.post("/voice/speak", json={"text": "Hello"})
    assert start.status_code == 200
    assert start.json()["changed"] is True
    assert start.json()["state"] == "speaking"
    assert player.speak_calls == ["Hello"]

    stop = client.post("/voice/speak/stop")
    assert stop.status_code == 200
    assert stop.json()["changed"] is True
    assert stop.json()["state"] == "idle"
    assert player.is_playing is False


def test_duplicate_start_speaking_reports_no_change():
    app, _, _, player = build_app()
    client = TestClient(app)

    client.post("/voice/speak", json={"text": "First"})
    duplicate = client.post("/voice/speak", json={"text": "Second"})

    assert duplicate.status_code == 200
    assert duplicate.json()["changed"] is False
    assert duplicate.json()["state"] == "speaking"
    assert player.speak_calls == ["First"]


def test_stop_speaking_when_idle_reports_no_change():
    app, _, _, _ = build_app()

    response = TestClient(app).post("/voice/speak/stop")

    assert response.status_code == 200
    assert response.json()["changed"] is False
    assert response.json()["state"] == "idle"


@pytest.mark.parametrize("payload", [{"text": ""}, {"text": "   "}, {}])
def test_speak_rejects_empty_or_missing_text(payload):
    app, _, _, player = build_app()

    response = TestClient(app).post("/voice/speak", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert player.speak_calls == []


def test_stop_all_and_reset():
    app, _, factory, _ = build_app()
    client = TestClient(app)
    client.post("/voice/listen/start")

    stopped = client.post("/voice/stop")
    assert stopped.status_code == 200
    assert stopped.json()["state"] == "stopped"
    assert factory.created[0].is_recording is False

    reset = client.post("/voice/reset")
    assert reset.status_code == 200
    assert reset.json()["state"] == "idle"


def test_busy_start_listening_while_speaking():
    app, controller, factory, _ = build_app()
    client = TestClient(app)
    client.post("/voice/speak", json={"text": "Talking"})

    response = client.post("/voice/listen/start")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUSY"
    assert controller.state is VoiceState.SPEAKING
    assert factory.created == []


def test_busy_start_speaking_while_listening():
    app, controller, _, player = build_app()
    client = TestClient(app)
    client.post("/voice/listen/start")

    response = client.post("/voice/speak", json={"text": "Talking"})

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUSY"
    assert controller.state is VoiceState.LISTENING
    assert player.speak_calls == []


def test_voice_control_error_is_structured_and_updates_status():
    def no_microphone():
        raise VoiceControlError(
            "NO_MICROPHONE",
            "No default microphone is available",
        )

    controller = VoiceController(
        recorder_factory=no_microphone,
        tts_player=FakePlayer(),
    )
    app = create_app(controller_factory=lambda: controller)
    client = TestClient(app)

    response = client.post("/voice/listen/start")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "NO_MICROPHONE"

    status = client.get("/voice/status").json()
    assert status["state"] == "error"
    assert status["busy"] is False
    assert status["last_error"]["code"] == "NO_MICROPHONE"


def test_stop_listening_failure_is_structured():
    app, controller, _, _ = build_app(fail_stop=True)
    client = TestClient(app)
    client.post("/voice/listen/start")

    response = client.post("/voice/listen/stop")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "STOP_FAILED"
    assert controller.state is VoiceState.ERROR


def test_stop_speaking_failure_is_structured():
    app, controller, _, player = build_app()
    client = TestClient(app)
    client.post("/voice/speak", json={"text": "Hello"})
    player.fail_stop = True

    response = client.post("/voice/speak/stop")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "STOP_FAILED"
    assert controller.state is VoiceState.ERROR


class _RaisingController:
    state = VoiceState.IDLE
    is_busy = False
    last_error = None

    def start_speaking(self, text):
        raise RuntimeError("secret internal detail")


def test_unexpected_exception_is_hidden():
    app = create_app(controller_factory=lambda: _RaisingController())
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/voice/speak", json={"text": "Hello"})

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "An unexpected error occurred"
    assert "secret" not in response.text
    assert "RuntimeError" not in response.text
