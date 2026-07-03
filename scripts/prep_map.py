"""Render the FAA KSBA airport diagram PDF to a crisp PNG for the map view."""

import sys
from pathlib import Path

import fitz  # pymupdf

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "FlightAware_SBA_APD_AIRPORT DIAGRAM.PDF"
OUT = ROOT / "web" / "assets" / "ksba-diagram.png"


def main() -> None:
    doc = fitz.open(PDF)
    page = doc[0]
    # 3x zoom gives ~1836x2772 — sharp enough to read taxiway labels when zoomed.
    pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pix.save(OUT)
    print(f"wrote {OUT} ({pix.width}x{pix.height})")


if __name__ == "__main__":
    sys.exit(main())
