from __future__ import annotations

import bisect
import re
from urllib.parse import quote
from dataclasses import dataclass, field, replace
from fractions import Fraction

from reflets import n1x
from reflets.score import FIFTHS, SEMITONES, SYSTEM_LINES, SYSTEM_MARKS, Mark, ScoreInfo, build_index, unescape

VALUES = sorted({Fraction(1, 2**k) * dots for k in range(8) for dots in (1, Fraction(3, 2), Fraction(7, 4))}, reverse=True)
GRACE_TYPES = {"acciaccatura": 1, "grace16": 8}


class IdeaError(Exception):
    pass


@dataclass(frozen=True, order=True)
class Line:
    tick: int
    track: int
    end: int
    track2: int
    grace: bool
    name: str
    text: str
    kind: str = field(default="", compare=False)


@dataclass(frozen=True)
class LineToken:
    cell: tuple[int, int]
    tick: int
    name: str
    label: str
    text: str
    opens: bool
    removal: bool
    grace: bool
    where: str


@dataclass
class Plan:
    start_tick: int
    end_tick: int
    ops: list[str]
    cells: set[tuple[int, int]]
    idea: n1x.Idea
    timed: set[tuple[int, int]] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)
    lines: list[Line] = field(default_factory=list)
    expected: dict[tuple[int, tuple[int, int]], n1x.Voice] = field(default_factory=dict)
    line_tokens: list[LineToken] = field(default_factory=list)
    chunks: dict[tuple[int, int], list[tuple[int, int]]] = field(default_factory=dict)
    grace_ticks: set[tuple[int, int]] = field(default_factory=set)
    expected_lines: list[Line] = field(default_factory=list)
    cleared: int = 0


def midi_tpc(name: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-G])(#{0,2}|b{0,2})(-?\d+)", name)
    if not match:
        raise IdeaError(f"{name!r} is not a pitch like C4, F#3 or Bb5")
    letter, accidentals, octave = match.groups()
    alter = len(accidentals) if accidentals.startswith("#") else -len(accidentals)
    return 12 * (int(octave) + 1) + SEMITONES[letter] + alter, FIFTHS.index(letter) - 1 + 7 * (alter + 2)


def pieces(quarters: Fraction, where: str) -> list[Fraction]:
    whole = quarters / 4
    if whole.denominator & (whole.denominator - 1):
        raise IdeaError(f"{where}: a duration of {quarters} quarter notes needs a tuplet; write it in braces, as in 3:2{{ 16 C5 D5 E5 }}")
    result = []
    while whole:
        value = next(value for value in VALUES if value <= whole)
        result.append(value)
        whole -= value
    return result


GRACE_ACTIONS = {
    "acciacc": "acciaccatura", "appog": "appoggiatura", "grace4": "grace4", "grace16": "grace16", "grace32": "grace32",
    "after": "grace8after", "after16": "grace16after", "after32": "grace32after",
}
SYMBOLS: dict[str, str] = {}
for symbol, short in n1x.SHORT_DECORATIONS.items():
    SYMBOLS.setdefault(short, symbol)
NOTE_ONLY = ("lv", "paren", "head")


def unwritable(voice: n1x.Voice, where: str) -> None:
    if voice.lyrics:
        raise IdeaError(f"{where}: lyrics cannot be written yet; leave the lyric lines out")
    for chord in voice.chords:
        if chord.grace and any(note.tied for note in chord.notes):
            raise IdeaError(f"{where}: a tie on a grace note cannot be written")
        if chord.grace and (any(name not in GRACE_ACTIONS for name in chord.decorations) or len(chord.decorations) > 1
                            or any(note.decorations or len(note.fingering) > 1 for note in chord.notes)):
            raise IdeaError(f"{where}: a grace note takes only its type ({', '.join(GRACE_ACTIONS)}), as in gD5[appog]")


def uncreatable(name: str) -> bool:
    return name.startswith("gliss") or name in ("trem2", "fall", "doit", "plop", "scoop")


def standalone(name: str) -> str | None:
    symbol = SYMBOLS.get(name, name)
    return "fermata" if symbol.startswith("fermata") else "breath" if symbol.startswith(("breath", "caesura")) else None


def classify(name: str, where: str) -> tuple[str, str]:
    if name in n1x.ARPEGGIOS:
        return "arp", str(n1x.ARPEGGIOS.index(name))
    if name in n1x.TREMOLOS:
        return "trem", str(n1x.TREMOLOS.index(name))
    if match := re.fullmatch(r"staff([+-]\d+)", name):
        return "move", match[1]
    if name in ("lv", "paren"):
        return name, ""
    if name.startswith("head="):
        head = name[5:]
        if head not in n1x.HEADS and not head.isdigit():
            raise IdeaError(f"{where}: {name} is not a notehead; use head=x, head=diamond, head=slash, …")
        return "head", str(n1x.HEADS.index(head) if head in n1x.HEADS else int(head))
    if uncreatable(name):
        raise IdeaError(f"{where}: [{name}] cannot be written: MuseScore's plugin API has no way to create glissandos, two-note tremolos or chord lines")
    if name in GRACE_ACTIONS:
        raise IdeaError(f"{where}: [{name}] is a grace note type; it goes on a grace note, as in gD5[{name}]")
    symbol = SYMBOLS.get(name, name)
    if symbol.startswith("fermata"):
        return "fermata", symbol
    if symbol.startswith(("breath", "caesura")):
        return "breath", symbol
    return "art", symbol


def decoration_ops(track: int, first: int, last: int, end: int, chord: n1x.Chord | None, rest_names: tuple[str, ...], where: str) -> list[str]:
    ops = []
    for name in chord.decorations if chord else rest_names:
        what, value = classify(name, where)
        if what in NOTE_ONLY:
            if chord is None or len(chord.notes) > 1:
                raise IdeaError(f"{where}: [{name}] belongs to one note; in a chord write it on the note, as in C4:{name}+E4")
            ops.append(f"e {track} {last if what == 'lv' else first} {midi_tpc(chord.notes[0].pitch)[0]} {what} {value}")
        elif chord is None and what not in ("fermata", "breath"):
            raise IdeaError(f"{where}: a rest takes only a fermata or a breath, not [{name}]")
        else:
            ops.append(f"e {track} {end if what == 'breath' else first} - {what} {value}")
    for note in chord.notes if chord else ():
        pitch = midi_tpc(note.pitch)[0]
        for name in note.decorations:
            what, value = classify(name, where)
            if what not in NOTE_ONLY:
                raise IdeaError(f"{where}: {name} belongs to the whole chord; write it in brackets after the chord, as in C4+E4[{name}]")
            ops.append(f"e {track} {last if what == 'lv' else first} {pitch} {what} {value}")
        ops += [f"e {track} {first} {pitch} finger {text}" for text in note.fingering]
    return ops


LINE_KINDS = {"": ("SLUR", 0), "ped": ("PEDAL", 0), "lr": ("LET_RING", 0), "pm": ("PALM_MUTE", 0), "line": ("TEXTLINE", 0),
              "tempo": ("GRADUAL_TEMPO_CHANGE", 0), "whammy": ("WHAMMY_BAR", 0)}
for kind, family in (("HAIRPIN", "HairPin"), ("OTTAVA", "Ottava"), ("TRILL", "Trill"), ("VIBRATO", "Vibrato")):
    for sub, name in enumerate(n1x.LINES[family]):
        LINE_KINDS[name] = (kind, sub)


def line_ops(lines: list[Line]) -> tuple[list[str], list[str]]:
    octaves, others = [], []
    for line in lines:
        kind, sub = LINE_KINDS[line.name]
        escaped = line.text.replace("\\", "\\\\").replace("\n", "\\n")
        op = f"l {line.track} {line.tick} {line.track2} {line.end} {int(line.grace)} {kind} {sub} {escaped}"
        (octaves if kind == "OTTAVA" else others).append(op)
    return octaves, others


def spans(lines: list[str]) -> list[Line]:
    result = set()
    for line in lines:
        words = line.split(" ")
        if words[0] != "N" or words[5] == "PartialLyricsLine":
            continue
        value = f"{words[5]}:{words[6]}"
        system = words[5] in SYSTEM_LINES or words[5] == "TextLine" and words[6] == "1"
        track, track2 = (0, 0) if system else (int(words[3]), int(words[4]))
        text = n1x.line_text(value, unescape(" ".join(words[7:])))
        result.add(Line(int(words[1]), track, int(words[2].rstrip("g")), track2, words[2].endswith("g"), n1x.line_name(value), text, words[5]))
    return sorted(result)


def start_cell(line: Line, info: ScoreInfo) -> tuple[int, int]:
    return bisect.bisect_right(info.ticks, line.tick) - 1, line.track


def end_cell(line: Line, info: ScoreInfo) -> tuple[int, int]:
    return (bisect.bisect_right if line.grace else bisect.bisect_left)(info.ticks, line.end) - 1, line.track2


def nearest(lines: list[Line], token: LineToken, info: ScoreInfo) -> Line | None:
    found = [line for line in lines if line.name == token.name
             and (start_cell(line, info) if token.opens else end_cell(line, info)) == token.cell]
    return min(found, key=lambda line: abs((line.tick if token.opens else line.end) - token.tick), default=None)


def snapped(line: Line, plan: Plan, info: ScoreInfo, where: str) -> Line:
    tick, end, grace = line.tick, line.end, line.grace
    if start_cell(line, info) in plan.timed:
        chunks = plan.chunks.get(start_cell(line, info), [])
        if not chunks:
            raise IdeaError(f"{where}: the slur starting here has no note left to start on; remove it with -( or keep a note there")
        tick = min(chunks, key=lambda chunk: 0 if chunk[0] <= tick < chunk[1] else abs(chunk[0] - tick))[0]
    if end_cell(line, info) in plan.timed and not (grace and (line.track2, end) in plan.grace_ticks):
        chunks = plan.chunks.get(end_cell(line, info), [])
        if not chunks:
            raise IdeaError(f"{where}: the slur ending here has no note left to end on; remove it with -) or keep a note there")
        end, grace = min(chunks, key=lambda chunk: 0 if chunk[0] < end <= chunk[1] else abs(chunk[1] - end))[1], False
    one = any(start <= tick and end <= stop for start, stop in plan.chunks.get(start_cell(line, info), []))
    if line.track == line.track2 and not grace and one and (line.track, tick) not in plan.grace_ticks:
        raise IdeaError(f"{where}: the slur here would start and end on one note of the new rhythm; remove it with -( or keep a note where it ends")
    return replace(line, tick=tick, end=end, grace=grace)


def add_lines(plan: Plan, pre: list[str], info: ScoreInfo) -> None:
    old = spans(pre)
    left = list(old)
    removed: list[Line] = []
    for token in plan.line_tokens:
        if token.removal:
            line = nearest(left + removed, token, info)
            if line in removed:
                continue
            if line is None:
                raise IdeaError(f"{token.where}: -{token.name}{'(' if token.opens else ')'} removes nothing; this bar and voice have no such line {'start' if token.opens else 'end'}")
            left.remove(line)
            removed.append(line)
    plain = [token for token in plan.line_tokens if not token.removal]
    referred, taken = set(), set()
    candidates = sorted(
        (abs((line.tick if token.opens else line.end) - token.tick), i, j)
        for i, line in enumerate(left) for j, token in enumerate(plain)
        if line.name == token.name and (start_cell(line, info) if token.opens else end_cell(line, info)) == token.cell
    )
    for _, i, j in candidates:
        if (i, plain[j].opens) not in taken and j not in referred:
            taken.add((i, plain[j].opens))
            referred.add(j)
    fresh = [token for j, token in enumerate(plain) if j not in referred]
    events = [(token.cell[1], token.tick, token.name + token.label, token.opens) for token in fresh]
    pairs = n1x.pair_lines(events)
    added: list[Line] = []
    for number, token in enumerate(fresh):
        if not token.opens and number in pairs:
            opener = fresh[pairs[number]]
            added.append(Line(opener.tick, opener.cell[1], token.tick, token.cell[1], token.grace, token.name, opener.text))
    paired = set(pairs) | set(pairs.values())
    movable = list(removed)
    for number, token in enumerate(fresh):
        if number in paired:
            continue
        if token.opens:
            moved = [line for line in movable if line.name == token.name and line.track == token.cell[1] and token.tick < line.end]
            if not moved:
                raise IdeaError(
                    f"{token.where}: {token.name}({token.label} has no closer; close it in the idea, in a later bar if need be: "
                    f"a bar of the idea may have a voice line with only that closer, e.g. '1.1: {token.name}){token.label}@12'"
                )
            line = min(moved, key=lambda line: abs(line.tick - token.tick))
            added.append(replace(line, tick=token.tick))
        else:
            moved = [line for line in movable if line.name == token.name and line.track2 == token.cell[1] and line.tick < token.tick]
            if not moved:
                raise IdeaError(
                    f"{token.where}: {token.name}){token.label} closes no line; the lines this bar and voice have stay as they are, "
                    f"so to move the end of one write its old end with a minus too, e.g. '-{token.name}) {token.name})@12'"
                )
            line = min(moved, key=lambda line: abs(line.end - token.tick))
            added.append(replace(line, end=token.tick, grace=token.grace))
        movable.remove(line)
    redone = []
    numbers = [measure.number for measure in info.measures]
    for line in left:
        if line.name == "" and (start_cell(line, info) in plan.timed or end_cell(line, info) in plan.timed):
            where = f"m{numbers[start_cell(line, info)[0]]} {line.track // 4 + 1}.{line.track % 4 + 1}"
            removed.append(line)
            redone.append(snapped(line, plan, info, where))
    plan.lines = added + redone
    plan.expected_lines = sorted(set(old) - set(removed) | set(added) | set(redone))
    octaves, others = line_ops(plan.lines)
    drops = [f"z {line.tick} {line.track} {line.end} {line.kind}" for line in removed]
    plan.ops[plan.cleared:plan.cleared] = octaves
    plan.ops[0:0] = drops
    plan.ops += others
    plan.counts["lines"] = len(added)
    plan.counts["removed lines"] = len(removed) - len(redone)


TEXT_KINDS = {"x": "EXPRESSION", "s": "STAFF_TEXT", "S": "SYSTEM_TEXT", "R": "REHEARSAL_MARK", "pt": "PLAYTECH_ANNOTATION", "fb": "FIGURED_BASS"}
SYSTEM_KINDS = {"TEMPO_TEXT", "REHEARSAL_MARK", "SYSTEM_TEXT"}
CLEF_NUMBERS = {**{name: number for number, name in enumerate(n1x.CLEF_NAMES)}, **{name: number for number, name in n1x.CLEFS.items()}}


def mark_element(token: str, where: str) -> tuple[str, float, str]:
    if token.startswith("!"):
        name = token[1:]
        if name.startswith('"'):
            return "DYNAMIC", 0, n1x.unquoted(name)
        if name not in n1x.DYNAMICS[1:]:
            raise IdeaError(f"{where}: {token!r} is not a dynamic; use one like !p, !mf, !sfz or !\"text\"")
        return "DYNAMIC", n1x.DYNAMICS.index(name), name
    if token.startswith('"'):
        return "HARMONY", 0, n1x.unquoted(token)
    if match := re.fullmatch(r'q([\d.]+)("(?:[^"\\]|\\.)*")?', token):
        return "TEMPO_TEXT", float(match[1]) / 60, n1x.unquoted(match[2]) if match[2] else f"<sym>metNoteQuarterUp</sym> = {match[1]}"
    if token.startswith("clef="):
        if token[5:] not in CLEF_NUMBERS:
            raise IdeaError(f"{where}: {token!r} is not a clef; use treble, bass, alto, tenor, treble8vb, …")
        return "CLEF", CLEF_NUMBERS[token[5:]], ""
    prefix, _, text = token.partition('"')
    return TEXT_KINDS[prefix], 0, n1x.unquoted('"' + text)


OldMark = tuple[Fraction, str | None, str]


def old_marks(pre: list[str], info: ScoreInfo, division: int) -> dict[tuple[int, int], list[OldMark]]:
    result: dict[tuple[int, int], list[OldMark]] = {}
    for line in pre:
        words = line.split(" ")
        if words[0] not in ("A", "F"):
            continue
        tick, track = int(words[1]), int(words[2])
        position = bisect.bisect_right(info.ticks, tick) - 1
        onset = Fraction(tick - info.ticks[position], division)
        if onset >= info.lengths[position]:
            continue
        if words[0] == "F":
            token = n1x.mark_token(Mark(track, onset, "Clef", words[3], ""))
        elif words[3] in ("Fermata", "Breath"):
            token = f"[{n1x.decoration(words[4])}]"
        else:
            track = 0 if words[3] in SYSTEM_MARKS else track
            token = n1x.mark_token(Mark(track, onset, words[3], words[4], unescape(" ".join(words[5:]))))
            if words[3] in SYSTEM_MARKS and any(mark[:2] == (onset, token) for mark in result.get((position, 0), [])):
                continue
        result.setdefault((position, track), []).append((onset, token, line))
    return result


def old_chords(pre: list[str], info: ScoreInfo, division: int, first: int, last: int) -> dict[tuple[int, int], dict[Fraction, n1x.Chord]]:
    numbers = [measure.number for measure in info.measures]
    result = {}
    for bar in n1x.decode(n1x.encode(info, build_index(info, pre, division), first, last)).bars:
        for (staff, layer), voice in bar.voices.items():
            chords = {chord.onset: chord for chord in merged(voice.chords) if not chord.grace}
            result[(numbers.index(bar.number), (staff - 1) * 4 + layer - 1)] = chords
    return result


def match_marks(old: list[OldMark], entries: list[tuple[Fraction, str, bool]], where: str) -> tuple[list[OldMark], list[tuple[Fraction, str, bool]], list[OldMark]]:
    pool, removed = list(old), []
    for onset, token, removal in entries:
        if not removal:
            continue
        found = [mark for mark in pool if mark[1] == token]
        if not found:
            raise IdeaError(f"{where}: -{token} removes nothing; this bar and voice have no {token}")
        mark = min(found, key=lambda mark: abs(mark[0] - onset))
        pool.remove(mark)
        removed.append(mark)
    plain = [entry for entry in entries if not entry[2]]
    taken, used = set(), set()
    for _, i, j in sorted((abs(mark[0] - entry[0]), i, j) for i, mark in enumerate(pool) for j, entry in enumerate(plain) if mark[1] == entry[1]):
        if i not in taken and j not in used:
            taken.add(i)
            used.add(j)
    return removed, [entry for j, entry in enumerate(plain) if j not in used], pool


def kept_chord(chord: n1x.Chord, old: n1x.Chord | None, where: str) -> n1x.Chord:
    def split(c: n1x.Chord) -> tuple[list[str], dict[str, tuple[list[str], tuple[str, ...]]]]:
        names = [name for name in c.decorations if not standalone(name.removeprefix("-"))]
        level = [name for name in names if name.removeprefix("-").split("=")[0] not in NOTE_ONLY]
        own = [name for name in names if name not in level]
        if own and len(c.notes) > 1:
            raise IdeaError(f"{where}: [{own[0]}] belongs to one note; in a chord write it on the note, as in C4:{own[0]}+E4")
        return level, {note.pitch: (list(note.decorations) + own, note.fingering) for note in c.notes}

    level, notes = split(chord)
    old_level, old_notes = split(old) if old else ([], {})
    gone = {name[1:] for name in level if name.startswith("-")}
    if gone - set(old_level):
        raise IdeaError(f"{where}: [-{min(gone - set(old_level))}] removes nothing; the note at that moment does not have it")
    names = {name for name in level if not name.startswith("-")} | {name for name in old_level if name not in gone}
    for name in sorted(names & set(old_level)):
        if uncreatable(name):
            raise IdeaError(
                f"{where}: the note at {chord.onset} quarter notes into the bar has [{name}], which the plugin API cannot create again; "
                f"leave that voice as it is, or remove it with [-{name}]"
            )
    result = []
    for note in chord.notes:
        mine, fingering = notes[note.pitch]
        drop = {name[1:] for name in mine if name.startswith("-")}
        theirs, their_fingering = old_notes.get(note.pitch, ([], ()))
        if drop - set(theirs):
            raise IdeaError(f"{where}: {note.pitch}:-{min(drop - set(theirs))} removes nothing; that note does not have it")
        kept = {name for name in mine if not name.startswith("-")} | {name for name in theirs if name not in drop}
        result.append(replace(note, decorations=tuple(sorted(kept)), fingering=fingering or their_fingering))
    return replace(chord, notes=tuple(result), decorations=tuple(sorted(names)))


def idea_range(text: str, info: ScoreInfo) -> tuple[int, int]:
    try:
        idea = n1x.decode(text)
    except n1x.DecodeError as error:
        raise IdeaError(str(error)) from None
    numbers = [measure.number for measure in info.measures]
    for bar in idea.bars:
        if bar.number not in numbers:
            raise IdeaError(f"Bar {bar.number} does not exist; the score has bars {numbers[0]} to {numbers[-1]}")
    positions = sorted(numbers.index(bar.number) for bar in idea.bars) or [0]
    return info.ticks[positions[0]], info.ticks[positions[-1] + 1] if positions[-1] + 1 < len(info.ticks) else 2**31 - 1


def split_rest(item: tuple, cuts: list[Fraction]) -> list[tuple]:
    onset, quarters, chord, names = item
    inside = [cut for cut in cuts if onset < cut < onset + quarters] if chord is None else []
    edges = [onset, *inside, onset + quarters]
    return [(start, stop - start, None, names if start == onset else ()) for start, stop in zip(edges, edges[1:])] if inside else [item]


def plan_end(info: ScoreInfo, plan: Plan) -> int:
    last = max(position for position, _ in plan.cells)
    return info.ticks[last + 2] if last + 2 < len(info.ticks) else info.ticks[-1] + 2**20


def current_fields(info: ScoreInfo, position: int) -> dict[str, str]:
    fields = dict(field.split("=", 1) for field in n1x.bar_fields(info.bars[position]))
    key_ticks = sorted(info.keys)
    tick = info.ticks[position]
    fields["ks"] = info.keys[key_ticks[bisect.bisect_right(key_ticks, tick) - 1]] if key_ticks else info.key
    fields["ts"] = info.measures[position].meter
    return fields


def compile_idea(text: str, info: ScoreInfo, division: int, staves: int, pre: list[str]) -> Plan:
    try:
        idea = n1x.decode(text)
    except n1x.DecodeError as error:
        raise IdeaError(str(error)) from None
    for line in idea.lines[1:]:
        for name, value in (("title", info.title), ("composer", info.composer)):
            if line.startswith(name + "=") and line != f"{name}={n1x.quote(value)}":
                raise IdeaError(f"The {name} cannot be changed by an idea; leave the {name}= line out")
    numbers = [measure.number for measure in info.measures]
    idea_range(text, info)
    written_bars = sorted(numbers.index(bar.number) for bar in idea.bars)
    olds = old_marks(pre, info, division)
    old_notes = old_chords(pre, info, division, numbers[written_bars[0]], numbers[written_bars[-1]]) if written_bars else {}
    ops, graces, ties, clears, marks, decorations, removals = [], [], [], [], [], [], []
    plan = Plan(0, 0, ops, set(), idea)
    voices: dict[int, list[tuple[int, Fraction, list[tuple[int, int, bool]], tuple[int, int]]]] = {}
    rests = grace_notes = 0
    for bar in sorted(idea.bars, key=lambda bar: numbers.index(bar.number) if bar.number in numbers else -1):
        if bar.number not in numbers:
            raise IdeaError(f"Bar {bar.number} does not exist; the score has bars {numbers[0]} to {numbers[-1]}")
        position = numbers.index(bar.number)
        length, bar_tick = info.lengths[position], info.ticks[position]
        if not bar.fields.get("len", "").isdigit() or Fraction(int(bar.fields["len"]), idea.div) != length:
            raise IdeaError(f"m{bar.number}: len= must match the score's bar, which is {length * idea.div} long")
        current = current_fields(info, position)
        changed = [f"{name}={value}" for name, value in bar.fields.items() if name != "len" and current.get(name) != value]
        if changed:
            raise IdeaError(f"m{bar.number}: bar fields cannot be changed yet ({' '.join(changed)}); leave them out or as the score has them")
        for (staff, layer), voice in sorted(bar.voices.items()):
            where = f"m{bar.number} {staff}.{layer}"
            if not 1 <= staff <= staves or not 1 <= layer <= 4:
                raise IdeaError(f"m{bar.number}: there is no {staff}.{layer}; the score has staves 1 to {staves}, voices 1 to 4")
            unwritable(voice, where)
            if voice.end > length:
                raise IdeaError(f"{where}: the notes last {voice.end} quarter notes; the bar has {length}")
            track = (staff - 1) * 4 + layer - 1
            cell = (position, track)
            plan.cells.add(cell)
            end_tick = info.ticks[position + 1] if position + 1 < len(info.ticks) else 2**31 - 1
            if voice.timed:
                clears.append(f"x {track} {bar_tick} {end_tick} 1")
            entries: list[tuple[Fraction, str, bool]] = []
            for number, (onset, token) in enumerate(voice.marks):
                if line := n1x.LINE_TOKEN.fullmatch(token.removeprefix("-")):
                    name, text, paren, label = line.groups()
                    if name not in LINE_KINDS:
                        raise IdeaError(f"{where}: {token} cannot be written; write ( ), <( <), >( >), cresc( cresc), dim( dim), ped( ped), 8va( 8va), tr( tr), line\"…\"( line) or tempo\"rit.\"( tempo)")
                    if onset > length or onset == length and paren == "(":
                        raise IdeaError(f"{where}: {token} falls after the end of the bar")
                    if name == "tempo" and track != 0:
                        raise IdeaError(f"{where}: {token} is a system line; write it in 1.1")
                    plan.line_tokens.append(LineToken(
                        cell, bar_tick + round(onset * division), name, label, n1x.unquoted(text) if text else "", paren == "(",
                        token.startswith("-"), name == "" and number in voice.after_graces, where,
                    ))
                    continue
                if onset >= length:
                    raise IdeaError(f"{where}: {token} falls at or after the end of the bar")
                removal, body = token.startswith("-"), token.removeprefix("-")
                if body.startswith("["):
                    for name in n1x.names(body):
                        if not standalone(name.removeprefix("-")):
                            raise IdeaError(f"{where}: only a fermata or a breath stands on its own with @, not [{name}]")
                        entries.append((onset, f"[{n1x.decoration(classify(name.removeprefix('-'), where)[1])}]", removal or name.startswith("-")))
                    continue
                mark_element(body, where)
                entries.append((onset, body, removal))
            for chord in voice.chords:
                for name in () if chord.grace else chord.decorations:
                    if kind := standalone(name.removeprefix("-")):
                        at = chord.onset + (chord.duration if kind == "breath" else 0)
                        entries.append((at, f"[{n1x.decoration(classify(name.removeprefix('-'), where)[1])}]", name.startswith("-")))
            for onset, duration, names in voice.rests:
                for name in names:
                    if not (kind := standalone(name.removeprefix("-"))):
                        raise IdeaError(f"{where}: a rest takes only a fermata or a breath, not [{name}]")
                    at = onset + (duration if kind == "breath" else 0)
                    entries.append((at, f"[{n1x.decoration(classify(name.removeprefix('-'), where)[1])}]", name.startswith("-")))
            gone, added, kept = match_marks(olds.get(cell, []), entries, where)
            removals += [f"y {mark[2]}" for mark in gone]
            for onset, token, _ in added:
                tick = bar_tick + round(onset * division)
                if token.startswith("["):
                    what, value = classify(token[1:-1], where)
                    decorations.append(f"e {track} {tick} - {what} {value}")
                    continue
                kind, value, text = mark_element(token, where)
                if kind in SYSTEM_KINDS and track != 0:
                    raise IdeaError(f"{where}: {token} is a system mark (tempo, rehearsal mark, system text); write it in 1.1")
                if kind == "CLEF" and layer != 1:
                    raise IdeaError(f"{where}: a clef belongs to the staff; write it in {staff}.1")
                escaped = text.replace("\\", "\\\\").replace("\n", "\\n")
                marks.append(f"a {track} {tick} {kind} {value:g} {escaped}")
            expected_marks = [(mark[0], mark[1]) for mark in kept if mark[1]] + [(onset, token) for onset, token, _ in added]
            if not voice.timed:
                plan.expected[(bar.number, (staff, layer))] = n1x.Voice(marks=expected_marks)
                continue
            plan.timed.add(cell)
            mains = {chord.onset: kept_chord(chord, old_notes.get(cell, {}).get(chord.onset), where) for chord in voice.chords if not chord.grace}
            plan.expected[(bar.number, (staff, layer))] = n1x.Voice(
                chords=[chord if chord.grace else mains[chord.onset] for chord in voice.chords],
                tuplets=list(voice.tuplets), marks=expected_marks, timed=True)
            before: dict[Fraction, list[n1x.Chord]] = {}
            for chord in voice.chords:
                if chord.grace:
                    before.setdefault(chord.onset, []).append(chord)
            if any(onset not in mains for onset in before):
                raise IdeaError(f"{where}: a grace note must come before a note, not a rest or the bar end")
            items = sorted([(chord.onset, chord.duration, chord, ()) for chord in mains.values()]
                           + [(onset, duration, None, ()) for onset, duration, _ in voice.rests], key=lambda item: item[0])
            if voice.end < length:
                items.append((voice.end, length - voice.end, None, ()))
            cuts = sorted({onset for onset, _, _ in added})
            items = [piece for item in items for piece in split_rest(item, cuts)]
            tuplets = sorted(voice.tuplets, key=lambda span: (span[0], -span[1]))
            for start, stop, _ in tuplets:
                if stop > length:
                    raise IdeaError(f"{where}: a tuplet cannot cross the bar line")
            opened: set[int] = set()
            ops.append(f"v {track} {bar_tick}")
            duration = None
            for onset, quarters, chord, rest_names in items:
                stop = onset + quarters
                if any(onset < edge < stop for start, end, _ in tuplets for edge in (start, end)):
                    raise IdeaError(f"{where}: the note or rest at {onset * idea.div} crosses the start or end of a tuplet")
                scale = Fraction(1)
                for number, (start, end, ratio) in enumerate(tuplets):
                    if not (start <= onset and stop <= end):
                        continue
                    actual, normal = (int(x) for x in ratio.split(":"))
                    if number not in opened:
                        total = (end - start) * scale / 4
                        ops.append(f"t {actual}:{normal} {total.numerator}/{total.denominator}")
                        opened.add(number)
                        duration = None
                    scale *= Fraction(actual, normal)
                cursor = onset
                chunks = pieces(quarters * scale, where)
                for number, chunk in enumerate(chunks):
                    tick = bar_tick + round(cursor * division)
                    if chunk != duration:
                        ops.append(f"d {chunk.numerator}/{chunk.denominator}")
                        duration = chunk
                    if chord is None:
                        ops.append(f"r {tick}")
                        rests += 1
                    else:
                        pitches = [(*midi_tpc(note.pitch), note.tied) for note in chord.notes]
                        if number == 0:
                            group = before.get(onset, [])
                            default = "acciaccatura" if len(group) == 1 else "grace16"
                            for grace in reversed(group):
                                notes = ",".join("%d:%d" % midi_tpc(note.pitch) + "".join(":F" + quote(f, safe="") for f in note.fingering) for note in grace.notes)
                                kind = GRACE_ACTIONS[grace.decorations[0]] if grace.decorations else default
                                graces.append(f"g {track} {tick} {kind} {notes}")
                                plan.grace_ticks.add((track, tick))
                                grace_notes += len(grace.notes)
                        ops.append(f"n {tick} " + ",".join(f"{pitch}:{tpc}" for pitch, tpc, _ in pitches))
                        last = number == len(chunks) - 1
                        voices.setdefault(track, []).append((tick, chunk / scale, [(p, t, tie if last else True) for p, t, tie in pitches], cell))
                    cursor += chunk * 4 / scale
                first = bar_tick + round(onset * division)
                decorations += decoration_ops(track, first, tick, bar_tick + round(stop * division), chord, rest_names, where)
    if not plan.cells:
        raise IdeaError("The idea has no voice lines; write at least one 'staff.voice:' line under a bar line")
    for track, chords in voices.items():
        for tick, chunk, _, cell in chords:
            plan.chunks.setdefault(cell, []).append((tick, tick + round(chunk * 4 * division)))
    for track, chords in voices.items():
        for number, (tick, chunk, pitches, cell) in enumerate(chords):
            following = chords[number + 1] if number + 1 < len(chords) else None
            for pitch, tpc, tie in pitches:
                if not tie:
                    continue
                end = tick + round(chunk * 4 * division)
                if following and following[0] == end and pitch in {p for p, _, _ in following[2]}:
                    ties.append(f"~ {track} {tick} {pitch}")
                elif (bisect.bisect_right(info.ticks, end) - 1, track) not in plan.timed and end < plan_end(info, plan):
                    ties.append(f"~ {track} {tick} {pitch} {end}")
                else:
                    raise IdeaError(
                        f"The tie on the note at tick {tick} (track {track}) needs the next note of that voice to start "
                        "right after it on the same pitch, in the idea or in the bar after it"
                    )
    plan.ops = clears + removals + ops + graces + marks + decorations + ties
    plan.cleared = len(clears) + len(removals)
    positions = sorted({position for position, _ in plan.cells})
    plan.start_tick = info.ticks[positions[0]]
    plan.end_tick = info.ticks[positions[-1] + 1] if positions[-1] + 1 < len(info.ticks) else 2**31 - 1
    plan.counts = {
        "notes": sum(len(entry[2]) for entries in voices.values() for entry in entries),
        "rests": rests,
        "ties": len(ties),
        "grace notes": grace_notes,
        "marks": len(marks),
        "decorations": len(decorations),
        "removed marks": len(removals),
    }
    return plan


def _order(key: tuple) -> tuple:
    return (key[0], key[1] != "G", key[4])


def cells(lines: list[str], info: ScoreInfo) -> dict[tuple[int, int], list[tuple]]:
    result: dict[tuple[int, int], list[tuple]] = {}
    graces: dict[tuple[int, int], int] = {}
    for line in lines:
        words = line.split(" ")
        if words[0] not in ("C", "R"):
            continue
        tick, track, written = int(words[1]), int(words[2]), Fraction(words[3])
        cell = (bisect.bisect_right(info.ticks, tick) - 1, track)
        flags = [word for word in words[4:] if word[:1] in "TG" and word[1:2].isdigit()]
        grace = next((int(flag[1:]) for flag in flags if flag[0] == "G"), 0)
        if words[0] == "R":
            key = (tick, "R", written, 0, 0, ())
        else:
            members = []
            for note in words[-1].split(","):
                parts = note.split(":")
                members.append((int(parts[0]), int(parts[1]), "b" in parts[3:], "f" in parts[3:]))
            if grace:
                sequence = graces.get((tick, track), 0)
                graces[(tick, track)] = sequence + 1
                key = (tick, "G", None, grace, sequence, tuple(sorted((p, t, False, False) for p, t, _, _ in members)))
            else:
                key = (tick, "C", written, 0, 0, tuple(sorted(members)))
        result.setdefault(cell, []).append(key)
    for keys in result.values():
        keys.sort(key=_order)
    return result


def occupied(plan: Plan, pre: dict[tuple[int, int], list[tuple]]) -> list[tuple[int, int]]:
    return sorted(cell for cell in plan.timed if any(key[1] != "R" for key in pre.get(cell, [])))


def _untied(keys: list[tuple], first: bool) -> list[tuple]:
    if not keys:
        return keys
    keys = list(keys)
    at = 0 if first else -1
    tick, kind, written, grace, sequence, members = keys[at]
    keys[at] = (tick, kind, written, grace, sequence, tuple((p, t, False, False) for p, t, _, _ in members))
    return keys


def merged(chords: list[n1x.Chord]) -> list[n1x.Chord]:
    result: list[n1x.Chord] = []
    for chord in chords:
        last = result[-1] if result else None
        if (
            last and not chord.grace and not last.grace and last.onset + last.duration == chord.onset
            and all(note.tied for note in last.notes)
            and [n.pitch for n in last.notes] == [n.pitch for n in chord.notes]
        ):
            notes = tuple(
                replace(note, tied=new.tied, fingering=note.fingering + new.fingering, decorations=tuple(sorted(set(note.decorations + new.decorations))))
                for note, new in zip(last.notes, chord.notes)
            )
            decorations = tuple(sorted(set(last.decorations + chord.decorations)))
            result[-1] = replace(last, duration=last.duration + chord.duration, notes=notes, decorations=decorations)
        else:
            result.append(chord)
    return result


def written(voice: n1x.Voice, timed: bool) -> tuple:
    marks = []
    for onset, token in voice.marks:
        if token.startswith("["):
            marks += [(onset, f"[{name}]") for name in n1x.names(token)]
        elif not n1x.is_line(token):
            marks.append((onset, token))
    for onset, duration, names in voice.rests:
        marks += [(onset + duration if standalone(name) == "breath" else onset, f"[{name}]") for name in names]
    chords = []
    for chord in merged(voice.chords):
        own = [name for name in chord.decorations if standalone(name)]
        marks += [(chord.onset + chord.duration if standalone(name) == "breath" else chord.onset, f"[{name}]") for name in own]
        names = [name for name in chord.decorations if not standalone(name)]
        single = [name for name in names if len(chord.notes) == 1 and name.split("=")[0] in NOTE_ONLY]
        notes = chord.notes if not single else (replace(chord.notes[0], decorations=tuple(sorted(chord.notes[0].decorations + tuple(single)))),)
        chords.append(replace(chord, notes=notes, decorations=tuple(name for name in names if name not in single)))
    if not timed:
        return (sorted(marks),)
    return (chords, sorted(voice.tuplets), sorted(marks))


def mark_lines(lines: list[str], info: ScoreInfo, skip: set[tuple[int, int]]) -> list[str]:
    kept = []
    for line in lines:
        words = line.split(" ")
        if words[0] not in ("A", "F"):
            continue
        track = 0 if words[0] == "A" and words[3] in SYSTEM_MARKS else int(words[2])
        if (bisect.bisect_right(info.ticks, int(words[1])) - 1, track) not in skip:
            kept.append(line)
    return sorted(kept)


def described(lines: list[Line], info: ScoreInfo, div: int, division: int) -> str:
    def at(tick: int, track: int, starts: bool) -> str:
        position = (bisect.bisect_right if starts else bisect.bisect_left)(info.ticks, tick) - 1 if tick > info.ticks[0] else 0
        return f"m{info.measures[position].number} {track // 4 + 1}.{track % 4 + 1} @{(tick - info.ticks[position]) * div // division}"

    texts = [f"{line.name}{n1x.quote(line.text) if line.text else ''}( {at(line.tick, line.track, True)} to {line.name}) {at(line.end, line.track2, line.grace)}" for line in lines]
    return "[" + "; ".join(texts) + "]"


def line_of(idea: n1x.Idea, number: int, label: str) -> str:
    bar = None
    for line in idea.lines[1:]:
        if re.match(r"m\d+\b", line):
            bar = int(line.split()[0][1:])
        elif bar == number and line.startswith(label + ":"):
            return line
    return f"{label}: (nothing)"


def verify(plan: Plan, pre: list[str], post: list[str], info: ScoreInfo, division: int) -> tuple[str | None, list[int]]:
    before, after = cells(pre, info), cells(post, info)
    numbers = [measure.number for measure in info.measures]
    cut = set()
    for cell in sorted(set(before) | set(after)):
        position, track = cell
        if cell in plan.timed:
            continue
        want, got = before.get(cell, []), after.get(cell, [])
        loose_want, loose_got = want, got
        for first, neighbour in ((False, position + 1), (True, position - 1)):
            if (neighbour, track) in plan.timed:
                loose_want, loose_got = _untied(loose_want, first), _untied(loose_got, first)
        if loose_want != loose_got:
            return f"bar {numbers[position]}, staff {track // 4 + 1} voice {track % 4 + 1}, outside the idea, changed", []
        if want != got:
            cut.add(numbers[position])
    annotations = (mark_lines(pre, info, plan.cells), mark_lines(post, info, plan.cells))
    if annotations[0] != annotations[1]:
        return f"marks outside the idea changed: {annotations[0]} -> {annotations[1]}", []
    got = spans(post)
    if got != plan.expected_lines:
        missing, extra = sorted(set(plan.expected_lines) - set(got)), sorted(set(got) - set(plan.expected_lines))
        return f"the lines differ: expected {described(missing, info, plan.idea.div, division)} but read back {described(extra, info, plan.idea.div, division)}", []
    positions = sorted({position for position, _ in plan.cells})
    text = n1x.encode(info, build_index(info, post, division), numbers[positions[0]], numbers[positions[-1]])
    back = n1x.decode(text)
    got_voices = {(bar.number, cell): voice for bar in back.bars for cell, voice in bar.voices.items()}
    for bar in plan.idea.bars:
        for cell, voice in sorted(bar.voices.items()):
            got = got_voices.get((bar.number, cell), n1x.Voice())
            if written(plan.expected[(bar.number, cell)], voice.timed) != written(got, voice.timed):
                label = f"{cell[0]}.{cell[1]}"
                return f"bar {bar.number} {label} was written as '{line_of(plan.idea, bar.number, label)}' and reads back as '{line_of(back, bar.number, label)}'", []
    return None, sorted(cut)
