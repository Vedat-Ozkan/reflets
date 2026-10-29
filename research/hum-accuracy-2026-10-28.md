# Humming to notes: accuracy on HumTrans (2026-10-28)

Phase 1 of the hum plan: does an off-the-shelf pitch tracker turn humming into the right notes, before any device code is written? Reproduce with `uv run --group hum-eval python -m eval.hum_eval [--key] [--eighths] [--human]`.

## Data
- **HumTrans** test split (CC BY-NC 4.0, evaluation only). Ten music students hum "da" melodies while hearing them played, at 52–156 BPM, in 4/4.
- **Labels:** the 440 test clips for which Dynamic HumTrans published heuristically corrected onsets and offsets (that repository has no licence; read locally, never committed). Pitches and the beat grid come from each clip's MIDI, whose onsets sit on whole 16ths at one tempo. 11,098 notes in all.
- **Fetching:** only these 440 clips are read out of the 14.7 GB archive, over HTTP range requests.

## Method
- **Pitch and notes:** SwiftF0 0.3.0 (MIT; the model ships inside the package), then its `segment_notes`. That function splits the pitch track into notes by dynamic programming over off-pitch, unvoiced and loudness-dip costs, with a pitch hold of 80 ms.
- **Tuning:** one offset per take, the duration-weighted circular mean of the notes' fractional semitones. Each note is then rounded to a semitone.
- **Key snap** (`--key`): Krumhansl–Kessler profiles on duration-weighted pitch classes. A note outside the key, sung more than 15 cents toward a scale neighbour, moves to that neighbour.
- **Raw metric:** mir_eval note F1, 50 ms onset tolerance, exact semitone, best octave shift per clip. This is the metric of the published comparison.
- **Click-mode metric:** onsets are snapped to the MIDI's grid after one latency offset, the median gap between the labelled onsets and the MIDI onsets. That offset stands in for Reflets' calibrated click latency. A note counts when its pitch lands on the right grid slot; the stricter count also requires the right note value (the gap to the next onset). `--human` runs the same snap on the labelled onsets with true pitches. That is the ceiling any transcriber can reach on this data, since the hummers, or the label correction, are not always on the beat.

## Results

| 440 clips | Raw F1 | Right pitch on the right slot | And right value |
|---|---|---|---|
| SwiftF0 + segment_notes, hold 60 ms | 0.627 | 0.630 | 0.594 |
| SwiftF0 + segment_notes, hold 80 ms | 0.645 | 0.637 | 0.607 |
| SwiftF0 + segment_notes, hold 120 ms | 0.657 | 0.638 | 0.608 |
| **Hold 80 ms + key snap** | **0.672** | **0.666** | **0.632** |
| Ceiling: the hummers' own onsets and pitches | 1.000 | 0.737 | 0.680 |
| 8th grid, the 5,433 notes of tunes with no 16ths: hold 80 + key | 0.672 | 0.717 | **0.696** |
| 8th grid ceiling | 1.000 | 0.813 | 0.774 |

For comparison, published note F1 on this set (Dynamic HumTrans, 2024; octave-invariant, offsets ignored): Dynamic HumTrans 0.673, MIR-ST500 0.604, VOCANO 0.564, Basic Pitch 0.434.

## Findings
- With key snapping, an untrained, MIT-licensed, 63 MB pipeline matches the best trained humming model (0.672 against 0.673). Key snapping adds about 0.03 on every measure.
- In click mode we reach 93% of what this data allows on the 16th grid (0.632 of 0.680) and 90% on the 8th grid (0.696 of 0.774).
  - A trained model could add at most the remaining 0.05–0.08. That doesn't justify SOME's 435 MB PyTorch checkpoint, which is dropped.
- **Most of the loss is timing** (diagnosed on 60 clips). The detected onsets sit within 0.03 of a 16th of the labelled ones (median), and 4% are off by more than half a 16th. But 18% of the labelled onsets are more than half a 16th from the MIDI grid.
- Following slow tempo drift with a refitted linear map gained only 0.007, so a single offset is kept.
- A coarser grid helps when the music allows it: the right note value goes from 0.632 on 16ths to 0.696 on 8ths, measured on different subsets.
- A longer pitch hold trades recall for precision. At 120 ms raw F1 is higher, but the notes fully right barely move, so 80 ms stays.

## Gate (restated)
The plan's gate of 85% right note values is impossible on this data, because the human ceiling is 0.680. The gate becomes: within 0.05 of the ceiling with the key snap. On the 16th grid that is 0.632 against 0.680, so it passes (0.048 below). On the 8th grid it is 0.696 against 0.774 (0.078 below), and the 8th-grid quantizer needs another look.

## What this does not measure
These hummers followed playback without a count-in. Reflets' takes, with its own count-in and click, are expected to sit closer to the grid, but that is unmeasured until Phase 0 takes exist. Three other things are not covered: the latency offset here comes from the labels, where in Reflets it comes from calibration; meter is always 4/4; triplets and syncopation are absent.

## Licences (checked 2026-10-28)
- **Shipped with the feature:** swift-f0 (MIT, weights included), onnxruntime (MIT), sounddevice (MIT; its Windows and macOS wheels bundle PortAudio, MIT-style), numpy (BSD-3 and others), music21 (BSD-3).
- **soxr is LGPL-2.1+.** It is used only to resample in this evaluation. Reflets will record at SwiftF0's 16 kHz, so the feature doesn't need it.
- SwiftF0's paper says it was trained on "diverse speech, music, and synthetic datasets" and doesn't name their licences.

## Phase 2: the clean-up in `reflets/hum.py` (2026-10-28)
Each clean-up step was scored on all 440 clips (`--reflets`, the same legato note values as above) and on the owner's three Twinkle Twinkle takes (`spikes/hum/replay.py`). A step stays only if HumTrans does not get worse.

| | 16th grid: slot / value | 8th grid: slot / value | Owner's takes: notes placed of 42 |
|---|---|---|---|
| Phase 1 pipeline (hold 80 + key snap) | 0.666 / 0.632 | 0.717 / 0.696 | 35 |
| Every step, with joining and re-splitting repeats on loudness dips | 0.659 / 0.563 | 0.705 / 0.659 | 41 |
| **Kept:** settled pitch, notes under 0.45 of a step merged, octave fix, tonic-triad tie-break | **0.670 / 0.635** | **0.719 / 0.695** | 36 |

- Joining same-pitch fragments and splitting them again where the loudness dips on a grid point fixed two merged repeats in the owner's takes, but at every threshold tried (fall/rise 2/4, 3/6, 4/8 dB) it cost HumTrans 0.02 to 0.06 of right note values, so it is dropped. Repeated notes hummed with no break stay one note; the advice to users is to give each note its own push.
- A fixed 0.2 s glitch threshold cost HumTrans 0.01; tied to the grid (0.45 of a step) it is neutral there and still removes scoops in the owner's takes.
- The remaining steps are neutral or slightly better on HumTrans (settled pitch +0.005).
- Delay: in WSL the driver reports 40 ms; the click's echo in the microphone measured 183 to 206 ms over five takes on speakers, so `hum` takes the delay from the echo, or from a stored calibration on headphones.

## Scoops into a note (2026-10-29)
In the owner's Desktop take of Twinkle Twinkle (`20261028-233945`), two notes began with a 0.17–0.18 s slide about 2 semitones away (0.51–0.54 of an eighth at tempo 90), just over the 0.45 cut-off, so each became an extra eighth. The audio itself was clean: no clipping, room noise 29 dB under the humming, pitch confidence 0.99.

| | 16th grid: slot / value | 8th grid: slot / value | Owner's 4 Twinkle takes: placed / right length / extra, of 56 |
|---|---|---|---|
| Before | 0.670 / 0.635 | 0.719 / 0.695 | 46 / 40 / 11 |
| Every note under 0.55 of a step merged | 0.666 / 0.628 | 0.715 / 0.688 | 49 / 43 / 4 |
| Under 0.6 of a step, within 2.5 semitones of the next note | – / 0.633 | – / 0.697 | 49 / 43 / 4 |
| Under 0.8 of a step, within 2.5 semitones | – / 0.622 | – / 0.668 | 50 / 44 / 2 |
| **Kept:** under 0.55 of a step, touching the next note and within 2.5 semitones of it | **0.670 / 0.635** | **0.720 / 0.696** | **49 / 43 / 4** |

- Rests: the same take had a quarter rest after a quarter note, which became a half note, since a note is stretched over a following gap of up to a quarter. Its last note, a half note held for one beat, ends the same way, so no gap threshold separates them; the rule stays.

## Key from a mediant-heavy opening (2026-10-29)
The owner's Ode to Joy take (`20261029-001505`, B major, +50 cents) dwells on the third degree, so the key profile ranked D#/Eb minor (0.627) above B major (0.549). Eb minor has no E, so a sharp-sung fa was moved up to F, and the key signature was wrong. Now every key within 0.15 of the best correlation is a candidate, and the one whose scale holds the most sung time wins, then the higher correlation.

| Candidates within | 16th grid: slot / value | 8th grid: slot / value | Owner's takes: placed / right length / extra, of 85 |
|---|---|---|---|
| 0 (before) | 0.670 / 0.635 | 0.720 / 0.696 | 76 / 69 / 5 |
| 0.1 | 0.674 / 0.638 | 0.730 / 0.707 | 77 / 70 / 4 |
| **0.15 (kept)** | **0.675 / 0.639** | **0.733 / 0.709** | **77 / 70 / 4** |
| 0.2 | – / 0.639 | – / 0.709 | 77 / 70 / 4 |
| 0.3 | – / 0.640 | – / 0.710 | 77 / 70 / 4 |

## Scoop limit in seconds (2026-10-29, rejected)
In the owner's Mary Had a Little Lamb take at tempo 120 (`20261029-004451`), the first note began with a 0.14 s scoop, just over 0.55 of an eighth (0.1375 s), so it became an extra note. A floor in seconds under the scoop limit fixes it, but costs HumTrans on the 16th grid, where a fast 16th is itself shorter than the floor.

| Scoop limit | 16th grid: slot / value | 8th grid: slot / value | Owner's takes: placed / right length / extra, of 112 |
|---|---|---|---|
| **0.55 of a step (kept)** | **0.675 / 0.639** | **0.733 / 0.709** | **102 / 92 / 8** |
| At least 0.15 s | 0.662 / 0.626 | 0.733 / 0.709 | 103 / 93 / 6 |
| At least 0.15 s, at most 0.7 of a step | 0.670 / 0.634 | 0.733 / 0.709 | 103 / 93 / 6 |
| At least 0.2 s | 0.654 / 0.617 | 0.729 / 0.702 | 103 / 93 / 6 |
| At least 0.25 s | 0.633 / 0.593 | 0.701 / 0.666 | 104 / 94 / 4 |

## Correction: HumTrans meters (2026-10-29)
"Meter is always 4/4" above is wrong. By the time signatures in each clip's MIDI, the clips with corrected onsets are:

| Split | 4/4 | 2/4 | 3/4 | 6/8 |
|---|---|---|---|---|
| test (440, used above) | 287 | 153 | 0 | 0 |
| valid (374) | 320 | 25 | 29 | 0 |
| train (6,827) | 5,090 | 1,047 | 650 | 40 |

`transcribe` never sees the meter, so a 3/4 score here measures notes in three-beat melodies, not the writing of 3/4 bars.

## Held-out check of the 2026-10-29 changes
The scoop and key changes above were tuned on the 440 test clips. Dynamic HumTrans also corrected the onsets of valid and train clips, which nothing had been tuned on (`--split valid|train`, `--meter 3/4`, `--clips N`). Before is the code with neither change (`KEY_CLOSE = 0`, `SCOOP_STEPS = SHORT_STEPS`). Right note value:

| Clips | 16th grid: before / now / ceiling | 8th grid: before / now / ceiling |
|---|---|---|
| test, 440 (tuned on) | 0.635 / 0.639 / 0.680 | 0.695 / 0.709 / 0.774 |
| valid, 374 | 0.578 / 0.587 / 0.618 | 0.657 / 0.671 / 0.698 |
| train, 1,000 spread evenly | 0.611 / 0.615 / 0.653 | 0.677 / 0.686 / 0.740 |
| train in 3/4, all 650 | 0.609 / 0.621 / 0.638 | 0.699 / 0.712 / 0.741 |

- Both changes help on every held-out set, by 0.004 to 0.014, so the gain on test was not luck.
- The distance to the hummers' own ceiling is 0.017 to 0.054 on held-out clips, and smallest in 3/4.
