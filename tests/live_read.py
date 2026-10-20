"""End-to-end check of reading N1x against a live MuseScore (docs/spec-core.md 4.2).

Needs the bridge plugin running and a score open: N1x with its extensions stripped must equal the engine's N1 of
the same score, both decoded and re-encoded by the engine, which merges the rests N1x splits at tuplet edges.
With tests/data/bar-fields.mscz open, the bar fields must also be the expected ones; its markers,
jump and dashed bar line were added by hand, as MuseScore imports them from bar-fields.musicxml as staff text.
With tests/data/marks.mscz open, the marks must be the expected ones; its expression, system text, playing
technique, "Dm7" and "sempre" were added by hand to the import of marks.musicxml. With
tests/data/system-marks.mscz open, tempo, rehearsal mark, system text, segno, D.C. and the rit. line must appear once
although the violin also shows system markings; those, the system text, segno, D.C. and rit. were added by hand. With
tests/data/decorations.mscz open, the decorations must be the expected ones; it is the import of
decorations.musicxml. With tests/data/groups.mscz open, the tuplets and decoration groups must be the expected
ones; it is the import of groups.musicxml with the triplet inside bar 5's triplet added by hand (Ctrl+3 on E5), as
MuseScore imports nested tuplets wrongly. With tests/data/lines.mscz open, the lines must be the expected ones; it
is the import of lines.musicxml with the rit. line on bar 4 and the cresc. line on bar 3 added by hand; the
wavy glissando of the import reads straight once saved and reopened. With tests/data/lyrics.mscz open, the import of
lyrics.musicxml, the lyrics must be the expected ones. With tests/data/repeats.mscz open, the import of
repeats.musicxml, bars and voices that repeat an earlier one must be written as references, and the stripped N1x is
compared after the references are expanded.

    REFLETS_TOKEN_FILE=... uv run python tests/live_read.py
"""

import asyncio
import re
import sys

from engine import notes

from reflets import n1x, server
from reflets.score import build_index

BAR_FIELDS_TITLE = "Reflets bar fields"
EXPECTED_BARS = [
    "m1 len=4 rep=start",
    "m2 len=4 rep=end x=3 volta=1",
    "m3 len=4 volta=2 bar=double",
    "m4 len=4 mark=segno",
    "m5 len=4 ks=2s bar=dashed break=line",
    "m6 len=3 ts=3/4",
    "m7 len=3 mark=tocoda",
    "m8 len=3 bar=double break=page jump=ds-al-coda",
    "m9 len=3 mark=coda",
    "m10 len=3 mark=fine",
]
MARKS_TITLE = "Reflets marks"
EXPECTED_MARKS = """m1 len=8
1.1: q120"Allegro" R"A" !mf "C" 8 C5 "G7"@4
2.1: 4 C3 G2
m2 len=8
1.1: x"dolce" 2 E5 s"legato" "Dm7" D5 !p C5 D5
2.1: 4 C3 clef=treble E4
m3 len=8
1.1: S"Tutti" 1 C5 D5 E5 F5 s"pizz." 4 G5
2.1: fb"6/4" 8 C4
m4 len=8
1.1: !f 4 r s"tacet"@2 q60 pt"arco" 2 C5 !pp@6
2.1: clef=bass s"sempre" 8 C3"""
SYSTEM_MARKS_TITLE = "Reflets system marks"
EXPECTED_SYSTEM_MARKS = """m1 len=4
1.1: q120"Allegro" R"A" 4 C5
2.1: 4 G4
3.1: 4 C3
m2 len=4 jump=dc mark=segno
1.1: S"Tutti" tempo"rit."( 4 C5 tempo)
2.1 = m1
3.1 = m1"""
DECORATIONS_TITLE = "Reflets decorations"
EXPECTED_DECORATIONS = """m1 len=8
1.1: 2 C5[stacc] D5[ten] E5[acc] F5[marc]
2.1: 8 C3
m2 len=8
1.1: 2 G5[staccis] C5+E5+G5[arp] A5[mord] B5[tr]
2.1 = m1
m3 len=8
1.1: 4 C6[fermata,breath] 2 D5[turn] E5[trem32]
2.1 = m1
m4 len=8
1.1: gD5[appog] 2 C5 C4'1+E4'3+G4'5 F5 A4[head=x]
2.1 = m1
m5 len=8
1.1: 4 G4[caesura] E5[lv]
2.1 = m1
m6 len=8
1.1: gD5 gE5 2 C5 2 r[fermata] C4:lv+E4:paren[arp]
2.1 = m1
m7 len=8
1.1: 1 C5 D5 B3[staff+1] A3[staff+1] 2 C5+E5:head=diamond E5'2
2.1 = m1"""
GROUPS_TITLE = "Reflets groups"
EXPECTED_GROUPS = """m1 len=360
1.1: 3:2{ 30 C5 D5 E5 } [stacc]{ 45 F5 G5 A5 B5 } 90 C6
m2 len=360
1.1: 3:2{ 30 C5 30 r E5 } 45 F5[stacc] G5[stacc] 90 r A5
m3 len=360
1.1: 3:2{ 15 C5 D5 E5 } 3:2{ F5 G5 A5 } 3:2{ C5 D5 E5 F5 G5 A5 } 5:4{ 18 C5 D5 E5 F5 G5 } 90 C6
m4 len=360
1.1: 3:2[acc]{ 60 C5 D5 E5 } 3:2{ 30 C5 60 r } 45 r D5
m5 len=360
1.1: 3:2{ 60 C5 D5 3:2{ 20 E5 40 r } } 180 C6
m6 len=360
1.1: 3:2{ 30 r D5 E5 } 90 F5 G5 3:2{ 30 C5 60 r }"""
LINES_TITLE = "Reflets lines"
EXPECTED_LINES = """m1 len=4
1.1: ( <( 1 C5 D5 E5 <) F5 )
2.1: ped( 4 C3
m2 len=4
1.1: 8va( >( 1 G5 A5 >) ( B5 C6 8va)
2.1: 4 C3 ped)
m3 len=4
1.1: line"sempre legato"( 1 C6 D6 ) tr( 2 E5 line)
2.1: cresc( 4 C3 cresc)
m4 len=4
1.1: tempo"rit."( 2 C5[gliss] tr) G5 tempo)
2.1: 4 C3
m5 len=4
1.1: line"rit."( 4 C5 line)
2.1: ped( 4 C3 ped)@2"""
LYRICS_TITLE = "Reflets lyrics"
EXPECTED_LYRICS = """m1 len=4
1.1: 1 C5 D5 E5 F5
1.1 L1: Twin- kle lit- tle
1.1 L2: Ah vous di- rai
m2 len=4
1.1: 1 G5 A5 B5
1.1 L1: star _ _
m3 len=4
1.1: 1 C5 D5 E5 F5~
1.1 L1: won- * der what
m4 len=4
1.1: 2 F5 gA5 1 G5
1.1 L1: _ "you are"
m5 len=4
1.1: 2 C5 D5
1.1 L1: high up
1.2: 4 A4
1.2 L1: Oo"""
REPEATS_TITLE = "Reflets repeats"
EXPECTED_REPEATS = """m1 len=4
1.1: 1 C5 D5 E5 F5
2.1: 4 C3
m2 = m1
m3 len=4
1.1 = m1
2.1: 4 G2
m4 len=4
1.1 = m1
2.1 = m3
m5 len=4
1.1: !p 1 C5 D5 E5 F5
2.1 = m1
m6 len=4 rep=end
1.1 = m1
2.1 = m1"""
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def normal(text: str) -> str:
    return notes.encode(notes.decode(text))


def decoded_notes(text: str) -> dict[tuple[int, int, int], list[tuple]]:
    result: dict[tuple[int, int, int], list[tuple]] = {}
    for bar in n1x.decode(text).bars:
        for (staff, layer), voice in bar.voices.items():
            for chord in voice.chords:
                for note in chord.notes:
                    result.setdefault((bar.number, staff, layer), []).append((chord.onset, chord.grace, chord.duration, note.pitch, note.tied))
    return {key: sorted(value) for key, value in result.items()}


def index_notes(index, first: int, last: int) -> dict[tuple[int, int, int], list[tuple]]:
    result: dict[tuple[int, int, int], list[tuple]] = {}
    for measure in index.measures:
        if first <= measure.number <= last:
            for event in measure.events:
                if event.pitch:
                    result.setdefault((measure.number, event.staff, event.layer), []).append((event.onset, event.grace, event.duration, event.pitch, event.tied))
    return {key: sorted(value) for key, value in result.items()}


def strip(text: str) -> str:
    lines = n1x.expand(text).splitlines()
    kept = [re.sub(r"^N1x ", "N1 ", lines[0])]
    for line in lines[1:]:
        if re.match(r'(title|composer)=|P\d+ "|\d+\.\d+ L\d+:', line):
            continue
        if re.match(r"m\d+ ", line):
            words = line.split()
            line = " ".join([words[0], *(word for word in words[1:] if word.split("=")[0] in ("len", "ts"))])
        else:
            line = re.sub(r' [a-z0-9<>-]*("(?:[^"\\]|\\.)*")?[()]\d*(@\d+)?(?= |$)', "", line)
            line = re.sub(r' (!|x|s|S|R|fb|pt|q[\d.]+)?"(?:[^"\\]|\\.)*"(@\d+)?| (![a-z]+|q[\d.]+|clef=\S+)(@\d+)?', "", line)
            line = re.sub(r"\[[^\]]*\](@\d+)?|(?<=\d)('[^\s+\[~:']*)*(:[A-Za-z][\w=-]*)*", "", line)
            line = re.sub(r"(?<= )(\d+:\d+)?\{ | \}(?= |$)", "", line + " ")
            line = re.sub(r" +", " ", line).rstrip()
            if line.endswith(":"):
                continue
        kept.append(line)
    return "\n".join(kept)


async def main() -> None:
    info = await server.load_info()
    _, lines = await server.bridge.request(f"read 0 {2**31 - 1}")
    index = build_index(info, lines, int(server.bridge.hello["division"]))
    numbers = [measure.number for measure in info.measures]
    first, last = numbers[0], numbers[-1]
    middle = numbers[len(numbers) // 2]
    for a, b in [(first, last), (1, min(4, last)), (middle, last)]:
        text = n1x.encode(info, index, a, b)
        check(f"bars {a}-{b}, stripped N1x equals N1", normal(strip(text)) == normal(notes.encode(index, a, b)))
        check(f"bars {a}-{b}, N1x decodes to the score's notes", decoded_notes(text) == index_notes(index, first if a == 1 else a, b))
    text = n1x.encode(info, index, first, last)
    print(text.split("\nm")[0])
    bars = [line for line in text.splitlines() if re.match(r"m\d+ ", line)]
    for line in bars:
        if len(line.split()) > 2:
            print("  " + line)
    if info.title == BAR_FIELDS_TITLE:
        check("bar fields", bars == EXPECTED_BARS, "\n".join(f"  got {g!r}, want {w!r}" for g, w in zip(bars, EXPECTED_BARS) if g != w))
    if info.title == MARKS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("marks", got == EXPECTED_MARKS, f"\n{got}")
    if info.title == SYSTEM_MARKS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("system objects once, in staff 1", got == EXPECTED_SYSTEM_MARKS, f"\n{got}")
    if info.title == DECORATIONS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("decorations", got == EXPECTED_DECORATIONS, f"\n{got}")
    if info.title == GROUPS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("groups and tuplets", got == EXPECTED_GROUPS, f"\n{got}")
    if info.title == LINES_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("lines", got == EXPECTED_LINES, f"\n{got}")
    if info.title == LYRICS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("lyrics", got == EXPECTED_LYRICS, f"\n{got}")
        _, lines = await server.bridge.request(f"read {info.ticks[numbers.index(4)]} {2**31 - 1}")
        got = n1x.encode(info, build_index(info, lines, int(server.bridge.hello["division"])), 4, 5)
        check("syllable held from before the range", '\nm4 len=4\n1.1: 2 F5 gA5 1 G5\n1.1 L1: _ "you are"\n' in got, f"\n{got}")
    if info.title == REPEATS_TITLE:
        got = text[text.index("\nm1 ") + 1 :]
        check("repeated bars", got == EXPECTED_REPEATS, f"\n{got}")
        got = n1x.encode(info, index, 4, 6)
        check("a range writes out the bars it refers to", got.endswith("\nm4 len=4\n1.1: 1 C5 D5 E5 F5\n2.1: 4 G2\nm5 len=4\n1.1: !p 1 C5 D5 E5 F5\n2.1: 4 C3\nm6 len=4 rep=end\n1.1 = m4\n2.1 = m5"), f"\n{got}")
    if failures:
        sys.exit(f"{len(failures)} failed")


if __name__ == "__main__":
    asyncio.run(main())
