# Multi-window spike

Checks the three assumptions in `research/multi-window-2026-10-23.md`. Run 2026-10-23, all passed (results in that note).

1. Copy `reflets-multiwindow-spike.qml` to `Documents/MuseScore4/Plugins/reflets-multiwindow-spike/` and enable it in MuseScore's plugin manager.
2. Open two scores in two MuseScore windows. Run Plugins > Reflets Multiwindow Spike in each, but not in a window running the bridge: plugins in one process share one WebSocket server, so the spike would take the bridge's connections until MuseScore restarts (spec 2.1).
3. `uv run python spikes/multi-window/probe.py`.

Passes when:

- the two windows answer on 8751 and 8752, each with its own score's title (sequential `listen` ends on the first free port);
- each reports `port=` its own port, with `probes` showing `probe mine` for its port and `probe other` for the other (the nonce probe);
- after clicking into one window and running the probe again, that window's `lastActive` is the larger and `changes` grew (`Qt.application.state` per process);
- after quitting the window on 8751 and running the spike in a newly opened one, the new window takes 8751 again.
