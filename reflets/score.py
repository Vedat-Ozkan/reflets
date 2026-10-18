"""Turns the plugin's raw lines (docs/spec-core.md 3.7) into the engine's ScoreIndex."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from fractions import Fraction

from engine.score import Event, Measure, ScoreIndex, beat_length

FIFTHS = "FCGDAEB"  # tonal pitch class 13 is F, 14 C, 15 G, ...; each step of 7 adds a sharp
SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def spell(pitch: int, tpc: int) -> str:
    """MIDI pitch plus MuseScore tonal pitch class to the engine's spelling, e.g. (63, 11) -> "Eb4"."""
    letter = FIFTHS[(tpc + 1) % 7]
    alter = (tpc + 1) // 7 - 2
    # The octave belongs to the letter, so B#3 is MIDI 60 and Cb4 is MIDI 59.
    octave = (pitch - alter - SEMITONES[letter]) // 12 - 1
    return f"{letter}{'#' * alter if alter > 0 else 'b' * -alter}{octave}"


def key_name(key: int) -> str:
    """MuseScore's key (sharps positive, flats negative) in the engine's form: "3f", "2s", "0"."""
    return "0" if key == 0 else f"{abs(key)}{'s' if key > 0 else 'f'}"


@dataclass
class ScoreInfo:
    title: str
    parts: list[tuple[str, list[int]]]  # name, 1-based staves
    measures: list[Measure]
    ticks: list[int]  # first tick of each measure, same order
    key: str
    keys: dict[int, str]  # tick of a bar where staff 1's key changes -> key


def parse_info(lines: list[str]) -> ScoreInfo:
    title, parts, measures, ticks, keys = "", [], [], [], {}
    staff_part: dict[int, int] = {}
    for line in lines:
        kind, _, rest = line.partition(" ")
        words = rest.split(" ")
        if kind == "T":
            title = unescape(rest)
        elif kind == "P":
            parts.append((unescape(" ".join(words[4:])), []))
        elif kind == "S":
            staff_part[int(words[0])] = int(words[1])
        elif kind == "M":
            no, irregular, tick, actual, nominal = int(words[0]), words[1] == "1", int(words[2]), words[3], words[4]
            count, unit = (int(x) for x in nominal.split("/"))
            numerator, denominator = (int(x) for x in actual.split("/"))
            # A pickup shares `no` with the bar after it; the engine numbers it 0 (spec 3.7).
            number = 0 if irregular and not measures else no + 1
            measure = Measure(
                id=f"m{len(measures) + 1}",
                number=number,
                index=len(measures) + 1,
                beat_length=beat_length(count, unit),
                meter=nominal,
                declared_length=None if irregular else Fraction(4 * numerator, denominator),
            )
            measures.append(measure)
            ticks.append(tick)
        elif kind == "K" and words[1] == "0":
            keys[int(words[0])] = key_name(int(words[2]))
    for staff, part in sorted(staff_part.items()):
        parts[part][1].append(staff + 1)
    return ScoreInfo(title, parts, measures, ticks, keys.get(0, "0"), keys)


def build_index(info: ScoreInfo, lines: list[str], division: int) -> ScoreIndex:
    """Fill info's measures with the events of the plugin's C and R lines."""
    for measure in info.measures:
        measure.events = []
    for number, line in enumerate(lines):
        words = line.split(" ")
        if words[0] not in ("C", "R"):
            continue
        tick, track, written = int(words[1]), int(words[2]), Fraction(words[3])
        flags = [word for word in words[4:] if word[:1] in "TG" and word[1:2].isdigit()]
        duration = 4 * written
        for flag in flags:
            if flag[0] == "T":
                actual, normal = (int(x) for x in flag[1:].split(":"))
                duration = duration * normal / actual
        grace = any(flag[0] == "G" for flag in flags)
        position = bisect.bisect_right(info.ticks, tick) - 1
        measure = info.measures[position]
        onset = Fraction(tick - info.ticks[position], division)
        staff, layer = track // 4 + 1, track % 4 + 1
        if words[0] == "R":
            measure.events.append(Event(f"e{number}", measure.number, staff, onset, duration, layer=layer, segment=measure.id))
            continue
        for note in words[4 + len(flags) :][0].split(","):
            parts = note.split(":")
            measure.events.append(
                Event(
                    f"e{number}-{parts[0]}",
                    measure.number,
                    staff,
                    onset,
                    Fraction(0) if grace else duration,
                    spell(int(parts[0]), int(parts[1])),  # tpc1 is the concert spelling
                    grace,
                    layer,
                    "f" in parts[3:],
                    measure.id,
                    attack=f"g{number}" if grace else "",
                )
            )
    for measure in info.measures:
        measure.events.sort(key=lambda event: (event.onset, event.staff))
    meter = info.measures[0].meter if info.measures else ""
    return ScoreIndex.from_measures(info.measures, meter, info.key)


def unescape(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\\\", "\\")
