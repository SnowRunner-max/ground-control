# Ground Control — KSBA Radio Communication Trainer

A local, speech-driven simulator for practicing VFR radio calls at Santa Barbara
Municipal (KSBA, Class C), built for private pilot training. You fly one mission
in a Cessna 152: engine start at **Above All Aviation**, ATIS → Clearance
Delivery → Ground → Tower → Departure → return → Approach → Tower → landing →
Ground → parking. The plane only moves on the real FAA airport diagram when your
readbacks are correct.

Everything runs offline on your Mac:

| Role | Engine | Model |
|---|---|---|
| Speech-to-text | whisper.cpp (`whisper-server`) | `ggml-small.en` |
| Coach / debrief brain | llama.cpp (`llama-server`) | Qwen3-4B-Instruct Q4_K_M |
| ATC voices | kokoro-onnx | kokoro-v1.0 (distinct voice per facility) |

## Setup (one time)

Requires Homebrew, `uv`, and `llama.cpp` (`brew install llama.cpp`).

```sh
./scripts/setup.sh   # installs whisper-cpp, python deps, downloads ~3.5 GB of models
```

## Run

```sh
./run.sh             # starts llama-server, whisper-server, and the game at http://localhost:8000
```

## How to play

1. **Mission brief** — you're parked at Above All Aviation. Plan: VFR departure
   east along the coastline at 3,500, ~10 miles out, return for a full stop.
2. **Radio** — a KX-155-style COM with **active/standby** displays: tune the
   standby with the MHz/kHz knobs, then press the flip-flop (⇄) to make it
   active. You only hear (and reach) a facility whose frequency is active.
3. **Listen to ATIS** on 132.65 — you'll need the information letter, and the
   ATIS tells you the runway in use.
4. **Push-to-talk** — hold **Space** (or the on-screen PTT) while speaking.
   Release to transmit. There's also a text box if you'd rather type a call.
5. **Transponder** — Clearance Delivery assigns a squawk. Dial it in and set
   the mode to ALT before takeoff; Tower will catch a wrong code.
6. **Readbacks move the plane.** A correct taxi readback starts the taxi
   animation; hold-short and runway-crossing readbacks are enforced (per the
   caution note on the SBA diagram). Bad calls get a realistic "say again" or
   correction — and in coach mode, a CFI-style tip plus the ideal phraseology.
7. Say **"say again"** any time to have ATC repeat the last transmission.
8. Park back at Above All for your **debrief**: per-exchange scores and a
   short instructor writeup.

Every mission is randomized: ATIS letter, wind (which picks runway 25 vs 15L),
altimeter, squawk code, taxi route, and whether Tower issues "line up and wait."

## Architecture

```
Browser (vanilla JS)                        FastAPI (server/)
  map: FAA diagram + pattern view   ◄─WS──►  scenario.py  deterministic mission FSM
  radio stack: COM + transponder    ─wav──►  main.py      /api/transmit, /ws pushes
  PTT capture, radio-effect audio   ◄─wav──  stt.py ─► whisper-server :8081
                                             llm.py ─► llama-server   :8080
                                             tts.py ─► kokoro-onnx (in-process)
```

Design note: the mission is driven by a **deterministic state machine**
(`server/scenario.py`), not the LLM. Grading matches your normalized transcript
("squawk four five seven one" → `squawk 4571`) against expected readback items.
The local LLM only polishes coach feedback and writes the debrief — so a small
model can never derail the scenario. All ATC audio is template-generated
phraseology spoken by Kokoro, with per-facility voices.

Key files:

- `server/scenario.py` — the mission: every exchange, graded items, ATC replies
- `server/airport.py` — KSBA frequencies, taxi node graph (normalized diagram
  coordinates), runway configs 25 / 15L, pattern-view geometry
- `server/phraseology.py` — spoken-number normalization both directions
- `server/atis.py` — randomized ATIS generation
- `scripts/setup.sh`, `run.sh` — install + launch

## Status

- [x] Scaffold, model downloads, map render from the FAA diagram PDF
- [x] Scenario FSM, grading, ATIS, LLM/STT/TTS wrappers, FastAPI server
- [x] Web UI (map animation, radio stack, PTT audio, coach panel, debrief)
- [x] pytest suite — 57 tests: full-mission walks (both runway configs, with
      and without line-up-and-wait), failure paths (wrong frequency, bad
      readbacks, transponder, say-again, scoring), phraseology round-trips,
      and API/WebSocket surface with TTS/LLM stubbed (`uv run pytest`)
- [ ] End-to-end verification with all three servers live (voice roundtrip,
      full mission in the browser, latency check)

A useful invariant the suite enforces: every step's coach-suggested ideal call
must fully satisfy that step's own grader, across randomized missions.
