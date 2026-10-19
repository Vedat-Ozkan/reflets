# Reflets

A composing companion for MuseScore Studio, served over MCP. A bridge plugin inside MuseScore exposes the open score on a local WebSocket (port 8731); the Reflets MCP server talks to it and gives an MCP host such as Claude Code tools for reading the score.

Status: slice 1. The server has two tools, `score_info` and `read_score`, which return the notes in N1. Checks and writing ideas into the score are designed in `docs/spec-core.md` but not built yet.

## Requirements

- MuseScore Studio 4.7 or later
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- A checkout of the engine, `sheet-music-plugin`, next to this repository (`../sheet-music-plugin`; see `[tool.uv.sources]` in `pyproject.toml`)

## Install

1. Copy `plugin/reflets-bridge.qml` to `Documents/MuseScore4/Plugins/reflets-bridge/reflets-bridge.qml`.
2. In MuseScore, enable Reflets Bridge under Home > Plugins.
3. Copy `.mcp.json.example` to `.mcp.json` and fill in the path to this repository and the path to the token file. The plugin writes the token file next to itself (`reflets-token.txt`). From WSL, that is a path under `/mnt/c/Users/<you>/Documents/...`.

## Use

1. Open a score in MuseScore and run Plugins > Reflets Bridge once per session. The plugin has no window and keeps running until MuseScore quits.
2. Start Claude Code in this directory and ask about the score.

## Docs

- `docs/spec-core.md`: design of the plugin, server, wire protocols and tools
- `docs/plan-2026-10-14.md`: planning and research summary
- `research/`: research reports and spike results

## Licence

MIT, see `LICENSE`.
