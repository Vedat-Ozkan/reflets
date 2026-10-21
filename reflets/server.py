from __future__ import annotations

import asyncio
import itertools
import json
import re
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from engine import annotate, draft, notes, part_writing, reduce
from engine.annotate import AnnotationError
from engine.annotations import AnnotationList
from engine.render import ScoreError
from engine.score import PositionError, ScoreIndex
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from reflets import n1x
from reflets.bridge import NOT_RUNNING, PROTO, Bridge, BridgeError, token_file
from reflets.score import ScoreInfo, build_index, parse_info
from reflets.write import (
    IdeaError,
    add_lines,
    cells,
    compile_idea,
    idea_range,
    meter_reach,
    meter_span,
    occupied,
    recast_view,
    verify,
    verify_bars,
)

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
        "15ma( octave lines (pitches stay sounding), tr( trill line, line\"…\"( text line, tempo\"rit.\"( tempo change; "
        "a number after the parenthesis pairs two ends that would otherwise pair with another line's, (2 … )2. "
        "A 'staff.voice Ln:' line under a voice line gives verse n's lyrics, one syllable per note, graces and rests "
        "skipped: a trailing '-' continues the word, '_' holds the syllable over the note, '*' marks a note without one. "
        "'m9 = m1' means bar 9 is bar 1 again, every line and field; '2.1 = m1' means this voice line is bar 1's. "
        "check lists part-writing faults such as parallel fifths in chorale-style bars, analyze drafts the harmony, "
        "render shows bars as an image, with check's findings drawn on it if asked. "
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
    pre_end: int


proposals: dict[str, Proposal] = {}
proposal_numbers = itertools.count(1)
render_numbers = itertools.count(1)


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
    info, index, first, last, whole = await read_bars(bars)
    numbers = [measure.number for measure in info.measures]
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


@mcp.tool(
    title="Check the voice leading",
    description=(
        "Use this to check bars against the classroom part-writing rules: parallel and direct fifths and octaves, "
        "voice crossing and overlap, spacing, range, a doubled or unresolved leading tone, an unresolved seventh. "
        'bars is a range like "5-12" or "all". The result is a beat-by-beat table of the notes sounding, then each '
        "finding with its bars, beats and voices (staff.voice). The rules apply to two to four voices of single "
        "notes moving mostly together, as in a chorale; for other textures the result says they do not apply. "
        "Findings are what a strict teacher would mark, not verdicts on the music."
    ),
    annotations=read_only("Check the voice leading"),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,
)
async def check(bars: str = "all") -> str:
    _, index, first, last, _ = await read_bars(bars)
    table = await asyncio.to_thread(reduce.as_text, index, first, last)
    if not part_writing.applies(index):
        return table + (
            f"\n\nThe voice-leading rules do not apply to bars {first}-{last}: they need two to four voices of single "
            "notes, no chords, on at most four staves, with at least 60% of their notes starting together."
        )
    findings = await asyncio.to_thread(part_writing.check, index)
    lines = [f"\n\nVoice-leading check of bars {first}-{last} (classroom rules, not verdicts on the music):"]
    for number, finding in enumerate(findings, 1):
        where = " to ".join(f"m{bar} b{beat:g}" for bar, beat in zip(finding.bars, finding.beats))
        voices = " and ".join(f"{staff}.{layer}" for staff, layer in finding.voices)
        lines.append(f"{number}. {where}, {voices}, {finding.rule.replace('_', ' ')}: {finding.why}")
    return table + "\n".join(lines if findings else lines + ["No rule broken."])


@mcp.tool(
    title="Analyze the harmony",
    description=(
        "Use this for a draft harmonic analysis of bars: a beat-by-beat table of the notes sounding, then chords "
        "with key, Roman numeral and the model's confidence, cadences, phrase ends, pedal points and possible "
        'non-chord tones. bars is a range like "5-12" or "all". The model reads the whole score for context. '
        "Its labels are right only about half the time: check each against the notes before you rely on it."
    ),
    annotations=read_only("Analyze the harmony"),
    structured_output=False,
)
async def analyze(bars: str = "all") -> str:
    _, index, first, last, _ = await read_bars(bars, whole_score=True)
    table = reduce.as_text(index, first, last)
    if not Path(draft.ANALYSISGNN_PYTHON).exists() or not Path(draft.ANALYSISGNN_CHECKPOINT).exists():
        return table + (
            f"\n\nNo harmony draft: the AnalysisGNN model is not installed (ANALYSISGNN_PYTHON {draft.ANALYSISGNN_PYTHON}, "
            f"ANALYSISGNN_CHECKPOINT {draft.ANALYSISGNN_CHECKPOINT}). Analyse from the table."
        )
    try:
        result = await asyncio.to_thread(draft.draft, index)
    except draft.DraftError as error:
        return table + f"\n\nNo harmony draft: {error}. Analyse from the table."
    return table + "\n\n" + draft.as_text(result, first, last)


async def read_bars(bars: str, whole_score: bool = False) -> tuple[ScoreInfo, ScoreIndex, int, int, bool]:
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
    start_tick = info.ticks[0 if whole_score or first == 1 and numbers[0] == 0 else numbers.index(first)]
    end_index = len(numbers) if whole_score else numbers.index(last) + 1
    end_tick = info.ticks[end_index] if end_index < len(info.ticks) else 2**31 - 1
    try:
        _, lines = await bridge.request(f"read {start_tick} {end_tick}")
    except BridgeError as error:
        raise ToolError(str(error)) from None
    return info, build_index(info, lines, int(bridge.hello["division"])), first, last, whole


@mcp.tool(
    title="Render bars",
    description=(
        'Use this to see bars engraved: bars is a range like "5-12", at most 32 bars. With check=True the '
        "voice-leading findings are drawn on the notes in red, numbered as listed in the result. The result gives "
        "the path of a PNG image of the bars as they are in MuseScore now, unsaved changes and ideas included; "
        "open it to look at it."
    ),
    annotations=read_only("Render bars"),
    structured_output=False,
)
async def render(bars: str, check: bool = False) -> str:
    _, index, first, last, _ = await read_bars(bars)
    found = await asyncio.to_thread(part_writing.as_text, index) if check else ""
    marks, spots = drawings(found)
    export = token_file().parent / f"reflets-export-{uuid.uuid4().hex}.musicxml"
    try:
        await bridge.request(f"export {windows_path(export)}")
        score = export.read_bytes()
    except BridgeError as error:
        raise ToolError(str(error)) from None
    finally:
        export.unlink(missing_ok=True)
    try:
        engraving = await asyncio.to_thread(annotate.render, score, AnnotationList(annotations=marks), (first, last))
    except (PositionError, AnnotationError, ScoreError) as error:
        raise ToolError(f"Could not render bars {first}-{last}: {error}") from None
    folder = Path(tempfile.gettempdir()) / "reflets"
    folder.mkdir(exist_ok=True)
    paths = []
    for page in range(1, engraving.page_count + 1):
        paths.append(folder / f"bars-{first}-{last}-{next(render_numbers)}.png")
        paths[-1].write_bytes(await asyncio.to_thread(engraving.png, page))
    text = "Bars {}-{}: {}".format(first, last, ", ".join(str(path) for path in paths))
    if check and not found:
        text += "\nThe voice-leading rules do not apply to these bars, so nothing is drawn."
    elif check:
        text += f"\n{sum(not spot.startswith(' ') for spot in spots)} numbered spot(s) drawn:\n" + "\n".join(spots) if spots else "\nNo rule broken."
    return text


def drawings(report: str) -> tuple[list[dict], list[str]]:
    marks, spots, number = [], [], 0
    for line in report.splitlines():
        spot = re.match(r"(\d+)\. m(\d+) b([\d.]+), callout at", line)
        draw = re.match(r'   draw (\w+) (\{[^}]*\})(?: -> (\{[^}]*\}))?(?: label "([^"]*)")?(?: direction "(\w+)")?$', line)
        if spot:
            number = int(spot[1])
            marks.append({"type": "callout", "at": {"measure": int(spot[2]), "beat": float(spot[3])}, "number": number})
            spots.append(line.split(", callout at")[0])
        elif draw:
            marks.append({
                "type": "voice_leading", "kind": draw[1], "from_note": json.loads(draw[2]),
                "to_note": json.loads(draw[3]) if draw[3] else None, "label": draw[4] or "",
                "direction": draw[5], "callout": number,
            })
        elif number and line.startswith("   "):
            spots.append(line)
    return marks, spots


def windows_path(path: Path) -> str:
    found = re.fullmatch(r"/mnt/([a-z])/(.*)", path.as_posix())
    return f"{found[1].upper()}:/{found[2]}" if found else str(path)


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
        "ks= changes the concert key from that bar on, on every staff (notes keep their pitches); ts= changes the meter from that bar on, and when it changes the bar's length "
        "(3/4 to 4/4, but not 4/4 to 2/2 or 3/4 to 6/8) only alone on a bar line, over bars with no notes, or with recast=True; other bar fields as marks: one the bar has stays when left out, "
        "one written is set, e.g. 'm8 len=4 rep=end x=3 jump=dc-al-fine', and a minus removes one, e.g. '-break=line'; "
        "-volta= removes the whole volta) and one 'staff.voice:' line per voice to write; a bar line alone changes only its fields. Each voice line replaces that voice's notes and rests in that bar; voices "
        "and bars you leave out are untouched; a line of rests only (e.g. '1.2: 288 r') empties a voice. "
        "Silence at the end of a voice line is filled with rests. The score's marks and decorations stay as they are: "
        "a mark the bar and voice already have, written anywhere in the line, is left where it is, and others are "
        "added; a new note at the moment of an old one keeps its articulations and other decorations, and fingering, "
        "parentheses, noteheads and let ring on a note of the same pitch. Remove something only when the user asks, "
        "with a minus: '-!p', '-\"Dm7\"', '-[fermata]@96', 'D5[-stacc]', 'C4:-paren'; move a mark by removing it and "
        "writing it where it goes. A line with marks only (e.g. '1.1: !f -!p@96') leaves the notes. A new mark needs a "
        "note or rest starting at its moment in some voice; tempo, rehearsal marks and system text go in 1.1, clefs in "
        "voice 1 of their staff. A note with a glissando cannot be rewritten unless the idea removes it ([-gliss]). Tuplets, grace "
        "chords, decorations, decoration groups, fingering and references to bars written out earlier in the idea "
        "('m9 = m1', '2.1 = m1') can be written; glissandos cannot. A tie may run into the bar after the idea when "
        "that bar's voice starts with the same pitch; a tie from the bar before stays when the bar still starts with "
        "that pitch, and the result says when one was cut. Lines (slurs, hairpins, pedal, …) stay as they are too: a line "
        "end the bar and voice already have refers to that line, wherever it is written, and a slur over rewritten notes "
        "is hung on the notes sounding at its old start and end. A new line needs both ends in the idea; a later bar may "
        "carry just its closer ('1.1: )@96'). Remove a line with a minus on either end ('-ped('); move an end by removing "
        "it and writing the new one ('-ped) ped)@96'). "
        "Lyrics stay too: when the notes change, each syllable stays on the note starting at its moment, or else on the "
        "note sounding there; one left without a note is named in the result. A lyric line ('1.1 L1: Twin- kle _ *') "
        "under a voice line sets that verse in the bar, one syllable per note as read_score shows it, with '_' holding the "
        "syllable before and '*' a note without one; an empty one ('1.1 L1:') removes the verse there. To change only "
        "the lyrics, write the voice line empty ('1.1:') with the lyric line under it. "
        "replace=True is needed when a voice you write already has "
        "notes there. recast=True, only when the user asks to recast music in a meter of another length (4/4 triplets as "
        "12/8, say), rewrites bars in a new meter bar for bar: the idea's first bar has the new ts=, and it writes each "
        "bar to recast, every voice that has notes or rests there, in the new meter; the bar after it keeps its meter. "
        "Marks, lines and lyrics move to the same place in the beat, on the nearest note or rest. The tempo stays in "
        "quarter notes, so to keep the beat write the new tempo too (q120 in 4/4 is q180 in 12/8) and the old one after. "
        "The idea is written in colour as one undo step and read back; the result gives a proposal id "
        "for keep or discard."
    ),
    annotations=writes("Propose an idea", destructive=True),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,
)
async def propose(idea: str, label: str = "idea", replace: bool = False, recast: bool = False) -> str:
    info = await load_info()
    division = int(bridge.hello["division"])
    staves = max(staff for _, part_staves in info.parts for staff in part_staves)
    numbers = [measure.number for measure in info.measures]
    try:
        start_tick, end_tick = idea_range(idea, info)
        original = pre = await request(f"read {start_tick} {end_tick}")
        view = recast_view(idea, info, pre, division) if recast else None
        if view:
            reach = meter_reach(info, view.positions[-1])
            span = (view.after, info.ticks[reach] if reach < len(info.ticks) else 2**31 - 1 - view.delta)
            info, pre = view.info, view.pre
        else:
            span = meter_span(idea, info)
        later = await request(f"read {span[0]} {span[1]}") if span else []
        plan = compile_idea(idea, info, division, staves, pre, later, view.positions if view else range(0))
        add_lines(plan, pre, info)
    except IdeaError as error:
        raise ToolError(str(error)) from None
    if view:
        plan.ops[0:0] = view.ops
        plan.meters = dict.fromkeys(view.positions, view.meter)
    taken = occupied(plan, cells(pre, info))
    if taken and not replace:
        where = ", ".join(f"bar {numbers[p]} {t // 4 + 1}.{t % 4 + 1}" for p, t in taken)
        raise ToolError(f"These voices already have notes: {where}. Ask the user, then call again with replace=True.")
    label = " ".join(label.split()) or "idea"
    reply = await request(f"write {plan.start_tick} {plan.end_tick} {label}\n" + "\n".join(plan.ops))
    mismatch, cut = verify(plan, pre, reply, info, division) if not plan.rebar else (None, [])
    if not mismatch and span and not plan.rebar:
        shift = view.delta if view else 0
        again = await request(f"read {span[0] + shift} {span[1] + shift}")
        if beyond(shifted(later, shift), plan.end_tick) != beyond(again, plan.end_tick):
            mismatch = "the bars after the idea, up to the next meter change, changed with the meter"
    if not mismatch and any(op.startswith("b ") or " VOLTA " in op for op in plan.ops):
        mismatch = verify_bars(plan, info, await load_info())
    if mismatch:
        await request("undo")
        after = await request(f"read {start_tick} {end_tick}")
        state = "The write was undone." if sorted(after) == sorted(original) else "Undoing it did not restore the bars; ask the user to check them."
        raise ToolError(f"The idea did not land as written ({mismatch}). {state}")
    positions = sorted(plan.expected_bars)
    bars = f"bars {numbers[positions[0]]}-{numbers[positions[-1]]}" if len(positions) > 1 else f"bar {numbers[positions[0]]}"
    proposal_id = f"p{next(proposal_numbers)}"
    tracks = sorted({t for _, t in plan.cells})
    proposals[proposal_id] = Proposal(label, plan.start_tick, plan.end_tick, tracks, bars, original, reply, end_tick)
    counts = ", ".join(f"{n} {what if n > 1 else what[:-1]}" for what, n in plan.counts.items() if n)
    voices = ", ".join(f"{t // 4 + 1}.{t % 4 + 1}" for t in tracks)
    cut = sorted(set(cut) | plan.cut_ties)
    note = f" The tie into or out of bar(s) {', '.join(map(str, cut))} was cut, as the idea replaced its note." if cut else ""
    if plan.dropped:
        note += f" These syllables had no note left and were removed: {'; '.join(plan.dropped)}."
    return (
        f'Written: {bars}, voices {voices}, {counts}, as one undo step "Reflets: {label}". Read-back matched.{note}\n'
        f"The new notes are blue. The user listens with Play in MuseScore; then keep(\"{proposal_id}\") turns them "
        f"black, or discard(\"{proposal_id}\") removes them.\nproposal id: {proposal_id}"
    )


def shifted(lines: list[str], delta: int) -> list[str]:
    result = []
    for line in lines:
        words = line.split(" ")
        words[1] = str(int(words[1]) + delta)
        if words[0] == "N":
            end = words[2].rstrip("g")
            words[2] = str(int(end) + delta) + words[2][len(end):]
        result.append(" ".join(words))
    return result


def beyond(lines: list[str], tick: int) -> list[str]:
    return sorted(line for line in lines if int(line.split(" ")[1]) >= tick)


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
    if sorted(await request(f"read {p.start_tick} {p.pre_end}")) != sorted(p.pre):
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


@mcp.tool(
    title="Diagnose the connection",
    description=(
        "Use this when score_info cannot reach MuseScore or a tool fails in a way you cannot explain: "
        "a checklist of the plugin file, its token file, the harmony model, the port, the bridge's answer, "
        "MuseScore's version and the open score, each passed or failed with what to do."
    ),
    annotations=read_only("Diagnose the connection"),
    structured_output=False,
)
async def doctor() -> str:
    checks = []

    def check(ok: bool, text: str) -> None:
        checks.append(("PASS " if ok else "FAIL ") + text)

    plugin = token_file().parent / "reflets-bridge.qml"
    where = "set REFLETS_TOKEN_FILE to reflets-token.txt in MuseScore's plugin folder if the folder is elsewhere"
    if plugin.exists():
        found = re.search(r"property int proto: (\d+)", plugin.read_text())
        proto = int(found[1]) if found else 0
        check(proto == PROTO, f"Plugin file {plugin}, protocol {proto}" + (
            "." if proto == PROTO else f"; this server speaks {PROTO}. Install the plugin file that came with this server and restart MuseScore."
        ))
    else:
        check(False, f"No plugin file at {plugin}. Copy plugin/reflets-bridge.qml there, or {where}.")
    token = token_file()
    check(token.exists(), f"Token file {token}." if token.exists() else f"No token file at {token}: run Plugins > Reflets Bridge, or {where}.")
    model = Path(draft.ANALYSISGNN_PYTHON).exists() and Path(draft.ANALYSISGNN_CHECKPOINT).exists()
    checks.append(f"PASS AnalysisGNN model {draft.ANALYSISGNN_CHECKPOINT}." if model else (
        f"NOTE No AnalysisGNN model at {draft.ANALYSISGNN_PYTHON} and {draft.ANALYSISGNN_CHECKPOINT}: analyze gives the "
        "notes table without a harmony draft. Set ANALYSISGNN_PYTHON and ANALYSISGNN_CHECKPOINT to install it."
    ))
    host, port = bridge.url.removeprefix("ws://").rsplit(":", 1)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 5)
        writer.close()
    except (OSError, asyncio.TimeoutError):
        check(False, f"Nothing listens on {bridge.url}: run Plugins > Reflets Bridge in MuseScore Studio 4.7. "
              "If it shows a message that the WebSocket API is missing, this MuseScore build cannot run Reflets.")
        return "\n".join(checks)
    check(True, f"Something listens on {bridge.url}.")
    try:
        _, lines = await bridge.request("info")
    except BridgeError as error:
        if str(error).startswith(NOT_RUNNING):
            check(False, "What listens on the port does not answer as the Reflets bridge. Another plugin that uses "
                  "the WebSocket server may have been run after the bridge: restart MuseScore and run only Plugins > Reflets Bridge.")
        else:
            check(False, str(error))
        return "\n".join(checks)
    version = bridge.hello.get("mscore", "0").rjust(5, "0")
    check(True, f"Bridge {bridge.hello.get('plugin', '?')} answers on protocol {bridge.hello.get('proto')}.")
    check(True, f"MuseScore {int(version[:-4])}.{int(version[-4:-2])}.{int(version[-2:])}.")
    check(True, f'Score open: "{parse_info(lines).title}".')
    return "\n".join(checks)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
