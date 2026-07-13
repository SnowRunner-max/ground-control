"""Failure paths: frequency, readbacks, state integrity, and scoring."""

import pytest

from server import airport
from server.scenario import Mission

from .conftest import find_seed


def make_mission(**kw) -> Mission:
    return Mission(seed=find_seed(**kw))


def advance_to(m: Mission, target: str) -> None:
    """Drive ideal calls and movement acknowledgements up to ``target``."""
    for _ in range(30):
        if m.current == target:
            return
        step = m.step()
        result = m.handle_transmission(
            airport.FREQS[step.facility], step.example, m.squawk, "ALT")
        assert result["passed"] is True, (step.id, result["missing"])
        if result["push"]:
            assert m.apply_push(result["push"]) is not None
        for action in result["actions"]:
            if action.get("leg"):
                m.leg_complete(action["leg"])
    raise AssertionError(f"mission never reached {target}")


class TestWrongFrequency:
    def test_unassigned_freq_is_static(self):
        m = make_mission(config="25")
        r = m.handle_transmission(118000, "Santa Barbara Clearance, Cessna 67525")
        assert r["heard"] is False
        assert r["atc"] is None
        assert "132.9" in r["coach"]

    def test_other_facility_redirects(self):
        m = make_mission(config="25")
        r = m.handle_transmission(airport.FREQS["ground"],
                                  "Santa Barbara Ground, Cessna 67525, ready to taxi")
        assert r["heard"] is True
        assert "Santa Barbara Ground" in r["atc"].display
        assert "Clearance" in r["atc"].display  # redirected to the right facility

    def test_transmitting_on_atis_goes_nowhere(self):
        m = make_mission(config="25")
        r = m.handle_transmission(airport.FREQS["atis"], "anyone there?")
        assert r["heard"] is False
        assert "ATIS" in r["coach"]

    def test_wrong_freq_does_not_advance(self):
        m = make_mission(config="25")
        m.handle_transmission(118000, "hello")
        assert m.current == "clearance_call"


class TestBadReadbacks:
    def test_gibberish_gets_say_again(self):
        m = make_mission(config="25")
        r = m.handle_transmission(airport.FREQS["clearance"], "uh hello tower guy")
        assert r["passed"] is False
        assert "say again" in r["atc"].display.lower()

    def test_missing_items_listed_and_negative(self):
        m = make_mission(config="25")
        step = m.steps["clearance_call"]
        m.handle_transmission(airport.FREQS["clearance"], step.example, "", "")
        # readback with the squawk missing
        r = m.handle_transmission(
            airport.FREQS["clearance"],
            "at or below two thousand five hundred, departure one two five point four, Cessna 525")
        assert r["passed"] is False
        assert any("squawk" in miss.lower() for miss in r["missing"])
        assert "negative" in r["atc"].display.lower()
        assert m.current == "clearance_readback"  # no advance

    def test_retry_costs_25_points(self):
        m = make_mission(config="25")
        step = m.steps["clearance_call"]
        m.handle_transmission(airport.FREQS["clearance"], step.example)
        m.handle_transmission(airport.FREQS["clearance"], "Cessna 525 roger")  # fail
        r = m.handle_transmission(airport.FREQS["clearance"],
                                  m.steps["clearance_readback"].example)  # pass
        assert r["passed"] is True
        assert r["score"] == 75

    def test_missed_optional_costs_10(self):
        m = make_mission(config="25")
        r = m.handle_transmission(
            airport.FREQS["clearance"],
            # valid but no direction-of-flight or altitude: two optional items missed
            f"Santa Barbara Clearance, Cessna 67525, information {m.wx.letter}, "
            f"request VFR departure")
        assert r["passed"] is True
        assert r["score"] == 80

    def test_coach_shows_ideal_call(self):
        m = make_mission(config="25")
        r = m.handle_transmission(airport.FREQS["clearance"], "Cessna 525, hi")
        assert m.steps["clearance_call"].example.split(",")[0] in r["coach"]

    def test_taxi_out_requires_complete_current_route(self):
        m = make_mission(config="25", luaw=False)
        advance_to(m, "ground_readback")
        result = m.handle_transmission(
            airport.FREQS["ground"],
            f"Runway 25 via Charlie Foxtrot Bravo, Cessna {m.tail_short}.",
            m.squawk,
            "ALT",
        )
        assert result["passed"] is False
        assert any("bravo one" in item.lower() for item in result["missing"])

    def test_taxi_in_requires_every_explicit_runway_crossing(self):
        m = make_mission(config="25", luaw=False)
        advance_to(m, "taxi_in_readback")
        result = m.handle_transmission(
            airport.FREQS["ground"],
            f"Taxi to Above All via Charlie, Cessna {m.tail_short}.",
            m.squawk,
            "ALT",
        )
        assert result["passed"] is False
        missing = " ".join(result["missing"]).lower()
        assert "15 right" in missing
        assert "15 left" in missing

    @pytest.mark.parametrize(
        ("config", "luaw", "target", "bad_call", "missing"),
        [
            ("25", False, "clearance_readback",
             lambda m: (f"Maintain VFR 2,500, departure frequency 125.4, "
                        f"squawk {m.squawk}, Cessna {m.tail_short}."),
             "at or below"),
            ("25", False, "tower_checkin",
             lambda m: (f"Santa Barbara Tower, Cessna {m.tail}, "
                        "ready for departure."),
             "holding short"),
            ("25", True, "luaw_readback",
             lambda m: f"Line up and wait, Cessna {m.tail_short}.",
             "runway"),
            ("25", False, "takeoff_readback",
             lambda m: (f"Cleared for takeoff Runway {m.runway}, "
                        f"Cessna {m.tail_short}."),
             "left turn"),
            ("25", False, "dep_ack",
             lambda m: f"Own navigation, Cessna {m.tail_short}.",
             "2,500"),
            ("25", False, "arrival_readback",
             lambda m: (f"Straight-in Runway {m.runway}, "
                        f"Cessna {m.tail_short}."),
             "three mile"),
            ("25", False, "landing_readback",
             lambda m: f"Cleared to land, Cessna {m.tail_short}.",
             "runway"),
        ],
    )
    def test_safety_critical_omissions_fail(
            self, config, luaw, target, bad_call, missing):
        m = make_mission(config=config, luaw=luaw)
        advance_to(m, target)
        step = m.step()
        result = m.handle_transmission(
            airport.FREQS[step.facility], bad_call(m), m.squawk, "ALT")
        assert result["passed"] is False
        assert any(missing in item.lower() for item in result["missing"])
        assert m.current == target


class TestStateIntegrity:
    def test_luaw_waits_for_clearance_and_stale_push_cannot_rewind(self):
        m = make_mission(config="25", luaw=True)
        advance_to(m, "luaw_readback")

        luaw = m.handle_transmission(
            airport.FREQS["tower"], m.step().example, m.squawk, "ALT")
        assert luaw["passed"] is True
        assert m.current == "takeoff_readback"
        assert m.awaiting_takeoff_clearance is True
        score_count = len(m.scores)

        early = m.handle_transmission(
            airport.FREQS["tower"], m.step().example, m.squawk, "ALT")
        assert early["passed"] is None
        assert len(m.scores) == score_count
        assert m.attempts_failed == 0
        assert m.current == "takeoff_readback"

        assert m.apply_push(luaw["push"]) is not None
        assert m.awaiting_takeoff_clearance is False
        takeoff = m.handle_transmission(
            airport.FREQS["tower"], m.step().example, m.squawk, "ALT")
        assert takeoff["passed"] is True
        assert m.current == "handoff_readback"
        assert m.apply_push(luaw["push"]) is None
        assert m.current == "handoff_readback"

    def test_only_issued_movement_legs_are_accepted_once(self):
        m = make_mission(config="25", luaw=False)
        assert m.leg_complete("taxi_in") is None
        assert m.complete is False

        advance_to(m, "ground_readback")
        result = m.handle_transmission(
            airport.FREQS["ground"], m.step().example, m.squawk, "ALT")
        assert result["passed"] is True
        assert "taxi_out" in m.pending_legs
        assert m.leg_complete("taxi_out") is not None
        assert m.leg_complete("taxi_out") is None

    def test_issued_leg_becomes_stale_after_state_advances(self):
        m = make_mission(config="25", luaw=False)
        advance_to(m, "ground_readback")
        taxi = m.handle_transmission(
            airport.FREQS["ground"], m.step().example, m.squawk, "ALT")
        assert taxi["passed"] is True
        assert "taxi_out" in m.pending_legs

        tower = m.handle_transmission(
            airport.FREQS["tower"], m.step().example, m.squawk, "ALT")
        assert tower["passed"] is True
        assert m.leg_complete("taxi_out") is None


class TestSayAgain:
    def test_say_again_repeats_last_atc(self):
        m = make_mission(config="25")
        first = m.handle_transmission(airport.FREQS["clearance"],
                                      m.steps["clearance_call"].example)
        r = m.handle_transmission(airport.FREQS["clearance"], "say again")
        assert r["atc"].display == first["atc"].display
        assert m.current == "clearance_readback"  # no advance either way


class TestTransponder:
    def to_tower_checkin(self, m: Mission) -> None:
        while m.current != "tower_checkin":
            step = m.steps[m.current]
            r = m.handle_transmission(airport.FREQS[step.facility], step.example,
                                      m.squawk, "ALT")
            assert r["passed"]

    def test_wrong_code_is_challenged(self):
        m = make_mission(config="25", luaw=False)
        self.to_tower_checkin(m)
        r = m.handle_transmission(airport.FREQS["tower"],
                                  m.steps["tower_checkin"].example, "1200", "ALT")
        assert r["passed"] is False
        assert "verify transponder" in r["atc"].display.lower()
        assert m.squawk in r["atc"].display
        assert m.current == "tower_checkin"

    def test_wrong_mode_costs_5(self):
        m = make_mission(config="25", luaw=False)
        self.to_tower_checkin(m)
        r = m.handle_transmission(airport.FREQS["tower"],
                                  m.steps["tower_checkin"].example, m.squawk, "SBY")
        assert r["passed"] is True
        assert r["score"] == 95

    def test_correct_xpdr_full_credit(self):
        m = make_mission(config="25", luaw=False)
        self.to_tower_checkin(m)
        r = m.handle_transmission(airport.FREQS["tower"],
                                  m.steps["tower_checkin"].example, m.squawk, "ALT")
        assert r["passed"] is True
        assert r["score"] == 100
