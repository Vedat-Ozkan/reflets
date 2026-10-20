"""N1x (docs/spec-core.md 4.2): N1 with the header lines, bar fields, marks and decorations Reflets reads from the score."""

from __future__ import annotations

import bisect
import html
import re
from fractions import Fraction
from urllib.parse import unquote

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
SHORT_DECORATIONS = {
    **{f"artic{name}{side}": short for name, short in [("Staccato", "stacc"), ("Staccatissimo", "staccis"), ("Tenuto", "ten"),
       ("Accent", "acc"), ("Marcato", "marc"), ("TenutoStaccato", "port")] for side in ("Above", "Below")},
    "fermataAbove": "fermata",
    "fermataBelow": "fermata",
    "breathMarkComma": "breath",
    "caesura": "caesura",
    "ornamentTrill": "tr",
    "ornamentMordent": "mord",
    "ornamentShortTrill": "prall",
    "ornamentTurn": "turn",
}
ARPEGGIOS = ["arp", "arp-up", "arp-down", "arp-bracket", "arp-up-straight", "arp-down-straight"]
TREMOLOS = ["trem8", "trem16", "trem32", "trem64", "buzz"]
GRACES = {1: "acciacc", 2: "appog", 4: "grace4", 8: "grace16", 16: "grace32", 32: "after", 64: "after16", 128: "after32"}
NOTE_DECORATIONS = {"l": "lv", "p": "paren"}
HEADS = (
    "normal x plus xcircle withx triangle-up triangle-down slashed1 slashed2 diamond diamond-old circled circled-large "
    "large-arrow altbrevis slash large-diamond sol la fa mi do re ti heavy-cross heavy-cross-hat do-walker re-walker "
    "ti-walker do-funk re-funk ti-funk do-name di-name ra-name re-name ri-name me-name mi-name fa-name fi-name se-name "
    "sol-name le-name la-name li-name te-name ti-name si-name a-sharp-name a-name a-flat-name b-sharp-name b-name "
    "b-flat-name c-sharp-name c-name c-flat-name d-sharp-name d-name d-flat-name e-sharp-name e-name e-flat-name "
    "f-sharp-name f-name f-flat-name g-sharp-name g-name g-flat-name h-name h-sharp-name swiss-rudiments-flam "
    "swiss-rudiments-double custom"
).split()
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
        attached: dict[tuple[int, int], list[Mark]] = {}
        for mark in info.bars[position].marks:
            where = (mark.track // 4 + 1, mark.track % 4 + 1)
            if mark.kind in ("Fermata", "Breath"):
                attached.setdefault(where, []).append(mark)
                continue
            token = mark_token(mark)
            if token and mark.onset < measure.length:
                marks.setdefault(where, []).append((mark.onset, token))
        for staff, layer in sorted(voices.keys() | marks.keys() | attached.keys()):
            events, voice_marks = voices.get((staff, layer), []), marks.get((staff, layer), [])
            lines.append(f"{staff}.{layer}: " + voice(events, div, voice_marks, info.details, attached.get((staff, layer), [])))
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


def decoration(name: str) -> str:
    return SHORT_DECORATIONS.get(name, name)


def chord_decorations(fields: list[str], graces: int) -> list[str]:
    names = []
    for word in fields:
        if word[0] == "!":
            names += [decoration(name) for name in word[1:].split(",")]
        elif word[0] == "A":
            names.append(ARPEGGIOS[int(word[1:])] if int(word[1:]) < len(ARPEGGIOS) else f"arp{word[1:]}")
        elif word[0] == "M":
            names.append(TREMOLOS[int(word[1:])] if int(word[1:]) < len(TREMOLOS) else f"trem{word[1:]}")
        elif word[0] == "G" and int(word[1:]) != (1 if graces == 1 else 8):
            names.insert(0, GRACES.get(int(word[1:]), word[1:]))
        elif word[0] == "X":
            names.append(f"staff{int(word[1:]):+d}")
    return names


def note_decorations(fields: list[str]) -> list[str]:
    names = []
    for field in fields:
        if field in NOTE_DECORATIONS:
            names.append(NOTE_DECORATIONS[field])
        elif field[0] == "h":
            names.append("head=" + (HEADS[int(field[1:])] if int(field[1:]) < len(HEADS) else field[1:]))
    return names


def note_token(event: Event, fields: list[str], decorations: list[str], in_chord: bool) -> str:
    name = event.pitch + "".join("'" + unquote(field[1:]) for field in fields if field[0] == "F")
    if in_chord:
        return name + "".join(f":{decoration}" for decoration in decorations) + ("~" if event.tied else "")
    return name + (f"[{','.join(decorations)}]" if decorations else "") + ("~" if event.tied else "")


def chord_token(group: list[Event], details: dict[str, tuple[list[str], list[str]]], extra: list[str], graces: int) -> str:
    chord = chord_decorations(details[group[0].id][0], graces) + extra
    fields = [details[event.id][1] for event in group]
    if len(group) == 1:
        return note_token(group[0], fields[0], note_decorations(fields[0]) + chord, False)
    notes = "+".join(note_token(event, own, note_decorations(own), True) for event, own in zip(group, fields))
    return notes + (f"[{','.join(chord)}]" if chord else "")


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", text)).strip()


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def units(value: Fraction, div: int) -> int:
    count = value * div
    if count.denominator != 1:
        raise NotesError(f"A duration of {value} quarter notes is not a whole number of {div}ths")
    return int(count)


def voice(
    events: list[Event],
    div: int,
    marks: list[tuple[Fraction, str]],
    details: dict[str, tuple[list[str], list[str]]],
    attached: list[Mark],
) -> str:
    tokens: list[str] = []
    cursor, current = Fraction(0), None
    onsets: dict[tuple[Fraction, bool, str], list[Event]] = {}
    for event in events:
        onsets.setdefault((event.onset, event.grace, event.attack if event.grace else ""), []).append(event)
    spans, end = [], Fraction(0)
    for onset, grace, _ in sorted(onsets):
        if not grace:
            if onset > end:
                spans.append(("r", end, onset))
            end = onset + onsets[(onset, grace, "")][0].duration
            spans.append(("n", onset, end))
    extra: dict[tuple[str, Fraction], list[str]] = {}
    marks = list(marks)
    for mark in attached:
        name = decoration(mark.value)
        side = 1 if mark.kind == "Fermata" else 2
        span = next((span for span in spans if span[side] == mark.onset), None)
        if span:
            extra.setdefault(span[:2], []).append(name)
        else:
            marks.append((mark.onset, f"[{name}]"))
    pending = sorted(marks, key=lambda mark: mark[0])

    def place(until: Fraction, at: bool) -> None:
        while pending and (pending[0][0] < until or not at and pending[0][0] == until):
            onset, token = pending.pop(0)
            tokens.append(f"{token}@{units(onset, div)}" if at else token)

    graces = {}
    for onset, grace, _ in onsets:
        if grace:
            graces[onset] = graces.get(onset, 0) + 1
    for onset, grace, attack in sorted(onsets, key=lambda key: (key[0], not key[1])):
        group = onsets[(onset, grace, attack)]
        names = chord_token(group, details, [] if grace else extra.get(("n", onset), []), graces.get(onset, 0))
        if onset > cursor:
            place(cursor, False)
            gap = units(onset - cursor, div)
            rest = extra.get(("r", cursor))
            tokens += [str(gap), f"r[{','.join(rest)}]" if rest else "r"]
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
