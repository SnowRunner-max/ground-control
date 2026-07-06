"""Aviation phraseology helpers.

Two directions:
- normalize(): pilot speech transcript -> canonical text for grading
  ("squawk four five seven one" -> "squawk 4571")
- say_*(): canonical values -> spoken words for TTS
  (121.7 -> "one two one point seven")
"""

from __future__ import annotations

import re

DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "won": "1", "two": "2", "to": "2",
    "three": "3", "tree": "3", "four": "4", "for": "4", "five": "5",
    "fife": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "niner": "9",
}
# "to"/"for"/"oh"/"won" only convert when adjacent to other digits — handled below.
AMBIGUOUS = {"to", "for", "oh", "won"}

TENS_WORDS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
TEENS_WORDS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19,
}

SPOKEN_DIGIT = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four",
    "5": "five", "6": "six", "7": "seven", "8": "eight", "9": "niner",
}

# STT homophones: whisper often writes the abbreviation, not the NATO word.
HOMOPHONES = {"mic": "mike"}

NATO = {
    "a": "alpha", "b": "bravo", "c": "charlie", "d": "delta", "e": "echo",
    "f": "foxtrot", "g": "golf", "h": "hotel", "i": "india", "j": "juliett",
    "k": "kilo", "l": "lima", "m": "mike", "n": "november", "o": "oscar",
    "p": "papa", "q": "quebec", "r": "romeo", "s": "sierra", "t": "tango",
    "u": "uniform", "v": "victor", "w": "whiskey", "x": "xray",
    "y": "yankee", "z": "zulu",
}


def normalize(text: str) -> str:
    """Canonicalize a transcript for pattern matching."""
    text = text.lower()
    text = re.sub(r"(?<=\d),(?=\d)", "", text)  # 3,500 -> 3500 (before ',' is stripped)
    # clause punctuation becomes a boundary token so digit groups on either
    # side never merge ("Cessna 525, three mile final" != "5253 mile final")
    text = re.sub(r"[,;:!?]", " | ", text)
    text = re.sub(r"[^a-z0-9.\s/|-]", " ", text)
    # non-decimal periods are sentence ends -> boundaries too
    text = re.sub(r"(?<!\d)\.|\.(?!\d)", " | ", text)
    text = text.replace("-", " ")
    tokens = text.split()

    out: list[str] = []
    for i, tok in enumerate(tokens):
        tok = HOMOPHONES.get(tok, tok)
        if tok in DIGIT_WORDS:
            if tok in AMBIGUOUS:
                # only digitize when a neighbor is numeric-ish
                prev_num = bool(out) and _is_numy(out[-1])
                nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
                nxt_num = _is_numy(nxt) or nxt in DIGIT_WORDS and nxt not in AMBIGUOUS
                if not (prev_num or nxt_num):
                    out.append(tok)
                    continue
            out.append(DIGIT_WORDS[tok])
        elif tok in TEENS_WORDS:
            out.append(str(TEENS_WORDS[tok]))
        elif tok in TENS_WORDS:
            out.append(str(TENS_WORDS[tok]))
        elif tok in ("point", "decimal"):
            out.append(".")
        elif tok in ("thousand", "hundred") and out and out[-1].isdigit():
            mult = 1000 if tok == "thousand" else 100
            out[-1] = str(int(out[-1]) * mult)
        else:
            out.append(tok)

    return _merge_numbers(out)


def _is_numy(tok: str) -> bool:
    return bool(re.fullmatch(r"[\d.]+", tok))


def _merge_numbers(tokens: list[str]) -> str:
    """Collapse digit runs: '1 2 1 . 7' -> '121.7'; '3500 500' -> '4000' is NOT
    attempted — only concatenation of single digits and additive hundred/thousand."""
    out: list[str] = []
    for tok in tokens:
        if out and _is_numy(tok) and _is_numy(out[-1]):
            prev = out[-1]
            if tok == "." or prev.endswith("."):
                out[-1] = prev + tok
            elif "." in prev:
                out[-1] = prev + tok  # decimals: 121. + 7
            elif len(tok) == 1 and len(prev) < 5:
                # digit run: 45 + 7 -> 457; capped at 5 (tail numbers) so a
                # following group can't swallow it ("67525 one zero miles")
                out[-1] = prev + tok
            elif prev.endswith("000") and len(tok) == 3:
                out[-1] = str(int(prev) + int(tok))  # 3000 + 500 -> 3500
            else:
                out.append(tok)
        elif tok == ".":
            if out and _is_numy(out[-1]) and "." not in out[-1]:
                out[-1] = out[-1] + "."
            # bare/duplicate point: drop
        else:
            out.append(tok)
    # drop boundary markers and any stray trailing periods
    cleaned = (t.rstrip(".") for t in out if t != "|")
    return " ".join(t for t in cleaned if t).strip()


def tail_regex(tail: str) -> str:
    """Regex over normalized() text for a tail number. '3083S' must match
    both the spoken form '3083 sierra' and the typed form '3083s'."""
    tail = tail.lower()
    parts: list[str] = []
    for ch in tail:
        if ch.isdigit() and parts and parts[-1].isdigit():
            parts[-1] += ch
        else:
            parts.append(ch if ch.isdigit() else NATO.get(ch, ch))
    spoken = " ".join(parts)
    if spoken == tail:
        return rf"\b{tail}\b"
    return rf"\b(?:{spoken}|{tail})\b"


# ---------------------------------------------------------------- TTS side

def say_digits(value: str) -> str:
    """'4571' -> 'four five seven one'; letters become NATO words."""
    words = []
    for ch in str(value).lower():
        if ch in SPOKEN_DIGIT:
            words.append(SPOKEN_DIGIT[ch])
        elif ch == ".":
            words.append("point")
        elif ch in NATO:
            words.append(NATO[ch])
    return " ".join(words)


def say_freq(freq: float) -> str:
    return say_digits(f"{freq:.4g}".rstrip("0").rstrip(".") if freq != int(freq) else str(freq))


def say_runway(rwy: str) -> str:
    """'15L' -> 'one five left'."""
    m = re.fullmatch(r"(\d+)([LRC]?)", rwy.upper())
    if not m:
        return say_digits(rwy)
    side = {"L": " left", "R": " right", "C": " center"}.get(m.group(2), "")
    return say_digits(m.group(1)) + side


def say_altitude(alt: int) -> str:
    """2500 -> 'two thousand five hundred'; 3500 -> 'three thousand five hundred'."""
    thousands, rem = divmod(alt, 1000)
    parts = []
    if thousands:
        parts.append(f"{say_digits(str(thousands))} thousand")
    if rem:
        parts.append(f"{say_digits(str(rem // 100))} hundred")
    return " ".join(parts) or "zero"


def say_letter(letter: str) -> str:
    return NATO.get(letter.lower(), letter)


def say_callsign(callsign: str, short: bool = False) -> str:
    """'N67525' -> 'cessna six seven five two five' (or 'cessna five two five')."""
    tail = callsign.upper().lstrip("N")
    if short and len(tail) > 3:
        tail = tail[-3:]
    return "cessna " + say_digits(tail)


def say_wind(direction: int, speed: int) -> str:
    return f"wind {say_digits(f'{direction:03d}')} at {say_digits(str(speed))}"
