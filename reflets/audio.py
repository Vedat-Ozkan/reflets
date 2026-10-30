"""The take: one duplex stream plays the count-in and click and records the mic on the same clock."""

from __future__ import annotations

import json
import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16000
CLICK = 0.03
LONGEST_ECHO = 0.5
ECHO_SPREAD = 0.01


@dataclass
class Take:
    audio: np.ndarray
    starts: list[int]
    gap: float
    device: str


def click(accent: bool) -> np.ndarray:
    t = np.arange(int(CLICK * RATE)) / RATE
    return ((0.6 if accent else 0.35) * np.sin(2 * np.pi * (1500 if accent else 1000) * t) * np.exp(-t * 120)).astype(np.float32)


def click_track(beat: float, beats: int, count: int) -> tuple[np.ndarray, list[int]]:
    starts = [int(n * beat * RATE) for n in range(count)]
    out = np.zeros(starts[-1] + int((beat + LONGEST_ECHO) * RATE), np.float32)
    for n, start in enumerate(starts):
        sound = click(n % beats == 0)
        out[start:start + len(sound)] += sound
    return out, starts


def record(play: np.ndarray, starts: list[int]) -> Take:
    import sounddevice

    recorded, times, position = [], [], [0]

    def callback(indata, outdata, frames, when, status):
        if not times:
            times.append(when.outputBufferDacTime - when.inputBufferAdcTime)
        chunk = play[position[0]:position[0] + frames]
        outdata[:, 0] = np.pad(chunk, (0, frames - len(chunk)))
        recorded.append(indata[:, 0].copy())
        position[0] += frames

    with sounddevice.Stream(samplerate=RATE, channels=1, dtype="float32", callback=callback):
        sounddevice.sleep(int(len(play) / RATE * 1000) + 100)
    device = sounddevice.query_devices(kind="input")["name"] + " / " + sounddevice.query_devices(kind="output")["name"]
    return Take(np.concatenate(recorded)[: len(play)], starts, times[0], device)


def echo(take: Take, beats: int) -> float | None:
    found = []
    for n, start in enumerate(take.starts[:beats]):
        sound = click(n % beats == 0)
        window = take.audio[start:start + int(LONGEST_ECHO * RATE) + len(sound)]
        found.append(int(np.argmax(np.abs(np.correlate(window, sound, mode="valid")))) / RATE)
    middle = float(np.median(found))
    agreeing = [f for f in found if abs(f - middle) <= ECHO_SPREAD]
    return float(np.median(agreeing)) if len(agreeing) >= max(2, len(found) - 1) else None


def latencies_file(folder: Path) -> Path:
    return folder / "hum-latency.json"


def stored_latency(folder: Path, device: str) -> float | None:
    try:
        return json.loads(latencies_file(folder).read_text()).get(device)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def store_latency(folder: Path, device: str, latency: float) -> None:
    try:
        known = json.loads(latencies_file(folder).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        known = {}
    known[device] = latency
    latencies_file(folder).write_text(json.dumps(known, indent=1))


def save(folder: Path, take: Take, meta: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path, n = folder / stamp, 2
    while path.with_suffix(".wav").exists():
        path, n = folder / f"{stamp}-{n}", n + 1
    with wave.open(str(path.with_suffix(".wav")), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes((np.clip(take.audio, -1, 1) * 32767).astype("<i2").tobytes())
    path.with_suffix(".json").write_text(json.dumps({**meta, "starts": take.starts, "gap": take.gap, "device": take.device}, indent=1))
    return path
