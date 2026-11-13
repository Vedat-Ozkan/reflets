# Reflets

A composing companion for MuseScore Studio, served over MCP. A bridge plugin inside MuseScore exposes the open score on a local WebSocket (port 8731); the Reflets MCP server talks to it and gives an MCP host such as Claude Code tools for reading the score.

Status: slices 3 and 4 done. The server reads the open score (`score_info`, `read_score`, notes in N1x with the header and bar fields: repeats, voltas, bar lines, breaks, jumps, markers, key and meter changes) and writes ideas into it in place: `propose` writes an idea in blue as one undo step and checks it by reading it back, `keep` turns it black, `discard` undoes it. `check` lists part-writing faults in chorale-style bars, `analyze` drafts the harmony, `render` engraves bars to a PNG with the findings drawn if asked, `checkpoint` saves the whole score as a MusicXML file under a name (`keep` saves one too, and `score_info` lists them), and `restore` writes chosen bars back as a checkpoint has them. When MuseScore cannot be reached, `score_info` says why with a checklist.

## Requirements

- MuseScore Studio 4.7 or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) and Git. uv fetches Python and the engine ([sheet-music-analysis](https://github.com/Vedat-Ozkan/sheet-music-analysis), from GitHub).
- Optional, for the harmony draft in `analyze`: the AnalysisGNN model. It is not part of the install: it runs in its own Python environment with PyTorch, set up from a clone of [sheet-music-analysis](https://github.com/Vedat-Ozkan/sheet-music-analysis) as its README's "Draft model" section says (`.venv-agnn` and `artifacts/models/model.ckpt`). Name the two in the server's `env`, as absolute paths: `ANALYSISGNN_PYTHON` the environment's Python (`.venv-agnn/bin/python`, on Windows `.venv-agnn\Scripts\python.exe`) and `ANALYSISGNN_CHECKPOINT` the checkpoint. Without them `analyze` gives the notes table only, and says so.

- Optional, for `hum` (humming a line into the score): a microphone, and the `hum` extra, which adds SwiftF0, ONNX Runtime and sounddevice (about 40 MB). Install with `--from 'reflets[hum] @ git+https://github.com/Vedat-Ozkan/reflets@v0.5.2'` in place of the `--from` below. On Linux and WSL, also `sudo apt install libportaudio2 libasound2-plugins pulseaudio-utils` and an `~/.asoundrc` with `pcm.!default { type pulse }` and `ctl.!default { type pulse }`, so the default device reaches WSLg's microphone and speakers.

## Install

1. Put the plugin in MuseScore's plugin folder:

   ```
   uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@v0.5.2 reflets install-plugin
   ```

   It copies `reflets-bridge.qml` to `Documents/MuseScore4/Plugins/reflets-bridge/` (from WSL, the Windows user's Documents folder). If MuseScore's plugin folder is elsewhere, set `REFLETS_TOKEN_FILE` to `reflets-token.txt` in that folder, here and in the server's `env`.
2. In MuseScore, enable Reflets Bridge under Home > Plugins.
3. Add the server to your MCP host.
   - Claude Code:

     ```
     claude mcp add reflets -- uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@v0.5.2 reflets
     ```

   - Claude Desktop: Settings > Developer > Edit Config, add the entry below to `claude_desktop_config.json`, and restart Claude. On Windows, use the full path of `uvx.exe` (`C:\Users\<you>\.local\bin\uvx.exe` with the default uv install) and keep the two `UV_` lines: Claude Desktop from the Microsoft Store redirects its programs' writes to `AppData`, which breaks uv's Python install there.

     ```json
     {
       "mcpServers": {
         "reflets": {
           "command": "uvx",
           "args": ["--python", "3.12", "--from", "git+https://github.com/Vedat-Ozkan/reflets@v0.5.2", "reflets"],
           "env": {
             "UV_PYTHON_INSTALL_DIR": "C:\\Users\\<you>\\.local\\share\\uv\\python",
             "UV_TOOL_DIR": "C:\\Users\\<you>\\.local\\share\\uv\\tools"
           }
         }
       }
     }
     ```

   - Codex:

     ```
     codex mcp add reflets -- uvx --python 3.12 --from git+https://github.com/Vedat-Ozkan/reflets@v0.5.2 reflets
     ```

     The first start installs Reflets, which can take longer than Codex's 10-second start limit. Add `startup_timeout_sec = 120` under `[mcp_servers.reflets]` in `~/.codex/config.toml`.

To work on Reflets itself, clone this repository, run `uv sync`, copy `.mcp.json.example` to `.mcp.json` with the path to the clone, and start Claude Code in it.

## Use

1. Open a score in MuseScore and run Plugins > Reflets Bridge once per session. It keeps running until MuseScore quits. A small blue pill at the top middle of MuseScore's window says "Reflets listening" when it starts, and for a few seconds after each thing Reflets does (connected, wrote an idea, kept it, undo). It shows only over MuseScore: if you are in another app, it waits until you switch back. After each idea is written, MuseScore scrolls to it and selects it, so Play starts just before it.
2. Ask Claude about the score, or to let you hum a line ("let me hum a melody into the flute from bar 9"). Reflets plays a bar of count-in clicks, then records you for the bars asked while the click goes on, and writes what you hummed as a blue idea. Speakers work best: each take then measures the delay between click and microphone from its own clicks. On headphones the delay is found from where your notes start; if notes still land late or early, ask Claude to calibrate humming (you say "ta" on 8 clicks).
   With scores open in several MuseScore windows, run the bridge in each; Claude works on the window you used last, so click into a window to work on its score.
3. If you were given a tester code: install with the `hum` extra, open a new empty 4/4 score, and tell Claude "let's do the humming test". It takes about ten minutes: Reflets plays eight short tunes one at a time and you hum each back along with the click. At the end Claude asks for your code, and the recordings are sent to the developer only if you agree.

   What is sent: for each tune, the recording of your humming and what Reflets heard and wrote from it (the notes, tempo, key and the staff's instrument), with your tester code. Not your name, your score, or the name of your microphone or headphones. The recordings are stored in the developer's Cloudflare storage until the developer downloads them, which deletes them there; the developer then keeps the downloaded copies to improve humming, with no set end date. To have yours deleted, ask the person who gave you your tester code, and tell them the code.

## Docs

- `docs/spec-core.md`: design of the plugin, server, wire protocols and tools
- `docs/plan-2026-10-14.md`: planning and research summary
- `research/`: research reports and spike results

## Licence

MIT, see `LICENSE`.
