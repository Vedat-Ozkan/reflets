# Humming to notes: accuracy on HumTrans (2026-10-28)

Phase 1 of the hum plan: does an off-the-shelf pitch tracker turn humming into the right notes, before any device code is written? Reproduce with `uv run --group hum-eval python -m eval.hum_eval [--key] [--eighths] [--human]` at commit acd0fc6; after it, `--key` uses `reflets/hum.py`'s `find_key` and `in_key`.

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

## Rests and a flat tonic (2026-10-29, headphone takes)
- **Rests.** The owner sings Twinkle's, Frère Jacques' and Mary's long notes as a quarter and a quarter rest: in every take the note lasts 0.7 to 1.2 beats and the silence after it 0.9 to 1.3 beats, while the last note of Ode to Joy lasts 1.6 beats. A note was stretched over a following gap of up to a beat, which swallowed these rests ("Rests" above took them for short half notes). Now only gaps shorter than a beat are filled. The answer keys of `eval/hum_takes.py` follow the owner's singing. HumTrans scores note values by onset gaps, so it cannot see rests and is unchanged (0.639 / 0.709).
- **Key.** In take `20261029-231918` (headphones, calibrated) the tonic B was sung 60 cents flat against the rest of the tune (the fifth above it measured 7.6 semitones; 6.8 to 7.7 over the owner's Twinkle takes), so it rounded to Bb, G♭ major won, and the triad rule pulled the B's down to Bb. Each note now also counts toward its two neighbouring semitones by how close it is, and keys within 0.15 of the best match of that split profile join the candidates; the tie-break by sung time in the scale is unchanged. Using the split profile alone cost 0.001 to 0.003 on held-out clips, so it only adds candidates.

| Right note value | 16th grid | 8th grid |
|---|---|---|
| test, before / now | 0.639 / 0.639 | 0.709 / 0.709 |
| valid, before / now | 0.587 / 0.589 | 0.671 / 0.672 |
| train 3/4, before / now | 0.621 / 0.621 | 0.712 / 0.712 |

Owner's 11 labelled takes, scored against the new answer keys before and after both changes: 98 → 118 of 154 with the right length; take `20261029-231918` 10 → 14 of 14.

## Repeated notes: a push on a grid point (2026-10-30)
Of the owner's remaining errors, 7 were repeated notes merged into one, and in 5 of them the pitch tracker itself returned one note over both. The owner gives each note its own push: a dip in loudness, then a rise. On 1,000 train clips, at grid points where the hummer was sounding inside one labelled note (5,203), a dip of 6 dB then a rise of 8 dB within about 0.15 s occurs 2.7% of the time; at the onsets of same-pitch repeats (3,575) 84.5% of the time. The earlier attempt (Phase 2) also counted points after the hummer had stopped, where the next note's attack sits, and so cost 0.02 to 0.06. Now a tracked note is split at a grid point with such a push, if the point is at least 0.2 s and 0.6 of a step from either end of the note; without the 0.2 s the 16th grid lost 0.08, as its steps are shorter than the loudness windows. Tuned on train, checked on the rest. Right note value:

| Clips | 16th grid: before / now | 8th grid: before / now |
|---|---|---|
| train, 1,000 (tuned on) | 0.615 / 0.616 | 0.686 / 0.687 |
| valid, 374 | 0.589 / 0.589 | 0.672 / 0.673 |
| test, 440 | 0.639 / 0.639 | 0.709 / 0.708 |
| train in 3/4, 650 | 0.621 / 0.621 | 0.712 / 0.712 |

Owner's takes: 118 → 124 of 154 with the right length. The owner accepted the 0.001 loss on test's 8th grid (about 5 of 5,433 notes) against the gains elsewhere. Thresholds are rises and falls within the take, so they do not depend on microphone gain; a noisy room or a microphone with noise suppression fills the dips and falls back to merged repeats.

## Slides and drift splits (2026-10-30)
- **Slides.** A scoop folded into the next piece made that piece look longer, so its own slide test failed: in take 10 (`20261029-231702`) 55.0 slid into a 57.2 overshoot, then 56.2, and 57.2 was written. The slide test now uses each piece's own length. HumTrans is unchanged except test's 8th grid, 0.708 → 0.709; owner's takes 124 → 126.
- **Drift splits.** A held note whose pitch drifted 0.5 to 0.9 semitone was cut in two by the tracker; after `in_key` both halves have the same written pitch. On 1,000 train clips, of the touching same-pitch boundaries the pipeline keeps, 667 sit at a labelled onset (a real repeat; 4% of them without a push) and 273 do not (78% without a push). Touching pieces with the same written pitch and no push between them are now joined. Right note value, recall / precision:

| Clips | 16th grid: before → now | 8th grid: before → now |
|---|---|---|
| test, 440 | 0.639 / 0.631 → 0.645 / 0.645 | 0.709 / 0.711 → 0.713 / 0.721 |
| valid, 374 | 0.589 / 0.578 → 0.594 / 0.590 | 0.673 / 0.667 → 0.679 / 0.682 |
| train, 1,000 (measured on) | 0.616 / 0.607 → 0.621 / 0.619 | 0.687 / 0.686 → 0.692 / 0.698 |
| train in 3/4, 650 | 0.621 / 0.605 → 0.628 / 0.621 | 0.712 / 0.708 → 0.720 / 0.725 |

Owner's takes 126 → 127 of 154 with the right length, 20 → 17 extra notes; one take (`20261028-193247`) loses 2, a repeat sung without a measurable push.

## Same-slot notes and grids that don't fit the bar (2026-10-30)

- **Same-slot notes.** When two notes snapped to the same slot, the second was compared by its real duration against the first's rounded length, so a 0.30 s note could lose to a 0.16 s one. Both are now compared by real duration. Right note value, recall / precision: test 16th .646/.644 (unchanged), 8th .713/.721 → .713/.722; valid 16th .597/.590 (unchanged), 8th .680/.682 → .681/.683; train (1,000 clips) 16th .623/.618 (unchanged), 8th .693/.698 → .694/.699. The owner's takes are unchanged (127/154 right length, 17 extra).
- **Bars that are not a whole number of grid steps.** A 7/16 bar at grid=2 is 3.5 eighths; the bar's slots were cut to 3, so later bars started a sixteenth early and the last notes were dropped. `hum` now refuses such a meter before recording and suggests grid=4.
