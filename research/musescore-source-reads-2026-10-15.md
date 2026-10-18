# MuseScore source reads, 2026-10-15

Direct reads of MuseScore Studio source to close the design questions the 2026-10-14 research left open on paper: action codes per version, what `Cursor.addNote` does to existing content, where the cursor lands, how ties toggle, how measure numbers are derived, and the exact N1 grammar. No MuseScore was run; everything here is source, and section 7 lists what still needs a running MuseScore.

Method: raw file fetches at tags `v4.4.4`, `v4.6.2`, `v4.7.5`, plus a blob-less partial clone of tag `v4.7.5` (commit `3654226`) to list `src/engraving/editing/`. The analysis engine was read from `Vedat-Ozkan/sheet-music-analysis` at commit `02c13ec` (2026-10-12). Line numbers are of the file at the named tag.

## 1. Action codes by version

Read from `src/notation/internal/notationuiactions.cpp` (4.4.4, 4.6.2), `src/notationscene/internal/notationuiactions.cpp` (4.7.5), `src/playback/internal/playbackuiactions.cpp` and `src/project/internal/projectuiactions.cpp` at each tag.

| Action | 4.4.4 | 4.6.2 | 4.7.5 |
|---|---|---|---|
| undo | `undo` (notation:572) | `undo` (notation:579) | `action://notation/undo` (notationscene:2659) |
| redo | `redo` (:579) | `redo` (:586) | `action://notation/redo` (:2666) |
| tie | `tie` (:2317) | `tie` (:2424) | `tie` (:2429) |
| chord-tie | `chord-tie` (:1214) | `chord-tie` (:1284) | `chord-tie` (:1289) |
| insert-measures | `insert-measures` (:659) | `insert-measures` (:692) | `insert-measures` (:697) |
| append-measures | `append-measures` (:683) | `append-measures` (:716) | `append-measures` (:721) |
| play / stop / rewind | `play` `stop` `rewind` (playback:35,42,49) | same (:35,42,56) | same (:39,67,74) |
| file-export | `file-export` (project:99) | `file-export` (:99) | `file-export` (:100) |
| delete / cancel | `delete`, `escape` (bare) | bare | `action://notation/delete` (:105), `action://notation/cancel` (:112) |

At 4.7.5 the notation table has 409 bare codes and 7 `action://notation/...` codes; undo, redo, delete and cancel are among the namespaced ones, tie and the measure actions are not. `PluginAPI::cmd` maps `escape` and `delete` to the namespaced codes itself (api matrix, `cmd` row) but not `undo`. The tie action is registered at 4.7.5 as `registerAction("tie", &Controller::addTie)` in `src/notationscene/internal/notationactioncontroller.cpp:233`, with `UNDO_ACTION_CODE = "action://notation/undo"` at line 52 of the same file.

Consequence: the only version branch the bridge needs for v1 is undo (and redo). `tie`, `play`, `stop`, `file-export`, `append-measures` are stable across 4.4.4 to 4.7.5.

## 2. Cursor and note entry: what a write does

`src/engraving/api/v1/cursor.cpp` at v4.7.5 (the 4.4.4 bodies read are the same apart from `_score` naming):

- `Cursor::addNote(pitch, addToChord)` (445-460): rejects an invalid pitch, requires `segment()` to be set ("use rewind() to define its location"), substitutes a quarter if no duration is set, then calls `m_score->addPitch(nval, addToChord, is.get())`. It returns nothing.
- `Cursor::addRest()` (470-480): same guards, then `m_score->enterRest(duration, is.get())`.
- `Cursor::setDuration(z, n)` (582-589): an invalid fraction becomes a quarter silently.
- `Cursor::rewindToTick(tick)` (165-178): `tick2leftSegment(tick + 1)`, re-filtered by segment type, then `setSegment(seg)` and `nextInTrack()`. There is no null check on `seg` before `seg->segmentType()` (171), so a tick past the end of the score dereferences null.
- `Cursor::nextInTrack()` (813-821): advances `seg = seg->next1(filter)` while `!seg->element(track)`. So after any rewind the cursor sits on the first segment at or after the tick that already holds a chord or rest in the cursor's track. In a voice with no content that is the end of the score (null segment), and in a voice with content it can be a later tick than asked.
- `Cursor::setTrack(track)` (694-701) only sets the input state's track, clamped to `ntracks - 1`; it does not move the segment. `setStaffIdx` (744-748) and `setVoice` (716-720) are arithmetic on `setTrack`.
- `Cursor::currentElement()` (641-646) is `segment()->element(track())`; `Cursor::segment()` (776-779) is `inputState().segment()`.
- `Cursor::inputState()` (86-89) returns the cursor's own `InputState` in `INPUT_STATE_INDEPENDENT` mode and the score's shared one in `INPUT_STATE_SYNC_WITH_SCORE` (`setInputStateMode`, 95-104).

`Score::addPitch(NoteVal&, bool addFlag, InputState*)` in `src/engraving/dom/noteentry.cpp` at v4.7.5 (171-277):

- With `addFlag` (176-182): takes the chord-rest at `is.lastSegment()->element(is.track())`, returns null unless it is a chord, and adds the pitch to it via `addPitchToChord` (279-322). `lastSegment` is the segment of the previous `addNote` (`InputState::moveToNextInputPos`, `src/engraving/dom/input.cpp:395-402`, stores `m_lastSegment = m_segment` before advancing).
- Without it: `expandVoice(is.segment(), is.track())` (185), `handleOverlappingChordRest` if there is no chord-rest at the input position (203-205), then `setNoteRest(is.segment(), track, nval, duration, ...)` (229-231) and `note = upNote()` of the new chord (233). Finally `is.moveToNextInputPos()` (273), so after `addNote` the cursor's segment is the next input position, not the chord just written.
- `InputState::nextInputPos()` (`input.cpp:377-388`): the next ChordRest segment that has an element in the track, or the first segment of the next measure.

`Score::setNoteRest` lives in `src/engraving/editing/cmd.cpp:1093` at v4.7.5 and in `src/engraving/dom/cmd.cpp:1065` at v4.6.2, where the body was read (1065-1214):

- `makeGap(segment, track, sd, tuplet)` (1088) carves the requested duration out of the existing content of the voice ("the returned gap ends at the measure boundary or at tuplet end"). Existing notes and rests under the new duration are removed or shortened. So `addNote` overwrites; it never inserts time.
- The gap is filled with a duration list (1097-1102); when one written duration needs more than one notated value, the pieces are tied automatically (1147-1153).
- If the duration runs past the bar (1174-1206), it continues into the next measure's segment and ties across the bar line (1200-1206); in voices 2 to 4 with nothing there it first adds a full-measure rest (1189-1195); in voice 1 with nothing there it stops ("no rest in voice 0").
- `Score::expandVoice(Segment*, track)` (`src/engraving/editing/cmd.cpp:641-701` at 4.7.5): when the segment has no element in the track, fills the voice with rests from the previous chord-rest (or the bar start) up to the segment, and from the segment to the next chord-rest or the bar end. This is what lets voices 2 to 4 receive their first note.
- `Score::handleOverlappingChordRest` (`noteentry.cpp:540-565`): if the previous chord-rest in the track extends past the input tick, shortens it and fills the difference with tied notes.

Consequences for the bridge:

1. Writes must be sequential per voice and bar, in note-entry order: land the cursor once, then `setDuration` and `addNote`/`addRest` for each event; the cursor advances by itself to the next input position. Random access by `rewindToTick` per event is wrong, because `nextInTrack` moves to wherever the voice next has content.
2. Landing: rewind with the cursor's track set to voice 1 of the target staff (voice 1 always has a chord-rest at the first ChordRest segment of a bar), then `setTrack` to the target voice. `setTrack` keeps the segment; `expandVoice` then creates the rests the empty voice needs.
3. Durations must fit the bar; an overlong one spills into the next bar with an auto-tie, which the read-back would report as extra notes.
4. The note just written is not `cursor.element`. Find it by tick after the pass: `score.findSegmentAtTick` or a segment walk, then `elementAt(track)` and `notes`; set `tpc1`/`tpc2` there.
5. `addNote(pitch, true)` adds to the chord at `lastSegment`, which is the previous `addNote`'s chord, so chord members follow their first note immediately.
6. The server validates ticks against the score length before any `rewindToTick` (null dereference at `cursor.cpp:171`).

## 3. Undo lock and nested commands

`src/engraving/editing/cmd.cpp` at v4.7.5: `Score::startCmd` returns at once if `undoStack()->isLocked()` (344-348) and `Score::endCmd` likewise (406-410); `UndoStack::beginMacro` also returns when locked (`src/engraving/editing/undo.cpp:292-296`). The plugin's `Score.startCmd` locks the stack (api matrix, undo transaction row), so any `startCmd`/`endCmd` pair that an action runs internally, such as the tie command's own (section 4), is a no-op inside the plugin's command and the whole write is one macro.

Also in `endCmd` (418-424): a non-warning `MScore::_error` forces a rollback, and rollback unwinds the active macro. The lock means the plugin's `endCmd(rollback)` is the one that decides.

## 4. Ties

- The `tie` action at 4.7.5 calls `NotationInteraction::addTieToSelection` (`src/notation/internal/notationinteraction.cpp:5477-5487`), which is `score()->cmdToggleTie()` plus a change notification.
- `Score::cmdTieNoteList` (`src/engraving/editing/edit.cpp:2005` at 4.7.5, identical to `src/engraving/dom/edit.cpp:1951-1967` at 4.6.2): with a single selected note outside note-entry mode the list is that one note (1953-1958); a selected chord gives all its notes; otherwise the selection's note list.
- `Score::cmdToggleTie` at 4.6.2 (`dom/edit.cpp:2114-2218`): for each listed note, if it already has `tieFor` the tie is removed (2165-2173, the toggle); otherwise `searchTieNote(n)` finds a successor (2133) and a tie is created to it (2158-2162). With two or more selected notes it also ties same-pitch pairs inside the selection (2182-2212).
- At 4.7.5 (`editing/edit.cpp:2175`) the body differs in one way that matters: when every selected note is at the same tick and none has a successor to tie to, it calls `cmdAddTie()` and returns, which is the note-entry behaviour of adding a new tied note. So the bridge must never dispatch `tie` unless the successor note already exists.
- At 4.4.4 (`dom/edit.cpp:1987-2040`): same core, a tie is added to the found successor (2015-2029) else existing ties are removed (2030-2037).
- `searchTieNote` (`src/engraving/dom/utils.cpp:576-`): takes the next ChordRest segment at or after the chord's end tick (586-591), then looks for a same-pitch note in any track of the same part on the same staff at that segment (641-664), with grace-note handling (601-637).
- All three versions call `startCmd`/`endCmd` inside the toggle, which section 3 shows is harmless under the plugin's lock.

Consequence: the procedure in the spec (select the first note alone, check `tieForward` is null, dispatch `tie`, read back) is correct on all three versions, with the added rule that the successor must exist before dispatch.

## 5. Measure numbering

`src/engraving/rendering/score/measurelayout.cpp` at v4.7.5:

- `adjustMeasureNo` (1189-1203): `measureNo += noOffset; m->setNo(measureNo); if (!irregular) ++measureNo;` and a section break with "start with measure one" resets the counter to 0 (1197-1200).
- The displayed number is `no() + 1` (1327, 1377).

`src/engraving/dom/measurebase.h`: `no()`/`setNo` (144-145), `noOffset()` (146-147), `irregular()` (158). The plugin wrapper (`src/engraving/api/v1/elements.h`, `MeasureBase`) exposes `no` read-only and `noOffset`, `irregular` as writable properties.

Consequences: `no` already has the offset folded in; the user sees `no + 1`. An irregular measure (a pickup marked "exclude from measure count") does not advance the counter, so the pickup and the first full bar carry the same `no`. The plugin must send `irregular` with each measure; the server labels an irregular bar that precedes a bar with the same `no` as bar 0, matching the engine's pickup convention (`engine/score.py:60`). `no` is assigned during layout, which `endCmd` triggers; adding notes does not change it.

## 6. The N1 grammar (`engine/notes.py` at `02c13ec`)

- Header: `N1 div=<ppq> ts=<n>/<d> ks=<key>` (62). Measure header: `m<number> len=<units>` with ` ts=` appended when the meter changes (65-68). Voice line: `<staff>.<layer>: ` then tokens (75).
- Tokens (86-108): a bare integer sets the duration in `div` units for what follows (103-105); `r` is a rest of the current duration, written only as a gap before the next note (95-98); `+` joins chord members (94); a leading `g` marks a grace attack, one token per attack, grace chords with `+` (99-101); a trailing `~` ties to the next note (94). Pitches are spelled sounding pitches like `Eb4` (score.py:40, notes.py:19).
- Trailing silence is not written: `_voice` only emits a gap when a later note starts (95-98).
- Decode (111-148): the first line must start with `N1 ` (116-117); `r` advances the cursor and creates no event (157-159); a token that is not a digit, `r`, or a pitch group raises (164-165); the result is `ScoreIndex.from_measures` (148).
- `Event.pitch` is `None` for a rest (`score.py:40`), so the model can hold rests; today the decoder just does not create them.
- Tests: round trip on the Chopin nocturne (`tests/test_notes.py:25-26`), size under 6,000 characters for the whole piece and 1,500 for bars 1-8 (29-31), pickup handling (34-38), ties, grace notes and rests in the text (41-45).
- `encode`/`decode` are used by `server/app.py`, `engine/draft.py`, `engine/correct.py` and the model runner, so N1 itself must stay backward compatible.

Consequences for N1x: rests need no new token; the change is that decode creates rest events and that silence between the last token and `len` is a rest. Part headers, dynamics and chord symbols are new tokens that today's decoder rejects, so N1x is a strict superset parsed by a new decoder, and `encode` keeps producing plain N1 unless asked for N1x.

## 7. Still runtime-only

Nothing here replaces running MuseScore for: `writeScore`/`readScore` behaviour, export dialogs, the WSLg launch, `fp` walk timing, the WebSocket API in the owner's 4.4.3 build, annotation text set after `cursor.add`, and whether grace notes can be written at all. Also not done: Claude-tokenizer counts for N1 on polyphonic scores, which need an API key this session does not have.
