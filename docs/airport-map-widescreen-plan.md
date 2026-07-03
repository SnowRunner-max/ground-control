# Plan: Widescreen airport map, vector rendering, and chart-info drawer

## Problem

The ground view renders `web/assets/ksba-diagram.png` — a portrait rasterization
of the FAA KSBA airport diagram — contain-fit into a landscape map panel. On a
widescreen monitor more than half the panel is empty margin and the airfield
itself is small. The chart also carries marginalia (comm frequencies, runway
data table, caution note, title blocks, lat/lon grid labels) that clutter the
map area but aren't needed *on* the map during play.

## Findings (verified against the source PDF)

These were confirmed experimentally with PyMuPDF against
`FlightAware_SBA_APD_AIRPORT DIAGRAM.PDF`; they anchor the whole plan:

1. **The chart is drawn landscape but printed portrait.** Page-up on the
   portrait page corresponds to true heading ~076.4° (the note at the top of
   `server/airport.py` already documents this). All labels *inside* the
   neatline (taxiway letters, "RUN-UP AREA", "TRANSIENT GA PARKING/FBO",
   hold-short boxes, runway numbers) are drawn rotated 90° on the portrait
   page.
2. **Rotating the page 90° clockwise fixes everything at once** (verified by
   rendering with `page.set_rotation(90)`):
   - Landscape aspect (~1.53:1) that nearly fills a widescreen panel.
   - All interior labels read upright.
   - Runway 7-25 runs horizontal (7 left, 25 right).
   - Orientation becomes near-conventional: page-up ≈ 346.4° true, i.e. within
     14° of north-up, east to the right.
3. **The source PDF is vector art**, and `page.get_svg_image()` (with
   `set_rotation(90)` applied) produces a ~370 KB standalone SVG of the same
   geometry. No tracing or redrawing is involved — this is a mechanical
   format conversion of the FAA linework, so accuracy is inherited from the
   original, satisfying the "perfectly accurate" requirement.
4. **After rotation, the marginalia land in known spots**: the frequency block
   (ATIS 132.65 / TWR 119.7 254.35 / GND 121.7 / CLNC DEL 132.9) top-left
   inside the neatline; the caution note bottom-center; the runway PCN data
   table center-left; magnetic-variation arrow and annual-rate note
   bottom-left; title blocks and effective-date strips *outside* the neatline
   on the edges. This makes a crop + targeted redaction feasible.

## Part A — Chart preparation pipeline (`scripts/prep_map.py`)

Extend the existing prep script to produce a cropped, rotated **SVG** (keeping
the PNG path available as a fallback until the migration is proven):

1. Open the PDF, `page.set_rotation(90)` (exact quarter-turn, confirmed
   correct direction).
2. **Redact interior marginalia** with `page.add_redact_annot(rect)` +
   `apply_redactions()` before export. Redaction removes content inside the
   given rects without disturbing anything else, so chart accuracy elsewhere
   is untouched. Rects (in page coordinates, to be measured precisely during
   implementation):
   - comm-frequency block (relocated to the drawer),
   - runway PCN data table,
   - caution note ("BE ALERT TO RUNWAY CROSSING CLEARANCES…"),
   - magnetic-variation arrow / annual-rate-of-change note.
   Everything operationally relevant stays: taxiways and letters, hold-short
   boxes HS1/HS2, runway numbers/dimensions painted along runways, elevations,
   run-up areas, buildings, FBO/terminal labels.
3. **Crop to the neatline interior** with `page.set_cropbox(rect)`, dropping
   the title blocks, effective-date strips, and lat/lon border labels.
4. Export `web/assets/ksba-diagram.svg` via `page.get_svg_image(text_as_path=True)`
   (text as paths avoids any font-availability issues in the browser).
5. Print the crop rectangle and rotation as normalized constants — these feed
   the coordinate migration below.
6. Keep emitting a (rotated, cropped) high-res PNG too, used only for the
   accuracy check in the verification step.

## Part B — Coordinate migration (`server/airport.py`, `server/scenario.py`)

All ground coordinates are normalized 0..1 against the diagram image, so they
must be re-referenced to the new cropped+rotated frame. The transform is exact
and mechanical:

- 90° CW rotation in normalized space: `(x, y) → (1 − y, x)`.
- Then the crop remap: `x' = (x − crop_x) / crop_w`, `y' = (y − crop_y) / crop_h`,
  where the crop box is expressed in the rotated image's normalized space.

Applied once, via a small throwaway script, to:

- the 21 entries in `NODES` (this also covers every taxi/runway path, since
  paths are built from nodes),
- nothing else server-side: `PATTERN_POINTS` / `PATTERN_PATHS` live in the
  abstract coastal-view space and are unaffected; the brief's initial plane
  position is `NODES["fbo"]`.

Update the orientation note at the top of `airport.py` (page-up becomes
~346.4°, runways 15/33 now slope steeply, 7-25 near-horizontal). The default
initial plane heading in `web/map.js` (`-Math.PI / 2`, nose-up) should be
revisited to match the ramp orientation in the new frame; everything else
derives heading from path direction in screen space, so animation needs no
changes.

## Part C — Rendering the map as vector with an aircraft marker (`web/map.js`)

Replace the ground-view raster blit with an SVG-based map so the chart stays
crisp at any size and the aircraft is a first-class marker *on the map*:

- **Recommended approach: inline SVG map component.** Fetch
  `ksba-diagram.svg` once and inline it into `#map-panel` inside a wrapper
  `<svg>` (or `<g>`), and add an overlay group containing:
  - the aircraft marker — the existing silhouette polygon from
    `GameMap.drawPlane()` transliterated to an SVG `<path>`, positioned with
    `transform="translate(px py) rotate(deg)"`,
  - (kept available for the future) a layer for route/path highlighting.
- Keep the existing animation engine (`runActions` / `animatePath` / `tick`)
  intact — it already works in normalized coordinates; only the *output* side
  changes: instead of repainting a canvas each frame, the rAF loop updates the
  marker's `transform` attribute. This is a small, low-risk refactor of
  `draw()`/`drawPlane()`/`groundRect()`.
- The **pattern (coastal) view** is procedural canvas art, not chart-derived.
  Two options:
  1. Convert it to a static inline SVG scene with the same plane marker —
     yields a single rendering path and deletes the canvas entirely.
  2. Leave it on canvas and toggle canvas/SVG visibility per view.
  Option 1 is preferred for one coherent renderer, but option 2 is an
  acceptable fallback if it keeps the change smaller; decide at implementation
  time based on diff size.
- Contain-fit logic carries over: the SVG wrapper uses
  `preserveAspectRatio="xMidYMid meet"`, and `toPx` maps normalized coords
  into the SVG viewBox instead of canvas pixels (simpler: use viewBox units
  directly so no per-resize math is needed at all).
- **Optional follow-up (not in scope, enabled by this work):** pan/zoom and a
  follow-the-aircraft camera become trivial with an SVG viewBox.

## Part D — Chart-info drawer (`web/index.html`, `web/styles.css`, `web/app.js`, `server/airport.py`)

Relocate the redacted marginalia plus the sidebar frequency strip into a
collapsible drawer attached to the map panel:

- **Server:** add a `CHART_INFO` structure to `airport.py` (source of truth,
  transcribed verbatim from the diagram) and include it in the
  `/api/mission/new` brief:
  - comm frequencies (already in `FREQS`; add tower UHF 254.35 for display),
  - field elevation 14, pattern altitude (already in `FIELD`),
  - runway data: 7-25 6052×150 PCN 66 F/A/X/U; 15L-33R 4184×100 PCN 14
    F/A/X/T; 15R-33L 4180×75 PCN 19 F/A/X/U (with S/D/2D load figures),
  - the runway-crossing caution note,
  - magnetic variation 12.2°E (0.1°W annual change), chart id AL-378 (FAA),
    effective dates.
- **UI:** a drawer anchored to the map panel's left edge with a slim
  always-visible tab ("CHART INFO"); clicking (or a keyboard shortcut) slides
  it over the map. Contents grouped as: Frequencies · Field/Runway data ·
  Notes. Styled with the existing `.panel` look.
- Move the `#freq-list` chips out of the Mission sidebar card into the drawer
  to avoid duplication (the mission card keeps only the mission text and the
  ATIS cheat). Frequencies remain one click away, which mirrors real cockpit
  use of the taxi diagram.

## Verification

1. **Geometric accuracy (the hard requirement):** render the new SVG and the
   redaction-free rotated PNG at identical resolution and pixel-diff them
   (masking the redacted rects); differences beyond anti-aliasing tolerance
   fail the check. This proves the vector conversion didn't move anything.
2. **Coordinate migration:** a one-off overlay render plotting every `NODES`
   point onto the new SVG — each node must sit on its taxiway/runway exactly
   as the old points sat on the old PNG. Spot-check fbo (FBO ramp), hs25,
   rwy25_thr, rwy15l_exit.
3. **Gameplay:** run the app on a widescreen viewport; fly both runway
   configs (25 and 15L) end-to-end confirming taxi-out, takeoff roll, pattern
   view, landing roll, exit, and taxi-in animations all track the drawn
   pavement; verify view switching and the drawer open/close.
4. **Existing tests:** `tests/` suite must pass unchanged (server logic is
   untouched except coordinate values and the added `CHART_INFO`); check
   whether any e2e test asserts on coordinates and update if so.

## Risks and mitigations

- **Redaction rects clipping chart linework** (e.g. the caution note sits near
  taxiway A): measure rects against the vector coordinates, keep them tight,
  and rely on the pixel-diff mask review to catch overreach.
- **`get_svg_image` fidelity:** already smoke-tested (valid ~370 KB SVG with
  correct rotated viewBox). If any rendering artifact shows up,
  `mutool draw -F svg` is a drop-in alternative; the raster PNG path remains
  as a final fallback (rotated/cropped PNG still solves the widescreen
  problem on its own).
- **SVG DOM performance:** one static chart plus a single animated transform
  is well within budget; no per-frame layout is triggered by attribute
  transforms on a marker group.

## Suggested implementation order

1. Prep pipeline (Part A) → produces the SVG + crop constants.
2. Coordinate migration (Part B) + accuracy overlay check.
3. Map renderer swap (Part C) behind the same `GameMap` API.
4. Drawer (Part D).
5. Full verification pass (visual + pixel diff + test suite).

Steps 1–2 are independently shippable (the rotated raster alone already fixes
widescreen use); 3 and 4 build on them.
