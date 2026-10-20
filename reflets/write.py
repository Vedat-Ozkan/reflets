from __future__ import annotations

import bisect
import re
from urllib.parse import quote
from dataclasses import dataclass, field, replace
from fractions import Fraction

from reflets import n1x
from reflets.score import FIFTHS, SEMITONES, SYSTEM_MARKS, ScoreInfo, build_index

VALUES = sorted({Fraction(1, 2**k) * dots for k in range(8) for dots in (1, Fraction(3, 2), Fraction(7, 4))}, reverse=True)
GRACE_TYPES = {"acciaccatura": 1, "grace16": 8}


class IdeaError(Exception):
    pass


@dataclass
class Plan:
    start_tick: int
    end_tick: int
    ops: list[str]
    cells: set[tuple[int, int]]
    idea: n1x.Idea
    timed: set[tuple[int, int]] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)


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
    later = [token for _, token in voice.marks if n1x.is_line(token)]
    if later:
        raise IdeaError(f"{where}: lines cannot be written yet ({' '.join(later)}); leave them out")
    if voice.lyrics:
        raise IdeaError(f"{where}: lyrics cannot be written yet; leave the lyric lines out")
    for chord in voice.chords:
        if chord.grace and any(note.tied for note in chord.notes):
            raise IdeaError(f"{where}: a tie on a grace note cannot be written")
        if chord.grace and (any(name not in GRACE_ACTIONS for name in chord.decorations) or len(chord.decorations) > 1
                            or any(note.decorations or len(note.fingering) > 1 for note in chord.notes)):
            raise IdeaError(f"{where}: a grace note takes only its type ({', '.join(GRACE_ACTIONS)}), as in gD5[appog]")


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
    if name.startswith("gliss") or name in ("trem2", "fall", "doit", "plop", "scoop"):
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


def compile_idea(text: str, info: ScoreInfo, division: int, staves: int) -> Plan:
    try:
        idea = n1x.decode(text)
    except n1x.DecodeError as error:
        raise IdeaError(str(error)) from None
    for line in idea.lines[1:]:
        for name, value in (("title", info.title), ("composer", info.composer)):
            if line.startswith(name + "=") and line != f"{name}={n1x.quote(value)}":
                raise IdeaError(f"The {name} cannot be changed by an idea; leave the {name}= line out")
    numbers = [measure.number for measure in info.measures]
    ops, graces, ties, clears, marks, decorations = [], [], [], [], [], []
    plan = Plan(0, 0, ops, set(), idea)
    voices: dict[int, list[tuple[int, Fraction, list[tuple[int, int, bool]], tuple[int, int]]]] = {}
    rests = grace_notes = 0
    for bar in idea.bars:
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
            clears.append(f"x {track} {bar_tick} {end_tick} {int(voice.timed)}")
            for onset, token in voice.marks:
                if onset >= length:
                    raise IdeaError(f"{where}: {token} falls at or after the end of the bar")
                if token.startswith("["):
                    for name in n1x.names(token):
                        what, value = classify(name, where)
                        if what not in ("fermata", "breath"):
                            raise IdeaError(f"{where}: only a fermata or a breath stands on its own with @, not [{name}]")
                        decorations.append(f"e {track} {bar_tick + round(onset * division)} - {what} {value}")
                    continue
                kind, value, text = mark_element(token, where)
                if kind in SYSTEM_KINDS and track != 0:
                    raise IdeaError(f"{where}: {token} is a system mark (tempo, rehearsal mark, system text); write it in 1.1")
                if kind == "CLEF" and layer != 1:
                    raise IdeaError(f"{where}: a clef belongs to the staff; write it in {staff}.1")
                escaped = text.replace("\\", "\\\\").replace("\n", "\\n")
                marks.append(f"a {track} {bar_tick + round(onset * division)} {kind} {value:g} {escaped}")
            if not voice.timed:
                continue
            plan.timed.add(cell)
            mains = {chord.onset: chord for chord in voice.chords if not chord.grace}
            before: dict[Fraction, list[n1x.Chord]] = {}
            for chord in voice.chords:
                if chord.grace:
                    before.setdefault(chord.onset, []).append(chord)
            if any(onset not in mains for onset in before):
                raise IdeaError(f"{where}: a grace note must come before a note, not a rest or the bar end")
            items = sorted([(chord.onset, chord.duration, chord, ()) for chord in mains.values()]
                           + [(onset, duration, None, names) for onset, duration, names in voice.rests], key=lambda item: item[0])
            if voice.end < length:
                items.append((voice.end, length - voice.end, None, ()))
            cuts = sorted({onset for onset, _ in voice.marks})
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
    plan.ops = clears + ops + graces + marks + decorations + ties
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
            marks += [(onset, name) for name in n1x.names(token)]
        elif not n1x.is_line(token):
            marks.append((onset, token))
    for onset, duration, names in voice.rests:
        marks += [(onset + duration if classify(name, "")[0] == "breath" else onset, name) for name in names]
    if not timed:
        return (sorted(marks),)
    return (merged(voice.chords), sorted(voice.tuplets), sorted(marks))


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
    positions = sorted({position for position, _ in plan.cells})
    text = n1x.encode(info, build_index(info, post, division), numbers[positions[0]], numbers[positions[-1]])
    back = n1x.decode(text)
    got_voices = {(bar.number, cell): voice for bar in back.bars for cell, voice in bar.voices.items()}
    for bar in plan.idea.bars:
        for cell, voice in sorted(bar.voices.items()):
            got = got_voices.get((bar.number, cell), n1x.Voice())
            if written(voice, voice.timed) != written(got, voice.timed):
                label = f"{cell[0]}.{cell[1]}"
                return f"bar {bar.number} {label} was written as '{line_of(plan.idea, bar.number, label)}' and reads back as '{line_of(back, bar.number, label)}'", []
    return None, sorted(cut)
