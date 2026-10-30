"""Score the saved hum takes (REFLETS_HUM_SAVE) against what was hummed, and compare with the last baseline.

    uv run --extra hum python -m eval.hum_takes [--folder spikes/hum/takes] [--save-baseline]
    uv run --extra hum python -m eval.hum_takes --label <take> <tune | right>

A take is scored once it is labelled: with a known tune, with a melody of eval.hum_synth (played from
tests/data/hum-targets.musicxml before humming it), or 'right' when the notes it wrote were right, which makes them
its answer. Pitches count up to one transposition, since people hum in a key of their own.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from eval.hum_synth import MELODIES
from reflets import hum, n1x
from reflets.write import midi_tpc

FOLDER = Path(__file__).parent.parent / "spikes" / "hum" / "takes"
TUNES = {
    "twinkle": [(0, 4, 0), (4, 4, 0), (8, 4, 7), (12, 4, 7), (16, 4, 9), (20, 4, 9), (24, 4, 7),
                (32, 4, 5), (36, 4, 5), (40, 4, 4), (44, 4, 4), (48, 4, 2), (52, 4, 2), (56, 4, 0)],
    "ode": [(0, 4, 4), (4, 4, 4), (8, 4, 5), (12, 4, 7), (16, 4, 7), (20, 4, 5), (24, 4, 4), (28, 4, 2),
            (32, 4, 0), (36, 4, 0), (40, 4, 2), (44, 4, 4), (48, 6, 4), (54, 2, 2), (56, 8, 2)],
    "frere": [(0, 4, 0), (4, 4, 2), (8, 4, 4), (12, 4, 0), (16, 4, 0), (20, 4, 2), (24, 4, 4), (28, 4, 0),
              (32, 4, 4), (36, 4, 5), (40, 4, 7), (48, 4, 4), (52, 4, 5), (56, 4, 7)],
    "mary": [(0, 4, 4), (4, 4, 2), (8, 4, 0), (12, 4, 2), (16, 4, 4), (20, 4, 4), (24, 4, 4),
             (32, 4, 2), (36, 4, 2), (40, 4, 2), (48, 4, 4), (52, 4, 7), (56, 8, 7)],
    **{melody.name: melody.notes for melody in MELODIES},
}


def load(path: Path) -> tuple[np.ndarray, dict]:
    with wave.open(str(path.with_suffix(".wav"))) as source:
        audio = np.frombuffer(source.readframes(source.getnframes()), "<i2").astype(np.float32) / 32767
    return audio, json.loads(path.with_suffix(".json").read_text())


def transcribed(audio: np.ndarray, meta: dict) -> list[hum.Placed]:
    numerator, denominator = (int(x) for x in meta["meter"].split("/"))
    grid = meta["grid"]
    slots = meta["bars"] * numerator * 4 // denominator * grid
    result = hum.transcribe(audio[meta["starts"][numerator]:], 60 / meta["tempo"], grid, meta["latency"], slots, max(1, grid * 4 // denominator))
    return result.notes if result else []


def written(meta: dict) -> list[tuple[int, int, int]]:
    numerator, denominator = (int(x) for x in meta["meter"].split("/"))
    bar_slots = numerator * 4 * meta["grid"] // denominator
    notes: list[list[int]] = []
    tied = False
    for n, bar in enumerate(n1x.decode(meta["idea"]).bars):
        for chord in bar.voices[meta["staff"], 1].chords:
            slot, length = n * bar_slots + int(chord.onset * meta["grid"]), int(chord.duration * meta["grid"])
            pitch = midi_tpc(chord.notes[0].pitch)[0]
            if tied and notes[-1][0] + notes[-1][1] == slot and notes[-1][2] == pitch:
                notes[-1][1] += length
            else:
                notes.append([slot, length, pitch])
            tied = chord.notes[0].tied
    return [tuple(note) for note in notes]


def answer(meta: dict) -> list[tuple[int, int, int]] | None:
    tune = meta.get("tune")
    if tune == "right":
        return written(meta)
    if tune in TUNES:
        return [(slot * meta["grid"] // 4, length * meta["grid"] // 4, pitch) for slot, length, pitch in TUNES[tune]]
    return None


def score(notes: list[hum.Placed], truth: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    def counts(shift: int) -> tuple[int, int]:
        found = {(n.slot, n.pitch + shift): n.length for n in notes}
        return (sum((s, p) in found for s, _, p in truth), sum(found.get((s, p)) == length for s, length, p in truth))

    placed, whole = counts(max(range(-60, 61), key=counts))
    return placed, whole, len(notes) - placed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, default=FOLDER)
    parser.add_argument("--label", nargs=2, metavar=("TAKE", "TUNE"))
    parser.add_argument("--save-baseline", action="store_true")
    args = parser.parse_args()
    if args.label:
        path = args.folder / f"{args.label[0]}.json"
        meta = json.loads(path.read_text())
        if args.label[1] not in TUNES and args.label[1] != "right":
            raise SystemExit(f"tune is one of {', '.join(TUNES)} or 'right'")
        path.write_text(json.dumps({**meta, "tune": args.label[1]}, indent=1))
        return
    baseline_file = args.folder / "baseline.json"
    baseline = json.loads(baseline_file.read_text()) if baseline_file.exists() else {}
    now, totals = {}, np.zeros(4, int)
    for path in sorted(args.folder.glob("*.wav")):
        audio, meta = load(path)
        truth = answer(meta)
        if truth is None:
            print(f"{path.stem}  not labelled")
            continue
        placed, whole, extra = score(transcribed(audio, meta), truth)
        now[path.stem] = [placed, whole, extra, len(truth)]
        totals += now[path.stem]
        before = baseline.get(path.stem)
        change = "" if not before or before == now[path.stem] else f"  (was {before[0]}/{before[1]}/{before[2]} extra)"
        print(f"{path.stem}  {meta['tune']:20s} {placed}/{len(truth)} placed, {whole} with the right length, {extra} extra{change}")
    placed, whole, extra, wanted = totals
    if wanted:
        print(f"all: {placed}/{wanted} placed ({placed / wanted:.3f}), {whole} right length ({whole / wanted:.3f}), {extra} extra")
    if args.save_baseline:
        baseline_file.write_text(json.dumps(now, indent=1))


if __name__ == "__main__":
    main()
