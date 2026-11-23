from pathlib import Path
import soundfile as sf
from kokoro_onnx import Kokoro

BASE_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = BASE_DIR / "models" / "kokoro-v1.0.int8.onnx"
VOICES_PATH = BASE_DIR / "models" / "voices-v1.0.bin"
OUTPUT_PATH = BASE_DIR / "sample_tts.wav"

print("Loading Kokoro model...")
kokoro = Kokoro(str(MODEL_PATH), str(VOICES_PATH))

text = "Welcome to ABC Fasteners and Industrial Supplies. How can I help you today?"

print("Generating speech...")
audio, sample_rate = kokoro.create(
    text,
    voice="af_heart",
    speed=1.0,
    lang="en-us",
)

sf.write(str(OUTPUT_PATH), audio, sample_rate)

print(f"Speech generated successfully: {OUTPUT_PATH}")
print(f"Sample rate: {sample_rate}")
print(f"Audio duration: {len(audio) / sample_rate:.2f} seconds")
