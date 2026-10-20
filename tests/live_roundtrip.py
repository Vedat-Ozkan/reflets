"""End-to-end check of writing N1x against a live MuseScore (docs/spec-core.md 4.3, 6.6).

Needs the bridge plugin running and a score open. From every bar, the shortest range of bars whose lines close inside
it is read and written three times with propose: back as read, which must change nothing; with a minus on every mark
and decoration, which must remove them all; then as read again, which must bring them back. Each write is checked and
the score must be as it was after the discards. Lyrics cannot be written yet and glissandos cannot be created through
the plugin API, so they are left out of the comparison and glissandos are removed explicitly ([-gliss]). A range with
another element the plugin API cannot create is refused and skipped.

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


def unlyrical(text: str) -> list[str]:
    return [line for line in n1x.expand(text).splitlines() if re.match(r"m\d+ |\d+\.\d+:", line)]


def writable(text: str) -> list[str]:
    return [re.sub(r"\[([^\]\"]*)\]", unglissed, line) for line in unlyrical(text)]


def idea(lines: list[str], header: str, token) -> str:
    result = [header]
    for line in lines:
        match = VOICE.fullmatch(line)
        result.append(match[1] + " ".join(token(word) for word in n1x.TOKEN.findall(match[2])) if match else line)
    return "\n".join(result)


def as_read(word: str) -> str:
    return re.sub(r"(?<=[\[,])(gliss[\w-]*)", r"-\1", word) if not word.startswith("g") else word


def removed(word: str) -> str:
    body = re.sub(r"@\d+$", "", word)
    if n1x.is_line(body) or word.startswith("g") or word.isdigit() or word == "}":
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
            left += [f"m{bar.number} {cell}: {token}" for _, token in voice.marks if not n1x.is_line(token)]
            left += [f"m{bar.number} {cell}: {chord.decorations}" for chord in voice.chords if chord.decorations and not chord.grace]
            left += [f"m{bar.number} {cell}: {note}" for chord in voice.chords for note in chord.notes if note.decorations]
            left += [f"m{bar.number} {cell}: rest {names}" for _, _, names in voice.rests if names]
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
                same = await server.propose(idea(unlyrical(text), header, as_read), f"bars {bars} as read", replace=True)
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
                written.append(await server.propose(idea(lines, header, removed), f"bars {bars} bare", replace=True))
                left = bare(await server.read_score(bars))
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
