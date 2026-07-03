"""KSBA (Santa Barbara Muni) static data.

Ground coordinates are normalized (0..1) against web/assets/ksba-diagram.png.
Pattern-view coordinates are normalized against an abstract canvas where the
coastline runs along the bottom and east is to the right.

Note on page orientation: the FAA diagram is drawn with runway 7-25 near
vertical, so page-up is roughly heading 076 — the 15/33 runways therefore
slope slightly *up* to the right. All paths below follow the drawn pavement.
"""

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

FACILITY_NAMES = {
    "atis": "Santa Barbara ATIS",
    "clearance": "Santa Barbara Clearance",
    "ground": "Santa Barbara Ground",
    "tower": "Santa Barbara Tower",
    "approach": "Santa Barbara Approach",
}

# ------------------------------------------------------------- ground graph

NODES = {
    "fbo":        (0.378, 0.547),  # Above All Aviation, south transient GA ramp
    "ramp_out":   (0.408, 0.524),
    "hs1":        (0.445, 0.540),  # HS1: hold short of 25 at Charlie
    "c_h":        (0.423, 0.474),
    "h_15r":      (0.430, 0.428),  # Hotel crossing runway 15R
    "h_mid":      (0.434, 0.404),
    "h_15l":      (0.438, 0.379),  # Hotel crossing runway 15L
    "h_north":    (0.447, 0.314),
    "h_top":      (0.452, 0.272),
    "hs25":       (0.462, 0.262),  # hold short runway 25
    "rwy25_thr":  (0.469, 0.253),
    "rwy25_td":   (0.472, 0.310),  # landing touchdown zone
    "rwy25_exit": (0.480, 0.535),  # rollout point abeam Charlie
    "c_15r":      (0.387, 0.416),  # Charlie crossing runway 15R
    "hs15l":      (0.365, 0.399),  # hold short runway 15L at Charlie
    "rwy15l_thr": (0.351, 0.386),
    "rwy15l_td":  (0.370, 0.383),
    "rwy15l_exit": (0.550, 0.353),  # exit right at Mike
    "m_clear":    (0.545, 0.395),
    "m_a":        (0.533, 0.508),   # Mike/Alpha junction
    "a_f":        (0.532, 0.547),   # Alpha/Foxtrot
    "f_cross":    (0.500, 0.544),   # Foxtrot crossing runway 25
}


def path(*names: str) -> list[list[float]]:
    return [list(NODES[n]) for n in names]


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
        "wind_dir": (230, 270),
        "taxi_out": {
            "display": "Runway 25, taxi via Charlie, Hotel, cross Runway 15 Right and Runway 15 Left.",
            "path": path("fbo", "ramp_out", "c_h", "h_15r", "h_mid", "h_15l",
                         "h_north", "h_top", "hs25"),
            "readback_items": [
                ("runway", "Runway 25", [r"\brunway 25\b", r"\b25\b"]),
                ("route", "via Charlie, Hotel", [r"\bcharlie\b.*\bhotel\b"]),
                ("cross_15r", "cross Runway 15R", [r"cross.*15 ?(right|r\b)"]),
                ("cross_15l", "cross Runway 15L", [r"cross.*15 ?(left|l\b)"]),
            ],
        },
        "line_up": path("hs25", "rwy25_thr"),
        "takeoff_roll": path("rwy25_thr", "rwy25_exit"),
        "departure_instruction": "left turn on course approved",
        "arrival_instruction": {
            "display": "Make straight-in Runway 25, report three mile final.",
            "readback_items": [
                ("entry", "straight-in", [r"straight in", r"straight-in"]),
                ("runway", "Runway 25", [r"\b25\b"]),
            ],
            "report_fix": "three mile final",
            "report_patterns": [r"\b3 mile\b", r"three mile", r"\bfinal\b"],
        },
        "landing_roll": path("rwy25_td", "rwy25_exit"),
        "exit_instruction": {
            "display": "Turn right at Charlie, contact Ground point seven.",
            "spoken_exit": "turn right at charlie",
            "path": path("rwy25_exit", "hs1"),
            "readback_items": [
                ("exit", "right at Charlie", [r"\bcharlie\b"]),
                ("ground", "Ground on 121.7", [r"121\.7", r"point (7|seven)", r"\bground\b"]),
            ],
            "clear_of": "clear of Runway 25 at Charlie",
        },
        "taxi_in": {
            "display": "Taxi to parking via Charlie.",
            "path": path("hs1", "fbo"),
            "readback_items": [
                ("route", "via Charlie", [r"\bcharlie\b", r"\bparking\b"]),
            ],
        },
    },
    "15L": {
        "runway": "15L",
        "wind_dir": (120, 170),
        "taxi_out": {
            "display": "Runway 15 Left, taxi via Charlie, cross Runway 15 Right.",
            "path": path("fbo", "ramp_out", "c_h", "c_15r", "hs15l"),
            "readback_items": [
                ("runway", "Runway 15L", [r"15 ?(left|l\b)"]),
                ("route", "via Charlie", [r"\bcharlie\b"]),
                ("cross_15r", "cross Runway 15R", [r"cross.*15 ?(right|r\b)"]),
            ],
        },
        "line_up": path("hs15l", "rwy15l_thr"),
        "takeoff_roll": path("rwy15l_thr", "rwy15l_exit"),
        "departure_instruction": "left turn eastbound approved",
        "arrival_instruction": {
            "display": "Enter right base Runway 15 Left, report two mile right base.",
            "readback_items": [
                ("entry", "right base", [r"right base"]),
                ("runway", "Runway 15L", [r"15 ?(left|l\b)"]),
            ],
            "report_fix": "two mile right base",
            "report_patterns": [r"\b2 mile\b", r"two mile", r"right base"],
        },
        "landing_roll": path("rwy15l_td", "rwy15l_exit"),
        "exit_instruction": {
            "display": "Turn right at Mike, contact Ground point seven.",
            "spoken_exit": "turn right at mike",
            "path": path("rwy15l_exit", "m_clear"),
            "readback_items": [
                ("exit", "right at Mike", [r"\bmike\b"]),
                ("ground", "Ground on 121.7", [r"121\.7", r"point (7|seven)", r"\bground\b"]),
            ],
            "clear_of": "clear of Runway 15 Left at Mike",
        },
        "taxi_in": {
            "display": "Taxi to parking via Mike, Alpha, Foxtrot, cross Runway 25 at Foxtrot.",
            "path": path("m_clear", "m_a", "a_f", "f_cross", "hs1", "fbo"),
            "readback_items": [
                ("route", "via Mike, Alpha, Foxtrot", [r"\bmike\b.*\bfoxtrot\b", r"\balpha\b.*\bfoxtrot\b"]),
                ("cross_25", "cross Runway 25", [r"cross.*25"]),
            ],
        },
    },
}
