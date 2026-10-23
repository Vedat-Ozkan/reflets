# Reflets

A composing companion for MuseScore Studio, served over MCP. A bridge plugin inside MuseScore exposes the open score on a local WebSocket (port 8731); the Reflets MCP server talks to it and gives an MCP host such as Claude Code tools for reading the score.

Status: slices 3 and 4 done. The server reads the open score (`score_info`, `read_score`, notes in N1x with the header and bar fields: repeats, voltas, bar lines, breaks, jumps, markers, key and meter changes) and writes ideas into it in place: `propose` writes an idea in blue as one undo step and checks it by reading it back, `keep` turns it black, `discard` undoes it. `check` lists part-writing faults in chorale-style bars, `analyze` drafts the harmony, `render` engraves bars to a PNG with the findings drawn if asked, `checkpoint` saves the whole score as a MusicXML file under a name (`keep` saves one too) `checkpoints` lists them and `restore` writes chosen bars back as a checkpoint has them, and `doctor` diagnoses the connection.

## Requirements

- MuseScore Studio 4.7 or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. uv fetches Python and the engine ([sheet-music-analysis](https://github.com/Vedat-Ozkan/sheet-music-analysis), from GitHub).
- Optional, for the harmony draft in `analyze`: the AnalysisGNN environment and checkpoint from `sheet-music-plugin` (`.venv-agnn`, `artifacts/models/model.ckpt`; see its README), named by `ANALYSISGNN_PYTHON` and `ANALYSISGNN_CHECKPOINT` in the server's `env`. Without them `analyze` gives the notes table only.

## Install

1. Put the plugin in MuseScore's plugin folder:

   ```
   uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@v0.3.1 reflets install-plugin
   ```

   It copies `reflets-bridge.qml` to `Documents/MuseScore4/Plugins/reflets-bridge/` (from WSL, the Windows user's Documents folder). If MuseScore's plugin folder is elsewhere, set `REFLETS_TOKEN_FILE` to `reflets-token.txt` in that folder, here and in the server's `env`.
2. In MuseScore, enable Reflets Bridge under Home > Plugins.
3. Add the server to your MCP host.
   - Claude Code:

     ```
     claude mcp add reflets -- uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@v0.3.1 reflets
     ```

   - Claude Desktop: Settings > Developer > Edit Config, add the entry below to `claude_desktop_config.json`, and restart Claude. On Windows, use the full path of `uvx.exe` (`C:\Users\<you>\.local\bin\uvx.exe` with the default uv install) and keep the two `UV_` lines: Claude Desktop from the Microsoft Store redirects its programs' writes to `AppData`, which breaks uv's Python install there.

     ```json
     {
       "mcpServers": {
         "reflets": {
           "command": "uvx",
           "args": ["--python", "3.12", "--from", "git+https://github.com/Vedat-Ozkan/reflets@v0.3.1", "reflets"],
           "env": {
             "UV_PYTHON_INSTALL_DIR": "C:\\Users\\<you>\\.local\\share\\uv\\python",
             "UV_TOOL_DIR": "C:\\Users\\<you>\\.local\\share\\uv\\tools"
           }
         }
       }
     }
     ```

To work on Reflets itself, clone this repository, run `uv sync`, copy `.mcp.json.example` to `.mcp.json` with the path to the clone, and start Claude Code in it.

## Use

1. Open a score in MuseScore and run Plugins > Reflets Bridge once per session. It keeps running until MuseScore quits. A small blue pill at the top middle of MuseScore's window says "Reflets listening" when it starts, and for a few seconds after each thing Reflets does (connected, wrote an idea, kept it, undo). It shows only over MuseScore: if you are in another app, it waits until you switch back. After each idea is written, MuseScore scrolls to it and selects it, so Play starts just before it.
2. Ask Claude about the score.

## Docs

- `docs/spec-core.md`: design of the plugin, server, wire protocols and tools
- `docs/plan-2026-10-14.md`: planning and research summary
- `research/`: research reports and spike results

## Licence

MIT, see `LICENSE`.
