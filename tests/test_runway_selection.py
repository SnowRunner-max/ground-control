"""Weather-first runway selection and mission integration tests."""

from __future__ import annotations

from dataclasses import replace
from math import isclose

import pytest

from server.atis import Weather, make_weather
from server.runway_selection import RUNWAY_POLICIES, select_runway, wind_components
from server.scenario import Mission


BASE_WEATHER = Weather(
    letter="bravo",
    time_z="1853",
    wind_dir=250,
    wind_speed=10,
    visibility=10,
    sky="clear",
    sky_spoken="sky clear",
    temp=20,
    dewpoint=14,
    altimeter="29.92",
)


def test_wind_components_aligned_opposite_and_crosswind():
    headwind, crosswind = wind_components(255, 10, 255)
    assert isclose(headwind, 10.0, abs_tol=1e-9)
    assert isclose(crosswind, 0.0, abs_tol=1e-9)

    headwind, crosswind = wind_components(75, 10, 255)
    assert isclose(headwind, -10.0, abs_tol=1e-9)
    assert isclose(crosswind, 0.0, abs_tol=1e-9)

    headwind, crosswind = wind_components(165, 10, 255)
    assert isclose(headwind, 0.0, abs_tol=1e-9)
    assert isclose(crosswind, 10.0, abs_tol=1e-9)


@pytest.mark.parametrize(
    ("wind_dir", "expected"),
    [(250, "25"), (150, "15L"), (205, "25")],
)
def test_runway_selection_uses_components_then_explicit_preference(wind_dir, expected):
    selection = select_runway(wind_dir, 10)
    assert selection.selected_runway == expected
    assert selection.overridden is False
    assert "best eligible score" in selection.reason


def test_no_supported_runway_rejects_weather_outside_modeled_limits():
    with pytest.raises(ValueError, match="modeled limits"):
        select_runway(0, 30)


def test_explicit_training_override_is_visible():
    selection = select_runway(250, 10, override="15l")
    assert selection.selected_runway == "15L"
    assert selection.overridden is True
    assert selection.reason == "explicit training override"


def test_weather_generation_is_independent_and_always_selectable():
    import random

    for seed in range(500):
        weather = make_weather(random.Random(seed))
        selection = select_runway(weather.wind_dir, weather.wind_speed)
        selected = next(
            candidate
            for candidate in selection.candidates
            if candidate.runway == selection.selected_runway
        )
        policy = RUNWAY_POLICIES[selected.runway]
        assert selected.eligible
        assert selected.tailwind_kt <= policy.max_tailwind_kt
        assert selected.crosswind_kt <= policy.max_crosswind_kt


def test_mission_selects_runway_after_injected_weather():
    west_wind = Mission(seed=10, weather=BASE_WEATHER)
    south_wind = Mission(
        seed=10,
        weather=replace(BASE_WEATHER, wind_dir=150),
    )
    assert west_wind.wx is BASE_WEATHER
    assert west_wind.runway == "25"
    assert south_wind.runway == "15L"
    assert west_wind.taxi_out_route.runway == west_wind.runway
    assert south_wind.taxi_out_route.runway == south_wind.runway


def test_mission_wind_and_runway_overrides_are_deterministic():
    first = Mission(seed=42, wind=(250, 9), runway="15L")
    second = Mission(seed=42, wind=(250, 9), runway="15L")
    assert first.wx == second.wx
    assert first.runway == second.runway == "15L"
    assert first.runway_selection == second.runway_selection
    assert first.squawk == second.squawk
    assert first.luaw == second.luaw


def test_same_seed_reproduces_weather_runway_and_route():
    first = Mission(seed=123)
    second = Mission(seed=123)
    assert first.wx == second.wx
    assert first.runway == second.runway
    assert first.runway_selection == second.runway_selection
    assert first.taxi_out_route == second.taxi_out_route
