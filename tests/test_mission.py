"""Full-mission happy paths and mission invariants."""

from server import airport, ground
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

    def test_current_routes_drive_phraseology_and_movement(self, mission25, mission15):
        for mission in (mission25, mission15):
            taxi_out = mission.taxi_out_route
            taxi_in = mission.taxi_in_route
            runway_op = mission.runway_operation

            assert mission.steps["ground_call"].atc.display.endswith(
                taxi_out.display_instruction)
            assert mission.steps["ground_readback"].actions[0]["path"] == taxi_out.path
            assert mission.steps["ground_inbound"].atc.display.endswith(
                taxi_in.display_instruction)
            assert mission.steps["taxi_in_readback"].actions[0]["path"] == taxi_in.path
            assert mission.steps["exit_readback"].actions[0]["path"] == runway_op.exit_path

    def test_no_legacy_taxiway_phraseology_remains(self, mission25, mission15):
        taxi_text = " ".join(
            step.example
            for mission in (mission25, mission15)
            for step in (
                mission.steps["ground_readback"],
                mission.steps["exit_readback"],
                mission.steps["taxi_in_readback"],
            )
        ).lower()
        assert "hotel" not in taxi_text
        assert "mike" not in taxi_text
        assert "alpha" not in taxi_text

    def test_every_same_view_movement_action_is_continuous(
            self, mission25, mission25_luaw, mission15):
        for mission in (mission25, mission25_luaw, mission15):
            brief = mission.brief()["plane"]
            current_view = brief["view"]
            current_position = tuple(brief["pos"])

            for step in mission.steps.values():
                for action in step.actions:
                    if action.get("type") != "move" or not action.get("path"):
                        continue
                    path = tuple(tuple(point) for point in action["path"])
                    if action["view"] == current_view:
                        assert path[0] == current_position, (
                            mission.runway, step.id, current_position, path[0]
                        )
                    else:
                        current_view = action["view"]
                    assert all(
                        first != second
                        for first, second in zip(path, path[1:])
                    ), (mission.runway, step.id, path)
                    current_position = path[-1]
                    assert action["speed"] in {"taxi", "roll", "fly"}


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

    def test_examples_satisfy_graders_with_alpha_tail(self):
        """Tails with letters ('N3083S') must grade like all-digit tails."""
        for seed in range(10):
            m = Mission(callsign="N3083S", seed=seed)
            for step in m.steps.values():
                norm = normalize(step.example)
                for item in step.items:
                    assert item.matches(norm), (
                        f"seed {seed} step {step.id}: item {item.key!r} "
                        f"({item.patterns}) not matched by example -> {norm!r}"
                    )

    def test_spoken_alpha_callsign_passes_clearance_call(self):
        """Whisper renders 'N3083S' as '... eight three sierra' — must pass."""
        m = Mission(callsign="N3083S", seed=0)
        r = m.handle_transmission(
            airport.FREQS["clearance"],
            f"Santa Barbara Clearance, Cessna three zero eight three sierra, "
            f"at Above All Aviation with information {m.wx.letter}, "
            f"request VFR departure to the east at three thousand five hundred",
        )
        assert r["passed"], r["missing"]

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

    def test_weather_matches_the_recorded_runway_selection(self):
        for seed in range(30):
            m = Mission(seed=seed)
            selection = m.runway_selection
            assert selection.wind_dir == m.wx.wind_dir
            assert selection.wind_speed == m.wx.wind_speed
            assert selection.selected_runway == m.runway
            selected = next(
                candidate for candidate in selection.candidates
                if candidate.runway == m.runway
            )
            assert selected.eligible

    def test_brief_shape(self):
        b = Mission(seed=1).brief()
        assert b["plane"]["pos"] == list(
            ground.GROUND_NODES["above_all_parking"].position)
        assert set(b["freqs"]) == {"atis", "clearance", "ground", "tower", "approach"}
        assert "132.65" == b["freqs"]["atis"]

    def test_paths_are_normalized_coords(self):
        paths = [route.path for route in ground.CANONICAL_TAXI_ROUTES.values()]
        paths.extend(
            path
            for operation in ground.RUNWAY_OPERATIONS.values()
            for path in (
                operation.line_up_path,
                operation.takeoff_roll_path,
                operation.landing_roll_path,
                operation.exit_path,
            )
        )
        for path in paths:
            for pt in path:
                assert 0 <= pt[0] <= 1 and 0 <= pt[1] <= 1
