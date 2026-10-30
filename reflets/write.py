from __future__ import annotations

import bisect
import copy
import re
from urllib.parse import quote
from dataclasses import dataclass, field, replace
from fractions import Fraction

from reflets import n1x
from engine.score import beat_length

from reflets.score import (
    FIFTHS, SEMITONES, SYSTEM_MARKS, Bar, Jump, Marker, Mark, ScoreInfo, bar_at, bar_start, build_index, chord_flags, escape,
    is_grace, is_system_line, key_at, retimed, unescape,
)

METER = r"[1-9]\d*/(1|2|4|8|16|32|64)"
VALUES = sorted({Fraction(1, 2**k) * dots for k in range(8) for dots in (1, Fraction(3, 2), Fraction(7, 4))}, reverse=True)


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
    tied_back: set[tuple[int, int, int]] = field(default_factory=set)
    cut_ties: set[int] = field(default_factory=set)
    expected_lines: list[Line] = field(default_factory=list)
    cleared: int = 0
    expected_lyrics: dict[tuple[int, tuple[int, int]], dict[Fraction, dict[int, tuple[str, bool] | None]]] = field(default_factory=dict)
    dropped: list[str] = field(default_factory=list)
    dropped_marks: list[str] = field(default_factory=list)
    moved_marks: list[str] = field(default_factory=list)
    expected_bars: dict[int, Bar] = field(default_factory=dict)
    meters: dict[int, str] = field(default_factory=dict)
    keys: dict[int, str] = field(default_factory=dict)
    rebar: bool = False
    recast: bool = False


@dataclass
class Recast:
    positions: range
    meter: str
    after: int
    delta: int
    info: ScoreInfo
    pre: list[str]
    ops: list[str]


@dataclass(frozen=True)
class Syllable:
    text: str
    continues: bool
    end: int


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
        value = next((value for value in VALUES if value <= whole), None)
        if value is None:
            raise IdeaError(f"{where}: a duration of {quarters} quarter notes is shorter than a 128th note")
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


def standalone_token(name: str) -> str:
    return f"[{n1x.decoration(SYMBOLS.get(name, name))}]"


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
    return standalone(name) or "art", SYMBOLS.get(name, name)


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
        op = f"l {line.track} {line.tick} {line.track2} {line.end} {int(line.grace)} {kind} {sub} {escape(line.text)}"
        (octaves if kind == "OTTAVA" else others).append(op)
    return octaves, others


def spans(lines: list[str]) -> list[Line]:
    result = set()
    for line in lines:
        words = line.split(" ")
        if words[0] != "N" or words[5] == "PartialLyricsLine":
            continue
        value = f"{words[5]}:{words[6]}"
        system = is_system_line(words[5], words[6])
        track, track2 = (0, 0) if system else (int(words[3]), int(words[4]))
        text = n1x.line_text(value, unescape(" ".join(words[7:])))
        result.add(Line(int(words[1]), track, int(words[2].rstrip("g")), track2, words[2].endswith("g"), n1x.line_name(value), text, words[5]))
    return sorted(result)


def start_cell(line: Line, info: ScoreInfo) -> tuple[int, int]:
    return bar_at(info.ticks, line.tick), line.track


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
    numbers = info.numbers
    for line in left:
        if line.name == "" and (start_cell(line, info) in plan.timed or end_cell(line, info) in plan.timed):
            where = f"m{numbers[start_cell(line, info)[0]]} {line.track // 4 + 1}.{line.track % 4 + 1}"
            removed.append(line)
            redone.append(snapped(line, plan, info, where))
    plan.lines = added + redone + ([line for line in left if line not in removed] if plan.recast else [])
    plan.expected_lines = sorted(set(old) - set(removed) | set(added) | set(redone))
    octaves, others = line_ops(plan.lines)
    drops = [] if plan.recast else [f"z {line.tick} {line.track} {line.end} {line.kind}" for line in removed]
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
    if match := re.fullmatch(rf"{n1x.TEMPO}({n1x.QUOTED})?", token):
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
        position = bar_at(info.ticks, tick)
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
    numbers = info.numbers
    result = {}
    for bar in n1x.decode(n1x.encode(info, build_index(info, pre, division), first, last)).bars:
        for (staff, layer), voice in bar.voices.items():
            chords = {chord.onset: chord for chord in merged(voice.chords) if not chord.grace}
            result[(numbers.index(bar.number), (staff - 1) * 4 + layer - 1)] = chords
    return result


def old_looks(pre: list[str]) -> dict[tuple[int, int], tuple[str, list[str]]]:
    result = {}
    for line in pre:
        words = line.split()
        if words[0] == "C" and not is_grace(words):
            looks = [f"stem {word[1:]}" if word[0] == "S" else f"beam {word[1:]}" for word in words[4:-1] if word[0] in "SB"]
            result[(int(words[2]), int(words[1]))] = (words[3], looks)
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


def parsed(text: str) -> n1x.Idea:
    try:
        return n1x.decode(text)
    except n1x.DecodeError as error:
        raise IdeaError(str(error)) from None


def idea_range(idea: n1x.Idea, info: ScoreInfo) -> tuple[int, int]:
    numbers = info.numbers
    for bar in idea.bars:
        if bar.number not in numbers:
            raise IdeaError(f"Bar {bar.number} does not exist; the score has bars {numbers[0]} to {numbers[-1]}")
    positions = sorted(numbers.index(bar.number) for bar in idea.bars) or [0]
    return info.ticks[positions[0]], bar_start(info, positions[-1] + 1)


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
    fields["ks"] = key_at(info, info.ticks[position])
    fields["ts"] = info.measures[position].meter
    return fields


def voice_entries(voice: n1x.Voice, cell: tuple[int, int], length: Fraction, bar_tick: int, division: int, plan: Plan, where: str) -> list[tuple[Fraction, str, bool]]:
    track = cell[1]
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
                entries.append((onset, standalone_token(name.removeprefix("-")), removal or name.startswith("-")))
            continue
        mark_element(body, where)
        entries.append((onset, body, removal))
    for chord in voice.chords:
        for name in () if chord.grace else chord.decorations:
            if kind := standalone(name.removeprefix("-")):
                at = chord.onset + (chord.duration if kind == "breath" else 0)
                entries.append((at, standalone_token(name.removeprefix("-")), name.startswith("-")))
    for onset, duration, names in voice.rests:
        for name in names:
            if not (kind := standalone(name.removeprefix("-"))):
                raise IdeaError(f"{where}: a rest takes only a fermata or a breath, not [{name}]")
            at = onset + (duration if kind == "breath" else 0)
            entries.append((at, standalone_token(name.removeprefix("-")), name.startswith("-")))
    return entries


def settled_marks(old: list[OldMark], entries: list[tuple[Fraction, str, bool]], voice: n1x.Voice, plan: Plan, recast: bool, where: str) -> tuple[list[OldMark], list[tuple[Fraction, str, bool]], list[OldMark]]:
    lost: list[OldMark] = []
    sounding: list[tuple[Fraction, Fraction]] = []
    if voice.timed:
        sounding = [(chord.onset, chord.onset + chord.duration) for chord in voice.chords if not chord.grace]
        sounding += [(onset, onset + duration) for onset, duration, _ in voice.rests]
        lost = [mark for mark in old if mark[1] and standalone(mark[1][1:-1]) == "fermata" and mark[0] not in {start for start, _ in sounding}]
        old = [mark for mark in old if mark not in lost]
        for entry in [entry for entry in entries if entry[2] and any(mark[1] == entry[1] for mark in lost)]:
            if all(mark[1] != entry[1] for mark in old):
                entries.remove(entry)
                lost.remove(min((mark for mark in lost if mark[1] == entry[1]), key=lambda mark: abs(mark[0] - entry[0])))
    gone, added, kept = match_marks(old, entries, where)
    for mark in lost:
        home = next((start for start, end in sounding if start < mark[0] < end), None)
        if home is None or any(other[0] == home and other[1] and standalone(other[1][1:-1]) == "fermata" for other in kept + added):
            plan.dropped_marks.append(f"{where} {mark[1]} at {mark[0] * plan.idea.div}")
        else:
            added.append((home, mark[1], False))
            plan.moved_marks.append(f"{where} {mark[1]} from {mark[0] * plan.idea.div} to {home * plan.idea.div}")
    if recast:
        return [], added + [(onset, token, False) for onset, token, _ in kept if token], []
    return gone, added, kept


def mark_ops(added: list[tuple[Fraction, str, bool]], track: int, staff: int, layer: int, bar_tick: int, division: int, where: str) -> tuple[list[str], list[str]]:
    marks, decorations = [], []
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
        marks.append(f"a {track} {tick} {kind} {value:g} {escape(text)}")
    return marks, decorations


def rhythm_ops(
    voice: n1x.Voice, mains: dict[Fraction, n1x.Chord], length: Fraction, added: list[tuple[Fraction, str, bool]], cell: tuple[int, int],
    bar_tick: int, division: int, looks: dict[tuple[int, int], tuple[str, list[str]]], plan: Plan, where: str,
) -> tuple[list[str], list[str], list[str], list[tuple[int, Fraction, list[tuple[int, int, bool]], tuple[int, int]]]]:
    track = cell[1]
    ops, graces, decorations, chords = [], [], [], []
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
            raise IdeaError(f"{where}: the note or rest at {onset * plan.idea.div} crosses the start or end of a tuplet")
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
                ops.append(f"n {tick} " + ",".join(f"{pitch}:{tpc}" for pitch, tpc, _ in pitches))
                duration_text, look = looks.get((track, tick), ("", []))
                if duration_text == f"{chunk.numerator}/{chunk.denominator}":
                    decorations += [f"e {track} {tick} - {kind}" for kind in look]
                last = number == len(chunks) - 1
                chords.append((tick, chunk / scale, [(p, t, tie if last else True) for p, t, tie in pitches], cell))
            cursor += chunk * 4 / scale
        first = bar_tick + round(onset * division)
        decorations += decoration_ops(track, first, tick, bar_tick + round(stop * division), chord, rest_names, where)
    return ops, graces, decorations, chords


def tie_ops(voices: dict[int, list[tuple[int, Fraction, list[tuple[int, int, bool]], tuple[int, int]]]], pre: list[str], info: ScoreInfo, division: int, plan: Plan) -> list[str]:
    ties = []
    for track, chords in voices.items():
        for number, (tick, chunk, pitches, cell) in enumerate(chords):
            following = chords[number + 1] if number + 1 < len(chords) else None
            for pitch, tpc, tie in pitches:
                if not tie:
                    continue
                end = tick + round(chunk * 4 * division)
                if following and following[0] == end and pitch in {p for p, _, _ in following[2]}:
                    ties.append(f"~ {track} {tick} {pitch}")
                elif (bar_at(info.ticks, end), track) not in plan.timed and end < plan_end(info, plan):
                    ties.append(f"~ {track} {tick} {pitch} {end}")
                else:
                    raise IdeaError(
                        f"The tie on the note at tick {tick} (track {track}) needs the next note of that voice to start "
                        "right after it on the same pitch, in the idea or in the bar after it"
                    )
    numbers = info.numbers
    for line in pre:
        words = line.split(" ")
        if words[0] != "C" or is_grace(words):
            continue
        tick, track = int(words[1]), int(words[2])
        position = bar_at(info.ticks, tick)
        if tick != info.ticks[position] or (position, track) not in plan.timed or (position - 1, track) in plan.timed:
            continue
        starting = {pitch for start, _, pitches, _ in voices.get(track, []) if start == tick for pitch, _, _ in pitches}
        for note in words[-1].split(","):
            parts = note.split(":")
            if "b" not in parts[3:]:
                continue
            if int(parts[0]) in starting:
                ties.append(f"^ {track} {tick} {parts[0]}")
                plan.tied_back.add((track, tick, int(parts[0])))
            else:
                plan.cut_ties.add(numbers[position - 1])
    return ties


def compile_idea(idea: n1x.Idea, info: ScoreInfo, division: int, staves: int, pre: list[str], later: list[str] = (), recast: range = range(0), drawn: list[str] = ()) -> Plan:
    for line in idea.lines[1:]:
        for name, value in (("title", info.title), ("composer", info.composer)):
            if line.startswith(name + "=") and line != f"{name}={n1x.quote(value)}":
                raise IdeaError(f"The {name} cannot be changed by an idea; leave the {name}= line out")
    numbers = info.numbers
    idea_range(idea, info)
    written_bars = sorted(numbers.index(bar.number) for bar in idea.bars)
    olds = old_marks(pre, info, division)
    looks = {} if recast else old_looks(pre) | old_looks(drawn)
    old_notes = old_chords([line for line in pre if line[0] in "CR"] if recast else pre, info, division, numbers[written_bars[0]], numbers[written_bars[-1]]) if written_bars else {}
    ops, graces, clears, marks, decorations, removals, field_ops, meter_ops, empties = [], [], [], [], [], [], [], [], []
    voltas: dict[int, str] = {}
    plan = Plan(0, 0, ops, set(), idea, recast=bool(recast))
    voices: dict[int, list[tuple[int, Fraction, list[tuple[int, int, bool]], tuple[int, int]]]] = {}
    for bar in sorted(idea.bars, key=lambda bar: numbers.index(bar.number)):
        position = numbers.index(bar.number)
        length, bar_tick = info.lengths[position], info.ticks[position]
        meter_op = meter_change(bar, position, info, idea, later)
        if meter_op:
            meter_ops.append(f"b {bar_tick} {meter_op}")
            plan.meters[position] = bar.fields.get("ts") or info.measures[position - 1].meter
            new_length = Fraction(4) * Fraction(plan.meters[position])
            if new_length != length:
                plan.rebar = True
                length = new_length
        key_op = key_change(bar, position, info)
        if key_op:
            meter_ops.append(f"b {bar_tick} {key_op}")
            plan.keys[position] = bar.fields.get("ks") or key_at(info, bar_tick - 1)
        if not bar.fields.get("len", "").isdigit() or Fraction(int(bar.fields["len"]), idea.div) != length:
            raise IdeaError(f"m{bar.number}: len= must match the score's bar, which is {length * idea.div} long")
        expected_bar, changes, volta = bar_changes(bar, position, info)
        plan.expected_bars[position] = expected_bar
        field_ops += [f"b {bar_tick} {change}" for change in changes]
        if volta is not None:
            voltas[position] = volta
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
            end_tick = bar_start(info, position + 1)
            if voice.timed:
                clears.append(f"x {track} {bar_tick} {end_tick} 1")
            if voice.timed and layer > 1 and not voice.chords and not voice.marks and not any(names for _, _, names in voice.rests) and not olds.get(cell):
                empties.append(f"k {track} {bar_tick} {end_tick}")
            entries = voice_entries(voice, cell, length, bar_tick, division, plan, where)
            gone, added, kept = settled_marks(olds.get(cell, []), entries, voice, plan, position in recast, where)
            removals += [f"y {mark[2]}" for mark in gone]
            voice_marks, voice_decorations = mark_ops(added, track, staff, layer, bar_tick, division, where)
            marks += voice_marks
            decorations += voice_decorations
            expected_marks = [(mark[0], mark[1]) for mark in kept if mark[1]] + [(onset, token) for onset, token, _ in added]
            if not voice.timed:
                plan.expected[(bar.number, (staff, layer))] = n1x.Voice(marks=expected_marks)
                continue
            plan.timed.add(cell)
            mains = {chord.onset: kept_chord(chord, old_notes.get(cell, {}).get(chord.onset), where) for chord in voice.chords if not chord.grace}
            plan.expected[(bar.number, (staff, layer))] = n1x.Voice(
                chords=[chord if chord.grace else mains[chord.onset] for chord in voice.chords],
                tuplets=list(voice.tuplets), marks=expected_marks, timed=True)
            voice_ops, voice_graces, voice_decorations, chords = rhythm_ops(voice, mains, length, added, cell, bar_tick, division, looks, plan, where)
            ops += voice_ops
            graces += voice_graces
            decorations += voice_decorations
            voices.setdefault(track, []).extend(chords)
    field_ops += volta_ops(voltas, plan, info, division)
    if not plan.cells and not field_ops and not meter_ops:
        raise IdeaError("The idea changes nothing; write a 'staff.voice:' line or a bar field to change under a bar line")
    for track, chords in voices.items():
        for tick, chunk, _, cell in chords:
            plan.chunks.setdefault(cell, []).append((tick, tick + round(chunk * 4 * division)))
    ties = tie_ops(voices, pre, info, division, plan)
    plan.ops = meter_ops + clears + removals + ops + graces + marks + decorations + ties + field_ops + empties
    plan.cleared = len(meter_ops) + len(clears) + len(removals)
    positions = sorted(plan.expected_bars)
    plan.start_tick = info.ticks[positions[0]]
    plan.end_tick = bar_start(info, positions[-1] + 1)
    plan.counts = {
        "notes": sum(len(entry[2]) for entries in voices.values() for entry in entries),
        "rests": sum(op.startswith("r ") for op in ops),
        "ties": len(ties),
        "grace notes": sum(len(op.split(" ")[4].split(",")) for op in graces),
        "marks": len(marks),
        "decorations": len(decorations),
        "removed marks": len(removals),
        "bar changes": len(field_ops) + len(meter_ops),
    }
    add_lyrics(plan, pre, info, division)
    return plan


REPEATS = {"start": (True, False), "end": (False, True), "both": (True, True)}
BARLINE_TYPES = {name: number for number, name in n1x.BARLINES.items()}
JUMP_LABELS = {name: labels for labels, name in n1x.JUMPS.items()}
JUMP_TEXTS = {
    "dc": "D.C.", "dc-al-fine": "D.C. al Fine", "dc-al-coda": "D.C. al Coda", "ds-al-coda": "D.S. al Coda", "ds-al-fine": "D.S. al Fine",
    "ds": "D.S.", "dc-al-dblcoda": "D.C. al Double Coda", "ds-al-dblcoda": "D.S. al Double Coda", "dss": "D.S.S.",
    "dss-al-coda": "D.S.S. al Coda", "dss-al-dblcoda": "D.S.S. al Double Coda", "dss-al-fine": "D.S.S. al Fine",
}
LISTED = {"break": n1x.LAYOUT_BREAKS, "jump": list(JUMP_TEXTS), "mark": n1x.MARKERS[:-1]}


def word(text: str) -> str:
    return text.replace("\\", "\\\\").replace(" ", "\\s") if text else "-"


def bar_changes(bar: n1x.IdeaBar, position: int, info: ScoreInfo) -> tuple[Bar, list[str], str | None]:
    where = f"m{bar.number}"
    current = current_fields(info, position)
    old = info.bars[position]
    new = copy.deepcopy(old)
    changes, volta = [], None
    for name, value in bar.fields.items():
        removal, key = name.startswith("-"), name.removeprefix("-")
        if key == "len":
            continue
        if key == "ts":
            continue
        if key == "ks":
            continue
        if key in LISTED:
            values = value.split(",")
            have = list(current[key].split(",")) if key in current else []
            for item in values:
                if item not in LISTED[key]:
                    raise IdeaError(f"{where}: {key}={item} is not one of {', '.join(LISTED[key])}")
                if removal and item not in have:
                    raise IdeaError(f"{where}: -{key}={item} removes nothing; the bar has no {key}={item}")
            if removal:
                gone = set(values)
                if key == "break":
                    new.layout_break_types = [t for t in new.layout_break_types if n1x.LAYOUT_BREAKS[t] not in gone]
                    changes += [f"break- {n1x.LAYOUT_BREAKS.index(item)}" for item in values]
                elif key == "jump":
                    new.jumps = [j for j in new.jumps if n1x.JUMPS.get((j.jump_to, j.play_until, j.continue_at)) not in gone]
                    changes += ["jump- " + " ".join(word(label) for label in JUMP_LABELS[item]) for item in values]
                else:
                    new.markers = [m for m in new.markers if n1x.MARKERS[m.marker_type] not in gone]
                    changes += [f"mark- {n1x.MARKERS.index(item)}" for item in values]
                continue
            for item in values:
                if item in have:
                    continue
                have.append(item)
                if key == "break":
                    new.layout_break_types.append(n1x.LAYOUT_BREAKS.index(item))
                    changes.append(f"break+ {n1x.LAYOUT_BREAKS.index(item)}")
                elif key == "jump":
                    labels = JUMP_LABELS[item]
                    new.jumps.append(Jump(*labels, JUMP_TEXTS[item]))
                    changes.append("jump+ " + " ".join(word(label) for label in labels) + " " + JUMP_TEXTS[item])
                else:
                    new.markers.append(Marker(n1x.MARKERS.index(item), "", ""))
                    changes.append(f"mark+ {n1x.MARKERS.index(item)}")
            continue
        if removal and current.get(key) != value:
            raise IdeaError(f"{where}: -{key}={value} removes nothing; the bar has {key + '=' + current[key] if key in current else 'no ' + key + '='}")
        if key == "rep":
            if value not in REPEATS:
                raise IdeaError(f"{where}: rep={value} is not start, end or both")
            new.repeat_start, new.repeat_end = (False, False) if removal else REPEATS[value]
        elif key == "x":
            if not value.isdigit() or int(value) < 2:
                raise IdeaError(f"{where}: x={value} is not a count of times played, 2 or more")
            new.repeat_count = 2 if removal else int(value)
        elif key == "bar":
            if value not in BARLINE_TYPES:
                raise IdeaError(f"{where}: bar={value} is not one of {', '.join(BARLINE_TYPES)}")
            new.user_barline_type = None if removal else BARLINE_TYPES[value]
            changes.append(f"bar {1 if removal else BARLINE_TYPES[value]}")
        elif key == "volta":
            if not re.fullmatch(r"\d+(,\d+)*", value):
                raise IdeaError(f"{where}: volta={value} is not a list of endings like 1 or 1,2")
            if not removal and old.volta_endings and old.volta_endings != [int(n) for n in value.split(",")]:
                raise IdeaError(f"{where}: the bar is under volta={current['volta']}; remove it first with -volta={current['volta']}")
            if removal or not old.volta_endings:
                volta = "-" if removal else value
        else:
            raise IdeaError(f"{where}: {name}= is not a bar field; use rep=, x=, volta=, bar=, break=, jump= or mark=")
    if new.repeat_count != 2 and not new.repeat_end:
        raise IdeaError(f"{where}: x= needs a repeat end, rep=end or rep=both")
    if (new.repeat_start, new.repeat_end, new.repeat_count) != (old.repeat_start, old.repeat_end, old.repeat_count):
        changes.insert(0, f"rep {int(new.repeat_start)} {int(new.repeat_end)} {new.repeat_count}")
    return new, changes, volta


def key_change(bar: n1x.IdeaBar, position: int, info: ScoreInfo) -> str | None:
    where = f"m{bar.number}"
    tick = info.ticks[position]
    current, previous = key_at(info, tick), key_at(info, tick - 1)
    changes_here = position > 0 and tick in info.keys and previous != current
    if "-ks" in bar.fields:
        if bar.fields["-ks"] != current or not changes_here:
            raise IdeaError(f"{where}: -ks={bar.fields['-ks']} removes nothing; the key does not change to it in this bar")
        return "key-"
    target = bar.fields.get("ks")
    if target is None or target == current:
        return None
    match = re.fullmatch(r"0|([1-7])([sf])", target)
    if not match:
        raise IdeaError(f"{where}: ks={target} is not a key like 0, 2s or 3f (sharps or flats)")
    if changes_here and target == previous:
        return "key-"
    return f"key {int(match[1]) * (1 if match[2] == 's' else -1) if match[1] else 0}"


def meter_reach(info: ScoreInfo, position: int) -> int:
    for later in range(position + 1, len(info.measures)):
        if info.measures[later].meter != info.measures[later - 1].meter:
            return later
    return len(info.measures)


def meter_span(idea: n1x.Idea, info: ScoreInfo) -> tuple[int, int] | None:
    numbers = info.numbers
    for bar in idea.bars:
        if ("ts" in bar.fields or "-ts" in bar.fields) and bar.number in numbers:
            position = numbers.index(bar.number)
            reach = meter_reach(info, position)
            return info.ticks[position], bar_start(info, reach)
    return None


def meter_change(bar: n1x.IdeaBar, position: int, info: ScoreInfo, idea: n1x.Idea, later: list[str]) -> str | None:
    where = f"m{bar.number}"
    current = info.measures[position].meter
    previous = info.measures[position - 1].meter if position else None
    if "-ts" in bar.fields:
        if bar.fields["-ts"] != current or previous in (None, current):
            raise IdeaError(f"{where}: -ts={bar.fields['-ts']} removes nothing; the meter does not change to it in this bar")
        target = previous
    elif "ts" in bar.fields:
        target = bar.fields["ts"]
        if not re.fullmatch(METER, target):
            raise IdeaError(f"{where}: ts={target} is not a meter like 3/4 or 12/8")
    else:
        return None
    if target == current:
        return None
    if Fraction(4) * Fraction(target) != info.lengths[position]:
        reach = meter_reach(info, position)
        numbers = info.numbers
        if bar.voices or any(numbers.index(other.number) > position for other in idea.bars):
            raise IdeaError(
                f"{where}: ts={target} changes the bar's length, so MuseScore re-bars the music after it; write it alone, "
                "with no voice lines and no later bars in the idea, and the notes in a later idea, or, when the user asks to "
                "recast these bars in the new meter, write them in it with recast=True"
            )
        if any(line.split(" ")[0] in ("C", "N") for line in later):
            end = info.measures[reach - 1].number
            raise IdeaError(
                f"{where}: ts={target} changes the bar's length, so MuseScore would re-bar bars {bar.number} to {end}, which have notes "
                "or lines; to recast bars in this meter, write them in it with recast=True"
            )
    if target == previous and previous != current:
        return "meter-"
    numerator, denominator = target.split("/")
    return f"meter {numerator} {denominator}"


def volta_ops(voltas: dict[int, str], plan: Plan, info: ScoreInfo, division: int) -> list[str]:
    ops = []
    for position, value in sorted(voltas.items()):
        if value != "-":
            continue
        endings = info.bars[position].volta_endings
        ops.append(f"b {info.ticks[position]} volta-")
        for step in (-1, 1):
            q = position
            while 0 <= q < len(info.bars) and info.bars[q].volta_endings == endings:
                if q in plan.expected_bars:
                    plan.expected_bars[q].volta_endings = []
                q += step
    added = sorted((position, value) for position, value in voltas.items() if value != "-")
    groups: list[list[tuple[int, str]]] = []
    for position, value in added:
        if groups and groups[-1][-1] == (position - 1, value):
            groups[-1].append((position, value))
        else:
            groups.append([(position, value)])
    for group in groups:
        first, last, value = group[0][0], group[-1][0], group[0][1]
        end = info.ticks[last] + round(info.lengths[last] * division)
        text = ", ".join(value.split(",")) + "."
        ops.append(f"l 0 {info.ticks[first]} 0 {end} 0 VOLTA 0 {text}")
        for position, _ in group:
            plan.expected_bars[position].volta_endings = [int(n) for n in value.split(",")]
    return ops


def old_lyrics(pre: list[str]) -> dict[tuple[int, int], dict[int, Syllable]]:
    result: dict[tuple[int, int], dict[int, Syllable]] = {}
    for line in pre:
        words = line.split(" ")
        if words[0] == "Y":
            tick, track, verse, syllabic, held = (int(word) for word in words[1:6])
            result.setdefault((track, verse), {})[tick] = Syllable(unescape(" ".join(words[6:])), syllabic in (1, 3), tick + held)
    return result


def sung_ticks(pre: list[str], info: ScoreInfo) -> dict[tuple[int, int], list[int]]:
    result: dict[tuple[int, int], set[int]] = {}
    for line in pre:
        words = line.split(" ")
        if words[0] == "C" and not is_grace(words):
            tick, track = int(words[1]), int(words[2])
            result.setdefault((bar_at(info.ticks, tick), track), set()).add(tick)
    return {cell: sorted(ticks) for cell, ticks in result.items()}


def syllable(token: str, where: str) -> tuple[str, bool]:
    if token.startswith('"'):
        match = re.fullmatch(rf"({n1x.QUOTED})(-?)", token)
        if not match:
            raise IdeaError(f"{where}: {token} is not a syllable; quote the whole syllable, as in \"you are\"-")
        return n1x.unquoted(match[1]), bool(match[2])
    return (token[:-1], True) if token.endswith("-") else (token, False)


def add_lyrics(plan: Plan, pre: list[str], info: ScoreInfo, division: int) -> None:
    old = old_lyrics(pre)
    lyrics = {key: dict(syllables) for key, syllables in old.items()}
    sung = sung_ticks(pre, info)
    numbers = info.numbers
    outside: dict[tuple[int, int], tuple[int, int]] = {}
    pieces_at = {cell: sorted(start for start, _ in chunks) for cell, chunks in plan.chunks.items()}
    for bar in sorted(plan.idea.bars, key=lambda bar: numbers.index(bar.number)):
        position = numbers.index(bar.number)
        start = info.ticks[position]
        stop = bar_start(info, position + 1)
        for (staff, layer), voice in sorted(bar.voices.items()):
            track = (staff - 1) * 4 + layer - 1
            cell = (position, track)
            timed = cell in plan.timed
            where = f"m{bar.number} {staff}.{layer}"
            if timed:
                chords = [(start + round(chord.onset * division), start + round((chord.onset + chord.duration) * division))
                          for chord in voice.chords if not chord.grace]
            else:
                chords = [(tick, tick) for tick in sung.get(cell, [])]
            for verse in sorted({verse for t, verse in lyrics if t == track} | {number - 1 for number in voice.lyrics}):
                if verse + 1 not in voice.lyrics and not timed:
                    continue
                mine = lyrics.setdefault((track, verse), {})
                gone = {tick: mine.pop(tick) for tick in [tick for tick in mine if start <= tick < stop]}
                if verse + 1 not in voice.lyrics:
                    starts = {begin for begin, _ in chords}
                    for tick, old_syllable in sorted(gone.items()):
                        home = tick if tick in starts else next((begin for begin, end in chords if begin < tick < end), None)
                        if home is None or home in mine:
                            at = (tick - start) * plan.idea.div // division
                            plan.dropped.append(f"{where} L{verse + 1}: {n1x.syllable_token((old_syllable.text, old_syllable.continues))} at {at}")
                        else:
                            mine[home] = old_syllable
                    continue
                tokens = voice.lyrics[verse + 1]
                if len(tokens) > len(chords):
                    raise IdeaError(f"{where} L{verse + 1}: {len(tokens)} syllables for {len(chords)} notes; one per note, rests and grace notes skipped")
                holding: int | None = None
                lead = None
                for number, ((tick, _), token) in enumerate(zip(chords, tokens)):
                    if token == "_":
                        if holding is not None:
                            mine[holding] = replace(mine[holding], end=tick)
                        elif number == 0 or lead is not None and lead == chords[number - 1][0]:
                            lead = tick
                        continue
                    holding = None
                    if token != "*":
                        text, continues = syllable(token, where)
                        mine[tick] = Syllable(text, continues, tick)
                        holding = tick
                if holding is not None and len(tokens) == len(chords) and holding in gone and gone[holding].end >= stop:
                    mine[holding] = replace(mine[holding], end=gone[holding].end)
                previous = max((tick for tick in mine if tick < start), default=None)
                if lead is not None and previous is None:
                    outside[(track, verse)] = (start, lead)
                elif lead is not None:
                    mine[previous] = replace(mine[previous], end=lead)
                elif previous is not None and mine[previous].end >= start:
                    mine[previous] = replace(mine[previous], end=start - 1)
    writes, holds, drops = [], [], []
    for (track, verse), mine in sorted(lyrics.items()):
        before = old.get((track, verse), {})
        for tick, new in sorted(mine.items()):
            cell = (bar_at(info.ticks, tick), track)
            was = before.get(tick)
            if cell in plan.timed or was is None or (was.text, was.continues) != (new.text, new.continues):
                writes.append((tick, f"w {track} {tick} {verse} {int(new.continues)} {new.end} {escape(new.text)}"))
            elif was.end != new.end:
                holds.append(f"h {track} {tick} {verse} {new.end}")
        for tick in sorted(before):
            cell = (bar_at(info.ticks, tick), track)
            if tick not in mine and cell not in plan.timed:
                drops.append(f"u {track} {tick} {verse}")
    holds += [f"h {track} {start - 1} {verse} {end}" for (track, verse), (start, end) in sorted(outside.items())]
    plan.ops += drops + [op for _, op in sorted(writes)] + holds
    plan.counts["syllables"] = len(writes) + len(holds)
    plan.counts["removed syllables"] = len(drops)
    for bar in plan.idea.bars:
        position = numbers.index(bar.number)
        start = info.ticks[position]
        for (staff, layer) in bar.voices:
            track = (staff - 1) * 4 + layer - 1
            cell = (position, track)
            expected: dict[Fraction, dict[int, tuple[str, bool] | None]] = {}
            for tick in pieces_at.get(cell, []) if cell in plan.timed else sung.get(cell, []):
                entry: dict[int, tuple[str, bool] | None] = {}
                for (t, verse), mine in lyrics.items():
                    if t != track:
                        continue
                    if tick in mine:
                        entry[verse] = (mine[tick].text, mine[tick].continues)
                        continue
                    held = [(begin, mine[begin].end) for begin in mine if begin < tick]
                    if (track, verse) in outside:
                        held.append((outside[(track, verse)][0] - 1, outside[(track, verse)][1]))
                    if held and max(held)[1] >= tick:
                        entry[verse] = None
                expected[Fraction(tick - start, division)] = dict(sorted(entry.items()))
            plan.expected_lyrics[(bar.number, (staff, layer))] = expected


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
        cell = (bar_at(info.ticks, tick), track)
        flags = chord_flags(words)
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
        if (bar_at(info.ticks, int(words[1])), track) not in skip:
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
    numbers = info.numbers
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
    tied = {(int(words[2]), int(words[1]), int(note.split(":")[0])) for words in (line.split(" ") for line in post)
            if words[0] == "C" for note in words[-1].split(",") if "b" in note.split(":")[3:]}
    if plan.tied_back - tied:
        track, tick, _ = min(plan.tied_back - tied)
        return f"the tie into bar {numbers[bar_at(info.ticks, tick)]}, staff {track // 4 + 1} voice {track % 4 + 1}, was not made again", []
    annotations = (mark_lines(pre, info, plan.cells), mark_lines(post, info, plan.cells))
    if annotations[0] != annotations[1]:
        return f"marks outside the idea changed: {annotations[0]} -> {annotations[1]}", []
    got = spans(post)
    if got != plan.expected_lines:
        missing, extra = sorted(set(plan.expected_lines) - set(got)), sorted(set(got) - set(plan.expected_lines))
        return f"the lines differ: expected {described(missing, info, plan.idea.div, division)} but read back {described(extra, info, plan.idea.div, division)}", []
    positions = sorted(plan.expected_bars)
    after = copy.deepcopy(info)
    text = n1x.encode(after, build_index(after, post, division), numbers[positions[0]], numbers[positions[-1]])
    back = n1x.decode(text)
    got_voices = {(bar.number, cell): voice for bar in back.bars for cell, voice in bar.voices.items()}
    for bar in plan.idea.bars:
        for cell, voice in sorted(bar.voices.items()):
            got = got_voices.get((bar.number, cell), n1x.Voice())
            label = f"{cell[0]}.{cell[1]}"
            if written(plan.expected[(bar.number, cell)], voice.timed) != written(got, voice.timed):
                return f"bar {bar.number} {label} was written as '{line_of(plan.idea, bar.number, label)}' and reads back as '{line_of(back, bar.number, label)}'", []
            want = plan.expected_lyrics[(bar.number, cell)]
            sung = after.lyrics.get((numbers.index(bar.number), *cell), {})
            if [want[onset] for onset in sorted(want)] != [sung[onset] for onset in sorted(sung)]:
                return f"bar {bar.number} {label} should have the lyrics {n1x.lyric_lines(label, want)} and reads back with {n1x.lyric_lines(label, sung)}", []
    return None, sorted(cut)


def verify_bars(plan: Plan, info: ScoreInfo, after: ScoreInfo) -> str | None:
    if after.ticks != info.ticks and not plan.rebar:
        return f"the score had {len(info.ticks)} bars and has {len(after.ticks)}, or its bars moved"
    for position, meter in sorted(plan.meters.items()):
        if after.measures[position].meter != meter:
            return f"bar {after.measures[position].number} should be in {meter} and reads back in {after.measures[position].meter}"
    for position, key in sorted(plan.keys.items()):
        if key_at(after, after.ticks[position]) != key:
            return f"bar {after.measures[position].number} should be in ks={key} and reads back in ks={key_at(after, after.ticks[position])}"
    if plan.rebar:
        return None
    for position, bar in sorted(plan.expected_bars.items()):
        want, got = n1x.bar_fields(bar), n1x.bar_fields(after.bars[position])
        if want != got:
            return f"bar {after.measures[position].number} should have the fields '{' '.join(want)}' and reads back with '{' '.join(got)}'"
    return None


def recast_view(idea: n1x.Idea, info: ScoreInfo, pre: list[str], division: int) -> Recast:
    numbers = info.numbers
    if any(bar.number not in numbers for bar in idea.bars):
        raise IdeaError(f"Bar {min(bar.number for bar in idea.bars if bar.number not in numbers)} does not exist")
    bars = sorted(idea.bars, key=lambda bar: numbers.index(bar.number))
    changed = [bar for bar in bars if "ts" in bar.fields or "-ts" in bar.fields]
    if not changed or changed[0] is not bars[0] or "ts" not in changed[0].fields:
        raise IdeaError("recast=True needs ts= on the idea's first bar, followed by the bars it recasts")
    ends = [numbers.index(bar.number) for bar in changed[1:] if bar.fields.get("ts") == info.measures[numbers.index(bar.number)].meter]
    if len(changed) > 2 or len(ends) != len(changed) - 1:
        raise IdeaError(
            f"m{changed[-1].number}: in a recast, only one later bar takes ts=, its own meter, to end the recast before it, "
            f"e.g. 'm{changed[-1].number} len=… ts={info.measures[numbers.index(changed[-1].number)].meter}'"
        )
    meter = changed[0].fields["ts"]
    if not re.fullmatch(METER, meter):
        raise IdeaError(f"m{changed[0].number}: ts={meter} is not a meter like 3/4 or 12/8")
    first = numbers.index(changed[0].number)
    length = 4 * Fraction(meter)
    if info.lengths[first] == length:
        raise IdeaError(f"m{changed[0].number}: ts={meter} keeps the bar's length, so it needs no recast; leave recast=True out")
    written = sorted(numbers.index(bar.number) for bar in idea.bars)
    positions = range(first, ends[0] if ends else written[-1] + 1)
    if any(position not in written for position in positions):
        raise IdeaError(f"m{changed[0].number}: a recast idea starts at the bar with ts= and writes every bar it recasts, in order, without gaps")
    ticks = info.ticks
    after = ticks[positions[-1]] + round(info.lengths[positions[-1]] * division)
    delta = round(len(positions) * length * division) - (after - ticks[first])
    needed: dict[int, set[int]] = {}
    for line in pre:
        words = line.split(" ")
        if words[0] in ("C", "R", "A", "F"):
            position = bar_at(ticks, int(words[1]))
            if position in positions:
                needed.setdefault(position, set()).add(0 if words[0] == "A" and words[3] in SYSTEM_MARKS else int(words[2]))
    starts: dict[int, list[Fraction]] = {}
    for bar in idea.bars:
        position = numbers.index(bar.number)
        if position not in positions:
            continue
        timed = {(staff - 1) * 4 + layer - 1 for (staff, layer), voice in bar.voices.items() if voice.timed}
        missing = sorted(needed.get(position, set()) - timed)
        if missing:
            voices = ", ".join(f"{track // 4 + 1}.{track % 4 + 1}" for track in missing)
            raise IdeaError(f"m{bar.number}: a recast rewrites every voice of its bars; write {voices} too, with its notes or rests in the new meter")
        starts[position] = sorted({chord.onset for voice in bar.voices.values() for chord in voice.chords if not chord.grace}
                                  | {onset for voice in bar.voices.values() for onset, _, _ in voice.rests})

    def start_of(position: int) -> int:
        return ticks[first] + round((position - first) * length * division)

    def moved(tick: int, snap: str = "") -> int:
        if tick < ticks[first]:
            return tick
        if tick >= after:
            return tick + delta
        position = bar_at(ticks, tick)
        at = Fraction(tick - ticks[position], division) * length / info.lengths[position]
        if snap and starts[position]:
            at = min(starts[position] + ([length] if snap == "end" else []), key=lambda onset: abs(onset - at))
        return start_of(position) + round(at * division)

    mapped = []
    for line in pre:
        words = line.split(" ")
        tick = int(words[1])
        position = bar_at(ticks, tick)
        if words[0] in ("C", "R"):
            words[1] = str(moved(tick))
            if position in positions:
                words[3] = str(Fraction(words[3]) * length / info.lengths[position])
        elif words[0] in ("A", "F"):
            words[1] = str(moved(tick, "start"))
        elif words[0] == "N":
            words[1] = str(moved(tick, "start"))
            words[2] = retimed(words[2], lambda end: moved(end, "end"))
        elif words[0] == "Y":
            words[1] = str(moved(tick))
            words[5] = str(moved(tick + int(words[5])) - int(words[1]))
        mapped.append(" ".join(words))
    projected = copy.deepcopy(info)
    count, unit = (int(x) for x in meter.split("/"))
    for position in positions:
        projected.measures[position] = replace(projected.measures[position], meter=meter, beat_length=beat_length(count, unit), declared_length=length)
        projected.lengths[position] = length
    projected.ticks = [tick if position <= first else start_of(position) if position in positions else tick + delta for position, tick in enumerate(ticks)]
    projected.keys = {moved(tick): key for tick, key in info.keys.items()}
    removals = [f"y {mark[2]}" for (position, _), marks in old_marks(pre, info, division).items() if position in positions for mark in marks]
    for line in spans(pre):
        if line.name not in LINE_KINDS:
            raise IdeaError(f"The {line.kind} in these bars cannot be written again in the new meter; remove it first")
        removals.append(f"z {line.tick} {line.track} {line.end} {line.kind}")
    after_position = positions[-1] + 1
    anchors = [f"b {ticks[after_position]} meter {info.measures[after_position].meter.replace('/', ' ')}"] if after_position < len(ticks) else []
    empties = []
    for position in positions:
        end = ticks[position] + round(info.lengths[position] * division)
        for track in sorted(needed.get(position, set())):
            empties += [f"x {track} {ticks[position]} {end} 1", f"v {track} {ticks[position]}"]
            for chunk in pieces(info.lengths[position], f"m{numbers[position]}"):
                empties += [f"d {chunk.numerator}/{chunk.denominator}", "r"]
    meters = [f"b {start_of(position)} len {count} {unit}" for position in positions] + [f"b {ticks[first]} meter {count} {unit}"]
    return Recast(positions, meter, after, delta, projected, mapped, removals + anchors + empties + meters)
