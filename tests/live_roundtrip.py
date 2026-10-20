"""End-to-end check of writing N1x against a live MuseScore (docs/spec-core.md 4.3, 6.6).

Needs the bridge plugin running and a score open. From every bar, the shortest range of bars whose lines close inside
it is read, written back as read with propose, read again and discarded: each must land, read back as before and leave
the score as it was. Lyrics cannot be written yet, and glissandos cannot be written through the plugin API, so they
are left out of the ideas and of the comparison. A range with another element the plugin API cannot create is
refused and skipped.

    REFLETS_TOKEN_FILE=... uv run python tests/live_roundtrip.py
"""

import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import n1x, server


def unglissed(match: re.Match) -> str:
    names = [name for name in match[1].split(",") if not name.startswith("gliss")]
    return f"[{','.join(names)}]" if names else ""


def writable(text: str) -> list[str]:
    lines = [line for line in n1x.expand(text).splitlines() if re.match(r"m\d+ |\d+\.\d+:", line)]
    return [re.sub(r"\[([^\]\"]*)\]", unglissed, line) for line in lines]


async def main() -> None:
    start = await server.read_score("all")
    numbers = [measure.number for measure in (await server.load_info()).measures]
    failures = []
    for first, number in enumerate(numbers):
        for last in numbers[first:]:
            bars = f"{number}-{last}"
            text = await server.read_score(bars)
            idea = "\n".join([text.splitlines()[0], *writable(text)])
            try:
                result = await server.propose(idea, f"bars {bars} as read", replace=True)
            except ToolError as error:
                if "has no closer in the idea" in str(error) and last != numbers[-1]:
                    continue
                if "plugin API has no way" in str(error):
                    print(f"SKIP bars {bars}: {error}")
                else:
                    failures.append(f"bars {bars}: {error}")
                break
            after = await server.read_score(bars)
            if writable(after) != writable(text):
                failures.append(f"bars {bars} read back differently:\n  {writable(text)}\n  {writable(after)}")
            await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
            break
    if await server.read_score("all") != start:
        failures.append("the score is not as it was after the discards")
    print("\n".join(failures) or f"PASS every bar of {len(numbers)} written back as read")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
