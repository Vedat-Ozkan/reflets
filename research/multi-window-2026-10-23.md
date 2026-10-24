# Several MuseScore windows, 2026-10-23

Question: can Reflets serve a score in each of several MuseScore windows at once?

## What happens today

MuseScore 4 opens each further score in a new process (one score per window). The owner opened the nocturne from Explorer while the chorale was open and ran the bridge in both.

- `netstat -ano` shows only the first process (the chorale) listening on 8731, on `0.0.0.0` and `[::]`. The second process's `listen(8731)` failed: Windows refuses a second bind of the port.
- The second bridge still wrote a fresh token to `reflets-token.txt` and showed "listening". Every new connection then reached the first process with the second's token and was refused ("token does not match").

## MuseScore 4.7.5 source (`src/framework/network/api/`)

- `WebSocketServerApi` is one `QWebSocketServer` per plugin engine. `listen(port, cb)` stores `cb` and calls `m_server->listen(QHostAddress::Any, port)`, ignoring the result; the JS call returns nothing (`spike-bridge-hello` 2026-10-18). A `QWebSocketServer` that is already listening refuses another `listen` and keeps its port; one whose bind failed can try another port.
  - So calling `listen` on 8731, 8732, … in turn leaves the plugin listening on the first free port, without knowing which.
- `WebSocketApi` (`api.websocket`) is a client: `open(port, onConnected)`, `onMessage`, `send`, `close`. `onConnected` fires only on success; there is no error callback.
  - So the plugin can find its own port: open a client to each candidate port and send a probe carrying a random nonce. Its own server sees its own nonce; another process's bridge does not.
- Nothing in the API names the process or the window. `Qt.application.state` is part of every QML engine (`Qt.ApplicationActive` when the process has the focused window), so each bridge could record when its window was last active. Not yet tried in a v1 plugin engine.

## Spike results (2026-10-23, `spikes/multi-window/`)

Run in three MuseScore 4.7.5 windows (lyrics, the nocturne, then groups in place of lyrics), next to the chorale's bridge on 8731. All passed:

- Sequential `listen` on 8751-8755: the first window listened on 8751, the second on 8752 (`netstat` showed each port held by its own process). MuseScore logs `QTcpServer::listen() called when already listening` for each refused call.
- The nonce probe through `api.websocket`: each window reported `probe mine` for its own port and `probe other` for the other's; ports with nothing listening never call `onConnected`, so they stay "no answer" without an error.
- `Qt.application.state` reaches a v1 plugin and is per process: 4 (active) in the window in front, 2 in the other; bringing a window forward raised its `lastActive` above the other's and counted a change.
- After the 8751 window was closed, the spike in a newly opened window took 8751 again.

Also seen: running a second plugin that calls `listen` (the old Reflets Spike, run by a mis-click) in the bridge's window takes the bridge's connections; running Reflets Bridge again takes them back, as spec 2.1 says.

## Design this allows

1. Plugin: listen on 8731-8740 in turn, find its port with the nonce probe, write the token to `reflets-token-<port>.txt` (never another instance's file), and show the port in the toast. It reports `Qt.application.state` changes as a last-active time.
2. Server: read every `reflets-token-*.txt`, connect to each port, and drop the ones that do not answer (a closed window leaves a stale file).
3. Which score a tool acts on: the window the user used last, by the bridges' last-active times. `score_info` lists every open score and marks that one. `keep` and `discard` go to the window whose score has the proposal's title, as proposals already record it. Checkpoints are already per title.
4. Ten tools stay ten; no tool takes a score argument unless the last-active rule proves confusing.

## To check in a spike before building

- Sequential `listen` calls in one process end on the first free port (two processes, one already on 8731).
- The nonce probe from `api.websocket` to the plugin's own server works within one process.
- `Qt.application.state` and its change signal reach a v1 plugin, and differ per process.

## Server half (branch `multi-window`, 2026-10-23)

Built and checked against two fake bridges (websocket servers answering `hello`, `ping` and `info` with captured lines), not against MuseScore: the window used last is chosen once per tool call; `keep` and `discard` go to the window holding the proposal's score; two windows with one score are refused; a bridge that does not answer, the 8731 one included, is skipped until its token file is rewritten, because under WSL's mirrored networking a closed port times out (10 s) instead of refusing. After the first window closes, the next call takes about 2 s, later ones none.

Follow-ups:

- Done 2026-10-24, plugin 0.25.0: the bridge listens on the first free port of 8731-8740, finds it with a `probe <nonce>` verb answered before `hello`, writes `reflets-token.txt` on 8731 and `reflets-token-<port>.txt` elsewhere, and answers `ping` with `active=<ms>`. Protocol stays 24: a 0.3.3 server keeps talking to 8731 and is no longer broken by a second window. `tests/live_windows.py` passed in three windows (the owner's chorale on plugin 0.24.6, groups and lyrics on 0.25.0); `live_proposals`, `live_checkpoint`, `live_restore` and `live_doctor` passed with the three open.
- Done: `diagnose` checks the 8731 bridge, and `live_doctor` pins its port-8739 checks to it.
- When the window used last has no score open but another window has one, tools report "no score open". Decide whether to fall back to the other window.
