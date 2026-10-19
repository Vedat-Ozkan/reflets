# Compressing N1 note text: back-references, repeat groups, relative octaves, an overview

Measured on 2026-10-18/19. Token counts: Anthropic `count_tokens` for `claude-opus-5-5`, minus the one-character baseline (9 tokens), as `encoding-tokens/count_tokens.py` does. Reading and writing tests: `claude-sonnet-5-5`; it rejects a non-default temperature (400), so temperature was not set; adaptive thinking, effort `medium` (first pass) and `high` (second pass); no server-side fallbacks, so every answer came from that model (`response.model` is logged). N1 comes from the engine at `../sheet-music-engine` (`verovio` → `engine.score.ScoreIndex` → `engine.notes.encode`), spelling unchanged (`Bb4`). Scripts, every variant text and the raw outputs are in `research/encoding-tokens/compression/`.

**Headline.** Measured: back-references save 32% of the tokens over all eleven scores (median 7% per score, 13% for scores over 2k tokens); repeat groups 8% (median 6%); relative octaves 16% (median 15%, very steady: 11–27% on every score); all three together 44% (median 28%, 34% over 2k tokens). Every lossless variant decodes back to the original N1 byte for byte on every score. Reading, at effort high: every variant scored 45–48 of 48 correct, against 45 and 47 for two runs of plain N1, so the differences are within noise. At effort medium, accuracy depended mainly on whether the model thought before answering. Relative octaves roughly doubled the thinking tokens, which outweighs their input saving on a single question set. Writing (24 rewrites of bars 1–8, counting only the rewrites where the feature had something to do): repeat groups were right 5 of 5 times, references 3 of 4, relative octaves 5 of 6, and all three together 3 of 6. Every misjudged octave was a fifth or a sixth treated as "within a fourth", and like the one wrong reference, it decoded silently to valid but wrong notes. Judged: put bar and voice back-references into N1x; leave relative octaves and repeat groups out for now.

## 1. Scores

| Score | File (`sheet-music-plugin/tests/data/`) | Bars | Notes | N1 tokens | Use |
|---|---|---|---|---|---|
| chopin-nocturne | `chopin_nocturne_op9_no2.mxl` | 38 | 1,253 | 6,030 | count, read, write |
| mozart-k545-1 (Alberti bass) | `mozart-k545-1-simulated-scan-reading.musicxml` | 73 | 1,283 | 6,131 | count, read, write |
| chopin-prelude-4 (repeated chords) | `chopin_prelude_op28_no4_reading.musicxml` | 25 | 598 | 2,572 | count, read, write |
| bach-bwv64-4 (4-voice chorale) | `part_writing_bwv64.4.musicxml` | 17 | 249 | 1,521 | count, read |
| brahms-fruehlingstrost (Lied) | `triplet_brahms_fruhlingstrost.musicxml` | 40 | 1,350 | 6,650 | count, read |
| haydn-104 (orchestral, piano score) | `piano/haydn-104.mxl` | 294 | 3,746 | 20,249 | count, read |
| dvorak-9-2 | `piano/dvorak-9-2.mxl` | 127 | 4,195 | 27,520 | count only |
| mozart-41 | `piano/mozart-41.mxl` | 433 | 16,893 | 103,017 | count only (too large to read cheaply) |
| mozart-k458 | `export-mozart-k458.musicxml` | 10 | 154 | 1,087 | count only (excerpt) |
| brahms-118-2 | `export-brahms-118-2.musicxml` | 8 | 110 | 655 | count only (excerpt) |
| debussy-clair | `export-debussy-clair.musicxml` | 2 | 24 | 191 | count only (excerpt) |

The three `export-*` files are short excerpts, so they say little about repetition. The k545 file is a simulated scan reading and its header has an empty `ts=`; `notes.decode` rejects that header, so every parser here accepts it.

## 2. The notations (as built in `codecs_n1.py`)

The header line is unchanged in every variant. Combined variants are encoded octaves → groups → references, and expanded in the reverse order: references, then groups, then octaves.

- **R, back-references.** `m9 = m1`: bar 9 has the same length as bar 1, no `ts=` change, and every voice line is identical. `2.1 = m1`: this voice line is identical to voice 2.1 of bar 1. A reference always points to the first bar where that content appears, and that bar is always written out in full, so there are no chains. A voice reference is used only when it is shorter than the line.
- **RT, with transposition.** `2.1 = m1 +M2`: voice 2.1 of bar 1 moved by a spelled interval (P/M/m/A/d, + up, − down), same rhythm, each pitch spelled by the interval (`engine.score.transpose`). The target must be written out in full. RT was measured only on plain N1, not combined with P or O.
- **P, repeat groups inside one voice line.** `(X)*n` is X written n times in a row; `X*n` repeats a single token. Durations carry on as if written out: the group repeats the text, not the notes. Example: `12 (C4 G4 E4 G4)*2`, `12 G3+B3+E4*7`. Groups are not nested and do not cross bar lines.
- **O, relative octaves.** In each voice line the first pitch has its octave. A later pitch may drop its digit, and then it takes the octave that puts it within three letter steps (a fourth) of its reference, accidentals ignored, so an augmented fourth is never ambiguous. The reference for a note, or for the first note of a chord, is the previous note, or the first note of the previous chord; grace notes count. The reference for a later note of a chord is that chord's first note. Every voice line starts afresh, so references and the bar-by-bar `propose` writes still work line by line. Example: `12 C4 E G C B4 G+B+D5 F` = `12 C4 E4 G4 C5 B4 G4+B4+D5 F4`. A variant, **Oc**, chains each chord note to the previous one, as LilyPond does. It was counted only.
- **V1/V2, overview (lossy).** Per bar, `top:` is the highest note attacked at each onset across all staves, skipped while a higher earlier note still sounds, written as an N1 voice. V1 adds `bass:`, the lowest note sounding at each beat start. V2 adds `beats:`, which gives per beat the bass with its octave plus the other pitch classes, e.g. `Eb2 G Bb | Eb3 Ab Cb D F G | …`. No chord names: a label would be an analysis, and could be wrong.

## 3. Tokens per idea

Tokens, with the % saved against N1 (`counts.tsv`). The total row is dominated by mozart-41.

| Score | N1 | R | RT | P | O | Oc |
|---|---|---|---|---|---|---|
| bach-bwv64-4 | 1,521 | 1,488 (2%) | 1,450 (5%) | 1,463 (4%) | 1,253 (18%) | 1,253 (18%) |
| brahms-118-2 | 655 | 655 (0%) | 655 (0%) | 653 (0%) | 581 (11%) | 580 (11%) |
| brahms-fruehlingstrost | 6,650 | 6,357 (4%) | 6,324 (5%) | 5,648 (15%) | 5,719 (14%) | 5,669 (15%) |
| chopin-nocturne | 6,030 | 4,507 (25%) | 4,507 (25%) | 5,642 (6%) | 5,111 (15%) | 4,943 (18%) |
| chopin-prelude-4 | 2,572 | 2,506 (3%) | 2,506 (3%) | 1,715 (33%) | 2,196 (15%) | 2,047 (20%) |
| debussy-clair | 191 | 191 (0%) | 191 (0%) | 191 (0%) | 170 (11%) | 170 (11%) |
| dvorak-9-2 | 27,520 | 24,025 (13%) | 23,775 (14%) | 24,701 (10%) | 22,994 (16%) | 22,992 (16%) |
| haydn-104 | 20,249 | 16,330 (19%) | 15,185 (25%) | 17,968 (11%) | 17,234 (15%) | 16,912 (16%) |
| mozart-41 | 103,017 | 55,937 (46%) | 50,058 (51%) | 96,436 (6%) | 86,889 (16%) | 86,884 (16%) |
| mozart-k458 | 1,087 | 930 (14%) | 930 (14%) | 1,057 (3%) | 944 (13%) | 944 (13%) |
| mozart-k545-1 | 6,131 | 5,704 (7%) | 4,918 (20%) | 5,492 (10%) | 4,497 (27%) | 4,469 (27%) |
| **total** | 175,623 | 118,630 (32%) | 110,499 (37%) | 160,966 (8%) | 147,588 (16%) | 146,863 (16%) |
| median per score | | 7% | 14% | 6% | 15% | 16% |
| total without mozart-41 | | 14% | 17% | 11% | 16% | 17% |

What each one used (`lossless.tsv`). The nocturne has 7 bar references and 6 voice references. Haydn has 48 and 48, and mozart-41 has 160 bar references and 764 voice references. Groups: 18 in the nocturne, 43 in the prelude, 1,889 in mozart-41. Octave digits dropped: 666 of the nocturne's pitches, 946 of k545's.

- **Relative octaves save more tokens than characters.** On k545 they cut 14% of the characters but 27% of the tokens. The octave digit is usually a token of its own, and the saving holds on every score (11–27%).
- **Back-references depend on the piece.** They save 46% on mozart-41, 25% on the nocturne (the reprise of the opening), and 0–4% on the chorale, the Lied and the excerpts.
- **Groups pay off on repeated chords and Alberti figures.** That is the prelude (33%) and Frühlingstrost (15%). Elsewhere they save 0–11%.
- **Transposed references (RT) add 0–13 points on top of R.** The most is on k545, at 13 points. Diagnostic (`figures.py`, not encoded): beats of three or more pitches that are an exact transposition of the previous beat in the same line are 0–3% of such beats on every score, against 0–21% that repeat it exactly. So a transposition notation inside a line is not worth having.

## 4. Combinations

| Score | N1 | RP | RO | PO | RPO |
|---|---|---|---|---|---|
| bach-bwv64-4 | 1,521 | 1,433 (6%) | 1,234 (19%) | 1,264 (17%) | 1,243 (18%) |
| brahms-118-2 | 655 | 653 (0%) | 581 (11%) | 581 (11%) | 581 (11%) |
| brahms-fruehlingstrost | 6,650 | 5,401 (19%) | 5,468 (18%) | 5,165 (22%) | 4,932 (26%) |
| chopin-nocturne | 6,030 | 4,226 (30%) | 3,820 (37%) | 4,885 (19%) | 3,646 (40%) |
| chopin-prelude-4 | 2,572 | 1,649 (36%) | 2,139 (17%) | 1,638 (36%) | 1,581 (39%) |
| debussy-clair | 191 | 191 (0%) | 170 (11%) | 170 (11%) | 170 (11%) |
| dvorak-9-2 | 27,520 | 21,836 (21%) | 20,412 (26%) | 22,038 (20%) | 19,712 (28%) |
| haydn-104 | 20,249 | 14,726 (27%) | 14,074 (30%) | 16,530 (18%) | 13,589 (33%) |
| mozart-41 | 103,017 | 52,879 (49%) | 47,943 (53%) | 86,934 (16%) | 47,935 (53%) |
| mozart-k458 | 1,087 | 900 (17%) | 806 (26%) | 940 (14%) | 802 (26%) |
| mozart-k545-1 | 6,131 | 5,179 (16%) | 4,231 (31%) | 4,253 (31%) | 4,016 (34%) |
| **total** | 175,623 | 109,073 (38%) | 100,878 (43%) | 144,398 (18%) | 98,207 (44%) |
| median per score | | 19% | 26% | 18% | 28% |

R and O are close to additive, because they act on different things: R removes whole lines, O removes digits inside lines. P adds little on top of O. Relative octaves make repeats harder to find, because the first copy of a figure keeps an absolute octave and later copies do not. On mozart-41, P alone found 1,889 groups; on top of O and R it found 171.

**Legend cost** (`legend_counts.tsv`, tokens). The N1 legend is 212 tokens. Adding R costs +56, P +48, O +183, RT +146 and RPO +311. That text sits in a tool description and is paid once per conversation; caching makes it cheaper still. R breaks even on the first repeated bar of a long piece. O breaks even at about 1,200 tokens of score, which is around eight bars of the nocturne.

## 5. Losslessness

Each compression has an exact inverse in `codecs_n1.py` (`decode`). `variants.py` first checks that the canonical renderer reproduces every N1 voice line byte for byte. This covers three N1 rules: a rest always has its duration written before it, even when it is unchanged; a gap is written before grace notes; and a grace note does not change the current duration. It then encodes and decodes every score under R, P, O, Oc, RP, RO, PO, RPO and RT. All 99 of those score × variant pairs decode to exactly the original N1 text (`lossless.tsv`). The overview is lossy by design and was not decoded.

## 6. Reading accuracy

Six scores (nocturne, k545, bwv64.4, prelude, Frühlingstrost, Haydn 104) and eight questions each (`reading.py`). The questions cover:

- the pitches attacked in a voice at a given offset;
- the lowest pitch sounding at the start of a bar;
- the highest pitch attacked in a bar;
- which bars are identical to bar Y, in every voice or in one voice;
- the number of attacks in one staff of a bar;
- the lowest and highest pitch of a voice over four bars;
- how often one pitch is attacked in a voice over two bars;
- the attacks of voice 1.1 in a bar, in order.

The script picks the bars itself and prefers material that a compression changes: referenced bars, lines with groups, and lines with octave digits dropped. Answers are computed from the N1 text with our own parser; per bar, its note count matches the engine index. Each prompt has the variant's legend, the questions, and the whole score, and asks for JSON with `null` allowed.

Grading: q5 (the prelude) and q7 (the nocturne) contained a tied-over note. "Attacked" can count it or not, so both counts are accepted. On every other question the two readings give the same answer. A single pitch returned as a one-item list was also accepted.

| Variant | Effort medium: correct / null / wrong | Effort high: correct / null / wrong | High: output tokens (all 6 scores) | High: cost per 6 scores |
|---|---|---|---|---|
| N1 | 39 / 1 / 8 | 45 / 0 / 3 | 5,170 | $0.15 |
| N1, second run | 41 / 1 / 6 | 47 / 0 / 1 | 4,975 | $0.14 |
| R | 39 / 1 / 8 | 46 / 0 / 2 | 6,229 | $0.15 |
| P | 36 / 7 / 5 | 47 / 0 / 1 | 6,382 | $0.15 |
| O | 46 / 0 / 2 | 48 / 0 / 0 | 11,354 | $0.20 |
| RP | 48 / 0 / 0 | 48 / 0 / 0 | 6,392 | $0.14 |
| RO | 43 / 0 / 5 | 47 / 0 / 1 | 10,698 | $0.18 |
| PO | 42 / 1 / 5 | 47 / 0 / 1 | 12,992 | $0.21 |
| RPO | 35 / 7 / 6 | 47 / 0 / 1 | 12,821 | $0.20 |
| RT | 43 / 2 / 3 | 47 / 0 / 1 | 6,159 | $0.14 |
| V1 (overview) | 12 / 33 / 3 | 13 / 35 / 0 | 2,993 | $0.09 |
| V2 (overview) | 13 / 32 / 3 | 12 / 36 / 0 | 6,401 | $0.13 |

Raw data: `reading/` (medium), `reading-high/`, `reading.tsv`, `reading-high.tsv`, and `*_summary.txt` with every wrong answer. The `grades` stored in each JSON file are from the first grading. `reading_summary.py` regrades with the rules above, and the tables use its output.

**Effort high.** No variant reads worse than N1. The two N1 runs alone differ by two answers, so nothing here ranks the variants. All the wrong answers at high are quoted here:

- **N1:** bwv64.4 q5 got 4 (truth 3); prelude q6 high got F#2 (B2); k545 q6 high got E4 (F4), in both runs.
- **R:** bwv64.4 q7 got 2 (truth 3); k545 q6 high got E4 (F4).
- **P:** k545 q6 high got E4 (F4).
- **RO and PO:** bwv64.4 q7 got 2 (truth 3).
- **RPO:** nocturne q3 got Eb5 (truth G5).
- **RT:** bwv64.4 q5 got 4 (truth 3).

**Effort medium.** Sonnet 5.5 sometimes answers without thinking (under 300 output tokens). That happened in 10 of 60 calls, and those calls got 40 of 80 answers right, against 372 of 400 when it thought. Which calls skipped thinking looks random (Frühlingstrost and Haydn under N1, P, R, RT, PO and RPO), so the medium column measures that more than the encoding. Two medium-effort error types do come from the notation:

- Under O, RO and RPO, the nocturne q6 "highest note of 2.1 in bars 31–34" got Ab4 instead of D5, three times, while N1 got it right. RO also gave k545 q6 a low of C3 instead of F#3. These are octave misreadings.
- RPO on the prelude answered 5 questions null and read `F#3+A3+E4` as `F3+Ab3+Eb4`, an accidental lost while expanding.

**Relative octaves make the model think about twice as long.** At high effort, every O variant used 2x the output tokens of N1 (10.7k–13.0k against 5.0–6.4k). Output costs five times input, so one question set over the whole score costs more with O ($0.18–0.21) than with N1 ($0.14–0.15), even though the input is smaller. The balance shifts back toward O when a score stays in context over many turns and questions are cheap.

**Overview.** It answered the bass question (q2) and the highest-note question (q3) correctly on all six scores at high effort, under both V1 and V2. For the inner voices, counts, ranges and voice 1.1 it said null every time, and at high effort it never invented an answer. It cannot find repeated bars: one correct answer in 12 at high; at medium it guessed wrongly twice, matching on similar top lines. None of the questions needed V2's pitch classes, so whether they help harmony questions is untested.

## 7. Writing (measured, small)

`write_test.py` gave Sonnet 5.5 (effort medium) the legend and bars 1–8 of three scores in N1, and asked for a rewrite in each form. It ran twice per score and form, 24 rewrites in all. The decoder then expanded each rewrite, and the result had to equal the N1 excerpt exactly (`writing.tsv`, `writing/*.json`). Using a feature less often than allowed is fine; only a wrong expansion fails. "Feature used" says which rewrites actually had something to compress: in bars 1–8 of k545 there was nothing to reference.

| Form | Exact | Feature used | Failures |
|---|---|---|---|
| R | 5 / 6 | 4 of 6 (k545 had no repeats in bars 1–8), so 3 / 4 where it applied | nocturne: `2.1 = m2` in bar 6, but bar 6's bass is C3, not C2. A near-identical line was referenced as identical, and it decoded silently to wrong notes. |
| P | 6 / 6 | 5 of 6 (k545 #2 wrote its one possible group out) | none. The prelude used all 15 possible groups both times. |
| O | 5 / 6 | 6 of 6 | nocturne: the first pitch of a line had no octave, carried over from the previous bar. The decoder rejected it, so this failure was loud. The same rewrite also had `F3+C` meant as F3+C4, a fifth. |
| RPO | 3 / 6 | octaves barely used on the prelude (0 and 1 of 52 digits dropped) | nocturne: `F3+C` (as above) and `B2 G+F4` meant as G3 (a sixth up). k545: `B3 G D G` meant as G4 D4 G4, and `F3+C` meant as C4. All decoded silently to wrong octaves. |

Every misjudged interval was a fifth or a sixth treated as "close". The carried-over octave was a different error, and it was caught. When rewriting everything at once, the model also left many digits in. That is allowed, but it suggests the model was unsure where the rule applies.

## 8. Cost

All Messages API calls were billed at Sonnet 5.5 rates, $2 / $10 per MTok. `count_tokens` is free.

| Run | Calls | Cost |
|---|---|---|
| Reading, effort medium (recorded) | 72 | $1.46 |
| Reading, medium: discarded attempts (estimated) | 12 | ~$0.25 |
| Reading, medium: retries inside kept records, not logged (estimated) | 11 | ~$0.15 |
| Reading, effort high | 72 | $1.87 |
| Writing test | 24 | $0.55 |
| **Total** | | **about $4.30** |

The discarded attempts happened because the first answer parser took everything between the first `{` and the last `}`, and the model sometimes adds notes after its JSON. Those four records were rerun after the fix. Before the fix, a record also logged only its last attempt, and 11 kept records had retried. Both estimates take each record's own token counts times its attempts.

## 9. Recommendation (judged, from the measurements above)

Claude has to read and write the same format, and `propose` writes bar by bar.

1. **Put bar and voice back-references into N1x.** Notation: `mN = mK` for a whole bar, `s.v = mK` for one voice, and the target is always the first bar written out in full. On long and repetitive pieces this is the biggest saving (25–50%). It costs 56 legend tokens and decodes trivially. It has the same failure mode as relative octaves: in one of four writing tests, a near-identical bar was referenced as identical and decoded to valid but wrong notes. The difference is that a reference error copies a whole line the model can see, and `propose` already writes the idea in colour and reads it back, so the user hears it. To catch it earlier, the server can refuse a reference whose target is outside the text that was read. One rule follows from the read path: a reference may only point inside the range returned by `read_score`, so a range read has to write out the first occurrence itself. Leave the transposed form (`+M2`) out: it adds 0–13 points, mostly on k545, and asks the model to transpose by spelled intervals in its head.
2. **Do not adopt relative octaves yet,** though they are the most reliable token saving (15–27% on every score, on top of R). The cost shows up elsewhere:
   - Writing errors cluster on exactly this rule: fifths and sixths read as "within a fourth". Each slip moves one note by an octave, and the result still decodes as valid notes, so the decoder cannot catch it. (Carrying the octave over from the previous bar was caught, because the decoder rejects a line that starts without one.)
   - At effort medium there were also octave misreadings that plain N1 did not have.
   - At effort high, reading stayed accurate but took twice the thinking tokens, which cancels the input saving for one-off questions.

   If tokens become the constraint, the safer form is one-way: `read_score` could emit relative octaves while `propose` keeps taking absolute octaves. Reading in that form was accurate at effort high, and only the thinking cost remains.
3. **Repeat groups `(X)*n`: optional, not the default.** Claude wrote them correctly every time it used them. But they save little outside repeated-chord and Alberti textures (median 6%), and on top of relative octaves they add little. A reasonable middle ground is to accept them in `propose` input without emitting them in `read_score`.
4. **Overview: worth having as a separate, cheap view.** By median, V1 is 45% of N1's tokens and V2 is 63%; over all scores they are 29% and 39%. It answered every top-line and bass question correctly. It answered null, never invented, for inner voices, counts and ranges, and it cannot detect repeated bars. Start with V1. V2's pitch classes per beat cost about 35% more tokens, and none of the questions here used them, so whether they help harmony questions is untested. On k545, where the top line includes the Alberti bass whenever the right hand rests, V1 still came to 78% of N1.

What was measured: token counts, losslessness, the reading answers and the writing round-trips. What was judged: the recommendation, the break-even sizes, and what an overview is good for beyond these questions. The samples are small: 48 questions per variant per pass, from six scores, and two writing samples per score and form. With differences of one or two answers, no variant ranks above another.

## Files (`research/encoding-tokens/compression/`)

| File | What it is |
|---|---|
| `build.py` | N1 for the eleven scores → `n1/` |
| `codecs_n1.py` | encoders and exact decoders for R, RT, P, O and Oc |
| `variants.py` | writes `variants/` and checks losslessness → `lossless.tsv` |
| `overview.py` | V1 and V2 → `variants/` |
| `figures.py` | the transposed-figure diagnostic → `figures.tsv` |
| `legends.py` | the legend for each variant |
| `count.py` | token counts → `counts.tsv`, `legend_counts.tsv` |
| `summarize.py` | the tables in sections 3 and 4 |
| `reading.py` and `reading_summary.py` | the reading test (run with `uv run --with anthropic --with verovio python reading.py run [high]`) |
| `write_test.py` | the writing test → `writing/`, `writing.tsv` |

The API key is read from the environment and is not stored anywhere.
