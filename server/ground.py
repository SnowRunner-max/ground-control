"""Typed ground graph and canonical taxi routes for KSBA FAA cycle 2607.

This module deliberately sits beside the legacy coordinate lists in
``server.airport``. Phase 2 establishes and validates the current-airport graph;
Phase 3 will make scenario phraseology and grading consume these route objects.

The routes are representative training routes derived from the current FAA
diagram. Their exact operational use remains subject to ATC instructions,
NOTAMs, and review by a KSBA-familiar instructor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from heapq import heappop, heappush
from math import hypot
from typing import Literal

from .phraseology import NATO, SPOKEN_DIGIT

NodeKind = Literal[
    "parking",
    "ramp_exit",
    "junction",
    "hold_short",
    "runway",
    "runway_clear",
]
EdgeKind = Literal[
    "ramp",
    "taxiway",
    "runway_crossing",
    "runway_entry",
    "runway_exit",
]
RouteOperation = Literal["taxi_out", "taxi_in"]
InstructionKind = Literal["taxiway", "cross_runway"]

KNOWN_TAXIWAYS = frozenset({
    "A", "A1", "A2", "A3", "A4", "A5",
    "B", "B1", "C", "D", "E", "E1", "E2", "E3", "F", "G", "H",
})
SUPPORTED_RUNWAYS = frozenset({"25", "15L"})
ROUTE_REVIEW_STATUS = "chart-derived; KSBA instructor review pending"


@dataclass(frozen=True, slots=True)
class GroundNode:
    """A named operational point in normalized current-chart coordinates."""

    id: str
    position: tuple[float, float]
    kind: NodeKind
    runway: str | None = None


@dataclass(frozen=True, slots=True)
class GroundEdge:
    """A traversable graph edge with its operational meaning attached."""

    start: str
    end: str
    kind: EdgeKind
    taxiway: str | None = None
    crosses_runway: str | None = None
    bidirectional: bool = True

    def reversed(self) -> GroundEdge:
        return GroundEdge(
            start=self.end,
            end=self.start,
            kind=self.kind,
            taxiway=self.taxiway,
            crosses_runway=self.crosses_runway,
            bidirectional=self.bidirectional,
        )


@dataclass(frozen=True, slots=True)
class RouteInstruction:
    kind: InstructionKind
    value: str


@dataclass(frozen=True, slots=True)
class ReadbackRequirement:
    key: str
    label: str
    patterns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaxiRoute:
    """One connected route used by movement, phraseology, and grading."""

    operation: RouteOperation
    runway: str
    start: str
    end: str
    node_ids: tuple[str, ...]
    edges: tuple[GroundEdge, ...]
    taxiways: tuple[str, ...]
    crossings: tuple[str, ...]
    hold_short: str | None
    review_status: str = ROUTE_REVIEW_STATUS

    @property
    def path(self) -> tuple[tuple[float, float], ...]:
        return tuple(GROUND_NODES[node_id].position for node_id in self.node_ids)

    @property
    def instructions(self) -> tuple[RouteInstruction, ...]:
        instructions: list[RouteInstruction] = []
        last_taxiway: str | None = None
        for edge in self.edges:
            if edge.taxiway is not None and edge.taxiway != last_taxiway:
                instructions.append(RouteInstruction("taxiway", edge.taxiway))
                last_taxiway = edge.taxiway
            if edge.crosses_runway is not None:
                instructions.append(RouteInstruction("cross_runway", edge.crosses_runway))
        return tuple(instructions)

    @property
    def display_instruction(self) -> str:
        prefix = (
            f"Runway {_runway_display(self.runway)}, taxi via "
            if self.operation == "taxi_out"
            else "Taxi to Above All Aviation via "
        )
        return prefix + _format_instruction_elements(self.instructions, spoken=False) + "."

    @property
    def spoken_instruction(self) -> str:
        prefix = (
            f"runway {_runway_spoken(self.runway)}, taxi via "
            if self.operation == "taxi_out"
            else "taxi to above all aviation via "
        )
        return prefix + _format_instruction_elements(self.instructions, spoken=True) + "."

    @property
    def readback_requirements(self) -> tuple[ReadbackRequirement, ...]:
        requirements: list[ReadbackRequirement] = []
        if self.operation == "taxi_out":
            requirements.append(ReadbackRequirement(
                "runway",
                f"Runway {_runway_display(self.runway)}",
                (_runway_pattern(self.runway),),
            ))

        route_pattern = ".*".join(_taxiway_pattern(code) for code in self.taxiways)
        route_label = "via " + ", ".join(_taxiway_display(code) for code in self.taxiways)
        requirements.append(ReadbackRequirement("route", route_label, (route_pattern,)))
        requirements.extend(
            ReadbackRequirement(
                f"cross_{runway.lower()}",
                f"cross Runway {_runway_display(runway)}",
                (rf"cross.*{_runway_pattern(runway)}",),
            )
            for runway in self.crossings
        )
        return tuple(requirements)


@dataclass(frozen=True, slots=True)
class RunwayOperation:
    runway: str
    line_up_nodes: tuple[str, ...]
    takeoff_roll_nodes: tuple[str, ...]
    landing_roll_nodes: tuple[str, ...]
    exit_nodes: tuple[str, ...]
    exit_direction: Literal["left", "right"]
    exit_taxiway: str

    def _path(self, node_ids: tuple[str, ...]) -> tuple[tuple[float, float], ...]:
        return tuple(GROUND_NODES[node_id].position for node_id in node_ids)

    @property
    def line_up_path(self) -> tuple[tuple[float, float], ...]:
        return self._path(self.line_up_nodes)

    @property
    def takeoff_roll_path(self) -> tuple[tuple[float, float], ...]:
        return self._path(self.takeoff_roll_nodes)

    @property
    def landing_roll_path(self) -> tuple[tuple[float, float], ...]:
        return self._path(self.landing_roll_nodes)

    @property
    def exit_path(self) -> tuple[tuple[float, float], ...]:
        return self._path(self.exit_nodes)

    @property
    def exit_display(self) -> str:
        return (
            f"Turn {self.exit_direction} at {_taxiway_display(self.exit_taxiway)}, "
            "contact Ground point seven."
        )

    @property
    def exit_spoken(self) -> str:
        return f"turn {self.exit_direction} at {_taxiway_spoken(self.exit_taxiway)}"

    @property
    def clear_of_display(self) -> str:
        return (
            f"clear of Runway {_runway_display(self.runway)} "
            f"at {_taxiway_display(self.exit_taxiway)}"
        )

    @property
    def exit_readback_requirements(self) -> tuple[ReadbackRequirement, ...]:
        taxiway = _taxiway_display(self.exit_taxiway)
        return (
            ReadbackRequirement(
                "exit",
                f"{self.exit_direction} at {taxiway}",
                (_taxiway_pattern(self.exit_taxiway),),
            ),
            ReadbackRequirement(
                "ground",
                "Ground on 121.7",
                (r"121\.7", r"point (7|seven)", r"\bground\b"),
            ),
        )


def _taxiway_parts(code: str) -> tuple[str, str]:
    match = re.fullmatch(r"([A-Z])(\d*)", code.upper())
    if match is None:
        raise ValueError(f"invalid taxiway identifier {code!r}")
    return match.group(1), match.group(2)


def _taxiway_spoken(code: str) -> str:
    letter, digits = _taxiway_parts(code)
    words = [NATO[letter.lower()]]
    words.extend(SPOKEN_DIGIT[digit] for digit in digits)
    return " ".join(words)


def _taxiway_display(code: str) -> str:
    return _taxiway_spoken(code).title()


def _taxiway_pattern(code: str) -> str:
    letter, digits = _taxiway_parts(code)
    spoken = NATO[letter.lower()]
    if not digits:
        return rf"\b(?:{spoken}|{letter.lower()})\b"
    digit_pattern = r"\s*".join(re.escape(digit) for digit in digits)
    return rf"\b(?:{spoken}\s*{digit_pattern}|{letter.lower()}\s*{digit_pattern})\b"


def _runway_display(runway: str) -> str:
    match = re.fullmatch(r"(\d+)([LRC]?)", runway.upper())
    if match is None:
        return runway
    side = {"L": " Left", "R": " Right", "C": " Center"}.get(match.group(2), "")
    return match.group(1) + side


def _runway_spoken(runway: str) -> str:
    match = re.fullmatch(r"(\d+)([LRC]?)", runway.upper())
    if match is None:
        return runway.lower()
    digits = " ".join(SPOKEN_DIGIT[digit] for digit in match.group(1))
    side = {"L": " left", "R": " right", "C": " center"}.get(match.group(2), "")
    return digits + side


def _runway_pattern(runway: str) -> str:
    match = re.fullmatch(r"(\d+)([LRC]?)", runway.upper())
    if match is None:
        return re.escape(runway.lower())
    side = {
        "L": r" ?(?:left|l\b)",
        "R": r" ?(?:right|r\b)",
        "C": r" ?(?:center|c\b)",
    }.get(match.group(2), "")
    return rf"\b{match.group(1)}{side}"


def _format_instruction_elements(
    instructions: tuple[RouteInstruction, ...], *, spoken: bool,
) -> str:
    parts: list[str] = []
    for instruction in instructions:
        if instruction.kind == "taxiway":
            value = (
                _taxiway_spoken(instruction.value)
                if spoken else _taxiway_display(instruction.value)
            )
        else:
            runway = (
                _runway_spoken(instruction.value)
                if spoken else _runway_display(instruction.value)
            )
            value = f"cross runway {runway}" if spoken else f"cross Runway {runway}"
        parts.append(value)
    return ", ".join(parts)


def _node(
    id: str,
    x: float,
    y: float,
    kind: NodeKind = "junction",
    runway: str | None = None,
) -> GroundNode:
    return GroundNode(id=id, position=(x, y), kind=kind, runway=runway)


# Coordinates were reviewed as a labeled overlay on the cycle-2607 chart. The
# graph contains only the pavement needed by the two currently supported runway
# configurations; it is intentionally not a general model of every KSBA route.
GROUND_NODES: dict[str, GroundNode] = {
    # Above All / north ramp
    "above_all_parking": _node("above_all_parking", 0.684, 0.237, "parking"),
    "above_all_ramp_exit": _node("above_all_ramp_exit", 0.700, 0.263, "ramp_exit"),
    "c_f_junction": _node("c_f_junction", 0.766, 0.285),
    "c_e_junction": _node("c_e_junction", 0.650, 0.290),

    # Runway 25 departure via C, F, B, B1
    "f_b_junction": _node("f_b_junction", 0.766, 0.389),
    "b_b1_junction": _node("b_b1_junction", 0.783, 0.389),
    "hold_short_25_b1": _node("hold_short_25_b1", 0.783, 0.432, "hold_short", "25"),
    "runway25_threshold": _node("runway25_threshold", 0.791, 0.466, "runway", "25"),
    "runway25_touchdown": _node("runway25_touchdown", 0.724, 0.469, "runway", "25"),

    # Runway 15L departure via C, E
    "hold_short_15l_e": _node("hold_short_15l_e", 0.631, 0.326, "hold_short", "15L"),
    "runway15l_threshold": _node("runway15l_threshold", 0.634, 0.336, "runway", "15L"),
    "runway15l_touchdown": _node("runway15l_touchdown", 0.638, 0.357, "runway", "15L"),

    # Runway 25 exit at C, then C across both 15/33 runways
    "runway25_exit_c": _node("runway25_exit_c", 0.459, 0.478, "runway", "25"),
    "clear_of_25_c": _node("clear_of_25_c", 0.438, 0.433, "runway_clear", "25"),
    "c_west": _node("c_west", 0.525, 0.374),
    "c_hold_15r_west": _node("c_hold_15r_west", 0.560, 0.363, "hold_short", "15R"),
    "c_clear_15r_east": _node("c_clear_15r_east", 0.581, 0.346, "runway_clear", "15R"),
    "c_hold_15l_west": _node("c_hold_15l_west", 0.600, 0.333, "hold_short", "15L"),
    "c_clear_15l_east": _node("c_clear_15l_east", 0.623, 0.310, "runway_clear", "15L"),

    # Runway 15L exit at E3, then E across Runway 25 to B, F, C
    "runway15l_exit_e3": _node("runway15l_exit_e3", 0.673, 0.555, "runway", "15L"),
    "clear_of_15l_e3": _node("clear_of_15l_e3", 0.700, 0.620, "runway_clear", "15L"),
    "e_south": _node("e_south", 0.700, 0.575),
    "e_hold_25_south": _node("e_hold_25_south", 0.668, 0.486, "hold_short", "25"),
    "e_clear_25_north": _node("e_clear_25_north", 0.653, 0.397, "runway_clear", "25"),
}


def _edge(
    start: str,
    end: str,
    kind: EdgeKind,
    taxiway: str | None = None,
    crosses_runway: str | None = None,
    bidirectional: bool = True,
) -> GroundEdge:
    return GroundEdge(
        start=start,
        end=end,
        kind=kind,
        taxiway=taxiway,
        crosses_runway=crosses_runway,
        bidirectional=bidirectional,
    )


GROUND_EDGES: tuple[GroundEdge, ...] = (
    # North ramp and the two departure branches.
    _edge("above_all_parking", "above_all_ramp_exit", "ramp"),
    _edge("above_all_ramp_exit", "c_f_junction", "taxiway", "C"),
    _edge("above_all_ramp_exit", "c_e_junction", "taxiway", "C"),
    _edge("c_f_junction", "f_b_junction", "taxiway", "F"),
    _edge("f_b_junction", "b_b1_junction", "taxiway", "B"),
    _edge("b_b1_junction", "hold_short_25_b1", "taxiway", "B1"),
    _edge("c_e_junction", "hold_short_15l_e", "taxiway", "E"),

    # Runway entry boundaries are represented but are not part of taxi routes.
    _edge("hold_short_25_b1", "runway25_threshold", "runway_entry", bidirectional=False),
    _edge("hold_short_15l_e", "runway15l_threshold", "runway_entry", bidirectional=False),

    # Runway 25 exit and current Taxiway C route back to the north ramp.
    _edge("runway25_exit_c", "clear_of_25_c", "runway_exit", bidirectional=False),
    _edge("clear_of_25_c", "c_west", "taxiway", "C"),
    _edge("c_west", "c_hold_15r_west", "taxiway", "C"),
    _edge("c_hold_15r_west", "c_clear_15r_east", "runway_crossing", "C", "15R"),
    _edge("c_clear_15r_east", "c_hold_15l_west", "taxiway", "C"),
    _edge("c_hold_15l_west", "c_clear_15l_east", "runway_crossing", "C", "15L"),
    _edge("c_clear_15l_east", "c_e_junction", "taxiway", "C"),

    # Runway 15L exit and current E/B/F/C route back to Above All.
    _edge("runway15l_exit_e3", "clear_of_15l_e3", "runway_exit", bidirectional=False),
    _edge("clear_of_15l_e3", "e_south", "taxiway", "E3"),
    _edge("e_south", "e_hold_25_south", "taxiway", "E"),
    _edge("e_hold_25_south", "e_clear_25_north", "runway_crossing", "E", "25"),
    _edge("e_clear_25_north", "f_b_junction", "taxiway", "B"),
)

# Every modeled runway boundary is declared independently of its edge. Graph
# validation uses this registry to prevent an ordinary taxiway edge from
# silently crossing a runway or an identified boundary from losing its runway
# metadata during future edits.
RUNWAY_BOUNDARIES: dict[frozenset[str], tuple[EdgeKind, str]] = {
    frozenset(("hold_short_25_b1", "runway25_threshold")): ("runway_entry", "25"),
    frozenset(("hold_short_15l_e", "runway15l_threshold")): ("runway_entry", "15L"),
    frozenset(("runway25_exit_c", "clear_of_25_c")): ("runway_exit", "25"),
    frozenset(("runway15l_exit_e3", "clear_of_15l_e3")): ("runway_exit", "15L"),
    frozenset(("c_hold_15r_west", "c_clear_15r_east")): ("runway_crossing", "15R"),
    frozenset(("c_hold_15l_west", "c_clear_15l_east")): ("runway_crossing", "15L"),
    frozenset(("e_hold_25_south", "e_clear_25_north")): ("runway_crossing", "25"),
}


ROUTE_ENDPOINTS: dict[tuple[RouteOperation, str], tuple[str, str]] = {
    ("taxi_out", "25"): ("above_all_parking", "hold_short_25_b1"),
    ("taxi_out", "15L"): ("above_all_parking", "hold_short_15l_e"),
    ("taxi_in", "25"): ("clear_of_25_c", "above_all_parking"),
    ("taxi_in", "15L"): ("clear_of_15l_e3", "above_all_parking"),
}


def _edge_cost(edge: GroundEdge) -> float:
    start = GROUND_NODES[edge.start].position
    end = GROUND_NODES[edge.end].position
    distance = hypot(end[0] - start[0], end[1] - start[1])
    # Prefer an otherwise comparable route that avoids a runway crossing.
    return distance + (1.0 if edge.kind == "runway_crossing" else 0.0)


def _adjacency() -> dict[str, list[GroundEdge]]:
    adjacency = {node_id: [] for node_id in GROUND_NODES}
    for edge in GROUND_EDGES:
        adjacency[edge.start].append(edge)
        if edge.bidirectional:
            adjacency[edge.end].append(edge.reversed())
    return adjacency


def _find_edges(start: str, end: str) -> tuple[GroundEdge, ...]:
    """Find the lowest-cost legal path through the small current KSBA graph."""
    adjacency = _adjacency()
    queue: list[tuple[float, int, str, tuple[GroundEdge, ...]]] = []
    heappush(queue, (0.0, 0, start, ()))
    best = {start: 0.0}
    sequence = 0

    while queue:
        cost, _, node_id, path = heappop(queue)
        if node_id == end:
            return path
        if cost > best.get(node_id, float("inf")):
            continue
        for edge in adjacency[node_id]:
            next_cost = cost + _edge_cost(edge)
            if next_cost >= best.get(edge.end, float("inf")):
                continue
            best[edge.end] = next_cost
            sequence += 1
            heappush(queue, (next_cost, sequence, edge.end, path + (edge,)))
    raise ValueError(f"no ground route from {start!r} to {end!r}")


def _instruction_taxiways(edges: tuple[GroundEdge, ...]) -> tuple[str, ...]:
    ordered: list[str] = []
    for edge in edges:
        if edge.taxiway is None or (ordered and edge.taxiway == ordered[-1]):
            continue
        if edge.taxiway in ordered:
            raise ValueError(f"taxiway {edge.taxiway} reappears non-contiguously")
        ordered.append(edge.taxiway)
    return tuple(ordered)


def validate_ground_graph() -> None:
    """Reject incomplete or operationally ambiguous graph declarations."""
    for node_id, node in GROUND_NODES.items():
        if node.id != node_id:
            raise ValueError(f"ground node key/id mismatch: {node_id!r} != {node.id!r}")
        x, y = node.position
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"ground node {node_id!r} is outside the chart")
        if node.kind in {"hold_short", "runway", "runway_clear"} and not node.runway:
            raise ValueError(f"ground node {node_id!r} requires a runway")

    pairs: set[frozenset[str]] = set()
    for edge in GROUND_EDGES:
        if edge.start not in GROUND_NODES or edge.end not in GROUND_NODES:
            raise ValueError(f"edge has unknown endpoint: {edge}")
        if edge.start == edge.end:
            raise ValueError(f"self-loop is not a ground route: {edge}")
        pair = frozenset((edge.start, edge.end))
        if pair in pairs:
            raise ValueError(f"duplicate ground edge: {edge.start!r} / {edge.end!r}")
        pairs.add(pair)
        if edge.taxiway is not None and edge.taxiway not in KNOWN_TAXIWAYS:
            raise ValueError(f"unknown current taxiway {edge.taxiway!r}")
        if edge.kind in {"taxiway", "runway_crossing"} and edge.taxiway is None:
            raise ValueError(f"{edge.kind} edge requires a taxiway: {edge}")
        if edge.kind == "runway_crossing" and edge.crosses_runway is None:
            raise ValueError(f"runway crossing is not identified: {edge}")
        if edge.kind != "runway_crossing" and edge.crosses_runway is not None:
            raise ValueError(f"implicit runway crossing metadata: {edge}")
        boundary = RUNWAY_BOUNDARIES.get(pair)
        if boundary is not None:
            expected_kind, runway = boundary
            if edge.kind != expected_kind:
                raise ValueError(f"runway boundary has incorrect edge kind: {edge}")
            if expected_kind == "runway_crossing" and edge.crosses_runway != runway:
                raise ValueError(f"runway crossing has incorrect runway: {edge}")

    declared_pairs = {frozenset((edge.start, edge.end)) for edge in GROUND_EDGES}
    missing_boundaries = set(RUNWAY_BOUNDARIES) - declared_pairs
    if missing_boundaries:
        raise ValueError(f"runway boundary has no graph edge: {missing_boundaries}")


def build_taxi_route(operation: RouteOperation, runway: str) -> TaxiRoute:
    """Build and validate a canonical route for a supported mission leg."""
    if runway not in SUPPORTED_RUNWAYS:
        raise ValueError(f"unsupported runway {runway!r}")
    try:
        start, end = ROUTE_ENDPOINTS[(operation, runway)]
    except KeyError as exc:
        raise ValueError(f"unsupported route {operation!r} / {runway!r}") from exc

    edges = _find_edges(start, end)
    if any(edge.kind in {"runway_entry", "runway_exit"} for edge in edges):
        raise ValueError("taxi route must begin clear of a runway and stop before entry")
    node_ids = (start,) + tuple(edge.end for edge in edges)
    taxiways = _instruction_taxiways(edges)
    crossings = tuple(
        edge.crosses_runway for edge in edges if edge.crosses_runway is not None
    )
    if len(crossings) != len(set(crossings)):
        raise ValueError(f"route crosses a runway more than once: {crossings}")

    end_node = GROUND_NODES[end]
    hold_short = runway if operation == "taxi_out" else None
    if operation == "taxi_out":
        if end_node.kind != "hold_short" or end_node.runway != runway:
            raise ValueError(f"taxi-out route does not end holding short of {runway}")
    elif end != "above_all_parking":
        raise ValueError("taxi-in route does not end at Above All Aviation")

    return TaxiRoute(
        operation=operation,
        runway=runway,
        start=start,
        end=end,
        node_ids=node_ids,
        edges=edges,
        taxiways=taxiways,
        crossings=crossings,
        hold_short=hold_short,
    )


validate_ground_graph()

CANONICAL_TAXI_ROUTES: dict[tuple[RouteOperation, str], TaxiRoute] = {
    key: build_taxi_route(*key) for key in ROUTE_ENDPOINTS
}

RUNWAY_OPERATIONS: dict[str, RunwayOperation] = {
    "25": RunwayOperation(
        runway="25",
        line_up_nodes=("hold_short_25_b1", "runway25_threshold"),
        takeoff_roll_nodes=("runway25_threshold", "runway25_exit_c"),
        landing_roll_nodes=("runway25_touchdown", "runway25_exit_c"),
        exit_nodes=("runway25_exit_c", "clear_of_25_c"),
        exit_direction="right",
        exit_taxiway="C",
    ),
    "15L": RunwayOperation(
        runway="15L",
        line_up_nodes=("hold_short_15l_e", "runway15l_threshold"),
        takeoff_roll_nodes=("runway15l_threshold", "runway15l_exit_e3"),
        landing_roll_nodes=("runway15l_touchdown", "runway15l_exit_e3"),
        exit_nodes=("runway15l_exit_e3", "clear_of_15l_e3"),
        exit_direction="left",
        exit_taxiway="E3",
    ),
}


def validate_runway_operations() -> None:
    if set(RUNWAY_OPERATIONS) != set(SUPPORTED_RUNWAYS):
        raise ValueError("every supported runway requires movement geometry")
    for runway, operation in RUNWAY_OPERATIONS.items():
        if operation.runway != runway:
            raise ValueError(f"runway operation key mismatch for {runway}")
        for node_ids in (
            operation.line_up_nodes,
            operation.takeoff_roll_nodes,
            operation.landing_roll_nodes,
            operation.exit_nodes,
        ):
            if len(node_ids) < 2 or any(node_id not in GROUND_NODES for node_id in node_ids):
                raise ValueError(f"invalid movement path for Runway {runway}: {node_ids}")

        line_up_boundary = RUNWAY_BOUNDARIES.get(frozenset(operation.line_up_nodes))
        if line_up_boundary != ("runway_entry", runway):
            raise ValueError(f"line-up path lacks Runway {runway} entry boundary")
        exit_boundary = RUNWAY_BOUNDARIES.get(frozenset(operation.exit_nodes))
        if exit_boundary != ("runway_exit", runway):
            raise ValueError(f"exit path lacks Runway {runway} exit boundary")
        if operation.exit_taxiway not in KNOWN_TAXIWAYS:
            raise ValueError(f"unknown exit taxiway {operation.exit_taxiway}")


validate_runway_operations()
