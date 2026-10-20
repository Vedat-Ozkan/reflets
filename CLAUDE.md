# Reflets

MCP server (`reflets/`, Python) plus a MuseScore bridge plugin (`plugin/reflets-bridge.qml`, QML). The design is `docs/spec-core.md`; read the relevant section before changing a protocol or tool. Setup is in `README.md`.

## Layout

- `reflets/bridge.py`: WebSocket client for the plugin (token, hello, reconnect once)
- `reflets/score.py`: parses the plugin's `info`/`read` lines into the engine's index
- `reflets/n1x.py`: encodes the score as N1x and decodes N1x ideas (spec 4.2)
- `reflets/write.py`: compiles a decoded N1x idea into the plugin's write ops and checks the read-back
- `reflets/server.py`: MCP tools
- `plugin/reflets-bridge.qml`: the bridge, a macro plugin with no dialog (spec 2.1)
- `tests/live_write.py`: end-to-end check of the write path against a live MuseScore with the nocturne open
- `tests/live_roundtrip.py`: writes every bar of whatever score is open, in the shortest range whose lines close in it, as read, with every mark, decoration and line that closes in the range removed and every lyric line emptied, and as read again, checking each read-back and the discard
- `tests/live_read.py`: end-to-end check of N1x reading against a live MuseScore; `tests/data/bar-fields.mscz` is its score for bar fields and `tests/data/marks.mscz` and `tests/data/system-marks.mscz` for marks, `tests/data/decorations.mscz` for decorations, `tests/data/groups.mscz` for tuplets and groups, `tests/data/lines.mscz` for lines, `tests/data/lyrics.mscz` for lyrics, `tests/data/repeats.mscz` for repeated bars. Scores for the owner to open go in `Documents/MuseScore4/Scores/reflets/` on Windows
- `research/`, `spikes/`: research reports and throwaway spike code, kept as a record

## Environment

- The owner runs MuseScore Studio 4.7.5 on Windows and works in WSL2 with mirrored networking; the server reaches the plugin at `ws://127.0.0.1:8731`.
- Plugin folder from WSL: `/mnt/c/Users/Vedat/Documents/MuseScore4/Plugins/reflets-bridge/`. After editing the plugin, copy it there; MuseScore must be restarted and the plugin run again from Plugins > Reflets Bridge.
- The engine (`import engine`) is `../sheet-music-engine`, a detached worktree of `../sheet-music-plugin` at its `main`, installed editable through `[tool.uv.sources]`. It is a separate worktree so branch switching in `../sheet-music-plugin` doesn't change what Reflets runs. Engine changes Reflets needs are made in that repository on a branch, pass its full test suite, merge to its `main`, then reach Reflets with `git -C ../sheet-music-engine switch --detach main` (spec open question 1). The hosted app also uses the engine and N1: keep changes additive, with default output unchanged.
- MuseScore's log: `%LOCALAPPDATA%\MuseScore\MuseScore4\logs\`.

## Docs conventions

- The spec cites other files by line number (`api:34`, `plan:13`, `notes:140`; key in spec section 0). When editing a cited file, keep existing lines where they are: change lines in place or append at the end, so citations stay valid.
- Owner decisions are recorded in spec section 11 with the date and the original question.
- Write "As built in slice N" notes in the spec when the code departs from or narrows the design.
