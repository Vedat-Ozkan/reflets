"""N1x (docs/spec-core.md 4.2): N1 with the header lines, bar fields, marks, lines, decorations and groups Reflets reads from the score."""

from __future__ import annotations

import html
import re
import dataclasses
from dataclasses import dataclass
from fractions import Fraction
from urllib.parse import unquote

from engine.notes import NotesError
from engine.score import Event, ScoreIndex

from reflets.score import Bar, Mark, ScoreInfo, key_at

VERSION = "N1x"
BAR = r"m\d+[b-z]?"
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
GLISSANDOS = ["gliss", "gliss-wavy"]
LINES = {
    "Slur": [""],
    "HairPin": ["<", ">", "cresc", "dim"],
    "Pedal": ["ped"],
    "Ottava": ["8va", "8vb", "15ma", "15mb", "22ma", "22mb"],
    "Trill": ["tr", "upprall", "downprall", "prallprall"],
    "Vibrato": ["vib", "vib-wide", "vib-sawtooth", "vib-sawtooth-wide"],
    "LetRing": ["lr"],
    "PalmMute": ["pm"],
    "TextLine": ["line", "line"],
    "GradualTempoChange": ["tempo"],
    "WhammyBar": ["whammy"],
    "HammerOnPullOff": ["hopo"],
}
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


def encode(info: ScoreInfo, index: ScoreIndex, start: int, end: int) -> str:
    measures = index.measures
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
    bars: list[tuple[str, list[str]]] = []
    numbers = line_numbers([
        (int(measure.id[1:]) - 1, mark)
        for measure in measures[start : end + 1]
        for mark in sorted(info.bars[int(measure.id[1:]) - 1].marks, key=mark_order)
        if mark.kind in LINE_PHASES
    ])
    labels = info.labels
    for measure in measures[start : end + 1]:
        position = int(measure.id[1:]) - 1
        header = f"m{labels[position]} len={units(measure.length, div)}"
        if measure.meter and measure.meter != meter:
            meter = measure.meter
            header += f" ts={meter}"
        tick = info.ticks[position]
        bar_key = key_at(info, tick)
        if bar_key != key:
            key = bar_key
            header += f" ks={key}"
        body: list[str] = []
        bars.append((" ".join([header, *bar_fields(info.bars[position])]), body))
        voices: dict[tuple[int, int], list[Event]] = {}
        for event in measure.events:
            if event.pitch:
                voices.setdefault((event.staff, event.layer), []).append(event)
        marks: dict[tuple[int, int], list[tuple[Fraction, str]]] = {}
        closers: dict[tuple[int, int], list[tuple[Fraction, str]]] = {}
        attached: dict[tuple[int, int], list[Mark]] = {}
        for mark in sorted(info.bars[position].marks, key=mark_order):
            where = (mark.track // 4 + 1, mark.track % 4 + 1)
            if mark.kind in ("Fermata", "Breath"):
                attached.setdefault(where, []).append(mark)
            elif mark.kind in ("Close", "CloseGrace"):
                closers.setdefault(where, []).append((mark.onset, line_token(mark, numbers.get(mark.span, 0)), mark.kind == "CloseGrace"))
            elif mark.kind == "Open" and mark.onset < measure.length:
                marks.setdefault(where, []).append((mark.onset, line_token(mark, numbers.get(mark.span, 0))))
            elif (token := mark_token(mark)) and mark.onset < measure.length:
                marks.setdefault(where, []).append((mark.onset, token))
        for staff, layer in sorted(voices.keys() | marks.keys() | attached.keys() | closers.keys()):
            where = (staff, layer)
            events = voices.get(where, [])
            tuplets = info.tuplets.get((position, staff, layer), []) if events else []
            body.append(f"{staff}.{layer}: " + voice(events, div, marks.get(where, []), info.details, attached.get(where, []), tuplets, closers.get(where, [])))
            body += lyric_lines(f"{staff}.{layer}", info.lyrics.get((position, staff, layer), {}))
    return "\n".join(lines + references(bars))


MARK_ORDER = ["Clef", "Tempo", "RehearsalMark", "SystemText", "StaffText", "Expression", "PlayTechAnnotation", "FiguredBass", "Dynamic", "Harmony"]


def mark_order(mark: Mark) -> tuple:
    if mark.kind not in MARK_ORDER:
        return mark.onset, len(MARK_ORDER), "", ""
    return mark.onset, MARK_ORDER.index(mark.kind), mark.value, mark.text


def references(bars: list[tuple[str, list[str]]]) -> list[str]:
    whole: dict[tuple[str, ...], str] = {}
    first: dict[str, str] = {}
    lines = []
    for header, body in bars:
        name, _, fields = header.partition(" ")
        key = (fields, *body)
        if key in whole and len(f"{name} = {whole[key]}") < len("\n".join([header, *body])):
            lines.append(f"{name} = {whole[key]}")
            continue
        written = [header]
        for line in body:
            label = line.split(":")[0]
            if " " not in label and line in first and len(f"{label} = {first[line]}") < len(line):
                written.append(f"{label} = {first[line]}")
            else:
                written.append(line)
                first.setdefault(line, name)
        if written[1:] == body:
            whole.setdefault(key, name)
        lines += written
    return lines


def lyric_lines(where: str, lyrics: dict[Fraction, dict[int, tuple[str, bool] | None]]) -> list[str]:
    lines = []
    for verse in sorted({verse for syllables in lyrics.values() for verse in syllables}):
        tokens = [syllable_token(lyrics[onset].get(verse, "*")) for onset in sorted(lyrics)]
        while tokens[-1] == "*":
            tokens.pop()
        lines.append(f"{where} L{verse + 1}: " + " ".join(tokens))
    return lines


def syllable_token(syllable: tuple[str, bool] | str | None) -> str:
    if syllable is None:
        return "_"
    if isinstance(syllable, str):
        return syllable
    text, continues = syllable
    return (quote(text) if not text or re.search(r'[\s"]|^[_*]|-$', text) else text) + ("-" if continues else "")


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


def line_name(value: str) -> str:
    name, sub = value.split(":")
    names = LINES.get(name, [name.lower()])
    return names[int(sub)] if int(sub) < len(names) else f"{names[0]}{sub}"


def line_text(value: str, text: str) -> str:
    return plain(text) if value.split(":")[0] in ("TextLine", "GradualTempoChange") else ""


def line_token(mark: Mark, number: int = 0) -> str:
    suffix = str(number) if number else ""
    if mark.kind in ("Close", "CloseGrace"):
        return line_name(mark.value) + ")" + suffix
    text = line_text(mark.value, mark.text)
    return line_name(mark.value) + (quote(text) if text else "") + "(" + suffix


LINE_PHASES = {"Close": 0, "Open": 1, "CloseGrace": 2}


def pair_lines(events: list[tuple[int, int | Fraction | tuple, str, bool]]) -> dict[int, int]:
    pairs: dict[int, int] = {}
    stacks: dict[tuple[int, str], list[int]] = {}
    strays = []
    for number, (track, _, key, opens) in enumerate(events):
        stack = stacks.setdefault((track, key), [])
        if opens:
            stack.append(number)
        elif stack:
            pairs[number] = stack.pop()
        else:
            strays.append(number)
    left = [number for stack in stacks.values() for number in stack]
    for number in strays:
        track, at, key, _ = events[number]
        found = [o for o in left if events[o][2] == key and events[o][0] != track and events[o][1] <= at]
        if found:
            opener = max(found, key=lambda o: events[o][1])
            pairs[number] = opener
            left.remove(opener)
    return pairs


def line_numbers(marks: list[tuple[int, Mark]]) -> dict[int, int]:
    events = sorted(
        ((position, mark.onset, LINE_PHASES[mark.kind], order, mark) for order, (position, mark) in enumerate(marks)),
        key=lambda event: event[:4],
    )
    numbers: dict[int, int] = {}
    while True:
        stream = [(mark.track, (position, onset), line_name(mark.value) + str(numbers.get(mark.span, "")), mark.kind == "Open")
                  for position, onset, _, _, mark in events]
        wrong = next((events[closer][4].span for closer, opener in sorted(pair_lines(stream).items())
                      if events[closer][4].span != events[opener][4].span), None)
        if wrong is None:
            return numbers
        numbers[wrong] = max(numbers.values(), default=1) + 1


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
        elif field[0] == "g":
            names.append(GLISSANDOS[int(field[1:])] if int(field[1:]) < len(GLISSANDOS) else f"gliss{field[1:]}")
    return names


def bracket(names: list[str]) -> str:
    return f"[{','.join(names)}]" if names else ""


def note_token(event: Event, fields: list[str], decorations: list[str], in_chord: bool) -> str:
    name = event.pitch + "".join("'" + unquote(field[1:]) for field in fields if field[0] == "F")
    if in_chord:
        return name + "".join(f":{decoration}" for decoration in decorations) + ("~" if event.tied else "")
    return name + bracket(decorations) + ("~" if event.tied else "")


def chord_names(group: list[Event], details: dict[str, tuple[list[str], list[str]]], extra: list[str], graces: int) -> list[str]:
    chord = chord_decorations(details[group[0].id][0], graces) + extra
    return note_decorations(details[group[0].id][1]) + chord if len(group) == 1 else chord


def chord_token(group: list[Event], details: dict[str, tuple[list[str], list[str]]], names: list[str]) -> str:
    if len(group) == 1:
        return note_token(group[0], details[group[0].id][1], names, False)
    own = [details[event.id][1] for event in group]
    return "+".join(note_token(event, fields, note_decorations(fields), True) for event, fields in zip(group, own)) + bracket(names)


def plain(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", text)).strip()


def quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def unquoted(text: str) -> str:
    return re.sub(r"\\(.)", lambda match: "\n" if match[1] == "n" else match[1], text[1:-1])


def units(value: Fraction, div: int) -> int:
    count = value * div
    if count.denominator != 1:
        raise NotesError(f"A duration of {value} quarter notes is not a whole number of {div}ths")
    return int(count)


def rhythm_pieces(onsets: dict[tuple[Fraction, bool, str], list[Event]], tuplets: list[tuple[Fraction, Fraction, str]]) -> list[tuple[str, Fraction, Fraction]]:
    boundaries = {time for start, stop, _ in tuplets for time in (start, stop)}

    def rests(start: Fraction, until: Fraction) -> list[tuple[str, Fraction, Fraction]]:
        cuts = sorted(time for time in boundaries if start < time < until)
        return [("r", a, b) for a, b in zip([start, *cuts], [*cuts, until])] if until > start else []

    pieces, end = [], Fraction(0)
    for onset in sorted(onset for onset, grace, _ in onsets if not grace):
        pieces += rests(end, onset)
        end = onset + onsets[(onset, False, "")][0].duration
        pieces.append(("n", onset, end))
    return pieces + rests(end, max([end, *(stop for _, stop, _ in tuplets)]))


def decoration_groups(
    pieces: list[tuple[str, Fraction, Fraction]], names: dict[Fraction, list[str]], graces: dict[Fraction, int], tuplets: list[tuple[Fraction, Fraction, str]],
) -> tuple[list[tuple[Fraction, Fraction, str]], set[Fraction]]:
    boundaries = {time for start, stop, _ in tuplets for time in (start, stop)}
    groups = list(tuplets)
    shared: set[Fraction] = set()
    run: list[tuple[str, Fraction, Fraction]] = []

    def close_run() -> None:
        if len(run) >= 3:
            start, stop, label = run[0][1], run[-1][2], bracket(names[run[0][1]])
            same = next((number for number, group in enumerate(groups) if group[:2] == (start, stop) and "[" not in group[2]), None)
            if same is None:
                groups.append((start, stop, label))
            else:
                groups[same] = (start, stop, groups[same][2] + label)
            shared.update(piece[1] for piece in run)
        run.clear()

    for piece in pieces:
        own = names.get(piece[1]) if piece[0] == "n" and not graces.get(piece[1]) else None
        if not (own and run and own == names[run[-1][1]] and piece[1] not in boundaries):
            close_run()
        if own:
            run.append(piece)
    close_run()
    return groups, shared


def voice(
    events: list[Event],
    div: int,
    marks: list[tuple[Fraction, str]],
    details: dict[str, tuple[list[str], list[str]]],
    attached: list[Mark],
    tuplets: list[tuple[Fraction, Fraction, str]],
    closers: list[tuple[Fraction, str, bool]],
) -> str:
    onsets: dict[tuple[Fraction, bool, str], list[Event]] = {}
    for event in events:
        onsets.setdefault((event.onset, event.grace, event.attack if event.grace else ""), []).append(event)
    graces: dict[Fraction, int] = {}
    for onset, grace, _ in onsets:
        if grace:
            graces[onset] = graces.get(onset, 0) + 1
    pieces = rhythm_pieces(onsets, tuplets)
    extra: dict[tuple[str, Fraction], list[str]] = {}
    marks = list(marks)
    for mark in attached:
        name = decoration(mark.value)
        side = 1 if mark.kind == "Fermata" else 2
        piece = next((piece for piece in pieces if piece[side] == mark.onset), None)
        if piece:
            extra.setdefault(piece[:2], []).append(name)
        else:
            marks.append((mark.onset, f"[{name}]"))
    names = {start: chord_names(onsets[(start, False, "")], details, extra.get(("n", start), []), graces.get(start, 0))
             for kind, start, _ in pieces if kind == "n"}
    groups, shared = decoration_groups(pieces, names, graces, tuplets)
    opening = sorted(groups, key=lambda group: (group[0], -group[1]))
    edges = {time for _, start, stop in pieces for time in (start, stop)}
    starts = {start for kind, start, _ in pieces if kind == "n" and graces.get(start)}
    ending: dict[Fraction, list[str]] = {}
    after_graces: dict[Fraction, list[str]] = {}
    inside = []
    for onset, token, grace in closers:
        if grace and onset in starts:
            after_graces.setdefault(onset, []).append(token)
        elif onset in edges:
            ending.setdefault(onset, []).append(token)
        else:
            inside.append((onset, token))
    pending = sorted(inside + marks, key=lambda mark: mark[0])
    tokens: list[str] = []
    stack: list[Fraction] = []

    def place(until: Fraction, at: bool) -> None:
        while pending and (pending[0][0] < until or not at and pending[0][0] == until):
            onset, token = pending.pop(0)
            tokens.append(f"{token}@{units(onset, div)}" if at else token)

    def edge(time: Fraction) -> None:
        while stack and stack[-1] <= time:
            stack.pop()
            tokens.append("}")
        tokens.extend(ending.pop(time, []))
        place(time, False)
        while opening and opening[0][0] == time:
            start, stop, prefix = opening.pop(0)
            tokens.append(prefix + "{")
            stack.append(stop)

    current = None
    for kind, start, stop in pieces:
        edge(start)
        if kind == "r":
            current = units(stop - start, div)
            tokens += [str(current), "r" + bracket(extra.get(("r", start), []))]
        else:
            for key in [key for key in onsets if key[1] and key[0] == start]:
                tokens.append("g" + chord_token(onsets[key], details, chord_names(onsets[key], details, [], graces[start])))
            tokens.extend(after_graces.get(start, []))
            duration = units(stop - start, div)
            if duration != current:
                tokens.append(str(duration))
                current = duration
            tokens.append(chord_token(onsets[(start, False, "")], details, [] if start in shared else names[start]))
        place(stop, True)
    tokens += ["}"] * len(stack)
    tokens.extend(token for time in sorted(ending) for token in ending[time])
    place(Fraction(10**9), True)
    return " ".join(tokens)


class DecodeError(ValueError):
    pass


@dataclass(frozen=True)
class Note:
    pitch: str
    tied: bool
    fingering: tuple[str, ...]
    decorations: tuple[str, ...]


@dataclass(frozen=True)
class Chord:
    onset: Fraction
    duration: Fraction
    grace: bool
    notes: tuple[Note, ...]
    decorations: tuple[str, ...]


@dataclass
class Voice:
    chords: list[Chord] = dataclasses.field(default_factory=list)
    rests: list[tuple[Fraction, Fraction, tuple[str, ...]]] = dataclasses.field(default_factory=list)
    tuplets: list[tuple[Fraction, Fraction, str]] = dataclasses.field(default_factory=list)
    marks: list[tuple[Fraction, str]] = dataclasses.field(default_factory=list)
    lyrics: dict[int, list[str]] = dataclasses.field(default_factory=dict)
    end: Fraction = Fraction(0)
    timed: bool = False
    after_graces: set[int] = dataclasses.field(default_factory=set)


@dataclass
class IdeaBar:
    label: str
    fields: dict[str, str]
    voices: dict[tuple[int, int], Voice]


@dataclass
class Idea:
    div: int
    lines: list[str]
    bars: list[IdeaBar]


TOKEN = re.compile(r'(?:[^\s"]|"(?:[^"\\]|\\.)*")+')
QUOTED = r'"(?:[^"\\]|\\.)*"'
PITCH = r"[A-G](?:#{1,2}|b{1,2})?-?\d+"
TEMPO = r"q(\d+(?:\.\d+)?)"
NOTE = re.compile(rf"({PITCH})((?:'[^':~]*)*)((?::[^:~]+)*)(~?)")
CHORD = re.compile(r"([^\[]+?)(\[[^\]]*\])?(~?)")
GROUP = re.compile(r"(?:(\d+):(\d+))?(\[[^\]]*\])?\{")
MARK = re.compile(rf'-?(?:!\S+|{QUOTED}|(?:x|s|S|R|fb|pt){QUOTED}|{TEMPO}(?:{QUOTED})?|clef=\S+|\[[^\]]*\]|[a-z0-9<>-]*(?:{QUOTED})?[()]\d*)')
LINE_TOKEN = re.compile(rf'([a-z0-9<>-]*)({QUOTED})?([()])(\d*)')


def expand(text: str) -> str:
    bars: dict[str, list[str]] = {}
    lines: list[str] = []
    current = None
    for line in text.splitlines():
        line = line.strip()
        if match := re.fullmatch(rf"({BAR}) = ({BAR})", line):
            if match[2] not in bars:
                raise DecodeError(f"{line}: bar {match[2][1:]} must be written out earlier in the same text")
            header, *body = bars[match[2]]
            current = bars[match[1]] = [f"{match[1]} {header.partition(' ')[2]}", *body]
            lines += current
            continue
        if match := re.fullmatch(rf"(\d+\.\d+) = ({BAR})", line):
            written = [w for w in bars.get(match[2], []) if w.startswith(match[1] + ": ")]
            if not written:
                raise DecodeError(f"{line}: bar {match[2][1:]} must be written out earlier in the same text, with a {match[1]} line")
            line = written[0]
        if re.match(rf"{BAR}\b", line):
            current = bars[line.split()[0]] = []
        if current is not None:
            current.append(line)
        lines.append(line)
    return "\n".join(lines)


def names(bracketed: str | None) -> tuple[str, ...]:
    return tuple(name for name in (bracketed or "[]")[1:-1].split(",") if name)


def parse_chord(token: str, onset: Fraction, duration: Fraction, grace: bool, shared: tuple[str, ...]) -> Chord:
    match = CHORD.fullmatch(token)
    if not match:
        raise DecodeError(f"{token!r} is not a note, chord or rest")
    body, bracketed, tie = match.groups()
    parts = body.split("+")
    notes = []
    for part in parts:
        note = NOTE.fullmatch(part)
        if not note:
            raise DecodeError(f"{token!r}: {part!r} is not a pitch like C4, F#3 or Bb5")
        pitch, fingering, own, tied = note.groups()
        notes.append(Note(pitch, bool(tied) or (bool(tie) and len(parts) == 1),
                          tuple(f for f in fingering.split("'")[1:]), tuple(sorted(d for d in own.split(":")[1:]))))
    if tie and len(parts) > 1:
        raise DecodeError(f"{token!r}: in a chord, a tie goes on its note, as in C4~+E4")
    return Chord(onset, duration, grace, tuple(notes), tuple(sorted(set(names(bracketed)) | (set() if grace else set(shared)))))


def decode_voice(text: str, div: int, where: str) -> Voice:
    voice = Voice()
    time, current, grace_at = Fraction(0), None, None
    stack: list[tuple[Fraction, str, tuple[str, ...]]] = []
    for token in TOKEN.findall(text):
        shared = tuple(name for _, _, group in stack for name in group)
        try:
            if token == "}":
                if not stack:
                    raise DecodeError("'}' closes no group")
                start, ratio, _ = stack.pop()
                if ratio:
                    voice.tuplets.append((start, time, ratio))
            elif group := GROUP.fullmatch(token):
                actual, normal, bracketed = group.groups()
                stack.append((time, f"{actual}:{normal}" if actual else "", names(bracketed)))
            elif token.isdigit():
                if int(token) == 0:
                    raise DecodeError("a duration is at least 1")
                current = Fraction(int(token), div)
                voice.timed = True
            elif re.fullmatch(r"r(\[[^\]]*\])?", token):
                if current is None:
                    raise DecodeError("a rest needs a duration before it")
                voice.rests.append((time, current, names(token[1:] or None)))
                time += current
                voice.timed, grace_at = True, None
            elif re.match(r"g[A-G]", token):
                voice.chords.append(parse_chord(token[1:], time, Fraction(0), True, ()))
                voice.timed, grace_at = True, time
            elif re.match(r"[A-G]", token):
                if current is None:
                    raise DecodeError("a note needs a duration before it")
                voice.chords.append(parse_chord(token, time, current, False, shared))
                time += current
                voice.timed, grace_at = True, None
            else:
                body, _, offset = token.rpartition("@") if re.search(r"@\d+$", token) else (token, "", "")
                if not MARK.fullmatch(body):
                    raise DecodeError(f"{token!r} is not a duration, note, rest, mark, line or group")
                if not offset and grace_at == time:
                    voice.after_graces.add(len(voice.marks))
                voice.marks.append((Fraction(int(offset), div) if offset else time, body))
        except DecodeError as error:
            raise DecodeError(f"{where}: {error}") from None
    if stack:
        raise DecodeError(f"{where}: a group opened with '{{' is not closed")
    voice.end = time
    return voice


def decode(text: str) -> Idea:
    lines = expand(text.strip()).splitlines()
    if not lines or not re.match(r"N1x? ", lines[0]):
        raise DecodeError("The first line must be the header, e.g. 'N1x div=48 ts=4/4 ks=0'")
    header = dict(word.split("=", 1) for word in lines[0].split()[1:] if "=" in word)
    if not header.get("div", "").isdigit() or int(header["div"]) < 1:
        raise DecodeError("The header needs div=<units per quarter note>")
    div = int(header["div"])
    idea = Idea(div, lines, [])
    bar = None
    for line in lines[1:]:
        if not line or re.match(r"(title|composer)=|P\d+ ", line):
            continue
        if re.match(rf"{BAR}\b", line):
            words = line.split()
            fields = {}
            for word in words[1:]:
                name, equals, value = word.partition("=")
                if not equals:
                    raise DecodeError(f"{words[0]}: {word!r} is not a field like len=192")
                fields[name] = value
            bar = IdeaBar(words[0][1:], fields, {})
            idea.bars.append(bar)
            continue
        match = re.fullmatch(r"(\d+)\.(\d+)( L(\d+))?:(.*)", line)
        if not match or bar is None:
            raise DecodeError(f"{line!r} is not a bar line 'mN len=…' or a voice line 'staff.voice: …' under one")
        cell = (int(match[1]), int(match[2]))
        where = f"m{bar.label} {match[1]}.{match[2]}"
        if match[3]:
            if cell not in bar.voices:
                raise DecodeError(f"{where} L{match[4]}: a lyric line goes under its voice line")
            tokens = TOKEN.findall(match[5])
            while tokens and tokens[-1] == "*":
                tokens.pop()
            bar.voices[cell].lyrics[int(match[4])] = tokens
        elif cell in bar.voices:
            raise DecodeError(f"{where}: the bar has two {match[1]}.{match[2]} lines")
        else:
            bar.voices[cell] = decode_voice(match[5], div, where)
    return idea


def is_line(token: str) -> bool:
    return bool(LINE_TOKEN.fullmatch(token.removeprefix("-")))
