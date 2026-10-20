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
1.1: 6 G5~ ) 6 G5 gAb5 4 Bb5 2 Ab5 6 G5
m6 len=24
1.1: 2 F5 Eb5 D5 gC5 gD5 10 Eb5 8 r
1.2: 12 r 12 Bb4"""
LATER = """N1 div=4 ts=12/8 ks=3f
m10 len=24
1.2: 24 Eb4"""
GROUPS = {
    "tuplets with a rest inside": ("N1x div=48\nm10 len=288\n1.2: 3:2{ 16 r D4 E4 } 48 F4 3:2{ 32 G4 16 r } 144 r", "1.2: 3:2{ 8 r D4 E4 } 24 F4 3:2{ 16 G4 8 r }"),
    "nested tuplets": ("N1x div=144\nm10 len=864\n1.2: 3:2{ 96 C4 D4 3:2{ 32 E4 F4 G4 } }", "1.2: 3:2{ 48 C4 D4 3:2{ 16 E4 F4 G4 } }"),
    "grace chords": ("N1x div=48\nm10 len=288\n1.2: gC4+E4 48 G4 gD4 gF4+A4 B4", "1.2: gC4+E4 8 G4 gD4 gF4+A4 B4"),
    "decorations": (
        "N1x div=4\nm10 len=24\n1.2: [stacc]{ 2 C4 D4 E4 } F4[acc,fermata] gG4[appog] A4:paren+C5'2[arp] B4[trem16] 4 r[fermata] 8 r",
        "1.2: [stacc]{ 4 C4 D4 E4 } F4[acc,fermata] gG4[appog] A4:paren+C5'2[arp] B4[trem16] [fermata]@24",
    ),
    "references": ("N1x div=48\nm10 len=288\n1.2: 48 C4 D4 E4 F4 G4 A4\nm11 len=288\n1.2 = m10", "1.2 = m10"),
}
MARKS = {
    "marks with notes": ("N1x div=4\nm5 len=24\n1.1: !f \"Eb\" x\"dolce\" 6 G5 ) q50 Ab5 !p 12 Bb5", "5", ['x"dolce"', "!f", '"Eb"', "q50", "!p"]),
    "a marks-only line": ("N1x div=4\nm10 len=24\n2.1: s\"marks only\"@4 clef=treble@12", "10", ['s"marks only"', "clef=treble"]),
}
failures = []
start = ""


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
    text = await server.read_score("all")
    check(name + ", score equals the reference", strip(text.strip()) == REFERENCE)
    check(name + ", marks and lines as at the start", text == start)


def proposal(result: str) -> str:
    return re.search(r"proposal id: (p\d+)", result).group(1)


async def main() -> None:
    global start
    start = await server.read_score("all")
    await unchanged("start")
    error = await refused(server.propose(IDEA, "test"))
    check("propose over notes without replace is refused", "replace=True" in error, error)

    first = await server.propose(IDEA, "test", replace=True)
    check("propose writes and reads back", "Read-back matched" in first and "3 grace notes" in first, first)
    bars = await server.read_score("5-6")
    check("bars 5-6 hold the idea", "3 G5~ ) G5 gAb5 2 Bb5 1 Ab5 3 G5" in bars and "!p" in bars and 'x"cresc."' in bars and "1.2: 6 r Bb4" in bars, bars)
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

    for name, (idea, expected) in GROUPS.items():
        written = proposal(await server.propose(idea, name))
        bars = await server.read_score("10-11")
        check(f"{name} read back as written", expected in bars, bars)
        await server.discard(written)
    await unchanged("after the tuplets, grace chords and references")
    sung = proposal(await server.propose('N1x div=48\nm10 len=288\n1.2: 48 C4 D4 E4 F4 G4 A4\n1.2 L1: Hel- lo _ "my dear" * end', "lyrics"))
    bars = await server.read_score("10")
    check("lyrics read back as written", '1.2 L1: Hel- lo _ "my dear" * end' in bars, bars)
    result = await server.propose("N1x div=48\nm10 len=288\n1.2: 72 C4 24 D4 48 E4 F4 G4 A4", "lyrics kept", replace=True)
    bars = await server.read_score("10")
    check("a new rhythm keeps each syllable at its moment", '1.2 L1: Hel- * * "my dear" * end' in bars, bars)
    check("a syllable left without a note is named", "lo at 48" in result, result)
    await server.discard(proposal(result))
    await server.discard(sung)
    await unchanged("after the lyrics")
    tie = proposal(await server.propose("N1x div=48\nm10 len=288\n1.2: 240 C4 48 F4~\nm11 len=288\n1.2: 48 F4 240 r", "tie", replace=True))
    result = await server.propose("N1x div=48\nm11 len=288\n1.2: 96 F4 192 r", "tie kept", replace=True)
    bars = await server.read_score("10")
    check("a tie from the bar before is kept when the bar is rewritten alone", "F4~" in bars and "was cut" not in result, f"{bars}\n{result}")
    await server.discard(proposal(result))
    result = await server.propose("N1x div=48\nm11 len=288\n1.2: 96 G4 192 r", "tie cut", replace=True)
    check("a tie from the bar before that cannot stay is named", "bar(s) 10 was cut" in result, result)
    await server.discard(proposal(result))
    await server.discard(tie)
    await unchanged("after the ties")
    error = await refused(server.propose("N1x div=48\nm11 len=288\n1.2 = m10", "bad"))
    check("a reference to a bar outside the idea is refused", "written out earlier" in error, error)
    error = await refused(server.propose("N1x div=48\nm10 len=288\n1.2: <( 288 r", "unclosed"))
    check("a line with no closer in the idea is refused", "has no closer" in error, error)
    error = await refused(server.propose("N1x div=48\nm10 len=288\n1.2: 288 r <)@96", "stray"))
    check("a closer with no line to close is refused", "closes no line" in error, error)
    written = proposal(await server.propose(IDEA.replace("G5~ ) ", "G5~ "), "dropped", replace=True))
    bars = await server.read_score("5")
    check("leaving out the end of a slur from bar 4 keeps it", "G5~ ) G5" in bars, bars)
    await server.discard(written)
    written = proposal(await server.propose("N1x div=48\nm10 len=288\n1.2: ( 48 C4 (2 D4 ) E4 )2 F4 96 G4", "crossing slurs"))
    bars = await server.read_score("10")
    check("crossing slurs read back numbered", "1.2: (2 8 C4 ( D4 )2 E4 ) F4 16 G4" in bars, bars)
    await server.discard(written)

    written = proposal(await server.propose("N1x div=4\nm5 len=24\n1.1: 24 G5", "a new rhythm", replace=True))
    bar = next(line for line in (await server.read_score("5")).splitlines() if line.startswith("1.1:"))
    check("a new rhythm keeps the bar's marks once and ends the slur on its note", bar.count("!p") == 1 and "G5 )" in bar, bar)
    await server.discard(written)
    written = proposal(await server.propose("N1x div=4\nm5 len=24\n1.1: -!p", "remove p"))
    bar = next(line for line in (await server.read_score("5")).splitlines() if line.startswith("1.1:"))
    check("a minus removes a mark", "!p" not in bar, bar)
    await server.discard(written)
    notes_before = strip(await server.read_score("10"))
    for name, (idea, bar, tokens) in MARKS.items():
        written = proposal(await server.propose(idea, name, replace=True))
        text = await server.read_score(bar)
        check(f"{name} read back as written", all(token in text for token in tokens), text)
        if bar == "10":
            check("a marks-only line leaves the notes", strip(text) == notes_before, text)
        await server.discard(written)
    await unchanged("after the marks")
    error = await refused(server.propose("N1x div=4\nm5 len=24\n2.1: q60 24 Eb2", "bad", replace=True))
    check("a tempo outside 1.1 is refused", "system mark" in error, error)

    tick = (await server.load_info()).ticks[5]
    error = await refused(server.request(f"write {tick} {tick + 2880} rollback\nv 0 {tick}\nd 3/2\nn {tick} 67:15\n~ 0 {tick} 99"))
    check("a failing write reports write-failed", "write-failed" in error, error)
    await unchanged("after the failed write")
    sys.exit(1 if failures else 0)


asyncio.run(main())
