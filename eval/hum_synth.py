"""How humming becomes notes on melodies HumTrans hardly has: chromatic notes, modes, syncopation, rests, repeats.

    uv run --extra hum python -m eval.hum_synth [--renders N] [--score tests/data/hum-targets.musicxml]

Each melody is synthesised as a hummed voice (scoop into each note, vibrato, a tuning offset and drift, each note
off pitch by 14 to 26 cents as HumTrans's hummers are, timing spread, a held or detached articulation, room noise
and a latency), in several renders with a different tonic, tempo and singer, then transcribed by reflets/hum.py on
the grid the melody needs. The labels are exact, so a note is right when its
pitch, up to one transposition, lands on its grid slot, and right in length when its written length is right too.
Half the singers join each note to the next with a glide and, on a repeated pitch, only a dip in loudness. Notes
outside the melody's major or minor key are counted apart, since HumTrans is 98% diatonic and a clean-up that snaps
toward the key wins there by never writing them. --score writes the melodies as a score to play before humming each
one, so the owner's takes of them are scored by eval.hum_takes against the same labels.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

from reflets import hum
from reflets.hum_tunes import MELODIES, Melody


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
    legato: bool


def singers(count: int) -> list[Singer]:
    rng = np.random.default_rng(7)
    return [Singer(int(rng.integers(45, 65)), float(rng.uniform(75, 125)), float(rng.uniform(-40, 40)),
                   float(rng.uniform(0.05, 0.25)), float(rng.uniform(0.7, 0.95)), float(rng.uniform(0.005, 0.03)),
                   float(rng.uniform(0.2, 1.5)), float(rng.uniform(0.05, 0.3)),
                   float(rng.uniform(14, 26)), bool(rng.random() < 0.5)) for _ in range(count)]


def sung(melody: Melody, singer: Singer, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    sixteenth = 15 / singer.tempo
    end = max(slot + length for slot, length, _ in melody.notes)
    size = int((end * sixteenth + singer.latency + 1) * hum.RATE)
    midi, level = np.full(size, 69.0), np.zeros(size)
    drift = rng.uniform(-30, 30)
    starts = [max(0.0, slot * sixteenth + singer.latency + rng.normal(0, singer.spread)) for slot, _, _ in melody.notes]
    previous = None
    for i, ((slot, length, degree), start) in enumerate(zip(melody.notes, starts)):
        joined = singer.legato and i + 1 < len(starts) and melody.notes[i + 1][0] == slot + length
        stop = starts[i + 1] if joined else start + max(0.06, length * sixteenth * singer.held + rng.normal(0, singer.spread))
        a, b = int(start * hum.RATE), min(size, int(stop * hum.RATE))
        t = np.arange(b - a) / hum.RATE
        pitch = singer.tonic + degree + (singer.cents + drift * slot / end + rng.normal(0, singer.intonation)) / 100
        if previous is None:
            glide = -singer.scoop * np.exp(-t / 0.04)
            attack = np.minimum(1, t / 0.02)
        else:
            glide = (previous - pitch) * np.exp(-t / 0.03)
            attack = 1 - (0.5 if round(previous) == round(pitch) else 0.1) * np.exp(-t / 0.03)
        midi[a:b] = pitch + glide + singer.vibrato * np.sin(2 * np.pi * 5.5 * t)
        release = 1 if joined else np.minimum(1, (len(t) / hum.RATE - t) / 0.05)
        level[a:b] = attack * release
        previous = pitch if joined else None
    phase = 2 * np.pi * np.cumsum(440 * 2 ** ((midi - 69) / 12)) / hum.RATE
    voice = sum(np.sin(k * phase) / k ** 1.5 for k in range(1, 8))
    return (0.2 * voice * level + 0.004 * rng.standard_normal(size)).astype(np.float32)


def scored(melody: Melody, singer: Singer, seed: int, reach: float) -> tuple[dict[str, int], dict[str, int]]:
    grid = melody.grid
    scale = 4 // grid
    numerator, denominator = melody.meter
    bar = numerator * grid * 4 // denominator
    end = max(slot + length for slot, length, _ in melody.notes) // scale
    result = hum.transcribe(sung(melody, singer, seed), 60 / singer.tempo, grid, singer.latency, reach, -(-end // bar) * bar,
                            max(1, grid * 4 // denominator))
    truth = [(slot // scale, length // scale, singer.tonic + degree) for slot, length, degree in melody.notes]
    main = tally(melody, result.notes if result else [], truth)
    given = tally(melody, result.as_given, truth) if result and result.as_given is not None else main
    return main, max(main, given, key=lambda t: t["whole"])


def tally(melody: Melody, notes: list[hum.Placed], truth: list[tuple[int, int, int]]) -> dict[str, int]:
    def counts(shift: int) -> tuple[int, int]:
        found = {(n.slot, n.pitch + shift): n.length for n in notes}
        return sum(found.get((s, p)) == length for s, length, p in truth), sum((s, p) in found for s, _, p in truth)

    shift = max(range(-24, 25), key=counts)
    found = {(n.slot, n.pitch + shift): n.length for n in notes}
    scale_steps = hum.MAJOR_STEPS if melody.key == "major" else hum.MINOR_STEPS
    outside = [(degree % 12) not in scale_steps for _, _, degree in melody.notes]
    counted = {"notes": len(truth), "placed": 0, "whole": 0, "found": len(notes), "outside": sum(outside), "outside placed": 0}
    for (s, length, p), out in zip(truth, outside):
        if (s, p) in found:
            counted["placed"] += 1
            counted["whole"] += found[s, p] == length
            counted["outside placed"] += out
    return counted


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
    print(f"{len(MELODIES)} melodies, {args.renders} renders each; recall / precision")
    paths = [("delay measured", 0, 0), ("delay searched", hum.DELAY_RANGE, 0), ("searched, or as given", hum.DELAY_RANGE, 1)]
    for label, by_kind in zip([label for label, *_ in paths], totals(singers(args.renders), paths)):
        print(label)
        for kind in ["control", "chromatic", "mode", "rhythm", "all"]:
            t = by_kind[kind]
            outside = f", outside the key {t['outside placed']}/{t['outside']} placed" if t["outside"] else ""
            print(f"  {kind:10} on the slot {t['placed'] / t['notes']:.3f} / {t['placed'] / t['found']:.3f}, "
                  f"right length {t['whole'] / t['notes']:.3f} / {t['whole'] / t['found']:.3f}{outside}")


def totals(voices: list[Singer], paths: list[tuple[str, float, int]]) -> list[dict[str, dict[str, int]]]:
    results = [defaultdict(lambda: defaultdict(int)) for _ in paths]
    for melody in MELODIES:
        for seed, singer in enumerate(voices):
            readings = {reach: scored(melody, singer, seed, reach) for reach in {reach for _, reach, _ in paths}}
            for (_, reach, reading), result in zip(paths, results):
                for key, value in readings[reach][reading].items():
                    result[melody.kind][key] += value
                    result["all"][key] += value
    return results


if __name__ == "__main__":
    main()
