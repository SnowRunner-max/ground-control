"""Area B — live mission over the wire.

A robo-pilot flies complete missions through the public HTTP + WebSocket API
exactly as the browser would: read `/api/debug/step`, transmit the ideal
call in text mode, drive `leg_complete` over the WebSocket for every
movement action, and consume the pushes the server sends back.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import wave

import pytest
from websockets.sync.client import connect

from .conftest import ROOT, debug_step, new_mission, transmit_text

# Legs that trigger a server push over the WebSocket (see server/scenario.py
# Mission.leg_complete). All other legs (line_up, exit) are silent.
PUSHING_LEGS = {"taxi_out", "climb_out", "cruise_east", "to_final", "landing_roll", "taxi_in"}

WEB = ROOT / "web"


def ws_url(app: str) -> str:
    return "ws://" + app.split("://", 1)[1] + "/ws"


def fly_step(api, ws, step: dict) -> tuple[dict, list[tuple[str, dict]]]:
    """Transmit the ideal call for `step`, assert it passes, and drive every
    movement action's leg_complete over the WS. Returns (transmit result,
    [(leg, push_message), ...] for legs that produced a push)."""
    result = transmit_text(
        api, step["freq_khz"], step["example"],
        xpdr_code=step["squawk"], xpdr_mode="ALT",
    )
    assert result["passed"] is True, (
        f"step {step['step_id']} failed to pass with its own ideal call: {result}")

    pushes: list[tuple[str, dict]] = []
    for action in result.get("actions") or []:
        leg = action.get("leg")
        if leg is None:
            continue
        ws.send(json.dumps({"type": "leg_complete", "leg": leg}))
        if leg in PUSHING_LEGS:
            msg = json.loads(ws.recv(timeout=30))
            pushes.append((leg, msg))
    return result, pushes


def fly_until(api, ws, stop_before_id: str, max_steps: int = 25) -> dict:
    """Fly steps (full step+leg_complete cycle) until the step *about to be
    flown* is `stop_before_id`. Returns that step's debug_step() dict without
    transmitting it."""
    for _ in range(max_steps):
        step = debug_step(api)
        if step["step_id"] == stop_before_id:
            return step
        fly_step(api, ws, step)
    raise RuntimeError(f"never reached step {stop_before_id!r} within {max_steps} steps")


# --------------------------------------------------------------------------- 1


def test_full_mission_completes(app, api):
    new_mission(api)

    with connect(ws_url(app)) as ws:
        luaw = debug_step(api)["luaw"]
        debrief = None
        for _ in range(25):
            step = debug_step(api)
            was_luaw_readback = step["step_id"] == "luaw_readback"
            _, pushes = fly_step(api, ws, step)

            if was_luaw_readback:
                # The FSM has already advanced to takeoff_readback; the
                # scheduled takeoff clearance is purely informational audio
                # that shows up on the WS a few seconds later. Drain it
                # before doing anything else so it doesn't get mistaken for
                # a later push.
                push_msg = json.loads(ws.recv(timeout=20))
                assert push_msg["type"] == "push"
                assert "cleared for takeoff" in push_msg["atc"]["display"].lower()

            complete_pushes = [m for leg, m in pushes if m.get("complete")]
            if complete_pushes:
                debrief = complete_pushes[-1]["debrief"]
                break

        assert debrief is not None, "mission never completed within step budget"
        assert debrief["total"] == 100, debrief

        narrative_msg = json.loads(ws.recv(timeout=30))
        assert narrative_msg["type"] == "debrief_narrative"
        assert narrative_msg["text"].strip()
        print(f"\n[full mission] luaw={luaw} debrief_narrative={narrative_msg['text']!r}")


# --------------------------------------------------------------------------- 2


def test_luaw_takeoff_clearance_timing(app, api):
    for _ in range(40):
        new_mission(api)
        if debug_step(api)["luaw"]:
            break
    else:
        pytest.skip("could not draw a luaw=true mission in 40 tries")

    with connect(ws_url(app)) as ws:
        step = fly_until(api, ws, "luaw_readback")
        assert step["luaw"] is True

        import time
        t0 = time.monotonic()
        _, pushes = fly_step(api, ws, step)
        assert pushes == []  # line_up leg is silent

        push_msg = json.loads(ws.recv(timeout=20))
        elapsed = time.monotonic() - t0

        assert push_msg["type"] == "push"
        assert "cleared for takeoff" in push_msg["atc"]["display"].lower()
        assert 4.0 <= elapsed <= 15.0, f"takeoff clearance arrived after {elapsed:.1f}s"
        print(f"\n[luaw timing] takeoff clearance arrived after {elapsed:.1f}s")


# --------------------------------------------------------------------------- 3


def test_live_llm_coaching(api):
    new_mission(api)
    step = debug_step(api)
    assert step["step_id"] == "clearance_call"

    result = transmit_text(api, step["freq_khz"],
                            "Santa Barbara Clearance, Cessna 67525")
    assert result["passed"] is False
    coach = result["coach"]
    assert coach.strip()
    assert step["example"] in coach, "ideal call must always be embedded via Try: “...”"

    fallback = coach.strip().startswith("Missing:")
    print(f"\n[coaching] {'template fallback' if fallback else 'live LLM tip'} fired:\n{coach}")


# --------------------------------------------------------------------------- 4


def test_frequency_realism_live(api):
    new_mission(api)
    step = debug_step(api)
    assert step["step_id"] == "clearance_call"

    # (a) transmit on Ground while Clearance is expected -> heard, redirected.
    r_ground = transmit_text(api, 121700, "test call")
    assert r_ground["heard"] is True
    assert r_ground["passed"] is False
    assert r_ground["atc"] is not None
    assert "clearance" in r_ground["atc"]["display"].lower()

    wav_bytes = base64.b64decode(r_ground["atc"]["audio_b64"])
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getnchannels() >= 1
        assert w.getsampwidth() == 2  # 16-bit PCM
        assert w.getnframes() > 1000  # non-trivial duration

    # (b) unassigned frequency -> not heard, no ATC reply.
    r_dead = transmit_text(api, 118000, "test call")
    assert r_dead["heard"] is False
    assert r_dead["atc"] is None

    # (c) ATIS frequency -> receive-only, coach explains why.
    r_atis = transmit_text(api, 132650, "test call")
    assert r_atis["heard"] is False
    assert r_atis["atc"] is None
    assert "atis" in r_atis["coach"].lower()


# --------------------------------------------------------------------------- 5


def test_static_and_js_assets(app):
    import httpx

    r = httpx.get(f"{app}/")
    assert r.status_code == 200
    assert "Ground Control" in r.text

    expected = {
        "styles.css": "text/css",
        "app.js": "javascript",
        "radio.js": "javascript",
        "map.js": "javascript",
        "audio.js": "javascript",
        "assets/ksba-diagram.png": "image/png",
    }
    for path, ctype_needle in expected.items():
        resp = httpx.get(f"{app}/{path}")
        assert resp.status_code == 200, path
        assert len(resp.content) > 0, path
        ctype = resp.headers.get("content-type", "")
        assert ctype_needle in ctype.lower(), f"{path}: unexpected content-type {ctype!r}"

    for js in ("app.js", "radio.js", "map.js", "audio.js"):
        path = WEB / js
        proc = subprocess.run(["node", "--check", str(path)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, f"{js}: {proc.stderr}"
