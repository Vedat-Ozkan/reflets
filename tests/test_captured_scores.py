import asyncio
import json
from fractions import Fraction
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from reflets import n1x, server
from reflets.score import parse_info
from reflets.write import add_lines, cells, compile_idea, occupied, parsed, verify

CAPTURES = {path.stem: json.loads(path.read_text()) for path in sorted((Path(__file__).parent / "data/reading").glob("*.json"))}
NOCTURNE_IDEA = """N1 div=4 ts=12/8 ks=3f
m5 len=24
1.1: 6 G5~ ) 6 G5 gAb5 4 Bb5 2 Ab5 6 G5
m6 len=24
1.1: 2 F5 Eb5 D5 gC5 gD5 10 Eb5 8 r
1.2: 12 r 12 Bb4"""


def in_range(words: list[str], start: int, end: int) -> bool:
    tick = int(words[1])
    if words[0] == "N":
        last = int(words[2].rstrip("g"))
        return start <= tick < end or start < last <= end
    if words[0] == "Y" and tick < start:
        return tick + int(words[5]) >= start
    return start <= tick < end


class CapturedScore:
    def __init__(self, capture: dict):
        self.capture = capture
        self.hello = {"division": str(capture["division"])}

    async def request(self, line: str):
        if line == "info":
            return [], self.capture["info"]
        verb, start, end = line.split(" ")
        assert verb == "read", f"MuseScore was asked to {line.split()[0]}"
        return [], [event for event in self.capture["read"] if in_range(event.split(" "), int(start), int(end))]


@pytest.fixture
def opened(monkeypatch):
    def open_score(name: str) -> dict:
        monkeypatch.setattr(server, "bridge", CapturedScore(CAPTURES[name]))
        return CAPTURES[name]

    return open_score


def read(bars: str) -> str:
    try:
        return asyncio.run(server.read_score(bars))
    except ToolError as error:
        return f"Error: {error}"


def propose(idea: str) -> str:
    return asyncio.run(server.propose(idea, "test"))


def compiled(capture: dict, idea: str):
    info = parse_info(capture["info"])
    plan = compile_idea(parsed(idea), info, capture["division"], max(staff for _, staves in info.parts for staff in staves), capture["read"])
    add_lines(plan, capture["read"], info)
    return plan


@pytest.mark.parametrize("name", CAPTURES)
def test_every_bar_range_reads_as_captured(opened, name):
    windows = opened(name)["windows"]
    assert [bars for bars, text in windows.items() if read(bars) != text] == []


def test_the_chorale_reads_as_notes_the_model_can_follow(opened):
    opened("chorale")
    idea = n1x.decode(read("0-1"))
    pickup, first = idea.bars
    assert idea.lines[0] == "N1x div=2 ts=4/4 ks=3s"
    assert (pickup.label, pickup.fields["len"]) == ("0", "2")
    soprano = first.voices[1, 1].chords
    assert [chord.notes[0].pitch for chord in soprano] == ["A4", "B4", "C#5", "E5"]
    assert [chord.onset for chord in soprano] == [0, 1, 2, 3]
    assert soprano[2].decorations == ("fermata",)
    assert sorted(first.voices) == [(1, 1), (2, 1), (3, 1), (4, 1)]


def test_tuplets_slurs_and_lyrics_read_as_written(opened):
    opened("groups")
    assert "1.1: 3:2{ 2 C5 D5 E5 } [stacc]{ 3 F5 G5 A5 B5 } 6 C6" in read("1")
    opened("nocturne")
    bars = read("5")
    assert "!p 6 G5 )" in bars and "F5'3[prall]" in bars and "Eb5[acc]~" in bars
    opened("lyrics")
    assert '1.1 L1: _ "you are"' in read("4")


@pytest.mark.parametrize("bars, error", [
    ("99", "Error: Bar 99 does not exist; the score has bars 0 to 9"),
    ("5-2", 'Error: bars runs from the earlier bar to the later one, as in "2-5"'),
    ("bar five", 'Error: bars must be "all" or a range like "5-12", not \'bar five\''),
])
def test_a_bar_range_the_score_does_not_have_is_refused(opened, bars, error):
    opened("chorale")
    assert read(bars) == error


@pytest.mark.parametrize("name", CAPTURES)
def test_the_score_written_back_as_read_matches_its_read_back(name):
    capture = CAPTURES[name]
    plan = compiled(capture, capture["windows"]["all"])
    assert plan.counts["notes"] > 0
    assert verify(plan, capture["read"], capture["read"], parse_info(capture["info"]), capture["division"])[0] is None


def test_a_read_back_with_one_wrong_pitch_is_caught():
    capture = CAPTURES["chorale"]
    plan = compiled(capture, capture["windows"]["all"])
    wrong = [line.replace(" 69:17:17", " 70:12:12", 1) if line.startswith("C 480 0 ") else line for line in capture["read"]]
    mismatch, _ = verify(plan, capture["read"], wrong, parse_info(capture["info"]), capture["division"])
    assert mismatch.startswith("bar 1 1.1 was written as '1.1: 2 A4 B4 C#5[fermata] E5' and reads back as '1.1: 2 Bb4 B4")


def test_a_note_longer_than_any_written_value_is_tied():
    plan = compiled(CAPTURES["chorale"], "N1x div=2\nm1 len=8\n1.2: 5 A4 3 r")
    assert plan.ops == ["x 1 480 2400 1", "v 1 480", "d 1/2", "n 480 69:17", "d 1/8", "n 1440 69:17", "d 3/8", "r 1680", "~ 1 480 69"]


def test_a_rewritten_melody_keeps_its_grace_notes_ties_and_slurs():
    plan = compiled(CAPTURES["nocturne"], NOCTURNE_IDEA)
    assert {what: n for what, n in plan.counts.items() if n} == {"notes": 11, "rests": 2, "ties": 2, "grace notes": 3, "decorations": 1}
    assert plan.ops[plan.ops.index("v 0 11760"):][:6] == ["v 0 11760", "d 3/8", "n 11760 79:15", "n 12480 79:15", "d 1/4", "n 13200 82:12"]
    assert "g 0 13200 acciaccatura 80:10" in plan.ops
    assert "~ 0 11760 79" in plan.ops
    assert "l 0 11520 0 12480 0 SLUR 0 " in plan.ops
    assert occupied(plan, cells(CAPTURES["nocturne"]["read"], parse_info(CAPTURES["nocturne"]["info"]))) == [(5, 0), (6, 0)]


def test_a_dynamic_is_written_as_a_mark():
    plan = compiled(CAPTURES["chorale"], "N1x div=2\nm1 len=8\n1.2: !f 8 A4")
    assert [op for op in plan.ops if op.startswith("a ")] == ["a 1 480 DYNAMIC 9 f"]


@pytest.mark.parametrize("idea, error", [
    ("m1 len=8\n1.1: 2 A4 B4 C#5 E5", "These voices already have notes: bar 1 1.1. Ask the user, then call again with replace=True."),
    ("m3b len=8\n1.2: 8 A4", "Bar 3b does not exist; the score has bars 0 to 9"),
    ("m1 len=6\n1.2: 6 A4", "m1: len= must match the score's bar, which is 8 long"),
    ("m1 len=8\n1.2: 2 A4 B4 C#5 E5 F#5", "m1 1.2: the notes last 5 quarter notes; the bar has 4"),
    ("m1 len=8\n1.2: 0 A4 8 r", "m1 1.2: a duration is at least 1"),
    ("m1 len=8\n5.1: 8 A4", "m1: there is no 5.1; the score has staves 1 to 4, voices 1 to 4"),
    ("m1 len=8\n2.1: q60 8 A4", "m1 2.1: q60 is a system mark (tempo, rehearsal mark, system text); write it in 1.1"),
])
def test_an_idea_the_score_cannot_take_is_refused_before_writing(opened, idea, error):
    opened("chorale")
    with pytest.raises(ToolError) as refused:
        propose("N1x div=2\n" + idea)
    assert str(refused.value) == error


def test_a_third_of_a_beat_needs_a_tuplet(opened):
    opened("chorale")
    with pytest.raises(ToolError, match=r"a duration of 1/3 quarter notes needs a tuplet"):
        propose("N1x div=3\nm1 len=12\n1.2: 1 A4 11 r")
    assert compiled(CAPTURES["chorale"], "N1x div=3\nm1 len=12\n1.2: 3:2{ 1 A4 B4 C#5 } 9 r").counts["notes"] == 3
    assert n1x.decode("N1x div=3\nm1 len=12\n1.2: 3:2{ 1 A4 B4 C#5 } 9 r").bars[0].voices[1, 2].chords[2].onset == Fraction(2, 3)
