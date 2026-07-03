"""Failure paths: wrong frequency, bad readbacks, transponder, say-again, scoring."""

from server import airport
from server.scenario import Mission

from .conftest import find_seed


def make_mission(**kw) -> Mission:
    return Mission(seed=find_seed(**kw))


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
