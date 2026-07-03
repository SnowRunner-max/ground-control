"""Kokoro TTS: spoken ATC text -> 16-bit WAV bytes, with a small file cache."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "server" / "tts_cache"
CACHE.mkdir(exist_ok=True)

# One distinct voice per facility so the student learns to track who is talking.
VOICES = {
    "atis": ("am_michael", 0.95),
    "clearance": ("af_sarah", 1.1),
    "ground": ("am_fenrir", 1.15),
    "tower": ("am_puck", 1.15),
    "approach": ("af_bella", 1.1),
}

_kokoro: Kokoro | None = None


def _engine() -> Kokoro:
    global _kokoro
    if _kokoro is None:
        _kokoro = Kokoro(str(ROOT / "models" / "kokoro-v1.0.onnx"),
                         str(ROOT / "models" / "voices-v1.0.bin"))
    return _kokoro


def synthesize(text: str, facility: str) -> bytes:
    voice, speed = VOICES.get(facility, ("am_michael", 1.1))
    key = hashlib.sha1(f"{voice}|{speed}|{text}".encode()).hexdigest()
    cached = CACHE / f"{key}.wav"
    if cached.exists():
        return cached.read_bytes()

    samples, sr = _engine().create(text, voice=voice, speed=speed)
    buf = io.BytesIO()
    sf.write(buf, np.asarray(samples), sr, format="WAV", subtype="PCM_16")
    data = buf.getvalue()
    cached.write_bytes(data)
    return data
