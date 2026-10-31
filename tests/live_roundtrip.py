"""End-to-end check of writing N1x against a live MuseScore (docs/spec-core.md 4.3, 6.6).

Needs the bridge plugin running and a score open. From every bar, the shortest range of bars whose lines close inside
it is read and written three times with propose: back as read, which must change nothing; with a minus on every mark,
decoration and bar field but the meter and key, which must remove them all; then as read again, which must bring them
back. Each write is checked and the score must be as it was after the discards. The bare write empties every lyric
line. Glissandos cannot be created through the plugin API, so they are left out of the comparison and removed
explicitly ([-gliss]). Stem directions and beam modes, which N1x does not show, must stay as read. A range with
another element the plugin API cannot create is refused and skipped.

    REFLETS_TOKEN_FILE=... uv run python tests/live_roundtrip.py
"""

import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import n1x, server
from reflets.restore import VOICE, bare_idea, body, writable


def idea(lines: list[str], header: str, token) -> str:
    result = [header]
    for line in lines:
        match = VOICE.fullmatch(line)
        result.append(match[1] + " ".join(token(word) for word in n1x.TOKEN.findall(match[2])) if match else line)
    return "\n".join(result)


def as_read(word: str) -> str:
    return re.sub(r"(?<=[\[,])(gliss[\w-]*)", r"-\1", word) if not word.startswith("g") else word


def looks(lines: list[str]) -> list[tuple[str, ...]]:
    return sorted(tuple(line.split()[1:3] + [word for word in line.split()[4:-1] if word[0] in "SB"]) for line in lines if line.startswith("C "))


def bare(text: str) -> list[str]:
    left = []
    for bar in n1x.decode(text).bars:
        left += [f"m{bar.label}: {name}={value}" for name, value in bar.fields.items() if name not in ("len", "ts", "ks")]
        for cell, voice in bar.voices.items():
            left += [f"m{bar.label} {cell}: {token}" for _, token in voice.marks]
            left += [f"m{bar.label} {cell}: {chord.decorations}" for chord in voice.chords if chord.decorations and not chord.grace]
            left += [f"m{bar.label} {cell}: {note}" for chord in voice.chords for note in chord.notes if note.decorations]
            left += [f"m{bar.label} {cell}: rest {names}" for _, _, names in voice.rests if names]
            left += [f"m{bar.label} {cell} L{number}: {tokens}" for number, tokens in voice.lyrics.items()]
    return left


async def main() -> None:
    start = await server.read_score("all")
    info = await server.load_info()
    labels = info.labels
    failures = []
    for first, label in enumerate(labels):
        for last in labels[first:]:
            bars = f"{label}-{last}"
            text = await server.read_score(bars)
            header, lines = text.splitlines()[0], writable(text)
            last_index = labels.index(last)
            span = f"read {info.ticks[first]} {info.ticks[last_index + 1] if last_index + 1 < len(info.ticks) else 2**31 - 1}"
            drawn = looks(await server.request(span))
            try:
                same = await server.propose(idea(body(text), header, as_read), f"bars {bars} as read", replace=True)
            except ToolError as error:
                if "has no closer in the idea" in str(error) and last != labels[-1]:
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
                if looks(await server.request(span)) != drawn:
                    failures.append(f"bars {bars}: stem directions or beam modes changed when written back as read")
                written.append(await server.propose(bare_idea(lines, header), f"bars {bars} bare", replace=True))
                left = [item for item in bare(await server.read_score(bars)) if not n1x.is_line(item.split(": ", 1)[1])]
                if left:
                    failures.append(f"bars {bars}: the minuses left {left}")
                written.append(await server.propose("\n".join([header, *lines]), f"bars {bars} restored", replace=True))
                if looks(await server.request(span)) != drawn:
                    failures.append(f"bars {bars}: stem directions or beam modes did not come back")
                if writable(await server.read_score(bars)) != lines:
                    failures.append(f"bars {bars} did not come back:\n  {lines}\n  {writable(await server.read_score(bars))}")
            except ToolError as error:
                failures.append(f"bars {bars}: {error}")
            for result in reversed([same, *written]):
                await server.discard(re.search(r"proposal id: (p\d+)", result)[1])
            break
    if await server.read_score("all") != start:
        failures.append("the score is not as it was after the discards")
    print("\n".join(failures) or f"PASS every bar of {len(labels)} written as read, bare and restored")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
