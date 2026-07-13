# KSBA Ground Route Assumptions

## Status

The routes below are chart-derived training routes implemented during Phase 2
of the Above All ground-routing plan. Their geometry and topology have been
checked against FAA airport diagram AL-378, cycle 2607, effective 9 July through
6 August 2026.

They have **not yet been reviewed by a KSBA-familiar instructor or controller**.
Until that review occurs, they must be treated as representative simulation
routes rather than predictions of a clearance that Ground will issue. Actual
operations remain subject to ATIS, NOTAMs, closures, traffic, and controller
instructions.

## Above All Location

The graph starts at `above_all_parking`, an aircraft position on the north apron
adjacent to Above All Aviation's 45 Hartley Place facility. It is deliberately
not the building centroid and is distinct from the legacy generic transient-FBO
node.

## Canonical Routes

| Operation | Runway | Taxiways | Explicit runway crossings |
| --- | --- | --- | --- |
| Taxi out | 25 | C, F, B, B1 | None |
| Taxi out | 15L | C, E | None |
| Taxi in | 25 | C | 15R, then 15L |
| Taxi in | 15L | E3, E, B, F, C | 25 |

Taxi-out routes end at a named hold-short node. Taxi-in routes begin at a
named runway-clear node after the Tower-directed exit and end at
`above_all_parking`. Runway entry and exit boundaries exist in the graph but
are intentionally excluded from Ground taxi routes.

## Review Checklist

Before removing the pending-review status, confirm with a KSBA-familiar pilot
or instructor:

1. The representative Above All aircraft parking point and normal ramp exit.
2. The typical Runway 25 route through C, F, B, and B1.
3. The typical Runway 15L route through C and E.
4. Whether a Runway 25 landing normally exits at C for this training scenario,
   followed by the modeled C crossings of 15R and 15L.
5. Whether a Runway 15L landing normally uses E3 and E, crosses Runway 25 at E,
   then returns via B, F, and C.
6. The exact hold-short and runway-clear locations used by each route.
7. The controller phraseology expected for each taxiway sequence and crossing.

Record the reviewer, date, corrections, and accepted routes here before the
routes are described as locally validated.

## Implementation Boundary

Phase 2 stores these routes in `server/ground.py` as typed nodes, edges, and
canonical `TaxiRoute` objects. Phase 3 made those objects the live source for
displayed/spoken ATC instructions, ordered readback requirements, runway
entry/exit movement, taxi animation, and the Above All start/return position.
The pending instructor review above still applies to the active representative
training routes.
