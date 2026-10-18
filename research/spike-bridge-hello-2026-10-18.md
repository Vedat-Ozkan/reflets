# Spike: bridge hello, read, write, undo on MuseScore 4.7.5 (Windows), 2026-10-18

Throwaway code in `spikes/bridge-hello/`: `reflets-bridge-hello.qml` (v1 dialog plugin), `probe.py` (WSL client, `websockets` 13.1), `screenshot.ps1` (captures the MuseScore window from WSL through `powershell.exe`).

Setup: the owner's Windows install, `mscoreVersion` 40705. Plugin copied to `C:\Users\Vedat\Documents\MuseScore4\Plugins\reflets-bridge-hello\`, enabled in Home > Plugins, run by hand on a new untitled score (treble staff, 4/4). Client in WSL2 (mirrored networking) at `ws://127.0.0.1:8731`.

## Results

| Check | Result |
|---|---|
| Plugin listed and opens with Qt 6 imports (`QtQuick 2.15`, `QtQuick.Controls 2.15`, `MuseScore 3.0`) | pass |
| `api.websocketserver` defined in a v1 plugin (`typeof` = `object`) | pass |
| `listen(8731, cb)` | works; returns `undefined`, so it cannot report a bind failure |
| WSL reaches the Windows plugin at 127.0.0.1 (`nc -vz`, then WebSocket) | pass; no firewall prompt seen |
| Client ids | 2002, 2003 on successive connections (the `nc` probe used one) |
| `hello` + 20 `ping` round trips | all answered, ids echoed; RTT min 0.26 ms, median 0.33 ms, max 0.65 ms |
| `read1` on an empty bar | `R 0 0 4/4` (whole-bar rest, duration reported as the full bar) |
| `write1`: `startCmd`, cursor `track=0`, `rewindToTick(0)`, `setDuration(1,4)`, `addNote(60,false)`, `endCmd(false)` | note landed: `C 0 0 1/4 60:14:14`, rest of the bar filled as `R 480 0 1/4`, `R 960 0 1/2`; visible on screen |
| `cmd("action://notation/undo")` from the plugin, once | bar back to `R 0 0 4/4`; screenshot confirms the note is gone |

Raw probe output (second run, plugin 0.0.2):

```
1 ok proto=0 plugin=reflets-bridge-hello/0.0.2 mscore=40705 ws=object score=1 title=Untitled score
2 ok
R 0 0 4/4
2 ok
C 0 0 1/4 60:14:14
R 480 0 1/4
R 960 0 1/2
2 ok action://notation/undo
R 0 0 4/4
2 ok
R 0 0 4/4
```

## Spec claims

- Confirmed: `deep:6` / `deep:17` (WebSocket server API present in an official 4.7.5 build, v1 plugin), `rig:30` (WSL to Windows over 127.0.0.1 in mirrored mode, on this machine), ids from 2001 upward (`deep:6`), spec 6.3 only partly (one wrapped op undoes in one step; a single `addNote` is one command anyway, so grouping several ops under one `startCmd` is not yet shown), spec 6.4 steps 1–2 (landing through track then `rewindToTick`; note entry fills the remainder with rests), spec 6.8 (`action://notation/undo` works on 4.7), `Note.tpc1/tpc2` readable.
- New: `listen` returns nothing, so a bind failure (port taken by a stale instance) is invisible to the plugin; the server's `hello` is the only detector, as the spec already assumes.

## The owner's own undo

After a second `write1`, the owner's Edit menu showed **"Undo 'Reflets: write1'"**, enabled, with the plugin's `startCmd` label as the history entry name. The owner then undid it from MuseScore. `read1` returned `R 0 0 4/4`, and a screenshot showed bar 1 empty. Spec 6.3's "discard = one Ctrl+Z" holds for a single wrapped op.

Toolbar quirk: the toolbar undo/redo arrows stayed greyed after the plugin's write and after the plugin's `cmd(undo)`. After the owner's own undo, redo lit up. So the toolbar refreshes on GUI actions but not after plugin changes. The Edit menu is correct. This is cosmetic and doesn't affect the design.

## Not tested after round 1

Several ops in one undo step, chords, voice 2, spelling, ties, annotations and tuplets are covered in round 2 below. Still open: other staves, larger scores (fp timing), bar numbers with a pickup, `readScore`/`writeScore`. 4.4.x is out of scope (spec 2.5).

## Round 2: plugin 0.0.3, write-path checks (same day, new untitled score, treble, 4/4)

Each verb is one `startCmd`/`endCmd`. Cursor landing as spec 6.4: `track=0`, `rewindToTick(barTick)`, then `track=<target>`.

| Verb | Ops | Read-back | Screen |
|---|---|---|---|
| `multi` (bar 1) | voice 1: `addNote(60)`, `addNote(64,true)`, `addNote(63)`, half `addNote(67)`; voice 2: whole `addNote(60)`; then respell the 63 found by tick | `C 0 0 1/4 60:14:14,64:18:18`, `C 0 1 1/1 60:14:14`, `C 480 0 1/4 63:21:21`, `C 960 0 1/2 67:15:15`; MuseScore had spelled 63 as Eb (11), the pass set D# (21) | matches |
| `tie` (bar 2) | G4, G4 quarters, half rest; `selection.select(firstNote)` returned `true`; `cmd("tie")` | notes present, **no tie flags** | **no tie**; the first G stays selected |
| `annot` (bar 1 beat 1) | `newElement(HARMONY/DYNAMIC/STAFF_TEXT)`, `cursor.add`, then `text` | `A 0 0 Harmony text=Cmaj7`, `A 0 0 Dynamic dynamicType=0 text=mf`, `A 0 0 StaffText text=reflets` | all three shown, no crash |
| `tuplet` (bar 3) | `addTuplet(fraction(3,2), fraction(1,4))`, three eighths | `C 3840 0 1/8 72:14:14 t=3/2` ×3 at 3840/4000/4160, then `R 4320 1/4`, `R 4800 1/2` | triplet with "3" |

Undo chain: four `cmd("action://notation/undo")`, one read after each. tuplet → bar 3 empty; annot → bar 1 notes back without the `A` lines; tie → bar 2 empty; multi → bar 1 empty. **Each write, including the seven-op `multi`, is exactly one undo step: spec 6.3 grouping confirmed.**

Findings:
- **Ties do not work as specced (6.5).** `select(note)` inside `startCmd` then `cmd("tie")` produced nothing. Not yet known whether the action needs to run outside the command, needs another code, or never works from a plugin; the next round tries variants.
- Dynamic with `text="mf"` reads back `dynamicType=0`: the text shows, but the type (and so playback velocity) is probably not mf. Needs a check of the enum and of setting `dynamicType` directly.
- Chord symbol with text set after `cursor.add`: no crash on 4.7.5.
- Respelling by `tpc1`/`tpc2` after entry works.
- Owner report: quitting MuseScore with the plugin window still open took noticeably long. Not measured yet.
- `screenshot.ps1` first used a screen copy, which captured an unrelated window covering MuseScore; it now uses `PrintWindow` with `PW_RENDERFULLCONTENT`, which captures MuseScore even when covered (the plugin dialog is a separate window and is not included).

## Round 3: plugin 0.0.4, why the tie failed, and dynamics

Diagnosis from MuseScore's own log (`%LOCALAPPDATA%\MuseScore\MuseScore4\logs\MuseScore_<date>.log`): round 2's `cmd("tie")` logged `ActionsDispatcher::doDispatch | no one can handle the action: tie`. Source at v4.7.5: `tie` is registered with the default enabler `isNotationPage` (`notationactioncontroller.h:234`), which asks `UiContextResolver::matchWithCurrent(UiCtxProjectOpened)`; the plugin's open dialog changes the current UI context, so the controller declines. Undo has its own enabler (`canUndo`), which is why undo worked.

Test: `install.sh` installs the same QML twice: as the dialog plugin (8731) and as a macro plugin with no `pluginType` (8732). New scratch score; only the macro run.

| Step (macro, no dialog open) | Result |
|---|---|
| `tie` (bar 2, inside `startCmd`) | `C 1920 0 1/4 67:15:15:f`, `C 2400 0 1/4 67:15:15:b`; tie visible; log `try call action: tie` |
| `dyn` bar 5: `dynamicType = DynamicType.MF` only | `dynamicType=8 velocity=80 text=` (empty); nothing visible |
| `dyn` bar 6: `text = "mf"` then `dynamicType = DynamicType.MF` | `dynamicType=8 velocity=80 text=mf`; mf visible |
| `undo` ×2 | dyn gone from bars 5 and 6, then bar 2 back to a whole rest (tie and notes in one step) |

Then the owner opened the dialog plugin as well:

| Step (dialog open) | Result |
|---|---|
| connect to 8731 | timed out: nothing listening |
| connect to 8732 | answered with `port=8731`, i.e. by the dialog instance's code |
| `tie` inside `startCmd` (bar 2) | notes written, no tie; log `no one can handle the action: tie` |
| `tieout`: notes in one command, then `select` + `cmd("tie")` after `endCmd` (bar 4) | notes written, no tie; same log line |

Findings:
- **The bridge cannot be a dialog plugin.** With any plugin dialog open, notation actions gated on `isNotationPage` are refused. A macro plugin has no dialog, and its object is never deleted (`legacy/extpluginrunner.cpp:49-61`: `component.create()`, no delete), so its server keeps running until MuseScore quits.
- **One shared WebSocket server per MuseScore** (`websocketserverapi.cpp`): all v1 plugins share one `WebSocketServerApi`. The dialog's `listen(8731)` failed silently (already listening on 8732) but replaced `m_onNewConnected`, so new connections went to the dialog's code.
- The server does handle socket disconnects internally (it deletes the socket and drops the client id); only JS gets no callback.
- Dynamics: set `text`, then `dynamicType`.
- Owner report: quitting MuseScore was faster this time (one to two seconds) than with the dialog open in round 2. Not measured.

Spec updated: 2.1 (no dialog, lifecycle, shared server), 2.2 (port constant, security decision), 6.5 step 4, 6.7, open question 4.

## Round 4: plugin 0.0.5 (macro only), real and large scores, bar numbers, writeScore, readScore

Scores in `C:\Users\Vedat\Documents\MuseScore4\Scores\reflets-spike\`: `chopin_nocturne_op9_no2.musicxml` (from `sheet-music-plugin/out/`, 38 bars, pickup, grace notes, tuplets, a 2/4 bar) and `big-300x16.musicxml` from `make_big_score.py` (300 bars, 16 single-staff parts, eighth notes everywhere = 38,400 notes, a chord symbol per bar and a dynamic every 8 bars in part 1). `readall <from> <to> [count]` walks every track of the range; `walk_ms` is measured in QML with `Date.now()`.

| Check | Result |
|---|---|
| Nocturne `stats` | 38 bars, 2 staves, 8 tracks, part "Piano" |
| Nocturne bar numbers (`bars 1 4`, `bars 36 38`) | index 1: `no=0 irregular=true ticks=1/8` (pickup); index 2: `no=0`; index 3: `no=1`; index 36: `no=34 ticks=2/4` (meter change). The pickup shares `no` with the first full bar, as the source read said. Not compared with the screen. |
| Nocturne full read | 881 lines, 27,973 chars, walk 6–7 ms; 66 ms round trip including connect. 809 chord, 15 grace, 6 rest, 51 annotation lines, 29 events in tuplets; **1,253 notes, the same count the engine gave for this file** |
| Annotation text | carries MuseScore markup: `<sym>dynamicPiano</sym>`, `<font size="12"/><b>Andante</b>`; types seen: StaffText, Expression, Dynamic (`dynamicType=6`, velocity 65), Tempo |
| `writeScore(curScore, "C:/.../export-chopin.musicxml", "musicxml")` | `true` in 32 ms, no dialog; file has 38 bars and 15 grace notes |
| `readScore(big)` with the nocturne open | returned the nocturne (`returned=chopin…`, `current=chopin…`); a **second MuseScore4 process** appeared with `big-300x16.musicxml` |
| Big score (bridge started in the second process after the first was closed) `stats` | 300 bars, 16 staves, 64 tracks |
| Big score full read | 38,738 lines, 971,088 chars, walk 214, 226, 238 ms; whole transfer to WSL 0.5 s including connect; 38,400 notes and 338 annotations, matching the file |
| Big score windows | bars 1–16: 2,066 lines, 17 ms; bars 1–32: 4,132 lines, 17 ms |
| `File > Close` with the bridge running, then `readScore(nocturne)` with no score open | the bridge survived the close; the nocturne loaded in the same window and was returned (`before=none returned=chopin… current=chopin…`) |

Findings:
- Read speed is not a constraint: a 16–32 bar window is ~17 ms, and even a whole orchestral-size score is about a quarter second of UI-thread time.
- `writeScore` works on 4.7.5 for the current score.
- **`readScore` does not open a tab** when a score is open: it starts a new process that the bridge cannot reach. Spec 7.2 (layout C) needs a redesign.
- The macro bridge outlives closing the score.
- A first attempt at `open` failed because the plugin refused every verb except `hello`/`ping` when no score was open; fixed in the same round (the verb is now handled before the score check).
