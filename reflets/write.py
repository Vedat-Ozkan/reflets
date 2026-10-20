from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field, replace
from fractions import Fraction

from reflets import n1x
from reflets.score import FIFTHS, SEMITONES, ScoreInfo, build_index

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


def unwritable(voice: n1x.Voice, where: str) -> None:
    if voice.marks:
        raise IdeaError(f"{where}: marks and lines cannot be written yet ({' '.join(token for _, token in voice.marks)}); leave them out")
    if voice.lyrics:
        raise IdeaError(f"{where}: lyrics cannot be written yet; leave the lyric lines out")
    for chord in voice.chords:
        if chord.decorations or any(note.decorations or note.fingering for note in chord.notes):
            raise IdeaError(f"{where}: decorations and fingering cannot be written yet; leave out the brackets and colons")
        if chord.grace and any(note.tied for note in chord.notes):
            raise IdeaError(f"{where}: a tie on a grace note cannot be written")
    if any(names for _, _, names in voice.rests):
        raise IdeaError(f"{where}: decorations on rests cannot be written yet")


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
    ops, graces, ties = [], [], []
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
            mains = {chord.onset: chord for chord in voice.chords if not chord.grace}
            before: dict[Fraction, list[n1x.Chord]] = {}
            for chord in voice.chords:
                if chord.grace:
                    before.setdefault(chord.onset, []).append(chord)
            if any(onset not in mains for onset in before):
                raise IdeaError(f"{where}: a grace note must come before a note, not a rest or the bar end")
            items = sorted([(chord.onset, chord.duration, chord) for chord in mains.values()]
                           + [(onset, duration, None) for onset, duration, _ in voice.rests], key=lambda item: item[0])
            if voice.end < length:
                items.append((voice.end, length - voice.end, None))
            tuplets = sorted(voice.tuplets, key=lambda span: (span[0], -span[1]))
            for start, stop, _ in tuplets:
                if stop > length:
                    raise IdeaError(f"{where}: a tuplet cannot cross the bar line")
            opened: set[int] = set()
            ops.append(f"v {track} {bar_tick}")
            duration = None
            for onset, quarters, chord in items:
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
                            kind = "acciaccatura" if len(group) == 1 else "grace16"
                            for grace in reversed(group):
                                notes = ",".join("%d:%d" % midi_tpc(note.pitch) for note in grace.notes)
                                graces.append(f"g {track} {tick} {kind} {notes}")
                                grace_notes += len(grace.notes)
                        ops.append(f"n {tick} " + ",".join(f"{pitch}:{tpc}" for pitch, tpc, _ in pitches))
                        last = number == len(chunks) - 1
                        voices.setdefault(track, []).append((tick, chunk / scale, [(p, t, tie if last else True) for p, t, tie in pitches], cell))
                    cursor += chunk * 4 / scale
    if not plan.cells:
        raise IdeaError("The idea has no voice lines; write at least one 'staff.voice:' line under a bar line")

    for track, chords in voices.items():
        for number, (tick, chunk, pitches, cell) in enumerate(chords):
            following = chords[number + 1] if number + 1 < len(chords) else None
            for pitch, tpc, tie in pitches:
                if not tie:
                    continue
                if not following or following[0] != tick + round(chunk * 4 * division) or pitch not in {p for p, _, _ in following[2]}:
                    raise IdeaError(
                        f"The tie on the note at tick {tick} (track {track}) needs the next note of that voice, "
                        "in the idea, to start right after it on the same pitch"
                    )
                ties.append(f"~ {track} {tick} {pitch}")
    plan.ops = ops + graces + ties
    positions = sorted({position for position, _ in plan.cells})
    plan.start_tick = info.ticks[positions[0]]
    plan.end_tick = info.ticks[positions[-1] + 1] if positions[-1] + 1 < len(info.ticks) else 2**31 - 1
    plan.counts = {
        "notes": sum(len(entry[2]) for entries in voices.values() for entry in entries),
        "rests": rests,
        "ties": len(ties),
        "grace notes": grace_notes,
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
    return sorted(cell for cell in plan.cells if any(key[1] != "R" for key in pre.get(cell, [])))


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
            last and not chord.grace and not last.grace and not chord.decorations and last.onset + last.duration == chord.onset
            and all(note.tied for note in last.notes)
            and [n.pitch for n in last.notes] == [n.pitch for n in chord.notes]
            and all(not n.decorations and not n.fingering for n in chord.notes)
        ):
            notes = tuple(replace(note, tied=new.tied) for note, new in zip(last.notes, chord.notes))
            result[-1] = replace(last, duration=last.duration + chord.duration, notes=notes)
        else:
            result.append(chord)
    return result


def written(voice: n1x.Voice) -> tuple:
    return (merged(voice.chords), sorted(voice.tuplets), voice.lyrics, [rest for rest in voice.rests if rest[2]])


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
        if cell in plan.cells:
            continue
        want, got = before.get(cell, []), after.get(cell, [])
        loose_want, loose_got = want, got
        for first, neighbour in ((False, position + 1), (True, position - 1)):
            if (neighbour, track) in plan.cells:
                loose_want, loose_got = _untied(loose_want, first), _untied(loose_got, first)
        if loose_want != loose_got:
            return f"bar {numbers[position]}, staff {track // 4 + 1} voice {track % 4 + 1}, outside the idea, changed", []
        if want != got:
            cut.add(numbers[position])
    annotations = ([line for line in pre if line.startswith("A ")], [line for line in post if line.startswith("A ")])
    if annotations[0] != annotations[1]:
        return f"the dynamics, chord symbols or texts in the range changed: {annotations[0]} -> {annotations[1]}", []
    positions = sorted({position for position, _ in plan.cells})
    text = n1x.encode(info, build_index(info, post, division), numbers[positions[0]], numbers[positions[-1]])
    back = n1x.decode(text)
    got_voices = {(bar.number, cell): voice for bar in back.bars for cell, voice in bar.voices.items()}
    for bar in plan.idea.bars:
        for cell, voice in sorted(bar.voices.items()):
            if written(voice) != written(got_voices.get((bar.number, cell), n1x.Voice())):
                label = f"{cell[0]}.{cell[1]}"
                return f"bar {bar.number} {label} was written as '{line_of(plan.idea, bar.number, label)}' and reads back as '{line_of(back, bar.number, label)}'", []
    return None, sorted(cut)
