"""How well humming becomes notes: SwiftF0 and its note splitter, on the HumTrans test clips.

    uv run --group hum-eval python -m eval.hum_eval [--key] [--eighths] [--hold MS] [--split valid|train] [--meter 3/4] [--clips N]

HumTrans (CC BY-NC 4.0) and the corrected onsets of Dynamic HumTrans (no licence) are fetched into out/hum-eval/
and never committed; only clips with corrected onsets are read from the 14.7 GB archive: 440 in test (the default),
374 in valid, 6,827 in train, of which --clips takes N spread evenly. Two scores: raw note F1 against the corrected
onsets (50 ms onsets, octave-invariant, the published metric; those onsets come from an amplitude threshold and are
often off, so this is for comparison only), and click mode: notes snapped to the grid of the melody's own MIDI after
the clip's latency from eval.hum_reference, counted right, up to one transposition, when the pitch lands on the right
grid slot and, stricter, when its written length is right too, so a rest held or lost counts; a last note the audio
cuts off is judged on its slot only. Clips eval.hum_reference leaves out are skipped.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
import zipfile
from pathlib import Path

import mir_eval
import numpy as np
import pretty_midi
import soundfile
import swift_f0

from reflets import hum

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
    return times, np.array([n.pitch for n in notes]), np.array([[n.start, n.end] for n in notes]), sixteenth


def hummed(path: Path, detector, hold: float, keyed: bool):
    audio, rate = soundfile.read(path, always_2d=True)
    notes = swift_f0.segment_notes(detector.detect(audio.mean(axis=1), rate), pitch_hold_ms=hold)
    if not notes:
        return np.zeros((0, 2)), np.zeros(0)
    semitones = np.array([69 + 12 * np.log2(n.pitch_hz / 440) for n in notes])
    weights = np.array([n.end - n.start for n in notes])
    raw = semitones - np.angle(np.sum(weights * np.exp(2j * np.pi * semitones))) / (2 * np.pi)
    intervals = np.array([[n.start, n.end] for n in notes])
    if not keyed:
        return intervals, np.round(raw)
    sung = [hum.Sung(n.start, n.end, r) for n, r in zip(notes, raw)]
    return intervals, np.array(hum.in_key(sung, hum.find_key(sung)), float)


def hz(midi) -> np.ndarray:
    return 440 * 2 ** ((np.asarray(midi, float) - 69) / 12)


def octave(score) -> int:
    return max(range(-24, 25, 12), key=score)


def on_steps(times, sixteenth: float, step: int) -> np.ndarray:
    return np.round(np.asarray(times) / (sixteenth * step)).astype(int) * step


def lengths(slots: np.ndarray, ends: np.ndarray, step: int) -> np.ndarray:
    following = np.append(slots[1:], np.iinfo(int).max)
    return np.minimum(np.maximum(ends, slots + step), following) - slots


def graded(slots, ends, pitches, ref_slots, ref_ends, ref_pitches, step, cut):
    values, ref_values = lengths(slots, ends, step), lengths(ref_slots, ref_ends, step)
    judged = [True] * (len(ref_slots) - 1) + [not cut]

    def counts(shift):
        found = dict(zip(zip(slots, pitches + shift), values))
        return (sum(found.get((s, p)) == v or (s, p) in found and not j for s, p, v, j in zip(ref_slots, ref_pitches, ref_values, judged)),
                sum((s, p) in found for s, p in zip(ref_slots, ref_pitches)))

    whole, placed = max(counts(shift) for shift in range(-24, 25))
    return placed, whole, len(slots), len(ref_slots)


def on_grid(intervals, pitches, latency, sixteenth, step):
    slots, ends = on_steps(intervals[:, 0] - latency, sixteenth, step), on_steps(intervals[:, 1] - latency, sixteenth, step)
    first = np.concatenate([[True], np.diff(slots) > 0])
    return slots[first], ends[first], pitches[first]


def reflets_grid(path: Path, latency, sixteenth, step, last_end):
    import soxr

    audio, rate = soundfile.read(path, always_2d=True)
    mono = soxr.resample(audio.mean(axis=1), rate, hum.RATE).astype(np.float32)
    result = hum.transcribe(mono, 4 * sixteenth, 4 // step, latency, last_end // step + 8)
    notes = result.notes if result else []
    return (np.array([n.slot * step for n in notes], int), np.array([(n.slot + n.length) * step for n in notes], int),
            np.array([n.pitch for n in notes], float))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold", type=float, default=80.0, help="SwiftF0 segment_notes pitch_hold_ms")
    parser.add_argument("--key", action="store_true", help="snap out-of-key notes that lean toward a scale note")
    parser.add_argument("--eighths", action="store_true", help="8th grid, on the clips whose melody has no 16ths")
    parser.add_argument("--reflets", action="store_true", help="click mode as reflets/hum.py does it, with its clean-up")
    parser.add_argument("--split", default="test", choices=["test", "valid", "train"])
    parser.add_argument("--meter", help="only clips whose MIDI is in this meter, such as 3/4")
    parser.add_argument("--clips", type=int, help="this many clips of the split, spread evenly")
    args = parser.parse_args()
    corrected, wanted = fetch(args.split, args.meter, args.clips)
    frozen = OUT / f"reference-{args.split}.json"
    if not frozen.exists():
        raise SystemExit(f"No {frozen.name}: run python -m eval.hum_reference with the same --split, --meter and --clips first")
    saved = json.loads(frozen.read_text())
    latencies = saved["latency"]
    missing = [key for key in wanted if key not in latencies and key not in saved["excluded"]]
    if missing:
        raise SystemExit(f"{len(missing)} clips are not in {frozen.name}: run python -m eval.hum_reference with the same options")
    wanted = [key for key in wanted if key in latencies]
    detector = swift_f0.SwiftF0()
    f1s, totals = [], np.zeros(4)
    step = 2 if args.eighths else 1
    for path in (OUT / "wav" / f"{key}.wav" for key in wanted):
        ref_times, ref_pitches, ref_notes, sixteenth = reference(path.stem, corrected)
        if len(ref_times) != len(ref_pitches):
            continue
        ref_slots, ref_ends = on_steps(ref_notes[:, 0], sixteenth, 1), on_steps(ref_notes[:, 1], sixteenth, step)
        scored = not (step == 2 and np.any(ref_slots % 2))
        latency = latencies[path.stem]
        cut = ref_notes[-1, 1] + latency > soundfile.info(path).duration
        intervals, pitches = hummed(path, detector, args.hold, args.key)
        if not len(pitches):
            f1s.append(0.0)
            totals += [0, 0, 0, len(ref_pitches) if scored else 0]
            continue
        f1 = lambda s: mir_eval.transcription.precision_recall_f1_overlap(
            ref_times, hz(ref_pitches + s), intervals, hz(pitches), onset_tolerance=0.05, pitch_tolerance=1.0, offset_ratio=None)[2]
        f1s.append(f1(octave(f1)))
        if scored:
            found = (reflets_grid(path, latency, sixteenth, step, int(ref_ends[-1])) if args.reflets
                     else on_grid(intervals, pitches, latency, sixteenth, step))
            totals += graded(*found, ref_slots, ref_ends, ref_pitches, step, cut)
    placed, whole, found, wanted = totals
    print(f"{len(f1s)} clips, {int(wanted)} notes scored on the {'8th' if args.eighths else '16th'} grid")
    print(f"raw note F1 against the corrected onsets (50 ms, octave-invariant): {np.mean(f1s):.3f}")
    print(f"right pitch on the right grid slot: recall {placed / wanted:.3f}, precision {placed / found:.3f}")
    print(f"and the right written length:      recall {whole / wanted:.3f}, precision {whole / found:.3f}")


if __name__ == "__main__":
    main()
