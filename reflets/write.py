from __future__ import annotations

import bisect
import re
from dataclasses import dataclass, field
from fractions import Fraction

from engine import notes

from reflets.score import FIFTHS, SEMITONES, ScoreInfo

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
    expected: dict[tuple[int, int], list[tuple]] = field(default_factory=dict)
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
        raise IdeaError(f"{where}: a duration of {quarters} quarter notes needs a tuplet; tuplets cannot be written yet")
    result = []
    while whole:
        value = next(value for value in VALUES if value <= whole)
        result.append(value)
        whole -= value
    return result


def voice_lines(idea: str) -> dict[int, set[tuple[int, int]]]:
    targets: dict[int, set[tuple[int, int]]] = {}
    bar = None
    for line in idea.splitlines():
        line = line.strip()
        if re.match(r"m\d+\b", line):
            bar = int(line.split()[0][1:])
            targets.setdefault(bar, set())
        elif bar is not None and re.match(r"\d+\.\d+:", line):
            staff, voice = (int(x) for x in line.split(":")[0].split("."))
            targets[bar].add((staff, voice))
    return targets


def as_n1(idea: str) -> str:
    lines = []
    for line in idea.strip().splitlines():
        line = line.strip()
        if not lines:
            lines.append(re.sub(r"^N1x ", "N1 ", line))
        elif re.match(r'(title|composer)=|P\d+ "', line):
            continue
        elif re.match(r"m\d+\b", line):
            words = line.split()
            unwritable = [word for word in words[1:] if word.split("=")[0] not in ("len", "ts")]
            if unwritable:
                raise IdeaError(f"{words[0]}: bar fields cannot be written yet ({' '.join(unwritable)}); leave them out")
            lines.append(line)
        else:
            lines.append(line)
    return "\n".join(lines)


def compile_idea(idea: str, info: ScoreInfo, division: int, staves: int) -> Plan:
    idea = as_n1(idea)
    try:
        index = notes.decode(idea)
    except notes.NotesError as error:
        raise IdeaError(str(error)) from None
    targets = voice_lines(idea)
    numbers = [measure.number for measure in info.measures]
    ops, graces, ties = [], [], []
    plan = Plan(0, 0, ops, set())
    voices: dict[int, list[tuple[int, Fraction, list[tuple[int, int, bool]]]]] = {}
    for measure in index.measures:
        bar = measure.number
        if bar not in numbers:
            raise IdeaError(f"Bar {bar} does not exist; the score has bars {numbers[0]} to {numbers[-1]}")
        position = numbers.index(bar)
        length, bar_tick = info.lengths[position], info.ticks[position]
        if measure.declared_length != length:
            raise IdeaError(f"m{bar}: len= must match the score's bar, which is {length} quarter notes long")
        for staff, layer in sorted(targets.get(bar, ())):
            if not 1 <= staff <= staves or not 1 <= layer <= 4:
                raise IdeaError(f"m{bar}: there is no {staff}.{layer}; the score has staves 1 to {staves}, voices 1 to 4")
            track = (staff - 1) * 4 + layer - 1
            cell = (position, track)
            plan.cells.add(cell)
            expected = plan.expected.setdefault(cell, [])
            events = [event for event in measure.events if event.staff == staff and event.layer == layer]
            mains: dict[Fraction, list] = {}
            before: dict[Fraction, dict[str, list]] = {}
            for event in events:
                if event.grace:
                    before.setdefault(event.onset, {}).setdefault(event.attack, []).append(event)
                else:
                    mains.setdefault(event.onset, []).append(event)
            ops.append(f"v {track} {bar_tick}")
            state = {"cursor": Fraction(0), "duration": None}

            def enter(kind: str, quarters: Fraction, pitches: list[tuple[int, int, bool]]) -> None:
                where = f"m{bar} {staff}.{layer}"
                chunks = pieces(quarters, where)
                for number, chunk in enumerate(chunks):
                    tick = bar_tick + int(state["cursor"] * division)
                    if chunk != state["duration"]:
                        ops.append(f"d {chunk.numerator}/{chunk.denominator}")
                        state["duration"] = chunk
                    if kind == "r":
                        ops.append(f"r {tick}")
                        expected.append((tick, "R", chunk, 0, 0, ()))
                    else:
                        ops.append(f"n {tick} " + ",".join(f"{pitch}:{tpc}" for pitch, tpc, _ in pitches))
                        last = number == len(chunks) - 1
                        tied = [(pitch, tpc, tie if last else True) for pitch, tpc, tie in pitches]
                        voices.setdefault(track, []).append((tick, chunk, tied, cell))
                    state["cursor"] += chunk * 4

            for onset in sorted(mains):
                where = f"m{bar} {staff}.{layer}"
                if onset > state["cursor"]:
                    enter("r", onset - state["cursor"], [])
                tick = bar_tick + int(onset * division)
                group = before.pop(onset, {})
                kind = "acciaccatura" if len(group) == 1 else "grace16"
                for sequence, attack in reversed(list(enumerate(sorted(group, key=int)))):
                    if len(group[attack]) > 1:
                        raise IdeaError(f"{where}: grace chords cannot be written yet")
                    pitch, tpc = midi_tpc(group[attack][0].pitch)
                    graces.append(f"g {track} {tick} {kind} {pitch}:{tpc}")
                    expected.append((tick, "G", None, GRACE_TYPES[kind], sequence, ((pitch, tpc, False, False),)))
                enter("n", mains[onset][0].duration, [(*midi_tpc(event.pitch), event.tied) for event in mains[onset]])
            if before:
                raise IdeaError(f"m{bar} {staff}.{layer}: a grace note must come before a note, not a rest or the bar end")
            if state["cursor"] > length:
                raise IdeaError(f"m{bar} {staff}.{layer}: the notes last {state['cursor']} quarter notes; the bar has {length}")
            if state["cursor"] < length:
                enter("r", length - state["cursor"], [])
    if not plan.cells:
        raise IdeaError("The idea has no voice lines; write at least one 'staff.voice:' line under a bar line")

    for track, chords in voices.items():
        backs: set[int] = set()
        for number, (tick, chunk, pitches, cell) in enumerate(chords):
            following = chords[number + 1] if number + 1 < len(chords) else None
            forwards = set()
            for pitch, tpc, tie in pitches:
                if not tie:
                    continue
                if not following or following[0] != tick + int(chunk * 4 * division) or pitch not in {p for p, _, _ in following[2]}:
                    raise IdeaError(
                        f"The tie on the note at tick {tick} (track {track}) needs the next note of that voice, "
                        "in the idea, to start right after it on the same pitch"
                    )
                ties.append(f"~ {track} {tick} {pitch}")
                forwards.add(pitch)
            plan.expected[cell].append(
                (tick, "C", chunk, 0, 0, tuple(sorted((p, t, p in backs, p in forwards) for p, t, _ in pitches)))
            )
            backs = forwards
    for expected in plan.expected.values():
        expected.sort(key=_order)
    plan.ops = ops + graces + ties
    positions = sorted({position for position, _ in plan.cells})
    plan.start_tick = info.ticks[positions[0]]
    plan.end_tick = info.ticks[positions[-1] + 1] if positions[-1] + 1 < len(info.ticks) else 2**31 - 1
    plan.counts = {
        "notes": sum(len(c[5]) for e in plan.expected.values() for c in e if c[1] == "C"),
        "rests": sum(1 for e in plan.expected.values() for c in e if c[1] == "R"),
        "ties": len(ties),
        "grace notes": len(graces),
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
            for note in words[4 + len(flags)].split(","):
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


def verify(plan: Plan, pre: list[str], post: list[str], info: ScoreInfo) -> tuple[str | None, list[int]]:
    before, after = cells(pre, info), cells(post, info)
    numbers = [measure.number for measure in info.measures]
    cut = set()
    for cell in sorted(set(before) | set(after) | plan.cells):
        position, track = cell
        want = plan.expected[cell] if cell in plan.cells else before.get(cell, [])
        got = after.get(cell, [])
        boundary = []
        if cell in plan.cells:
            if (position - 1, track) not in plan.cells:
                boundary.append(True)
        else:
            if (position + 1, track) in plan.cells:
                boundary.append(False)
            if (position - 1, track) in plan.cells:
                boundary.append(True)
        loose_want, loose_got = want, got
        for first in boundary:
            loose_want, loose_got = _untied(loose_want, first), _untied(loose_got, first)
        if loose_want != loose_got:
            return f"bar {numbers[position]}, staff {track // 4 + 1} voice {track % 4 + 1}: expected {want}, read back {got}", []
        if cell not in plan.cells and want != got:
            cut.add(numbers[position])
    annotations = ([line for line in pre if line.startswith("A ")], [line for line in post if line.startswith("A ")])
    if annotations[0] != annotations[1]:
        return f"the dynamics, chord symbols or texts in the range changed: {annotations[0]} -> {annotations[1]}", []
    return None, sorted(cut)
