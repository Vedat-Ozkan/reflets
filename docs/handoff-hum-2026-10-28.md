# Handoff: testing `hum` from Claude Desktop (2026-10-28)

For a Claude session in the Claude desktop app, with computer use on, picking up the humming feature of Reflets. The repository is in WSL: `/home/kema/projects/reflets` (from Windows: `\\wsl.localhost\Ubuntu\home\kema\projects\reflets`). Read `CLAUDE.md` there first; the owner's global rules apply (minimal code, no comments, explicit-path commits, verify before saying done, never publish).

## What the feature is
The user hums a melody, bass line or rhythm and says where it goes; Reflets plays one bar of count-in clicks, records the mic while the click goes on, turns the humming into notes on the click's grid and writes them into the open MuseScore score as a blue proposal (keep or discard). The design and decisions: `docs/spec-core.md` decision 47, the plan in `~/.claude/plans/about-your-90-target-async-waterfall.md`, accuracy in `research/hum-accuracy-2026-10-28.md`.

## State
- **Built, uncommitted** (the owner has not yet said to commit):
  - `reflets/hum.py`: transcription;
  - `reflets/audio.py`: the duplex click and record, the delay, take saving;
  - the `hum` tool in `reflets/server.py`;
  - the `hum` extra in `pyproject.toml`;
  - `tests/test_hum.py`, `tests/live_hum.py`, `tests/hum-session.md`, `eval/hum_takes.py`;
  - `eval/hum_eval.py --reflets`;
  - README, CLAUDE.md, the spec and the research report.
- **Accuracy on 440 HumTrans clips:** right pitch and note value 0.635 on the 16th grid and 0.695 on the 8th. This is no worse than Phase 1 (0.632 and 0.696).
  - Every clean-up rule must keep that true. Rules tuned only on the owner's takes were dropped: splitting repeated notes on loudness dips helped the takes but cost HumTrans up to 0.06.
- **The delay:** WSLg's driver says 40 ms, but the click's echo in the mic measures about 195 ms.
  - On speakers, each take measures its own delay from the echo.
  - On headphones, it uses a calibration stored per device: `hum(calibrate=True)`, the user says "ta" on 8 clicks.
- **Verified 2026-10-28:**
  - `uv run --extra hum pytest -q tests` passes.
  - `tests/live_hum.py` passed all checks in a live MuseScore: the 4 saved takes were written, read back exactly, given the key signature set from the humming, and discarded.
  - The server starts from Windows through `wsl.exe` and lists `hum`.

## Known problems, not fixed
1. **With nobody humming, `hum` writes a note made of room noise.** It should refuse with "no humming was heard". The proposed fix compares the level after the count-in with the room level during it. The owner has not yet answered whether to make it.
2. **Repeated notes merge.** Same-pitch notes hummed with no break stay one note (accepted; see above). Users are told to give each note its own push.
3. **Not built:**
   - the "listening" pill in MuseScore;
   - triplets;
   - free mode (no click);
   - humming along to the score's own parts;
   - native Windows Python (only WSL has been tried).

## Desktop setup
- **Claude Desktop config** (Settings > Developer > Edit Config, under `mcpServers`). Restart Desktop afterwards, and turn off any other Reflets server.

  ```json
  "reflets-dev": {
    "command": "wsl.exe",
    "args": ["--cd", "/home/kema/projects/reflets", "-e", "env", "REFLETS_HUM_SAVE=spikes/hum/takes",
             "/home/kema/.local/bin/uv", "run", "--extra", "hum", "reflets"]
  }
  ```

- **MuseScore:** open the score, then Plugins > Reflets Bridge. A blank flute test score, "Hum test" (8 bars, 4/4, tempo 90), is at `Documents/MuseScore4/Scores/reflets/hum-test.musicxml`.
- **Saved takes:** with `REFLETS_HUM_SAVE` set, every take is saved as a WAV plus JSON in `spikes/hum/takes/`. That folder is git-ignored: the takes are the owner's voice, so keep them out of git.

## The session
Follow `tests/hum-session.md`: 12 takes, from Twinkle on a blank flute score to calibration on headphones and keep. Rules for each take:
- **Ask the owner first, and only start a take when they say they are ready.** On 2026-10-28 a take started while they were not ready recorded only noise.
- Before calling `hum`, tell them: hum after the 4 count-in clicks, along with the click, giving each note its own push.
- Afterwards, they listen in MuseScore and say whether it came out right. Note which take (timestamp) was which tune, and whether it was right.
- Discard each take unless the step says keep.

## Afterwards, in Claude Code (WSL)
1. **Label each take.** Known tunes: `twinkle`, `ode`, `frere`, `mary`. A take that came out right: `right`.
   ```
   uv run --extra hum python -m eval.hum_takes --label <timestamp> <tune|right>
   ```
2. **Save the baseline:**
   ```
   uv run --extra hum python -m eval.hum_takes --save-baseline
   ```
   The current baseline, from the 3 old Twinkle takes, is 35 of 42 notes placed.
3. **For any change to `reflets/hum.py`,** run all three checks:
   - `uv run --extra hum python -m eval.hum_takes` (the owner's takes against the baseline);
   - `uv run --group hum-eval --extra hum python -m eval.hum_eval --key --reflets [--eighths]` (HumTrans, no worse than above);
   - `uv run --extra hum python tests/live_hum.py` (MuseScore open: replays every take of the score's meter).
4. **Report** what went wrong in the session, then fix it under the same "no worse on HumTrans" rule.

## Update 2026-10-29
- Known problem 1 was a misreading. Take `20261028-192934` is not room noise: it holds 16 confident notes on B2, the first note of the owner's Twinkle, so they hummed or spoke on it. Clicks and room noise alone give no notes (`tests/test_hum.py`), and `hum` then answers "No humming was heard". No fix was needed.
- `hum` now writes a tempo mark at the first hummed bar when the take's tempo is not the score's there.
- 2026-10-30: known problem 2 is mostly fixed: a tracked note is split where the owner gives a repeated note its own push (loudness dip then rise on a grid point). A one-beat silence now stays a rest, and a flat tonic no longer flips the key. See the last sections of `research/hum-accuracy-2026-10-28.md`.
- MuseScore makes ties with its own tie command, which fails ("tie not made") while the window shows its Home page or the screen is locked; live checks need the score showing.
