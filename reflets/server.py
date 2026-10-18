"""The Reflets MCP server (docs/spec-core.md section 5). Slice 1: score_info and read_score."""

from __future__ import annotations

from engine import notes
from engine.score import PositionError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from reflets.bridge import Bridge, BridgeError
from reflets.score import ScoreInfo, build_index, parse_info

# Spec 4.4: estimate tokens as characters / 3.5; a default read over this returns the first bars only.
WHOLE_SCORE_TOKENS = 6000
FIRST_BARS = 16

mcp = MCPServer(
    "reflets",
    title="Reflets",
    instructions=(
        "Reflets connects you to the score open in the user's MuseScore Studio. Call score_info first, then "
        "read_score for the notes. Notes come in N1: one 'staff.voice:' line per voice per bar, a bare number "
        "sets the duration in div units per quarter note, '+' joins a chord, 'r' is a rest, a leading 'g' marks "
        "a grace note, a trailing '~' a tie. Pitches are sounding pitches with their spelling (Eb4, not D#4)."
    ),
)
bridge = Bridge()


def read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


async def load_info() -> ScoreInfo:
    try:
        _, lines = await bridge.request("info")
    except BridgeError as error:
        raise ToolError(str(error)) from None
    return parse_info(lines)


@mcp.tool(
    title="Score info",
    description=(
        "Use this first: whether MuseScore is connected, and the open score's title, parts with their staves, "
        "bar count, meter, key and pickup. If it says MuseScore is not reachable, tell the user what it says."
    ),
    annotations=read_only("Score info"),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,  # plain text only; a structured copy would double the tokens (spec 5.1)
)
async def score_info() -> str:
    try:
        _, lines = await bridge.request("info")
    except BridgeError as error:
        return str(error)
    info = parse_info(lines)
    hello = bridge.hello
    version = hello.get("mscore", "0").rjust(5, "0")
    parts = "; ".join(
        f"P{n} {name} (staff {staves[0]})" if len(staves) == 1 else f"P{n} {name} (staves {staves[0]}-{staves[-1]})"
        for n, (name, staves) in enumerate(info.parts, 1)
    )
    first, last = info.measures[0].number, info.measures[-1].number
    changes = f", key changes at {len(info.keys) - 1} bars" if len(info.keys) > 1 else ""
    return (
        f"MuseScore {int(version[:-4])}.{int(version[-4:-2])}.{int(version[-2:])}, "
        f"Reflets bridge {hello.get('plugin', '?').split('/')[-1]}, connected.\n"
        f'"{info.title}": {len(info.parts)} part(s): {parts}. Bars {first}-{last} '
        f"({'with' if first == 0 else 'no'} pickup), meter {info.measures[0].meter}, key {info.key}{changes}."
    )


@mcp.tool(
    title="Read the score",
    description=(
        "Use this to see the notes of the score open in MuseScore, as N1 text (see the server instructions). "
        'bars is "all" or a range like "5-12", numbered as MuseScore shows them, a pickup being bar 0. '
        f"A long score read as \"all\" returns the first {FIRST_BARS} bars and says how many there are; "
        "then read further ranges as needed."
    ),
    annotations=read_only("Read the score"),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,  # plain text only; a structured copy would double the tokens (spec 5.1)
)
async def read_score(bars: str = "all") -> str:
    info = await load_info()
    numbers = [measure.number for measure in info.measures]
    if bars.strip().lower() == "all":
        first, last, whole = numbers[0], numbers[-1], True
    else:
        try:
            start, _, end = bars.partition("-")
            first, last, whole = int(start), int(end or start), False
        except ValueError:
            raise ToolError(f'bars must be "all" or a range like "5-12", not {bars!r}') from None
    for number in (first, last):
        if number not in numbers:
            raise ToolError(f"Bar {number} does not exist; the score has bars {numbers[0]} to {numbers[-1]}")
    start_tick = info.ticks[numbers.index(first)]
    end_index = numbers.index(last) + 1
    end_tick = info.ticks[end_index] if end_index < len(info.ticks) else 2**31 - 1
    try:
        _, lines = await bridge.request(f"read {start_tick} {end_tick}")
    except BridgeError as error:
        raise ToolError(str(error)) from None
    index = build_index(info, lines, int(bridge.hello["division"]))
    try:
        text = notes.encode(index, first, last)
        if whole and len(text) / 3.5 > WHOLE_SCORE_TOKENS:
            cut = numbers[min(len(numbers) - 1, numbers.index(first) + FIRST_BARS - 1)]
            text = notes.encode(index, first, cut) + (
                f"\n(The score has bars {numbers[0]}-{numbers[-1]}; this is bars {first}-{cut}. "
                "Call read_score with a range for more.)"
            )
    except (notes.NotesError, PositionError) as error:
        raise ToolError(f"Could not encode bars {first}-{last}: {error}") from None
    return text


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
