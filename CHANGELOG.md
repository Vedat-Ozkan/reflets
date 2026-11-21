# Changelog

## Unreleased

- Ideas show in violet, coloured whole, and `keep` turns them black on the kept bars.
- `discard` writes an idea's bars back when later changes came after it, instead of refusing.
- `score_info` lists the open ideas, and leaves out any undone in MuseScore.
- A write that the plugin answered with an error after it may have landed stays recorded and is checked on the next call.
- Plainer setup and messages: Claude Desktop config for Windows, and the status pill says why the bridge cannot start.

## v0.5.3 (2026-11-13)

- A write whose answer never came is recorded first, then settled by reading its bars back on the next call.
- The humming test no longer uploads the device name.
- The plugin's hello names the installed version.

## v0.5.2 (2026-11-06)

- A change whose answer never came is not sent again.
- Calibration beats the last take's delay.
- A failed details upload is sent again.

## v0.5.1 (2026-11-05)

- Bars are found by position.
- A repeated bar number reads as `mNb`, `mNc`.

## v0.5.0 (2026-10-31)

- `hum`: hum a line into a staff, with rests, repeated notes, slides and a tempo mark when the take's tempo differs from the score's.
- The delay between click and mic is found from where the hummed notes start.
- Pitches more than a quarter of a semitone out of key are snapped to the key.
- A humming test for testers: Claude walks them through the tunes and uploads the takes.
- A voice written twice is refused, as are zero durations, values under a 128th and reversed bar ranges.

## v0.4.0 (2026-10-24)

- Several MuseScore windows can each run the bridge (plugin 0.25.0); each tool call uses the window active last.
- `discard` and `keep` close a proposal that is no longer in the score and say so.
- Setup for Codex added to the README.

## v0.3.3 (2026-10-23)

- `score_info` lists the open score's checkpoints.
- `restore` takes a checkpoint and bars again, because Claude Desktop's permission check refused listing through it.

## v0.3.2 (2026-10-23)

- Ten tools: the connection checklist moved into `score_info`, and the checkpoint list into `restore`.
- The harmony model is used only when `ANALYSISGNN_PYTHON` and `ANALYSISGNN_CHECKPOINT` name existing files.
- The status toast is drawn inside MuseScore's window and moves with it (plugin 0.24.6).

## v0.3.1 (2026-10-23)

- One-command install: `reflets install-plugin` copies the plugin to MuseScore's plugin folder.
- Native Windows finds the Documents folder through PowerShell.
- The connection checklist names unset model variables.

## Before v0.3.1 (2026-10-18 to 2026-10-22)

- Reads the open score as N1x: notes, marks, decorations, lines, lyrics, repeats and bar fields.
- `propose`, `keep` and `discard` write ideas into the score in one undo step, checked by reading them back.
- Ideas keep the score's marks, decorations, lines and lyrics, and can change meter, key and repeats.
- `check`, `analyze` and `render` give part-writing faults, a harmony draft and an engraved PNG.
- `checkpoint` and `restore` save the whole score and write chosen bars back.
- A status toast shows what Reflets did.
