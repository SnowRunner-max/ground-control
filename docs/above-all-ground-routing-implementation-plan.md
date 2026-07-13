# Above All Aviation Ground Routing Implementation Plan

## Objective

Make every mission in this version begin at Above All Aviation's current
north-side KSBA location, select a plausible departure runway from independently
generated weather and airport operating preferences, and issue and animate a
realistic taxi clearance using the current airport layout and taxiway names.

This work should correct the complete ground-operation model rather than only
moving the initial aircraft marker. The chart, named ground nodes, route data,
ATC phraseology, readback grading, and animation must all describe the same
airport state.

## Confirmed Defects

1. `server/airport.py` labels the existing `fbo` node as Above All Aviation,
   but that node is on the west/south transient GA ramp. Above All's current
   address is 45 Hartley Place on the north-side ramp.
2. The bundled FAA diagram was effective 22 February through 21 March 2024.
   KSBA renamed taxiways after that chart was published, so several simulated
   instructions and paths use obsolete identifiers.
3. `Mission` chooses a runway first and then constrains generated wind to favor
   it. This produces internally consistent ATIS text but does not actually
   select a runway from weather.
4. Taxi paths, displayed instructions, spoken instructions, and readback rules
   are maintained separately. They can disagree without a structural failure.
5. The browser teleports the aircraft to the first point of every movement
   action. That can conceal gaps between the current position and an incorrect
   route.
6. Tests establish that coordinates are normalized, but do not establish that
   named nodes represent the correct real-world landmarks or that paths remain
   on pavement.

## Source of Truth

Use the current FAA KSBA airport diagram as the geometric and taxiway naming
source of truth:

- FAA terminal-procedure directory:
  <https://aeronav.faa.gov/d-tpp/2607/>
- Current chart at the time of planning (9 July–6 August 2026):
  <https://aeronav.faa.gov/d-tpp/2607/00378AD.PDF>
- FAA notice concerning KSBA's taxiway nomenclature changes:
  <https://www.faa.gov/flight_deck/sba>
- Above All Aviation location:
  <https://www.aboveallsba.com/contact>

The implementation must record the chart cycle/effective dates in the
repository and make a future chart refresh straightforward. The simulator is a
training aid, not a substitute for current charts, ATIS, or NOTAMs.

## Scope

### Included

- Current KSBA diagram assets and coordinate transformation.
- An explicit Above All Aviation start/parking location.
- Current taxiway and hold-short geometry needed by supported missions.
- Weather-driven departure-runway selection.
- Taxi-out, runway-entry, runway-exit, and taxi-in route generation.
- Ground ATC display/spoken phraseology and readback grading derived from the
  selected route.
- Movement continuity checks in the client.
- Unit, API, geometry, and full-mission regression coverage.
- Documentation of operational assumptions and chart currency.

### Initially excluded

- Live ATIS, METAR, or NOTAM integration.
- Dynamic traffic sequencing, closures, or controller reroutes.
- Arbitrary user-selected parking locations.
- A general-purpose routing engine for airports other than KSBA.
- Claims that a single simulated clearance is what ATC will issue in every
  real-world circumstance.

## Design

### 1. Separate facilities, graph nodes, and routes

Replace the ambiguous `fbo` identity with explicit named locations. At minimum:

- `above_all_parking`
- `above_all_ramp_exit`
- current taxiway junctions used by supported routes
- runway hold-short points
- runway threshold/line-up points
- landing rollout and runway-exit points

Each movement edge should carry operational metadata rather than only two
coordinates. A suitable shape is:

```python
GroundEdge(
    start="above_all_ramp_exit",
    end="c_f_junction",
    taxiway="C",
    kind="taxiway",
    crosses_runway=None,
)
```

Other `kind` values can distinguish ramp taxilanes, taxiways, hold-short
boundaries, runway crossings, runway entry, and runway movement. Route output
should contain both the node path used for animation and ordered instruction
elements used for phraseology and grading.

Do not call the graph complete merely because all points are in the `[0, 1]`
range. Every supported edge must be checked visually against the rendered
current chart.

### 2. Generate one canonical taxi clearance

Create a route result that is the sole source for:

- displayed ATC clearance;
- spoken ATC clearance;
- readback items and matching patterns;
- animation coordinates;
- expected final hold-short point; and
- required runway-crossing clearances.

For example:

```python
TaxiRoute(
    destination="25",
    taxiways=("C", "F", "B", "B1"),
    crossings=(),
    hold_short="25",
    path=(...),
)
```

The taxiway sequence above is a chart-derived candidate, not a final
operational assertion. Before it becomes an accepted training route, validate
the exact Above All parking spot, ramp exit, and typical controller clearance
with a KSBA-familiar instructor or pilot. Apply the same validation to every
supported runway and taxi-in route.

Runway crossings must never be inferred only from clearance prose. They must be
explicit graph edges so the route builder, grader, and tests agree about them.

### 3. Select runway from weather

Change mission creation to this sequence:

1. Generate a plausible KSBA weather sample independently of runway choice.
2. Calculate headwind/tailwind and crosswind components for supported runway
   ends.
3. Reject or strongly penalize runway ends exceeding configured Cessna 152
   training limits.
4. Apply airport/training preferences as a secondary score, including runway
   length, noise/operational assumptions, and a preference for Runway 25 when
   conditions are comparable.
5. Select the best supported runway and use it consistently in ATIS, ground,
   tower, paths, and arrival configuration.

Keep runway-selection policy in explicit data rather than random-choice code.
For deterministic tests, allow weather and/or selected runway to be injected
when constructing a mission. A runway override is appropriate for tests and a
future training selector, but production defaults should remain weather-driven.

Decide whether the first release will continue to support only Runways 25 and
15L or add Runways 7 and 33. If only two runway ends remain supported, weather
generation must avoid implausible scenarios that neither can serve safely, and
the UI/documentation must state that limitation.

### 4. Preserve movement continuity

On ground-to-ground actions, do not teleport the aircraft to the route start.
Compare the aircraft's current normalized position with the first route point:

- begin normally when within a small tolerance;
- log and reject the action in development/tests when discontinuous; and
- reserve explicit repositioning for view-space transitions such as switching
  between the airport and airborne pattern views.

This turns route discontinuities into observable defects instead of hiding
them.

### 5. Make chart currency visible

Update the chart information drawer with the current FAA effective dates and
data. Store chart metadata alongside the asset, including source URL, cycle,
effective dates, crop box, and transformation. Add a small maintenance note
describing how to refresh the source chart and revalidate operational nodes.

## Work Plan

### Phase 1: Establish current geometry

1. Add the current FAA KSBA PDF as the chart source, subject to the repository's
   asset policy.
2. Update `scripts/prep_map.py` and `server/chart_geometry.py` for the current
   page geometry, redactions, crop, and rotation.
3. Regenerate the SVG and PNG chart assets.
4. Plot temporary labeled overlays for every old and proposed node.
5. Locate Above All using its current north-ramp facility and choose a realistic
   aircraft parking/start point rather than the building centroid.
6. Re-measure runway thresholds, hold-short points, exits, and required taxiway
   centerlines.
7. Remove old nodes only after all consumers have migrated.

Deliverable: a current chart with reviewed landmark coordinates and a dedicated
Above All start node.

### Phase 2: Build the operational ground graph

1. Define typed nodes and edges for all supported taxi-out and taxi-in routes.
2. Mark every runway boundary and crossing explicitly.
3. Implement a small KSBA route builder that can select a legal path from Above
   All to a runway hold-short point and from runway exit back to Above All.
4. Add route validation: connected edges, known taxiway names, correct start
   and destination, no implicit runway crossings, and no duplicate or reversed
   instruction elements.
5. Review candidate routes with a KSBA-familiar pilot/instructor and record the
   approved training assumptions.

Deliverable: canonical `TaxiRoute` objects for each supported departure and
arrival case.

### Phase 3: Derive ATC and grading from routes

1. Replace handwritten taxi display/spoken strings with formatters operating on
   `TaxiRoute`.
2. Generate ordered readback requirements from the same route, including the
   assigned runway, taxiway sequence, hold-short instruction where applicable,
   and every runway crossing.
3. Preserve robust speech-normalization alternatives for letters and runway
   sides without accepting missing safety-critical items.
4. Update ground-call coaching to identify Above All Aviation consistently.
5. Generate taxi-in instructions and grading through the same mechanism.

Deliverable: one route description drives ATC, grading, and animation.

### Phase 4: Implement runway selection

1. Define supported runway headings and policy data.
2. Add wind-component calculations with unit tests.
3. Generate weather independently.
4. Select the runway from wind components and policy scores.
5. Add constructor/API overrides for deterministic test scenarios.
6. Ensure the selected runway is exposed in the mission brief/debug state and
   remains immutable for the mission unless a future runway-change feature is
   intentionally implemented.

Deliverable: wind and operating policy determine the runway, not the reverse.

### Phase 5: Harden client movement

1. Initialize the plane solely from the mission brief's `above_all_parking`
   position; remove the duplicate hard-coded default as an operational value.
2. Add ground-action continuity validation.
3. Keep explicit repositioning only for changes between ground and pattern
   coordinate spaces.
4. Optionally add a subtle "Above All Aviation" start marker for orientation,
   provided it does not obscure the FAA chart.
5. Verify taxi speed and aircraft heading along each rebuilt route.

Deliverable: the marker starts at Above All and moves continuously along the
cleared route.

### Phase 6: Tests and documentation

Add the following coverage:

- `test_above_all_node_is_on_north_ramp`
- `test_every_mission_starts_at_above_all`
- `test_taxi_routes_start_at_current_aircraft_position`
- `test_taxi_routes_end_at_assigned_runway_hold_short`
- `test_route_crossings_match_readback_requirements`
- `test_route_phraseology_matches_route_taxiways`
- `test_no_route_uses_retired_taxiway_names`
- `test_wind_components_for_each_supported_runway`
- `test_runway_is_selected_after_weather_generation`
- `test_selected_runway_has_acceptable_tailwind`
- `test_same_seed_produces_same_weather_runway_and_route`
- full-mission tests for every supported runway configuration

Geometry tests should use reviewed landmark regions/polygons or a maintained
reference overlay, not brittle exact pixel comparisons alone. Include a manual
visual checklist at desktop and widescreen viewport sizes.

Update `README.md` with supported runway ends, the current-chart disclaimer,
the Above All start behavior, runway-selection behavior, and chart-refresh
instructions.

## Acceptance Criteria

The work is complete when:

1. Every newly created mission places the aircraft at a reviewed parking point
   on Above All Aviation's north-side ramp.
2. The displayed chart and all spoken/displayed taxiway identifiers use the
   same current FAA chart cycle.
3. Weather is generated before runway selection, and the chosen runway has a
   defensible wind/policy score recorded in debug state.
4. Ground issues a route from Above All to the selected runway using the
   current taxiway names and all required runway-crossing instructions.
5. The aircraft follows that route continuously on depicted pavement and stops
   at the correct hold-short point.
6. ATC text, spoken text, readback grading, and animation are generated from one
   canonical route.
7. Taxi-in returns the aircraft to Above All, not generic parking.
8. Automated tests fail if the spawn point, route geometry, route phraseology,
   runway crossings, or runway-selection ordering regresses.
9. A KSBA-familiar pilot/instructor has reviewed the chosen training routes and
   operational assumptions.
10. The existing offline test suite and the new ground-routing/full-mission
    tests pass.

## Risks and Mitigations

- **Charts change again:** keep chart metadata and refresh tooling explicit;
  avoid embedding taxiway names throughout scenario code.
- **FAA diagrams do not identify individual tenants:** validate Above All's
  actual parking/start point against local knowledge rather than equating its
  street-address centroid with an aircraft position.
- **ATC may issue alternate routes:** describe routes as representative training
  scenarios and keep the graph capable of supporting alternatives later.
- **Route automation adds complexity:** begin with a small typed KSBA graph and
  reviewed route policy; do not introduce a general airport-routing framework.
- **Wind alone does not determine runway use:** keep airport preference and
  training constraints explicit and testable, while avoiding claims of live
  operational accuracy.
- **Current user work is already in progress:** implement in focused commits and
  avoid overwriting unrelated modified files.

## Suggested Commit Sequence

1. `docs: record Above All ground-routing implementation plan`
2. `data: update KSBA diagram and chart geometry`
3. `data: add Above All node and current ground graph`
4. `server: derive taxi clearances and grading from routes`
5. `server: select runway from weather and airport policy`
6. `web: enforce continuous ground movement`
7. `tests: cover KSBA landmarks routes and runway selection`
8. `docs: document chart currency and supported operations`

