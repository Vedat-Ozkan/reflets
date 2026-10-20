"""End-to-end check of reading N1x against a live MuseScore (docs/spec-core.md 4.2).

Needs the bridge plugin running and a score open: N1x with its extensions stripped must equal the engine's N1 of
the same score. With tests/data/bar-fields.mscz open, the bar fields must also be the expected ones; its markers,
jump and dashed bar line were added by hand, as MuseScore imports them from bar-fields.musicxml as staff text.

    REFLETS_TOKEN_FILE=... uv run python tests/live_read.py
"""

import asyncio
import re
import sys

from engine import notes

from reflets import n1x, server
from reflets.score import build_index

BAR_FIELDS_TITLE = "Reflets bar fields"
EXPECTED_BARS = [
    "m1 len=4 rep=start",
    "m2 len=4 rep=end x=3 volta=1",
    "m3 len=4 volta=2 bar=double",
    "m4 len=4 mark=segno",
    "m5 len=4 ks=2s bar=dashed break=line",
    "m6 len=3 ts=3/4",
    "m7 len=3 mark=tocoda",
    "m8 len=3 bar=double break=page jump=ds-al-coda",
    "m9 len=3 mark=coda",
    "m10 len=3 bar=final mark=fine",
]
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def strip(text: str) -> str:
    lines = text.splitlines()
    kept = [re.sub(r"^N1x ", "N1 ", lines[0])]
    for line in lines[1:]:
        if re.match(r'(title|composer)=|P\d+ "', line):
            continue
        if re.match(r"m\d+ ", line):
            words = line.split()
            line = " ".join([words[0], *(word for word in words[1:] if word.split("=")[0] in ("len", "ts"))])
        kept.append(line)
    return "\n".join(kept)


async def main() -> None:
    info = await server.load_info()
    _, lines = await server.bridge.request(f"read 0 {2**31 - 1}")
    index = build_index(info, lines, int(server.bridge.hello["division"]))
    numbers = [measure.number for measure in info.measures]
    first, last = numbers[0], numbers[-1]
    middle = numbers[len(numbers) // 2]
    for a, b in [(first, last), (1, min(4, last)), (middle, last)]:
        text = n1x.encode(info, index, a, b)
        check(f"bars {a}-{b}, stripped N1x equals N1", strip(text) == notes.encode(index, a, b))
    text = n1x.encode(info, index, first, last)
    print(text.split("\nm")[0])
    bars = [line for line in text.splitlines() if re.match(r"m\d+ ", line)]
    for line in bars:
        if len(line.split()) > 2:
            print("  " + line)
    if info.title == BAR_FIELDS_TITLE:
        check("bar fields", bars == EXPECTED_BARS, "\n".join(f"  got {g!r}, want {w!r}" for g, w in zip(bars, EXPECTED_BARS) if g != w))
    if failures:
        sys.exit(f"{len(failures)} failed")


if __name__ == "__main__":
    asyncio.run(main())
