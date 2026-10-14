# MuseScore plugin API gaps, resolved from source (2026-10-14)

Resolves the four items left unverified in `docs/plan-2026-10-14.md` and
`research/musescore-4.7.5-plugin-api-matrix.md` ("Could not determine").

Method: sparse clone of `musescore/MuseScore` at tag `v4.7.5` (commit `3654226`)
and tag `v4.4.3` (commit `eb6b367`), read directly. Paths are repo-relative;
line numbers are per tag. Nothing was executed: no MuseScore build was run.

- **CONFIRMED** = the behaviour follows directly from the code read.
- **UNCERTAIN** = depends on runtime or Qt behaviour that was not read or run.

Tag v4.7.5 is the current release; v4.4.3 is the version installed on the
owner's Windows machine. Where the two differ, both are given.

---

## 1. `cmd()` action codes: play/stop/rewind, insert-measures, file-export

### 1.1 How `cmd()` reaches a handler

**CONFIRMED.** `PluginAPI::cmd(s)` rewrites a few MuseScore-3 names through a
compat map and hands the string to the action dispatcher, with no arguments:

| Tag | `cmd()` | Compat map (only these 11 names are rewritten) |
|---|---|---|
| 4.7.5 | `src/engraving/api/v1/qmlpluginapi.cpp:408-425` | `escape`→`action://notation/cancel`, `cut`/`copy`/`paste`/`delete`→`action://notation/<same>`, `paste-half`→`notation-paste-half`, `paste-double`→`notation-paste-double`, `select-all`→`notation-select-all`, `next-chord`→`notation-move-right`, `prev-chord`→`notation-move-left`, `prev-measure`→`notation-move-left-quickly` |
| 4.4.3 | `src/engraving/api/v1/qmlpluginapi.cpp:284-301` | same keys, but `escape`→`notation-escape`, `cut`→`notation-cut`, `copy`→`notation-copy`, `paste`→`notation-paste`, `delete`→`notation-delete`; the rest identical |

Every other string is dispatched verbatim: `actionsDispatcher()->dispatch(COMPAT_CMD_MAP.value(s, s).toStdString())`.

**CONFIRMED.** The 4.7.5 dispatcher has two lookup paths
(`src/framework/actions/internal/actionsdispatcher.cpp`):

- `dispatch(code, data)` (lines 50-69): builds `ActionQuery(code)`; a query is
  "valid" only when the string has a scheme and a path (`src/framework/global/types/uri.cpp:47-79`,
  `Uri::isValid` needs non-empty scheme and path). A bare code such as `play`
  has no `:` and is looked up as-is in `m_clients`; unknown codes log
  `LOGW "not a registered action"` and return (line 65).
- `dispatch(ActionQuery)` (lines 72-93): looks up the full string
  (`action://x/y?k=v`), then just the URI (`action://x/y`); if neither is
  registered, `LOGW` and return (line 83). When found, the handler receives
  one `ActionData` arg: the full query string (line 90). `ActionQuery` is
  `UriQuery` (`src/framework/actions/actiontypes.h:37`); params are parsed
  from `?k=v&k2=v2` (`uri.cpp:174`).
- `doDispatch` (from line 104) calls a handler only if its `Actionable::canReceiveAction(code)`
  returns true (line 109); otherwise `LOGI "no one can handle the action"` (line 128). The
  `UiAction` context (`CTX_NOTATION_FOCUSED`, `UiCtxProjectOpened`) is **not**
  checked by the dispatcher; it only gates menus and shortcuts. So a plugin
  can dispatch a `CTX_NOTATION_FOCUSED` action while its own dialog has focus.

**CONFIRMED.** The 4.4.3 dispatcher (`actionsdispatcher.cpp:47-75`) has only
the bare-code path: no `action://` scheme exists in 4.4.3, and unknown codes
`LOGW` at line 51.

**CONFIRMED.** Neither tag returns anything to the plugin: `cmd()` is `void`,
so an unregistered or blocked action is indistinguishable from success.
This confirms the plan's "verify every write by read-back" rule.

### 1.2 Play, stop, rewind

Registered in `PlaybackController::init()` under bare codes at both tags.

| Code | 4.7.5 handler (`src/playback/internal/playbackcontroller.cpp`) | 4.4.3 handler (same path) | No-arg behaviour |
|---|---|---|---|
| `play` | `togglePlay()` (reg line 109; body 614) | `togglePlay()` (reg 99; body 559) | toggles play/pause. **CONFIRMED** |
| `stop` | `stop()` → `currentPlayer()->stop()` (reg 113; body 749) | **`pause()`** → `currentPlayer()->pause()` (reg 100; body 610) | 4.7.5 stops and resets; 4.4.3 "stop" only pauses. **CONFIRMED difference** |
| `rewind` | `rewind(args)`: `args.empty()` → position 0, clamped to `[playbackStartSecs, totalPlayTime]`, then `seek()` (reg 114; body 721-729) | same, clamped to `[playbackStartSecs, playbackEndSecs]` (reg 101; body 600-608) | seeks to start. **CONFIRMED** |
| `pause` | `pause(false)` (reg 111; codes 52-60) | not registered (only `play`, `stop`, `rewind`, `loop*`, `repeat`, `pan`, `metronome`, `midi-on`, `countin`, `playback-setup` exist, lines 47-49, 99-112) | 4.7.5 only |
| `pause-and-select`, `play-from-selection` | reg 110, 112 | absent | 4.7.5 only |

Guards (`canReceiveAction`): 4.7.5 lines 1793-1816 require a master notation
with parts and, for `play`/`pause`/`stop`/`rewind`/`loop*`, a first measure;
4.4.3 line 1612 requires a master notation with parts. **CONFIRMED.**

UI action definitions for reference: 4.7.5 `src/playback/internal/playbackuiactions.cpp:39-80`
(`play`, `play-from-selection`, `pause`, `pause-and-select`, `stop`, `rewind`);
4.4.3 `playbackuiactions.cpp:35-55` (`play`, `stop`, `rewind`).

**CONFIRMED.** `rewind` accepts a `secs_t` arg in C++ but no caller from QML
can pass it: `cmd()` passes nothing and `DispatcherApi` (section 2) passes
`int` only.

### 1.3 Insert measures

Registered in `NotationActionController` (4.7.5 `src/notationscene/internal/notationactioncontroller.cpp:282-299`;
4.4.3 `src/notation/internal/notationactioncontroller.cpp:260-277`). Same
codes and same shape at both tags:

| Code | Handler | With empty `ActionData` (what `cmd()` sends) | Guard |
|---|---|---|---|
| `insert-measure` | `addBoxes(Measure, 1, BeforeSelection)` | inserts **one** measure before the selection, no dialog. **CONFIRMED** | `hasSelection` (selection not `isNone`; 4.7.5 line 2249, 4.4.3 line 2016) |
| `insert-measures` | `addMeasures(data, BeforeSelection)` | **opens the "how many measures" dialog** `musescore://notation/selectmeasurescount` (4.7.5 lines 1693-1707; 4.4.3 lines 1513-1530). **CONFIRMED** | `hasSelection` |
| `insert-measures-after-selection` | `addMeasures(data, AfterSelection)` | dialog | `hasSelection` |
| `insert-measures-at-start-of-score` | `addMeasures(data, AtStartOfScore)` | dialog | none |
| `append-measure` | `addBoxes(Measure, 1, AtEndOfScore)` | appends one measure, no dialog | none |
| `append-measures` | `addMeasures(data, AtEndOfScore)` | dialog | none |

The count is read only when `ActionData` is non-empty (`actionData.arg<int>()`,
4.7.5 line 1698). There is no way to supply it through `cmd()`:

- `cmd("action://notation/insert-measures?count=4")`: the handler is registered
  under the bare code `insert-measures`, not under an `action://` URI, so the
  URI lookup fails and logs "not a registered action" (dispatcher lines 72-93). **CONFIRMED.**
- `cmd("insert-measures?count=4")`: no scheme, so it is looked up as the
  literal bare code `insert-measures?count=4`, which is not registered. **CONFIRMED.**
- In 4.7.5 only `cancel`, `copy`, `cut`, `paste`, `delete`, `undo`, `redo` are
  registered under `action://notation/...` (lines 52-53, 91, 222-229, 239-240).
  The `?param` mechanism exists for those URI-registered actions only; none of
  the measure, playback or export actions use it. **CONFIRMED.**

So "insert N measures silently" is impossible through `cmd()` at both tags.
Options that remain: `cmd("insert-measure")` N times (one undo step each
unless wrapped in `startCmd`/`endCmd`), `Score.appendMeasures(n)` for the end
of the score, or `Dispatcher.dispatch("insert-measures", [n])` if the import
in section 2 works at runtime.

4.7.5 `canReceiveAction` (line 578) additionally refuses every action except
undo/redo when the score has no parts; 4.4.3 (line 532) same.

### 1.4 File export

**CONFIRMED.** `file-export` is registered at both tags
(4.7.5 `src/project/internal/projectactionscontroller.cpp:91`, body 1882-1888;
4.4.3 same file line 80, body 1763-1766) and does one thing: open the Export
dialog (`interactive()->open("musescore://project/export")`). 4.7.5 first
checks `isOpened` so a second dispatch is a no-op. It never exports by
itself and takes no arguments. `UiCtxAny` (`projectuiactions.cpp:100` /
`:99`). The silent path is `writeScore` (section 3), which exists only in 4.7.5.

### 1.5 Does 4.4 use different codes?

- Same bare codes for `play`, `stop`, `rewind`, `insert-measure(s)*`,
  `append-measure(s)`, `file-export`. **CONFIRMED.**
- Different semantics for `stop` (pause in 4.4.3). **CONFIRMED.**
- `pause`, `pause-and-select`, `play-from-selection` do not exist in 4.4.3. **CONFIRMED.**
- `undo`/`redo`: 4.7.5 `action://notation/undo` (`notationactioncontroller.cpp:52-53`;
  bare `undo` is unregistered and silently logged); 4.4.3 bare `undo`
  (`notationactioncontroller.cpp:47`). **CONFIRMED**, matching the plan.
- 4.4.3 has no `action://` URIs anywhere; a bridge targeting both must send
  `undo` on 4.4 and `action://notation/undo` on 4.7, keyed on `mscoreVersion`.

---

## 2. Can a legacy v1 plugin import `MuseInternal.Dispatcher` or `MuseApi.Interactive`?

### 2.1 What the v1 engine exposes through `api`

**CONFIRMED (both tags).** Legacy plugins run in their own `QQmlEngine`
whose global `api` object is `ExtApiV1` with exactly four properties:
`log`, `engraving`, `websocket`, `websocketserver`.

- 4.7.5: `src/framework/extensions/internal/extensionsuiengine.cpp:93-108`
  (`setupV1`: `m_apiV1 = new apiv1::ExtApiV1(...)`, `addImportPath(":/qml")`);
  `src/framework/extensions/api/v1/extapiv1.h:37-40` (properties), `:50-53`
  (names `MuseApi.Log`, `MuseApi.Engraving`, `MuseApi.Websocket`, `MuseApi.WebsocketServer`).
- 4.4.3: `src/framework/extensions/view/extensionsuiengine.cpp:118-131`;
  `extapiv1.h:37-41`, `:51-54` (names `api.log`, `api.engraving.v1`,
  `api.websocket`, `api.websocketserver`).

`ExtApiV1::api(name)` (4.7.5 `extapiv1.cpp:81-103`) calls
`apiRegister()->createApi(name, m_engine)` for any name, but it is private
and only reached from those four getters, so `api.dispatcher` cannot be
requested by name from QML. **CONFIRMED.**

### 2.2 The import route (4.7.5)

**CONFIRMED (code).** In 4.7.5 every API registration also registers a
process-wide QML singleton. `ApiRegister::regApiCreator`
(`src/framework/global/api/internal/apiregister.cpp:49-87`) splits the name
at the dot and calls

```cpp
qmlRegisterSingletonType(api.c_str(), 1, 0, name.c_str(),
    [this, api](QQmlEngine*, QJSEngine* jsengine) -> QJSValue {
        auto obj = createApi(api, makeApiEngine(jsengine));   // line 81-86
        ...
        return jsengine->newQObject(obj.first);
    });
```

`makeApiEngine` (lines 89-116) builds a `JsApiEngine` for whichever
`QJSEngine` asks, using `modularity::globalCtx()`, so the creator does not
depend on the extensions engine. Registered names and their QML module/type:

| Registration | Evidence | QML import | Singleton name |
|---|---|---|---|
| `MuseInternal.Dispatcher` | `src/framework/actions/actionsmodule.cpp:50` | `import MuseInternal.Dispatcher 1.0` | `Dispatcher` |
| `MuseApi.Interactive` | `src/framework/global/globalmodule.cpp:145` | `import MuseApi.Interactive 1.0` | `Interactive` |
| `MuseApi.Log` | `globalmodule.cpp:144` | | `Log` |
| `api.process`, `api.filesystem` | `globalmodule.cpp:146-147` | see below | `process`, `filesystem` |
| `MuseInternal.Navigation`, `MuseInternal.Keyboard`, `MuseApi.Theme` | `src/framework/ui/uimodule.cpp:138-140` | | |
| `MuseApi.Engraving` | `src/engraving/engravingmodule.cpp:146` | | |

Qt's QML type registry is global to the process, not per engine, and the
v1 engine adds `:/qml` to its import path without removing anything
(`extensionsuiengine.cpp:107`). Nothing in the extensions code calls
`qmlProtectModule` or otherwise restricts imports (grep over both trees:
no hits).

**UNCERTAIN (runtime).** Therefore `import MuseInternal.Dispatcher 1.0` and
`import MuseApi.Interactive 1.0` in a v1 plugin should resolve in 4.7.5 and
hand the plugin a working `Dispatcher` / `Interactive` singleton, bypassing
the `ExtApiV1` allow-list. This was not run. Two things could still break it:
the registration order (modules register at startup, before any plugin
loads, so this looks safe) and any import filtering added after 4.7.5. The
v2 `ExtApi` deliberately withholds `dispatcher` ("Providing these APIs
requires approval", `src/framework/extensions/api/extapi.h:45-56`, getter at
line 75), so this route is an oversight that a later release may close.
Treat it as an optional accelerator, never as the only path.

**UNCERTAIN (Qt).** `api.process` and `api.filesystem` would be registered
as QML types named `process` and `filesystem`. Qt rejects type names that
do not start with an uppercase letter at registration time, so these two are
most likely not importable even in 4.7.5, which matches the "ATTENTION" note
in `extapi.h:51-56`.

What the singletons offer:

- `Dispatcher.dispatch(action: string, args: list)`: `src/framework/actions/api/dispatcherapi.cpp:35-55`
  (identical at 4.4.3). Only `int` args survive; any other type logs
  `LOGE "unknown type"` and is skipped. This is the one way to pass a count
  to `insert-measures`/`append-measures` (section 1.3) or to any
  `ActionData`-taking handler that reads ints. **CONFIRMED (code).**
- `Interactive`: `info/warning/error(title, text)`, `question(title, text, buttons)`,
  `openUrl(url)` (`src/framework/global/api/interactiveapi.h:74-80`). The
  4.4.3 version has only `info` and `openUrl` (`interactiveapi.h:40-42`).

### 2.3 4.4.3: not possible

**CONFIRMED.** The 4.4.3 `regApiCreator`
(`src/framework/global/api/internal/apiregister.cpp:37-53`) only stores the
creator in a map; there is no `qmlRegisterSingletonType` for any API name
anywhere in `src/framework/global`, `src/framework/extensions` or
`src/framework/actions`. The names are `api.dispatcher`
(`actionsmodule.cpp:50`) and `api.interactive` (`globalmodule.cpp:123`), and
the only consumer is `ExtApiV1`/`ExtApi`. A v1 plugin on 4.4.3 cannot reach
the dispatcher or interactive APIs by any import. (The 4.4.3 v2 engine even
restricts its import path to `:/api`, `extensionsuiengine.cpp:85-87`; the
v1 engine uses `:/qml`, line 130.)

Consequence for the bridge: on the owner's 4.4.3 install, the only levers are
`cmd(code)` without arguments and the `Score`/`Cursor` write API.

---

## 3. `readScore` / `writeScore`: exact fields and dialogs

### 3.1 Signatures (identical headers at both tags)

- `readScore(name: string, noninteractive: bool = false) → Score | null`
  (4.7.5 `src/engraving/api/v1/qmlpluginapi.h:537`; 4.4.3 `:284`).
- `writeScore(score: Score, name: string, ext: string) → bool`
  (4.7.5 `:536`; 4.4.3 `:283`).
- `closeScore(score)` and 4.7.5-only `closeScore()` (4.7.5 `.cpp:321-339`; 4.4.3 `.h:285`).

### 3.2 4.4.3: all three are stubs

**CONFIRMED.** In 4.4.3 `writeScore` is `NOT_IMPLEMENTED` and returns `false`
(`qmlpluginapi.cpp:174-185`), `readScore` is `NOT_IMPLEMENTED` and returns
`null` (`:197-204`), `closeScore` is `NOT_IMPLEMENTED` (`:210-215`). On the
owner's installed version a plugin cannot open or export files at all; the
only export path there is the Export dialog (`cmd("file-export")`) or the
CLI (`MuseScore4.exe -o`). The bridge must not depend on these on 4.4.

### 3.3 4.7.5 `writeScore`

`qmlpluginapi.cpp:272-285` → `EngravingPluginAPIHelper::writeScore`
(`src/project/internal/engravingpluginapihelper.cpp:34-50`). **CONFIRMED:**

1. `score` must be non-null and must be the current score, else `LOGW` and
   `false` ("Only writing the selected score is currently supported").
2. `ext` is looked up as an exact key in the writers register
   (`src/project/internal/notationwritersregister.cpp:34`, a `std::map`
   lookup: lowercase registered suffix, no leading dot). Unknown → `false`.
3. Unit type is chosen per writer: `PER_PAGE` if supported, else `PER_PART`,
   else `MULTI_PART` (helper lines 69-83).
4. `outPath = name.endsWith(ext) ? name : name + "." + ext` (line 48). The
   suffix of `outPath` is what the export scenario uses to pick the writer
   again (`exportprojectscenario.cpp:102-103`), so `name` should carry the
   same suffix or none.
5. `exportProjectScenario()->exportScores({currentNotation}, outPath, unitType, false)`
   (`src/project/iexportprojectscenario.h:43`; body
   `src/project/internal/exportprojectscenario.cpp:98-243`). The last
   argument disables "reveal in file browser".

Writers and the unit type `writeScore` picks (all 4.7.5, `supportedUnitTypes()`):

| `ext` | Writer | Unit type used | Files written |
|---|---|---|---|
| `png`, `svg` | `src/importexport/imagesexport/internal/pngwriter.cpp:37-39`, `svgwriter.cpp:47-49` | `PER_PAGE` | one file per page: `base.png` if one page, else `base-1.png`, `base-2.png`, … (`completeExportPath`, lines 326-342) |
| `pdf` | `pdfwriter.cpp:40-42` (`PER_PART`, `MULTI_PART`) | `PER_PART` | one file |
| `musicxml`, `xml`, `mxl` | `src/importexport/musicxml/internal/musicxmlwriter.cpp:35-37` | `PER_PART` | one file |
| `mid`, `midi`, `kar` | `src/importexport/midi/internal/notationmidiwriter.cpp:38-40` | `PER_PART` | one file |
| `mei` | `src/importexport/mei/internal/meiwriter.cpp:38-40` | `PER_PART` | one file |
| `wav`, `mp3`, `ogg`, `flac`, `aac` | `src/importexport/audioexport/internal/abstractaudiowriter.cpp:39-41` | `PER_PART` | one file |
| `brf` | `src/braille/internal/braillewriter.cpp:33-35` | `PER_PART` | one file |
| `spos`, `mpos` | `src/notation/internal/positionswriter.cpp:98-100` | `PER_PART` | one file |
| `mscz`, `mscx` | `src/notation/internal/mscnotationwriter.cpp:44-46` | `MULTI_PART` | one file |

Dialogs the export scenario can show from `writeScore` (**CONFIRMED** from
`exportprojectscenario.cpp`):

| Dialog | When | Evidence |
|---|---|---|
| "File already exists … Replace / Replace all / Skip / Skip all" (modal question) | Only when `isCreatingOnlyOneFile` is false **and** the target exists. With one notation that is only `png`/`svg` of a multi-page score. For every other `ext` the policy is pre-set to `ReplaceAll`, so existing files are overwritten silently. | `guessIsCreatingOnlyOneFile` 257-294, policy at 176, `shouldReplaceFile` 344-380, check at 401 |
| "Error: An error occurred while writing the file … Retry / Abort" (modal question) | File cannot be opened for writing, or the writer returns an error. Abort → `Cancel` → `writeScore` returns `false`. | `askForRetry` 384-392, loop 394-445 |
| Progress dialog "Exporting audio…" | Only for writers whose `progress()` is non-null, which is the audio writers (`abstractaudiowriter.cpp:87-90`); every other writer inherits `nullptr` (`src/project/inotationwriter.h:69`), so there is no progress UI for notation, image or MusicXML export. | 144-160, `showExportProgress` 447-452 |
| File chooser | Never. `askExportPath` is not on this path. | helper 34-50 |
| Reveal in file browser | Never (`openDestinationFolderOnExport=false`). | helper 49, scenario 240-242 |

Side effects to know about: uninitialised excerpts selected for export are
initialised (117-130), closed scores are laid out, the view mode is forced to
PAGE for the duration and then restored (141-142, 164), and the whole
loop runs synchronously on the UI thread, so the WebSocket callback that
called `writeScore` blocks until the file is written.

Return value caveat: when the user chooses "Skip" in the overwrite dialog,
`doExportLoop` returns `InternalError`, not `Cancel`, and `exportScores`
keeps going and still returns `true` (only `Cancel` aborts: lines 201-202, 221-222, 234-235). So `true`
does not guarantee that every file was written; check the file afterwards.

### 3.4 4.7.5 `readScore`

`qmlpluginapi.cpp:297-315` → `EngravingPluginAPIHelper::readScore`
(`engravingpluginapihelper.cpp:52-62`) → `ProjectActionsController::openProject(ProjectFile)`
(`src/project/internal/projectactionscontroller.cpp:193-221`, then
`openProject(path, displayNameOverride)` 223-291). **CONFIRMED:**

- `noninteractive=true` → `LOGW "not yet implemented"` and `null` (lines 305-308).
- After `openProject` returns success, the helper returns
  `globalContext()->currentNotation()->elements()->msScore()`, that is
  **whatever score is current in this window**, not necessarily the file
  just opened (helper lines 58-60).
- Steps inside `openProject(path)`:
  1. Same file already open in this window → `doFinishOpenProject()`; the
     returned wrapper is that score. Correct result (line 248-250).
  2. File open in another window → that window is activated, `Ok` is
     returned, and the helper returns **this window's current score**,
     which is the wrong one (253-256).
  3. Any other project open in this window → a **new MuseScore process**
     is spawned with the path as argument
     (`multiwindowsProvider()->openNewWindow(args)`, line 268;
     `src/framework/multiwindows/internal/multiprocess/multiprocessprovider.cpp:258-267`,
     `QProcess::startDetached(applicationFilePath, args)`) and `Ok` is
     returned. The helper again returns the **old** current score. The new
     process has its own plugin instance and its own WebSocket port, so the
     bridge never sees the new score (258-270).
  4. No project open in this window (only reachable from a plugin with
     `requiresScore: false`) → `doOpenProject` loads it here (289-290,
     345-364) and the result is correct.
- Dialogs on the load path (step 4 only): the migration dialog
  `musescore://project/migration` for files with `mscVersion < 400` when
  "ask again" is set (`src/project/internal/projectmigrator.cpp:64-96`,
  101-103); "file too old" / "file too new" / "file corrupted" questions and
  the "cannot be opened" error from `shouldRetryLoadAfterError`
  (`projectactionscontroller.cpp:1745-1768`, called from `loadWithFallback`
  325-343; `warnProjectCannotBeOpened` at 1827); cloud-score paths can trigger a login prompt (272-287).
- Re-entrancy guard: a second `readScore` while one is in progress returns
  `InternalError` (231-233).

Net: in a bridge whose plugin runs inside an open score, `readScore` never
yields the opened file's score object; it either returns the existing score
(same file) or launches another MuseScore window and returns the existing
score. It is usable only as "make MuseScore open this file somewhere".

`closeScore` (4.7.5 `qmlpluginapi.cpp:321-339`): current score only;
`closeOpenedProject` (`projectactionscontroller.cpp:694-745`) shows the
"save changes?" question when the project `needSave()` (line 721) and then
calls `interactive()->closeAllDialogsSync()`. **UNCERTAIN:** whether that
also closes a `pluginType: "dialog"` plugin's own window (it is opened
through the interactive layer) was not traced.

---

## 4. Transposing instruments: `Part.instrumentId` and `Staff.transpose(frac)`

### 4.1 Data model (same at both tags)

**CONFIRMED.** `mu::engraving::Instrument` holds three relevant fields
(4.7.5 `src/engraving/dom/instrument.h:310, 319, 365, 407, 414-415`;
4.4.3 `:325, 334, 380, 419, 426-427`):

- `m_id`: the `instruments.xml` template id, set from the template
  (`src/engraving/dom/instrument.cpp:1182-1184`, `Instrument instrument(templ->id)`),
  e.g. `bb-clarinet`.
- `m_musicXmlId`: the MusicXML sound id (`instrument.cpp:1199`), e.g.
  `wind.reed.clarinet.bflat`.
- `m_transpose`: an `Interval { int8_t diatonic; int8_t chromatic; }`
  (`src/engraving/dom/interval.h:32-41`; 4.4.3 `:35-44`) copied from the
  template (`instrument.cpp:1198`).

Example from `share/instruments/instruments.xml` at v4.7.5 lines 2502-2515
(4.4.3 lines 2409-2422, same values):

```xml
<Instrument id="bb-clarinet">
  <longName>Clarinet</longName>
  <musicXMLid>wind.reed.clarinet.bflat</musicXMLid>
  <transposeDiatonic>-1</transposeDiatonic>
  <transposeChromatic>-2</transposeChromatic>
```

Sign convention: the interval goes from **written to sounding**. `Note`
computes its written tpc as `v.flip(); m_tpc[1] = transposeTpc(m_tpc[0], v, true)`
with `v = staff()->transpose(tick)` (`src/engraving/dom/note.cpp:843-852`),
and `Staff::transpose` derives the written key as the concert key
transposed by the flipped interval (`src/engraving/dom/staff.cpp:861-892`;
4.4.3 `:812`). So for B-flat clarinet `chromatic = -2`:
`sounding = written - 2`, `written = sounding + 2`. **CONFIRMED.**

`Part::instrumentId(tick)` returns `instrument(tick)->id()` at both tags
(4.7.5 `src/engraving/dom/part.cpp:486-489`; 4.4.3 `:482`). Files imported
without an id get one reconstructed by `updateInstrumentId()`
(`instrument.cpp:1253-1262`), so `id` can be empty only transiently.

### 4.2 What the plugin API exposes: the `instrumentId` trap

**CONFIRMED.** The property named `Part.instrumentId` returns a different
field at the two tags:

| Property | 4.7.5 | 4.4.3 |
|---|---|---|
| `Part.instrumentId` | `part()->instrument()->id()` → `bb-clarinet` (`src/engraving/api/v1/part.h:69, 134`) | `part()->instrument()->musicXmlId()` → `wind.reed.clarinet.bflat` (`part.h:67, 117`) |
| `Part.musicXmlId` | `wind.reed.clarinet.bflat` (`part.h:76, 135`; doc at 73: "Was called using instrumentId prior to 4.6") | does not exist |
| `Instrument.instrumentId` | `instrument()->id()` → `bb-clarinet` (`src/engraving/api/v1/instrument.h:380, 419`) | `instrument()->id()` → `bb-clarinet` (`instrument.h:238, 270`) |
| `Instrument.musicXmlId` | `instrument.h:385, 420` | does not exist |
| `Part.instrumentAtTick(int \| Fraction)`, `Part.instrumentIdAtTick(Fraction)` | `part.h:158-180` | `instrumentAtTick(int)` only (`part.h:138`) |

Recommendation for a bridge that must run on both: read
`part.instruments[i].instrumentId` (the template id, stable across both
tags; `Part.instruments` exists at both, `part.h:115` / `:105`) and never
`Part.instrumentId`. Neither tag exposes `Instrument.transpose`.

### 4.3 The transposition interval

**CONFIRMED (4.7.5).** `Staff.transpose(tick: Fraction) → IntervalWrapper`
(`src/engraving/api/v1/elements.h:2403`, documented 2398-2402 as "The
transposition at a given tick in the score, active if the score is not in
concert pitch", `\since 4.6`; implementation `elements.cpp:553-556` wraps
`staff()->transpose(tick->fraction())`). `IntervalWrapper` has read-only
`diatonic`, `chromatic`, `isZero` (`src/engraving/api/v1/apistructs.h:207-215`).
The value is `Staff::transpose` above: the instrument's interval at that
tick (so instrument changes mid-score are honoured), with the diatonic and
chromatic parts re-derived from the concert/written key pair so the
interval is spelled consistently with the key signatures (`staff.cpp:861-892`).
Companions added in 4.6 on `Staff`: `clefType(frac)`, `timeStretch(frac)`,
`timeSig(frac)`, `key(frac)` (written key) (`elements.h:2382-2397`).

**CONFIRMED (4.4.3): not exposed.** The 4.4.3 `Staff` wrapper
(`src/engraving/api/v1/elements.h:900-965`) has only `part` and the generic
properties; no `transpose`, `clefType`, `key` or `timeSig` invokables, no
`IntervalWrapper` (no `apistructs.h` in the 4.4.3 tree), and the
`Instrument` wrapper has no `transpose` property (`instrument.h:238-280`).
`grep -rn transpose src/engraving/api/v1/*.h` at 4.4.3 returns nothing.

### 4.4 Pitches on a transposing part (both tags)

**CONFIRMED.**

- `Note.pitch` is always the **sounding** MIDI pitch
  (`src/engraving/api/v1/elements.h:1404-1406` "MIDI pitch of this note";
  `src/engraving/dom/note.h:535` "Note pitch as midi value"). The API value
  does not change with the Concert Pitch toggle.
- `Note.tpc1` = concert spelling, `Note.tpc2` = written spelling
  (`elements.h:1407-1412`; 4.4.3 `:493-498`). Both writable.
- `Note.tpc` follows the score's Concert Pitch setting: `tpc1` when
  concert pitch is on, else `tpc2` (`elements.h:1413-1416`, getter 1454,
  setter `elements.cpp:168-180` branching on `note()->concertPitch()`;
  4.4.3 `:504`).
- The Concert Pitch flag is the style value `concertPitch`
  (`src/engraving/style/styledef.cpp:515`), readable with
  `curScore.style.value("concertPitch")` (`src/engraving/api/v1/style.h:75`;
  4.4.3 `:64`).

Deriving the transposition on 4.4.3, where `Staff.transpose` is missing:

- Chromatic step modulo octave: `tpc2 - tpc1` is a number of fifths;
  `chromatic ≡ 7 * (tpc1 - tpc2) (mod 12)` and `diatonic ≡ 4 * (tpc1 - tpc2) (mod 7)`
  (same arithmetic as `staff.cpp:874-882`, which uses the key pair). This
  needs at least one note on the staff and cannot recover the octave
  (B-flat clarinet −2 and bass clarinet −14 look the same).
- Octave-exact: map `Instrument.instrumentId` (the template id) to
  `transposeChromatic`/`transposeDiatonic` with a table generated from
  `share/instruments/instruments.xml`. The table is derived data from a
  GPL file; whether shipping it in an MIT plugin is acceptable is a
  licensing question for the owner, not resolved here. **UNCERTAIN** only
  in that sense; the mapping itself is exact for scores created from the
  stock templates.
- On 4.7.5 use `Staff.transpose(frac)` directly.

Written pitch for the model-facing encoding = `Note.pitch - transpose.chromatic`
(so `+2` for B-flat clarinet), spelled with `tpc2`.

---

## Summary table

| # | Question | Verdict |
|---|---|---|
| 1 | Arg-free `cmd()` codes | `play`, `stop`, `rewind`, `insert-measure`, `append-measure`, `file-export` work with no args at both tags. `insert-measures*`/`append-measures` open the count dialog; `file-export` opens the Export dialog. No way to pass a count through `cmd()`. 4.4.3: `stop` pauses; `undo` is bare, 4.7.5 needs `action://notation/undo`. **CONFIRMED** |
| 2 | Import `MuseInternal.Dispatcher` / `MuseApi.Interactive` from v1 | 4.7.5: registered as process-wide QML singletons, so the import should work (**UNCERTAIN**, not run). 4.4.3: impossible (**CONFIRMED**). `Dispatcher.dispatch` passes `int` args only. |
| 3 | `readScore` / `writeScore` fields and dialogs | 4.4.3: both stubs (**CONFIRMED**). 4.7.5: `writeScore(curScore, path, ext)` is dialog-free for single-file formats (silent overwrite), can show overwrite and retry questions for multi-page png/svg or write errors, progress dialog only for audio. `readScore` with a score open spawns a new MuseScore process and returns the old score (**CONFIRMED**). |
| 4 | `Part.instrumentId`, `Staff.transpose` | `Part.instrumentId` means template id on 4.7.5 and MusicXML id on 4.4.3; use `Instrument.instrumentId`. `Staff.transpose(frac)` exists only from 4.6 (4.7.5: `IntervalWrapper{diatonic, chromatic}`, written→sounding). On 4.4.3 derive from `tpc1`/`tpc2` plus an id table. `Note.pitch` is always sounding. **CONFIRMED** |

Implications for the plan: the first release slice on the owner's 4.4.3
install has no file export or silent open from the plugin, no transposition
interval from the API, and no argument-taking actions. All four gaps close
on 4.7.5, so the bridge should feature-detect on `mscoreVersion` and the
owner should consider upgrading MuseScore for development.
