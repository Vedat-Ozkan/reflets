"""Phase 0 spike: play a count-in and click, record a hum on the same stream, and print the notes.

    uv run --with sounddevice --with swift-f0 --with onnxruntime --with soundfile --with soxr \
        python spikes/hum/take.py --tempo 90 --bars 4

Takes are saved in spikes/hum/takes/ with the click times, so they can be scored again later.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import sounddevice
import soundfile
import swift_f0

RATE = 16000
NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def clicks(tempo, beats, bars):
    beat = 60 / tempo
    total = int((bars + 1) * beats * beat * RATE) + RATE
    out = np.zeros(total, np.float32)
    starts = []
    for n in range((bars + 1) * beats):
        start = int(n * beat * RATE)
        starts.append(start)
        t = np.arange(int(0.03 * RATE)) / RATE
        tone = np.sin(2 * np.pi * (1500 if n % beats == 0 else 1000) * t) * np.exp(-t * 120)
        out[start:start + len(t)] += (0.6 if n % beats == 0 else 0.35) * tone.astype(np.float32)
    return out, starts


def record(play):
    recorded, times, position = [], [], [0]

    def callback(indata, outdata, frames, when, status):
        if not times:
            times.append((when.outputBufferDacTime, when.inputBufferAdcTime, when.currentTime))
        chunk = play[position[0]:position[0] + frames]
        outdata[:, 0] = np.pad(chunk, (0, frames - len(chunk)))
        recorded.append(indata[:, 0].copy())
        position[0] += frames

    with sounddevice.Stream(samplerate=RATE, channels=1, dtype="float32", callback=callback) as stream:
        reported = stream.latency
        sounddevice.sleep(int(len(play) / RATE * 1000))
    return np.concatenate(recorded), times[0], reported


def notes_of(audio):
    found = swift_f0.segment_notes(swift_f0.SwiftF0().detect(audio, RATE), pitch_hold_ms=80)
    if not found:
        return []
    semitones = np.array([69 + 12 * np.log2(n.pitch_hz / 440) for n in found])
    weights = np.array([n.end - n.start for n in found])
    tuning = np.angle(np.sum(weights * np.exp(2j * np.pi * semitones))) / (2 * np.pi)
    raw = semitones - tuning
    rounded = np.round(raw)
    profile = np.bincount(rounded.astype(int) % 12, weights=weights, minlength=12)
    _, tonic, major = max((np.corrcoef(profile, np.roll(shape, tonic))[0, 1], tonic, shape is MAJOR)
                          for tonic in range(12) for shape in (MAJOR, MINOR))
    scale = {(tonic + s) % 12 for s in ([0, 2, 4, 5, 7, 9, 11] if major else [0, 2, 3, 5, 7, 8, 10])}
    for i, (r, n) in enumerate(zip(raw, rounded)):
        near = n + (1 if r > n else -1)
        if int(n) % 12 not in scale and abs(r - n) > 0.15 and int(near) % 12 in scale:
            rounded[i] = near
    key = f"{NAMES[tonic]} {'major' if major else 'minor'}"
    return [(n.start, n.end, int(p)) for n, p in zip(found, rounded)], key, round(float(tuning) * 100)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tempo", type=float, default=90)
    parser.add_argument("--beats", type=int, default=4, help="beats per bar")
    parser.add_argument("--bars", type=int, default=4)
    parser.add_argument("--grid", type=int, default=2, help="grid steps per beat: 2 = eighths, 4 = sixteenths")
    parser.add_argument("--latency", type=float, help="round trip in ms measured from the click echo, in place of the driver's")
    parser.add_argument("--list", action="store_true", help="list audio devices and stop")
    args = parser.parse_args()
    if args.list:
        print(sounddevice.query_devices())
        return
    play, starts = clicks(args.tempo, args.beats, args.bars)
    print(f"One bar of count-in at {args.tempo:g} BPM, then hum {args.bars} bars on 'da'...")
    audio, (dac, adc, now), reported = record(play)
    shift = int(round((args.latency / 1000 if args.latency else dac - adc) * RATE))
    print(f"stream latency reported (in, out): {reported}; output-input clock gap {1000 * (dac - adc):.1f} ms")
    probe = audio[: starts[1]]
    echo = int(np.argmax(np.abs(np.correlate(probe, play[: int(0.03 * RATE)], mode="valid"))))
    print(f"first click heard in the mic at {1000 * echo / RATE:.1f} ms (meaningful only with speakers, not headphones)")
    folder = Path(__file__).parent / "takes"
    folder.mkdir(exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S")
    soundfile.write(folder / f"{name}.wav", audio, RATE)
    beat = 60 / args.tempo
    first = starts[args.beats] + shift
    (folder / f"{name}.json").write_text(json.dumps({"tempo": args.tempo, "beats": args.beats, "bars": args.bars,
                                                     "first_beat_sample": first, "clock_gap_ms": 1000 * (dac - adc), "latency_ms": args.latency,
                                                     "echo_ms": 1000 * echo / RATE, "reported_latency": list(reported)}))
    level = 20 * np.log10(np.sqrt(np.mean(audio[first:] ** 2)) + 1e-9)
    print(f"mic level while humming: {level:.0f} dBFS (below about -50 means the mic is not reaching us)")
    result = notes_of(audio[first:])
    if not result:
        print("no notes found")
        return
    notes, key, cents = result
    print(f"key {key}, singer tuned {cents:+d} cents; saved {folder / name}.wav")
    step = beat / args.grid
    for start, end, pitch in notes:
        slot = int(round(start / step))
        bar, within = divmod(slot, args.beats * args.grid)
        print(f"  bar {bar + 1} beat {1 + within / args.grid:<5g} {NAMES[pitch % 12]}{pitch // 12 - 1:<3} "
              f"off grid {1000 * (start - slot * step):+5.0f} ms  length {end - start:.2f} s")


if __name__ == "__main__":
    main()
