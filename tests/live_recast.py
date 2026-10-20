import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import server

IDEA = """N1x div=2 ts=4/4 ks=0
m2 len=12 ts=12/8
1.1: q180 1 B4 C5 D5 E5 G4 A4 B4 C5 D5 E5 G4 A4
m3 len=12
1.1: 1 D5 E5 G4 A4 B4 C5 D5 E5 G4 [stacc]{ A4 B4 C5 }
m4 len=8 ts=4/4
1.1: q120"Allegro"@0"""
EXPECTED = [
    "m2 len=12 ts=12/8",
    "1.1: q180 !p ( 1 B4 C5 D5 ) E5 G4 A4 !f B4 C5 D5 E5 G4 A4",
    "1.1 L1: ta ki ta ta ki ta",
    "m3 len=12",
    "1.1: <( 1 D5 E5 G4 A4 B4 C5 D5 E5 G4 <) [stacc]{ A4 B4 C5 }",
    "m4 len=8 ts=4/4",
    '1.1: q120"Allegro" 2 C5 B4 A4 G4',
    "1.1 L1: la la la la",
]
SHORTER = "N1x div=3 ts=4/4 ks=0\nm2 len=9 ts=3/4\n1.1: 3:2{ 1 B4 C5 D5 } 3:2{ E5 G4 A4 } 3:2{ B4 C5 D5 }"
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def refused(coro) -> str:
    try:
        await coro
    except ToolError as error:
        return str(error)
    return ""


async def main() -> None:
    start = await server.read_score("all")
    error = await refused(server.propose(IDEA, "no flag", replace=True))
    check("a meter of another length over notes without recast=True is refused", "recast=True" in error, error)
    result = await server.propose(IDEA, "recast", replace=True, recast=True)
    check("the recast reads back as written", "Read-back matched" in result, result)
    text = await server.read_score("2-4")
    lines = [line for line in text.splitlines() if re.match(r"m\d|1\.1", line)]
    check("marks, lines and lyrics keep their place in the beat", lines == EXPECTED, "\n".join(lines))
    await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
    check("discard restores the score", await server.read_score("all") == start)
    error = await refused(server.propose(SHORTER, "shorter", replace=True, recast=True))
    check("a recast into a shorter meter is refused", "only lengthen" in error, error)
    error = await refused(server.propose(IDEA.replace("m3 len=12\n1.1: 1 D5 E5 G4 A4 B4 C5 D5 E5 G4 [stacc]{ A4 B4 C5 }\n", ""), "gap", replace=True, recast=True))
    check("a recast must write every bar up to its end", "without gaps" in error, error)
    check("the score is as at the start", await server.read_score("all") == start)
    sys.exit(1 if failures else 0)


asyncio.run(main())
