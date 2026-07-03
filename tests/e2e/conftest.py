"""Shared e2e infrastructure.

Expects llama-server ($LLAMA_URL, default :8080) and whisper-server
($WHISPER_URL, default :8081) to already be running — tests skip otherwise.
Each pytest session launches its OWN uvicorn app on a free port so that
concurrent e2e sessions never share global mission state.

WebSocket tests can use the `websockets` package (installed via
uvicorn[standard]): `from websockets.sync.client import connect`.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
LLAMA_URL = os.environ.get("LLAMA_URL", "http://127.0.0.1:8080")
WHISPER_URL = os.environ.get("WHISPER_URL", "http://127.0.0.1:8081")


def _up(url: str) -> bool:
    try:
        return httpx.get(url, timeout=2.0).status_code < 500
    except Exception:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def stack():
    """Skip the whole e2e session unless the model servers are up."""
    missing = []
    if not _up(f"{LLAMA_URL}/health"):
        missing.append(f"llama-server ({LLAMA_URL})")
    if not _up(f"{WHISPER_URL}/"):
        missing.append(f"whisper-server ({WHISPER_URL})")
    if missing:
        pytest.skip("e2e stack not running: " + ", ".join(missing)
                    + " — start it with ./run.sh", allow_module_level=False)


@pytest.fixture(scope="session")
def app(stack) -> str:
    """A private app instance for this test session; yields its base URL."""
    port = _free_port()
    env = os.environ | {"LLAMA_URL": LLAMA_URL, "WHISPER_URL": WHISPER_URL}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server.main:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            if _up(f"{base}/api/health"):
                break
            if proc.poll() is not None:
                raise RuntimeError("app process died during startup")
            time.sleep(0.2)
        else:
            raise RuntimeError("app did not become healthy")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture
def api(app) -> httpx.Client:
    # generous timeout: real STT + LLM + TTS in the loop
    with httpx.Client(base_url=app, timeout=60.0) as client:
        yield client


def new_mission(api: httpx.Client, callsign: str = "N67525",
                coach: bool = True) -> dict:
    r = api.post("/api/mission/new", json={"callsign": callsign, "coach": coach})
    r.raise_for_status()
    return r.json()


def debug_step(api: httpx.Client) -> dict:
    r = api.get("/api/debug/step")
    r.raise_for_status()
    return r.json()


def transmit_text(api: httpx.Client, freq_khz: int, text: str,
                  xpdr_code: str = "", xpdr_mode: str = "") -> dict:
    r = api.post("/api/transmit", data={
        "freq_khz": freq_khz, "text": text,
        "xpdr_code": xpdr_code, "xpdr_mode": xpdr_mode,
    })
    r.raise_for_status()
    return r.json()


def transmit_wav(api: httpx.Client, freq_khz: int, wav: bytes,
                 xpdr_code: str = "", xpdr_mode: str = "") -> dict:
    r = api.post(
        "/api/transmit",
        data={"freq_khz": freq_khz, "text": "",
              "xpdr_code": xpdr_code, "xpdr_mode": xpdr_mode},
        files={"audio": ("call.wav", wav, "audio/wav")},
    )
    r.raise_for_status()
    return r.json()
