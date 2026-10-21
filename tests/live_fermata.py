import asyncio
import re
import sys

from reflets import server

CASES = {
    "a held note over the fermata's beat takes the fermata": ("1.1: 8 C5", "1.1: 8 C5[fermata]", "moved onto the note or rest sounding at their moment: m1 1.1 [fermata] from 4 to 0"),
    "a held note from a later beat takes it too": ("1.1: 2 C5 6 D5", "1.1: 2 C5 6 D5[fermata]", "[fermata] from 4 to 2"),
    "a fermata the idea writes on that note is not doubled": ("1.1: 8 C5[fermata]", "1.1: 8 C5[fermata]", "were removed, as the note or rest sounding at their moment has its own or none sounds there: m1 1.1 [fermata] at 4"),
    "a fermata over the filled silence at the end is removed and named": ("1.1: 2 C5", "1.1: 2 C5", "none sounds there: m1 1.1 [fermata] at 4"),
    "a fermata the idea removes is not named": ("1.1: 8 C5 -[fermata]@4", "1.1: 8 C5", None),
    "a note on the fermata's beat keeps it": ("1.1: 4 C5 C5", "1.1: 4 C5 C5[fermata]", None),
    "a removal on a kept fermata removes it": ("1.1: 4 C5 C5 -[fermata]@4", "1.1: 4 C5 C5", None),
}
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def main() -> None:
    start = await server.read_score("1")
    check("bar 1 of bwv66.6 has a fermata on beat 3 of 1.1", "1.1: 2 A4 B4 C#5[fermata] E5" in start, start)
    for name, (line, expected, named) in CASES.items():
        result = await server.propose(f"N1x div=2\nm1 len=8\n{line}", "fermata", replace=True)
        bar = await server.read_score("1")
        check(name, expected in bar.splitlines() and ((named in result) if named else "fermatas" not in result), f"{result}\n{bar}")
        await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
    check("the bar is as before", await server.read_score("1") == start)
    sys.exit(1 if failures else 0)


asyncio.run(main())
