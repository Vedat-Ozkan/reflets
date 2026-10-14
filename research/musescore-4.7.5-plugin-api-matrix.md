All sources resolved at tag v4.7.5 (no fallbacks to 4.6.2/4.4.4 were needed). Local copies are under `/tmp/claude-1000/-home-kema-projects-reflets/6266e500-860c-4634-98fc-70bfd316979b/scratchpad/api475/` (engraving API files keep their basenames; others are the repo path with `/`→`_`). Line numbers below refer to the v4.7.5 files.

# MuseScore Studio 4.7.5 plugin API capability matrix

## A. Root object (`MuseScore {}` in QML = `PluginAPI`, `src/engraving/api/v1/qmlpluginapi.{h,cpp}`)

| Capability | API | R/W | Evidence | Notes |
|---|---|---|---|---|
| Score-change notifications | `signal scoreStateChanged(QMap state)` | — | h:512 declares it; h:524 `void endCmd(const QMap<QString,QVariant>& stateInfo) { emit scoreStateChanged(stateInfo); }` | **Declared but never emitted.** Authenticated GitHub code search for `scoreStateChanged` over the repo hits only `qmlpluginapi.h` and `share/plugins/lilyrics/lilyrics.qml`; search for `"endCmd" "stateInfo"` hits only the header. Nothing in `src/notation`, `src/engraving`, or the extensions runner calls `PluginAPI::endCmd(QMap)`. The only `endCmd` in the .cpp is `currentScore()->endCmd()` (cpp:387, engraving-level). `onScoreStateChanged` handlers will never fire in 4.x. |
| Run lifecycle | `signal run()`, `runPlugin() { emit run(); }`, `closeRequested()`, `quit()` | — | h:456-458, h:521, cpp:485-489 | `quit()` emits `closeRequested` and notifies `m_closeRequested`. |
| Current score | `curScore` | R | cpp:242-249 wraps `context()->currentNotation()->elements()->msScore()` | null if no score. |
| All open scores | `scores` | R | cpp:251-258: `NOT_IMPLEMENTED; static std::vector<mu::engraving::Score*> scores; return wrapContainerProperty<Score>(this, scores);` | **Always empty.** |
| Open a file | `readScore(name, noninteractive=false)` | — | cpp:297-315: `if (noninteractive) { LOGW() << "Noninteractive flag is not yet implemented"; return nullptr; }` then `helper()->readScore(name)` → `src/project/internal/engravingpluginapihelper.cpp`: `projectFilesController()->openProject(file)`, returns `currentNotation()->elements()->msScore()` | Opens as a real project in a new window/tab (`LOGW "Will open a score in a new window"`). `noninteractive=true` returns null. |
| Save/export | `writeScore(score, name, ext)` | — | cpp:272-285: refuses if `s->score() != currentScore()` ("Only writing the selected score is currently supported"); helper: `writers()->writer(ext)`; unit type PER_PAGE > PER_PART > MULTI_PART; `exportProjectScenario()->exportScores({notation}, outPath, unitType, false)`; `outPath = name.endsWith(ext) ? name : name+'.'+ext` | Accepted `ext` = any registered writer suffix (see CLI section). Goes through the export scenario (may show dialogs for overwrite). |
| Close | `closeScore()` / `closeScore(score)` | — | cpp:321-339: only current score; `helper()->closeScore()` → `projectFilesController()->closeOpenedProject()` | May prompt to save. |
| New score | `newScore(name, part, measures)` | — | cpp:384-406: `createMasterScoreWithDefaultStyle(iocContext())`; `NOT_IMPLEMENTED << "setting path/filename"`; `appendPart(Score::instrTemplateFromName(part))`; `appendMeasures(measures)`; `doLayout()`; `NOT_IMPLEMENTED << "opening the newly created score"`; `Q_ASSERT(currentScore() == score)`; `score->startCmd(...)`; returns wrapper | The score is **not opened as a project**; `name` ignored. The assert would fail in debug builds; in release you get a detached score. Unusable for a bridge. |
| Dispatch UI action | `cmd(code)` | — | cpp:408-425: `COMPAT_CMD_MAP = { escape→action://notation/cancel, cut→action://notation/cut, copy→action://notation/copy, paste→action://notation/paste, paste-half→notation-paste-half, paste-double→notation-paste-double, select-all→notation-select-all, delete→action://notation/delete, next-chord→notation-move-right, prev-chord→notation-move-left, prev-measure→notation-move-left-quickly }`; `actionsDispatcher()->dispatch(COMPAT_CMD_MAP.value(s, s).toStdString())` | **Any action code string is dispatched unmapped** (e.g. `file-export`, `play`, `undo`); no args can be passed. |
| Element factory | `newElement(type)`, `removeElement(el)` | — | cpp:349-378: range check `INVALID < type < ROOT_ITEM`; `Factory::createItem(type, score->dummy())`, ownership PLUGIN | `removeElement` calls `score->deleteItem` directly (not inside undo guard). |
| External process | `newQProcess()` | — | cpp:457-461 `NOT_IMPLEMENTED; return nullptr;` | **But** cpp:203 `qmlRegisterType<MsProcess>("MuseScore", 3, 0, "QProcess")` and `util.h:127-150`/`util.cpp:282-285`: `startWithArgs(program,args){ QProcess::start(program,args,ReadWrite); }`, `waitForFinished`, `readAllStandardOutput`. So a declarative `QProcess { id: p }` in the plugin **does run arbitrary programs** (only `start(cmd)` is DEPRECATED, still works). |
| File I/O | `FileIO { source: ... }` | R/W | cpp:204 registers `FileIO`; util.h:53-99: `read()`, `exists()`, `write()`, `writeBinary()`, `remove()`, `homePath()`, `tempPath()`, `modifiedTime()` | `read()` has no path guard. `write/writeBinary` call `isPathAllowed()` (util.cpp:44-147): allowed = `userDataPath()` (Documents/MuseScore4), system temp, plugins dir, scores dir, templates dir, styles dir, soundfont dirs; **userAppDataPath explicitly excluded**. `remove()` shows no guard call (util.cpp:242-250). |
| Version/consts | `mscoreVersion` = major*10000+minor*100+patch (→ 40705), `mscoreMajorVersion/Minor/Update`, `division` = `Constants::DIVISION`, `mscoreDPI` | R | cpp:590-618 | |
| Fractions/intervals | `fraction(n,d)`, `fractionFromTicks(t)`, `interval()`, `ornamentInterval()`, `intervalFromOrnamentInterval()` | — | cpp:469-483, 630-653 | |
| Logging | `log/logn/log2` → `LOGD`; `openLog/closeLog` → `DEPRECATED` | — | cpp:427-450 | |
| Manifest props | `menuPath`, `dockArea` setters are `DEPRECATED`, getters return `QString()`; `title/version/description/pluginType/requiresScore/thumbnailName/categoryCode` stored | W | cpp:500-588 | |
| Enums | ~100 `DECLARE_API_ENUM` (`Element`, `Accidental`, `NoteType`, `Segment`, `Tid`, `SymId`, `Cursor`…) | R | h:146-451 | |

## B. Score (`score.h/.cpp`)

| Capability | API | R/W | Evidence | Notes |
|---|---|---|---|---|
| Undo transaction | `startCmd(actionName="")`, `endCmd(rollback=false)` | — | cpp:591-622: `undoStack()->prepareChanges(actionName); undoStack()->lock();` … `unlock(); rollback ? rollbackChanges() : commitChanges(); notation()->notationChanged().notify();` | Comment: "Lock the undo stack, so that all changes made by the plugin, including PluginAPI::cmd(), are committed as a single command." |
| Layout | `doLayout(startTick, endTick)` (Fraction*) | — | cpp:624-627 `doLayoutRange` | No zero-arg overload. |
| Measures | `appendMeasures(n)`, `nmeasures`, `firstMeasure/MM`, `lastMeasure/MM`, `lastSegment`, `firstSegment(type)`, `tick2measure(frac)`, `findSegmentAtTick(types, frac)` | R (+append) | h:246-283, 465-492 | **No `insertMeasure`/`removeMeasures`** Q_INVOKABLE exists (only via `cmd("insert-measures…")`-style actions, unverified). |
| Parts/staves | `parts`, `staves`, `nstaves`, `ntracks`, `appendPart(id)`, `appendPartByMusicXmlId`, `insertPart`, `replacePart`, `removeParts`, `removeStaves`, `moveParts/Staves`, `appendStaff`, `appendLinkedStaff`, `setPartVisible`, `setStaffType`, `setVoiceVisible`, `replaceInstrument`, `setInstrumentName/Abbreviature`, `replaceDrumset`, `setScoreOrder`, system-object ops | R/W | h:166-187, 407-730 | `appendPart` falls back to `defaultInstrTemplate()` if id unknown (cpp:131-144). |
| Excerpts | `excerpts` | R | cpp:543-545 wraps `masterScore()->excerpts()` | No create/remove. |
| Metadata | `scoreName` (W → `NOT_IMPLEMENTED`, cpp:523), `title`=`metaTag("workTitle")`, `composer`, `lyricist` (R), `metaTag(tag)`, `setMetaTag(tag,val)` | R/W | h:78-99, 370-386 | `setMetaTag` writes directly (`score()->setMetaTag`), not through undo. |
| Misc | `keysig`, `duration`, `npages`, `pages`, `systems`, `spanners`, `hasHarmonies`, `harmonyCount`, `hasLyrics`, `lyricCount`, `lyrics`, `style`, `layoutMode` (W), `show*` flags (W), `pageNumberOffset` (W) | mostly R | h:106-346 | |
| Selection | `selection` | R | h:757 `selectionWrap(&score()->selection())` | |
| Other | `newCursor()`, `createPlayEvents()`, `addText(type,text)` (inserts VBOX if needed, `undoAddElement`), `extractLyrics()`, `showElementInScore()`, `makeIntoSystem`, `addRemoveSystemLocks` | — | cpp:50-58, 55-80, 528-531 | |

## C. Cursor (`cursor.h/.cpp`)

| Capability | API | Evidence | Notes |
|---|---|---|---|
| Rewind | `rewind(SCORE_START=0 / SELECTION_START=1 / SELECTION_END=2)`, `rewindToTick(t)`, `rewindToFraction(f)` | h:121-126; cpp `rewind`: SELECTION_* `if (!m_score->selection().isRange()) return;` | Selection modes are no-ops for list selections. `rewindToTick` searches `tick+1` then re-filters by `m_filter`. |
| Input state mode | `inputStateMode` = `INPUT_STATE_INDEPENDENT` (default) / `INPUT_STATE_SYNC_WITH_SCORE` | cpp `setInputStateMode`: `SYNC → is.reset()` (uses score's `InputState`), else `is.reset(new InputState)` | In SYNC mode `addNote` passes `is.get()==nullptr` → score's own input state. |
| Position | `track` (W, clamped to `ntracks-1`), `staffIdx` (W: `v*VOICES + track%VOICES`), `voice` (W), `staff` (W), `filter` (W, SegmentType bitmask, default ChordRest), `tick` (R, deprecated), `utick`, `fraction`, `tempo`, `keySignature`, `element`, `segment`, `measure`, `stringNumber` (W), `score` (W) | h:69-118 | |
| Navigation | `next()` (`segment()->next1(m_filter)` then `nextInTrack()`), `nextMeasure()`, `prev()` | cpp | return false when segment becomes null. |
| Entry | `setDuration(z,n)` (invalid → quarter), `addNote(pitch, addToChord=false)` → `m_score->addPitch(nval, addToChord, is.get())`, `addRest()` → `enterRest`, `addTuplet(ratio, duration)` → `changeCRlen` + `cmdCreateTuplet`; rejects cross-measure | cpp | Requires `segment()` else `LOGW ... use rewind()`. |
| `add(element)` dispatch | cpp `Cursor::add`: refuses `Ownership::SCORE`; sets score/track/parent; `isChordRest()` → `undoAddCR`; `KEYSIG` → KeySig segment + `undoAddElement`; `TIMESIG` → `cmdAddTimeSig`; `LAYOUT_BREAK` → `MeasureBase::addInternal`; `MEASURE_NUMBER/SPACER/JUMP/MARKER/HBOX/STAFFTYPE_CHANGE` → parent = measure; `NOTE/ARPEGGIO/CHORD_BRACKET/TREMOLO_*/CHORDLINE/ORNAMENT/TAPPING/ARTICULATION` → `Chord::addInternal` if current element is a chord; `LYRICS` → parent = ChordRest; `SYMBOL` (rest or first note) / `FINGERING/BEND/NOTEHEAD` → `Note::addInternal(first note)`; `CLEF` → Clef/HeaderClef segment logic; `AMBITUS`; `default` → `undoAddElement` into current segment (covers Harmony, Dynamic, StaffText, Tempo, etc.) | | No handling of spanners (slur/hairpin) here — they go `default` with only a parent segment set. |

## D. Elements (`elements.h`, `scoreelement.h`)

Property macros (elements.h:84-129): `API_PROPERTY*(name, PID)` generate `READ get_name WRITE set_name RESET reset_name` — **writable** (via `undoChangeProperty`); only `API_PROPERTY_READ_ONLY*` is read-only.

| Class | Read-only | Writable | Evidence |
|---|---|---|---|
| ScoreElement | `type` (QJSValue), `name`, `spatium`, `eid`, `userName()`, `is(other)` | — | scoreelement.h:62-123 |
| EngravingItem | `parent`, `staff`, `staffIdx`, `effectiveStaffIdx`, `vStaffIdx`, `posX/posY/pos/pagePos/canvasPos`, `bbox`, `subtype`, `up`, `header/trailer`, `isMovable`, `selected` (READ_ONLY), `generated` (READ_ONLY), `fraction` (=tick), `beat`; `clone()`, `subtypeName()` | `offsetX/offsetY`, `offset`, `subType`, `color`, `visible`, `z`, `small`, `placement`, `hPlacement`, `track`, `voice`, `direction`, `text`, `htmlText`, `tempo`, `tempoFollowText`, `accidentalType`, `accidentalBracket`, `timesig`, `timesigStretch`, `timesigType`, `numeratorString/denominatorString`, `concertKey`, `actualKey`, `keysig_mode`, `concertClefType/transposingClefType`, `harmonyType`, `harmonyVoicing`, `harmonyDuration`, `dynamicType`, `velocity`, `veloChange`, `articulationAnchor`, `symbol`, `playRepeats`, `beginText/continueText/endText`, `hairpinType`, `ottavaType`, `trillType`, `lineStyle`, `autoplace`, `verse`, `role`, `isCourtesy`, … (~330 generic props, h:328-1281) | **No dedicated Harmony/Dynamic/Articulation/StaffText/Tempo/KeySig/TimeSig/Clef classes** — all are generic `EngravingItem`s with these props. `tick` as int is commented out (h:820). |
| Note | `accidental`, `dots`, `elements`, `playEvents`, `spannerForward/Back`, `tieBack`, `tieForward`, `firstTiedNote`, `lastTiedNote`, `noteType` (grace detection), `isTrillCueNote`; `createPlayEvent()`, `add()`, `remove()` | `accidentalType`, `pitch`, `tpc1`, `tpc2`, `tpc` (`setTpc`), `dotPosition`, `veloType`, `userVelocity`, `tuning`, `line`, `fixed`, `fixedLine`, `fret`, `string`, `dead`, `headType/headGroup/mirrorHead/ghost/play/small` (inherited) | h:1355-1500. No `tieBackward`, no `veloOffset` (renamed `userVelocity`). |
| DurationElement | `globalDuration`, `actualDuration`, `tuplet`, `topTuplet`, `measure` | `duration` (`WRITE changeCRlen`, since 4.6) | h:1505-1535 |
| ChordRest | `lyrics`, `beam`, `isFullMeasureRest`, `elements`; `actualBeamMode()` | `staffMove`, `durationTypeWithDots`, `beamMode` | h:1621-1667 |
| Chord | `graceNotes`, `graceNotesBefore/After`, `notes`, `articulations`, `stem`, `stemSlash`, `hook`, `noteType`, `upNote`, `downNote`, `arpeggio`, `tremolo*`; `add()`, `remove()` | `playEventType`, `noStem`, `showStemSlash`, `combineVoice`, `stemDirection` | h:1675-1771 |
| Tuplet | `actualNotes`, `normalNotes` (READ_ONLY), `hasBracket`, `elements`, `defaultP11/22` | `numberType`, `bracketType`, `p1`, `p2` | h:1561-1597. No `ratio` property (derive from actual/normal). |
| Segment | `annotations`, `next/prev`, `nextInMeasure/prevInMeasure`, `segmentType`, `tick` (int), `fraction`; `elementAt(track)` | `leadingSpace` | h:1825-1890 |
| MeasureBase/Measure | `no`, `tick`, `ticks`, `elements`, `next/prevMeasure(MM)`, `firstSegment`, `lastSegment`, `segments`, `mmRest`, `isMMRestStart`; `add/remove`, `visible(staff)`, `stemless(staff)`, `measureNumber(staff)` | `repeatEnd/Start/Jump`, `noOffset`, `irregular`, `timesigNominal`, `timesigActual`, `measureNumberMode`, `breakMmr`, `repeatCount`, `userStretch` | h:1897-2131 |
| Spanner / Tie | `startElement`, `endElement`, `spannerSegments`, `ornament`; Tie: `startNote`, `endNote`, `isInside` | `spannerTick`, `spannerTicks`, `spannerTrack2`, `anchor` | h:2541-2600 |
| Lyrics | `plainText`, `isMelisma`, `separator` | `syllabic`, `lyricTicks`, (`verse` generic) | h:2625-2636 |
| Staff | `part`, `idx`, `show`, `primaryStaff`, `brackets`; `clefType(frac)`, `key(frac)`, `timeSig(frac)`, `transpose(frac)`, `swing`, `capo`, `isPitchedStaff/isTabStaff/isDrumStaff`, `lines`, … `isVoiceVisible(v)` | `small`, `mag`, `color`, `playbackVoice1-4`, `staffInvisible`, `visible`, `cutaway`, … | h:2282-2480 |
| Part (`part.h`) | `startTrack`, `endTrack`, `instrumentId`, `musicXmlId`, `harmonyCount`, `hasChordSymbol`, `hasDrumStaff/PitchedStaff/TabStaff`, `lyricCount`, `midiChannel`, `midiProgram`, `longName`, `shortName`, `partName`, `instruments`, `staves`, `masterPart`; `instrumentAtTick`, `*NameAtTick`, harp-diagram helpers | `show` | part.h:62-196 |
| Instrument/Channel (`instrument.h`) | Instrument: `instrumentId`, `musicXmlId`, `longName`, `shortName`, `stringData`, `drumset`, `channels`; `cloneDrumset()`. Channel: `name`, `isHarmonyChannel` | Channel: `volume`, `pan`, `chorus`, `reverb`, `mute`, `midiProgram`, `midiBank`; Drumset setters | instrument.h:81-119, 380-439 |
| Excerpt | `partScore`, `title`; `is()` | — | excerpt.h:49-71 |
| PlayEvent | `offtime` | `pitch`, `ontime`, `len` | playevent.h:48-61 |

## E. Selection (`selection.h/.cpp`)

| API | Guard | Evidence |
|---|---|---|
| `elements`, `isRange`, `startSegment`, `endSegment`, `startStaff`, `endStaff` (R) | — | h:42-67 |
| `select(e, add=false)` | `checkSelectionIsNotLocked()` (`m_selection->isLocked()` → LOGW + false); `UndoMacro::canRecordSelectedElement(e)` else "Cannot select element of type"; `e->score() != m_selection->score() \|\| ownership != SCORE` → false | cpp:73-101 |
| `selectRange(startTick, endTick, startStaff, endStaff)` | not locked; staves clamped (`endStaff` excluded); segments via `tick2leftSegmentMM`; **`if (segEnd && undoStack()->hasActiveCommand()) setRangeTicks(...) else setRange(...)`** — i.e. inside `startCmd` the range is applied deferred by tick | cpp:117-146 |
| `deselect(e)`, `clear()` | not locked | cpp:157-188 |

No hard requirement to be inside `startCmd/endCmd`; the `hasActiveCommand()` branch is the only behavioural difference.

## F. `api.*` objects available to a plugin

Registry (`src/framework/global/api/internal/apiregister.cpp`): every `regApiCreator(module, "Ns.Name", …)` also does `qmlRegisterSingletonType("Ns.Name", 1, 0, "Name", …)` (process-global). Registered names: `MuseApi.Log`, `MuseApi.Interactive`, `api.process`, `api.filesystem` (globalmodule.cpp:144-147), `MuseApi.Engraving` (engravingmodule.cpp:146), `MuseApi.Theme`, `MuseInternal.Navigation`, `MuseInternal.Keyboard` (uimodule.cpp:138-140), `MuseInternal.Dispatcher` (actionsmodule.cpp:50), `MuseInternal.Shortcuts` (shortcutsmodule.cpp:65), `MuseApi.Websocket`, `MuseApi.WebsocketServer` (networkmodule.cpp:57-58), `MuseApi.Converter` (convertermodule.cpp:49).

**Legacy v1 QML plugins** (`extensionsuiengine.cpp:96-108`): separate `QQmlEngine` with `api` = `ExtApiV1`, which exposes **only** `api.log`, `api.engraving`, `api.websocket`, `api.websocketserver` (`extapiv1.h:34-37`). `api.engraving` is `EngravingApiV1` — same members as the root `MuseScore` item (`engravingapiv1.h:46-338`). Import path `:/qml` is added so `MuseScore.UiComponents` works.

**v2 extensions** (`extapi.h`): `api.log`, `api.interactive`, `api.theme`, `api.engraving`, `api.converter`, `api.websocket`, `api.websocketserver`. `dispatcher/navigation/shortcuts/keyboard/accessibility` have getters but **no `Q_PROPERTY`** ("Providing these APIs requires approval"), and `process`/`filesystem` are commented out with: "ATTENTION Don't add these APIs here… they can deliberately or accidentally harm the user's system."

| Object | Methods | Evidence |
|---|---|---|
| Log | `error/warn/info/debug(msg)` and `(tag,msg)` | logapi.h:34-44 |
| Interactive | `info/warning/error(title,text)`, `question(title,text,buttons)`, `openUrl(url)` | interactiveapi.h:74-80 |
| Process | `execute(program,args)`, `startDetached(program,args)` | processapi.h:42-43 (not exposed in either ExtApi) |
| FileSystem | `fileName`, `baseName`, `remove`, `clear`, `copy`, `scanFiles`, `writeTextFile`, `readTextFile` | filesystemapi.h:44-64 (not exposed) |
| Dispatcher | `dispatch(action, args)` — only `int` args supported, others `LOGE "unknown type"` | dispatcherapi.cpp:35-52 (not exposed as property) |
| Websocket | `open(conf{url|port|host}, onConnected)`, `close(id)`, `onMessage(id, cb)`, `send(id, msg)` | websocketapi.h:39-42 |
| WebsocketServer | `listen(port, onNewConnected)`, `onMessage(id, cb)`, `send(id, msg)` | websocketserverapi.h:36-38 |
| Theme | colour/font/opacity props, `themeChanged` | themeapi.h:53-263 |
| Keyboard | `key`, `pressKey`, `releaseKey`, `repeatKey`, `text` | keyboardapi.h:43-47 |
| Navigation | `nextPanel`, `goToControl`, `triggerControl`, `sections()`, … | navigationapi.h:45-64 |
| Shortcuts | `activate(sequence)` | shortcutsapi.h:40 |
| Converter | `selectDir`, `scanDir`, `basename`, `batch(outDir, job, uriQuery, progress)` | converterapi.h:46-51 |

**Playback:** no API object exposes playback state or transport. The only lever is `cmd("play")`-style dispatch through `PluginAPI::cmd` (action codes not verified in this pass).

## G. Plugin discovery / lifecycle (`src/framework/extensions/internal/legacy/extpluginsloader.cpp`, `extensionsconfiguration.cpp`)

- Paths: `pluginsDefaultPath()` = `appDataPath()/plugins`; `pluginsUserPath()` = settings key `application/paths/myPlugins`, default `userDataPath() + "/Plugins"` (→ `~/Documents/MuseScore4/Plugins`). `io::Dir::scanFiles(root, {"*.qml"})` recursively; file must contain the string `MuseScore` and a `{`.
- Manifest is a **line-based text scan** of the `MuseScore {` block, stopping at the first subsequent line ending in `{` (`//! As soon as the first open bracket is encountered, we consider that the properties have ended`). Recognised: `title`, `description`, `pluginType` (`"dialog"`/`"dock"` → `Type::Form`, else `Type::Macros`), `categoryCode`, `thumbnailName`, `requiresScore` (`"false"` → uiCtx `Any`, otherwise `ProjectOpened`), `version`. Lines prefixed `//4.4 ` are un-commented for 3.6 compatibility. `menuPath`, `dockArea` are ignored (setters `DEPRECATED`). URI = `musescore://extensions/v1/<relpath lowercased>`; single action `code="main"`, `legacyPlugin=true`, `apiversion=1`.
- Run (`extpluginrunner.cpp`): `QQmlComponent(engine()->qmlEngineApiV1(), path)` → `create()` (so `Component.onCompleted` fires first) → `dynamic_cast<IPluginApiV1*>` → `runPlugin()` → `emit run()` → `onRun`. `Form` types go through `interactive()->openSync(uri)` (`extensionsprovider.cpp:150-155`); `Macros` call `run()` directly.
- v2 extensions use `manifest.json` (`extensionsloader.cpp:38,146-197`): `type` (form/macros/composite), `apiversion` (default 2), `actions[]` with `code`, `type`, `main`, `func` (default `"main"`).

## H. CLI (`src/app/internal/commandlineparser.cpp` v4.7.5)

Options: `-h/--help`, `-v/--version`, `--long-version`, `-d/--debug`, `-D/--monitor-resolution DPI`, `-T/--trim-image px`, `-b/--bitrate`, `--template-mode`, `-t/--test-mode`, `--session-type`, `--unroll-repeats`, `-r/--image-resolution DPI`, `-o/--export-to file`, `-j/--job file`, `--extension uri` ("Use extension to process a conversion job"), `-F/--factory-settings`, `-R/--revert-settings`, `-M/--midi-operations file`, `-P/--export-score-parts`, `-f/--force`, `--score-media`, `--highlight-config`, `--score-meta` (JSON to stdout), `--score-parts`, `--score-parts-pdf`, `--score-transpose opts`, `--score-elements`, `--source-update`, `-S/--style`, `--sound-profile`, `--tracks-diff`, `--transpose`, `--page`, `--region`, `--musicxml-use-default-font`, `--musicxml-infer-text-type`, video: `--score-video`, `--resolution`, `--fps`, `--ls`, `--ts`, `--no-audio`; `--gp-linked`, `--gp-experimental`, `--migration mode`, `--diagnostic-output`, `--diagnostic-gen-drawdata`, `--diagnostic-com-drawdata`, `--diagnostic-drawdata-to-png`, `--diagnostic-drawdiff-to-png`, `--test-case*`, `--register-audio-plugin`, `--register-failed-audio-plugin`, hidden `--score-display-name-override`. **No `--run-plugin`/`-p`** (grep for "plugin" only hits audio-plugin options). `-o` takes only the first positional file (`LOGW "multiple input files"`).

`-o` format = output suffix looked up in the writers register (`convertercontroller.cpp:142-145`). Registered writers: `musicxml`, `xml`, `mxl` (musicxmlmodule.cpp:64-65); `mid`, `midi`, `kar`; `mei`; `wav`, `mp3`, `ogg`, `flac`, `aac`; `pdf`, `svg`, `png`; `mp4` (if video module); `spos`, `mpos`, `mscz`, `mscx` (notationmodule.cpp:61-64); `brf` (`src/braille/braillemodule.cpp:50`). `metajson` is not a writer — use `--score-meta`. The same register backs `writeScore(ext)`.

## Hard "cannot do" (with evidence)

1. Receive score-change/selection-change events — `scoreStateChanged` is never emitted (no caller of `PluginAPI::endCmd(QMap)` anywhere in the repo).
2. Enumerate open scores — `scores` is `NOT_IMPLEMENTED`, static empty.
3. Create and open a new score programmatically — `newScore` has two `NOT_IMPLEMENTED` markers and never registers a project.
4. Open a file silently — `readScore(name, true)` returns `nullptr`.
5. Write/close any score other than the current one — explicit `!= currentScore()` refusals.
6. Rename a score — `Score::setName` is `NOT_IMPLEMENTED`.
7. Insert/remove measures through the Score API — no such invokable (only `appendMeasures`).
8. Call `api.process`/`api.filesystem`/`api.dispatcher`/`api.keyboard` from a v1 plugin — `ExtApiV1` exposes only log/engraving/websocket/websocketserver; v2 `ExtApi` deliberately omits process/filesystem.
9. Pass arguments with `cmd()` — single string, no args; `DispatcherApi` accepts only `int` args.
10. Write files outside the allowed directories via `FileIO` — `isPathAllowed` blocks (userAppDataPath explicitly excluded).
11. Run a plugin from the CLI — no option; nearest is `--extension <uri>` combined with `-o`/`-j` (`convertByExtension`: `extensionsProvider()->perform(uri)` then `writer->write`).

## Could not determine

- Whether `import MuseInternal.Dispatcher 1.0` (or `MuseApi.Interactive`) works from a legacy plugin's QML engine. `regApiCreator` registers a process-wide QML singleton for every API name, so it plausibly bypasses `ExtApiV1`, but I did not run MuseScore to confirm. For `api.process`/`api.filesystem` the derived QML type name is lowercase (`process`, `filesystem`), which Qt normally rejects, so those likely fail even via import.
- Which action codes (`play`, `file-export`, `insert-measures`, …) accept being dispatched with no args from `cmd()`; I did not fetch the playback/notation `uiactions` tables.
- Whether `FileIO::remove()` is guarded; the grep of util.cpp:242-250 shows no `isPathAllowed` call, but I did not read the full body.
- Runtime behaviour of `newScore` in release builds after the failed `Q_ASSERT`.