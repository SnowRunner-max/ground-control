"""Geometry for adapting the FAA KSBA portrait airport diagram to the map.

The published diagram (``FlightAware_SBA_APD_AIRPORT DIAGRAM.PDF``) is drawn
landscape but printed portrait: page-up is roughly true heading 076. For a
widescreen map we crop to the neatline and rotate the page 90 degrees
clockwise, which makes runway 7-25 horizontal and every interior label read
upright.

This module is the single source of truth for that adaptation: the crop box,
the marginalia redaction rectangles, and the coordinate transform. It is used
both by ``scripts/prep_map.py`` (to render the chart asset) and by the one-off
migration that rebased ``server.airport.NODES`` onto the new frame; keeping the
constants here lets the transform be unit-tested. All rectangles are in
portrait PDF points; ``portrait_to_chart`` works in normalized (0..1) space.
"""

from __future__ import annotations

# Portrait page size of the source PDF, in PDF points.
PAGE_W = 387.36
PAGE_H = 594.0

# Neatline (the inner border of the diagram) in portrait PDF points. Measured
# as the largest rectangle in the page's vector drawings. Everything outside it
# (title blocks, effective-date strips, lat/lon border labels) is cropped away.
NEATLINE = (18.0, 44.9, 369.3, 549.3)  # x0, y0, x1, y1

# Non-critical marginalia to redact before export, each verified clear of the
# airfield linework (nodes span roughly x[136,213], y[150,325] in page points).
# Their content is relocated into the UI chart-info drawer.
REDACTIONS = (
    (18.0, 470.0, 89.0, 547.0),    # comm frequency block + tower name (bottom-left)
    (240.0, 286.0, 309.0, 366.0),  # runway PCN / dimensions data table
    (322.0, 214.0, 342.0, 458.0),  # runway-crossing caution note
    (243.0, 460.0, 340.0, 545.0),  # magnetic-variation arrow + annual-rate note
)


def portrait_to_chart(nx: float, ny: float) -> tuple[float, float]:
    """Map a coordinate normalized against the full portrait page onto the
    cropped + 90-degree-clockwise-rotated chart frame (also normalized 0..1).
    """
    x0, y0, x1, y1 = NEATLINE
    # full-page normalized -> portrait PDF points
    px, py = nx * PAGE_W, ny * PAGE_H
    # crop to the neatline interior
    cx = (px - x0) / (x1 - x0)
    cy = (py - y0) / (y1 - y0)
    # rotate 90 clockwise: (x, y) -> (1 - y, x)
    return (1.0 - cy, cx)
