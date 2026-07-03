"""llama-server client.

The scenario FSM is deterministic; the LLM is a bounded assistant:
- coach_feedback(): turn a template correction into a friendly CFI-style tip
- debrief_narrative(): short post-mission writeup

Every call has a template fallback so the sim works even if llama-server
is down or slow.
"""

from __future__ import annotations

import os

import httpx

LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080")
TIMEOUT = 8.0

SYSTEM = (
    "You are a friendly certificated flight instructor helping a student pilot "
    "practice VFR radio calls at Santa Barbara (KSBA, Class C). Be brief, warm, "
    "and concrete. Never invent clearances, frequencies, or numbers not given to you."
)


async def _chat(messages: list[dict], max_tokens: int = 160,
                timeout: float = TIMEOUT) -> str | None:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{LLAMA_URL}/v1/chat/completions",
                json={"messages": messages, "max_tokens": max_tokens,
                      "temperature": 0.6},
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"].strip()
            return text or None
    except Exception:
        return None


async def coach_feedback(step_coach: str, example: str, transcript: str,
                         missing: list[str]) -> str | None:
    """One or two sentences telling the student what was missing and why it matters."""
    prompt = (
        f"The student keyed the mic and said: \"{transcript}\"\n"
        f"Their call was missing: {', '.join(missing)}.\n"
        f"The ideal call is: \"{example}\"\n\n"
        "In one or two short sentences, tell them what to add and why ATC needs it. "
        "Do not repeat the full ideal call back to them; the UI already shows it."
    )
    return await _chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=90,
    )


async def debrief_narrative(scores: list[dict], total: int) -> str | None:
    """Short mission debrief paragraph."""
    lines = "\n".join(
        f"- {s['name']}: {s['score']}/100, attempts {s['attempts']}"
        + (f", missed: {', '.join(s['missed'])}" if s["missed"] else "")
        for s in scores
    )
    prompt = (
        f"The student just completed a full KSBA mission (clearance, taxi, takeoff, "
        f"departure, return, landing, taxi in). Overall score {total}/100.\n"
        f"Per-exchange results:\n{lines}\n\n"
        "Write a 3-4 sentence debrief: one thing they did well, the main pattern to "
        "work on, and an encouraging close. Plain text, no lists."
    )
    return await _chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=200, timeout=20.0,
    )
