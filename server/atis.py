"""ATIS text generation for a randomized mission."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .phraseology import NATO, say_altitude, say_digits, say_letter, say_runway

ATIS_LETTERS = [letter for letter in NATO.values()]

# A bounded KSBA training-weather distribution. It is sampled before runway
# selection and keeps the current two-runway simulation within a scenario that
# at least one modeled runway can normally serve. Westerly winds are weighted
# more heavily to represent the common Runway 25 case.
TRAINING_WIND_DIRECTIONS = tuple(range(120, 281, 10))
TRAINING_WIND_WEIGHTS = tuple(
    4 if direction >= 220 else 2 if direction <= 170 else 1
    for direction in TRAINING_WIND_DIRECTIONS
)


@dataclass
class Weather:
    letter: str          # "bravo"
    time_z: str          # "0353"
    wind_dir: int
    wind_speed: int
    visibility: int
    sky: str             # display, e.g. "few clouds at 2,000"
    sky_spoken: str
    temp: int
    dewpoint: int
    altimeter: str       # "29.92"


def make_weather(rng: random.Random) -> Weather:
    skies = [
        ("clear", "sky clear"),
        ("few clouds at 2,000", "few clouds at two thousand"),
        ("scattered clouds at 2,500", "two thousand five hundred scattered"),
    ]
    sky, sky_spoken = rng.choice(skies)
    temp = rng.randint(14, 24)
    return Weather(
        letter=rng.choice(ATIS_LETTERS),
        time_z=f"{rng.randint(16, 23):02d}53",
        wind_dir=rng.choices(TRAINING_WIND_DIRECTIONS, TRAINING_WIND_WEIGHTS, k=1)[0],
        wind_speed=rng.randint(6, 14),
        visibility=10,
        sky=sky,
        sky_spoken=sky_spoken,
        temp=temp,
        dewpoint=temp - rng.randint(4, 8),
        altimeter=f"{rng.choice(['29', '30'])}.{rng.randint(85, 99) if rng.random() < .5 else rng.randint(0, 15):02d}",
    )


def atis_display(wx: Weather, runway: str) -> str:
    return (
        f"Santa Barbara Airport information {wx.letter.title()}, {wx.time_z} zulu. "
        f"Wind {wx.wind_dir:03d} at {wx.wind_speed}. Visibility {wx.visibility}. {wx.sky.capitalize()}. "
        f"Temperature {wx.temp}, dew point {wx.dewpoint}. Altimeter {wx.altimeter}. "
        f"Landing and departing Runway {runway}. "
        f"VFR departures contact Clearance Delivery on 132.9 prior to taxi. "
        f"Advise on initial contact you have information {wx.letter.title()}."
    )


def atis_spoken(wx: Weather, runway: str) -> str:
    return (
        f"Santa Barbara airport information {say_letter(wx.letter)}, "
        f"{say_digits(wx.time_z)} zulu. "
        f"Wind {say_digits(f'{wx.wind_dir:03d}')} at {say_digits(str(wx.wind_speed))}. "
        f"Visibility one zero. {wx.sky_spoken}. "
        f"Temperature {say_digits(str(wx.temp))}, dew point {say_digits(str(wx.dewpoint))}. "
        f"Altimeter {say_digits(wx.altimeter.replace('.', ''))}. "
        f"Landing and departing runway {say_runway(runway)}. "
        f"V F R departures contact clearance delivery on {say_digits('132.9')} prior to taxi. "
        f"Advise on initial contact you have information {say_letter(wx.letter)}."
    )
