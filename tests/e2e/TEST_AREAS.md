# End-to-End Test Areas

E2E tests exercise the *live* stack — real llama-server (Qwen3-4B), real
whisper-server (small.en), real Kokoro TTS — unlike `tests/test_*.py` which
stub all models. They auto-skip when the stack isn't running.

**Infrastructure contract** (`tests/e2e/conftest.py`, shared):
- llama-server on `$LLAMA_URL` (default :8080) and whisper-server on
  `$WHISPER_URL` (default :8081) are expected to be already running; tests
  skip with a helpful message otherwise. Never start/stop these in tests.
- Each pytest session launches its **own** app instance (uvicorn subprocess on
  a free port) so concurrent sessions can't clobber each other's global
  mission state. Fixtures: `app` (base URL string), `api` (httpx.Client).
- `GET /api/debug/step` exposes the active mission's current step (id,
  facility, freq_khz, ideal example call, squawk, ATIS letter, runway) so a
  robo-pilot can fly without reaching into server internals.

## Area A — Voice pipeline (`test_voice_pipeline.py`)

The full audio loop, no microphone needed: synthesize *pilot* calls with
Kokoro (a voice not used by ATC), POST as WAV to `/api/transmit`, and require
whisper's transcription to still pass the deterministic grader.

1. Spoken clearance call transcribes and passes (callsign, ATIS letter, request).
2. Digit-critical readback survives STT: squawk code, "at or below 2,500",
   departure frequency 125.4 — spoken as phonetic words ("four five seven one").
3. Taxi readback with route letters (Charlie/Hotel) and runway crossings passes.
4. Robustness: at least one alternate TTS voice/speed still grades correctly.
5. ATIS endpoint returns a real WAV: parseable header, mono 16-bit, plausible
   duration (>15 s), and the spoken info letter matches the mission's.
6. Latency budgets on this hardware (M1 Pro): text-only transmit round trip
   (grade + TTS reply) and full voice round trip (STT + grade + TTS). Generous
   ceilings — these guard against order-of-magnitude regressions, not jitter.

## Area B — Live mission over the wire (`test_live_mission.py`)

A robo-pilot flies complete missions through the public HTTP + WebSocket API
exactly as the browser would.

1. Full mission to `complete: true`: for each step, read `/api/debug/step`,
   transmit the ideal call in text mode on the right frequency, run every
   returned movement action's `leg_complete` over the WebSocket, and consume
   pushes (contact-departure, runway-exit instruction). Debrief total == 100.
2. Line-up-and-wait path: when drawn, the scheduled takeoff clearance arrives
   over the WebSocket ~8 s after the LUAW readback, without any pilot call.
3. Live LLM coaching: a deliberately bad readback returns coach text that
   includes the ideal call; with llama-server up it should usually be the
   CFI-style tip (tolerated fallback: template text, since the LLM may time
   out under load).
4. Debrief narrative arrives over the WebSocket after mission completion
   (real Qwen output: non-empty prose mentioning nothing false — smoke-level
   assertion only).
5. Frequency realism live: transmitting on another facility's frequency gets
   an audible redirect (with real TTS audio); unassigned frequency gets static
   (no audio); ATIS frequency is receive-only.
6. Static/UI serving: index.html, styles.css, all four JS files, and the
   diagram PNG serve 200; each JS file parses (`node --check`).

## Execution

```sh
./run.sh                      # or start llama-server + whisper-server manually
uv run pytest tests/e2e -q    # e2e only
uv run pytest -q              # unit suite still passes standalone (e2e skips if stack down)
```
