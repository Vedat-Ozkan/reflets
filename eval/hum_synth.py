"""How humming becomes notes on melodies HumTrans hardly has: chromatic notes, modes, syncopation, rests, repeats.

    uv run --extra hum python -m eval.hum_synth [--renders N] [--score tests/data/hum-targets.musicxml]

Each melody is synthesised as a hummed voice (scoop into each note, vibrato, a tuning offset and drift, each note
off pitch by 14 to 26 cents as HumTrans's hummers are, timing spread, a held or detached articulation, room noise
and a latency), in several renders with a different tonic, tempo and singer, then transcribed by reflets/hum.py on
the grid the melody needs. The labels are exact, so a note is right when its
pitch, up to one transposition, lands on its grid slot, and right in length when its written length is right too.
Notes outside the melody's own mode are counted apart, since HumTrans is 98% diatonic and a clean-up that snaps
toward the key wins there by never writing them. --score writes the melodies as a score to play before humming each
one, so the owner's takes of them are scored by eval.hum_takes against the same labels.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from reflets import hum

MODES = {
    "major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10], "lydian": [0, 2, 4, 6, 7, 9, 11], "phrygian": [0, 1, 3, 5, 7, 8, 10],
    "harmonic minor": [0, 2, 3, 5, 7, 8, 11],
}


@dataclass
class Melody:
    name: str
    kind: str
    mode: str
    notes: list[tuple[int, int, int]]
    meter: tuple[int, int] = (4, 4)


MELODIES = [
    Melody("major-steps", "control", "major",
           [(0, 4, 0), (4, 4, 4), (8, 4, 7), (12, 4, 4), (16, 2, 5), (18, 2, 4), (20, 2, 2), (22, 2, 0), (24, 8, 2),
            (32, 4, 7), (36, 4, 9), (40, 4, 7), (44, 4, 5), (48, 4, 4), (52, 4, 2), (56, 8, 0)]),
    Melody("chromatic-run", "chromatic", "major",
           [(0, 4, 0), (4, 2, 2), (6, 2, 3), (8, 2, 4), (10, 2, 5), (12, 2, 6), (14, 2, 7), (16, 8, 9),
            (24, 2, 8), (26, 2, 7), (28, 2, 6), (30, 2, 5), (32, 4, 4), (36, 4, 3), (40, 8, 2), (48, 8, 0)]),
    Melody("chromatic-neighbours", "chromatic", "major",
           [(0, 4, 7), (4, 2, 6), (6, 2, 7), (8, 4, 4), (12, 2, 3), (14, 2, 4), (16, 4, 0), (20, 4, 1), (24, 8, 2),
            (32, 4, 9), (36, 2, 8), (38, 2, 9), (40, 4, 11), (44, 4, 10), (48, 8, 12)]),
    Melody("blues", "chromatic", "major",
           [(0, 4, 0), (4, 4, 3), (8, 2, 5), (10, 2, 6), (12, 4, 7), (16, 4, 10), (20, 4, 7), (24, 8, 6),
            (32, 4, 5), (36, 4, 3), (40, 4, 0), (44, 4, 3), (48, 4, 4), (52, 4, 0), (56, 8, 0)]),
    Melody("harmonic-minor", "chromatic", "harmonic minor",
           [(0, 4, 0), (4, 4, 3), (8, 4, 7), (12, 4, 8), (16, 4, 11), (20, 4, 12), (24, 8, 11),
            (32, 4, 8), (36, 4, 7), (40, 4, 5), (44, 4, 3), (48, 4, 2), (52, 4, -1), (56, 8, 0)]),
    Melody("dorian", "mode", "dorian",
           [(0, 4, 2), (4, 4, 5), (8, 4, 9), (12, 4, 7), (16, 4, 5), (20, 4, 4), (24, 8, 2),
            (32, 4, 9), (36, 4, 11), (40, 4, 12), (44, 4, 9), (48, 4, 7), (52, 4, 5), (56, 8, 2)]),
    Melody("mixolydian", "mode", "mixolydian",
           [(0, 4, 0), (4, 4, 4), (8, 4, 7), (12, 4, 10), (16, 8, 9), (24, 8, 7),
            (32, 4, 10), (36, 4, 9), (40, 4, 7), (44, 4, 5), (48, 4, 4), (52, 4, 2), (56, 8, 0)]),
    Melody("lydian", "mode", "lydian",
           [(0, 4, 0), (4, 4, 2), (8, 4, 4), (12, 4, 6), (16, 8, 7), (24, 8, 6),
            (32, 4, 9), (36, 4, 7), (40, 4, 6), (44, 4, 4), (48, 4, 6), (52, 4, 2), (56, 8, 0)]),
    Melody("phrygian", "mode", "phrygian",
           [(0, 4, 0), (4, 4, 1), (8, 4, 3), (12, 4, 1), (16, 8, 0), (24, 8, -2),
            (32, 4, 0), (36, 4, 1), (40, 4, 3), (44, 4, 5), (48, 4, 3), (52, 4, 1), (56, 8, 0)]),
    Melody("syncopation", "rhythm", "major",
           [(0, 2, 0), (2, 4, 2), (6, 2, 4), (8, 2, 5), (10, 4, 4), (14, 2, 2), (16, 6, 0), (22, 2, 2), (24, 8, 4),
            (32, 2, 7), (34, 4, 9), (38, 2, 7), (40, 6, 5), (46, 2, 4), (48, 2, 2), (50, 6, 0)]),
    Melody("rests", "rhythm", "major",
           [(0, 2, 0), (4, 2, 4), (8, 2, 7), (12, 4, 12), (20, 4, 7), (24, 2, 4), (28, 4, 0),
            (32, 2, 5), (34, 2, 4), (36, 2, 2), (40, 4, 7), (48, 2, 0), (52, 2, 2), (56, 4, 0)]),
    Melody("repeats", "rhythm", "major",
           [(0, 2, 4), (2, 2, 4), (4, 2, 4), (6, 2, 4), (8, 4, 5), (12, 4, 5), (16, 2, 7), (18, 2, 7), (20, 1, 7),
            (21, 1, 7), (22, 2, 7), (24, 8, 4), (32, 2, 2), (34, 2, 2), (36, 2, 2), (38, 2, 2), (40, 8, 0)]),
    Melody("dotted", "rhythm", "major",
           [(0, 3, 0), (3, 1, 2), (4, 3, 4), (7, 1, 5), (8, 4, 7), (12, 1, 9), (13, 1, 7), (14, 1, 5), (15, 1, 4),
            (16, 6, 2), (22, 2, 4), (24, 8, 0), (32, 3, 7), (35, 1, 5), (36, 3, 4), (39, 1, 2), (40, 8, 0)]),
    Melody("leaps", "control", "minor",
           [(0, 4, 0), (4, 4, 12), (8, 4, 7), (12, 4, -5), (16, 4, 3), (20, 4, 10), (24, 8, 8),
            (32, 4, 15), (36, 4, 3), (40, 4, 7), (44, 4, -2), (48, 8, 0)]),
    Melody("chromatic-waltz", "chromatic", "major",
           [(0, 4, 4), (4, 4, 3), (8, 4, 4), (12, 8, 7), (20, 4, 6), (24, 4, 7), (28, 4, 9), (32, 4, 8),
            (36, 12, 7), (48, 4, 5), (52, 4, 4), (56, 4, 2), (60, 12, 0)], (3, 4)),
]


@dataclass
class Singer:
    tonic: int
    tempo: float
    cents: float
    latency: float
    held: float
    spread: float
    scoop: float
    vibrato: float
    intonation: float


def singers(count: int) -> list[Singer]:
    rng = np.random.default_rng(7)
    return [Singer(int(rng.integers(45, 65)), float(rng.uniform(75, 125)), float(rng.uniform(-40, 40)),
                   float(rng.uniform(0.05, 0.25)), float(rng.uniform(0.7, 0.95)), float(rng.uniform(0.005, 0.03)),
                   float(rng.uniform(0.2, 1.5)), float(rng.uniform(0.05, 0.3)),
                   float(rng.uniform(14, 26))) for _ in range(count)]


def sung(melody: Melody, singer: Singer, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sixteenth = 15 / singer.tempo
    end = max(slot + length for slot, length, _ in melody.notes)
    audio = np.zeros(int((end * sixteenth + singer.latency + 1) * hum.RATE), np.float32)
    drift = rng.uniform(-30, 30)
    for slot, length, degree in melody.notes:
        start = max(0.0, slot * sixteenth + singer.latency + rng.normal(0, singer.spread))
        seconds = max(0.06, length * sixteenth * singer.held + rng.normal(0, singer.spread))
        t = np.arange(int(seconds * hum.RATE)) / hum.RATE
        bend = (singer.cents + drift * slot / end + rng.normal(0, singer.intonation)) / 100
        midi = singer.tonic + degree + bend - singer.scoop * np.exp(-t / 0.04) + singer.vibrato * np.sin(2 * np.pi * 5.5 * t)
        phase = 2 * np.pi * np.cumsum(440 * 2 ** ((midi - 69) / 12)) / hum.RATE
        voice = sum(np.sin(k * phase) / k ** 1.5 for k in range(1, 8))
        envelope = np.minimum(1, t / 0.02) * np.minimum(1, (seconds - t) / 0.05)
        at = int(start * hum.RATE)
        audio[at:at + len(t)] += (0.2 * voice * envelope)[: len(audio) - at].astype(np.float32)
    return audio + 0.004 * rng.standard_normal(len(audio)).astype(np.float32)


def scored(melody: Melody, singer: Singer, seed: int) -> dict[str, int]:
    grid = 2 if all(slot % 2 == 0 and length % 2 == 0 for slot, length, _ in melody.notes) else 4
    scale = 4 // grid
    numerator, denominator = melody.meter
    beat = 60 / singer.tempo * 4 / denominator
    bar = numerator * grid * 4 // denominator
    end = max(slot + length for slot, length, _ in melody.notes) // scale
    result = hum.transcribe(sung(melody, singer, seed), beat, grid, singer.latency, -(-end // bar) * bar)
    notes = result.notes if result else []
    truth = [(slot // scale, length // scale, singer.tonic + degree) for slot, length, degree in melody.notes]

    def counts(shift: int) -> tuple[int, int]:
        found = {(n.slot, n.pitch + shift): n.length for n in notes}
        return sum(found.get((s, p)) == length for s, length, p in truth), sum((s, p) in found for s, _, p in truth)

    shift = max(range(-24, 25), key=counts)
    found = {(n.slot, n.pitch + shift): n.length for n in notes}
    outside = [(degree % 12) not in MODES[melody.mode] for _, _, degree in melody.notes]
    tally = {"notes": len(truth), "placed": 0, "whole": 0, "found": len(notes), "outside": sum(outside), "outside placed": 0}
    for (s, length, p), out in zip(truth, outside):
        if (s, p) in found:
            tally["placed"] += 1
            tally["whole"] += found[s, p] == length
            tally["outside placed"] += out
    return tally


def write_score(path: str) -> None:
    from music21 import clef, duration, expressions, meter, note, stream

    part = stream.Part([clef.TrebleClef()])
    for melody in MELODIES:
        numerator, denominator = melody.meter
        bar = numerator * 16 // denominator
        end = max(slot + length for slot, length, _ in melody.notes)
        measures = [stream.Measure() for _ in range(-(-end // bar))]
        measures[0].append([meter.TimeSignature(f"{numerator}/{denominator}"), expressions.RehearsalMark(melody.name)])
        at = 0
        for slot, length, degree in melody.notes + [(len(measures) * bar, 0, 0)]:
            if slot > at:
                measures[at // bar].append(note.Rest(duration=duration.Duration(quarterLength=(slot - at) / 4)))
            if length:
                measures[slot // bar].append(note.Note(60 + degree, duration=duration.Duration(quarterLength=length / 4)))
            at = slot + length
        part.append(measures)
    stream.Score([part]).write("musicxml", fp=path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renders", type=int, default=24, help="renders of each melody, each by another singer")
    parser.add_argument("--score", help="write the melodies as MusicXML here instead")
    args = parser.parse_args()
    if args.score:
        write_score(args.score)
        return
    voices = singers(args.renders)
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for melody in MELODIES:
        for seed, singer in enumerate(voices):
            for key, value in scored(melody, singer, seed).items():
                totals[melody.kind][key] += value
                totals["all"][key] += value
    print(f"{len(MELODIES)} melodies, {args.renders} renders each; recall / precision")
    for kind in ["control", "chromatic", "mode", "rhythm", "all"]:
        t = totals[kind]
        outside = f", outside the mode {t['outside placed']}/{t['outside']} placed" if t["outside"] else ""
        print(f"{kind:10} on the slot {t['placed'] / t['notes']:.3f} / {t['placed'] / t['found']:.3f}, "
              f"right length {t['whole'] / t['notes']:.3f} / {t['whole'] / t['found']:.3f}{outside}")


if __name__ == "__main__":
    main()
