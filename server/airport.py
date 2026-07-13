"""KSBA (Santa Barbara Muni) static data.

Ground coordinates are normalized (0..1) against web/assets/ksba-diagram.svg,
the cropped and 90-deg-clockwise-rotated FAA diagram (see scripts/prep_map.py
and server/chart_geometry.py). Pattern-view coordinates are normalized against
an abstract canvas where the coastline runs along the bottom and east is right.

Note on chart orientation: after the rotation, runway 7-25 runs horizontal
(runway 7 west/left, runway 25 east/right) and page-up is roughly true north
(~346 deg), so the 15/33 runways slope steeply down to the right. All paths
below follow the drawn pavement. These coordinates were produced by applying
chart_geometry.portrait_to_chart to the original portrait-referenced values.
"""

from .chart_geometry import CHART_CYCLE, CHART_EFFECTIVE, CHART_SOURCE_URL

FIELD = {
    "id": "KSBA",
    "name": "Santa Barbara Municipal",
    "elevation": 14,
    "pattern_altitude": 1000,  # AGL, what students fly
}

# kHz to avoid float comparisons; display as MHz.
FREQS = {
    "atis": 132650,
    "clearance": 132900,
    "ground": 121700,
    "tower": 119700,
    "approach": 125400,
}


def mhz(khz: int) -> str:
    """Format a kHz frequency as its MHz display string (e.g. 132650 -> '132.65')."""
    return f"{khz / 1000:.2f}".rstrip("0").rstrip(".") if khz % 100 else f"{khz / 1000:.1f}"

FACILITY_NAMES = {
    "atis": "Santa Barbara ATIS",
    "clearance": "Santa Barbara Clearance",
    "ground": "Santa Barbara Ground",
    "tower": "Santa Barbara Tower",
    "approach": "Santa Barbara Approach",
}

# Non-critical chart marginalia relocated from the map into the UI drawer,
# transcribed from the FAA KSBA airport diagram (AL-378). Consumed by
# Mission.brief() as brief["chart_info"]. Frequencies are derived from FREQS so
# the drawer can never drift from the sim radio; only the tower UHF (which the
# sim does not model) is a hand-written suffix.
CHART_INFO = {
    "frequencies": [
        {"label": "ATIS", "value": mhz(FREQS["atis"])},
        {"label": "Clearance", "value": mhz(FREQS["clearance"])},
        {"label": "Ground", "value": mhz(FREQS["ground"])},
        {"label": "Tower", "value": f"{mhz(FREQS['tower'])} / 254.35"},
        {"label": "Approach", "value": mhz(FREQS["approach"])},
    ],
    "field": {"elevation_ft": 14, "pattern_altitude_ft_agl": 1000},
    "runways": [
        {"id": "7-25", "dimensions_ft": "6052 x 150",
         "pavement_rating": "PCR 658 F/D/X/T", "strength": "S-113, D-188, 2D-318"},
        {"id": "15L-33R", "dimensions_ft": "4180 x 75",
         "pavement_rating": "PCR 45 F/D/X/T", "strength": "S-39, D-61, 2D-108"},
        {"id": "15R-33L", "dimensions_ft": "4184 x 100",
         "pavement_rating": "PCR 45 F/D/X/T", "strength": "S-25, D-39"},
    ],
    "notes": [
        "CAUTION: Be alert to runway crossing clearances. Readback of all "
        "runway holding instructions is required.",
        "SAID in use. Operate transponders with altitude reporting mode and "
        "ADS-B (if equipped) enabled on all airport surfaces.",
        "Magnetic variation 14° E (annual rate of change 0.0° W, Jan 1985).",
        f"FAA airport diagram AL-378, cycle {CHART_CYCLE}, effective {CHART_EFFECTIVE}.",
        f"Source: {CHART_SOURCE_URL}",
    ],
}

# ------------------------------------------------------------- pattern view

PATTERN_POINTS = {
    "airport":   (0.24, 0.58),
    "east_10mi": (0.86, 0.70),
    "east_8mi":  (0.72, 0.68),
    "final_3mi": (0.42, 0.62),
}

PATTERN_PATHS = {
    "25": {
        "climb_out": [(0.24, 0.58), (0.14, 0.62), (0.09, 0.68), (0.13, 0.76), (0.24, 0.78)],
        "cruise_east": [(0.24, 0.78), (0.45, 0.74), (0.65, 0.72), (0.86, 0.70)],
        "inbound": [(0.86, 0.70), (0.72, 0.68)],
        "to_final": [(0.72, 0.68), (0.55, 0.65), (0.42, 0.62)],
        "final": [(0.42, 0.62), (0.24, 0.58)],
    },
    "15L": {
        "climb_out": [(0.24, 0.58), (0.30, 0.66), (0.30, 0.74), (0.38, 0.77)],
        "cruise_east": [(0.38, 0.77), (0.55, 0.74), (0.70, 0.72), (0.86, 0.70)],
        "inbound": [(0.86, 0.70), (0.72, 0.68)],
        "to_final": [(0.72, 0.68), (0.52, 0.58), (0.36, 0.48)],  # right base
        "final": [(0.36, 0.48), (0.24, 0.58)],
    },
}

# ------------------------------------------------------------- runway configs

CONFIGS = {
    "25": {
        "runway": "25",
        "departure_instruction": "left turn on course approved",
        "arrival_instruction": {
            "display": "Make straight-in Runway 25, report three mile final.",
            "readback_items": [
                ("entry", "straight-in", [r"straight in", r"straight-in"]),
                ("runway", "Runway 25", [r"\b25\b"]),
            ],
            "report_fix": "three mile final",
            "report_patterns": [r"\b3 mile\b", r"three mile", r"\bfinal\b"],
            "report_readback_patterns": [r"\b3 mile\b", r"three mile"],
        },
    },
    "15L": {
        "runway": "15L",
        "departure_instruction": "left turn eastbound approved",
        "arrival_instruction": {
            "display": "Enter right base Runway 15 Left, report two mile right base.",
            "readback_items": [
                ("entry", "right base", [r"right base"]),
                ("runway", "Runway 15L", [r"15 ?(left|l\b)"]),
            ],
            "report_fix": "two mile right base",
            "report_patterns": [r"\b2 mile\b", r"two mile", r"right base"],
            "report_readback_patterns": [r"\b2 mile\b", r"two mile"],
        },
    },
}
