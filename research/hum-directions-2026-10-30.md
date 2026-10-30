# Humming: where the remaining accuracy is, and what could reach it (2026-10-30)

The owner asked what it would take to get humming close to speech recognition, and asked for research on four ideas: onboarding a user with a few short styles (E), decoding with a melody prior (A), confidence and alternatives (C), and a trained note model (D), plus whether annotated data exists beyond HumTrans. Using the score's own harmony was dropped because a blank score gains nothing from it. Numbers are `--key --reflets` on the frozen reference (`research/hum-accuracy-2026-10-28.md`), code at b536c16, recall / precision unless marked.

## Where today's misses are

Every reference note of the 421 test clips on the 16th grid, by what the tool wrote at its slot (`eval.hum_eval` scoring, any transposition):

| Outcome | Notes | Share |
|---|---|---|
| right pitch, slot and written length (a last note the audio cuts off on its slot only) | 8,384 | .789 |
| a note at the slot one semitone off | 593 | .056 |
| right pitch and slot, length off by more than one step | 549 | .052 |
| a note one step early or late at the right pitch | 471 | .044 |
| right pitch and slot, length off by one step | 282 | .027 |
| no note near | 189 | .018 |
| a note at the slot two semitones or an octave off | 127 | .012 |
| any other pitch at the slot | 29 | .003 |
| extra notes (not part of the shares) | 1,519 | |

About 18 of the 21 missing points are a choice between candidates the audio already offers: a written length, the neighbouring semitone, the neighbouring slot. About 3 points have no candidate. That is the ceiling of any decoder that picks among acoustic candidates, before a trained model is needed.

Threshold tuning has reached its end. Of the key clean-up's two rules, moving fewer notes onto the tonic triad (`TRIAD_LEAN` 0.4) gained .002 to .004 on every HumTrans set but cost two notes of the owner's take `20261029-231918`, so it stays at 0.3. Moving every leaning out-of-key note into the key (`SCALE_LEAN` 0) scored best of all on train (.775 / .766 and .833 / .833) by never writing a chromatic note:

| Test clips, notes on the right slot | In the key the tool found (10,420) | Chromatic (204) |
|---|---|---|
| no key clean-up | .816 | .618 |
| today (`SCALE_LEAN` 0.15) | .878 | .324 |
| `SCALE_LEAN` 0, `TRIAD_LEAN` 0.4 | .891 | .000 |

Chromatic here means outside the key the tool found, so some of the 204 may be clips whose key it got wrong. HumTrans is 98% diatonic, so it rewards a hard snap that a user writing chromatic music would find wrong every time; today's clean-up already loses half of those notes. Any later change is also scored on this split, and on HumTrans alone a gain that comes from the chromatic column is a loss.

For comparison with the published numbers: raw note F1 against Dynamic HumTrans's corrected onsets (50 ms, octave-invariant) is .687 on 421 test clips for SwiftF0's own note splitter with the key clean-up, without the click (`hummed` in `eval/hum_eval.py`, not the click pipeline), and the clips are not exactly theirs; their own CNN trained on humming reports .673 on the test clips they kept, and off-the-shelf singing models .43 to .60 (Basic Pitch .434, VOCANO .564, the MIR-ST500 model .604; arXiv 2410.05455).

## Data beyond HumTrans

No large set has humming labelled with what was hummed. What exists:

| Set | Labels | Size | Licence | Use |
|---|---|---|---|---|
| Vocadito | notes as sung, two annotators each | 40 sung excerpts, 28–29 singers | CC BY 4.0 | eval, human ceiling; training allowed |
| Molina et al. 2014 | notes as sung | 38 clips, children and untrained adults | CC BY-NC-ND 4.0 | local eval only |
| MTG-QBH | none (queries only) | 118 sung queries | CC BY 4.0 | audio to pseudo-label |
| Children's Song Dataset | score notes hand-aligned to the audio | 200 recordings, one singer | CC BY-NC-SA 4.0 | local eval |
| HumTrans | the score MIDI the hummer heard | 56 h, 10 music students | CC BY-NC 4.0 | local eval; weights risky |
| MIR-ST500, M4Singer, GTSinger, Opencpop, TONAS, Lyra-QBH | sung or score notes, pop with accompaniment or professionals | large | NC, ND, no licence, or YouTube links | not for weights we ship |

Every large labelled set is non-commercial or forbids changes, so weights trained on them could not ship in an open-source tool without the authors' permission. HumTrans's melodies come from about 5,000 pieces of public sheet music with no named corpus, so a melody prior trained on public MIDI has to be checked against its 1,000 MIDI segments.

The only human ceiling found is Vocadito's: one annotator against the other gives note F1 .74 without offsets and .64 with them (range .34 to .88; arXiv 2110.05580). That is free singing with lyrics and no click, so it says only that annotators disagree mostly on short notes and ornaments; it does not bound click-mode grid scores.

## E: onboarding to fit the singer

Simulated on HumTrans, which names each hummer: each of 9 hummers (M03 has 16 clips) had their settings tuned on their own train clips (`SHORT_STEPS`, `SCOOP_STEPS`, `SCALE_LEAN`, `TRIAD_LEAN`, and rests by the singer's gaps at margins of one or two steps), and the best pick was scored on their own test clips (16th grid, written length):

| Hummer | Pick on train | Test, today → pick |
|---|---|---|
| F01, F04 | `TRIAD_LEAN` 0.4 | +.001 / +.001 |
| F02 | `SCOOP_STEPS` 0.4 | .833 / .852 → .833 / .849 |
| F03 | rests at one step | .843 / .832 → .848 / .837 |
| F05 | `TRIAD_LEAN` 0.4 | .808 / .805 → .811 / .808 |
| M02 | `SCOOP_STEPS` 0.7 | .656 / .635 → .656 / .641 |
| M04 | `SCOOP_STEPS` 0.7 | .767 / .760 → .766 / .763 |
| M01, M05 | today's | |

Rests by the singer's gaps helped only F03 on train (+.003); for every other hummer they lost there too, so the failed global rule is not a habit some singers have. The picks gain at most .005, and about .002 on average.

So tuning the clean-up per singer pays little on these ten music students. Elsewhere, the closest precedent (Microsoft Research, AAAI 2010: a calibration of melodies with known pitch and rhythm, then a per-user pitch predictor) cut pitch errors 20–30% for an average singer against a commercial baseline; speech recognition's few-shot adaptation gains are a few percent and overfit unless only a few parameters move. Products ask for little: a vocal range (Yousician, Dubler), a microphone check, or nothing (Hum to Search).

What onboarding can carry: what Reflets already calibrates (the device delay), the singer's range and octave, their tuning offset, and a syllable that gives clean onsets ("da" rather than "mm"). Three short styles on the click, each 8 to 15 seconds after the target is played: detached quarter notes on "da" up and down a five-note scale (delay, tuning, range); legato steps and leaps in eighths on "mm" (slides, octave handling); repeated notes and sixteenths with rests and one syncopation (repeated-note splits, note lengths). Its value would be checked on the owner and other real users, which HumTrans cannot do: it has no singers who are not musicians and no device spread.

## A: decoding with a melody prior

What the literature measured:

- Against plain rounding and per-slot voting, which is close to today's rules, priors gained a lot: frame error 20% → 13% on sung, hummed and whistled folk tunes with note bigrams from 5,983 Essen tunes and a key model (Viitaniemi, Klapuri and Eronen 2003); note accuracy 54.0% → 73.5% with a hidden semi-Markov model of key, pitch and onset decoded on known beat times, close to Reflets's click (Nishikimi et al., TASLP 2020), where most of the gain was in onsets and offsets.
- Against a tuned hidden Markov model the gains are small and need a gate: a fixed-weight language model scored piano note F1 63.0 against the HMM's 69.1, recall falling 66.4 → 55.7, and only a learned gate on both models' uncertainty gained (71.7; Ycart et al., ISMIR 2019).
- Priors rewrite unusual music: a wrong key dropped recall 63 → 37 (Ryynänen and Klapuri 2006), and Nishikimi's prior added missing notes. The mitigations are a mild out-of-key penalty (Nishikimi used 10:1 "because non-diatonic notes are often used"), gating on acoustic confidence, and never a hard snap. No paper evaluated chromatic or modal material separately.

The design that fits: one decoder on the click's grid (with triplet positions) over states pitch × {onset, held, rest}, emissions from SwiftF0's pitch and loudness at each grid point, and a prior of note lengths by metrical position and a mild key-relative interval table, counted from freely usable melodies (Lakh MIDI CC BY 4.0, POP909 MIT; deduplicated against HumTrans). It would replace `absorb_short`, `split_pushes`, `in_key`, `fix_octaves`, `join_unpushed` and `snap` with one model whose few weights are tuned on train and checked on valid, test, the chromatic split and the owner's takes. Its ceiling is the 18 points above. A cheaper first step is rescoring: generate the current output's neighbours (split, merge, ±1 semitone, ±1 step, length ±1) and accept one only when its acoustic margin is small.

## C: confidence and alternatives

Confidence highlighting has a weak record: in a 36-person study, flags on likely speech-recognition errors neither sped up correction nor felt helpful (arXiv 2503.15124), and Melodyne shows the alternatives it considered without asking. A design that would not penalise unusual music scores each decision from the acoustics only: a pitch's distance to the semitone boundary in units of its own spread within the note, an onset's or end's distance to the boundary between the two best grid positions in units of the singer's timing spread against the click, and whether the written result changes when the delay moves 15 ms or the tuning 15 cents. Mapped to a chance of being wrong (logistic fit on held-out clips), checked with a reliability diagram and risk–coverage curve, and with equal false-flag rates on correct diatonic and chromatic notes. Claude would ask about at most one spot per phrase, above a threshold set for most flags being real errors. A decoder from A gives the second-best reading at each spot for free, so C is best built after A.

## D: a trained note model

Off-the-shelf singing models transfer poorly to humming (.43 to .60 raw F1 above, against today's .687) and lose about 30 points of onset, pitch and offset F1 out of domain even when strong in domain (ROSVOT: 77.4 → 47.4 on MIR-ST500). What they mainly learn, finding onsets with no time reference, the click already gives. Training our own would need in-domain data that can ship: synthesised humming rendered from free melodies with scoops, vibrato, drift, room noise and timing jitter (a model trained only on synthesised singing reached 74% note F1 on real amateur singing; Schwabe et al., JAES 2022), then pseudo-labels from real takes the rules handle. That is weeks of work, and worth it only if A plateaus well below its ceiling.

## Recommendation

1. A, as the tatum-grid decoder, measured on the 18 points it can reach, the chromatic split and the owner's takes; the rescoring step first if a smaller change is wanted.
2. Add Vocadito (CC BY) and Molina 2014 (local only) to the eval, as sets labelled with what was sung.
3. C on top of A's second-best readings.
4. E as onboarding for range, tuning, syllable and delay, tried on real users rather than tuned on HumTrans.
5. D only if A plateaus, on synthesised humming; training on HumTrans or other non-commercial sets needs the owner's decision first.
