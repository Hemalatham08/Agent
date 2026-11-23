# Voice Module

Standalone voice functionality for the iFive AI ERP Agent.

## Features
- Speech-to-Text (STT): Convert spoken questions into text using Faster-Whisper.
- Text-to-Speech (TTS): Read ERP answers aloud using Kokoro-82M.
- Microphone Recording: Capture audio from microphone for STT input.
- Independent testing.

## Isolation Rules
- Do not modify existing backend files.
- Do not modify existing frontend files.
- Do not modify main.py or database files.
- Do not modify Gemini integration.
- Keep all voice-module code inside this folder.

## Current Implementation

### Stage 1: Speech-to-Text (STT)
- **Model**: Whisper `small` with `int8` quantization (CPU)
- **Framework**: Faster-Whisper 1.2.1 (CTranslate2)
- **Language**: English (including Indian English)
- **Input**: Audio file (wav, mp3, m4a, flac, ogg, aac, wma)
- **Output**: Transcribed text with timestamps and language detection

### Stage 2: Text-to-Speech (TTS)
- **Model**: Kokoro-82M INT8 ONNX
- **Framework**: kokoro-onnx
- **Voices**: Multiple English voices (af_heart, am_michael, etc.)
- **Output**: WAV audio files

### Stage 3: Microphone Recording
- **Library**: sounddevice (PortAudio backend)
- **Format**: 16kHz mono 16-bit PCM WAV (STT compatible)
- **Features**: Device listing, selection, start/stop recording, fixed-duration recording
- **Output**: WAV files in `recordings/` folder

### Stage 4: Voice Controls
- **States**: `IDLE`, `LISTENING`, `PROCESSING`, `SPEAKING`, `STOPPED`, `ERROR`
- **Controls**: start/stop listening, start/stop speech, begin/finish processing,
  `return_to_idle()`, `stop_all()`
- **Safety**: recording and playback are mutually exclusive; duplicate starts are
  no-ops; stop/cleanup failures never leave the controller stuck in a busy state
- **Design**: `VoiceController` with an injected recorder factory and TTS player.
  Kokoro and sounddevice are imported lazily; no FastAPI/ERP integration.

## Requirements
- Python 3.11+
- Virtual environment in `.venv` (already configured)
- Dependencies in `requirements.txt`

## Virtual Environments
- `.venv` — STT + Recording (faster-whisper, sounddevice, soundfile, pydub)
- `.venv_tts` — TTS (kokoro-onnx, soundfile, onnxruntime)

## Installation

### STT + Recording dependencies (in .venv)
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### TTS dependencies (in .venv_tts)
```powershell
D:\Agent\Agent\voice_module\.venv_tts\Scripts\python.exe -m pip install kokoro-onnx soundfile onnxruntime
```

## Usage

### Test STT with an audio file
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m tests.test_stt path/to/audio.wav
```

### Test TTS
```powershell
D:\Agent\Agent\voice_module\.venv_tts\Scripts\python.exe -m tests.test_tts
```

### Test Microphone Recording (Unit Tests)
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m pytest tests/test_microphone.py -v
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m pytest tests/test_recording.py -v
```

### Test Voice Controls (Stage 4, mocked hardware)
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m pytest tests/test_voice_control.py -v
```

### Manual Microphone Recording Test (5 seconds)
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m tests.test_recording --manual
```

**With specific device:**
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m tests.test_recording --manual --device 0 --duration 10
```

### List Available Microphones
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -c "
from voice_module.audio import list_microphones
for m in list_microphones():
    print(f'[{m.index}] {m.name} ({m.max_input_channels}ch, {m.default_sample_rate:.0f}Hz) [{m.hostapi}]')
"
```

### Programmatic Usage

#### STT
```python
from voice_module.stt import FasterWhisperSTT
from voice_module.config import DEFAULT_STT_CONFIG

stt = FasterWhisperSTT(DEFAULT_STT_CONFIG)
result = stt.transcribe_file("path/to/audio.wav")
print(result.text)
```

#### TTS
```python
from kokoro_onnx import Kokoro
import soundfile as sf

kokoro = Kokoro("models/kokoro-v1.0.int8.onnx", "models/voices-v1.0.bin")
audio, sr = kokoro.create("Hello world", voice="af_heart", speed=1.0, lang="en-us")
sf.write("output.wav", audio, sr)
```

#### Microphone Recording
```python
from voice_module.audio import (
    list_microphones,
    get_default_microphone,
    RecordingSession,
    record_fixed_duration,
)

# List devices
for mic in list_microphones():
    print(f"[{mic.index}] {mic.name}")

# Fixed duration recording (blocking)
audio_data, sr = record_fixed_duration(device_index=0, duration_sec=5.0)

# Manual start/stop recording
session = RecordingSession(device_index=0)
session.start()
# ... do other things ...
session.stop()
session.save("recordings/my_recording.wav")
```

#### Voice Controls (Stage 4)
```python
from voice_module.control import VoiceController, VoiceState

controller = VoiceController(device_index=0)

controller.start_listening()            # IDLE -> LISTENING
audio, sr = controller.stop_listening() # LISTENING -> IDLE

controller.begin_processing()           # IDLE -> PROCESSING (while STT runs)
controller.finish_processing()          # PROCESSING -> IDLE

controller.start_speaking("Hello")      # IDLE -> SPEAKING
controller.stop_speaking()              # SPEAKING -> IDLE (interrupt)

controller.stop_all()                   # anything -> STOPPED
controller.return_to_idle()             # anything -> IDLE (safe cleanup)
```

`VoiceController` is hardware/model agnostic: pass `recorder_factory=` and/or
`tts_player=` to inject backends. Automated tests use fakes only.

**Playback environment note:** Stage 2 (`kokoro_onnx`) is installed in
`.venv_tts`, while Stage 3 audio (`sounddevice`) is installed in `.venv`.
`KokoroTTSPlayer` imports both lazily, so real speech playback requires whichever
environment runs it to have both `kokoro_onnx` and `sounddevice` available. The
control layer itself and all automated tests do not load either model or device.

## Recordings Location
All test recordings are saved to: `voice_module/recordings/`

Files are named with timestamps: `manual_test_<timestamp>.wav`

## Model Downloads
- **Whisper small** (~244 MB): Downloads on first STT run to `~/.cache/huggingface/hub/`
- **Kokoro INT8** (~30 MB): Pre-downloaded in `models/` folder

## Microphone Setup (Windows)
1. Ensure microphone is connected and working in Windows Sound settings
2. Allow microphone access for Python/Terminal in Windows Privacy settings:
   - Settings → Privacy & security → Microphone → Let apps access your microphone
   - Enable for "Desktop apps" or your terminal application
3. Run the device listing command above to verify detection

## Known Limitations & Troubleshooting

| Issue | Solution |
|-------|----------|
| No devices listed | Check Windows microphone permissions; try different host API |
| Permission denied | Run terminal as Administrator or enable mic access in Windows Settings |
| Recording is silent | Check microphone input level in Sound Control Panel |
| "PortAudio error" | Update audio drivers; try different sample rate (44100, 48000) |
| STT transcription empty | Ensure recording duration > 0.5s; speak clearly; check audio level |

### Resource Constraints (4 GB RAM)
- Do NOT load Whisper and Kokoro models simultaneously
- Use separate virtual environments (`.venv` for STT/Recording, `.venv_tts` for TTS)
- Recording uses minimal memory (~few MB for 5s audio)

## Integration
This module is developed independently.
Connecting it to the ERP interface (FastAPI endpoints etc.) will be a separate,
future step (Stage 5+).

## Stage 5: FastAPI API Layer

Local development server (binds to loopback only):

```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m uvicorn voice_module.api.app:app --app-dir src --host 127.0.0.1 --port 8000
```

Health check (does not load Kokoro, Whisper, or microphone hardware):

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Endpoints:
- `GET /health`
- `GET /voice/status`
- `POST /voice/listen/start`
- `POST /voice/listen/stop`
- `POST /voice/speak` (JSON body: `{"text": "..."}`)
- `POST /voice/speak/stop`
- `POST /voice/stop`
- `POST /voice/reset`

Run the API tests with:
```powershell
D:\Agent\Agent\voice_module\.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests\test_api.py -v
```