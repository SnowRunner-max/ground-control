"""Normalization (speech -> canonical) and verbalization (canonical -> spoken)."""

from server.phraseology import (
    normalize, say_altitude, say_callsign, say_digits, say_freq, say_runway,
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
