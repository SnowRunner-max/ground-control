"""API surface tests with TTS and LLM stubbed out (no models needed)."""

import base64

import pytest
from fastapi.testclient import TestClient

from server import airport, main


FAKE_WAV = b"RIFFfakewav"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main.tts, "synthesize", lambda text, facility: FAKE_WAV)

    async def no_tip(*args, **kwargs):
        return None

    async def narrative(*args, **kwargs):
        return "Nice flying out there."

    monkeypatch.setattr(main.llm, "coach_feedback", no_tip)
    monkeypatch.setattr(main.llm, "debrief_narrative", narrative)
    main.mission = None
    with TestClient(main.app) as c:
        yield c


def new_mission(client) -> dict:
    r = client.post("/api/mission/new", json={"callsign": "N67525", "coach": True})
    assert r.status_code == 200
    return r.json()


def transmit(client, freq_khz, text, code="", mode=""):
    r = client.post("/api/transmit", data={
        "freq_khz": freq_khz, "text": text, "xpdr_code": code, "xpdr_mode": mode,
    })
    assert r.status_code == 200
    return r.json()


class TestApi:
    def test_health(self, client):
        assert client.get("/api/health").json() == {"ok": True, "mission": False}

    def test_index_served(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Ground Control" in r.text

    def test_new_mission_brief(self, client):
        b = new_mission(client)
        assert b["callsign"] == "N67525"
        assert b["freqs"]["tower"] == "119.7"
        assert "atis_display" in b
        assert b["plane"]["view"] == "ground"

    def test_brief_includes_chart_info_for_drawer(self, client):
        b = new_mission(client)
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
        assert "12.2" in notes_blob

    def test_chart_info_frequencies_stay_consistent_with_freqs(self):
        # Guards the FREQS -> CHART_INFO derivation against drift/mislabeling.
        by_label = {f["label"]: f["value"] for f in airport.CHART_INFO["frequencies"]}
        assert by_label["ATIS"] == airport.mhz(airport.FREQS["atis"])
        assert by_label["Clearance"] == airport.mhz(airport.FREQS["clearance"])
        assert by_label["Ground"] == airport.mhz(airport.FREQS["ground"])
        assert by_label["Approach"] == airport.mhz(airport.FREQS["approach"])
        assert by_label["Tower"] == f"{airport.mhz(airport.FREQS['tower'])} / 254.35"

    def test_atis_wav(self, client):
        new_mission(client)
        r = client.get("/api/atis.wav")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content == FAKE_WAV

    def test_atis_wav_without_mission_404s(self, client):
        assert client.get("/api/atis.wav").status_code == 404

    def test_transmit_without_mission_400s(self, client):
        r = client.post("/api/transmit", data={"freq_khz": 132900, "text": "hi"})
        assert r.status_code == 400

    def test_transmit_happy_call(self, client):
        new_mission(client)
        step = main.mission.steps["clearance_call"]
        res = transmit(client, airport.FREQS["clearance"], step.example)
        assert res["passed"] is True
        assert res["atc"]["facility"] == "clearance"
        assert base64.b64decode(res["atc"]["audio_b64"]) == FAKE_WAV
        assert main.mission.current == "clearance_readback"

    def test_transmit_empty_text(self, client):
        new_mission(client)
        res = transmit(client, airport.FREQS["clearance"], "   ")
        assert res["heard"] is False
        assert "PTT" in res["coach"]

    def test_transmit_wrong_freq_static(self, client):
        new_mission(client)
        res = transmit(client, 118000, "hello anyone")
        assert res["heard"] is False
        assert res["atc"] is None

    def test_ws_leg_complete_coach_push(self, client):
        new_mission(client)
        m = main.mission
        # advance through the taxi clearance so taxi_out is the active leg
        for step_id in ("clearance_call", "clearance_readback", "ground_call",
                        "ground_readback"):
            step = m.steps[step_id]
            res = transmit(client, airport.FREQS[step.facility], step.example,
                           m.squawk, "ALT")
            assert res["passed"] is True, (step_id, res["missing"])
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "leg_complete", "leg": "taxi_out"})
            msg = ws.receive_json()
            assert msg["type"] == "push"
            assert "Tower" in msg["coach"]

    def test_ws_mission_complete_debrief(self, client):
        new_mission(client)
        m = main.mission
        # fly the mission via the HTTP API to exercise the real transmit path
        for _ in range(30):
            if m.current == "taxi_in_readback":
                break
            step = m.steps[m.current]
            res = transmit(client, airport.FREQS[step.facility], step.example,
                           m.squawk, "ALT")
            assert res["passed"] is True, (step.id, res["missing"])
            for action in res["actions"]:
                if action.get("leg") and action["leg"] != "taxi_in":
                    m.leg_complete(action["leg"])
        # final readback, then the client reports the last taxi leg done
        step = m.steps["taxi_in_readback"]
        res = transmit(client, airport.FREQS[step.facility], step.example,
                       m.squawk, "ALT")
        assert res["passed"] is True

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "leg_complete", "leg": "taxi_in"})
            msg = ws.receive_json()
            assert msg["type"] == "push"
            assert msg["complete"] is True
            assert msg["debrief"]["total"] == 100
            msg2 = ws.receive_json()
            assert msg2 == {"type": "debrief_narrative",
                            "text": "Nice flying out there."}
