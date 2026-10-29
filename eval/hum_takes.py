"""Score the saved hum takes (REFLETS_HUM_SAVE) against what was hummed, and compare with the last baseline.

    uv run --extra hum python -m eval.hum_takes [--folder spikes/hum/takes] [--save-baseline]
    uv run --extra hum python -m eval.hum_takes --label <take> <tune | right>

A take is scored once it is labelled: with a known tune, or 'right' when the notes it wrote were right, which makes
them its answer. Pitches count up to one transposition, since people hum in a key of their own.
"""

from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path

import numpy as np

from reflets import hum

FOLDER = Path(__file__).parent.parent / "spikes" / "hum" / "takes"
TUNES = {
    "twinkle": [(0, 2, 0), (2, 2, 0), (4, 2, 7), (6, 2, 7), (8, 2, 9), (10, 2, 9), (12, 4, 7),
                (16, 2, 5), (18, 2, 5), (20, 2, 4), (22, 2, 4), (24, 2, 2), (26, 2, 2), (28, 4, 0)],
    "ode": [(0, 2, 4), (2, 2, 4), (4, 2, 5), (6, 2, 7), (8, 2, 7), (10, 2, 5), (12, 2, 4), (14, 2, 2),
            (16, 2, 0), (18, 2, 0), (20, 2, 2), (22, 2, 4), (24, 3, 4), (27, 1, 2), (28, 4, 2)],
    "frere": [(0, 2, 0), (2, 2, 2), (4, 2, 4), (6, 2, 0), (8, 2, 0), (10, 2, 2), (12, 2, 4), (14, 2, 0),
              (16, 2, 4), (18, 2, 5), (20, 4, 7), (24, 2, 4), (26, 2, 5), (28, 4, 7)],
    "mary": [(0, 2, 4), (2, 2, 2), (4, 2, 0), (6, 2, 2), (8, 2, 4), (10, 2, 4), (12, 4, 4),
             (16, 2, 2), (18, 2, 2), (20, 4, 2), (24, 2, 4), (26, 2, 7), (28, 4, 7)],
}


def load(path: Path) -> tuple[np.ndarray, dict]:
    with wave.open(str(path.with_suffix(".wav"))) as source:
        audio = np.frombuffer(source.readframes(source.getnframes()), "<i2").astype(np.float32) / 32767
    return audio, json.loads(path.with_suffix(".json").read_text())


def transcribed(audio: np.ndarray, meta: dict) -> list[hum.Placed]:
    numerator, denominator = (int(x) for x in meta["meter"].split("/"))
    grid = meta["grid"]
    slots = meta["bars"] * numerator * 4 // denominator * grid
    result = hum.transcribe(audio[meta["starts"][numerator]:], 60 / meta["tempo"], grid, meta["latency"], slots)
    return result.notes if result else []


def answer(meta: dict) -> list[tuple[int, int, int]] | None:
    tune = meta.get("tune")
    if tune == "right":
        return [tuple(note) for note in meta["notes"]]
    if tune in TUNES:
        scale = meta["grid"] // 2
        return [(slot * scale, length * scale, pitch) for slot, length, pitch in TUNES[tune]]
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
        print(f"{path.stem}  {meta['tune']:8s} {placed}/{len(truth)} placed, {whole} with the right length, {extra} extra{change}")
    placed, whole, extra, wanted = totals
    if wanted:
        print(f"all: {placed}/{wanted} placed ({placed / wanted:.3f}), {whole} right length ({whole / wanted:.3f}), {extra} extra")
    if args.save_baseline:
        baseline_file.write_text(json.dumps(now, indent=1))


if __name__ == "__main__":
    main()
