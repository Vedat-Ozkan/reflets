"""End-to-end check of writing N1x against a live MuseScore (docs/spec-core.md 4.3, 6.6).

Needs the bridge plugin running and a score open. Every bar is read, written back as read with propose, read again
and discarded: each must land, read back as before and leave the score as it was. Lines and lyrics cannot be written
yet, so they are left out of the ideas and of the comparison; a slur that ends on a grace note or inside a tuplet of
a rewritten voice is lost until lines can be written. A bar with an element the plugin API cannot create, such as a
glissando, is refused and skipped.

    REFLETS_TOKEN_FILE=... uv run python tests/live_roundtrip.py
"""

import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import n1x, server

LINE = re.compile(r' [a-z0-9<>-]*("(?:[^"\\]|\\.)*")?[()](@\d+)?(?= |$)')


def without_lines(text: str) -> list[str]:
    return [LINE.sub("", line) for line in n1x.expand(text).splitlines() if re.match(r"m\d+ |\d+\.\d+:", line)]


async def main() -> None:
    start = await server.read_score("all")
    numbers = [measure.number for measure in (await server.load_info()).measures]
    failures = []
    for number in numbers:
        text = await server.read_score(str(number))
        idea = "\n".join([text.splitlines()[0], *without_lines(text)])
        try:
            result = await server.propose(idea, f"bar {number} as read", replace=True)
        except ToolError as error:
            if "plugin API has no way" in str(error):
                print(f"SKIP bar {number}: {error}")
            else:
                failures.append(f"bar {number}: {error}")
            continue
        after = await server.read_score(str(number))
        if without_lines(after) != without_lines(text):
            failures.append(f"bar {number} reads back differently:\n  {without_lines(text)}\n  {without_lines(after)}")
        await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
    if await server.read_score("all") != start:
        failures.append("the score is not as it was after the discards")
    print("\n".join(failures) or f"PASS {len(numbers)} bars written back as read")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
