"""Mission state machine.

A mission is a fixed sequence of radio exchanges (Steps), each with:
- the facility/frequency the pilot must be tuned to
- graded items (regex patterns over the normalized transcript)
- a concrete ATC reply (display text + TTS-ready spoken text)
- world actions (plane movement) triggered by a passing call
- an ideal example call shown by the coach

All randomized values (runway config, weather, squawk, LUAW-or-not) are
resolved at mission start, so grading is fully deterministic. The LLM never
drives the scenario — it only polishes coach feedback and the debrief.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import airport
from .atis import Weather, atis_display, atis_spoken, make_weather
from .phraseology import (
    normalize, say_altitude, say_callsign, say_digits, say_freq,
    say_letter, say_runway, say_wind,
)


@dataclass
class Item:
    key: str
    label: str
    patterns: list[str]
    required: bool = True

    def matches(self, norm: str) -> bool:
        return any(re.search(p, norm) for p in self.patterns)


@dataclass
class AtcReply:
    facility: str
    display: str
    spoken: str
    delay_ms: int = 1400


@dataclass
class Step:
    id: str
    facility: str            # key into airport.FREQS
    coach: str               # what the coach panel tells the pilot to do
    example: str             # ideal phraseology
    items: list[Item]
    atc: AtcReply | None = None
    actions: list[dict] = field(default_factory=list)
    next_id: str | None = None
    push_after: dict | None = None  # {"delay_s":, "atc":, "advance_to":}
    check_xpdr: bool = False


def _mhz(khz: int) -> str:
    return f"{khz / 1000:.2f}".rstrip("0").rstrip(".") if khz % 100 else f"{khz / 1000:.1f}"


class Mission:
    def __init__(self, callsign: str = "N67525", coach: bool = True,
                 seed: int | None = None):
        self.rng = random.Random(seed)
        self.callsign = callsign.upper()
        self.tail = self.callsign.lstrip("N")
        self.tail_short = self.tail[-3:]
        self.coach_mode = coach

        self.config_id = self.rng.choice(["25", "25", "15L"])  # 25 favored, as IRL
        self.cfg = airport.CONFIGS[self.config_id]
        self.runway = self.cfg["runway"]
        self.wx: Weather = make_weather(self.rng, self.cfg["wind_dir"])
        self.squawk = self._make_squawk()
        self.luaw = self.rng.random() < 0.5

        self.steps = self._build_steps()
        self.current = "clearance_call"
        self.attempts_failed = 0
        self.scores: list[dict] = []
        self.log: list[dict] = []
        self.last_atc: AtcReply | None = None
        self.complete = False
        self.started = time.time()
        self.xpdr_noted = False

    # ------------------------------------------------------------ helpers

    def _make_squawk(self) -> str:
        while True:
            code = "".join(str(self.rng.randint(0, 7)) for _ in range(4))
            if code[0] != "0" and code not in ("1200", "7500", "7600", "7700"):
                return code

    def _cs(self, short: bool = True) -> str:
        return say_callsign(self.tail_short if short else self.tail)

    def _cs_disp(self, short: bool = True) -> str:
        return f"Cessna {self.tail_short if short else self.tail}"

    def _item_callsign(self) -> Item:
        return Item("callsign", "your callsign",
                    [rf"\b{self.tail}\b", rf"\b{self.tail_short}\b"])

    def atis_text(self) -> tuple[str, str]:
        return atis_display(self.wx, self.runway), atis_spoken(self.wx, self.runway)

    # -------------------------------------------------------------- steps

    def _build_steps(self) -> dict[str, Step]:
        cfg, wx, rwy = self.cfg, self.wx, self.runway
        rwy_spoken = say_runway(rwy)
        rwy_pat = r"15 ?(left|l\b)" if rwy == "15L" else r"\b25\b"
        letter = wx.letter
        dep_freq = _mhz(airport.FREQS["approach"])
        wind = f"wind {wx.wind_dir:03d} at {wx.wind_speed}"
        wind_spoken = say_wind(wx.wind_dir, wx.wind_speed)
        steps: dict[str, Step] = {}

        def add(step: Step) -> None:
            steps[step.id] = step

        add(Step(
            id="clearance_call", facility="clearance",
            coach=(f"Listen to ATIS on 132.65 first, then call Clearance Delivery on 132.9: "
                   f"who you are, where you are, ATIS letter, and your request."),
            example=(f"Santa Barbara Clearance, Cessna {self.tail}, at Above All Aviation "
                     f"with information {letter.title()}, request VFR departure to the east "
                     f"at 3,500."),
            items=[
                self._item_callsign(),
                Item("atis", f"ATIS information {letter.title()}", [rf"\b{letter}\b"]),
                Item("request", "your request (VFR departure)", [r"vfr", r"departure"]),
                Item("direction", "direction of flight (east)", [r"\beast\b", r"coastal"], required=False),
                Item("altitude", "requested altitude 3,500", [r"3500"], required=False),
            ],
            atc=AtcReply(
                "clearance",
                (f"{self._cs_disp(False)}, Santa Barbara Clearance, VFR departure to the east "
                 f"approved. Maintain VFR at or below 2,500 until advised. Departure frequency "
                 f"{dep_freq}. Squawk {self.squawk}."),
                (f"{self._cs(False)}, santa barbara clearance, V F R departure to the east "
                 f"approved. maintain V F R at or below {say_altitude(2500)} until advised. "
                 f"departure frequency {say_freq(float(dep_freq))}. "
                 f"squawk {say_digits(self.squawk)}."),
            ),
            next_id="clearance_readback",
        ))

        add(Step(
            id="clearance_readback", facility="clearance",
            coach="Read back the clearance: altitude restriction, departure frequency, squawk, callsign.",
            example=(f"Maintain VFR at or below 2,500, departure frequency {dep_freq}, "
                     f"squawk {self.squawk}, Cessna {self.tail_short}."),
            items=[
                Item("altitude", "at or below 2,500", [r"2500"]),
                Item("at_or_below", "the words 'at or below'", [r"at or below"], required=False),
                Item("dep_freq", f"departure frequency {dep_freq}", [dep_freq.replace(".", r"\.")]),
                Item("squawk", f"squawk {self.squawk}", [rf"\b{self.squawk}\b"]),
                self._item_callsign(),
            ],
            atc=AtcReply("clearance",
                         f"{self._cs_disp()}, readback correct.",
                         f"{self._cs()}, readback correct."),
            next_id="ground_call",
        ))

        add(Step(
            id="ground_call", facility="ground",
            coach=(f"Set your transponder to {self.squawk}. Then call Ground on 121.7: "
                   f"who you are, where you are, and that you're ready to taxi."),
            example=(f"Santa Barbara Ground, Cessna {self.tail}, at Above All Aviation "
                     f"with information {letter.title()}, ready to taxi."),
            items=[
                self._item_callsign(),
                Item("position", "your position (Above All Aviation)", [r"above all", r"aviation"]),
                Item("intent", "ready to taxi", [r"taxi", r"ready"]),
                Item("atis", f"information {letter.title()}", [rf"\b{letter}\b"], required=False),
            ],
            atc=AtcReply(
                "ground",
                f"{self._cs_disp()}, Santa Barbara Ground, {cfg['taxi_out']['display']}",
                (f"{self._cs()}, santa barbara ground, runway {rwy_spoken}, "
                 f"{self._spoken_taxi_out()}"),
            ),
            next_id="ground_readback",
        ))

        add(Step(
            id="ground_readback", facility="ground",
            coach="Read back the full taxi instruction — runway, route, and every crossing.",
            example=f"{cfg['taxi_out']['display'].rstrip('.')}, Cessna {self.tail_short}.",
            items=[Item(k, lbl, pats) for k, lbl, pats in cfg["taxi_out"]["readback_items"]]
                  + [self._item_callsign()],
            atc=AtcReply("ground",
                         f"{self._cs_disp()}, readback correct.",
                         f"{self._cs()}, readback correct."),
            actions=[{"type": "move", "view": "ground", "path": cfg["taxi_out"]["path"],
                      "leg": "taxi_out", "speed": "taxi"}],
            next_id="tower_checkin",
        ))

        takeoff_reply = AtcReply(
            "tower",
            (f"{self._cs_disp()}, Runway {rwy}, {wind}, cleared for takeoff, "
             f"{cfg['departure_instruction']}."),
            (f"{self._cs()}, runway {rwy_spoken}, {wind_spoken}, cleared for takeoff, "
             f"{cfg['departure_instruction']}."),
        )

        add(Step(
            id="tower_checkin", facility="tower",
            coach=("Taxi to the hold-short line. When you're there and run-up is done, "
                   "switch to Tower 119.7 and report ready for departure."),
            example=f"Santa Barbara Tower, Cessna {self.tail}, holding short Runway {rwy}, ready for departure.",
            items=[
                self._item_callsign(),
                Item("position", "holding short / ready for departure",
                     [r"holding short", r"ready for (departure|takeoff)", r"\bready\b"]),
                Item("runway", f"Runway {rwy}", [rwy_pat], required=False),
            ],
            check_xpdr=True,
            atc=(AtcReply("tower",
                          f"{self._cs_disp()}, Santa Barbara Tower, Runway {rwy}, line up and wait.",
                          f"{self._cs()}, santa barbara tower, runway {rwy_spoken}, line up and wait.")
                 if self.luaw else takeoff_reply),
            next_id="luaw_readback" if self.luaw else "takeoff_readback",
        ))

        if self.luaw:
            add(Step(
                id="luaw_readback", facility="tower",
                coach="Read back: line up and wait, runway, callsign. Then taxi onto the runway and hold.",
                example=f"Runway {rwy}, line up and wait, Cessna {self.tail_short}.",
                items=[
                    Item("luaw", "line up and wait", [r"line up and wait"]),
                    Item("runway", f"Runway {rwy}", [rwy_pat], required=False),
                    self._item_callsign(),
                ],
                actions=[{"type": "move", "view": "ground", "path": cfg["line_up"],
                          "leg": "line_up", "speed": "taxi"}],
                push_after={"delay_s": 8.0, "atc": takeoff_reply,
                            "advance_to": "takeoff_readback"},
                next_id="takeoff_readback",
            ))

        add(Step(
            id="takeoff_readback", facility="tower",
            coach="Read back the takeoff clearance: cleared for takeoff, runway, callsign.",
            example=f"Cleared for takeoff Runway {rwy}, {cfg['departure_instruction'].split(' approved')[0]}, Cessna {self.tail_short}.",
            items=[
                Item("clearance", "cleared for takeoff", [r"cleared for takeoff"]),
                Item("runway", f"Runway {rwy}", [rwy_pat], required=False),
                self._item_callsign(),
            ],
            actions=[
                {"type": "move", "view": "ground",
                 "path": (cfg["line_up"] if not self.luaw else []) + cfg["takeoff_roll"],
                 "leg": None, "speed": "roll"},
                {"type": "move", "view": "pattern",
                 "path": airport.PATTERN_PATHS[self.config_id]["climb_out"],
                 "leg": "climb_out", "speed": "fly"},
            ],
            next_id="handoff_readback",
        ))

        add(Step(
            id="handoff_readback", facility="tower",
            coach="Acknowledge the handoff, then switch to Departure on 125.4.",
            example=f"Over to Departure, Cessna {self.tail_short}.",
            items=[
                Item("handoff", "going to departure",
                     [r"departure", dep_freq.replace(".", r"\.")]),
                self._item_callsign(),
            ],
            next_id="departure_checkin",
        ))

        add(Step(
            id="departure_checkin", facility="approach",
            coach="Check in with Santa Barbara Departure on 125.4: callsign and altitude climbing.",
            example=f"Santa Barbara Departure, Cessna {self.tail}, one thousand two hundred climbing 3,500.",
            items=[
                self._item_callsign(),
                Item("altitude", "altitude climbing to 3,500", [r"3500", r"climbing"]),
            ],
            atc=AtcReply(
                "approach",
                (f"{self._cs_disp(False)}, Santa Barbara Departure, radar contact. "
                 f"Resume own navigation, maintain VFR at or below 2,500 until leaving the Class Charlie, "
                 f"then altitude your discretion."),
                (f"{self._cs(False)}, santa barbara departure, radar contact. resume own "
                 f"navigation, maintain V F R at or below {say_altitude(2500)} until leaving "
                 f"the class charlie, then altitude your discretion."),
            ),
            next_id="dep_ack",
        ))

        add(Step(
            id="dep_ack", facility="approach",
            coach="Acknowledge with a short readback: own navigation, altitude restriction, callsign.",
            example=f"Own navigation, at or below 2,500 until leaving the Charlie, Cessna {self.tail_short}.",
            items=[self._item_callsign(),
                   Item("ack", "own navigation / the restriction",
                        [r"own navigation", r"2500", r"roger", r"wilco"], required=False)],
            actions=[{"type": "move", "view": "pattern",
                      "path": airport.PATTERN_PATHS[self.config_id]["cruise_east"],
                      "leg": "cruise_east", "speed": "fly"}],
            next_id="approach_request",
        ))

        add(Step(
            id="approach_request", facility="approach",
            coach="You're 10 miles east over the coastline. Request the return: callsign, position, altitude, request.",
            example=(f"Santa Barbara Approach, Cessna {self.tail}, one zero miles east at 3,500, "
                     f"request full stop at Santa Barbara."),
            items=[
                self._item_callsign(),
                Item("position", "position (10 miles east)", [r"\beast\b", r"10 mile", r"coastline"]),
                Item("request", "full-stop landing request",
                     [r"full stop", r"landing", r"land\b", r"return"]),
            ],
            atc=AtcReply(
                "approach",
                (f"{self._cs_disp()}, Santa Barbara Approach, expect Runway {rwy}. "
                 f"Maintain VFR. Contact Santa Barbara Tower, 119.7."),
                (f"{self._cs()}, santa barbara approach, expect runway {rwy_spoken}. "
                 f"maintain V F R. contact santa barbara tower, {say_freq(119.7)}."),
            ),
            next_id="approach_readback",
        ))

        add(Step(
            id="approach_readback", facility="approach",
            coach="Read back: expect the runway, tower frequency, callsign. Then switch to Tower 119.7.",
            example=f"Expect Runway {rwy}, over to Tower 119.7, Cessna {self.tail_short}.",
            items=[
                Item("tower_freq", "Tower on 119.7", [r"119\.7", r"tower"]),
                Item("runway", f"expect Runway {rwy}", [rwy_pat], required=False),
                self._item_callsign(),
            ],
            actions=[{"type": "move", "view": "pattern",
                      "path": airport.PATTERN_PATHS[self.config_id]["inbound"],
                      "leg": "inbound", "speed": "fly"}],
            next_id="tower_inbound",
        ))

        arr = cfg["arrival_instruction"]
        add(Step(
            id="tower_inbound", facility="tower",
            coach="Call Tower on 119.7: callsign, position, full stop.",
            example=f"Santa Barbara Tower, Cessna {self.tail}, eight miles east at 2,500, full stop.",
            items=[
                self._item_callsign(),
                Item("position", "position (8 miles east)", [r"\beast\b", r"8 mile"]),
                Item("intent", "full stop", [r"full stop", r"landing", r"land\b", r"inbound"]),
            ],
            atc=AtcReply(
                "tower",
                f"{self._cs_disp()}, Santa Barbara Tower, {arr['display']}",
                f"{self._cs()}, santa barbara tower, {self._spoken_arrival()}",
            ),
            next_id="arrival_readback",
        ))

        add(Step(
            id="arrival_readback", facility="tower",
            coach="Read back the pattern entry, runway, and the report point.",
            example=f"{arr['display'].rstrip('.')}, Cessna {self.tail_short}.",
            items=[Item(k, lbl, pats) for k, lbl, pats in arr["readback_items"]]
                  + [self._item_callsign()],
            actions=[{"type": "move", "view": "pattern",
                      "path": airport.PATTERN_PATHS[self.config_id]["to_final"],
                      "leg": "to_final", "speed": "fly"}],
            next_id="position_report",
        ))

        add(Step(
            id="position_report", facility="tower",
            coach=f"You're at the report point. Report it: callsign, {arr['report_fix']}.",
            example=f"Cessna {self.tail_short}, {arr['report_fix']}, Runway {rwy}.",
            items=[
                self._item_callsign(),
                Item("report", arr["report_fix"], arr["report_patterns"]),
            ],
            atc=AtcReply(
                "tower",
                f"{self._cs_disp()}, Runway {rwy}, {wind}, cleared to land.",
                f"{self._cs()}, runway {rwy_spoken}, {wind_spoken}, cleared to land.",
            ),
            next_id="landing_readback",
        ))

        add(Step(
            id="landing_readback", facility="tower",
            coach="Read back the landing clearance: cleared to land, runway, callsign.",
            example=f"Cleared to land Runway {rwy}, Cessna {self.tail_short}.",
            items=[
                Item("clearance", "cleared to land", [r"cleared to land"]),
                Item("runway", f"Runway {rwy}", [rwy_pat], required=False),
                self._item_callsign(),
            ],
            actions=[
                {"type": "move", "view": "pattern",
                 "path": airport.PATTERN_PATHS[self.config_id]["final"],
                 "leg": None, "speed": "fly"},
                {"type": "move", "view": "ground", "path": cfg["landing_roll"],
                 "leg": "landing_roll", "speed": "roll"},
            ],
            next_id="exit_readback",
        ))

        ex = cfg["exit_instruction"]
        add(Step(
            id="exit_readback", facility="tower",
            coach="Read back the runway exit and the ground frequency.",
            example=f"{ex['display'].rstrip('.')}, Cessna {self.tail_short}.",
            items=[Item(k, lbl, pats) for k, lbl, pats in ex["readback_items"]]
                  + [self._item_callsign()],
            actions=[{"type": "move", "view": "ground", "path": ex["path"],
                      "leg": "exit", "speed": "taxi"}],
            next_id="ground_inbound",
        ))

        add(Step(
            id="ground_inbound", facility="ground",
            coach="Switch to Ground 121.7: callsign, clear of the runway and where, taxi to Above All Aviation.",
            example=f"Santa Barbara Ground, Cessna {self.tail}, {ex['clear_of']}, taxi to Above All Aviation.",
            items=[
                self._item_callsign(),
                Item("position", "clear of the runway and where", [r"clear of"]),
                Item("request", "taxi to Above All / parking",
                     [r"above all", r"parking", r"taxi to"]),
            ],
            atc=AtcReply(
                "ground",
                f"{self._cs_disp()}, Santa Barbara Ground, {cfg['taxi_in']['display']}",
                f"{self._cs()}, santa barbara ground, {self._spoken_taxi_in()}",
            ),
            next_id="taxi_in_readback",
        ))

        add(Step(
            id="taxi_in_readback", facility="ground",
            coach="Read back the taxi-in route (and any crossing!), then taxi to parking.",
            example=f"{cfg['taxi_in']['display'].rstrip('.')}, Cessna {self.tail_short}.",
            items=[Item(k, lbl, pats) for k, lbl, pats in cfg["taxi_in"]["readback_items"]]
                  + [self._item_callsign()],
            actions=[{"type": "move", "view": "ground", "path": cfg["taxi_in"]["path"],
                      "leg": "taxi_in", "speed": "taxi"}],
            next_id=None,
        ))

        return steps

    def _spoken_taxi_out(self) -> str:
        if self.config_id == "25":
            return ("taxi via charlie, hotel, cross runway one five right "
                    "and runway one five left.")
        return "taxi via charlie, cross runway one five right."

    def _spoken_arrival(self) -> str:
        if self.config_id == "25":
            return "make straight in runway two five, report three mile final."
        return "enter right base runway one five left, report two mile right base."

    def _spoken_taxi_in(self) -> str:
        if self.config_id == "25":
            return "taxi to parking via charlie."
        return ("taxi to parking via mike, alpha, foxtrot, "
                "cross runway two five at foxtrot.")

    # ------------------------------------------------------------ gameplay

    def step(self) -> Step:
        return self.steps[self.current]

    def handle_transmission(self, freq_khz: int, raw_text: str,
                            xpdr_code: str = "", xpdr_mode: str = "") -> dict:
        norm = normalize(raw_text)
        self.log.append({"who": "pilot", "freq": freq_khz, "text": raw_text,
                         "t": time.time() - self.started})
        step = self.step()
        expected_khz = airport.FREQS[step.facility]

        # not on the right frequency?
        if freq_khz != expected_khz:
            return self._wrong_freq(freq_khz, step)

        # "say again" repeats the last ATC transmission
        if "say again" in norm and self.last_atc:
            return self._result(heard=True, atc=self.last_atc, repeat=True,
                                coach="Repeated. " + step.coach)

        # transponder gate at the tower check-in
        if step.check_xpdr and xpdr_code and xpdr_code != self.squawk:
            reply = AtcReply(
                "tower",
                f"{self._cs_disp()}, verify transponder code. Squawk {self.squawk}.",
                f"{self._cs()}, verify transponder code. squawk {say_digits(self.squawk)}.",
            )
            self.attempts_failed += 1
            return self._result(
                heard=True, atc=reply, passed=False,
                coach=f"Your transponder is on {xpdr_code} but you were assigned {self.squawk}. Fix it and call again.")

        matched = [i for i in step.items if i.matches(norm)]
        missing_req = [i for i in step.items if i.required and i not in matched]
        missing_opt = [i for i in step.items if not i.required and i not in matched]

        if missing_req:
            self.attempts_failed += 1
            if len(matched) == 0:
                reply = AtcReply(
                    step.facility,
                    f"Aircraft calling {airport.FACILITY_NAMES[step.facility]}, say again.",
                    f"aircraft calling {airport.FACILITY_NAMES[step.facility].lower()}, say again.")
            else:
                prev = self._prev_instruction()
                body = prev or "I need a full readback."
                reply = AtcReply(
                    step.facility,
                    f"{self._cs_disp()}, negative. {body} Read back all instructions.",
                    f"{self._cs()}, negative. {self._prev_instruction_spoken() or body.lower()} read back all instructions.")
            coach = ("Missing: " + "; ".join(i.label for i in missing_req)
                     + f". Try: “{step.example}”")
            return self._result(heard=True, atc=reply, passed=False, coach=coach,
                                missing=[i.label for i in missing_req])

        # passed
        score = max(0, 100 - 25 * self.attempts_failed - 10 * len(missing_opt))
        if step.check_xpdr and xpdr_mode and xpdr_mode.lower() != "alt" and not self.xpdr_noted:
            self.xpdr_noted = True
            score = max(0, score - 5)
        self.scores.append({
            "step": step.id, "score": score,
            "missed": [i.label for i in missing_opt],
            "attempts": self.attempts_failed + 1,
        })
        self.attempts_failed = 0

        atc = step.atc
        push = step.push_after
        actions = step.actions
        if step.next_id:
            self.current = step.next_id
        else:
            pass  # final step: completion fires on leg_complete("taxi_in")

        next_step = self.steps.get(self.current)
        coach = next_step.coach if next_step and next_step.id != step.id else ""
        if atc:
            self.last_atc = atc
            self.log.append({"who": "atc", "freq": freq_khz, "text": atc.display,
                             "t": time.time() - self.started})
        return self._result(heard=True, atc=atc, passed=True, score=score,
                            actions=actions, coach=coach, push=push)

    def _prev_instruction(self) -> str | None:
        for entry in reversed(self.log):
            if entry["who"] == "atc" and "negative" not in entry["text"].lower() \
                    and "say again" not in entry["text"].lower():
                return entry["text"]
        return None

    def _prev_instruction_spoken(self) -> str | None:
        if self.last_atc and "negative" not in self.last_atc.display.lower():
            return self.last_atc.spoken
        return None

    def _wrong_freq(self, freq_khz: int, step: Step) -> dict:
        expected = airport.FREQS[step.facility]
        for fac, khz in airport.FREQS.items():
            if khz == freq_khz and fac != "atis":
                reply = AtcReply(
                    fac,
                    (f"{self._cs_disp()}, this is {airport.FACILITY_NAMES[fac]}. "
                     f"Contact {airport.FACILITY_NAMES[step.facility]} on {_mhz(expected)}."),
                    (f"{self._cs()}, this is {airport.FACILITY_NAMES[fac].lower()}. contact "
                     f"{airport.FACILITY_NAMES[step.facility].lower()} on {say_freq(expected / 1000)}."),
                )
                return self._result(
                    heard=True, atc=reply, passed=False,
                    coach=f"Wrong frequency — you need {airport.FACILITY_NAMES[step.facility]} on {_mhz(expected)}.")
        hint = ("ATIS is a recorded broadcast — nobody is listening. "
                if freq_khz == airport.FREQS["atis"] else "Nothing but static. ")
        return self._result(
            heard=False, atc=None, passed=False,
            coach=hint + f"You need {airport.FACILITY_NAMES[step.facility]} on {_mhz(expected)}.")

    def leg_complete(self, leg: str) -> dict | None:
        """Client finished animating a movement leg. Returns an optional push."""
        cfg = self.cfg
        if leg == "taxi_out":
            return {"coach": self.steps["tower_checkin"].coach}
        if leg == "climb_out":
            reply = AtcReply("tower",
                             f"{self._cs_disp()}, contact Departure.",
                             f"{self._cs()}, contact departure.")
            self.last_atc = reply
            self.log.append({"who": "atc", "freq": airport.FREQS["tower"],
                             "text": reply.display, "t": time.time() - self.started})
            return {"atc": reply, "coach": self.steps["handoff_readback"].coach}
        if leg == "cruise_east":
            return {"coach": self.steps["approach_request"].coach}
        if leg == "to_final":
            return {"coach": self.steps["position_report"].coach}
        if leg == "landing_roll":
            ex = cfg["exit_instruction"]
            reply = AtcReply(
                "tower",
                f"{self._cs_disp()}, {ex['display']}",
                f"{self._cs()}, {ex['spoken_exit']}, contact ground point seven.",
            )
            self.last_atc = reply
            self.log.append({"who": "atc", "freq": airport.FREQS["tower"],
                             "text": reply.display, "t": time.time() - self.started})
            return {"atc": reply, "coach": self.steps["exit_readback"].coach}
        if leg == "taxi_in":
            self.complete = True
            return {"complete": True, "debrief": self.debrief()}
        return None

    def apply_push(self, push: dict) -> AtcReply:
        """Advance state for a scheduled push and log it."""
        reply: AtcReply = push["atc"]
        if push.get("advance_to"):
            self.current = push["advance_to"]
        self.last_atc = reply
        self.log.append({"who": "atc", "freq": airport.FREQS[reply.facility],
                         "text": reply.display, "t": time.time() - self.started})
        return reply

    # ------------------------------------------------------------- summary

    def brief(self) -> dict:
        return {
            "callsign": self.callsign,
            "tail": self.tail,
            "coach": self.coach_mode,
            "mission": (
                "You are in a Cessna 152 at Above All Aviation, Santa Barbara (KSBA), "
                "engine running. Plan: VFR departure to the east along the coastline at 3,500, "
                "about 10 miles out, then return for a full-stop landing and taxi back. "
                "Start by listening to ATIS on 132.65, then call Clearance Delivery on 132.9."
            ),
            "freqs": {k: _mhz(v) for k, v in airport.FREQS.items()},
            "chart_info": airport.CHART_INFO,
            "plane": {"view": "ground", "pos": list(airport.NODES["fbo"])},
            "pattern_points": {k: list(v) for k, v in airport.PATTERN_POINTS.items()},
            "coach_hint": self.steps["clearance_call"].coach,
        }

    def debrief(self) -> dict:
        total = round(sum(s["score"] for s in self.scores) / max(1, len(self.scores)))
        return {
            "total": total,
            "steps": [
                {**s, "example": self.steps[s["step"]].example,
                 "name": s["step"].replace("_", " ")}
                for s in self.scores
            ],
            "duration_min": round((time.time() - self.started) / 60, 1),
        }

    def _result(self, heard: bool, atc: AtcReply | None = None, passed: bool | None = None,
                score: int | None = None, actions: list | None = None, coach: str = "",
                missing: list | None = None, push: dict | None = None,
                repeat: bool = False) -> dict:
        return {
            "heard": heard,
            "passed": passed,
            "score": score,
            "atc": atc,
            "actions": actions or [],
            "coach": coach if self.coach_mode else "",
            "missing": missing or [],
            "push": push,
            "repeat": repeat,
            "step_id": self.current,
            "complete": self.complete,
        }
