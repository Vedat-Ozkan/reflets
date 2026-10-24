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

## Design this allows

1. Plugin: listen on 8731-8740 in turn, find its port with the nonce probe, write the token to `reflets-token-<port>.txt` (never another instance's file), and show the port in the toast. It reports `Qt.application.state` changes as a last-active time.
2. Server: read every `reflets-token-*.txt`, connect to each port, and drop the ones that do not answer (a closed window leaves a stale file).
3. Which score a tool acts on: the window the user used last, by the bridges' last-active times. `score_info` lists every open score and marks that one. `keep` and `discard` go to the window whose score has the proposal's title, as proposals already record it. Checkpoints are already per title.
4. Ten tools stay ten; no tool takes a score argument unless the last-active rule proves confusing.

## To check in a spike before building

- Sequential `listen` calls in one process end on the first free port (two processes, one already on 8731).
- The nonce probe from `api.websocket` to the plugin's own server works within one process.
- `Qt.application.state` and its change signal reach a v1 plugin, and differ per process.
