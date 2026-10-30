# Humming session in Claude Desktop

A test session for `hum` through Claude Desktop, MuseScore and the microphone. Every take is saved to `spikes/hum/takes/` (git-ignored) and becomes a test: `eval/hum_takes.py` scores it offline, `tests/live_hum.py` writes it into MuseScore again.

## Setup, once

1. Claude Desktop: Settings > Developer > Edit Config, and add this server under `mcpServers` (the server runs in WSL, from this working copy, and saves every take):

   ```json
   "reflets-dev": {
     "command": "wsl.exe",
     "args": ["--cd", "/home/kema/projects/reflets", "-e", "env", "REFLETS_HUM_SAVE=spikes/hum/takes",
              "/home/kema/.local/bin/uv", "run", "--extra", "hum", "reflets"]
   }
   ```

   Restart Claude Desktop. If Reflets is installed there from GitHub too, turn that one off for the session, so Claude uses this one.
2. MuseScore: open a score and run Plugins > Reflets Bridge.
3. Speakers on, unless a step says headphones.

## Takes

For each step, tell Claude what you will hum, hum after the count-in, then listen in MuseScore and note the take's result as right or wrong. Discard each idea unless the step says keep.

| # | Score | Ask Claude | Expected |
|---|---|---|---|
| 1 | New blank score, flute, 4/4 | "Let me hum Twinkle Twinkle into the flute from bar 1" | Key signature set to the key you hummed; notes around the middle of the treble staff |
| 2 | Same | Ode to Joy, bars 1-4 | Dotted quarter and eighth in bar 4 |
| 3 | Same | Frère Jacques, plain humming ("mmm") | Repeated notes hummed with a push come out separate |
| 4 | Same | Mary Had a Little Lamb, 4 bars, at tempo 120 | Same notes at the faster tempo |
| 5 | Same | Twinkle again into bar 1, without saying replace | Claude asks before you hum, and nothing is recorded until you agree |
| 6 | New score, cello, 4/4 | A bass line of your own, 4 bars | Notes in the cello's register (bass clef); say whether it is what you hummed |
| 7 | A score with notes in another key (e.g. `tests/data/bwv66.6.musicxml`, add a staff or use bars past the end) | Twinkle past the last bar | Moved into the score's key; bars appended, removed again on discard |
| 8 | New score, 3/4 | A waltz tune of your own, 4 bars | Bars of three beats |
| 9 | Blank flute score | "Hum just a rhythm" (kind rhythm), 4 bars | One pitch, your rhythm |
| 10 | Blank flute score, headphones on | Twinkle without calibrating | Claude says the delay is uncalibrated; the notes may land late |
| 11 | Same, headphones | "Calibrate humming", then Twinkle again | Calibration reports a delay; the notes land on the beats |
| 12 | Blank flute score | Any take, then keep it | Notes turn black |

## Afterwards

Tell Claude Code which take was which and whether each was right. Takes of known tunes are labelled by name, takes that came out right as `right`:

```
uv run --extra hum python -m eval.hum_takes --label <take> twinkle
uv run --extra hum python -m eval.hum_takes --save-baseline
```

From then on, `uv run --extra hum python -m eval.hum_takes` shows each take against the baseline, and `uv run --extra hum python tests/live_hum.py` writes every take of the open score's meter into MuseScore again.

## Without humming (2026-10-29)

Takes 5, 6, 7 and 9 replay the saved takes instead of the microphone, with `tests/data/bwv66.6.musicxml` open (as an import) and the bridge running:

```
uv run --extra hum python tests/live_hum.py --staff 1
uv run --extra hum python tests/live_hum.py --staff 4
uv run --extra hum python tests/live_hum.py --staff 1 --rhythm
```

The first checks take 5 (refused before recording, as the staff has notes) and take 7 (moved into the chorale's key, bars appended and removed); the second take 6 (the bass register); the third take 9. Accuracy in 3/4 (take 8) is measured on HumTrans: `python -m eval.hum_eval --key --reflets --split train --meter 3/4`. Takes 10 and 11 still need headphones and the owner; take 12 is `keep`, covered by `tests/live_proposals.py`.

Take `20261029-231528` (headphones, started an eighth late) is kept on purpose: its scoops land on beats as extra notes, so on a score that has notes, such as `bwv66.6`, its "in the score's key" check fails. That failure is expected, not a regression.
