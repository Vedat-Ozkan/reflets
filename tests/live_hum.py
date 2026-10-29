"""End-to-end check of hum against a live MuseScore with any score open: each saved take (REFLETS_HUM_SAVE) whose meter
is the last bar's is written after the last bar of a staff in place of the microphone, read back and discarded. The
notes must sit in the staff's register, in the score's key when it has notes (or with its relative minor's leading tone), and on one pitch with --rhythm. When the
staff already has notes in its first bar, hum without replace must refuse before recording.

    uv run --extra hum python tests/live_hum.py [spikes/hum/takes] [--staff N] [--rhythm]
    uv run --extra hum python tests/live_hum.py --mic

With --mic the owner hums 4 bars at 90 after the count-in, into staff 1.
"""

import argparse
import asyncio
import re
from pathlib import Path

import numpy as np
from mcp.server.mcpserver.exceptions import ToolError

from eval import hum_takes
from reflets import audio, hum, n1x, server
from reflets.score import key_name
from reflets.write import midi_tpc

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def refuses_replacing(staff: int) -> None:
    info, *_ = await server.read_bars("all")
    first = info.measures[0].number
    if not any(event.pitch and event.staff == staff and event.layer == 1 for event in info.measures[0].events):
        return

    def recorded(play, starts):
        raise AssertionError("recorded")

    audio.record = recorded
    try:
        await server.hum(start_bar=first, staff=staff, bars=2)
        refused = "nothing raised"
    except ToolError as error:
        refused = str(error)
    except AssertionError:
        refused = "it recorded"
    check(f"bar {first} has notes: hum without replace asks first", "already has notes" in refused and "Ask the user" in refused, refused)


async def one(name: str, last: int, bars: int, tempo: float, grid: int, staff: int, kind: str) -> None:
    info, index, *_ = await server.read_bars("all")
    had_notes = any(event.pitch for measure in index.measures for event in measure.events)
    result = await server.hum(start_bar=last + 1, staff=staff, bars=bars, tempo=tempo, grid=grid, kind=kind)
    print(result.splitlines()[0])
    check(f"{name}: written and read back", "Read-back matched" in result and f"bars {last + 1}-{last + bars}" in result, result)
    written = n1x.decode(await server.read_score(f"{last + 1}-{last + bars}"))
    pitches = [midi_tpc(note.pitch)[0] for bar in written.bars for (s, _), voice in bar.voices.items() if s == staff
               for chord in voice.chords for note in chord.notes]
    instrument, staves = next((i, s) for (_, s), i in zip(info.parts, info.instrument_ids) if staff in s)
    target = hum.centre(instrument, staves.index(staff), len(staves))
    check(f"{name}: in the {instrument} register", bool(pitches) and abs(np.median(pitches) - target) <= 7, f"median {np.median(pitches) if pitches else None}, centre {target}")
    if had_notes:
        fifths = server.key_at(info, info.ticks[-1])
        scale = {(fifths * 7 + step) % 12 for step in hum.MAJOR_STEPS + [8]}
        outside = sorted({p % 12 for p in pitches} - scale)
        check(f"{name}: in the score's key", not outside, f"pitch classes {outside} outside ks={key_name(fifths)}")
    if kind == "rhythm":
        check(f"{name}: one pitch", len(set(pitches)) == 1, str(sorted(set(pitches))))
    proposal = re.search(r"proposal id: (p\d+)", result)
    if proposal:
        discarded = await server.discard(proposal[1])
        after = await server.load_info()
        check(f"{name}: discard removes the appended bars", after.measures[-1].number == last, discarded)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", nargs="?", type=Path, default=hum_takes.FOLDER)
    parser.add_argument("--mic", action="store_true")
    parser.add_argument("--staff", type=int, default=1)
    parser.add_argument("--rhythm", action="store_true")
    args = parser.parse_args()
    kind = "rhythm" if args.rhythm else "line"
    info = await server.load_info()
    last, meter = info.measures[-1].number, info.measures[-1].meter
    if args.mic:
        print("Hum 4 bars after the one-bar count-in, at 90.")
        await one("mic", last, 4, 90, 2, 1, "line")
    else:
        await refuses_replacing(args.staff)
        for path in sorted(args.folder.glob("*.wav")):
            recorded, meta = hum_takes.load(path)
            if meta["meter"] != meter:
                print(f"skip {path.stem}: {meta['meter']}, the score ends in {meter}")
                continue
            audio.record = lambda play, starts, recorded=recorded, meta=meta: audio.Take(recorded[: len(play)], meta["starts"], meta["gap"], "replay")
            audio.echo = lambda take, beats, meta=meta: meta["latency"]
            audio.store_latency = lambda folder, device, latency: None
            await one(path.stem, last, meta["bars"], meta["tempo"], meta["grid"], args.staff, kind)
    print("FAILED: " + ", ".join(failures) if failures else "ALL PASSED")


asyncio.run(main())
