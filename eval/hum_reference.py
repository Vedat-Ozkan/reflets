"""The frozen reference eval.hum_eval scores against: each clip's latency, found from the audio, and the clips left out.

    uv run --group hum-eval --extra hum python -m eval.hum_reference [--split valid|train] [--meter 3/4] [--clips N]

Dynamic HumTrans's corrected onsets come from an amplitude threshold and miss the hummed onset by over 50 ms on about
a quarter of notes, so a latency taken from them can be off by a beat or more. Here the MIDI melody is slid over the
notes SwiftF0 tracks, to the offset where the most notes sound at the MIDI pitch up to one transposition, then refined
by the median gap between the tracked and MIDI onsets of those notes. A clip is left out when its audio repeats
another take's, when too few notes agree at the best offset, or when another offset half a beat or more away agrees
almost as well. The result goes to out/hum-eval/reference-<split>.json with the commit that made it; regenerate it
on purpose, never as part of an evaluation, so the target does not move with the tracker.
"""

from __future__ import annotations

import argparse
import json
import subprocess

import numpy as np
import soundfile
import soxr

from eval.hum_eval import OUT, fetch, reference
from reflets import hum

OFFSETS = np.arange(-1.0, 3.0, 0.01)
AGREEING = 0.5
CLEAR = 0.1


def tracked(key: str) -> tuple[list[hum.Sung], np.ndarray]:
    audio, rate = soundfile.read(OUT / "wav" / f"{key}.wav", always_2d=True)
    mono = audio.mean(axis=1)
    sung, _ = hum.tuned(hum.track(soxr.resample(mono, rate, hum.RATE).astype(np.float32)) or [hum.Sung(0, 0, 0)])
    return sung, mono


def agreement(sung: list[hum.Sung], notes: np.ndarray, pitches: np.ndarray, offset: float) -> tuple[int, int]:
    starts = np.array([s.start for s in sung])
    middles = notes.mean(axis=1) + offset
    index = np.searchsorted(starts, middles) - 1
    inside = (index >= 0) & (middles < np.array([s.end for s in sung])[np.maximum(index, 0)])
    differences = [round(sung[i].semitone - p) for i, p, ok in zip(index, pitches, inside) if ok]
    if not differences:
        return 0, 0
    values, counts = np.unique(differences, return_counts=True)
    return int(counts.max()), int(values[counts.argmax()])


def latency(sung: list[hum.Sung], notes: np.ndarray, pitches: np.ndarray, sixteenth: float) -> tuple[float | None, str]:
    scores = np.array([agreement(sung, notes, pitches, offset)[0] for offset in OFFSETS])
    best = int(scores.argmax())
    rival = scores[np.abs(OFFSETS - OFFSETS[best]) >= 2 * sixteenth].max(initial=0)
    if scores[best] < AGREEING * len(pitches):
        return None, "too few notes agree with the MIDI at any offset"
    if scores[best] - rival < CLEAR * len(pitches):
        return None, "another offset half a beat or more away agrees almost as well"
    offset, shift = OFFSETS[best], agreement(sung, notes, pitches, OFFSETS[best])[1]
    gaps = []
    for (start, end), pitch in zip(notes, pitches):
        near = [s for s in sung if abs(s.start - start - offset) < 2 * sixteenth and round(s.semitone - pitch) == shift]
        if near:
            gaps.append(min(near, key=lambda s: abs(s.start - start - offset)).start - start)
    return (float(np.median(gaps)) if len(gaps) >= 5 else float(offset)), ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", default="test", choices=["test", "valid", "train"])
    parser.add_argument("--meter")
    parser.add_argument("--clips", type=int)
    args = parser.parse_args()
    corrected, wanted = fetch(args.split, args.meter, args.clips)
    path = OUT / f"reference-{args.split}.json"
    saved = json.loads(path.read_text()) if path.exists() else {"latency": {}, "excluded": {}}
    takes: dict[str, tuple[str, np.ndarray]] = {}
    for key in wanted:
        ref_times, pitches, notes, sixteenth = reference(key, corrected)
        if len(ref_times) != len(pitches):
            continue
        sung, mono = tracked(key)
        parts = key.split("_")
        twin = "_".join(parts[:3] + parts[4:])
        earlier = takes.get(twin)
        if earlier and len(earlier[1]) == len(mono) and np.array_equal(earlier[1], mono):
            saved["excluded"][key] = f"the same recording as {earlier[0]}"
            continue
        takes[twin] = (key, mono)
        found, why = latency(sung, notes, pitches, sixteenth)
        if found is None:
            saved["excluded"][key] = why
        else:
            saved["latency"][key] = found
    saved["commit"] = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    path.write_text(json.dumps(saved, indent=0, sort_keys=True))
    print(f"{len(saved['latency'])} clips with a latency, {len(saved['excluded'])} left out, in {path}")


if __name__ == "__main__":
    main()
