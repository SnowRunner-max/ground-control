"""Weather-first departure-runway selection for the supported KSBA mission.

The simulator currently models Runways 25 and 15L. Selection is based on wind
components first and a small, explicit training preference second. It is not a
prediction of the runway that ATC will assign in live operations.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, radians, sin


@dataclass(frozen=True, slots=True)
class RunwayPolicy:
    runway: str
    magnetic_heading: int
    max_tailwind_kt: float
    max_crosswind_kt: float
    preference_bonus: float = 0.0


@dataclass(frozen=True, slots=True)
class RunwayCandidate:
    runway: str
    magnetic_heading: int
    headwind_kt: float
    tailwind_kt: float
    crosswind_kt: float
    preference_bonus: float
    score: float
    eligible: bool


@dataclass(frozen=True, slots=True)
class RunwaySelection:
    wind_dir: int
    wind_speed: int
    selected_runway: str
    overridden: bool
    reason: str
    candidates: tuple[RunwayCandidate, ...]

    def as_dict(self) -> dict:
        return {
            "wind_dir": self.wind_dir,
            "wind_speed": self.wind_speed,
            "selected_runway": self.selected_runway,
            "overridden": self.overridden,
            "reason": self.reason,
            "candidates": [asdict(candidate) for candidate in self.candidates],
        }


RUNWAY_POLICIES: dict[str, RunwayPolicy] = {
    "25": RunwayPolicy(
        runway="25",
        magnetic_heading=255,
        max_tailwind_kt=5.0,
        max_crosswind_kt=12.0,
        preference_bonus=1.5,
    ),
    "15L": RunwayPolicy(
        runway="15L",
        magnetic_heading=152,
        max_tailwind_kt=5.0,
        max_crosswind_kt=12.0,
    ),
}


def wind_components(
    wind_dir: int,
    wind_speed: float,
    runway_heading: int,
) -> tuple[float, float]:
    """Return signed headwind and absolute crosswind components in knots."""
    delta = ((wind_dir - runway_heading + 180) % 360) - 180
    headwind = wind_speed * cos(radians(delta))
    crosswind = abs(wind_speed * sin(radians(delta)))
    return headwind, crosswind


def _candidate(wind_dir: int, wind_speed: int, policy: RunwayPolicy) -> RunwayCandidate:
    headwind, crosswind = wind_components(
        wind_dir, wind_speed, policy.magnetic_heading,
    )
    tailwind = max(0.0, -headwind)
    eligible = (
        tailwind <= policy.max_tailwind_kt
        and crosswind <= policy.max_crosswind_kt
    )
    # Crosswind matters, but should not outweigh a materially better headwind.
    score = headwind - 0.15 * crosswind + policy.preference_bonus
    return RunwayCandidate(
        runway=policy.runway,
        magnetic_heading=policy.magnetic_heading,
        headwind_kt=round(headwind, 2),
        tailwind_kt=round(tailwind, 2),
        crosswind_kt=round(crosswind, 2),
        preference_bonus=policy.preference_bonus,
        score=round(score, 2),
        eligible=eligible,
    )


def select_runway(
    wind_dir: int,
    wind_speed: int,
    *,
    override: str | None = None,
) -> RunwaySelection:
    """Select the best supported runway, or honor an explicit training override."""
    if not (0 <= wind_dir <= 360):
        raise ValueError("wind direction must be between 0 and 360 degrees")
    if wind_speed < 0:
        raise ValueError("wind speed cannot be negative")

    candidates = tuple(
        _candidate(wind_dir, wind_speed, policy)
        for policy in RUNWAY_POLICIES.values()
    )
    by_runway = {candidate.runway: candidate for candidate in candidates}

    if override is not None:
        try:
            selected = by_runway[override.upper()]
        except KeyError as exc:
            raise ValueError(f"unsupported runway override {override!r}") from exc
        reason = "explicit training override"
        overridden = True
    else:
        eligible = tuple(candidate for candidate in candidates if candidate.eligible)
        if not eligible:
            raise ValueError(
                "weather exceeds the modeled limits for supported Runways 25 and 15L"
            )
        selected = max(eligible, key=lambda candidate: candidate.score)
        reason = (
            f"best eligible score: {selected.headwind_kt:.1f} kt headwind, "
            f"{selected.crosswind_kt:.1f} kt crosswind, "
            f"{selected.preference_bonus:.1f} preference bonus"
        )
        overridden = False

    return RunwaySelection(
        wind_dir=wind_dir,
        wind_speed=wind_speed,
        selected_runway=selected.runway,
        overridden=overridden,
        reason=reason,
        candidates=candidates,
    )
