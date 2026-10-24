import asyncio
import os
import re
import sys

from reflets import server

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def main() -> None:
    info = await server.load_info()
    first = info.measures[1].number
    bars = f"{first}-{first + 1}"
    report = await server.analyze(bars)
    chords = re.findall(r"^m(\d+) b[\d.]+ \|", report, re.M)
    check("the draft lists chords in the range only", chords and {int(bar) for bar in chords} <= {first, first + 1}, report)
    check("the notes table comes first", report.index(f"\nm{first}\n") < report.index("CHORDS:"), report)
    python = os.environ.pop("ANALYSISGNN_PYTHON")
    report = await server.analyze(bars)
    check("without the model, the table and the reason", f"\nm{first}\n" in report and "AnalysisGNN model is not installed (ANALYSISGNN_PYTHON and ANALYSISGNN_CHECKPOINT are not set)" in report, report)
    os.environ["ANALYSISGNN_PYTHON"] = python
    sys.exit(1 if failures else 0)


asyncio.run(main())
