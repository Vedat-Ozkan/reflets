"""How well humming becomes notes: SwiftF0 and its note splitter, on the HumTrans test clips.

    uv run --group hum-eval python -m eval.hum_eval [--key] [--eighths] [--human] [--hold MS] [--split valid|train] [--meter 3/4] [--clips N]

HumTrans (CC BY-NC 4.0) and the corrected onsets of Dynamic HumTrans (no licence) are fetched into out/hum-eval/
and never committed; only clips with corrected onsets are read from the 14.7 GB archive: 440 in test (the default),
374 in valid, 6,827 in train, of which --clips takes N spread evenly. Two scores:
raw note F1 (50 ms onsets, octave-invariant, the published metric), and click mode: notes snapped to the grid of
the melody's own MIDI after one latency offset, counted right when the pitch lands on the right grid slot and,
stricter, when the note value is right too. --human snaps the hummers' own labelled onsets and true pitches, the
ceiling any transcriber can reach on this data.
"""

from __future__ import annotations

import argparse
import urllib.request
import zipfile
from pathlib import Path

import mir_eval
import numpy as np
import pretty_midi
import soundfile
import swift_f0

from reflets.hum import MAJOR, MINOR

OUT = Path(__file__).parent.parent / "out" / "hum-eval"
HUMTRANS = "https://huggingface.co/datasets/dadinghh2/HumTrans/resolve/main/"
CORRECTED = "https://raw.githubusercontent.com/shubham-gupta-30/humming_transcription/HEAD/heurestic_filtered_onsets_offsets/filtered_{}.zip"


def meter(key: str) -> str:
    changes = pretty_midi.PrettyMIDI(str(OUT / "midi" / "midi_data" / f"{key}.mid")).time_signature_changes
    return f"{changes[-1].numerator}/{changes[-1].denominator}" if changes else "4/4"


def fetch(split: str, only: str | None, clips: int | None) -> tuple[zipfile.ZipFile, list[str]]:
    OUT.mkdir(parents=True, exist_ok=True)
    labels = OUT / f"filtered_{split}.zip"
    if not labels.exists():
        urllib.request.urlretrieve(CORRECTED.format(split), labels)
    if not (OUT / "midi").exists():
        urllib.request.urlretrieve(HUMTRANS + "all_midi.zip", OUT / "all_midi.zip")
        zipfile.ZipFile(OUT / "all_midi.zip").extractall(OUT / "midi")
    corrected = zipfile.ZipFile(labels)
    wanted = sorted(Path(name).name.split("_onsets_offsets")[0] for name in corrected.namelist() if name.endswith(".txt"))
    if only:
        wanted = [key for key in wanted if meter(key) == only]
    if clips:
        wanted = [wanted[i] for i in np.unique(np.linspace(0, len(wanted) - 1, clips).astype(int))]
    (OUT / "wav").mkdir(exist_ok=True)
    if any(not (OUT / "wav" / f"{key}.wav").exists() for key in wanted):
        from remotezip import RemoteZip

        with RemoteZip(HUMTRANS + "all_wav.zip") as archive:
            names = {Path(name).stem: name for name in archive.namelist() if name.endswith(".wav")}
            for key in sorted(set(wanted) & names.keys()):
                if not (OUT / "wav" / f"{key}.wav").exists():
                    (OUT / "wav" / f"{key}.wav").write_bytes(archive.read(names[key]))
    return corrected, wanted


def reference(key: str, corrected: zipfile.ZipFile):
    midi = pretty_midi.PrettyMIDI(str(OUT / "midi" / "midi_data" / f"{key}.mid"))
    notes = midi.instruments[0].notes
    rows = [line.split() for line in corrected.read(f"{key}_onsets_offsets.txt").decode().splitlines() if line.strip()]
    times = np.array([[float(a) / 44100, float(b) / 44100] for a, b in rows])
    sixteenth = 60 / midi.get_tempo_changes()[1][0] / 4
    return times, np.array([n.pitch for n in notes]), np.array([n.start for n in notes]), sixteenth


def in_key(raw: np.ndarray, rounded: np.ndarray, weights: np.ndarray) -> np.ndarray:
    profile = np.bincount(rounded.astype(int) % 12, weights=weights, minlength=12)
    _, tonic, major = max((np.corrcoef(profile, np.roll(shape, tonic))[0, 1], tonic, shape is MAJOR)
                          for tonic in range(12) for shape in (MAJOR, MINOR))
    scale = {(tonic + step) % 12 for step in ([0, 2, 4, 5, 7, 9, 11] if major else [0, 2, 3, 5, 7, 8, 10])}
    out = rounded.copy()
    for i, (r, n) in enumerate(zip(raw, rounded)):
        near = n + (1 if r > n else -1)
        if int(n) % 12 not in scale and abs(r - n) > 0.15 and int(near) % 12 in scale:
            out[i] = near
    return out


def hummed(path: Path, detector, hold: float, keyed: bool):
    audio, rate = soundfile.read(path, always_2d=True)
    notes = swift_f0.segment_notes(detector.detect(audio.mean(axis=1), rate), pitch_hold_ms=hold)
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    semitones = np.array([69 + 12 * np.log2(n.pitch_hz / 440) for n in notes])
    weights = np.array([n.end - n.start for n in notes])
    raw = semitones - np.angle(np.sum(weights * np.exp(2j * np.pi * semitones))) / (2 * np.pi)
    rounded = np.round(raw)
    return np.array([[n.start, n.end] for n in notes]), in_key(raw, rounded, weights) if keyed else rounded


def hz(midi) -> np.ndarray:
    return 440 * 2 ** ((np.asarray(midi, float) - 69) / 12)


def octave(score) -> int:
    return max(range(-24, 25, 12), key=score)


def on_grid(onsets, pitches, ref_pitches, ref_starts, ref_times, sixteenth, step):
    ref_slots = np.round(ref_starts / sixteenth).astype(int)
    if step == 2 and np.any(ref_slots % 2):
        return None
    latency = np.median(ref_times[:, 0] - ref_starts)
    slots = np.round((onsets - latency) / (sixteenth * step)).astype(int) * step
    first = np.concatenate([[True], np.diff(slots) > 0])
    slots, pitches = slots[first], pitches[first]
    ref_values, values = np.diff(np.append(ref_slots, 0)), np.diff(np.append(slots, 0))
    ref_values[-1] = values[-1] = 0

    def counts(shift):
        found = dict(zip(zip(slots, pitches + shift), values))
        return (sum((s, p) in found for s, p in zip(ref_slots, ref_pitches)),
                sum(found.get((s, p)) == v for s, p, v in zip(ref_slots, ref_pitches, ref_values)))

    placed, whole = counts(octave(lambda s: counts(s)[1]))
    return placed, whole, len(slots), len(ref_slots)


def reflets_grid(path: Path, ref_pitches, ref_starts, ref_times, sixteenth, step):
    from reflets import hum

    ref_slots = np.round(ref_starts / sixteenth).astype(int)
    if step == 2 and np.any(ref_slots % 2):
        return None
    audio, rate = soundfile.read(path, always_2d=True)
    latency = float(np.median(ref_times[:, 0] - ref_starts))
    import soxr

    mono = soxr.resample(audio.mean(axis=1), rate, hum.RATE).astype(np.float32)
    grid = 4 // step
    result = hum.transcribe(mono, 4 * sixteenth, grid, latency, int(ref_slots[-1] // step) + 8)
    notes = result.notes if result else []
    slots = np.array([n.slot * step for n in notes], int)
    pitches = np.array([n.pitch for n in notes], float)
    values = np.diff(np.append(slots, 0))
    ref_values = np.diff(np.append(ref_slots, 0))
    ref_values[-1] = 0
    if len(values):
        values[-1] = 0

    def counts(shift):
        found = dict(zip(zip(slots, pitches + shift), values))
        return (sum((s, p) in found for s, p in zip(ref_slots, ref_pitches)),
                sum(found.get((s, p)) == v for s, p, v in zip(ref_slots, ref_pitches, ref_values)))

    placed, whole = counts(octave(lambda s: counts(s)[1]))
    return placed, whole, len(slots), len(ref_slots)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold", type=float, default=80.0, help="SwiftF0 segment_notes pitch_hold_ms")
    parser.add_argument("--key", action="store_true", help="snap out-of-key notes that lean toward a scale note")
    parser.add_argument("--eighths", action="store_true", help="8th grid, on the clips whose melody has no 16ths")
    parser.add_argument("--human", action="store_true", help="the ceiling: the hummers' own onsets and true pitches")
    parser.add_argument("--reflets", action="store_true", help="click mode as reflets/hum.py does it, with its clean-up")
    parser.add_argument("--split", default="test", choices=["test", "valid", "train"])
    parser.add_argument("--meter", help="only clips whose MIDI is in this meter, such as 3/4")
    parser.add_argument("--clips", type=int, help="this many clips of the split, spread evenly")
    args = parser.parse_args()
    corrected, wanted = fetch(args.split, args.meter, args.clips)
    detector = swift_f0.SwiftF0()
    f1s, totals = [], np.zeros(4)
    for path in (OUT / "wav" / f"{key}.wav" for key in wanted):
        ref_times, ref_pitches, ref_starts, sixteenth = reference(path.stem, corrected)
        if len(ref_times) != len(ref_pitches):
            continue
        intervals, pitches = (ref_times, ref_pitches.astype(float)) if args.human else hummed(path, detector, args.hold, args.key)
        if not len(pitches):
            f1s.append(0.0)
            totals += [0, 0, 0, len(ref_pitches)]
            continue
        f1 = lambda s: mir_eval.transcription.precision_recall_f1_overlap(
            ref_times, hz(ref_pitches + s), intervals, hz(pitches), onset_tolerance=0.05, pitch_tolerance=1.0, offset_ratio=None)[2]
        f1s.append(f1(octave(f1)))
        step = 2 if args.eighths else 1
        counted = (reflets_grid(path, ref_pitches, ref_starts, ref_times, sixteenth, step) if args.reflets
                   else on_grid(intervals[:, 0], pitches, ref_pitches, ref_starts, ref_times, sixteenth, step))
        if counted:
            totals += counted
    placed, whole, found, wanted = totals
    print(f"{len(f1s)} clips, {int(wanted)} notes scored on the {'8th' if args.eighths else '16th'} grid")
    print(f"raw note F1 (50 ms, octave-invariant): {np.mean(f1s):.3f}")
    print(f"right pitch on the right grid slot: recall {placed / wanted:.3f}, precision {placed / found:.3f}")
    print(f"and the right note value:           recall {whole / wanted:.3f}, precision {whole / found:.3f}")


if __name__ == "__main__":
    main()
