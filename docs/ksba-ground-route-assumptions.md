# KSBA Ground Route Assumptions

## Status

The routes below are training routes implemented during Phase 2 of the Above
All ground-routing plan. Pavement geometry and connections were reconciled
against the City of Santa Barbara Airport Layout Plan approved 29 October 2024;
operational taxiway names were then checked against FAA airport diagram AL-378,
cycle 2607, effective 9 July through 6 August 2026.

- City layout plan: <https://flysba.santabarbaraca.gov/sites/default/files/2025-02/Airport%20Layout%20Plan_1.pdf>
- Current simplified diagram: <https://skyvector.com/files/tpp/2607/pdf/00378AD.PDF>

Local-pilot feedback established two corrections to the earlier graph: Charlie
bends around the north ends of Runways 15R and 15L rather than crossing them,
and Delta must be represented as the taxiway serving the 15R end. The exact
representative clearances still need controller/instructor review, so these
remain simulation routes rather than predictions of what Ground will issue.
Actual operations remain subject to ATIS, NOTAMs, closures, traffic, and
controller instructions.

## Above All Location

The graph starts at `above_all_parking`, an aircraft position on the north apron
adjacent to Above All Aviation's 45 Hartley Place facility. It is deliberately
not the building centroid and is distinct from the legacy generic transient-FBO
node.

## Canonical Routes

| Operation | Runway | Taxiways | Explicit runway crossings |
| --- | --- | --- | --- |
| Taxi to run-up | 25 | C, G | None |
| Run-up to hold short | 25 | G, B, B1 | None |
| Taxi to run-up | 15L | C, F | None |
| Run-up to hold short | 15L | F, C, E | None |
| Taxi in | 25 | C | None |
| Taxi in | 15L | E3, E, B, F, C | 25 |

The first Ground clearance ends at a runway-specific run-up node. After the
pilot reports run-up complete on Ground, a second clearance ends at the named
hold-short node. Taxi-in routes begin at a named runway-clear node after the
Tower-directed exit and end at `above_all_parking`. Runway entry and exit
boundaries exist in the graph but are intentionally excluded from Ground taxi
routes.

All four run-up areas shown on AL-378 are represented: Alpha near Runway 7,
Charlie near Runway 15R, Foxtrot adjacent to Runway 15L, and Golf near Runway
25. The current mission assigns the Foxtrot area to 15L departures and the Golf
area to 25 departures.

## Review Checklist

Before removing the pending-review status, confirm with a KSBA-familiar pilot
or instructor:

1. The representative Above All aircraft parking point and normal ramp exit.
2. The typical Runway 25 routing through the Golf run-up area, then G, B, B1.
3. The typical Runway 15L routing through the Foxtrot run-up area, then F, C, E.
4. Whether a Runway 25 landing normally exits at C for this training scenario,
   followed by Charlie around (not across) the 15R and 15L runway ends.
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
