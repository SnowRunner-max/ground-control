"""Area A — voice pipeline e2e tests.

Full audio loop, no microphone needed: synthesize *pilot* speech with Kokoro
(a voice/engine instance separate from the app's, using voices ATC never
speaks with), POST it as a WAV to /api/transmit on the live app, and require
whisper-server's transcription to still pass the deterministic grader.

Kokoro renders at 24 kHz; whisper-server wants 16 kHz mono 16-bit WAV, so
pilot audio is resampled (linear interpolation) before encoding. Digits in
the mission's `example` display text ("125.4", "2,500", "Cessna 67525") are
rewritten as phonetic words before synthesis, the way a real pilot would key
them, using the same `say_digits` helper the server uses for ATC speech.
"""

from __future__ import annotations

import io
import re
import time

import numpy as np
import pytest
import soundfile as sf

from server import tts as tts_module
from server.phraseology import say_digits

from .conftest import debug_step, new_mission, transmit_text, transmit_wav

# ATC never speaks with these voices (see server/tts.py VOICES) — safe picks
# for the "robo-pilot" so audio content, not voice identity, is what's tested.
ATC_VOICES = {"am_michael", "af_sarah", "am_fenrir", "am_puck", "af_bella"}
PILOT_VOICE_PRIMARY = ("af_heart", 1.0)
PILOT_VOICE_ALT = ("am_eric", 1.15)

TARGET_SR = 16000


# --------------------------------------------------------------- synthesis


def _resample(samples: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Linear-interpolation resample (good enough for STT input)."""
    samples = np.asarray(samples, dtype=np.float32)
    if orig_sr == target_sr:
        return samples
    duration = len(samples) / orig_sr
    n_target = max(1, int(round(duration * target_sr)))
    x_orig = np.linspace(0.0, duration, num=len(samples), endpoint=False)
    x_target = np.linspace(0.0, duration, num=n_target, endpoint=False)
    return np.interp(x_target, x_orig, samples).astype(np.float32)


def _speak_numbers(text: str) -> str:
    """Rewrite digit groups as spoken words ('125.4' -> 'one two five point
    four') so Kokoro reads them like a pilot instead of a narrator."""
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # "2,500" -> "2500"
    return re.sub(r"\d+(?:\.\d+)?", lambda m: say_digits(m.group()), text)


def pilot_wav(text: str, voice: str = PILOT_VOICE_PRIMARY[0],
             speed: float = PILOT_VOICE_PRIMARY[1]) -> bytes:
    """Synthesize pilot speech for `text` as a 16 kHz mono 16-bit WAV."""
    assert voice not in ATC_VOICES, "pilot audio must not reuse an ATC voice"
    spoken = _speak_numbers(text)
    samples, sr = tts_module._engine().create(spoken, voice=voice, speed=speed)
    samples_16k = _resample(samples, sr, TARGET_SR)
    buf = io.BytesIO()
    sf.write(buf, samples_16k, TARGET_SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def transmit_voice(api, freq_khz: int, text: str, *, voice: str = PILOT_VOICE_PRIMARY[0],
                   speed: float = PILOT_VOICE_PRIMARY[1], retries: int = 1) -> dict:
    """Transmit synthesized pilot speech; whisper is imperfect so allow one
    re-synthesis-and-retry before handing back the (possibly failing) result."""
    result: dict = {}
    for attempt in range(retries + 1):
        wav = pilot_wav(text, voice=voice, speed=speed)
        result = transmit_wav(api, freq_khz, wav)
        if result["passed"]:
            return result
        print(f"[transmit_voice] attempt {attempt + 1} did not pass — "
              f"transcript={result.get('transcript')!r} missing={result.get('missing')!r}")
    return result


# ------------------------------------------------------------------- tests


def test_sequential_digit_critical_readbacks(api):
    """Fly clearance_call -> clearance_readback -> ground_call ->
    ground_readback with synthesized pilot voice, driven by /api/debug/step
    from a fresh mission. Covers the digit-critical clearance readback
    (squawk, "at or below 2,500", departure frequency 125.4) and the taxi
    readback (route letters + runway crossings)."""
    new_mission(api)

    # 1. initial clearance call (callsign, ATIS letter, VFR request)
    step = debug_step(api)
    assert step["step_id"] == "clearance_call"
    result = transmit_voice(api, step["freq_khz"], step["example"])
    assert result["passed"] is True, (
        f"clearance_call failed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")

    # 2. digit-critical clearance readback: squawk + "at or below 2,500" + 125.4
    step = debug_step(api)
    assert step["step_id"] == "clearance_readback"
    example = step["example"]
    assert "2,500" in example or "2500" in example
    assert "125.4" in example
    assert step["squawk"] in example
    result = transmit_voice(api, step["freq_khz"], example)
    assert result["passed"] is True, (
        f"clearance_readback failed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")

    # 3. ground call (needed to unlock the taxi readback)
    step = debug_step(api)
    assert step["step_id"] == "ground_call"
    result = transmit_voice(api, step["freq_khz"], step["example"])
    assert result["passed"] is True, (
        f"ground_call failed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")

    # 4. ground taxi readback: current route identifiers (C/F/B/B1 or C/E)
    step = debug_step(api)
    assert step["step_id"] == "ground_readback"
    result = transmit_voice(api, step["freq_khz"], step["example"])
    assert result["passed"] is True, (
        f"ground_readback failed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")


def test_alternate_pilot_voice_and_speed_also_grades(api):
    """A second, different pilot voice/speed must still pass grading —
    proves the pipeline isn't tuned to one specific synthetic voice."""
    new_mission(api)
    step = debug_step(api)
    assert step["step_id"] == "clearance_call"
    result = transmit_voice(api, step["freq_khz"], step["example"],
                            voice=PILOT_VOICE_ALT[0], speed=PILOT_VOICE_ALT[1])
    assert result["passed"] is True, (
        f"alternate-voice clearance_call failed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")


def test_atis_wav_is_valid_mono_and_long_enough(api):
    brief = new_mission(api)
    step = debug_step(api)

    r = api.get("/api/atis.wav")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"

    data, samplerate = sf.read(io.BytesIO(r.content))
    assert samplerate > 0
    # sf.read gives a 1-D array for mono, 2-D (frames, channels) for multi-channel
    channels = 1 if data.ndim == 1 else data.shape[1]
    assert channels == 1, "ATIS audio must be mono"

    duration_s = len(data) / samplerate
    assert duration_s > 15.0, f"ATIS recording too short: {duration_s:.1f}s"

    # info letter consistency: the mission brief's atis_display text and the
    # debug step's atis_letter must agree on which info letter is current.
    letter_title = step["atis_letter"].title()
    assert f"information {letter_title}" in brief["atis_display"]


def test_text_transmit_latency_budget(api):
    """Text-mode round trip: grade + TTS reply synthesis. Generous ceiling —
    this guards against order-of-magnitude regressions, not jitter."""
    new_mission(api)
    step = debug_step(api)
    t0 = time.monotonic()
    result = transmit_text(api, step["freq_khz"], step["example"])
    elapsed = time.monotonic() - t0
    print(f"[latency] text round trip (grade + TTS): {elapsed:.2f}s")
    assert result["passed"] is True
    assert elapsed < 15.0, f"text round trip too slow: {elapsed:.2f}s"


def test_voice_transmit_latency_budget(api):
    """Full voice round trip: STT + grade + TTS reply synthesis. Pilot audio
    synthesis happens client-side and is NOT included in the timed window —
    only the server round trip is measured. Generous ceiling."""
    new_mission(api)
    step = debug_step(api)

    wav = pilot_wav(step["example"])
    t0 = time.monotonic()
    result = transmit_wav(api, step["freq_khz"], wav)
    elapsed = time.monotonic() - t0
    print(f"[latency] voice round trip (STT + grade + TTS): {elapsed:.2f}s")

    if not result["passed"]:
        print(f"[latency] retry — transcript={result.get('transcript')!r} "
              f"missing={result.get('missing')!r}")
        wav = pilot_wav(step["example"])
        t0 = time.monotonic()
        result = transmit_wav(api, step["freq_khz"], wav)
        elapsed = time.monotonic() - t0
        print(f"[latency] voice round trip retry: {elapsed:.2f}s")

    assert result["passed"] is True, (
        f"voice round trip never passed: transcript={result.get('transcript')!r} "
        f"missing={result.get('missing')!r}")
    assert elapsed < 25.0, f"voice round trip too slow: {elapsed:.2f}s"
