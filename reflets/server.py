from __future__ import annotations

import itertools
from dataclasses import dataclass

from engine import notes
from engine.score import PositionError
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from reflets import n1x
from reflets.bridge import Bridge, BridgeError
from reflets.score import ScoreInfo, build_index, parse_info
from reflets.write import IdeaError, cells, compile_idea, occupied, verify

WHOLE_SCORE_TOKENS = 6000
FIRST_BARS = 16

mcp = MCPServer(
    "reflets",
    title="Reflets",
    instructions=(
        "Reflets connects you to the score open in the user's MuseScore Studio. Call score_info first, then "
        "read_score for the notes. Notes come in N1x: a header line, then the title, composer and one 'P' line per "
        "part; each bar starts 'mN len=' with fields where they apply: ts= and ks= at a meter or key change, "
        "rep=start|end|both and x= (times played), volta=, bar= (a bar line the user set), break=, jump=, mark=. "
        "Then one 'staff.voice:' line per voice per bar, a bare number "
        "sets the duration in div units per quarter note, '+' joins a chord, 'r' is a rest, a leading 'g' marks "
        "a grace note, a trailing '~' a tie. Pitches are sounding pitches with their spelling (Eb4, not D#4). "
        "Marks stand before the note or rest they fall on, or after one with @ and their offset from the bar start "
        "in div units when they fall inside it: !mf dynamic, \"G7\" chord symbol, x\"…\" expression, s\"…\" staff "
        "text, S\"…\" system text, q60 or q60\"Andante\" tempo in quarter notes per minute, R\"A\" rehearsal mark, "
        "fb\"6/4\" figured bass, pt\"pizz.\" playing technique, clef=bass. Decorations follow their note, rest "
        "or chord in brackets, G5[stacc,acc], Eb4+G4[arp], 24 r[fermata], B3[staff+1] cross-staff; one note's own "
        "in a chord takes a colon, C4:head=x+E4; fingering follows the pitch, C4'1. Braces group notes: "
        "3:2{ 8 C5 D5 E5 } is a tuplet, durations inside in div units of the time they take; [stacc]{ … } gives "
        "every note inside the decoration; a duration number carries across braces. "
        "Lines open just before the note they start on and close just after the note they end with, or with @, "
        "possibly in a later bar: ( ) slur, <( <) and >( >) hairpins, cresc( and dim( lines, ped( pedal, 8va( 8vb( "
        "15ma( octave lines (pitches stay sounding), tr( trill line, line\"…\"( text line, tempo\"rit.\"( tempo change. "
        "A 'staff.voice Ln:' line under a voice line gives verse n's lyrics, one syllable per note, graces and rests "
        "skipped: a trailing '-' continues the word, '_' holds the syllable over the note, '*' marks a note without one. "
        "'m9 = m1' means bar 9 is bar 1 again, every line and field; '2.1 = m1' means this voice line is bar 1's. "
        "To try an idea, write it in the same form with propose; it lands in the score in colour as one undo step. "
        "The user listens in MuseScore, then you call keep or discard as they decide. Before you say which note "
        "sounds where, find the bar and count through its voice line from the start of the bar; answers given "
        "at a glance are often wrong."
    ),
)
bridge = Bridge()


@dataclass
class Proposal:
    label: str
    start_tick: int
    end_tick: int
    tracks: list[int]
    bars: str
    pre: list[str]
    post: list[str]


proposals: dict[str, Proposal] = {}
proposal_numbers = itertools.count(1)


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
    structured_output=False,
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
        "Use this to see the notes of the score open in MuseScore, as N1x text (see the server instructions). "
        'bars is "all" or a range like "5-12", numbered as MuseScore shows them, a pickup being bar 0. '
        f"A long score read as \"all\" returns the first {FIRST_BARS} bars and says how many there are; "
        "then read further ranges as needed."
    ),
    annotations=read_only("Read the score"),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,
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
    start_tick = info.ticks[0 if first == 1 and numbers[0] == 0 else numbers.index(first)]
    end_index = numbers.index(last) + 1
    end_tick = info.ticks[end_index] if end_index < len(info.ticks) else 2**31 - 1
    try:
        _, lines = await bridge.request(f"read {start_tick} {end_tick}")
    except BridgeError as error:
        raise ToolError(str(error)) from None
    index = build_index(info, lines, int(bridge.hello["division"]))
    try:
        text = n1x.encode(info, index, first, last)
        if whole and len(text) / 3.5 > WHOLE_SCORE_TOKENS:
            cut = numbers[min(len(numbers) - 1, numbers.index(first) + FIRST_BARS - 1)]
            text = n1x.encode(info, index, first, cut) + (
                f"\n(The score has bars {numbers[0]}-{numbers[-1]}; this is bars {first}-{cut}. "
                "Call read_score with a range for more.)"
            )
    except (notes.NotesError, PositionError) as error:
        raise ToolError(f"Could not encode bars {first}-{last}: {error}") from None
    return text


async def request(line: str) -> list[str]:
    try:
        _, lines = await bridge.request(line)
    except BridgeError as error:
        raise ToolError(str(error)) from None
    return lines


def writes(title: str, destructive: bool) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=False, destructive_hint=destructive, idempotent_hint=False, open_world_hint=False)


@mcp.tool(
    title="Propose an idea",
    description=(
        "Use this to write an idea into the open score so the user can hear it. idea is N1x in the form "
        "read_score returns: the header line, then for each bar to write its 'mN len=' line (len as in the score; "
        "other bar fields only as the score has them, they cannot be changed yet) "
        "and one 'staff.voice:' line per voice to write. Each voice line replaces that voice's notes and rests in that bar; voices "
        "and bars you leave out are untouched; a line of rests only (e.g. '1.2: 288 r') empties a voice. "
        "Silence at the end of a voice line is filled with rests. Marks are written with the voice line and replace "
        "its marks in that bar, so write again any you keep; a line with marks only (e.g. '1.1: !f \"Dm7\"@96') "
        "replaces the voice's marks and leaves its notes. A mark needs a note or rest starting at its moment in some "
        "voice; tempo, rehearsal marks and system text go in 1.1, clefs in voice 1 of their staff. Tuplets, grace "
        "chords and references to bars written out earlier in the idea ('m9 = m1', '2.1 = m1') can be written. Not "
        "yet: lines, decorations and decoration groups, lyrics; the lines already in a voice stay. replace=True is "
        "needed when a voice you write already has "
        "notes there. The idea is written in colour as one undo step and read back; the result gives a proposal id "
        "for keep or discard."
    ),
    annotations=writes("Propose an idea", destructive=True),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,
)
async def propose(idea: str, label: str = "idea", replace: bool = False) -> str:
    info = await load_info()
    staves = max(staff for _, part_staves in info.parts for staff in part_staves)
    try:
        plan = compile_idea(idea, info, int(bridge.hello["division"]), staves)
    except IdeaError as error:
        raise ToolError(str(error)) from None
    numbers = [measure.number for measure in info.measures]
    pre = await request(f"read {plan.start_tick} {plan.end_tick}")
    taken = occupied(plan, cells(pre, info))
    if taken and not replace:
        where = ", ".join(f"bar {numbers[p]} {t // 4 + 1}.{t % 4 + 1}" for p, t in taken)
        raise ToolError(f"These voices already have notes: {where}. Ask the user, then call again with replace=True.")
    label = " ".join(label.split()) or "idea"
    reply = await request(f"write {plan.start_tick} {plan.end_tick} {label}\n" + "\n".join(plan.ops))
    mismatch, cut = verify(plan, pre, reply, info, int(bridge.hello["division"]))
    if mismatch:
        await request("undo")
        after = await request(f"read {plan.start_tick} {plan.end_tick}")
        state = "The write was undone." if sorted(after) == sorted(pre) else "Undoing it did not restore the bars; ask the user to check them."
        raise ToolError(f"The idea did not land as written ({mismatch}). {state}")
    positions = sorted({p for p, _ in plan.cells})
    bars = f"bars {numbers[positions[0]]}-{numbers[positions[-1]]}" if len(positions) > 1 else f"bar {numbers[positions[0]]}"
    proposal_id = f"p{next(proposal_numbers)}"
    tracks = sorted({t for _, t in plan.cells})
    proposals[proposal_id] = Proposal(label, plan.start_tick, plan.end_tick, tracks, bars, pre, reply)
    counts = ", ".join(f"{n} {what if n > 1 else what[:-1]}" for what, n in plan.counts.items() if n)
    voices = ", ".join(f"{t // 4 + 1}.{t % 4 + 1}" for t in tracks)
    note = f" The tie into or out of bar(s) {', '.join(map(str, cut))} was cut, as the idea replaced its note." if cut else ""
    return (
        f'Written: {bars}, voices {voices}, {counts}, as one undo step "Reflets: {label}". Read-back matched.{note}\n'
        f"The new notes are blue. The user listens with Play in MuseScore; then keep(\"{proposal_id}\") turns them "
        f"black, or discard(\"{proposal_id}\") removes them.\nproposal id: {proposal_id}"
    )


def find(proposal_id: str) -> Proposal:
    if proposal_id not in proposals:
        open_ids = ", ".join(proposals) or "none"
        raise ToolError(f"There is no open proposal {proposal_id!r} (open: {open_ids}).")
    return proposals[proposal_id]


@mcp.tool(
    title="Discard an idea",
    description=(
        "Use this when the user does not want a proposed idea: it undoes the proposal, restoring the bars. "
        "Refused if the user has edited those bars since; then they can use Ctrl+Z themselves."
    ),
    annotations=writes("Discard an idea", destructive=True),
    structured_output=False,
)
async def discard(proposal_id: str) -> str:
    p = find(proposal_id)
    span = f"read {p.start_tick} {p.end_tick}"
    if sorted(await request(span)) != sorted(p.post):
        raise ToolError(
            f"{p.bars.capitalize()} changed since {proposal_id} was written, so undoing would remove the user's edit. "
            "Nothing was undone; the user can use Ctrl+Z in MuseScore."
        )
    await request("undo")
    if sorted(await request(span)) != sorted(p.pre):
        await request("redo")
        restored = sorted(await request(span)) == sorted(p.post)
        raise ToolError(
            f"The last step in MuseScore's undo history was not {proposal_id}"
            + (", so it was redone and nothing changed." if restored else ", and redoing it did not restore the bars; ask the user to check them.")
            + " The user can remove the idea with Edit > Undo."
        )
    del proposals[proposal_id]
    return f"Discarded {proposal_id}: the score is back as it was in {p.bars}."


@mcp.tool(
    title="Keep an idea",
    description="Use this when the user keeps a proposed idea: its notes turn from blue to black.",
    annotations=writes("Keep an idea", destructive=False),
    structured_output=False,
)
async def keep(proposal_id: str) -> str:
    p = find(proposal_id)
    tracks = ",".join(map(str, p.tracks))
    await request(f"color {p.start_tick} {p.end_tick} {tracks} #000000 keep {p.label}")
    del proposals[proposal_id]
    return f'Kept {proposal_id}: the notes in {p.bars} are black now (one undo step, "Reflets: keep {p.label}").'


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
