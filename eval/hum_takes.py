"""Score the saved hum takes (REFLETS_HUM_SAVE) against what was hummed, and compare with the last baseline.

    uv run --extra hum python -m eval.hum_takes [--folder spikes/hum/takes] [--save-baseline]
    uv run --extra hum python -m eval.hum_takes --label <take> <tune | right>

A take is scored once it is labelled: with a tune of reflets/hum_tunes.py (a known tune, or a melody played from
tests/data/hum-targets.musicxml before humming it), or 'right' when the notes it wrote were right, which makes them
its answer. Takes from hum_test come labelled; --folder out/hum-tests scores every tester's (eval.hum_pull), the
subfolders too. Pitches count up to one transposition, since people hum in a key of their own. Each take also gets
its edits per 4 bars: notes missing or of the wrong length, and notes extra.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from reflets import hum, n1x
from reflets.hum_tunes import TUNES
from reflets.write import midi_tpc

FOLDER = Path(__file__).parent.parent / "spikes" / "hum" / "takes"


def load(path: Path) -> tuple[np.ndarray, dict]:
    with wave.open(str(path.with_suffix(".wav"))) as source:
        audio = np.frombuffer(source.readframes(source.getnframes()), "<i2").astype(np.float32) / 32767
    return audio, json.loads(path.with_suffix(".json").read_text())


def transcribed(audio: np.ndarray, meta: dict) -> list[hum.Placed]:
    result = hum.hummed(audio, meta["starts"], meta["tempo"], meta["meter"], meta["bars"], meta["grid"], meta["latency"], meta["reach"])
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
        return [(slot * meta["grid"] // 4, length * meta["grid"] // 4, pitch) for slot, length, pitch in TUNES[tune].notes]
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
    now, totals, edits = {}, np.zeros(4, int), []
    for path in sorted(args.folder.rglob("*.wav")):
        name = str(path.relative_to(args.folder).with_suffix(""))
        audio, meta = load(path)
        truth = answer(meta)
        if truth is None:
            print(f"{name}  not labelled")
            continue
        placed, whole, extra = score(transcribed(audio, meta), truth)
        now[name] = [placed, whole, extra, len(truth)]
        totals += now[name]
        edits.append((len(truth) - whole + extra) * 4 / meta["bars"])
        before = baseline.get(name)
        change = "" if not before or before == now[name] else f"  (was {before[0]}/{before[1]}/{before[2]} extra)"
        print(f"{name}  {meta['tune']:20s} {placed}/{len(truth)} placed, {whole} with the right length, {extra} extra, "
              f"{edits[-1]:.1f} edits per 4 bars{change}")
    placed, whole, extra, wanted = totals
    if wanted:
        print(f"all: {placed}/{wanted} placed ({placed / wanted:.3f}), {whole} right length ({whole / wanted:.3f}), {extra} extra; "
              f"edits per 4 bars median {np.median(edits):.1f}, {sum(e == 0 for e in edits)}/{len(edits)} takes with none")
    if args.save_baseline:
        baseline_file.write_text(json.dumps(now, indent=1))


if __name__ == "__main__":
    main()
