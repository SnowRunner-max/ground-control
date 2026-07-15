# Code review — quality, smells, duplication (July 2026)

Scope: full application (`server/`, `web/`, `tests/`, `run.sh`, `scripts/`),
reviewed against the project mission: a **single-user, local, deterministic**
KSBA radio trainer where the FSM drives the scenario and the LLM only polishes
feedback. Overall the codebase is in good shape — small, well-commented modules,
a typed ground graph with self-validation, and a solid server-side test suite.
The tasks below reduce drift risk and duplication rather than rework the design.

Test status at review time: `uv run pytest` → 176 passed, 10 skipped,
2 failed (`tests/test_chart_geometry.py` — the checked-in FAA PDF is an
unhydrated Git LFS pointer in a fresh clone; see task 1).

---

## P1 — Correctness / robustness

1. **Chart-geometry tests fail on a clone without `git lfs pull`.**
   `FAA_KSBA_APD_2607.pdf` is stored in LFS; without hydration the sha256 check
   and the PyMuPDF open both fail confusingly. Detect the LFS pointer file
   (starts with `version https://git-lfs.github.com/spec/v1`) and
   `pytest.skip` with a clear "run `git lfs pull`" message.
   (`tests/test_chart_geometry.py`)

2. **Client reads the wrong error key from FastAPI.** `App.start()` does
   `body.error || "Could not start the mission."` but `/api/mission/new`
   raises `HTTPException(detail=...)`, so the body is `{"detail": ...}` and the
   real validation message never reaches the user. Read
   `body.detail || body.error`. (`web/app.js:28`)

3. **`/api/transmit` re-reads the `mission` global across awaits.** Between
   `handle_transmission`, the TTS `await`, the LLM coach `await`, and
   `asyncio.create_task(_scheduled_push(mission, ...))`, a concurrently created
   new mission can interleave: coach feedback would be computed from the *new*
   mission's step and the push scheduled against the wrong object
   (`_scheduled_push` guards with `mission is not m`, but `transmit` passes the
   global read at schedule time, not the mission that produced the push).
   Capture `m = mission` once at the top and use it throughout.
   (`server/main.py:160-212`)

4. **Fragile string surgery for the takeoff example.**
   `cfg['departure_instruction'].split(' approved')[0]` silently produces the
   whole string if a future instruction doesn't contain " approved". Store the
   short form explicitly in the config. (`server/scenario.py:326`)

5. **Silent `except Exception` fallbacks hide real faults.** `_speak`,
   `_service_up`, and `llm._chat` swallow everything; a typo in `tts.py` looks
   identical to "model not downloaded". Keep the fallback behavior but log the
   exception (`logging.getLogger(...).warning(..., exc_info=True)`). Related:
   `run.sh` sends llama-server stdout/stderr to `/dev/null` — send it to
   `logs/llama.log` like whisper. (`server/main.py:24-47`, `server/llm.py:39`,
   `run.sh:31`)

## P2 — Duplication / drift risk

6. **Parallel display/spoken ATC strings are hand-maintained in every
   `AtcReply`.** Each of ~15 replies in `_build_steps` writes the same sentence
   twice (once cased, once TTS-phonetic); a wording change must be applied in
   two places with no check they stay in sync. `server/ground.py` already
   solved this pattern (`TaxiRoute.display_instruction` /
   `spoken_instruction` derived from one `RouteInstruction` list). Introduce a
   small segment-based builder (literal text + typed values like runway, freq,
   squawk, altitude) that renders both forms, and migrate replies to it.
   (`server/scenario.py:_build_steps`)

7. **The arrival instruction lives in two files in two forms.**
   `airport.CONFIGS[..]["arrival_instruction"]["display"]` holds the display
   text while `Mission._spoken_arrival()` hardcodes the spoken twin — adding or
   editing a runway config requires synchronized edits in `airport.py` and
   `scenario.py`. Fold the spoken form (or a segment list per task 6) into the
   config. (`server/scenario.py:550-553`, `server/airport.py:115-144`)

8. **Runway formatting logic exists three times.** `phraseology.say_runway`,
   `ground._runway_spoken` / `_runway_display` / `_runway_pattern`, and literal
   regexes: `rwy_pat = r"15 ?(left|l\b)" if rwy == "15L" else r"\b25\b"` in
   `scenario.py:153` plus the same patterns inline in `airport.CONFIGS`
   `readback_items`. Move the display/spoken/pattern trio into `phraseology`
   and consume it from `ground`, `scenario`, and `airport`.

9. **Two representations of "readback requirement".** `ground.py` has the
   typed `ReadbackRequirement`; `airport.CONFIGS` uses bare tuples
   (`("entry", "right base", [r"right base"])`) that `scenario.py:461` adapts
   with a parallel list-comprehension next to `_route_items`. Type the
   `CONFIGS` arrival/departure data as dataclasses and use one adapter.

10. **Frequency values round-trip through strings.** Canonical form is kHz
    (`airport.FREQS`), but `scenario.py` formats to an MHz string then parses
    it back (`say_freq(float(dep_freq))` at line 185; `say_freq(expected / 1000)`
    at 686), and `brief["freqs"]` ships MHz strings that `app.js:37-39` converts
    back to kHz with `Math.round(parseFloat(mhz) * 1000)`. Add
    `phraseology.say_freq_khz(khz)` and include integer `freqs_khz` in the
    brief so neither side re-parses display strings.

11. **Push-payload assembly duplicated server-side; ATC-playback duplicated
    client-side.** `main.py` builds the `{"type": "push", "atc": ..., "coach": ...}`
    shape twice (`_scheduled_push` vs the `leg_complete` branch of
    `ws_endpoint`); `app.js` duplicates the "play audio or warn, then log"
    block in `onPush` and `handleResult`. Extract one helper on each side.
    (`server/main.py:60-71,215-242`, `web/app.js:160-183,259-284`)

12. **`Mission.leg_complete` hardcodes what the step graph already knows.**
    The if-chain maps each leg to the coach text of the step the mission is
    already in (`self.steps["runup_complete"].coach`, etc.). Since
    `pending_legs[leg]` stores the target step id, the default case is simply
    `self.steps[expected_state].coach`; only `climb_out`/`landing_roll`
    (which emit ATC) and `taxi_in` (completion) need special entries.
    (`server/scenario.py:697-732`)

## P3 — Smells / hygiene

13. **`Mission._build_steps` is ~400 lines of inline construction.** Split
    into per-phase builders (`_clearance_steps`, `_ground_steps`,
    `_tower_steps`, `_approach_steps`) so each phase is reviewable on one
    screen; tasks 6-9 shrink it substantially first.

14. **`handle_transmission` mixes five concerns** (frequency gate, say-again,
    LUAW gate, transponder gate, grading/scoring/logging). Extract the failure
    reply construction and the scoring block; keep the method as the
    orchestrator. (`server/scenario.py:560-663`)

15. **Remove the `config_id` alias.** It is documented as "retained for
    pattern/config compatibility" but equals `self.runway` inside a single
    codebase — use `runway` everywhere. (`server/scenario.py:91`)

16. **Module-global mutable state in `main.py`** (`mission`, `sockets`).
    Single-user is by design, but wrapping them in one `AppState` (attached to
    `app.state`) removes `global`, makes tests independent, and gives the
    task-3 fix a natural home.

17. **Unused import:** `say_letter` in `server/scenario.py:28`. Also
    `atis.ATIS_LETTERS = [letter for letter in NATO.values()]` →
    `list(NATO.values())`. (`server/atis.py:10`)

18. **`web/audio.js` uses the deprecated `ScriptProcessorNode`** for mic
    capture; migrate to an `AudioWorklet` (Chromium ships it; the PTT chunk
    logic ports directly).

19. **`innerHTML` with server data in `renderChartInfo` and `showDebrief`.**
    The data is locally generated so this isn't an exposed XSS, but
    `addLog`/`setCoach` already use `textContent`/`createElement` — make the
    remaining renderers consistent so no injection sink exists at all.
    (`web/app.js:93-122,326-340`)

20. **Unbounded TTS cache inside the source tree.** `server/tts_cache/` grows
    without limit (every distinct squawk/wind/ATIS string is a new WAV). Move
    it out of `server/` (e.g. a top-level `var/` or XDG cache dir) and add a
    simple size cap or LRU sweep at startup. (`server/tts.py:14`)

21. **No CI.** There is no `.github/workflows`; the suite only runs locally.
    Add a workflow running `uv run pytest` (with the LFS-skip from task 1 it
    passes without the 200 KB chart) and `node tests/js/test_map.js`.

## Explicitly fine as-is

- The deterministic FSM + bounded-LLM split matches the mission statement and
  is enforced in code (LLM output only ever lands in coach/debrief text).
- `ground.py`'s graph validation at import time is a strength — it is the
  pattern the rest of the phraseology data should converge on (tasks 6-9).
- Radio/transponder modeling, normalization (`phraseology.normalize`), and
  `tail_regex` are well-tested (189-line test module) and readable.
