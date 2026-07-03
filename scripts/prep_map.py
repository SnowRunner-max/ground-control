"""Render the FAA KSBA airport diagram to the map assets.

The published PDF is portrait and carries marginalia (comm frequencies, a
runway data table, the crossing-caution note, the magnetic-variation block)
that clutter the map and are surfaced in the UI drawer instead. This script:

  1. redacts those marginalia (they sit clear of the airfield linework),
  2. crops to the neatline,
  3. rotates 90 degrees clockwise (widescreen aspect, upright labels,
     runway 7-25 horizontal),

then writes a vector ``ksba-diagram.svg`` (the map uses this) plus a matching
raster ``ksba-diagram.png`` (fallback / accuracy check). Because the source is
vector art and every step is a mechanical page transform, the exported chart is
as accurate as the original FAA diagram.

The crop box, redaction rects, and the matching coordinate transform live in
``server.chart_geometry`` so they can be unit-tested and reused by the node
migration.
"""

import sys
from pathlib import Path

import fitz  # pymupdf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server.chart_geometry import NEATLINE, REDACTIONS  # noqa: E402

PDF = ROOT / "FlightAware_SBA_APD_AIRPORT DIAGRAM.PDF"
OUT_SVG = ROOT / "web" / "assets" / "ksba-diagram.svg"
OUT_PNG = ROOT / "web" / "assets" / "ksba-diagram.png"


def main() -> None:
    doc = fitz.open(PDF)
    page = doc[0]

    # 1. Redact marginalia. Redaction removes only the covered content; the
    #    white diagram background makes the rects vanish. Done first, in the
    #    original (unrotated, uncropped) page coordinate space.
    for rect in REDACTIONS:
        page.add_redact_annot(fitz.Rect(*rect))
    # LINE_ART_REMOVE_IF_COVERED also drops vector marginalia fully inside a
    # rect (e.g. the magnetic-variation arrow) without touching the lat/lon
    # graticule, whose long lines merely pass through and are never covered.
    page.apply_redactions(graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)

    # 2. Crop to the neatline, then 3. rotate 90 CW. set_cropbox is applied in
    #    unrotated page coords, which is what NEATLINE is measured in.
    page.set_cropbox(fitz.Rect(*NEATLINE))
    page.set_rotation(90)

    OUT_SVG.parent.mkdir(parents=True, exist_ok=True)

    # Vector export: text as paths so no browser font dependency.
    svg = page.get_svg_image(matrix=fitz.Matrix(1, 1), text_as_path=True)
    OUT_SVG.write_text(svg)

    # Raster twin at 3x for the pixel-diff accuracy check and as a fallback.
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    pix.save(OUT_PNG)

    print(f"wrote {OUT_SVG}")
    print(f"wrote {OUT_PNG} ({pix.width}x{pix.height}, aspect {pix.width / pix.height:.3f})")


if __name__ == "__main__":
    sys.exit(main())
