# MuseScore 4.7.5: plugin read and write paths per element kind

Date 2026-10-18. Tag `v4.7.5` (commit `3654226`). Method: a blob-less sparse clone of `musescore/MuseScore` at the tag, read directly. Nothing was run against MuseScore. Every line number is of the file at that tag. **[inferred]** marks a conclusion that follows from code but depends on runtime behaviour that was not traced. Everything else was read in source.

Path keys:

| Key | File |
|---|---|
| cur | `src/engraving/api/v1/cursor.cpp` |
| el / elh | `src/engraving/api/v1/elements.cpp` / `elements.h` |
| se | `src/engraving/api/v1/scoreelement.cpp` |
| sc / sch | `src/engraving/api/v1/score.cpp` / `score.h` |
| sel | `src/engraving/api/v1/selection.cpp` |
| qpa | `src/engraving/api/v1/qmlpluginapi.cpp` |
| ed | `src/engraving/editing/edit.cpp` |
| cmd | `src/engraving/editing/cmd.cpp` |
| dsc | `src/engraving/dom/score.cpp` |
| seg | `src/engraving/dom/segment.cpp` |
| spn | `src/engraving/dom/spanner.cpp` |
| nac | `src/notationscene/internal/notationactioncontroller.cpp` |
| ni | `src/notation/internal/notationinteraction.cpp` |
| nus | `src/notation/internal/notationundostack.cpp` |

## 0. Mechanisms every table relies on

**W1: properties.** `API_PROPERTY*` setters go through `ScoreElement::set`. On a score-owned element that is `undoChangeProperty`. On a not-yet-added element (`newElement`, ownership PLUGIN) it is a plain `setProperty` with no undo (se:162-227, branch at 221-226). So on a new element, properties can be set before `cursor.add`, and spanner ticks must be set that way.

**W2: `newElement(type)` + `cursor.add(el)`.** `Cursor::add` refuses a SCORE-owned element, then sets the score, the cursor's track and the cursor's segment as parent, and switches on type (cur:271-431). Branches:

- ChordRest: `undoAddCR` (294).
- KEYSIG: KeySig segment, then `undoAddElement` (298-302).
- TIMESIG: `cmdAddTimeSig` (304-311).
- LAYOUT_BREAK: `MeasureBase::addInternal` (315-318).
- Parent becomes the measure for MEASURE_NUMBER, SPACER, JUMP, MARKER, HBOX and STAFFTYPE_CHANGE (321-331).
- `Chord::addInternal` on the cursor's current element, only if it is a chord, for NOTE, ARPEGGIO, CHORD_BRACKET, TREMOLO_*, CHORDLINE, ORNAMENT, TAPPING and ARTICULATION (334-349).
- LYRICS: parent becomes the ChordRest (352-359).
- `Note::addInternal` on the chord's first note for FINGERING, BEND and NOTEHEAD. SYMBOL goes to a rest, or to the first note of a chord (362-383).
- CLEF: Clef or HeaderClef segment, and at bar start it goes to the end of the previous bar (386-409).
- AMBITUS (411-426).
- `default`: `undoAddElement` with the cursor's segment as parent (428-430).

Every branch reaches `Score::undoAddElement`, so every add is undoable and lands in the plugin's single macro.

**W3: `Chord.add(el)`, `Note.add(el)`, `Measure.add(el)`.** These are Q_INVOKABLEs (elh:1768, 1495, 2001).

- `Chord::addInternal` sets the parent to the chord, then calls `undoAddElement` (el:367-379).
- `Note::addInternal` accepts only NOTEHEAD, NOTEDOT, FINGERING, SYMBOL, IMAGE, TEXT, BEND, TIE, PARTIAL_TIE, LAISSEZ_VIB, ACCIDENTAL, TEXTLINE, NOTELINE, GLISSANDO and HAMMER_ON_PULL_OFF (el:188-210, 238-251). Other types are dropped with a LOGD.
- `MeasureBase::addInternal` sets the parent to the measure, then calls `undoAddElement` (el:460-465).

These calls reach any note of a chord, while `cursor.add` reaches only the first note.

**Set `el.track = chord.track` before `chord.add(el)`.** `Chord::addInternal` sets the track only for notes. A new element's track defaults to `nidx` (`dom/engravingitem.h:716`), so `element->staff()` is null and `undoAddElement` takes the direct `doUndoAddElement` path (ed:6902). There `Chord::add` fixes the track (`dom/chord.cpp:619`), but linked staves and parts never get the item [inferred]. With the track set first, the articulation, arpeggio and tremolo branches run and copy the item to linked staves.

**W4: `cmd("<code>")`.**
- Inside `startCmd` the stack is locked. The action's own `startEdit`/`apply` become `prepareChanges`/`commitChanges`, and both return at once when the stack is locked (nus:106-145). So the action joins the plugin's macro.
- Side effect: no layout runs between actions, because layout normally happens in `apply` → `endCmd`.
- Nearly every handler returns early when the selection is empty (for example ni:5455, 5507, 5528, 5575).

**One undo step.** Every write path here runs inside the plugin's single `startCmd` macro unless a row says otherwise. The exceptions are `setMetaTag`, which is not undoable, and actions dispatched outside the command.

**No dedicated spanner invokable.** `score.h` has no Q_INVOKABLE that adds a spanner or exposes `undoAddElement`; the only adds are `addText`, `addSystemObjects` and `addRemoveSystemLocks` (sch:429, 500, 637). `undoAddElement` is reached only through `Cursor.add`, `Chord.add`, `Note.add` and `Measure.add`.

**Selection rule.**
- `selection.select(e[, add])` is immediate.
- `selectRange` inside an active command only stores ticks and leaves start and end segments null (sel:141-145, `dom/select.cpp:885-901`).
- Range-based actions dispatched after that see no chord-rests. `getSelectedStartEndChordRests` then sets `NO_NOTE_REST_SELECTED` (ed:177-201), and `cmdTimeDelete` dereferences a null `startSegment` (ed:4975-5010).
- Any non-warning `MScore` error makes `Score::endCmd` roll back (cmd:418). The plugin's `endCmd(false)` calls `unlock` then `commitChanges`, which calls `score()->endCmd()` (sc:606-620). So one failed action silently rolls back the whole write, notes included.
- Rules:
  - Inside a command, select by list: `select(first)`, then `select(last, true)`.
  - A range action needs `selectRange` **before** `startCmd`.
  - Always read back after `endCmd`.

**Grip edit and note input.**
- `add-hairpin` puts the notation into grip edit on the new hairpin's front segment when it creates exactly one hairpin outside note input (ni:5583-5587).
- `add-slur` does the same when it gets a single note with no second item (ni:3033-3037).
- `add-staccato`/`sforzato`/`tenuto`/`marcato` and the accidental actions **start note input** when the selection is empty (nac:939-965, 909-937).
- The text actions (`staff-text`, `tempo`, `lyrics`, `chord-text`, ...) open a text editor on the item (nac:1450-1475 → ni:6196-6290). Never use them; use W2.

## 1. Spanners

**Read.**
- `Score.spanners` returns `score()->spannerList()`, the whole spanner map, refilled into one **static** vector on each call (sc:580-585). Copy it to a JS array once per read.
- Each item is wrapped as `Spanner` (el:672-697): `spannerTick`, `spannerTicks` (Fractions), `track`, `spannerTrack2`, `anchor`, `startElement`, `endElement`, `spannerSegments` (elh:2545-2562), plus `type`, `subtype` and the generic type properties.
- The map holds slur, hammer-on, volta, trill, vibrato, pedal, text line (segment-anchored only), hairpin, let ring, gradual tempo change, palm mute, whammy bar, ottava and partial lyrics line (dsc:1413-1456).
- **Not in the map**: glissando, note line, guitar bend, note-anchored text line and ties. Those hang off the note: `Note.spannerForward`/`spannerBack` (elh:1373-1376) and `tieForward`/`tieBack`. The TEXTLINE with anchor NOTE breaks out at dsc:1434-1436, and Note::add puts these into spannerFor (`dom/note.cpp:1364-1369`).

**Write via W2.**
- Set `spannerTick`, `spannerTicks`, and `spannerTrack2` when needed, on the new element before `cursor.add`. Spanner::setProperty maps them to setTick/setTicks/setTrack2 (spn:642-669). `Cursor::add` sets neither the tick nor ticks.
- `undoAddElement` takes these into the spanner branch (ed:7184-7240): slur, hairpin, ottava, trill, vibrato, textline, pedal, let ring, palm mute, whammy.
- Then `Score::addElement` → `parent->add` (dsc:1399). The parent is the cursor's Segment, and `Segment::add` has no spanner case, so it reaches `ASSERT_X` (seg:853). That is LOGE plus `assert`, so a debug build aborts and a release build [inferred: NDEBUG] logs and continues to `addSpanner` (dsc:1430). Undo reaches the same default in `Segment::remove` (seg:991-993).
- The native `Score::addHairpin(type, sTick, eTick, track)` builds its hairpin with a dummy Segment as parent and takes the same path (ed:4353-4371). So this route matches an internal path [inferred: runtime equal].
- Volta, system text lines and gradual tempo change carry the SYSTEM flag and take the system-object branch (ed:6701-6790). See the Risk column.

| Kind | Read | Write | Risk | Source |
|---|---|---|---|---|
| Slur | yes: `Score.spanners`, type SLUR; start/end chord via `startElement`/`endElement` (anchor CHORD, `dom/slur.cpp:381`) | yes, two ways. (a) `select(n1); select(n2,true); cmd("add-slur")` → `doAddSlur` list branch → `Score::addSlur` (ed:698-758); one step. (b) W2 SLUR with tick, ticks, track2; start and end are computed from tick and track (spn:717-760) [inferred] | Single-note selection enters grip edit (ni:3033-3037). If a slur already joins the two chords with AUTO direction, (a) is a no-op (ni:3018-3020). (b) hits the Segment::add assert path [inferred: release OK] | nac:236, ni:2878-2966, 3018-3037, ed:698 |
| Hairpin < > | yes: HAIRPIN, `hairpinType` (elh:616) | yes: W2 HAIRPIN, set `hairpinType` and ticks. Do **not** use `cmd("add-hairpin")`/`"add-hairpin-reverse"` inside `startCmd`: with one hairpin created it calls `frontSegment()`, which is `m_segments.front()` on a spanner that has no segments yet because no layout ran under the lock (ni:5583-5587, `dom/spanner.h:187`) | Using the action inside the lock is likely UB or a crash [inferred]. Outside `startCmd` it is safe, but it is its own undo step and leaves grip edit on | nac:337-339, ni:5573-5588, ed:4298-4371 |
| cresc./dim. text line | yes: hairpinType CRESC_LINE/DIM_LINE, `beginText`/`continueText` (elh:912, 946) | yes: W2 HAIRPIN with `hairpinType` set to CRESC_LINE or DIM_LINE, plus `beginText` "cresc." and `continueText` "(cresc.)". Natively those texts are filled only at creation (ed:4337-4343) | Without the texts it draws a bare line | ed:4332-4371 |
| Ottava 8va/8vb | yes: OTTAVA, `ottavaType` (elh:605); sounding pitch needs `Staff.pitchOffset` (elh:2474) | yes: `cmd("add-8va")`/`"add-8vb"` with a list selection (ed:2322-2392; the single branch selects the ottava, no grip). Or W2 OTTAVA with `ottavaType` | Range selected inside the command → NO_NOTE_REST_SELECTED → rollback. `addElement` calls `staff()->updateOttava()` (dsc:1446-1456) | nac:334-335, ni:5526-5534 |
| Ottava 15ma/15mb/22ma | yes, as above | no action exists. W2 OTTAVA with `ottavaType` set, or add-8va followed by setting `ottavaType` on the new ottava | none beyond W2 | ed:2338 (8vb only) |
| Pedal | yes: PEDAL, hook and text properties (elh:912-992) | W2 only: PEDAL, track = staff*4. Variants (Ped./*, hooks) via `beginText`, `endText`, `beginHookType`, `endHookType`, `lineVisible` | No action. The default style comes from Factory [inferred] | ed:6921, dsc:1421 |
| Trill line | yes: TRILL, `trillType` (elh:609), `ornament` (elh:2562) | W2 only: TRILL, with **`trillType` set before add**. `setTrillType` creates the inner Ornament (`dom/trill.cpp:341-350`) | Without it, `Trill::linkedClone` dereferences a null ornament (`trill.cpp:210-216`) when the score has parts or linked staves → crash. `cmd("add-trill")` is the trill **ornament**, not the line | `dom/trill.cpp`, nac:461 |
| Vibrato | yes: VIBRATO, `vibratoType` (elh:611) | W2 only | none known | ed:7184-7240 |
| Let ring / palm mute | yes: LET_RING, PALM_MUTE | W2 only | none known | ed:7184-7240 |
| Text line (staff) | yes: TEXTLINE, `beginText` etc. | W2 TEXTLINE, track = staff*4 | Segment-anchored only | ed:7184-7240 |
| System text line | yes: TEXTLINE with `systemFlag` (elh:909) | W2 with `systemFlag` set, cursor on **track 0** | System-object branch: the element itself is added only when its staff is the first system-object staff. Otherwise only linked clones are added and the plugin's wrapper points at an orphan (ed:6746-6757) | ed:6701-6790 |
| Volta | yes: VOLTA, `volta_ending` (elh:752), `beginText` | W2 VOLTA (SYSTEM flag, `dom/volta.cpp:106`; anchor MEASURE), cursor on **track 0**, ticks spanning whole bars, `volta_ending` and `beginText` "1." | Same system-object rule as above. `volta_ending` is INT_VEC, converted with `v.value<QList<int>>()` (`types/propertyvalue.cpp:210-213`); whether a JS array converts is untested | ed:6701-6790 |
| Glissando | yes: `Note.spannerForward`, type GLISSANDO, `glissType` (elh:675) | **no**. No action is registered. W3 `note.add(GLISSANDO)` is allowed, but the anchor is NOTE, `doComputeEndElement` does nothing for NOTE (spn:806-807) and no API sets `endElement` | A null end note into layout → likely crash [inferred]. Do not attempt | el:188-210 |
| Note-anchored line | yes: `Note.spannerForward`, NOTELINE | yes: `select(n1); select(n2,true); cmd("add-noteline")` → `Score::addNoteLine` (ed:2380-) | Needs exactly a start and an end note | nac:340, ni:6125-6134 |
| Guitar bend | yes: GUITAR_BEND via spannerForward, `guitarBendAmount` (elh:1141) | yes: `select(note); cmd("standard-bend" / "pre-bend" / "grace-note-bend" / "slight-bend" / "dive" / "pre-dive" / "dip" / "scoop")` | May create an end note (ed:705-711 pattern) [inferred] | nac:538-546, ni:7974 |
| Tie / l.v. | yes: `tieForward`/`tieBack` | `cmd("tie")` as in spec 6.5; `cmd("lv")` toggles l.v. | W2 TIE crashes: the `isTie` branch runs `tie->startNote()->chord()` and a fresh tie has a null start note (ed:7277-7281). That explains the 4.6.5 crash from source | nac:233-235 |
| Hammer-on/pull-off | yes: HAMMER_ON_PULL_OFF in the spanner map | `cmd("hammer-on-pull-off")` with a list selection | Same grip edit as slur on a single note | nac:237 |

## 2. Per chord and per note

| Kind | Read | Write | Risk | Source |
|---|---|---|---|---|
| Articulation (staccato, accent, tenuto, marcato, bow, ...) | yes: `Chord.articulations` (elh:1690), `symbol` (elh:824) | yes: W3 `chord.add(newElement(ARTICULATION))` with `symbol` (SymId as int) and `track` = chord track set before add. `undoAddElement` articulation branch (ed:7050-7090) | Toggle actions `add-staccato` etc. remove the mark when every note already has it (ni:5706-5707), and start note input when nothing is selected (nac:954-958). W2 needs the cursor on the chord, because `currentElement()` is not null-checked (cur:343) | nac:176-179, 471-472 |
| Ornament (trill, mordent, turn, ...) | yes: also in `Chord.articulations` (Articulation family, `dom/engravingobject.h:575-578`), wrapper `Ornament` | yes: W3 `chord.add(newElement(ORNAMENT))` with `symbol` and `track` set first. Or `select(note); cmd("add-trill" / "add-mordent" / "add-turn" / ...)` | The actions toggle (`Score::toggleOrnament`) | nac:456-469, ni:8280 |
| Fermata | yes: `Segment.annotations` (seg:723), `symbol` | yes: W2 FERMATA with `symbol`, cursor on the chord. It is a segment annotation (ed:7129-7183), not a chord child | No action | seg:703-726 |
| Breath / caesura | yes: element of track in the **Breath** segment (`Segment.elementAt`, elh:1890) during a walk over all segment types | yes: W2 BREATH with `symbol`. `undoAddElement` puts it in a Breath segment **at the cursor's tick** and moves it to the previous bar when that tick is a bar start (ed:7335-7348). So place the cursor on the chord **after** the breath | Off-by-one position if the cursor is put on the chord the breath follows | ed:7335 |
| Arpeggio | yes: `Chord.arpeggio` (elh:1723), `arpeggioType` (elh:1081) | yes: W3 (set `track` first) or W2 ARPEGGIO with `arpeggioType`, `arpeggioSpan` | none known | ed:7268-7276 |
| Tremolo, single chord | yes: `Chord.tremoloSingleChord` (elh:1729), `tremoloType` | yes: W3 (set `track` first) or W2 TREMOLO_SINGLECHORD with `tremoloType` | none known | ed:7263-7267 |
| Tremolo, two chords | yes: `Chord.tremoloTwoChord` (elh:1732) | **no**. The `undoAddElement` branch dereferences `tremolo->chord1()` (ed:7246), which starts null (`dom/tremolotwochord.h:135`) and has no API setter; no action exists | Crash. Do not attempt | ed:7244-7262 |
| Fingering | yes: `Note.elements` | yes: W3 `note.add(newElement(FINGERING))`, then `text`. W2 reaches only the first note (cur:370-382) | Text set after add (see 3) | el:238-251 |
| Lyrics | yes: `ChordRest.lyrics` (elh:1626): `text`/`plainText`, `verse`, `syllabic` (elh:2634), `lyricTicks` (elh:2636), `isMelisma` | yes: W2 LYRICS (parent ChordRest, cur:352-359) with `verse` (0-based), `syllabic`, `lyricTicks` for a melisma, then `text` | `add-melisma`/`add-lyric-verse` work only while editing lyrics (nac:165-166) | ed:7092-7128 |
| Notehead type/group | yes: `headType`, `headGroup` (elh:407, 413) | yes: W1 on the note (`dom/note.cpp:3176`, 3214) | none | |
| Stem direction | yes: `stemDirection` (elh:438) | yes: W1 on the chord. `cmd("flip")` with a selection also works | none | nac:231 |
| Beam mode | yes: `beamMode`, `actualBeamMode()` | yes: W1 `beamMode`, or `cmd("beam-auto"/"beam-none"/"beam-break-left"/"beam-join"/...)` | none | elh:1640, nac:409-414 |
| Cross-staff | yes: `staffMove`, `isCrossStaff` | yes: `select(cr); cmd("move-up"/"move-down")` (the native checks) or W1 `staffMove` | W1 skips the checks that `moveChordRestToStaff` makes [inferred] | nac:256-257, ni:3961 |
| Grace notes before / after | yes: `graceNotesBefore`/`After` (elh:1682-1685), `noteType` | yes: `select(note); cmd("acciaccatura" / "appoggiatura" / "grace4/16/32" / "grace8after" / "grace16after" / "grace32after")`, as built in slice 2 | Graces are created at the main note's pitch; fix `pitch`/`tpc` afterwards | nac:400-407 |
| Accidental, courtesy / bracket | yes: `note.accidental` and its `accidentalType`, `accidentalBracket` (elh:576) | yes: `note.accidentalType = t` calls `Score::changeAccidental`, which is undoable and **changes the pitch** (`dom/note.cpp:3974-3978`); setting the type the pitch already implies gives a courtesy accidental [inferred]. Bracket: W1 `accidentalBracket` on `note.accidental`. Parentheses: `cmd("add-parentheses")` (toggle) | Pitch change if the type is wrong. The accidental actions start note input when nothing is selected | elh:1359, 1481; nac:168-172, 417 |
| Chord line (fall, doit, ...) | yes: `ChordRest.elements` [inferred], `chordLineType` (elh:1085) | **no**. The `undoAddElement` branch runs `oldChordLine->note()->pitch()` (ed:7113) with `m_note` null (`dom/chordline.h:117`), and no action exists | Crash. Do not attempt | ed:7092-7128 |
| TAB fret/string | yes: `fret`, `string` (elh:1437-1439) | yes: W1 on the note, or `cmd("fret-N")` on a TAB staff (nac:548-550) | W1 fret/string do not re-derive pitch [inferred] | |

## 3. Segment annotations

**Read** all through `Segment.annotations` (elh:1832), which takes every type at seg:703-726 and the special cases at 728-765. **Write** all through W2 `default`.

**Text order.**
- On 4.7.5, setting text **after** `cursor.add` worked for dynamics and chord symbols (spike 2026-10-18).
- For the system objects below, text must be set **before** add. If the original element is not the copy actually added, the wrapper is an orphan (ed:6746-6757).
- **[inferred]**: setting text before add is safe for text types other than Harmony.

| Kind | Read | Write | Risk | Source |
|---|---|---|---|---|
| Staff text | yes: STAFF_TEXT, `text` | yes: W2, then `text` | none | seg:703-726 |
| Expression | yes: EXPRESSION | yes: W2, then `text` | none | |
| System text | yes: SYSTEM_TEXT | yes: W2 with cursor on **track 0**, `text` set first | System-object rule: only the copy on the first system-object staff is the original (ed:6702-6790). Read-back by the cursor's track misses it on other staves | ed:6702 |
| Tempo | yes: TEMPO_TEXT, `tempo` (beats per **second**), `tempoFollowText`, `text` | yes: W2 track 0. Set `text`, `tempo` = bpm/60 (`types/propertyvalue.cpp:271`) and `tempoFollowText`. `TempoText::setProperty(TEMPO)` calls `setUpTempoMapLater`, and `added()` calls `updateScore` (`dom/tempotext.cpp:358-372`, 483-486) | `followText` re-derives tempo only on `commitText` (tempotext.cpp:491-498), so always set `tempo` explicitly. System-object rule applies | |
| Rehearsal mark | yes: REHEARSAL_MARK | yes: W2 track 0, `text` | System-object rule | ed:6702 |
| Dynamic | yes: DYNAMIC, `dynamicType` | yes: W2, `text` then `dynamicType` (spec 6.7) | none new | |
| Chord symbol | yes: HARMONY, `text`, `harmonyType` | yes: W2, then `text` after add | Text set before add crashed [reported] | |
| Fretboard diagram | yes: FRET_DIAGRAM, `fretStrings`/`fretFrets`/`fretOffset`/... (elh:767-786) | partial: W2 plus the grid properties. Dots, barres and markers have no API property [inferred]. `cmd("add-fretboard-diagram")` needs a selected chord symbol | Diagram contents may stay empty | nac:322 |
| Figured bass | yes: FIGURED_BASS, `text` | partial: W2, then `text` | Whether the TEXT property re-parses figures (normally done when the editor closes) is unknown | seg:703-726 |
| Instrument change | yes: INSTRUMENT_CHANGE, `text` | effectively **no**. With no channels, the added element copies the staff's **current** instrument (ed:7322-7323). No API sets its instrument | Only a text label results | ed:7311-7334 |
| Playing technique | yes: PLAYTECH_ANNOTATION, `playTechType` (elh:1178) | yes: W2, `playTechType`, `text` | none known | |
| Harp pedal diagram | yes: HARP_DIAGRAM, `isDiagram` | partial: W2. The pedal states have no API property; Part has read helpers only [inferred] | Contents may stay at defaults | seg:758-765 |
| Sticking, capo, string tunings, symbol, image | yes | yes: W2 (capo: `fretPosition` and friends, elh:1204-1210) | none known | |

## 4. Bar and measure level

| Kind | Read | Write | Risk | Source |
|---|---|---|---|---|
| Repeat start/end, repeat count | yes: `Measure.repeatStart`, `repeatEnd`, `repeatJump`, `repeatCount` (elh:1902-1906, 2065) | yes: W1 on the Measure (`dom/measurebase.cpp:459-466`, `dom/measure.cpp:2921-2923`). Layout forces repeat bar lines from the flags (`rendering/score/measurelayout.cpp:1695-1730`) | Linked parts get the flag only if a measure property change propagates to excerpts [inferred] | |
| Bar line type (double, final, dashed, ...) | yes: `elementAt(staff*4)` in EndBarLine, BeginBarLine, StartRepeatBarLine and mid-bar BarLine segments, `barlineType` (elh:457) | **partial**. W1 `barlineType` on a **generated** bar line (most of them) is reset by layout to the computed type (measurelayout.cpp:1722-1726). `generated` is read-only (elh:342), and `undoChangeBarLineType` (ed:5733) is not exposed. No action exists | Probably reverts at the next layout [inferred]. A user-set (non-generated) bar line keeps its type | |
| Volta | see 1 | see 1 | | |
| Jumps (D.C., D.S., To Coda) | yes: `Measure.elements`, JUMP, `jumpTo`/`playUntil`/`continueAt` (elh:652-656), `text` | yes: W2 JUMP (parent measure, cur:321-331) on **track 0**, with labels and `text` set before add | System-object rule (ed:6765-6770) | |
| Markers (segno, coda, fine) | yes: MARKER, `markerType`, `label` (elh:658-661) | yes: W2 MARKER, track 0, `markerType` and `label` set before add | Same rule | |
| Layout breaks | yes: `Measure.elements`, LAYOUT_BREAK, `layoutBreakType` (elh:511) | yes: W2 with `layoutBreakType` set first (cur:315-318), or `select(cr); cmd("system-break" / "page-break" / "section-break")` (toggle; guarded by `toggleLayoutBreakAvailable`) | The actions toggle | nac:265-270 |
| Spacers | yes: `Measure.vspacerUp(staff)`/`vspacerDown(staff)` (elh:2103-2107) | yes: W2 SPACER (parent measure). Type through `subType`, height through properties [inferred] | Which property holds the spacer type is unverified | cur:322 |
| Measure number | yes: `no` (display = no+1), `measureNumber(staff)` | yes: W1 `measureNumberMode`, `noOffset`, `irregular` (elh:1908-1910, 2054) | none | |
| Key signature change | yes: `Staff.key(frac)` (elh:2397); KeySig segment elements (`concertKey`, `actualKey`, `keysig_mode`) | partial: W2 KEYSIG with `concertKey` (and `actualKey`) set before add. `KEYSIG` is not in the `undoAddElement` per-staff list, so it is added to **one staff** (ed:6902-6950). `Segment::add` updates that staff's key map (seg:788-799). Repeat per staff | No transposition of a transposing staff's written key, no linked parts. The native `undoChangeKeySig` is not exposed | cur:298-302 |
| Time signature change | yes: TimeSig segment elements, `timesig`, `numeratorString` | yes: W2 TIMESIG with `timesig` (Fraction) set first → native `cmdAddTimeSig` (all staves, rewrites bars) | **Use-after-free**: `cmdAddTimeSig` deletes the passed element (ed:1469, 1619) after the wrapper was made SCORE-owned (cur:289). Never touch the JS object after add. It also deselects everything (ed:1440). `Cursor::add` passes the **track** as the staff index (cur:307), so keep the cursor on track 0 | ed:1438-1619 |
| Clef change, bar start and mid-bar | yes: `Staff.clefType(frac)` (elh:2382); Clef and HeaderClef segment elements | yes: W2 CLEF with `concertClefType`/`transposingClefType` set first. Mid-bar goes to a Clef segment at that tick; bar start goes to the end of the previous bar (cur:386-409). `cmd("clef-violin"/"clef-bass")` also exists (nac:486-487) | An existing clef at the same spot is overwritten in `m_elist` without removal [inferred]. Change the old clef's type with W1 instead | |
| Actual length (irregular bar) | yes: `timesigActual`, `ticks` | yes: W1 `timesigActual` on a score-owned Measure calls `adjustToLen` (se:180-187); `irregular` | Content beyond the new length is cut [inferred] | |
| Insert / delete bars | yes: walk | insert: `select(cr); cmd("insert-measure")` (one bar before the selection; repeat N times); `appendMeasures(n)`. Delete: `cmd("time-delete")` with a **range selected before** `startCmd` | `time-delete` after an in-command `selectRange` dereferences a null start segment (ed:4975-5010). `insert-measures` (count) opens a dialog | nac:282-299, 387 |
| Split / join | yes | `cmd("split-measure")` / `cmd("join-measures")` with a selection | none known | nac:279-280 |

## 5. Score and part level

| Kind | Read | Write | Risk | Source |
|---|---|---|---|---|
| Title, composer, metadata | yes: `metaTag(tag)` | `setMetaTag` (sch:386) writes directly, **not undoable**. The title frame text is separate: `Score.addText(type, text)` (sch:500) adds a VBOX text with undo | Metadata survives a discard | |
| Parts and instruments | yes: `parts`, `Part.instruments` | `appendPart`, `insertPart`, `removeParts`, `replaceInstrument`, ... (sch:407-730) | Layout A only (spec 6.12) | |
| Staff properties | yes: Staff wrapper | W1 on Staff (`small`, `mag`, `color`, `staffInvisible`, ...) | not traced further | elh:2282-2480 |

## Needs a live spike

One session, a scratch copy of the nocturne. Save before each block and work from the safest block to the most crash-prone. After each item:

- Ctrl+Z once and check that the score is back to its prior state.
- Save, then reload.

Blocks:

1. **Properties (W1):** `measure.repeatStart`/`repeatEnd`/`repeatCount`; `barlineType=DOUBLE` on a generated end bar line, then force a layout and check whether it reverts; `stemDirection`, `beamMode`, `headGroup`, `staffMove`; `note.accidentalType` set to the implied type (is it a courtesy accidental, and is the pitch unchanged?).
2. **Annotations (W2 default):** tempo on track 0 with `tempo`=1.5 and `text` set before add (does playback change?); rehearsal mark and system text on track 4 (is the wrapper an orphan, and is a copy on staff 0 visible?); figured bass `text` (does it parse?); fermata; playing technique.
3. **Chord and note children (W3):** with `track` set and with it unset, on staff 2 of a score that has a part, `chord.add` ARTICULATION (does the part get it?), then and ORNAMENT with `symbol`; `note.add` FINGERING on the second note of a chord; LYRICS with verse 1 and `syllabic`; ARPEGGIO; TREMOLO_SINGLECHORD; BREATH placed on the chord after.
4. **Actions with a list selection inside one `startCmd`:** `add-slur` (two notes), `add-8va` (two notes), `add-noteline`, `acciaccatura`, `system-break`, `insert-measure`. After each, dispatch `cmd("escape")` and check that no grip edit remains. Then repeat `add-slur` on a single note (grip edit) and call `endCmd(true)`: does rollback while in grip edit crash?
5. **Spanners (W2):** HAIRPIN, CRESC_LINE (with texts), PEDAL, TRILL (`trillType` first), OTTAVA 15ma, TEXTLINE, VOLTA (track 0, `volta_ending=[1]`). Check what `Score.spanners` returns, the LOGE line "Segment::add() unknown", undo, then save and reload.
6. **Time and key:** TIMESIG via W2 on track 0 (drop the wrapper); KEYSIG on each staff; mid-bar CLEF.
7. **Do last, expect a crash, save first:** `cmd("add-hairpin")` with one note selected inside `startCmd`. This confirms the `frontSegment` hazard; if it does not crash, record that.

## Not possible through the plugin API

- **Glissando**: no action. The NOTE anchor needs an end note that no API can set (spn:806-807, el:188-210).
- **Two-chord tremolo**: crashes in `undoAddElement` on a null `chord1` (ed:7246). No action exists.
- **Chord line**: crashes on a null `note()` (ed:7113). No action exists.
- **Tie through `newElement`**: crashes on a null `startNote` (ed:7281). Only `cmd("tie")` works.
- **Instrument change with a real instrument**: the instrument cannot be set, and the current one is copied (ed:7322-7323).
- **Bar line types other than repeats**, reliably: the layout overrides generated bar lines and `undoChangeBarLineType` is not exposed (measurelayout.cpp:1722-1726). Partial at best.
- **Fretboard diagram dots and barres, harp pedal states**: no API properties found [inferred]. Partial only.
- **Key change on all staves with transposition in one call**: `undoChangeKeySig` is not exposed. Per-staff W2 only.
- **Counted insert of N bars without a dialog**: covered in `research/api-gaps-2026-10.md` 1.3. `insert-measure` must be repeated N times.
- **Undoable metadata**: `setMetaTag` bypasses the undo stack (sch:386).
