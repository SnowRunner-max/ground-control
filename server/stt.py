"""whisper-server client. Expects 16 kHz 16-bit mono WAV from the browser."""

from __future__ import annotations

import os

import httpx

WHISPER_URL = os.environ.get("WHISPER_URL", "http://127.0.0.1:8081")

# Bias whisper toward aviation phraseology and this mission's vocabulary.
PROMPT = (
    "Santa Barbara Ground, Cessna six seven five two five, Above All Aviation, "
    "information Bravo, request VFR departure, taxi runway two five via Charlie "
    "Hotel, cross runway one five right, holding short, cleared for takeoff, "
    "squawk four five seven one, departure frequency one two five point four, "
    "line up and wait, cleared to land, full stop, niner, three mile final, "
    "turn right at Mike, taxi to parking via Mike, Alpha, Foxtrot."
)


async def transcribe(wav_bytes: bytes) -> str:
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{WHISPER_URL}/inference",
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={
                "temperature": "0.0",
                "temperature_inc": "0.2",
                "response_format": "json",
                "prompt": PROMPT,
            },
        )
        r.raise_for_status()
        return r.json().get("text", "").strip()
