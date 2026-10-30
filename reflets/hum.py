"""Humming to notes: pitch track, note split, tuning, key, clean-up and grid snap, then N1x voice lines."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import numpy as np
import swift_f0

RATE = 16000
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
MAJOR_STEPS = [0, 2, 4, 5, 7, 9, 11]
MINOR_STEPS = [0, 2, 3, 5, 7, 8, 10]
FIFTHS = "FCGDAEB"
SHORT_STEPS = 0.45
SCOOP_STEPS = 0.55
SCOOP_SEMITONES = 2.5
KEY_CLOSE = 0.15
TOUCHING = 0.06
PUSH_RISE = 8
PUSH_FALL = 6
PUSH_CLEAR = 0.2
FRAME = 160


@dataclass
class Sung:
    start: float
    end: float
    semitone: float


@dataclass
class Placed:
    slot: int
    length: int
    pitch: int


@dataclass
class Key:
    tonic: int
    major: bool
    fifths: int
    margin: float

    @property
    def name(self) -> str:
        return f"{spell(self.tonic, self.fifths + (0 if self.major else 3), octave=False)} {'major' if self.major else 'minor'}"

    @property
    def triad(self) -> set[int]:
        return {(self.tonic + step) % 12 for step in (0, 4 if self.major else 3, 7)}

    @property
    def scale(self) -> set[int]:
        return {(self.tonic + step) % 12 for step in (MAJOR_STEPS if self.major else MINOR_STEPS)}


def tpc_of(pitch: int, fifths: int) -> int:
    choices = [t for t in range(-15, 21) if (t * 7) % 12 == pitch % 12]
    return min(choices, key=lambda t: abs(t - fifths - 2))


def spell(pitch: int, fifths: int, octave: bool = True) -> str:
    tpc = tpc_of(pitch, fifths)
    letter = FIFTHS[(tpc + 1) % 7]
    alter = (tpc + 1) // 7
    name = letter + ("#" * alter if alter > 0 else "b" * -alter)
    return f"{name}{(pitch - alter - 'C D EF G A B'.index(letter)) // 12 - 1}" if octave else name


def fifths_of(tonic: int, major: bool) -> int:
    relative = tonic if major else (tonic + 3) % 12
    return min(range(-7, 8), key=lambda f: (((f * 7) % 12) != relative, abs(f)))


@cache
def detector() -> swift_f0.SwiftF0:
    return swift_f0.SwiftF0()


def track(audio: np.ndarray) -> list[Sung]:
    result = detector().detect(audio.astype(np.float32), RATE)
    found = swift_f0.segment_notes(result, pitch_hold_ms=80)
    times, hz, voiced = np.asarray(result.timestamps), np.asarray(result.pitch_hz), np.asarray(result.confidence) > 0.9
    sung = []
    for n in found:
        settled = voiced & (times >= n.start + min(0.08, 0.25 * (n.end - n.start))) & (times <= n.end - 0.1 * (n.end - n.start))
        pitch = np.median(hz[settled]) if settled.any() else n.pitch_hz
        sung.append(Sung(n.start, n.end, 69 + 12 * np.log2(pitch / 440)))
    return sung


def tuned(sung: list[Sung]) -> tuple[list[Sung], float]:
    semitones = np.array([s.semitone for s in sung])
    weights = np.array([s.end - s.start for s in sung])
    tuning = float(np.angle(np.sum(weights * np.exp(2j * np.pi * semitones))) / (2 * np.pi))
    return [Sung(s.start, s.end, s.semitone - tuning) for s in sung], tuning


def ranking(profile: np.ndarray) -> list[tuple[float, int, bool]]:
    return sorted(((np.corrcoef(profile, np.roll(shape, tonic))[0, 1], tonic, shape is MAJOR)
                   for tonic in range(12) for shape in (MAJOR, MINOR)), reverse=True)


def find_key(sung: list[Sung]) -> Key:
    classes = [round(s.semitone) % 12 for s in sung]
    durations = [s.end - s.start for s in sung]
    lower = [int(np.floor(s.semitone)) for s in sung]
    above = [s.semitone - low for s, low in zip(sung, lower)]
    split = (np.bincount([low % 12 for low in lower], [d * (1 - a) for d, a in zip(durations, above)], 12)
             + np.bincount([(low + 1) % 12 for low in lower], [d * a for d, a in zip(durations, above)], 12))
    ranked = ranking(np.bincount(classes, weights=durations, minlength=12))
    split_ranked = ranking(split)
    best = ranked[0][0]
    fit = {(tonic, major): r for r, tonic, major in ranked}

    def in_scale(tonic: int, major: bool) -> float:
        steps = MAJOR_STEPS if major else MINOR_STEPS
        return sum(d for c, d in zip(classes, durations) if (c - tonic) % 12 in steps)

    near = ({(tonic, major) for r, tonic, major in ranked if best - r <= KEY_CLOSE}
            | {(tonic, major) for r, tonic, major in split_ranked if split_ranked[0][0] - r <= KEY_CLOSE})
    tonic, major = max(near, key=lambda k: (in_scale(*k), fit[k]))
    other = max(r for r, t, m in ranked if (t, m) != (tonic, major))
    return Key(tonic, major, fifths_of(tonic, major), float(fit[tonic, major] - other))


def in_key(sung: list[Sung], key: Key) -> list[int]:
    pitches = []
    for s in sung:
        rounded = round(s.semitone)
        near = rounded + (1 if s.semitone > rounded else -1)
        if rounded % 12 not in key.scale and abs(s.semitone - rounded) > 0.15 and near % 12 in key.scale:
            rounded = near
        elif abs(s.semitone - rounded) > 0.3 and near % 12 in key.triad and rounded % 12 not in key.triad:
            rounded = near
        pitches.append(rounded)
    return pitches


def absorb_short(sung: list[Sung], shortest: float, scoop: float) -> list[Sung]:
    out: list[Sung] = []
    pending: Sung | None = None
    for i, own in enumerate(sung):
        s = Sung(pending.start, own.end, own.semitone) if pending else own
        pending = None
        following = sung[i + 1] if i + 1 < len(sung) else None
        touching = following is not None and following.start - s.end < TOUCHING
        slides_in = touching and own.end - own.start < scoop and abs(own.semitone - following.semitone) <= SCOOP_SEMITONES
        if s.end - s.start >= shortest and not slides_in:
            out.append(s)
            continue
        if touching:
            pending = s
        elif out and s.start - out[-1].end < TOUCHING:
            out[-1] = Sung(out[-1].start, s.end, out[-1].semitone)
    return out


def loudness(audio: np.ndarray) -> np.ndarray:
    frames = audio[: len(audio) // FRAME * FRAME].reshape(-1, FRAME)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(1)) + 1e-9)


def pushed(level: np.ndarray, at: float) -> bool | None:
    i = int(at * RATE / FRAME)
    if i < 20 or i + 12 > len(level):
        return None
    dip = level[i - 15:i + 3].min()
    return bool(level[i:i + 12].max() - dip >= PUSH_RISE and level[i - 20:i - 8].mean() - dip >= PUSH_FALL)


def split_pushes(sung: list[Sung], level: np.ndarray, step: float, latency: float) -> list[Sung]:
    clear = max(0.6 * step, PUSH_CLEAR)
    out = []
    for s in sung:
        start = s.start
        for k in range(int(np.floor((s.start - latency) / step)) + 1, int(np.ceil((s.end - latency) / step))):
            at = k * step + latency
            if at - start > clear and s.end - at > clear and pushed(level, at):
                out.append(Sung(start, at, s.semitone))
                start = at
        out.append(Sung(start, s.end, s.semitone))
    return out


def join_unpushed(sung: list[Sung], pitches: list[int], level: np.ndarray) -> tuple[list[Sung], list[int]]:
    out: list[Sung] = []
    kept: list[int] = []
    for s, pitch in zip(sung, pitches):
        if out and kept[-1] == pitch and s.start - out[-1].end < TOUCHING and pushed(level, s.start) is False:
            out[-1] = Sung(out[-1].start, s.end, out[-1].semitone)
            continue
        out.append(s)
        kept.append(pitch)
    return out, kept


def fix_octaves(pitches: list[int]) -> list[int]:
    out = list(pitches)
    for i in range(len(out)):
        neighbours = [out[j] for j in (i - 1, i + 1) if 0 <= j < len(out)]
        if neighbours and all(abs(out[i] - n) >= 9 for n in neighbours):
            out[i] += 12 * round((np.mean(neighbours) - out[i]) / 12)
    return out


def snap(sung: list[Sung], pitches: list[int], step: float, latency: float, slots: int, rest: int) -> list[Placed]:
    placed: list[Placed] = []
    held = 0.0
    for s, pitch in zip(sung, pitches):
        slot = round((s.start - latency) / step)
        end = max(slot + 1, round((s.end - latency) / step))
        if end <= 0 or slot >= slots:
            continue
        slot = max(slot, 0)
        if placed and placed[-1].slot == slot:
            if s.end - s.start <= held:
                continue
            placed.pop()
        held = s.end - s.start
        if placed and placed[-1].slot + placed[-1].length > slot:
            placed[-1].length = slot - placed[-1].slot
        placed.append(Placed(slot, min(end, slots) - slot, pitch))
    for a, following in zip(placed, [p.slot for p in placed[1:]] + [slots]):
        if following - (a.slot + a.length) < rest:
            a.length = following - a.slot
    return placed


@dataclass
class Transcription:
    notes: list[Placed]
    key: Key
    tuning: float


def transcribe(audio: np.ndarray, beat: float, grid: int, latency: float, slots: int, click: int | None = None) -> Transcription | None:
    step = beat / grid
    sung = track(audio)
    if not sung:
        return None
    sung, tuning = tuned(sung)
    key = find_key(sung)
    sung = absorb_short(sung, SHORT_STEPS * step, SCOOP_STEPS * step)
    level = loudness(audio)
    sung = split_pushes(sung, level, step, latency)
    sung, pitches = join_unpushed(sung, fix_octaves(in_key(sung, key)), level)
    notes = snap(sung, pitches, step, latency, slots, click or grid)
    return Transcription(notes, key, tuning)


CENTRES = [
    ("piccolo", 86), ("alto-flute", 67), ("bass-flute", 55), ("flute", 79), ("oboe", 74), ("english-horn", 65), ("bass-clarinet", 50), ("clarinet", 67),
    ("contrabassoon", 38), ("bassoon", 50), ("soprano-saxophone", 70), ("alto-saxophone", 63), ("tenor-saxophone", 56),
    ("baritone-saxophone", 48), ("trumpet", 69), ("horn", 60), ("bass-trombone", 45), ("trombone", 52), ("tuba", 38),
    ("violin", 74), ("viola", 62), ("violoncello", 50), ("cello", 50), ("contrabass", 38), ("bass-guitar", 38),
    ("guitar", 59), ("soprano", 70), ("mezzo", 67), ("alto", 64), ("tenor", 57), ("baritone", 52), ("bass", 48),
    ("voice", 64),
]
KEYBOARD_CENTRES = (72, 50)


def centre(instrument: str, staff_in_part: int, staves_in_part: int) -> int:
    if staves_in_part > 1:
        return KEYBOARD_CENTRES[min(staff_in_part, 1)]
    return next((pitch for name, pitch in CENTRES if name in instrument), 67)


def placed_octave(pitches: list[int], target: int) -> int:
    middle = float(np.median(pitches))
    return 12 * round((target - middle) / 12)


def tonic_near(target: int, tonic: int) -> int:
    return target + (tonic - target + 6) % 12 - 6


def key_from_signature(fifths: int, major: bool) -> int:
    return (fifths * 7 + (0 if major else 9)) % 12


def moved_to(key: Key, fifths: int) -> int:
    tonic = key_from_signature(fifths, key.major)
    return (tonic - key.tonic + 6) % 12 - 6


def voice_lines(notes: list[Placed], bar_slots: list[int], div_per_slot: int, fifths: int) -> list[str]:
    lines, start = [], 0
    for length in bar_slots:
        end, cursor, tokens = start + length, start, []
        for note in notes:
            first, last = max(note.slot, start), min(note.slot + note.length, end)
            if first >= last:
                continue
            if first > cursor:
                tokens.append(f"{(first - cursor) * div_per_slot} r")
            tie = "~" if note.slot + note.length > end else ""
            tokens.append(f"{(last - first) * div_per_slot} {spell(note.pitch, fifths)}{tie}")
            cursor = last
        lines.append(" ".join(tokens) or f"{length * div_per_slot} r")
        start = end
    return lines


def calibration(audio: np.ndarray, clicks: list[float]) -> float | None:
    sung = track(audio)
    offsets = []
    for at in clicks:
        near = [s for s in sung if -0.15 < s.start - at < 0.6]
        if near:
            offsets.append(max(near, key=lambda s: s.end - s.start).start - at)
    if len(offsets) < len(clicks) * 0.6:
        return None
    middle = float(np.median(offsets))
    agreeing = [o for o in offsets if abs(o - middle) < 0.05]
    return float(np.median(agreeing)) if len(agreeing) >= len(clicks) * 0.6 else None
