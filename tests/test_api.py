"""API surface tests with TTS and LLM stubbed out (no models needed)."""

import base64

import httpx
import pytest
from fastapi import WebSocketDisconnect

from server import airport, main


FAKE_WAV = b"RIFFfakewav"


@pytest.fixture
async def client(monkeypatch):
    monkeypatch.setattr(main.tts, "synthesize", lambda text, facility: FAKE_WAV)

    async def inline_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(main.asyncio, "to_thread", inline_thread)

    async def no_tip(*args, **kwargs):
        return None

    async def narrative(*args, **kwargs):
        return "Nice flying out there."

    monkeypatch.setattr(main.llm, "coach_feedback", no_tip)
    monkeypatch.setattr(main.llm, "debrief_narrative", narrative)
    main.mission = None
    transport = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(
            transport=transport, base_url="http://test") as c:
        yield c


async def new_mission(client, **overrides) -> dict:
    payload = {"callsign": "N67525", "coach": True, **overrides}
    r = await client.post(
        "/api/mission/new", json=payload)
    assert r.status_code == 200
    return r.json()


async def transmit(client, freq_khz, text, code="", mode=""):
    r = await client.post("/api/transmit", data={
        "freq_khz": freq_khz, "text": text, "xpdr_code": code, "xpdr_mode": mode,
    })
    assert r.status_code == 200
    return r.json()


class FakeWebSocket:
    """Minimal WebSocket protocol fake for exercising the endpoint loop."""

    def __init__(self, *messages):
        self.incoming = list(messages)
        self.sent = []

    async def accept(self):
        pass

    async def receive_json(self):
        if self.incoming:
            return self.incoming.pop(0)
        raise WebSocketDisconnect()

    async def send_json(self, payload):
        self.sent.append(payload)


class TestApi:
    async def test_health(self, client):
        assert (await client.get("/api/health")).json() == {
            "ok": True, "mission": False}

    async def test_readiness_reports_service_state(self, client, monkeypatch):
        async def up(url):
            return "8080" in url

        monkeypatch.setattr(main, "_service_up", up)
        result = (await client.get("/api/readiness")).json()
        assert result["services"]["llm"] is True
        assert result["services"]["stt"] is False
        assert "stt" in result["degraded"]

    def test_index_asset_exists(self):
        text = (main.ROOT / "web" / "index.html").read_text()
        assert "Ground Control" in text

    async def test_new_mission_brief(self, client):
        b = await new_mission(client)
        assert b["callsign"] == "N67525"
        assert b["freqs"]["tower"] == "119.7"
        assert "atis_display" in b
        assert b["plane"]["view"] == "ground"
        assert b["runway"] == b["runway_selection"]["selected_runway"]
        assert b["runway_selection"]["overridden"] is False

    async def test_new_mission_weather_and_runway_overrides(self, client):
        south = await new_mission(client, seed=7, wind_dir=150, wind_speed=10)
        assert south["runway"] == "15L"
        assert south["runway_selection"]["wind_dir"] == 150
        assert south["runway_selection"]["overridden"] is False

        forced = await new_mission(
            client, seed=7, wind_dir=250, wind_speed=10, runway="15L")
        assert forced["runway"] == "15L"
        assert forced["runway_selection"]["overridden"] is True
        assert forced["runway_selection"]["reason"] == "explicit training override"

    async def test_new_mission_rejects_partial_wind_override(self, client):
        response = await client.post(
            "/api/mission/new",
            json={"callsign": "N67525", "wind_dir": 250},
        )
        assert response.status_code == 400
        assert "supplied together" in response.json()["detail"]

    async def test_debug_step_exposes_runway_selection(self, client):
        await new_mission(client, wind_dir=250, wind_speed=10)
        result = (await client.get("/api/debug/step")).json()
        assert result["runway"] == "25"
        assert result["runway_selection"]["selected_runway"] == "25"
        assert result["runway_selection"]["candidates"]

    async def test_brief_includes_chart_info_for_drawer(self, client):
        b = await new_mission(client)
        ci = b["chart_info"]
        # frequencies for the drawer, including the tower UHF not in the sim map
        labels = {f["label"]: f["value"] for f in ci["frequencies"]}
        assert labels["ATIS"] == "132.65"
        assert labels["Tower"] == "119.7 / 254.35"
        assert labels["Clearance"] == "132.9"
        # field + runway reference
        assert ci["field"]["elevation_ft"] == 14
        rwys = {r["id"]: r for r in ci["runways"]}
        assert rwys["7-25"]["dimensions_ft"] == "6052 x 150"
        assert "15L-33R" in rwys and "15R-33L" in rwys
        # notes carry the crossing-caution text and magnetic variation
        notes_blob = " ".join(ci["notes"]).upper()
        assert "READBACK" in notes_blob and "CROSSING" in notes_blob
        assert "14° E" in notes_blob
        assert "CYCLE 2607" in notes_blob

    def test_chart_info_frequencies_stay_consistent_with_freqs(self):
        # Guards the FREQS -> CHART_INFO derivation against drift/mislabeling.
        by_label = {f["label"]: f["value"] for f in airport.CHART_INFO["frequencies"]}
        assert by_label["ATIS"] == airport.mhz(airport.FREQS["atis"])
        assert by_label["Clearance"] == airport.mhz(airport.FREQS["clearance"])
        assert by_label["Ground"] == airport.mhz(airport.FREQS["ground"])
        assert by_label["Approach"] == airport.mhz(airport.FREQS["approach"])
        assert by_label["Tower"] == f"{airport.mhz(airport.FREQS['tower'])} / 254.35"

    async def test_atis_wav(self, client):
        await new_mission(client)
        r = await client.get("/api/atis.wav")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content == FAKE_WAV

    async def test_atis_wav_without_mission_404s(self, client):
        assert (await client.get("/api/atis.wav")).status_code == 404

    async def test_atis_tts_failure_returns_text_fallback(self, client, monkeypatch):
        await new_mission(client)

        def fail(*args, **kwargs):
            raise RuntimeError("tts down")

        monkeypatch.setattr(main.tts, "synthesize", fail)
        r = await client.get("/api/atis.wav")
        assert r.status_code == 503
        assert r.json()["code"] == "tts_unavailable"

    async def test_transmit_without_mission_400s(self, client):
        r = await client.post(
            "/api/transmit", data={"freq_khz": 132900, "text": "hi"})
        assert r.status_code == 400

    async def test_transmit_happy_call(self, client):
        await new_mission(client)
        step = main.mission.steps["clearance_call"]
        res = await transmit(client, airport.FREQS["clearance"], step.example)
        assert res["passed"] is True
        assert res["atc"]["facility"] == "clearance"
        assert base64.b64decode(res["atc"]["audio_b64"]) == FAKE_WAV
        assert main.mission.current == "clearance_readback"

    async def test_transmit_preserves_atc_text_when_tts_fails(self, client, monkeypatch):
        await new_mission(client)

        def fail(*args, **kwargs):
            raise RuntimeError("tts down")

        monkeypatch.setattr(main.tts, "synthesize", fail)
        step = main.mission.steps["clearance_call"]
        res = await transmit(client, airport.FREQS["clearance"], step.example)
        assert res["passed"] is True
        assert res["atc"]["display"]
        assert res["atc"]["audio_b64"] is None
        assert res["atc"]["audio_unavailable"] is True

    async def test_voice_transmit_reports_stt_unavailable(self, client, monkeypatch):
        await new_mission(client)

        async def fail(*args, **kwargs):
            raise RuntimeError("stt down")

        monkeypatch.setattr(main.stt, "transcribe", fail)
        r = await client.post(
            "/api/transmit",
            data={"freq_khz": airport.FREQS["clearance"], "text": ""},
            files={"audio": ("call.wav", b"RIFFfake", "audio/wav")},
        )
        assert r.status_code == 503
        assert r.json()["code"] == "stt_unavailable"

    async def test_transmit_empty_text(self, client):
        await new_mission(client)
        res = await transmit(client, airport.FREQS["clearance"], "   ")
        assert res["heard"] is False
        assert "PTT" in res["coach"]

    async def test_transmit_wrong_freq_static(self, client):
        await new_mission(client)
        res = await transmit(client, 118000, "hello anyone")
        assert res["heard"] is False
        assert res["atc"] is None

    async def test_ws_leg_complete_coach_push(self, client):
        await new_mission(client)
        m = main.mission
        # advance through the taxi clearance so taxi_out is the active leg
        for step_id in ("clearance_call", "clearance_readback", "ground_call",
                        "ground_readback"):
            step = m.steps[step_id]
            res = await transmit(client, airport.FREQS[step.facility], step.example,
                                 m.squawk, "ALT")
            assert res["passed"] is True, (step_id, res["missing"])
        ws = FakeWebSocket({"type": "leg_complete", "leg": "taxi_out"})
        await main.ws_endpoint(ws)
        assert ws.sent[0]["type"] == "push"
        assert "Tower" in ws.sent[0]["coach"]

    async def test_ws_mission_complete_debrief(self, client):
        await new_mission(client)
        m = main.mission
        # fly the mission via the HTTP API to exercise the real transmit path
        for _ in range(30):
            if m.current == "taxi_in_readback":
                break
            step = m.steps[m.current]
            res = await transmit(client, airport.FREQS[step.facility], step.example,
                                 m.squawk, "ALT")
            assert res["passed"] is True, (step.id, res["missing"])
            if m.awaiting_takeoff_clearance:
                assert m.apply_push(m.steps["luaw_readback"].push_after) is not None
            for action in res["actions"]:
                if action.get("leg") and action["leg"] != "taxi_in":
                    m.leg_complete(action["leg"])
        # final readback, then the client reports the last taxi leg done
        step = m.steps["taxi_in_readback"]
        res = await transmit(client, airport.FREQS[step.facility], step.example,
                             m.squawk, "ALT")
        assert res["passed"] is True

        ws = FakeWebSocket({"type": "leg_complete", "leg": "taxi_in"})
        await main.ws_endpoint(ws)
        assert ws.sent[0]["type"] == "push"
        assert ws.sent[0]["complete"] is True
        assert ws.sent[0]["debrief"]["total"] == 100
        assert ws.sent[1] == {"type": "debrief_narrative",
                              "text": "Nice flying out there."}

    async def test_ws_debrief_has_fallback_when_llm_is_down(
            self, client, monkeypatch):
        await new_mission(client)
        m = main.mission
        m.current = "taxi_in_readback"
        m.pending_legs["taxi_in"] = "taxi_in_readback"

        async def no_narrative(*args, **kwargs):
            return None

        monkeypatch.setattr(main.llm, "debrief_narrative", no_narrative)
        ws = FakeWebSocket({"type": "leg_complete", "leg": "taxi_in"})
        await main.ws_endpoint(ws)
        assert ws.sent[0]["complete"] is True
        assert "unavailable" in ws.sent[1]["text"].lower()
