"""Ground Control web server: game API + WebSocket pushes + static UI."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import airport, llm, stt, tts
from .scenario import AtcReply, Mission

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Ground Control")

mission: Mission | None = None
sockets: set[WebSocket] = set()


async def _speak(reply: AtcReply) -> dict:
    """Serialize an ATC reply with synthesized audio."""
    audio = await asyncio.to_thread(tts.synthesize, reply.spoken, reply.facility)
    return {
        "facility": reply.facility,
        "display": reply.display,
        "delay_ms": reply.delay_ms,
        "audio_b64": base64.b64encode(audio).decode(),
    }


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
    payload = {"type": "push", "atc": await _speak(reply),
               "coach": m.step().coach if m.coach_mode else ""}
    await _broadcast(payload)


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "mission": mission is not None}


@app.post("/api/mission/new")
async def new_mission(payload: dict) -> dict:
    global mission
    mission = Mission(
        callsign=(payload.get("callsign") or "N67525").strip() or "N67525",
        coach=bool(payload.get("coach", True)),
    )
    # Pre-warm the ATIS recording so tuning 132.65 is instant.
    display, spoken = mission.atis_text()
    asyncio.get_running_loop().run_in_executor(None, tts.synthesize, spoken, "atis")
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
        "luaw": mission.luaw,
        "complete": mission.complete,
    })


@app.get("/api/atis.wav")
async def atis_wav() -> Response:
    if mission is None:
        return Response(status_code=404)
    _, spoken = mission.atis_text()
    audio = await asyncio.to_thread(tts.synthesize, spoken, "atis")
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
        transcript = await stt.transcribe(await audio.read())
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
                    if narrative:
                        await ws.send_json({"type": "debrief_narrative",
                                            "text": narrative})
    except WebSocketDisconnect:
        pass
    finally:
        sockets.discard(ws)


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
