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

## Not tested

- Several ops under one `startCmd` undoing in one step (for example two notes plus a `tpc1`/`tpc2` change). Planned for the next plugin version.
- Chords, other voices, other staves, spelling writes, ties, annotations, larger scores: the rest of the spike list in `docs/spec-core.md` §10.
- 4.4.x (the owner now runs 4.7.5).
