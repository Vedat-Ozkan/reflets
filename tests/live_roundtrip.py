"""End-to-end check of writing N1x against a live MuseScore (docs/spec-core.md 4.3, 6.6).

Needs the bridge plugin running and a score open. From every bar, the shortest range of bars whose lines close inside
it is read and written three times with propose: back as read, which must change nothing; with a minus on every mark
and decoration, which must remove them all; then as read again, which must bring them back. Each write is checked and
the score must be as it was after the discards. The bare write empties every lyric line. Glissandos cannot be created
through the plugin API, so they are left out of the comparison and removed explicitly ([-gliss]). A range with another
element the plugin API cannot create is refused and skipped.

    REFLETS_TOKEN_FILE=... uv run python tests/live_roundtrip.py
"""

import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import n1x, server

VOICE = re.compile(r"(\d+\.\d+: )(.*)")


def unglissed(match: re.Match) -> str:
    names = [name for name in match[1].split(",") if not name.removeprefix("-").startswith("gliss")]
    return f"[{','.join(names)}]" if names else ""


def body(text: str) -> list[str]:
    return [line for line in n1x.expand(text).splitlines() if re.match(r"m\d+ |\d+\.\d+( L\d+)?:", line)]


def writable(text: str) -> list[str]:
    return [re.sub(r"\[([^\]\"]*)\]", unglissed, line) for line in body(text)]


def idea(lines: list[str], header: str, token) -> str:
    result = [header]
    for line in lines:
        match = VOICE.fullmatch(line)
        result.append(match[1] + " ".join(token(word) for word in n1x.TOKEN.findall(match[2])) if match else line)
    return "\n".join(result)


def as_read(word: str) -> str:
    return re.sub(r"(?<=[\[,])(gliss[\w-]*)", r"-\1", word) if not word.startswith("g") else word


def closed(lines: list[str]) -> set[tuple[int, int]]:
    stacks: dict[tuple[str, str], list[tuple[int, int]]] = {}
    found = set()
    for row, line in enumerate(lines):
        match = VOICE.fullmatch(line)
        for column, word in enumerate(n1x.TOKEN.findall(match[2]) if match else []):
            body = re.sub(r"@\d+$", "", word)
            token = n1x.LINE_TOKEN.fullmatch(body)
            if not token:
                continue
            stack = stacks.setdefault((match[1], token[1] + token[4]), [])
            if token[3] == "(":
                stack.append((row, column))
            elif stack:
                found |= {stack.pop(), (row, column)}
    return found


def bare_idea(lines: list[str], header: str) -> str:
    lines_closed = closed(lines)
    result = [header]
    for row, line in enumerate(lines):
        match = VOICE.fullmatch(line)
        if not match:
            result.append(line.split(":")[0] + ":" if " L" in line else line)
            continue
        words = n1x.TOKEN.findall(match[2])
        result.append(match[1] + " ".join(
            ("-" + word if (row, column) in lines_closed else word) if n1x.is_line(re.sub(r"@\d+$", "", word)) else removed(word)
            for column, word in enumerate(words)
        ))
    return "\n".join(result)


def removed(word: str) -> str:
    if word.startswith("g") or word.isdigit() or word == "}":
        return word
    word = re.sub(r"(?<=[\[,])(?!-)", "-", word)
    if word.endswith("{"):
        return word
    if re.match(r"[A-G]", word):
        return re.sub(r":(?!-)(?=[A-Za-z])", ":-", word)
    return word if word.startswith(("[", "r", "-")) else "-" + word


def bare(text: str) -> list[str]:
    left = []
    for bar in n1x.decode(text).bars:
        for cell, voice in bar.voices.items():
            left += [f"m{bar.number} {cell}: {token}" for _, token in voice.marks]
            left += [f"m{bar.number} {cell}: {chord.decorations}" for chord in voice.chords if chord.decorations and not chord.grace]
            left += [f"m{bar.number} {cell}: {note}" for chord in voice.chords for note in chord.notes if note.decorations]
            left += [f"m{bar.number} {cell}: rest {names}" for _, _, names in voice.rests if names]
            left += [f"m{bar.number} {cell} L{number}: {tokens}" for number, tokens in voice.lyrics.items()]
    return left


async def main() -> None:
    start = await server.read_score("all")
    numbers = [measure.number for measure in (await server.load_info()).measures]
    failures = []
    for first, number in enumerate(numbers):
        for last in numbers[first:]:
            bars = f"{number}-{last}"
            text = await server.read_score(bars)
            header, lines = text.splitlines()[0], writable(text)
            try:
                same = await server.propose(idea(body(text), header, as_read), f"bars {bars} as read", replace=True)
            except ToolError as error:
                if "has no closer in the idea" in str(error) and last != numbers[-1]:
                    continue
                if "plugin API" in str(error):
                    print(f"SKIP bars {bars}: {error}")
                else:
                    failures.append(f"bars {bars}: {error}")
                break
            written = []
            try:
                if writable(await server.read_score(bars)) != lines:
                    failures.append(f"bars {bars} changed when written back as read")
                written.append(await server.propose(bare_idea(lines, header), f"bars {bars} bare", replace=True))
                left = [item for item in bare(await server.read_score(bars)) if not n1x.is_line(item.split(": ", 1)[1])]
                if left:
                    failures.append(f"bars {bars}: the minuses left {left}")
                written.append(await server.propose("\n".join([header, *lines]), f"bars {bars} restored", replace=True))
                if writable(await server.read_score(bars)) != lines:
                    failures.append(f"bars {bars} did not come back:\n  {lines}\n  {writable(await server.read_score(bars))}")
            except ToolError as error:
                failures.append(f"bars {bars}: {error}")
            for result in reversed([same, *written]):
                await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
            break
    if await server.read_score("all") != start:
        failures.append("the score is not as it was after the discards")
    print("\n".join(failures) or f"PASS every bar of {len(numbers)} written as read, bare and restored")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
