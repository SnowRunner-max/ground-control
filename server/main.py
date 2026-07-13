"""Ground Control web server: game API + WebSocket pushes + static UI."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import airport, llm, stt, tts
from .scenario import AtcReply, Mission

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Ground Control")

mission: Mission | None = None
sockets: set[WebSocket] = set()


async def _speak(reply: AtcReply) -> dict:
    """Serialize an ATC reply; preserve its text if TTS is unavailable."""
    out = {
        "facility": reply.facility,
        "display": reply.display,
        "delay_ms": reply.delay_ms,
        "audio_b64": None,
        "audio_unavailable": False,
    }
    try:
        audio = await asyncio.to_thread(tts.synthesize, reply.spoken, reply.facility)
        out["audio_b64"] = base64.b64encode(audio).decode()
    except Exception:
        out["audio_unavailable"] = True
    return out


async def _service_up(url: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            return (await client.get(url)).status_code < 500
    except Exception:
        return False


async def _broadcast(payload: dict) -> None:
    dead = []
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        sockets.discard(ws)


async def _scheduled_push(m: Mission, push: dict) -> None:
    """e.g. line-up-and-wait -> takeoff clearance a few seconds later."""
    await asyncio.sleep(push.get("delay_s", 6.0))
    if mission is not m or m.complete:
        return
    reply = m.apply_push(push)
    if reply is None:
        return
    payload = {"type": "push", "atc": await _speak(reply),
               "coach": m.step().coach if m.coach_mode else ""}
    await _broadcast(payload)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "mission": mission is not None}


@app.get("/api/readiness")
async def readiness() -> dict:
    llama_up, whisper_up = await asyncio.gather(
        _service_up(f"{llm.LLAMA_URL}/health"),
        _service_up(f"{stt.WHISPER_URL}/"),
    )
    tts_ready = all((ROOT / "models" / name).is_file() for name in (
        "kokoro-v1.0.onnx", "voices-v1.0.bin"))
    services = {"llm": llama_up, "stt": whisper_up, "tts": tts_ready}
    return {
        "ready": all(services.values()),
        "services": services,
        "degraded": [name for name, available in services.items() if not available],
    }


@app.post("/api/mission/new")
async def new_mission(payload: dict) -> dict:
    global mission
    wind_dir = payload.get("wind_dir")
    wind_speed = payload.get("wind_speed")
    if (wind_dir is None) != (wind_speed is None):
        raise HTTPException(
            status_code=400,
            detail="wind_dir and wind_speed must be supplied together",
        )
    try:
        wind = None if wind_dir is None else (int(wind_dir), int(wind_speed))
        seed = None if payload.get("seed") is None else int(payload["seed"])
        runway_override = payload.get("runway") or None
        mission = Mission(
            callsign=(payload.get("callsign") or "N67525").strip() or "N67525",
            coach=bool(payload.get("coach", True)),
            seed=seed,
            wind=wind,
            runway=runway_override,
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    display, _ = mission.atis_text()
    brief = mission.brief()
    brief["atis_display"] = display
    return brief


@app.get("/api/debug/step")
async def debug_step() -> JSONResponse:
    """Test support: what the sim expects next (used by the e2e robo-pilot)."""
    if mission is None:
        return JSONResponse({"error": "no mission"}, status_code=400)
    s = mission.step()
    return JSONResponse({
        "step_id": s.id,
        "facility": s.facility,
        "freq_khz": airport.FREQS[s.facility],
        "example": s.example,
        "squawk": mission.squawk,
        "atis_letter": mission.wx.letter,
        "runway": mission.runway,
        "runway_selection": mission.runway_selection.as_dict(),
        "luaw": mission.luaw,
        "awaiting_takeoff_clearance": mission.awaiting_takeoff_clearance,
        "complete": mission.complete,
    })


@app.get("/api/atis.wav")
async def atis_wav() -> Response:
    if mission is None:
        return Response(status_code=404)
    _, spoken = mission.atis_text()
    try:
        audio = await asyncio.to_thread(tts.synthesize, spoken, "atis")
    except Exception:
        return JSONResponse(
            {"error": "ATIS audio is unavailable; use the displayed ATIS text.",
             "code": "tts_unavailable"},
            status_code=503,
        )
    return Response(content=audio, media_type="audio/wav")


@app.post("/api/transmit")
async def transmit(
    freq_khz: int = Form(...),
    xpdr_code: str = Form(""),
    xpdr_mode: str = Form(""),
    text: str = Form(""),
    audio: UploadFile | None = File(None),
) -> JSONResponse:
    if mission is None:
        return JSONResponse({"error": "no mission"}, status_code=400)

    transcript = text.strip()
    if not transcript and audio is not None:
        try:
            transcript = await stt.transcribe(await audio.read())
        except Exception:
            return JSONResponse(
                {"error": "Speech recognition is unavailable; use the text box.",
                 "code": "stt_unavailable"},
                status_code=503,
            )
    if not transcript:
        return JSONResponse({"transcript": "", "heard": False,
                             "coach": "I didn't catch any speech — hold the PTT while you talk."})

    result = mission.handle_transmission(freq_khz, transcript, xpdr_code, xpdr_mode)

    out: dict = {
        "transcript": transcript,
        "heard": result["heard"],
        "passed": result["passed"],
        "score": result["score"],
        "coach": result["coach"],
        "missing": result["missing"],
        "actions": result["actions"],
        "step_id": result["step_id"],
        "atc": None,
    }
    if result["atc"] is not None:
        out["atc"] = await _speak(result["atc"])

    # On a failed attempt, let the local LLM turn the correction into a CFI-style tip.
    if result["passed"] is False and result["missing"] and mission.coach_mode:
        step = mission.step()
        tip = await llm.coach_feedback(step.coach, step.example, transcript,
                                       result["missing"])
        if tip:
            out["coach"] = f"{tip}\nTry: “{step.example}”"

    if result.get("push"):
        asyncio.create_task(_scheduled_push(mission, result["push"]))

    return JSONResponse(out)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    sockets.add(ws)
    try:
        while True:
            msg = await ws.receive_json()
            if msg.get("type") == "leg_complete" and mission is not None:
                push = mission.leg_complete(msg.get("leg", ""))
                if not push:
                    continue
                payload: dict = {"type": "push", "coach": push.get("coach", "")
                                 if mission.coach_mode else ""}
                if push.get("atc"):
                    payload["atc"] = await _speak(push["atc"])
                if push.get("complete"):
                    payload["complete"] = True
                    payload["debrief"] = push["debrief"]
                await ws.send_json(payload)
                if push.get("complete"):
                    narrative = await llm.debrief_narrative(
                        push["debrief"]["steps"], push["debrief"]["total"])
                    await ws.send_json({
                        "type": "debrief_narrative",
                        "text": narrative or (
                            "Instructor narrative is unavailable. Review the "
                            "exchange scores below for your debrief."),
                    })
    except WebSocketDisconnect:
        pass
    finally:
        sockets.discard(ws)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
