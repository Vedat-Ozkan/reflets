# Reflets

MCP server (`reflets/`, Python) plus a MuseScore bridge plugin (`plugin/reflets-bridge.qml`, QML). The design is `docs/spec-core.md`; read the relevant section before changing a protocol or tool. Setup is in `README.md`.

## Layout

- `reflets/bridge.py`: WebSocket client for the plugin (token, hello, reconnect once)
- `reflets/score.py`: parses the plugin's `info`/`read` lines into the engine's index
- `reflets/n1x.py`: encodes the score as N1x and decodes N1x ideas (spec 4.2)
- `reflets/write.py`: compiles a decoded N1x idea into the plugin's write ops and checks the read-back
- `reflets/restore.py`: builds the two ideas `restore` writes: the current bars cleared of their details, then the checkpoint's bars
- `reflets/server.py`: MCP tools
- `plugin/reflets-bridge.qml`: the bridge, a macro plugin with no dialog (spec 2.1)
- `tests/live_write.py`: end-to-end check of the write path against a live MuseScore with the nocturne open
- `tests/live_roundtrip.py`: writes every bar of whatever score is open, in the shortest range whose lines close in it, as read, with every mark, decoration and line that closes in the range removed and every lyric line emptied, and as read again, checking each read-back and the discard, and that stem directions and beam modes stay as read
- `tests/live_recast.py`: end-to-end check of recasting bars in a longer and a shorter meter (`recast=True`) against a live MuseScore with `tests/data/recast.musicxml` open (as an import)
- `tests/live_doctor.py`: end-to-end check of the connection checklist (`diagnose`, which `score_info` returns when MuseScore cannot be reached) against a live MuseScore running the bridge, plus a wrong plugin folder, an unset or missing harmony model, a plugin file of another protocol, a closed port and another server on the port
- `tests/live_check.py`: end-to-end check of `check` against a live MuseScore, by the open score's title: `tests/data/part_writing_motion.musicxml` (planted errors), `tests/data/bwv66.6.musicxml` (a chorale with a pickup), or any other score, where the rules must say they do not apply; each opened as an import
- `tests/live_render.py`: end-to-end check of `render` (plugin export, engraving, findings drawn, an idea in colour) against the same scores as `tests/live_check.py`
- `tests/live_analyze.py`: end-to-end check of `analyze` against any open score, with and without the AnalysisGNN model (`ANALYSISGNN_PYTHON`, `ANALYSISGNN_CHECKPOINT`)
- `tests/live_checkpoint.py`: end-to-end check of `checkpoint`, the checkpoint `keep` saves, and the list `restore()` gives without a checkpoint, against any open score; it removes the checkpoint files it made, as `live_write` and `live_recast` do
- `tests/live_restore.py`: end-to-end check of `restore` against any open score: a dynamic, staccato, slur, lyric and new notes are taken back to a checkpoint, discard and keep of a restore, a restore of every bar, an unknown checkpoint
- `tests/live_proposals.py`: end-to-end check that open proposals outlive the server: proposed in one process, discarded or kept in another, ids not reused, one from another score refused
- `tests/live_lines.py`: end-to-end check that a hairpin the bridge made can be removed after the notes under it were rewritten (a MuseScore crash before plugin 0.24.1); run it on `tests/data/recast.musicxml`, one staff, where the rewrite empties the bar's segments
- `tests/live_fermata.py`: end-to-end check of ideas that rewrite a voice holding a fermata, against a live MuseScore with `tests/data/bwv66.6.musicxml` open (as an import)
- `tests/reading_capture.py`: saves the open score's `info` and `read` lines and the live `read_score` text of every bar range to a JSON file in `tests/data/reading/`
- `tests/reading_accuracy.py`: decision 22's release test: Sonnet 5.5 at effort low and medium answers 40 computed questions on which note starts or sounds where, through a `read_score` tool served from `tests/data/reading/` (chorale, nocturne, groups, lyrics) with the server instructions; needs `Anth_Key` and `uv run --with anthropic`; medium passes at 95%
- `tests/live_read.py`: end-to-end check of N1x reading against a live MuseScore; `tests/data/bar-fields.mscz` is its score for bar fields and `tests/data/marks.mscz` and `tests/data/system-marks.mscz` for marks, `tests/data/decorations.mscz` for decorations, `tests/data/groups.mscz` for tuplets and groups, `tests/data/lines.mscz` for lines, `tests/data/lyrics.mscz` for lyrics, `tests/data/repeats.mscz` for repeated bars, `tests/data/keys.musicxml` (opened as an import) for a transposing staff's key. Scores for the owner to open go in `Documents/MuseScore4/Scores/reflets/` on Windows
- `research/`, `spikes/`: research reports and throwaway spike code, kept as a record

## Environment

- The owner runs MuseScore Studio 4.7.5 on Windows and works in WSL2 with mirrored networking; the server reaches the plugin at `ws://127.0.0.1:8731`.
- Plugin folder from WSL: `/mnt/c/Users/Vedat/Documents/MuseScore4/Plugins/reflets-bridge/`. After editing the plugin, copy it there; MuseScore must be restarted and the plugin run again from Plugins > Reflets Bridge.
- The engine (`import engine`) is the `sheet-music-analysis` package of `../sheet-music-plugin`, installed from GitHub at the tag in its `dependencies` entry in `pyproject.toml` (v0.1.0), a plain git reference so `uvx` and pip installs get it too. Engine changes Reflets needs are made in that repository on a branch, pass its full test suite, merge to its `main` and get a new tag, which that entry then names. To try unreleased engine changes, add `[tool.uv.sources]` with `sheet-music-analysis = { path = "../sheet-music-engine", editable = true }`, a detached worktree of `../sheet-music-plugin` at the commit to try, and remove it before committing.
- Users install with `uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@<tag> reflets` (README); the wheel carries the plugin (`force-include`), and `reflets install-plugin` copies it to MuseScore's plugin folder. A release needs the version bumped, a tag pushed, and the tag in the README updated. The hosted app also uses the engine and N1: keep changes additive, with default output unchanged.
- MuseScore's log: `%LOCALAPPDATA%\MuseScore\MuseScore4\logs\`.

## Docs conventions

- The spec cites other files by line number (`api:34`, `plan:13`, `notes:140`; key in spec section 0). When editing a cited file, keep existing lines where they are: change lines in place or append at the end, so citations stay valid.
- Owner decisions are recorded in spec section 11 with the date and the original question.
- Write "As built in slice N" notes in the spec when the code departs from or narrows the design.
