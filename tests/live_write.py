import asyncio
import re
import sys
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from live_read import strip
from reflets import server

REFERENCE = (Path(__file__).parent.parent / "research/encoding-tokens/chopin.n1.txt").read_text().strip()
IDEA = """N1 div=4 ts=12/8 ks=3f
m5 len=24
1.1: 6 G5~ 6 G5 gAb5 4 Bb5 2 Ab5 6 G5
m6 len=24
1.1: 2 F5 Eb5 D5 gC5 gD5 10 Eb5 8 r
1.2: 12 r 12 Bb4"""
LATER = """N1 div=4 ts=12/8 ks=3f
m10 len=24
1.2: 24 Eb4"""
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


async def unchanged(name: str) -> None:
    check(name + ", score equals the reference", strip((await server.read_score("all")).strip()) == REFERENCE)


def proposal(result: str) -> str:
    return re.search(r"proposal id: (p\d+)", result).group(1)


async def main() -> None:
    await unchanged("start")
    error = await refused(server.propose(IDEA, "test"))
    check("propose over notes without replace is refused", "replace=True" in error, error)

    first = await server.propose(IDEA, "test", replace=True)
    check("propose writes and reads back", "Read-back matched" in first and "3 grace notes" in first, first)
    bars = await server.read_score("5-6")
    check("bars 5-6 hold the idea", "1.1: !p 3 G5~ ) G5 gAb5 2 Bb5 1 Ab5 3 G5" in bars and "1.2: 6 r Bb4" in bars, bars)
    check("discard", "Discarded" in await server.discard(proposal(first)))
    await unchanged("after discard")

    older = proposal(await server.propose(IDEA, "older", replace=True))
    newer = proposal(await server.propose(LATER, "newer"))
    error = await refused(server.discard(older))
    check("discard of an idea that is not the last undo step is refused and redone", "redone" in error, error)
    check("the newer idea is still there", "1.2: 48 Eb4" in await server.read_score("10"))
    await server.discard(newer)
    await server.discard(older)
    await unchanged("after both discards")

    kept = proposal(await server.propose(IDEA, "kept", replace=True))
    check("keep", "black" in await server.keep(kept))
    error = await refused(server.discard(kept))
    check("discard after keep is refused", "no open proposal" in error, error)
    await server.request("undo")
    await server.request("undo")
    await unchanged("after undoing keep and the idea")

    tick = (await server.load_info()).ticks[5]
    error = await refused(server.request(f"write {tick} {tick + 2880} rollback\nv 0 {tick}\nd 3/2\nn {tick} 67:15\n~ 0 {tick} 99"))
    check("a failing write reports write-failed", "write-failed" in error, error)
    await unchanged("after the failed write")
    sys.exit(1 if failures else 0)


asyncio.run(main())
