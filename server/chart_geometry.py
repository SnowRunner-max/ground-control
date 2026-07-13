"""Geometry for adapting the FAA KSBA portrait airport diagram to the map.

The published diagram (``FAA_KSBA_APD_2607.pdf``) is drawn
landscape but printed portrait: page-up is roughly true heading 076. For a
widescreen map we crop to the neatline and rotate the page 90 degrees
clockwise, which makes runway 7-25 horizontal and every interior label read
upright.

This module is the single source of truth for that adaptation: the crop box,
the marginalia redaction rectangles, and the coordinate transform. It is used
both by ``scripts/prep_map.py`` (to render the chart asset) and by the ground
graph in ``server.ground``; keeping the
constants here lets the transform be unit-tested. All rectangles are in
portrait PDF points; ``portrait_to_chart`` works in normalized (0..1) space.
"""

from __future__ import annotations

# Keep the checked-in chart source and UI currency notice tied to one release.
CHART_CYCLE = "2607"
CHART_EFFECTIVE = "09 JUL 2026 to 06 AUG 2026"
CHART_SOURCE_FILE = "FAA_KSBA_APD_2607.pdf"
CHART_SOURCE_URL = "https://aeronav.faa.gov/d-tpp/2607/00378AD.PDF"
CHART_SOURCE_SHA256 = "e146968bbd25f886b3e16ecae8816590cf2f1224c39173fb122d4e3639aa9de2"

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
    (18.0, 470.0, 84.5, 547.0),    # comm frequency block + tower name (bottom-left)
    (240.0, 415.0, 315.0, 502.0),  # runway PCR / dimensions data table
    (326.0, 230.0, 351.0, 532.0),  # runway-crossing caution note
    (250.0, 45.0, 350.0, 135.0),   # magnetic-variation arrow + annual-rate note
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
