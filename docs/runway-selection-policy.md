# KSBA Runway Selection Policy

## Purpose and Scope

The simulation generates weather before choosing a runway. It currently models
only Runways 25 and 15L, matching the ground routes and airborne scenarios
implemented in this version. The selector is a deterministic training policy,
not a prediction of a live ATC runway assignment.

## Supported Runways

| Runway | Modeled magnetic heading | Tailwind limit | Crosswind limit | Preference bonus |
| --- | ---: | ---: | ---: | ---: |
| 25 | 255° | 5 kt | 12 kt | 1.5 |
| 15L | 152° | 5 kt | 12 kt | 0 |

The limits are simulator policy values for generating suitable Cessna 152
training scenarios. They are not presented as aircraft limitations or a
substitute for the POH, instructor direction, ATIS, NOTAMs, or ATC clearance.

## Weather Generation

Training winds are sampled independently from runway selection:

- direction: 120° through 280° in 10° increments;
- speed: 6 through 14 kt;
- westerly directions are weighted most heavily;
- southerly directions have a smaller secondary weight; and
- directions between those sectors remain possible.

This bounded distribution keeps the two-runway simulation within conditions
that normally leave at least one modeled runway eligible. Supporting live or
arbitrary weather later will require additional runway ends or an explicit
"no suitable modeled runway" experience.

## Selection

For each supported runway, the selector calculates:

- signed headwind component;
- tailwind component;
- absolute crosswind component;
- eligibility under the configured limits; and
- score: `headwind - 0.15 × crosswind + preference bonus`.

The eligible runway with the highest score is selected. The Runway 25 bonus is
small enough for a materially better southerly wind to select 15L while making
25 win when conditions are otherwise comparable.

If neither runway is eligible, mission creation fails instead of inventing a
safe assignment. An explicit runway override is available for deterministic
testing and future targeted training; the resulting debug data clearly marks
the selection as overridden even when its wind components exceed policy.

## Reproducibility and Debugging

`Mission` accepts a seed, injected `Weather`, wind tuple, and runway override.
The mission brief and `/api/debug/step` expose the selected runway, wind,
candidate components and scores, reason, and override status. The HTTP mission
creation endpoint accepts `seed`, paired `wind_dir`/`wind_speed`, and `runway`
for deterministic test scenarios.
