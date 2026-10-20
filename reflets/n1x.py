"""N1x (docs/spec-core.md 4.2): N1 with the header lines, bar fields and marks Reflets reads from the score."""

from __future__ import annotations

import bisect
import html
import re
from fractions import Fraction

from engine.notes import NotesError
from engine.score import Event, ScoreIndex

from reflets.score import Bar, Mark, ScoreInfo

VERSION = "N1x"
BARLINES = {2: "double", 0x10: "dashed", 0x20: "final", 0x80: "dotted", 0x100: "reverse-final", 0x200: "heavy", 0x400: "double-heavy"}
REPEAT_BARLINES = {1, 4, 8, 0x40}
LAYOUT_BREAKS = ["page", "line", "section", "nobreak"]
JUMPS = {
    ("start", "end", ""): "dc",
    ("start", "fine", ""): "dc-al-fine",
    ("start", "coda", "codab"): "dc-al-coda",
    ("segno", "coda", "codab"): "ds-al-coda",
    ("segno", "fine", ""): "ds-al-fine",
    ("segno", "end", ""): "ds",
    ("start", "varcoda", "codab"): "dc-al-dblcoda",
    ("segno", "varcoda", "codab"): "ds-al-dblcoda",
    ("varsegno", "end", ""): "dss",
    ("varsegno", "coda", "codab"): "dss-al-coda",
    ("varsegno", "varcoda", "codab"): "dss-al-dblcoda",
    ("varsegno", "fine", ""): "dss-al-fine",
}
DYNAMICS = (
    "other pppppp ppppp pppp ppp pp p mp mf f ff fff ffff fffff ffffff fp pf sf sfz sff sffz sfff sfffz sfp sfpp "
    "rfz rf fz m r s z n"
).split()
CLEFS = {0: "treble", 2: "treble8vb", 3: "treble8va", 10: "alto", 11: "tenor", 20: "bass", 22: "bass8vb", 29: "perc", 31: "tab"}
CLEF_NAMES = (
    "G G15mb G8vb G8va G15ma G8vbo G8vbp G1 C1 C2 C3 C4 C5 C_19C C1_F18C C3_F18C C4_F18C C1_F20C C3_F20C C4_F20C "
    "F F15mb F8vb F8va F15ma F3 F5 F_F18C F_19C PERC PERC2 TAB TAB4 TAB2 TAB4_SERIF C4_8VB G8vbc"
).split()
TEXT_MARKS = {"Expression": "x", "StaffText": "s", "SystemText": "S", "RehearsalMark": "R", "PlayTechAnnotation": "pt"}
MARKERS = ["segno", "varsegno", "coda", "varcoda", "codetta", "fine", "tocoda", "tocodasym", "dacoda", "dadblcoda", "user"]


def encode(info: ScoreInfo, index: ScoreIndex, first: int, last: int) -> str:
    measures = index.measures
    start = measures.index(index.measure(first))
    end = measures.index(index.measure(last))
    if start == 1 and measures[0].number == 0:
        start = 0
    div = index.ppq
    key = index.key_signature or "0"
    lines = [f"{VERSION} div={div} ts={index.meter} ks={key}"]
    if info.title:
        lines.append(f"title={quote(info.title)}")
    if info.composer:
        lines.append(f"composer={quote(info.composer)}")
    for number, ((name, staves), instrument) in enumerate(zip(info.parts, info.instrument_ids), 1):
        span = f"{staves[0]}-{staves[-1]}" if len(staves) > 1 else f"{staves[0]}"
        lines.append(f"P{number} {quote(name)} staves={span} instr={instrument}")
    meter = index.meter
    key_ticks = sorted(info.keys)
    for measure in measures[start : end + 1]:
        position = int(measure.id[1:]) - 1
        header = f"m{measure.number} len={units(measure.length, div)}"
        if measure.meter and measure.meter != meter:
            meter = measure.meter
            header += f" ts={meter}"
        tick = info.ticks[position]
        bar_key = info.keys[key_ticks[bisect.bisect_right(key_ticks, tick) - 1]] if key_ticks else key
        if bar_key != key:
            key = bar_key
            header += f" ks={key}"
        lines.append(" ".join([header, *bar_fields(info.bars[position])]))
        voices: dict[tuple[int, int], list[Event]] = {}
        for event in measure.events:
            if event.pitch:
                voices.setdefault((event.staff, event.layer), []).append(event)
        marks: dict[tuple[int, int], list[tuple[Fraction, str]]] = {}
        for mark in info.bars[position].marks:
            token = mark_token(mark)
            if token and mark.onset < measure.length:
                marks.setdefault((mark.track // 4 + 1, mark.track % 4 + 1), []).append((mark.onset, token))
        for staff, layer in sorted(voices.keys() | marks.keys()):
            lines.append(f"{staff}.{layer}: " + voice(voices.get((staff, layer), []), div, marks.get((staff, layer), [])))
    return "\n".join(lines)


def bar_fields(bar: Bar) -> list[str]:
    fields = []
    if bar.repeat_start or bar.repeat_end:
        fields.append("rep=" + ("both" if bar.repeat_start and bar.repeat_end else "start" if bar.repeat_start else "end"))
    if bar.repeat_end and bar.repeat_count != 2:
        fields.append(f"x={bar.repeat_count}")
    if bar.volta_endings:
        fields.append("volta=" + ",".join(map(str, bar.volta_endings)))
    if bar.user_barline_type is not None and bar.user_barline_type not in REPEAT_BARLINES:
        fields.append("bar=" + BARLINES.get(bar.user_barline_type, str(bar.user_barline_type)))
    if bar.layout_break_types:
        fields.append("break=" + ",".join(LAYOUT_BREAKS[t] for t in bar.layout_break_types))
    if bar.jumps:
        names = [JUMPS.get((j.jump_to, j.play_until, j.continue_at)) or f"{j.jump_to}:{j.play_until}:{j.continue_at}" for j in bar.jumps]
        fields.append("jump=" + ",".join(names))
    if bar.markers:
        fields.append("mark=" + ",".join(MARKERS[m.marker_type] for m in bar.markers))
    return fields


def mark_token(mark: Mark) -> str | None:
    if mark.kind == "Clef":
        number = int(mark.value)
        return "clef=" + CLEFS.get(number, CLEF_NAMES[number] if 0 <= number < len(CLEF_NAMES) else mark.value)
    if mark.kind == "Dynamic":
        number = int(mark.value)
        return "!" + (DYNAMICS[number] if 0 < number < len(DYNAMICS) else quote(plain(mark.text)))
    if mark.kind == "Harmony":
        return quote(plain(mark.text))
    if mark.kind == "Tempo":
        words = plain(re.sub(r"\(?\s*(<sym>met[^<]*</sym>\s*)+=\s*[\d.,]+\s*\)?", "", mark.text))
        return f"q{round(float(mark.value) * 60, 2):g}" + (quote(words) if words else "")
    if mark.kind == "FiguredBass":
        return "fb" + quote(plain(mark.text).replace("\n", "/"))
    if mark.kind in TEXT_MARKS:
        return TEXT_MARKS[mark.kind] + quote(plain(mark.text))
    return None


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", text)).strip()


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def units(value: Fraction, div: int) -> int:
    count = value * div
    if count.denominator != 1:
        raise NotesError(f"A duration of {value} quarter notes is not a whole number of {div}ths")
    return int(count)


def voice(events: list[Event], div: int, marks: list[tuple[Fraction, str]] = ()) -> str:
    tokens: list[str] = []
    cursor, current = Fraction(0), None
    pending = sorted(marks, key=lambda mark: mark[0])

    def place(until: Fraction, at: bool) -> None:
        while pending and (pending[0][0] < until or not at and pending[0][0] == until):
            onset, token = pending.pop(0)
            tokens.append(f"{token}@{units(onset, div)}" if at else token)

    onsets: dict[tuple[Fraction, bool, str], list[Event]] = {}
    for event in events:
        onsets.setdefault((event.onset, event.grace, event.attack if event.grace else ""), []).append(event)
    for onset, grace, attack in sorted(onsets, key=lambda key: (key[0], not key[1])):
        group = onsets[(onset, grace, attack)]
        names = "+".join(event.pitch + ("~" if event.tied else "") for event in group)
        if onset > cursor:
            place(cursor, False)
            gap = units(onset - cursor, div)
            tokens += [str(gap), "r"]
            place(onset, True)
            current, cursor = gap, onset
        place(onset, False)
        if grace:
            tokens.append("g" + names)
            continue
        duration = units(group[0].duration, div)
        if duration != current:
            tokens.append(str(duration))
            current = duration
        tokens.append(names)
        cursor = onset + group[0].duration
        place(cursor, True)
    place(Fraction(10**9), True)
    return " ".join(tokens)
