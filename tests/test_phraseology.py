"""Normalization (speech -> canonical) and verbalization (canonical -> spoken)."""

import re

import pytest

from server.phraseology import (
    normalize, say_altitude, say_callsign, say_digits, say_freq, say_runway,
    tail_regex,
)


class TestNormalize:
    def test_squawk_digits(self):
        assert "squawk 4571" in normalize("Squawk four five seven one")

    def test_frequency_with_point(self):
        assert "121.7" in normalize("contact ground one two one point seven")

    def test_frequency_with_decimal_word(self):
        assert "125.4" in normalize("departure one two five decimal four")

    def test_niner_and_tree(self):
        assert "119.3" in normalize("tower one one niner point tree")

    def test_thousands(self):
        assert "3500" in normalize("climbing three thousand five hundred")

    def test_one_thousand_two_hundred(self):
        assert "1200" in normalize("one thousand two hundred")

    def test_numeric_commas(self):
        assert "2500" in normalize("maintain 2,500")

    def test_callsign_merge(self):
        assert "cessna 67525" in normalize("Cessna six seven five two five")

    def test_short_callsign(self):
        assert "cessna 525" in normalize("Cessna five two five")

    def test_ambiguous_to_stays_a_word(self):
        # "to"/"for" must not digitize when used as words
        n = normalize("taxi to runway two five")
        assert "taxi to runway 25" in n

    def test_tail_regex_spoken_and_typed(self):
        pat = tail_regex("3083S")
        assert re.search(pat, normalize("Cessna three zero eight three sierra"))
        assert re.search(pat, normalize("Cessna 3083S"))
        short = tail_regex("83S")
        assert re.search(short, normalize("Cessna eight three sierra"))
        # all-digit tails keep working
        assert re.search(tail_regex("67525"), normalize("Cessna six seven five two five"))

    @pytest.mark.parametrize(
        "spoken",
        [
            "Cessna three zero six, eight Sierra",
            "Cessna three zero six. eight Sierra",
            "Cessna three, zero six eight Sierra",
        ],
    )
    def test_alpha_tail_tolerates_punctuation_split_digits(self, spoken):
        assert re.search(tail_regex("3068S"), normalize(spoken))

    @pytest.mark.parametrize(
        "spoken",
        ["Cessna six, eight Sierra", "Cessna six. eight Sierra"],
    )
    def test_short_alpha_tail_tolerates_punctuation_split_digits(self, spoken):
        assert re.search(
            tail_regex("68S"),
            normalize(spoken),
        )

    @pytest.mark.parametrize(
        "spoken",
        [
            "Cessna three zero six, uh, eight Sierra",
            "Cessna three zero six. um eight Sierra",
            "Cessna three zero six er eight Sierra",
            "Cessna three zero six eight, ah, Sierra",
        ],
    )
    def test_alpha_tail_tolerates_brief_fillers(self, spoken):
        assert re.search(tail_regex("3068S"), normalize(spoken))

    @pytest.mark.parametrize(
        "spoken",
        [
            "Cessna six, uh, eight Sierra",
            "Cessna six eight, um, Sierra",
        ],
    )
    def test_short_alpha_tail_tolerates_brief_fillers(self, spoken):
        assert re.search(tail_regex("68S"), normalize(spoken))

    @pytest.mark.parametrize(
        "spoken",
        [
            "Cessna three zero six, six, eight Sierra",
            "Cessna three zero six, eight, eight Sierra",
            "Cessna six, six, eight Sierra",
        ],
    )
    def test_alpha_tail_tolerates_separated_repeated_digits(self, spoken):
        expected = "68S" if spoken.startswith("Cessna six") else "3068S"
        assert re.search(tail_regex(expected), normalize(spoken))

    @pytest.mark.parametrize(
        "spoken",
        [
            "Cessna three zero six well eight Sierra",
            "Cessna three zero six seven eight Sierra",
            "Cessna 30668S",
        ],
    )
    def test_alpha_tail_rejects_unknown_or_contiguous_extra_tokens(self, spoken):
        assert not re.search(tail_regex("3068S"), normalize(spoken))

    def test_digit_only_tail_does_not_cross_clause_boundary(self):
        norm = normalize("Cessna 525, three mile final")
        assert norm == "cessna 525 3 mile final"
        assert not re.search(tail_regex("5253"), norm)

    @pytest.mark.parametrize(
        ("spoken", "merged_value"),
        [
            ("squawk four five, heading seven one", "4571"),
            ("departure one two five point, heading four", "125.4"),
            ("runway one, five mile final", "15"),
            ("maintain two thousand, five hundred foot ceiling", "2500"),
        ],
    )
    def test_other_numeric_fields_remain_separated_across_clauses(
            self, spoken, merged_value):
        assert merged_value not in normalize(spoken).split()

    def test_mic_resolves_to_mike(self):
        # whisper transcribes spoken "Mike" as "mic"; taxiway M readbacks
        # must still match \bmike\b
        assert "right at mike" in normalize("Turn right at mic, ground point seven")
        assert "via mike alpha foxtrot" in normalize("taxi via mic, alpha, foxtrot")

    @pytest.mark.parametrize("spoken", ["X-ray", "X ray"])
    def test_xray_variants(self, spoken):
        assert normalize(f"information {spoken}") == "information xray"

    def test_juliet_variant(self):
        assert normalize("information Juliet") == "information juliett"

    def test_hyphenated(self):
        assert "straight in" in normalize("make straight-in runway two five")

    def test_runway_letters_survive(self):
        assert "15 left" in normalize("runway one five left")

    def test_punctuation_stripped(self):
        assert normalize("Roger, wilco!") == "roger wilco"


class TestSay:
    def test_say_digits(self):
        assert say_digits("4571") == "four five seven one"

    def test_say_digits_niner(self):
        assert say_digits("119") == "one one niner"

    def test_say_freq(self):
        assert say_freq(121.7) == "one two one point seven"

    def test_say_runway_sides(self):
        assert say_runway("15L") == "one five left"
        assert say_runway("25") == "two five"

    def test_say_altitude(self):
        assert say_altitude(2500) == "two thousand five hundred"
        assert say_altitude(3000) == "three thousand"

    def test_say_callsign(self):
        assert say_callsign("N67525") == "cessna six seven five two five"
        assert say_callsign("N67525", short=True) == "cessna five two five"

    def test_roundtrip_squawk(self):
        # what ATC speaks must normalize back to the same code
        assert "4571" in normalize(say_digits("4571"))

    def test_roundtrip_freq(self):
        assert "121.7" in normalize(say_freq(121.7))
