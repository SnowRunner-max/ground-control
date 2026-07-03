"""Shared helpers: drive a Mission through its own ideal example calls."""

from __future__ import annotations

import pytest

from server import airport
from server.scenario import Mission


def find_seed(config: str | None = None, luaw: bool | None = None) -> int:
    """Find a deterministic seed producing the requested mission variant."""
    for seed in range(200):
        m = Mission(seed=seed)
        if config is not None and m.config_id != config:
            continue
        if luaw is not None and m.luaw != luaw:
            continue
        return seed
    raise AssertionError(f"no seed found for config={config} luaw={luaw}")


def fly_mission(m: Mission) -> list[dict]:
    """Fly the whole mission by transmitting each step's ideal example call.

    Simulates the client: applies scheduled pushes immediately and reports
    every named movement leg as complete. Returns leg_complete pushes seen.
    """
    pushes = []
    for _ in range(40):  # hard stop against infinite loops
        if m.complete:
            break
        step = m.steps[m.current]
        freq = airport.FREQS[step.facility]
        result = m.handle_transmission(freq, step.example, m.squawk, "ALT")
        assert result["passed"], (
            f"ideal call failed at {step.id}: missing {result['missing']} "
            f"(example: {step.example!r})"
        )
        if result["push"]:
            m.apply_push(result["push"])
        for action in result["actions"]:
            if action.get("leg"):
                push = m.leg_complete(action["leg"])
                if push:
                    pushes.append(push)
    assert m.complete, f"mission stalled at {m.current}"
    return pushes


@pytest.fixture
def mission25() -> Mission:
    return Mission(seed=find_seed(config="25", luaw=False))


@pytest.fixture
def mission25_luaw() -> Mission:
    return Mission(seed=find_seed(config="25", luaw=True))


@pytest.fixture
def mission15() -> Mission:
    return Mission(seed=find_seed(config="15L"))
