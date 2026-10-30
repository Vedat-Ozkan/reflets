from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from fractions import Fraction
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
from reflets.restore import bare_idea, body, marks, target_idea, writable
from reflets.bridge import NOT_RUNNING, PROTO, Bridge, BridgeError, Bridges, chosen, token_file
from reflets.score import ScoreInfo, appended, build_index, key_name, parse_info
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
        "3:2{ 4 C5 D5 E5 } is a tuplet, three notes in the time of two; the numbers inside are the time each note "
        "really takes, in div units, with the ratio already applied, so at div=12 that is an eighth-note triplet "
        "filling one quarter: do not scale them again. [stacc]{ … } gives "
        "every note inside the decoration; a duration number carries across braces. "
        "Lines open just before the note they start on and close just after the note they end with, or with @, "
        "possibly in a later bar: ( ) slur, <( <) and >( >) hairpins, cresc( and dim( lines, ped( pedal, 8va( 8vb( "
        "15ma( octave lines (pitches stay sounding), tr( trill line, line\"…\"( text line, tempo\"rit.\"( tempo change; "
        "a number after the parenthesis pairs two ends that would otherwise pair with another line's, (2 … )2. "
        "A 'staff.voice Ln:' line under a voice line gives verse n's lyrics, one syllable per note, graces and rests "
        "skipped: a trailing '-' continues the word, '_' holds the syllable over the note, '*' marks a note without one. "
        "'m9 = m1' means bar 9 is bar 1 again, every line and field; '2.1 = m1' means this voice line is bar 1's. "
        "check lists part-writing faults such as parallel fifths in chorale-style bars, analyze drafts the harmony, "
        "render shows bars as an image, with check's findings drawn on it if asked; hum records the user humming a line into a staff. checkpoint saves the whole score "
        "under a name, to come back to later; keep saves one too; restore writes chosen bars back as a checkpoint has them. "
        "To try an idea, write it in the same form with propose; it lands in the score in colour as one undo step. "
        "The user listens in MuseScore, then you call keep or discard as they decide. Before you say which note "
        "sounds where, find the bar and count through its voice line from the start of the bar; answers given "
        "at a glance are often wrong."
    ),
)
bridge = Bridges()


class Unchanged(ToolError):
    pass


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
    title: str
    steps: int = 1


render_numbers = itertools.count(1)


def read_only(title: str) -> ToolAnnotations:
    return ToolAnnotations(title=title, read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


async def windows() -> list[tuple[Bridge, ScoreInfo]]:
    found = []
    for window in bridge.found():
        try:
            _, lines = await window.request("info")
        except BridgeError:
            continue
        found.append((window, parse_info(lines)))
    return found


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
        "bar count, meter, key and pickup, and its checkpoints by number, name and time, with their files. When MuseScore is not reachable it says why, with a checklist of the plugin "
        "file, its token file, the harmony model, the port and the bridge's answer, each passed or failed with what "
        "to do: tell the user what it says."
    ),
    annotations=read_only("Score info"),
    meta={"anthropic/alwaysLoad": True},
    structured_output=False,
)
async def score_info() -> str:
    try:
        _, lines = await bridge.request("info")
    except BridgeError as error:
        return f"{error}\n\n{await diagnose()}" if bridge.socket is None else str(error)
    info = parse_info(lines)
    hello = bridge.hello
    version = hello.get("mscore", "0").rjust(5, "0")
    parts = "; ".join(
        f"P{n} {name} (staff {staves[0]})" if len(staves) == 1 else f"P{n} {name} (staves {staves[0]}-{staves[-1]})"
        for n, (name, staves) in enumerate(info.parts, 1)
    )
    first, last = info.measures[0].number, info.measures[-1].number
    changes = f", key changes at {len(info.keys) - 1} bars" if len(info.keys) > 1 else ""
    others = [f'"{other.title}"' for window, other in await windows() if window is not bridge.current] if len(bridge.found()) > 1 else []
    elsewhere = (
        f"\nAlso open in other MuseScore windows: {', '.join(others)}. Tools act on the window the user used last; to work "
        "on another score, the user clicks into its window." if others else ""
    )
    return (
        f"MuseScore {int(version[:-4])}.{int(version[-4:-2])}.{int(version[-2:])}, "
        f"Reflets bridge {hello.get('plugin', '?').split('/')[-1]}, connected.\n"
        f'"{info.title}": {len(info.parts)} part(s): {parts}. Bars {first}-{last} '
        f"({'with' if first == 0 else 'no'} pickup), meter {info.measures[0].meter}, key {info.key}{changes}.\n"
        f"{listed_checkpoints(info)}{elsewhere}"
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
    missing = missing_model()
    if missing:
        return table + f"\n\nNo harmony draft: the optional AnalysisGNN model is not installed ({missing}). Analyse from the table."
    try:
        result = await asyncio.to_thread(draft.draft, index)
    except draft.DraftError as error:
        return table + f"\n\nNo harmony draft: {error}. Analyse from the table."
    return table + "\n\n" + draft.as_text(result, first, last)


def missing_model() -> str:
    paths = [os.environ.get(name) for name in ("ANALYSISGNN_PYTHON", "ANALYSISGNN_CHECKPOINT")]
    if not all(paths):
        return "ANALYSISGNN_PYTHON and ANALYSISGNN_CHECKPOINT are not set"
    gone = [path for path in paths if not Path(path).exists()]
    return f"nothing at {' or '.join(gone)}" if gone else ""


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
    if first > last:
        raise ToolError(f'bars runs from the lower bar to the higher one, as in "{last}-{first}"')
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
        "An idea may go past the last bar: the bars it needs are appended in the same undo step. "
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
    return await write_idea(idea, label, replace, recast)


async def write_idea(idea: str, label: str, replace: bool, recast: bool = False, drawn: list[str] = ()) -> str:
    info = await load_info()
    division = int(bridge.hello["division"])
    staves = max(staff for _, part_staves in info.parts for staff in part_staves)
    numbers = [measure.number for measure in info.measures]
    try:
        try:
            past = max(bar.number for bar in n1x.decode(idea).bars) - numbers[-1] if not recast else 0
        except (n1x.DecodeError, ValueError):
            past = 0
        if past > 0:
            closing = info.bars[-1].user_barline_type if info.bars[-1].user_barline_type not in n1x.REPEAT_BARLINES else None
            info = appended(info, past, division, closing)
            numbers = [measure.number for measure in info.measures]
        start_tick, end_tick = idea_range(idea, info)
        original = pre = await request(f"read {start_tick} {end_tick}")
        if past > 0:
            pre = pre + [f"R {info.ticks[p]} {staff * 4} {info.lengths[p] / 4}" for p in range(len(info.ticks) - past, len(info.ticks)) if info.ticks[p] >= start_tick for staff in range(staves)]
        view = recast_view(idea, info, pre, division) if recast else None
        if view:
            reach = meter_reach(info, view.positions[-1])
            span = (view.after, info.ticks[reach] if reach < len(info.ticks) else 2**31 - 1 - view.delta)
            info, pre = view.info, view.pre
        else:
            span = meter_span(idea, info)
        later = await request(f"read {span[0]} {span[1]}") if span else []
        plan = compile_idea(idea, info, division, staves, pre, later, view.positions if view else range(0), drawn)
        add_lines(plan, pre, info)
    except IdeaError as error:
        raise ToolError(str(error)) from None
    if not plan.ops:
        raise Unchanged("The idea changes nothing in the score, so nothing was written.")
    if view:
        plan.ops[0:0] = view.ops
        plan.meters = dict.fromkeys(view.positions, view.meter)
    if past > 0:
        plan.ops[0:0] = [f"m {past}"] + ([] if info.bars[-past - 1].repeat_end else [f"b {info.ticks[-past - 1]} bar 1"]) + ([f"b {info.ticks[-1]} bar {closing}"] if closing else [])
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
    tracks = sorted({t for _, t in plan.cells})
    proposal_id = opened(Proposal(label, plan.start_tick, plan.end_tick, tracks, bars, original, reply, end_tick, info.title))
    counts = ", ".join(f"{n} {what if n > 1 else what[:-1]}" for what, n in plan.counts.items() if n)
    voices = ", ".join(f"{t // 4 + 1}.{t % 4 + 1}" for t in tracks)
    cut = sorted(set(cut) | plan.cut_ties)
    note = f" The tie into or out of bar(s) {', '.join(map(str, cut))} was cut, as the idea replaced its note." if cut else ""
    if past > 0:
        added = f"Bar {numbers[-1]} was" if past == 1 else f"Bars {numbers[-past]}-{numbers[-1]} were"
        note += f" {added} added at the end of the score; discard removes {'it' if past == 1 else 'them'} again."
    if plan.dropped:
        note += f" These syllables had no note left and were removed: {'; '.join(plan.dropped)}."
    if plan.dropped_marks:
        note += f" These fermatas lost their note and were removed, as the note or rest sounding at their moment has its own or none sounds there: {'; '.join(plan.dropped_marks)}."
    if plan.moved_marks:
        note += f" These fermatas lost their note and moved onto the note or rest sounding at their moment: {'; '.join(plan.moved_marks)}."
    return (
        f'Written: {bars}, voices {voices}, {counts}, as one undo step "Reflets: {label}". Read-back matched.{note}\n'
        f"The new notes are blue. The user listens with Play in MuseScore; then keep(\"{proposal_id}\") turns them "
        f"black, or discard(\"{proposal_id}\") removes them.\nproposal id: {proposal_id}"
    )


def moved(lines: list[str], then: ScoreInfo, now: ScoreInfo, first: int, last: int) -> list[str]:
    result, numbers, then_numbers = [], [m.number for m in now.measures], [m.number for m in then.measures]
    for number in numbers[numbers.index(first) : numbers.index(last) + 1]:
        position, then_position = numbers.index(number), then_numbers.index(number)
        start, end = then.ticks[then_position], then.ticks[then_position] + then.lengths[then_position] * int(bridge.hello["division"])
        bar = [line for line in lines if line.startswith("C ") and start <= int(line.split(" ")[1]) < end]
        result += shifted(bar, now.ticks[position] - start)
    return result


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


def proposals_file() -> Path:
    return token_file().parent / "proposals.json"


def stored() -> dict:
    path = proposals_file()
    return json.loads(path.read_text()) if path.exists() else {"next": 1, "open": {}}


def opened(proposal: Proposal) -> str:
    data = stored()
    proposal_id = f"p{data['next']}"
    data["next"] += 1
    data["open"][proposal_id] = asdict(proposal)
    proposals_file().write_text(json.dumps(data))
    return proposal_id


def closed(proposal_id: str) -> Proposal:
    data = stored()
    proposal = Proposal(**data["open"].pop(proposal_id))
    proposals_file().write_text(json.dumps(data))
    return proposal


async def find(proposal_id: str) -> Proposal:
    found = stored()["open"]
    if proposal_id not in found:
        open_ids = ", ".join(found) or "none"
        raise ToolError(f"There is no open proposal {proposal_id!r} (open: {open_ids}).")
    p = Proposal(**found[proposal_id])
    holding = [window for window, info in await windows() if info.title == p.title] if len(bridge.found()) > 1 else []
    if len(holding) > 1:
        raise ToolError(f'"{p.title}" is open in {len(holding)} MuseScore windows, so {proposal_id} cannot be found. '
                        "Ask the user to close the other copies. Nothing was done.")
    if holding:
        chosen.set(holding[0])
    title = (await load_info()).title
    if p.title != title:
        raise ToolError(f'{proposal_id} was written in "{p.title}", but "{title}" is open in MuseScore. Nothing was done.')
    return p


async def gone(proposal_id: str, p: Proposal) -> str:
    if sorted(await request(f"read {p.start_tick} {p.pre_end}")) != sorted(p.pre):
        return ""
    closed(proposal_id)
    return (
        f"{proposal_id} is no longer in the score: {p.bars} are as they were before it, undone in MuseScore or the "
        "score reopened. It is closed now; nothing changed."
    )


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
    p = await find(proposal_id)
    span = f"read {p.start_tick} {p.end_tick}"
    if sorted(await request(span)) != sorted(p.post):
        if left := await gone(proposal_id, p):
            return left
        raise ToolError(
            f"{p.bars.capitalize()} changed since {proposal_id} was written, so undoing would remove the user's edit. "
            "Nothing was undone; the user can use Ctrl+Z in MuseScore."
        )
    for _ in range(p.steps):
        await request("undo")
    if sorted(await request(f"read {p.start_tick} {p.pre_end}")) != sorted(p.pre):
        for _ in range(p.steps):
            await request("redo")
        restored = sorted(await request(span)) == sorted(p.post)
        raise ToolError(
            f"The last step in MuseScore's undo history was not {proposal_id}"
            + (", so it was redone and nothing changed." if restored else ", and redoing it did not restore the bars; ask the user to check them.")
            + " The user can remove the idea with Edit > Undo."
        )
    closed(proposal_id)
    return f"Discarded {proposal_id}: the score is back as it was in {p.bars}."


@mcp.tool(
    title="Keep an idea",
    description="Use this when the user keeps a proposed idea: its notes turn from blue to black.",
    annotations=writes("Keep an idea", destructive=False),
    structured_output=False,
)
async def keep(proposal_id: str) -> str:
    p = await find(proposal_id)
    if left := await gone(proposal_id, p):
        raise ToolError(left)
    tracks = ",".join(map(str, p.tracks))
    await request(f"color {p.start_tick} {p.end_tick} {tracks} #000000 keep {p.label}")
    closed(proposal_id)
    try:
        saved = await save_checkpoint(f"keep {p.label}")
    except (ToolError, OSError) as error:
        saved = f"No checkpoint was saved: {error}"
    return f'Kept {proposal_id}: the notes in {p.bars} are black now (one undo step, "Reflets: keep {p.label}").\n{saved}'


LONGEST_TAKE = 40
CALIBRATION_CLICKS = 8
HUM_SETUP = (
    "Humming needs the audio extra: install Reflets with uvx --from 'reflets[hum] @ git+…' (see the README); on Linux "
    "and WSL also sudo apt install libportaudio2 libasound2-plugins, with ~/.asoundrc routing to pulse."
)
NO_RECORDING = "Recording failed: {}. Check that the microphone and speakers or headphones are connected and that no other app holds them."


def tempo_at(info: ScoreInfo, position: int) -> float | None:
    for at, bar in reversed(list(enumerate(info.bars[: position + 1]))):
        tempos = [mark for mark in bar.marks if mark.kind == "Tempo" and (at < position or mark.onset == 0)]
        if tempos:
            return float(max(tempos, key=lambda mark: mark.onset).value) * 60
    return None


def key_at(info: ScoreInfo, tick: int) -> int:
    name = max(((at, key) for at, key in info.keys.items() if at <= tick), default=(0, info.key))[1]
    return 0 if name == "0" else int(name[:-1]) * (1 if name.endswith("s") else -1)


@mcp.tool(
    title="Hum a line",
    description=(
        "Use this when the user wants to hum, sing or 'da' a melody, bass line or rhythm into the score. It plays one "
        "bar of count-in clicks (beat 1 higher) through the computer's speakers or headphones, then records the "
        "microphone for `bars` bars while the click goes on, turns the humming into notes on the click's grid, and "
        "writes them as a proposal like propose does: blue, one undo step, then keep or discard. Before calling, tell "
        "the user to get ready: hum after the count-in, along with the click, giving each note its own push; any "
        "syllable or plain humming works, 'da' helps repeated notes. The call blocks while they hum. "
        "start_bar is where the first downbeat lands; staff is the staff number as in read_score's voice lines "
        "(the flute's staff, say); bars past the end are appended. tempo defaults to the score's tempo at start_bar, "
        "else 90, in quarter notes per minute; the meter is the score's. grid=2 snaps to eighths (best for most "
        "tunes), grid=4 to sixteenths. The notes go to the instrument's middle register; octave=1 or -1 moves "
        "them. kind='rhythm' writes only the rhythm, on one pitch. If the score has no notes and its key is C, the "
        "key heard is written as the key signature; if the score has notes in another key, the humming is moved "
        "to that key, as most people hum in a key of their own. replace=True as for propose. calibrate=True "
        "measures the delay between click and microphone instead: 8 clicks, the user says 'ta' on each; needed once "
        "per audio device when using headphones, since on speakers each take measures the delay from its own clicks."
    ),
    annotations=writes("Hum a line", destructive=True),
    structured_output=False,
)
async def hum(
    start_bar: int = 1, staff: int = 1, bars: int = 4, tempo: float | None = None, grid: int = 2, octave: int = 0,
    kind: str = "line", replace: bool = False, calibrate: bool = False,
) -> str:
    try:
        from reflets import audio, hum as humming
        import sounddevice  # noqa: F401
    except (ImportError, OSError):
        raise ToolError(HUM_SETUP) from None
    if tempo is not None and not 20 <= tempo <= 300:
        raise ToolError("tempo is 20 to 300 quarter notes per minute.")
    folder = token_file().parent
    if calibrate:
        beat = 60 / (tempo or 90)
        play, starts = audio.click_track(beat, 4, CALIBRATION_CLICKS)
        try:
            take = await asyncio.to_thread(audio.record, play, starts)
        except Exception as error:
            raise ToolError(NO_RECORDING.format(error)) from None
        found = humming.calibration(take.audio, [start / audio.RATE for start in starts])
        if found is None:
            raise ToolError("Not enough 'ta's were heard on the clicks to measure the delay. Ask the user to try again, louder, one 'ta' on each click.")
        audio.store_latency(folder, take.device, found)
        return f"Calibrated: the microphone hears the user {1000 * found:.0f} ms after each click on {take.device}. Takes on this device use it."
    if grid not in (2, 4) or kind not in ("line", "rhythm") or not 1 <= bars <= 32:
        raise ToolError("grid is 2 or 4, kind is 'line' or 'rhythm', bars is 1 to 32.")
    info, index, *_ = await read_bars("all")
    numbers = [measure.number for measure in info.measures]
    if start_bar not in numbers and start_bar != numbers[-1] + 1:
        raise ToolError(f"Bar {start_bar} does not exist; the score has bars {numbers[0]} to {numbers[-1]}.")
    parts = [(instrument, staves) for (_, staves), instrument in zip(info.parts, info.instrument_ids)]
    owner = next(((instrument, staves) for instrument, staves in parts if staff in staves), None)
    if owner is None:
        raise ToolError(f"Staff {staff} does not exist; the score has staves 1 to {max(s for _, staves in parts for s in staves)}.")
    position = numbers.index(start_bar) if start_bar in numbers else len(numbers) - 1
    covered = info.measures[position:position + bars]
    if any(measure.meter != info.measures[position].meter for measure in covered):
        raise ToolError("The meter changes inside those bars; hum fewer bars, up to the change.")
    taken = [measure.number for measure in covered if measure.number >= start_bar and any(
        event.pitch and event.staff == staff and event.layer == 1 for event in measure.events)]
    if taken and not replace:
        raise ToolError(f"Staff {staff} already has notes in bar(s) {', '.join(map(str, taken))}. Ask the user, then call again with replace=True, before they hum.")
    numerator, denominator = (int(x) for x in info.measures[position].meter.split("/"))
    marked = tempo_at(info, numbers.index(start_bar) if start_bar in numbers else len(numbers))
    tempo = tempo or marked or 90
    beat = 60 / tempo * 4 / denominator
    bar_quarters = Fraction(4 * numerator, denominator)
    if (bar_quarters * grid).denominator != 1:
        raise ToolError(f"A {info.measures[position].meter} bar is not a whole number of {'eighths' if grid == 2 else 'sixteenths'}"
                        + ("; use grid=4." if grid == 2 and (bar_quarters * 4).denominator == 1 else "; this meter cannot be hummed yet."))
    if (bars + 1) * numerator * beat > LONGEST_TAKE:
        raise ToolError(f"That take would last over {LONGEST_TAKE} seconds; hum fewer bars at a time.")
    play, starts = audio.click_track(beat, numerator, (bars + 1) * numerator)
    try:
        take = await asyncio.to_thread(audio.record, play, starts)
    except Exception as error:
        raise ToolError(NO_RECORDING.format(error)) from None
    heard = audio.echo(take, numerator)
    stored = audio.stored_latency(folder, take.device)
    if heard is not None:
        latency, timing = heard, "measured from the click this take"
    elif stored is not None:
        latency, timing = stored, "calibrated earlier"
    else:
        latency, timing = take.gap, "the driver's estimate, uncalibrated"
    first = starts[numerator]
    slots = int(bars * bar_quarters * grid)
    click_slots = max(1, int(grid * 4 // denominator))
    result = await asyncio.to_thread(humming.transcribe, take.audio[first:], 60 / tempo, grid, latency, slots, click_slots)
    if not result or not result.notes:
        raise ToolError("No humming was heard after the count-in. Check the microphone, then try again.")
    score_has_notes = any(event.pitch for measure in index.measures for event in measure.events)
    signature = key_at(info, info.ticks[position])
    pitches = [note.pitch for note in result.notes]
    moved, set_key = 0, None
    if score_has_notes:
        moved = humming.moved_to(result.key, signature)
        fifths = signature
    else:
        fifths = result.key.fifths if signature == 0 else signature
        if kind == "rhythm" and signature == 0:
            fifths = 0
        elif signature == 0 and fifths != 0:
            set_key = fifths
        elif signature != 0:
            moved = humming.moved_to(result.key, signature)
    instrument, staves = owner
    target = humming.centre(instrument, staves.index(staff), len(staves))
    shift = moved + humming.placed_octave([p + moved for p in pitches], target) + 12 * octave
    for note in result.notes:
        note.pitch = humming.tonic_near(target, result.key.tonic + moved) + 12 * octave if kind == "rhythm" else note.pitch + shift
    division = 48
    lines = humming.voice_lines(result.notes, [int(bar_quarters * grid)] * bars, division // grid, fifths)
    tempo_marks = []
    if marked is None or abs(marked - tempo) > 0.5:
        old = [mark for mark in info.bars[position].marks if mark.kind == "Tempo" and mark.onset == 0] if start_bar in numbers else []
        tempo_marks = ["-" + n1x.mark_token(mark) for mark in old] + [f"q{tempo:g}"]
    idea = [f"N1x div={division} ts={info.measures[position].meter}"]
    for n, line in enumerate(lines):
        header = f"m{start_bar + n} len={int(bar_quarters * division)}" + (f" ks={key_name(set_key)}" if n == 0 and set_key is not None else "")
        if n == 0 and tempo_marks and staff == 1:
            line = " ".join(tempo_marks + [line])
        idea += [header, f"{staff}.1: {line}"]
        if n == 0 and tempo_marks and staff != 1:
            idea.append("1.1: " + " ".join(tempo_marks))
    if saving := os.environ.get("REFLETS_HUM_SAVE"):
        audio.save(Path(saving), take, {
            "tempo": tempo, "meter": info.measures[position].meter, "bars": bars, "grid": grid, "latency": latency,
            "timing": timing, "start_bar": start_bar, "staff": staff, "instrument": instrument, "kind": kind,
            "key": result.key.name, "idea": "\n".join(idea),
        })
    written = await write_idea("\n".join(idea), "hummed", replace)
    heard_key = result.key.name + (" (or close to another key; check by ear)" if result.key.margin < 0.05 else "")
    notes = [
        f"Heard {len(result.notes)} notes in {heard_key}, the singer {100 * result.tuning:+.0f} cents off concert pitch; "
        f"tempo {tempo:g}, {'eighth' if grid == 2 else 'sixteenth'} grid, delay {1000 * latency:.0f} ms ({timing}).",
    ]
    if moved:
        notes.append(f"Moved {abs(moved)} semitone{'s' if abs(moved) > 1 else ''} {'up' if moved > 0 else 'down'} into the score's key.")
    if set_key is not None:
        notes.append("The key signature was set from the humming, from the first bar of the take on.")
    if tempo_marks:
        notes.append(f"The tempo mark was set to {tempo:g}, from bar {start_bar} on.")
    if timing.startswith("the driver"):
        notes.append("If the notes land late or early, the user is probably on headphones: run hum with calibrate=True once.")
    return " ".join(notes) + "\n" + written


def checkpoint_folder(title: str) -> Path:
    return token_file().parent / "checkpoints" / file_name(title or "untitled")


def file_name(text: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", " ".join(text.split())).strip(" .")[:80]


async def save_checkpoint(name: str) -> str:
    info_lines = await request("info")
    info = parse_info(info_lines)
    folder = checkpoint_folder(info.title)
    folder.mkdir(parents=True, exist_ok=True)
    number = 1 + max((int(path.stem.split(" ", 1)[0]) for path in folder.glob("*.json")), default=0)
    stem = f"{number:03d} {file_name(name)}".rstrip()
    score = folder / f"{stem}.musicxml"
    await request(f"export {windows_path(score)}")
    lines = await request(f"read {info.ticks[0]} {2**31 - 1}")
    saved = datetime.now().strftime("%Y-%m-%d %H:%M")
    (folder / f"{stem}.json").write_text(json.dumps({"name": name, "saved": saved, "info": info_lines, "read": lines}))
    return f'Checkpoint {number} "{name}" saved: {windows_path(score)}'


@mcp.tool(
    title="Save a checkpoint",
    description=(
        "Use this when the user wants to mark the score as it is now, to come back to it later. It saves the whole "
        "score, unsaved changes and open ideas included, as a MusicXML file the user can open in MuseScore, under a "
        "name. keep saves one too, named after the idea kept."
    ),
    annotations=writes("Save a checkpoint", destructive=False),
    structured_output=False,
)
async def checkpoint(name: str) -> str:
    return await save_checkpoint(" ".join(name.split()) or "checkpoint")


def listed_checkpoints(info: ScoreInfo) -> str:
    folder = checkpoint_folder(info.title)
    found = sorted(folder.glob("*.json")) if folder.exists() else []
    if not found:
        return f'No checkpoints for "{info.title}" yet.'
    lines = [f'Checkpoints for "{info.title}":']
    for path in found:
        saved = json.loads(path.read_text())
        lines.append(f'{int(path.stem.split(" ", 1)[0])}. "{saved["name"]}", {saved["saved"]}: {windows_path(path.with_suffix(".musicxml"))}')
    return "\n".join(lines)


@mcp.tool(
    title="Restore bars from a checkpoint",
    description=(
        "Use this when the user wants bars back as they were at a checkpoint: it writes them as the checkpoint has "
        'them, notes, marks, decorations, lines and lyrics, as a proposal. checkpoint is its number, which score_info '
        'lists; bars is a range like "5-12" or "all". '
        "Bars outside it keep the user's later edits. Refused when a bar's length changed since; then the user can "
        "open the checkpoint's file."
    ),
    annotations=writes("Restore bars from a checkpoint", destructive=True),
    structured_output=False,
)
async def restore(checkpoint: int, bars: str) -> str:
    info, index, first, last, _ = await read_bars(bars, whole_score=True)
    folder = checkpoint_folder(info.title)
    found = [path for path in folder.glob(f"{checkpoint:03d}*.json") if path.stem.split(" ", 1)[0] == f"{checkpoint:03d}"]
    if not found:
        raise ToolError(f"There is no checkpoint {checkpoint}. " + listed_checkpoints(info))
    saved = json.loads(found[0].read_text())
    then_info = parse_info(saved["info"])
    numbers, then_numbers = [m.number for m in info.measures], [m.number for m in then_info.measures]
    for number in numbers[numbers.index(first) : numbers.index(last) + 1]:
        if number not in then_numbers or then_info.lengths[then_numbers.index(number)] != info.lengths[numbers.index(number)]:
            raise ToolError(
                f"Bar {number} is not the same length as in checkpoint {checkpoint}, so it cannot be restored in place. "
                f"The user can open {windows_path(found[0].with_suffix('.musicxml'))}."
            )
    then_index = build_index(then_info, saved["read"], int(bridge.hello["division"]))
    try:
        now, then = n1x.encode(info, index, first, last), n1x.encode(then_info, then_index, first, last)
    except (notes.NotesError, PositionError) as error:
        raise ToolError(f"Could not encode bars {first}-{last}: {error}") from None
    if body(now) == body(then):
        return f'Bars {first}-{last} are as in checkpoint {checkpoint} "{saved["name"]}" already.'
    label = f"restore {checkpoint}"
    try:
        cleared = re.search(r"proposal id: (p\d+)", await propose(bare_idea(body(now), now.splitlines()[0], marks(writable(then), then.splitlines()[0])), label, replace=True))[1]
    except Unchanged:
        cleared = None
    try:
        result = await write_idea(target_idea(body(now), writable(then), then.splitlines()[0]), label, True, drawn=moved(saved["read"], then_info, info, first, last))
    except ToolError as error:
        if cleared:
            await discard(cleared)
        raise ToolError(f"Bars {first}-{last} could not be restored, and nothing changed: {error}") from None
    proposal_id = re.search(r"proposal id: (p\d+)", result)[1]
    if cleared:
        a, b = closed(cleared), closed(proposal_id)
        proposal_id = opened(Proposal(label, b.start_tick, b.end_tick, sorted(set(a.tracks) | set(b.tracks)), b.bars, a.pre, b.post, a.pre_end, b.title, 2))
    note = result.split("Read-back matched.", 1)[1].split("\n", 1)[0]
    if body(then) != writable(then):
        note += " Glissandos cannot be written, so the checkpoint's are left out; they are in its file."
    where = f"bar {first}" if first == last else f"bars {first}-{last}"
    return (
        f'Restored {where} from checkpoint {checkpoint} "{saved["name"]}" ({saved["saved"]}), in {"two undo steps" if cleared else "one undo step"} '
        f'"Reflets: {label}". Read-back matched.{note}\nThe restored notes are blue. The user listens with Play in '
        f'MuseScore; then keep("{proposal_id}") turns them black, or discard("{proposal_id}") takes the bars back as '
        f"they were before.\nproposal id: {proposal_id}"
    )


async def diagnose() -> str:
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
    missing = missing_model()
    checks.append(f"NOTE No AnalysisGNN model ({missing}): analyze gives the notes table without a harmony draft. The model "
                  "is optional: set it up as sheet-music-plugin's README says (Draft model), then name its Python and checkpoint "
                  "with ANALYSISGNN_PYTHON and ANALYSISGNN_CHECKPOINT in the server's env." if missing else
                  f"PASS AnalysisGNN model {os.environ['ANALYSISGNN_CHECKPOINT']}.")
    first = bridge.first
    host, port = first.url.removeprefix("ws://").rsplit(":", 1)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), 5)
        writer.close()
    except (OSError, asyncio.TimeoutError):
        check(False, f"Nothing listens on {first.url}: run Plugins > Reflets Bridge in MuseScore Studio 4.7. "
              "If it shows a message that the WebSocket API is missing, this MuseScore build cannot run Reflets.")
        return "\n".join(checks)
    check(True, f"Something listens on {first.url}.")
    try:
        _, lines = await first.request("info")
    except BridgeError as error:
        if str(error).startswith(NOT_RUNNING):
            check(False, "What listens on the port does not answer as the Reflets bridge. Another plugin that uses "
                  "the WebSocket server may have been run after the bridge: restart MuseScore and run only Plugins > Reflets Bridge.")
        else:
            check(False, str(error))
        return "\n".join(checks)
    version = first.hello.get("mscore", "0").rjust(5, "0")
    check(True, f"Bridge {first.hello.get('plugin', '?')} answers on protocol {first.hello.get('proto')}.")
    check(True, f"MuseScore {int(version[:-4])}.{int(version[-4:-2])}.{int(version[-2:])}.")
    check(True, f'Score open: "{parse_info(lines).title}".')
    return "\n".join(checks)


def install_plugin() -> None:
    here = Path(__file__).parent
    plugin = next(path for path in (here / "reflets-bridge.qml", here.parent / "plugin" / "reflets-bridge.qml") if path.exists())
    folder = token_file().parent
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(plugin, folder / plugin.name)
    print(f"Copied the Reflets Bridge plugin to {folder}. In MuseScore, enable Reflets Bridge under Home > Plugins, "
          "then open a score and run Plugins > Reflets Bridge.")


def main() -> None:
    if sys.argv[1:] == ["install-plugin"]:
        install_plugin()
    else:
        mcp.run("stdio")


if __name__ == "__main__":
    main()
