from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction

from engine.score import Event, Measure, ScoreIndex, beat_length

FIFTHS = "FCGDAEB"
SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
SYSTEM_MARKS = {"Tempo", "RehearsalMark", "SystemText"}
SYSTEM_LINES = {"GradualTempoChange"}


def spell(pitch: int, tpc: int) -> str:
    letter = FIFTHS[(tpc + 1) % 7]
    alter = (tpc + 1) // 7 - 2
    octave = (pitch - alter - SEMITONES[letter]) // 12 - 1
    return f"{letter}{'#' * alter if alter > 0 else 'b' * -alter}{octave}"


def key_name(key: int) -> str:
    return "0" if key == 0 else f"{abs(key)}{'s' if key > 0 else 'f'}"


@dataclass
class Jump:
    jump_to: str
    play_until: str
    continue_at: str
    text: str


@dataclass
class Marker:
    marker_type: int
    label: str
    text: str


@dataclass
class Mark:
    track: int
    onset: Fraction
    kind: str
    value: str
    text: str
    span: int = field(default=-1, compare=False)


@dataclass
class Bar:
    repeat_start: bool = False
    repeat_end: bool = False
    repeat_count: int = 2
    user_barline_type: int | None = None
    layout_break_types: list[int] = field(default_factory=list)
    jumps: list[Jump] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    volta_endings: list[int] = field(default_factory=list)
    marks: list[Mark] = field(default_factory=list)


@dataclass
class ScoreInfo:
    title: str
    parts: list[tuple[str, list[int]]]
    measures: list[Measure]
    ticks: list[int]
    key: str
    keys: dict[int, str]
    lengths: list[Fraction]
    composer: str = ""
    instrument_ids: list[str] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    details: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)
    tuplets: dict[tuple[int, int, int], list[tuple[Fraction, Fraction, str]]] = field(default_factory=dict)
    lyrics: dict[tuple[int, int, int], dict[Fraction, dict[int, tuple[str, bool] | None]]] = field(default_factory=dict)


def appended(info: ScoreInfo, count: int, division: int, closing: int | None) -> ScoreInfo:
    last = info.measures[-1]
    length = 4 * Fraction(last.meter)
    measures, ticks, lengths, bars = list(info.measures), list(info.ticks), list(info.lengths), list(info.bars)
    end = ticks[-1] + int(lengths[-1] * division)
    for _ in range(count):
        measures.append(replace(last, id=f"m{len(measures) + 1}", number=measures[-1].number + 1, index=len(measures) + 1, declared_length=length))
        ticks.append(end)
        lengths.append(length)
        bars.append(Bar())
        end += int(length * division)
    if closing:
        bars[len(info.bars) - 1] = replace(bars[len(info.bars) - 1], user_barline_type=None)
        bars[-1] = replace(bars[-1], user_barline_type=closing)
    return replace(info, measures=measures, ticks=ticks, lengths=lengths, bars=bars)


def parse_info(lines: list[str]) -> ScoreInfo:
    title, composer, parts, instrument_ids, measures, ticks, keys, lengths, bars = "", "", [], [], [], [], {}, [], []
    voltas: list[tuple[int, int, list[int]]] = []
    staff_part: dict[int, int] = {}
    for line in lines:
        kind, _, rest = line.partition(" ")
        words = rest.split(" ")
        if kind == "T":
            title = unescape(rest)
        elif kind == "X" and words[0] == "composer":
            composer = unescape(" ".join(words[1:]))
        elif kind == "P":
            parts.append((unescape(" ".join(words[4:])), []))
            instrument_ids.append(words[3])
        elif kind == "S":
            staff_part[int(words[0])] = int(words[1])
        elif kind == "M":
            no, irregular, tick, actual, nominal = int(words[0]), words[1] == "1", int(words[2]), words[3], words[4]
            count, unit = (int(x) for x in nominal.split("/"))
            numerator, denominator = (int(x) for x in actual.split("/"))
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
            lengths.append(Fraction(4 * numerator, denominator))
            bars.append(Bar(words[5] == "1", words[6] == "1", int(words[7])))
        elif kind == "K" and words[1] == "0":
            keys[int(words[0])] = key_name(int(words[2]))
        elif kind == "B":
            bars[-1].user_barline_type = int(words[1])
        elif kind == "L":
            bars[-1].layout_break_types.append(int(words[1]))
        elif kind == "J":
            jump = Jump(*(unword(w) for w in words[1:4]), unescape(" ".join(words[4:])))
            if jump not in bars[-1].jumps:
                bars[-1].jumps.append(jump)
        elif kind == "Q":
            marker = Marker(int(words[1]), unword(words[2]), unescape(" ".join(words[3:])))
            if marker not in bars[-1].markers:
                bars[-1].markers.append(marker)
        elif kind == "V":
            text = unescape(" ".join(words[3:]))
            endings = [int(n) for n in (words[2].split(",") if words[2] != "-" else re.findall(r"\d+", text))]
            voltas.append((int(words[0]), int(words[0]) + int(words[1]), endings))
    if bars and bars[-1].user_barline_type == 0x20:
        bars[-1].user_barline_type = None
    for staff, part in sorted(staff_part.items()):
        parts[part][1].append(staff + 1)
    for start, end, endings in voltas:
        for position, tick in enumerate(ticks):
            if start <= tick < end:
                bars[position].volta_endings = endings
    return ScoreInfo(title, parts, measures, ticks, keys.get(0, "0"), keys, lengths, composer, instrument_ids, bars)


def build_index(info: ScoreInfo, lines: list[str], division: int) -> ScoreIndex:
    for measure, bar in zip(info.measures, info.bars):
        measure.events = []
        bar.marks = []
    info.details, info.tuplets, info.lyrics = {}, {}, {}
    melismas: dict[tuple[int, int], int] = {}
    chords: dict[int, dict[int, tuple[str, bool] | None]] = {}
    open_tuplets: dict[tuple[int, int], list[tuple[Fraction, Fraction, str]]] = {}
    cursors: dict[tuple[int, int], Fraction] = {}
    spanners: list[list[str]] = []
    for number, line in enumerate(lines):
        words = line.split(" ")
        if words[0] == "N" and words[5] != "PartialLyricsLine":
            spanners.append(words[1:])
            continue
        if words[0] in ("A", "F"):
            tick, track = int(words[1]), int(words[2])
            position = bisect.bisect_right(info.ticks, tick) - 1
            onset = Fraction(tick - info.ticks[position], division)
            if words[0] == "F":
                info.bars[position].marks.append(Mark(track, onset, "Clef", words[3], ""))
            else:
                system = words[3] in SYSTEM_MARKS
                mark = Mark(0 if system else track, onset, words[3], words[4], unescape(" ".join(words[5:])))
                if not system or mark not in info.bars[position].marks:
                    info.bars[position].marks.append(mark)
            continue
        if words[0] == "Y":
            tick, track, verse, syllabic, held = (int(word) for word in words[1:6])
            if track in chords:
                chords[track][verse] = (unescape(" ".join(words[6:])), syllabic in (1, 3))
            melismas[(track, verse)] = tick + held
            continue
        if words[0] not in ("C", "R"):
            continue
        tick, track, written = int(words[1]), int(words[2]), Fraction(words[3])
        flags = [word for word in words[4:] if word[:1] in "TG" and word[1:2].isdigit()]
        duration = 4 * written
        for flag in flags:
            if flag[0] == "T":
                actual, normal = (int(x) for x in flag[1:].split(":")[:2])
                duration = duration * normal / actual
        grace = any(flag[0] == "G" for flag in flags)
        position = bisect.bisect_right(info.ticks, tick) - 1
        measure = info.measures[position]
        onset = Fraction(tick - info.ticks[position], division)
        cursor = cursors.get((position, track))
        if cursor is not None and abs(onset - cursor) < Fraction(1, division):
            onset = cursor
        staff, layer = track // 4 + 1, track % 4 + 1
        if not grace:
            cursors[(position, track)] = onset + duration
            spans = info.tuplets.setdefault((position, staff, layer), [])
            track_tuplets(open_tuplets.setdefault((position, track), []), spans, onset, flags)
        if words[0] == "C" and not grace:
            chords[track] = {verse: None for (held, verse), end in melismas.items() if held == track and tick <= end}
            info.lyrics.setdefault((position, staff, layer), {})[onset] = chords[track]
        if words[0] == "R":
            measure.events.append(Event(f"e{number}", measure.number, staff, onset, duration, layer=layer, segment=measure.id))
            continue
        for note in words[-1].split(","):
            parts = note.split(":")
            info.details[f"e{number}-{parts[0]}"] = (words[4:-1], [part for part in parts[3:] if part not in ("b", "f")])
            measure.events.append(
                Event(
                    f"e{number}-{parts[0]}",
                    measure.number,
                    staff,
                    onset,
                    Fraction(0) if grace else duration,
                    spell(int(parts[0]), int(parts[1])),
                    grace,
                    layer,
                    "f" in parts[3:],
                    measure.id,
                    attack=f"g{number}" if grace else "",
                )
            )
    line_marks(info, spanners, division)
    for measure in info.measures:
        measure.events.sort(key=lambda event: (event.onset, event.staff))
    meter = info.measures[0].meter if info.measures else ""
    return ScoreIndex.from_measures(info.measures, meter, info.key)


def line_marks(info: ScoreInfo, spanners: list[list[str]], division: int) -> None:
    lines = []
    for words in spanners:
        tick, end, track, track2 = (int(word.rstrip("g")) for word in words[:4])
        system = words[4] in SYSTEM_LINES or words[4] == "TextLine" and words[5] == "1"
        text = unescape(" ".join(words[6:]))
        lines.append((tick, end, words[1].endswith("g"), 0 if system else track, 0 if system else track2, system, f"{words[4]}:{words[5]}", text))
    marks = []
    spans: dict[tuple, int] = {}
    opening = sorted(lines, key=lambda line: (line[0], -line[1], line[6], line[3]))
    for line in opening:
        tick, _, _, track, _, system, value, text = line
        marks.append(("Open", tick, track, bisect.bisect_right, system, value, text, spans.setdefault(line, len(spans))))
    for line in sorted(reversed(opening), key=lambda line: (line[1], -line[0])):
        tick, end, grace, _, track2, system, value, text = line
        side = bisect.bisect_right if grace else bisect.bisect_left
        marks.append(("CloseGrace" if grace else "Close", end, track2, side, system, value, text, spans[line]))
    for kind, at, track, side, system, value, text, span in marks:
        position = side(info.ticks, at) - 1
        mark = Mark(track, Fraction(at - info.ticks[position], division), kind, value, text, span)
        if not system or mark not in info.bars[position].marks:
            info.bars[position].marks.append(mark)


def track_tuplets(stack: list, spans: list, onset: Fraction, flags: list[str]) -> None:
    levels = [flag[1:].split(":") for flag in flags if flag[0] == "T"]
    scale = Fraction(1)
    for depth, (actual, normal, total) in enumerate(levels):
        ratio = f"{actual}:{normal}"
        if depth >= len(stack) or onset >= stack[depth][1] or stack[depth][2] != ratio:
            del stack[depth:]
            stack.append((onset, onset + 4 * Fraction(total) * scale, ratio))
            spans.append(stack[-1])
        scale = scale * int(normal) / int(actual)
    del stack[len(levels):]


def unescape(text: str) -> str:
    return text.replace("\\n", "\n").replace("\\\\", "\\")


def unword(word: str) -> str:
    return "" if word == "-" else unescape(word.replace("\\s", " "))
