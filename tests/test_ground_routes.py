"""Current-chart topology and canonical KSBA ground-route tests."""

from __future__ import annotations

import re

import pytest

from server.phraseology import normalize
from server.ground import (
    CANONICAL_TAXI_ROUTES,
    GROUND_EDGES,
    GROUND_NODES,
    KNOWN_TAXIWAYS,
    ROUTE_ENDPOINTS,
    ROUTE_REVIEW_STATUS,
    RUNWAY_OPERATIONS,
    RUNWAY_BOUNDARIES,
    build_taxi_route,
    validate_ground_graph,
)


EXPECTED_ROUTES = {
    ("taxi_to_runup", "25"): {
        "taxiways": ("C", "G"),
        "crossings": (),
        "start": "above_all_parking",
        "end": "runup_25_g",
    },
    ("taxi_out", "25"): {
        "taxiways": ("G", "B", "B1"),
        "crossings": (),
        "start": "runup_25_g",
        "end": "hold_short_25_b1",
    },
    ("taxi_to_runup", "15L"): {
        "taxiways": ("C", "F"),
        "crossings": (),
        "start": "above_all_parking",
        "end": "runup_15l_f",
    },
    ("taxi_out", "15L"): {
        "taxiways": ("F", "C", "E"),
        "crossings": (),
        "start": "runup_15l_f",
        "end": "hold_short_15l_e",
    },
    ("taxi_in", "25"): {
        "taxiways": ("C",),
        "crossings": (),
        "start": "clear_of_25_c",
        "end": "above_all_parking",
    },
    ("taxi_in", "15L"): {
        "taxiways": ("E3", "E", "B", "F", "C"),
        "crossings": ("25",),
        "start": "clear_of_15l_e3",
        "end": "above_all_parking",
    },
}


def test_ground_graph_validates():
    validate_ground_graph()


def test_every_supported_endpoint_has_a_canonical_route():
    assert set(CANONICAL_TAXI_ROUTES) == set(ROUTE_ENDPOINTS) == set(EXPECTED_ROUTES)


@pytest.mark.parametrize("key, expected", EXPECTED_ROUTES.items())
def test_canonical_route_operational_elements(key, expected):
    route = CANONICAL_TAXI_ROUTES[key]
    assert route.start == expected["start"]
    assert route.end == expected["end"]
    assert route.taxiways == expected["taxiways"]
    assert route.crossings == expected["crossings"]
    assert route.review_status == ROUTE_REVIEW_STATUS


@pytest.mark.parametrize("route", CANONICAL_TAXI_ROUTES.values())
def test_route_edges_and_path_are_continuous(route):
    assert route.node_ids[0] == route.start
    assert route.node_ids[-1] == route.end
    assert len(route.node_ids) == len(route.edges) + 1
    assert route.path == tuple(GROUND_NODES[node_id].position for node_id in route.node_ids)

    for index, edge in enumerate(route.edges):
        assert edge.start == route.node_ids[index]
        assert edge.end == route.node_ids[index + 1]
        assert edge.kind not in {"runway_entry", "runway_exit"}
        x, y = route.path[index]
        next_x, next_y = route.path[index + 1]
        assert ((next_x - x) ** 2 + (next_y - y) ** 2) ** 0.5 < 0.20


@pytest.mark.parametrize("route", CANONICAL_TAXI_ROUTES.values())
def test_route_crossings_come_only_from_explicit_crossing_edges(route):
    crossing_edges = tuple(edge for edge in route.edges if edge.kind == "runway_crossing")
    assert route.crossings == tuple(edge.crosses_runway for edge in crossing_edges)
    assert all(
        frozenset((edge.start, edge.end)) in RUNWAY_BOUNDARIES
        for edge in crossing_edges
    )


def test_taxi_out_ends_at_matching_hold_short_node():
    for runway in ("25", "15L"):
        route = CANONICAL_TAXI_ROUTES[("taxi_out", runway)]
        end = GROUND_NODES[route.end]
        assert route.hold_short == runway
        assert end.kind == "hold_short"
        assert end.runway == runway


def test_taxi_to_runup_ends_at_matching_runup_node():
    for runway in ("25", "15L"):
        route = CANONICAL_TAXI_ROUTES[("taxi_to_runup", runway)]
        end = GROUND_NODES[route.end]
        assert route.start == "above_all_parking"
        assert route.hold_short is None
        assert end.kind == "run_up"
        assert end.runway == runway


def test_taxi_in_returns_to_above_all():
    for runway in ("25", "15L"):
        route = CANONICAL_TAXI_ROUTES[("taxi_in", runway)]
        assert route.end == "above_all_parking"
        assert route.path[-1] == GROUND_NODES["above_all_parking"].position
        assert route.hold_short is None


def test_routes_use_only_current_known_taxiways():
    used = {
        taxiway
        for route in CANONICAL_TAXI_ROUTES.values()
        for taxiway in route.taxiways
    }
    assert used <= KNOWN_TAXIWAYS
    assert used.isdisjoint({"M", "Foxtrot", "Hotel", "Mike"})


def test_every_declared_runway_boundary_has_one_edge():
    graph_pairs = [frozenset((edge.start, edge.end)) for edge in GROUND_EDGES]
    for boundary in RUNWAY_BOUNDARIES:
        assert graph_pairs.count(boundary) == 1


def test_unsupported_route_is_rejected():
    with pytest.raises(ValueError, match="unsupported runway"):
        build_taxi_route("taxi_out", "7")


def test_route_clearances_are_derived_in_traversal_order():
    assert CANONICAL_TAXI_ROUTES[("taxi_to_runup", "25")].display_instruction == (
        "Runway 25, taxi via Charlie, Golf to the run-up area."
    )
    assert CANONICAL_TAXI_ROUTES[("taxi_out", "25")].display_instruction == (
        "Runway 25, taxi via Golf, Bravo, Bravo One."
    )
    assert CANONICAL_TAXI_ROUTES[("taxi_to_runup", "15L")].display_instruction == (
        "Runway 15 Left, taxi via Charlie, Foxtrot to the run-up area."
    )
    assert CANONICAL_TAXI_ROUTES[("taxi_out", "15L")].display_instruction == (
        "Runway 15 Left, taxi via Foxtrot, Charlie, Echo."
    )
    assert CANONICAL_TAXI_ROUTES[("taxi_in", "25")].display_instruction == (
        "Taxi to Above All Aviation via Charlie."
    )
    assert CANONICAL_TAXI_ROUTES[("taxi_in", "15L")].display_instruction == (
        "Taxi to Above All Aviation via Echo Three, Echo, cross Runway 25, "
        "Bravo, Foxtrot, Charlie."
    )


@pytest.mark.parametrize("route", CANONICAL_TAXI_ROUTES.values())
def test_displayed_route_satisfies_its_generated_readback_requirements(route):
    normalized = normalize(route.display_instruction)
    for requirement in route.readback_requirements:
        assert any(re.search(pattern, normalized) for pattern in requirement.patterns), (
            requirement, normalized
        )


def test_runway_operations_use_current_boundaries_and_exit_names():
    runway25 = RUNWAY_OPERATIONS["25"]
    assert runway25.line_up_nodes == ("hold_short_25_b1", "runway25_threshold")
    assert runway25.exit_nodes == ("runway25_exit_c", "clear_of_25_c")
    assert runway25.exit_display.startswith("Turn right at Charlie")

    runway15 = RUNWAY_OPERATIONS["15L"]
    assert runway15.line_up_nodes == ("hold_short_15l_e", "runway15l_threshold")
    assert runway15.exit_nodes == ("runway15l_exit_e3", "clear_of_15l_e3")
    assert runway15.exit_display.startswith("Turn left at Echo Three")


def test_charlie_bends_around_15_runway_ends_without_crossing_them():
    route = CANONICAL_TAXI_ROUTES[("taxi_in", "25")]
    assert route.taxiways == ("C",)
    assert route.crossings == ()
    assert all(edge.kind == "taxiway" for edge in route.edges if edge.taxiway == "C")


def test_delta_is_a_distinct_taxiway_branch_and_crosses_only_runway_25():
    delta = [edge for edge in GROUND_EDGES if edge.taxiway == "D"]
    assert delta
    crossings = [edge for edge in delta if edge.kind == "runway_crossing"]
    assert len(crossings) == 1
    assert crossings[0].crosses_runway == "25"
    assert any(
        frozenset((edge.start, edge.end))
        == frozenset(("c_d_junction", "hold_short_15r_d"))
        for edge in delta
    )


def test_all_four_charted_runup_areas_are_nodes_with_access_edges():
    runups = {node_id for node_id, node in GROUND_NODES.items() if node.kind == "run_up"}
    assert runups == {"runup_7_a", "runup_15r_c", "runup_15l_f", "runup_25_g"}
    for node_id in runups:
        access = [
            edge for edge in GROUND_EDGES
            if edge.kind == "run_up_access" and node_id in {edge.start, edge.end}
        ]
        assert len(access) == 1
