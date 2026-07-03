"""Full-mission happy paths and mission invariants."""

from server import airport
from server.phraseology import normalize
from server.scenario import Mission

from .conftest import fly_mission


class TestHappyPath:
    def test_full_mission_runway_25(self, mission25):
        pushes = fly_mission(mission25)
        d = mission25.debrief()
        assert d["total"] == 100, d["steps"]
        assert pushes[-1]["complete"] is True

    def test_full_mission_runway_25_luaw(self, mission25_luaw):
        m = mission25_luaw
        fly_mission(m)
        assert any(s["step"] == "luaw_readback" for s in m.debrief()["steps"])
        assert m.debrief()["total"] == 100

    def test_full_mission_runway_15l(self, mission15):
        m = mission15
        fly_mission(m)
        assert m.debrief()["total"] == 100
        # the 15L taxi-in crosses runway 25 — the crossing readback must be graded
        assert any("cross" in i.label.lower()
                   for i in m.steps["taxi_in_readback"].items)

    def test_climb_out_triggers_handoff_push(self, mission25):
        m = mission25
        while m.current != "handoff_readback":
            step = m.steps[m.current]
            r = m.handle_transmission(airport.FREQS[step.facility], step.example,
                                      m.squawk, "ALT")
            assert r["passed"]
            if r["push"]:
                m.apply_push(r["push"])
        push = m.leg_complete("climb_out")
        assert "contact departure" in push["atc"].display.lower()

    def test_landing_roll_triggers_exit_instruction(self, mission25):
        m = mission25
        while m.current != "exit_readback":
            step = m.steps[m.current]
            r = m.handle_transmission(airport.FREQS[step.facility], step.example,
                                      m.squawk, "ALT")
            assert r["passed"]
            if r["push"]:
                m.apply_push(r["push"])
        push = m.leg_complete("landing_roll")
        assert "contact ground" in push["atc"].display.lower()


class TestInvariants:
    def test_examples_satisfy_their_own_graders(self):
        """Every step's ideal call must match ALL of its items (incl. optional),
        across many randomized missions."""
        for seed in range(30):
            m = Mission(seed=seed)
            for step in m.steps.values():
                norm = normalize(step.example)
                for item in step.items:
                    assert item.matches(norm), (
                        f"seed {seed} step {step.id}: item {item.key!r} "
                        f"({item.patterns}) not matched by example -> {norm!r}"
                    )

    def test_atc_spoken_text_contains_key_numbers(self):
        """What ATC says aloud must normalize back to the graded values."""
        for seed in range(20):
            m = Mission(seed=seed)
            clearance = m.steps["clearance_call"].atc
            norm = normalize(clearance.spoken)
            assert m.squawk in norm
            assert "125.4" in norm
            assert "2500" in norm

    def test_squawk_is_valid_transponder_code(self):
        for seed in range(100):
            m = Mission(seed=seed)
            assert len(m.squawk) == 4
            assert all(c in "01234567" for c in m.squawk)
            assert m.squawk not in ("1200", "7500", "7600", "7700")

    def test_atis_letter_appears_in_atis_text(self):
        for seed in range(20):
            m = Mission(seed=seed)
            display, spoken = m.atis_text()
            assert m.wx.letter.title() in display
            assert m.wx.letter in spoken

    def test_wind_favors_the_active_runway(self):
        for seed in range(30):
            m = Mission(seed=seed)
            lo, hi = m.cfg["wind_dir"]
            assert lo <= m.wx.wind_dir <= hi

    def test_brief_shape(self):
        b = Mission(seed=1).brief()
        assert b["plane"]["pos"] == list(airport.NODES["fbo"])
        assert set(b["freqs"]) == {"atis", "clearance", "ground", "tower", "approach"}
        assert "132.65" == b["freqs"]["atis"]

    def test_paths_are_normalized_coords(self):
        for cfg in airport.CONFIGS.values():
            for pt in cfg["taxi_out"]["path"]:
                assert 0 <= pt[0] <= 1 and 0 <= pt[1] <= 1
