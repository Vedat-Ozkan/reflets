# Reflets

A composing companion for MuseScore Studio, served over MCP. A bridge plugin inside MuseScore exposes the open score on a local WebSocket (port 8731); the Reflets MCP server talks to it and gives an MCP host such as Claude Code tools for reading the score.

Status: slices 3 and 4 done. The server reads the open score (`score_info`, `read_score`, notes in N1x with the header and bar fields: repeats, voltas, bar lines, breaks, jumps, markers, key and meter changes) and writes ideas into it in place: `propose` writes an idea in blue as one undo step and checks it by reading it back, `keep` turns it black, `discard` undoes it. `check` lists part-writing faults in chorale-style bars, `analyze` drafts the harmony, `render` engraves bars to a PNG with the findings drawn if asked, `checkpoint` saves the whole score as a MusicXML file under a name (`keep` saves one too) `checkpoints` lists them and `restore` writes chosen bars back as a checkpoint has them, and `doctor` diagnoses the connection.

## Requirements

- MuseScore Studio 4.7 or later
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- The engine from `sheet-music-plugin`, as a worktree of its `main` next to this repository: `git -C ../sheet-music-plugin worktree add --detach ../sheet-music-engine main` (see `[tool.uv.sources]` in `pyproject.toml`). To take newer engine changes: `git -C ../sheet-music-engine switch --detach main`, then `uv sync`.
- Optional, for the harmony draft in `analyze`: the AnalysisGNN environment and checkpoint from `sheet-music-plugin` (`.venv-agnn`, `artifacts/models/model.ckpt`; see its README), named by `ANALYSISGNN_PYTHON` and `ANALYSISGNN_CHECKPOINT` in `.mcp.json`. Without them `analyze` gives the notes table only.

## Install

1. Copy `plugin/reflets-bridge.qml` to `Documents/MuseScore4/Plugins/reflets-bridge/reflets-bridge.qml`.
2. In MuseScore, enable Reflets Bridge under Home > Plugins.
3. Copy `.mcp.json.example` to `.mcp.json` and fill in the path to this repository and, if you have them, the AnalysisGNN paths. The plugin writes a token file next to itself (`reflets-token.txt`); the server looks for it in `Documents/MuseScore4/Plugins/reflets-bridge/`, from WSL in the Windows user's Documents folder. If MuseScore's plugin folder is elsewhere, add `REFLETS_TOKEN_FILE` with the token file's path to `env`.

## Use

1. Open a score in MuseScore and run Plugins > Reflets Bridge once per session. It keeps running until MuseScore quits. A small blue pill at the top middle of the screen says "Reflets listening" when it starts, and for a few seconds after each thing Reflets does (connected, wrote an idea, kept it, undo). After each idea is written, MuseScore scrolls to it and selects it, so Play starts just before it.
2. Start Claude Code in this directory and ask about the score.

## Docs

- `docs/spec-core.md`: design of the plugin, server, wire protocols and tools
- `docs/plan-2026-10-14.md`: planning and research summary
- `research/`: research reports and spike results

## Licence

MIT, see `LICENSE`.
