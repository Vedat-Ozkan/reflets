# Score encodings for the model: token counts, and an N1 extension

Measured on 2026-10-14/15 against `sheet-music-analysis` at commit `02c13ec`, file `tests/data/chopin_nocturne_op9_no2.mxl` (Chopin, Op. 9 No. 2: 38 bars including the pickup, 1,253 notes, 2 staves, one part). Token counts come from the Anthropic `count_tokens` API for `claude-fable-5-1`. Scripts, the encodings and the raw counts are in `research/encoding-tokens/`; the plugin repo is expected next to this one (or at `$SHEET_MUSIC_REPO`).

**Headline.** N1 is 6,030 tokens for the whole nocturne, about one token per character, not the 1.7k the plan estimated from characters ÷ 3.5. The ratios still hold in N1's favour but are smaller in tokens than in characters: minified JSON per note is 7.4x N1 (9.8x by characters), uncompressed MusicXML 33x (88x). The cost sits in pitch spelling: a natural such as `G5` is 2 tokens, a flat such as `Bb4` is 4, so respelling flats (`B-4`) saves 10% and key-relative spelling 17%; MIDI numbers would save 40% but drop the spelling the harmony model needs. The extension with rests, part names, dynamics and chord symbols adds 4–26% depending on what is on the page.

## 1. The three base encodings

| Encoding | File | Tokens | Characters | Chars per token | Relative to N1 (tokens) |
|---|---|---|---|---|---|
| MusicXML, uncompressed (what is inside the .mxl) | `chopin.musicxml` (regenerate with `build_base.py`) | 196,221 | 509,478 | 2.60 | 32.5x |
| MEI from Verovio (reference only) | `chopin.mei` (regenerate) | 101,503 | 263,769 | 2.60 | 16.8x |
| JSON per note, verbose (indent 2, same keys) | `chopin.notes.verbose.json` (regenerate) | 71,140 | 130,744 | 1.84 | 11.8x |
| JSON per note, minified, short keys | `chopin.notes.min.json` | 44,339 | 56,879 | 1.28 | 7.4x |
| N1 (`engine/notes.py`, `encode(index)`) | `chopin.n1.txt` | 6,030 | 5,797 | 0.96 | 1x |

The minified JSON carries exactly what N1 carries, so the comparison is fair: `{"div":48,"ts":"12/8","ks":"3f","measures":[{"n":0,"len":24},…],"notes":[{"m":1,"s":1,"v":1,"o":0,"d":72,"p":"G5","t":1},…]}`, one object per note with measure, staff, voice, onset and duration in `div` units, sounding pitch, and `g`/`t` flags for grace and tie. The character counts agree with the plan of 2026-10-14 (5,796 and 58,745 there).

What this means for the companion: a 38-bar piano piece is 6k tokens, so a chat turn that carries a whole movement of 150 bars is around 25k tokens of score, which fits a context window comfortably but is not free to resend every turn. Bar ranges (`encode(index, first, last)`) stay the right default for conversation, and the full score should be cached as a stable prefix when it is sent at all.

## 2. Where the tokens go

Per-item costs, each measured as a line repeated 40 times (the line break is excluded):

| Text | Tokens | Note |
|---|---|---|
| `G5` | 2 | letter, octave |
| `Bb4`, `Eb4`, `Cb4` | 4 | the accidental costs two |
| `B-4` (music21 spelling) | 3 | |
| `bb4` | 3 | |
| `B4` | 2 | |
| `24`, `72`, `288` | 1 | durations are cheap |
| `G5~` | 3 | tie adds one |
| `gE5` | 3 | grace prefix adds one |
| `r` | 1 | |
| `Bb3+Eb4+G4` | 12 | three flats; `Bb3 Eb4 G4` and `Bb3.Eb4.G4` cost the same, so the `+` is free |
| `2.1:` | 4 | voice label |
| `m12 len=288` | 6 | measure header |
| `d1: 0 p 144 < 288 !` | 15 | dynamics line with three marks |
| `[p]G5~` | 6 | inline mark adds three to the note |
| `h: 0 Eb 144 Bb7` | 15 | chord line with two symbols |
| left-hand line of bar 1, N1 spelling | 108 | 94 characters |
| same line in MIDI numbers | 54 | 79 characters |

Separators do not matter; the accidentals do. In Eb major most bass notes carry a flat, so the nocturne is an expensive case for N1 and a C-major piece would be noticeably cheaper per note.

Whole-piece respellings of the same N1 text (`respell.tsv`):

| Spelling | Tokens | Saving | Example (bar 1, right hand) |
|---|---|---|---|
| N1 as is | 6,030 | | `72 G5~ 24 G5 F5 G5 72 F5 48 Eb5 24 Bb4` |
| Flats as `-`, music21 style | 5,439 | 10% | `… 48 E-5 24 B-4` |
| Key-relative: a letter in the key signature carries its flat, `n` marks a natural | 4,998 | 17% | `… 48 E5 24 B4` |
| MIDI numbers, spelling dropped | 3,586 | 41% | `… 48 75 24 70` |

Key-relative spelling is how a player reads the page and keeps every spelling recoverable from `ks=`, but it moves the burden of applying the key signature to the model and to every decoder, and key changes mid-piece (which N1 does not carry yet) would have to be written. The `-` spelling is a free 10% with no semantic change and is already what music21 prints; `normalise_pitch` in `engine/score.py` accepts it on the way in. MIDI numbers are the floor and not an option for a harmony reader that needs Cb against B.

## 3. Counting tokens

`research/encoding-tokens/count_tokens.py` calls `client.messages.count_tokens(model="claude-fable-5-1", messages=[{"role": "user", "content": text}])` once per file, subtracts the fixed per-request overhead (measured with a one-character message, 9 tokens), and prints tokens, characters and characters per token. It reads the key from `ANTHROPIC_API_KEY` or the environment secret `Anth_Key`:

```sh
cd research/encoding-tokens
python build_base.py out            # writes chopin.musicxml, chopin.mei, chopin.notes.*.json, chopin.n1.txt
python count_tokens.py out/chopin.musicxml out/chopin.notes.min.json out/chopin.n1.txt \
    chopin.n2.txt chopin.n2-inline.txt chopin.n2-words.txt chopin.n2-chords.txt
```

The raw output of the run behind this note is `counts.tsv`; the respelling run is `respell.tsv`.

## 4. An N1 extension: rests, part names, dynamics, chord symbols

Prototype encoder: `research/encoding-tokens/n2.py` (not wired into `engine/notes.py`; it imports `engine.score` for the note index and reads the MusicXML itself for the markup that the index drops). The version tag is `N2` so a decoder knows that `r` is now a written rest; the owner may prefer to keep `N1` and make the new lines optional, since every new line type is additive.

```
N2 div=48 ts=12/8 ks=3f
parts: 1-2 Piano
m0 len=24
1.1: 24 Bb4
2.1: 24 r
d1: 0 p
m1 len=288
1.1: 72 G5~ 24 G5 F5 G5 72 F5 48 Eb5 24 Bb4
2.1: 24 Eb2 G3+Eb4 Bb3+Eb4+G4 Eb3 Ab3+D4 Cb4+D4+Ab4 Eb2 G3+Eb4 Bb3+Eb4+G4 D2 G3+Eb4 Bb3+Eb4+G4
h: 0 Eb 96 Ddim 120 Ddim7 144 Eb
```

### Rests

N1 already writes `r` for every gap before the next attack in a voice, so most rests are in the text already. What it loses is rests that end a voice (nothing follows them, so no gap is written) and the split between consecutive rests. N2 writes every written rest with its own duration, `r` following a duration token like a note, and still writes unwritten gaps (`<forward>`, spaces, a voice that starts late) as `r`. On decode each `r` becomes a rest `Event`, which `ScoreIndex` already models (`pitch=None`); N1's decoder drops them.

Cost on the Chopin: 9 tokens (`2.1: 24 r` in the pickup bar, where the left hand only rests). The file has six written rests and five of them were already gaps in N1.

### Part names

One header line after the version line: `parts: 1-2 Piano` or `parts: 1 Flute; 2 Oboe; 3-4 Piano; 5 Violin I`. Staff ranges are Verovio's score-wide numbering, which N1's `staff.voice` lines already use, so a part is just a label on a range. `;` separates parts so names may hold spaces; no quotes. Cost: about 7 tokens here, 5–8 per part in general. Transposing instruments stay at sounding pitch as in N1; the line gives the model the instrument, which is what it needs for range and idiom checks, without written pitch.

### Dynamics

Two spellings were built and measured. Marks are the dynamic as printed (`p`, `pp`, `mf`, `ff`, `sf`, `fp`, …), `<` for a crescendo hairpin start, `>` for a diminuendo start, `!` for a hairpin end.

- **Line form.** After the voices of a bar, one line per staff that has marks: `d1: 0 p 144 < 288 !`, onset in `div` units from the bar start, like note durations. Dynamics belong to a staff in MusicXML, not a voice, and a hairpin end usually sits at an onset with no note, so this form represents every mark without special cases.
- **Inline form.** The mark is prefixed to the note that starts at its onset on that staff: `72 [p]G5~`, `[fp,z]Bb4`, `[!]F5`. Cheaper and the model reads the dynamic next to the note it governs. A mark with no note at its onset (9 of the 52 here, hairpin ends at bar ends) falls back to a `d` line.

With `--words` the other direction text (`a tempo`, `cresc.`, `dolciss.`, `rallent. smorz.`, `Andante`) goes into the same lines as quoted text. Pedal marks, articulations, slurs and lyrics are not encoded; pedal would fit the same line form (`ped`, `*`).

One file quirk: bar 13 carries `fp` and a separate `<other-dynamics>z</other-dynamics>`, which N2 writes as `0 fp 0 z`. It is in the source that way.

### Chord symbols

One line per bar for the part, not the staff: `h: 0 Eb 144 Bb7 216 Fm/Ab`. Root, kind as printed (MusicXML `kind text=` when present, else `m`, `7`, `m7`, `dim`, `dim7`, `m7b5`, `+`, `sus4`, `6`, `9`, `maj7`, `N.C.`), and `/bass` when the file gives one. `n2.py` reads `<harmony>` elements from MusicXML; the Chopin has none, so for the measurement `synth_chords.py` derived symbols from the AnalysisGNN draft in `tests/data/chopin_analysisgnn_raw.json` (root from the predicted scale degree in Eb, quality from the predicted quality, one symbol wherever they change). That is 176 symbols, 4.6 per bar, which is denser than a lead sheet (1–2 per bar) because the model's prediction flickers, so the per-symbol figure below is the useful number.

### Measured cost of each addition

| Variant | File | Tokens | Δ tokens vs N1 | Characters | Items | Tokens per item |
|---|---|---|---|---|---|---|
| N1 | `chopin.n1.txt` | 6,030 | | 5,797 | | |
| + explicit rests | (`n2.py --no-dynamics --no-parts`) | 6,039 | +9 | 5,807 | 1 trailing rest | 9 |
| + part names + dynamics, line form | `chopin.n2.txt` | 6,366 | +336 | 6,196 | 1 part, 52 marks | 6.3 per mark |
| + part names + dynamics, inline form | `chopin.n2-inline.txt` | 6,257 | +227 | 6,048 | 1 part, 43 inline + 9 fallback | 4.2 per mark |
| line form + direction words | `chopin.n2-words.txt` | 6,559 | +529 | 6,493 | 19 words extra | 10 per word |
| + chord symbols only (synthetic) | (`--chords --no-dynamics --no-parts`) | 7,280 | +1,250 | 7,155 | 176 symbols | 7.1 per symbol |
| everything, line form (synthetic chords) | `chopin.n2-chords.txt` | 7,607 | +1,577 | 7,544 | | 1.26x N1 |

So the full extension costs 26% over N1 on a piece with dense marks and an unrealistically dense chord track; with one chord symbol per bar it would be about 10%, and the inline dynamics form takes a third off the dynamics share. The extension stays 5.8x smaller than the minified JSON that carries no marks at all.

## 5. What to carry into `engine/notes.py`

1. Spelling: write flats as `-` (`B-4`), which saves 10% for free; `decode` and `normalise_pitch` already accept it. Decide separately on key-relative spelling (17%), which changes what a pitch token means and needs key changes in the text.
2. Rests: write every rest `Event` as `r` with its duration, keep gap `r`s, and create rest events on decode. Bump the version tag or document that both readings decode the same way (they do, except that trailing rests now survive).
3. `parts:` header. Verovio's MEI carries the part name as `label` on the `staffGrp`, so `ScoreIndex` can read it where it reads `staffDef`, without opening the MusicXML.
4. Dynamics: the MEI has `dynam` elements with `staff` and `tstamp` and `hairpin` elements with `tstamp` and `tstamp2` (both ends in one element), so `ScoreIndex` can collect them as it collects ties. Recommend the inline form with the `d` line fallback: cheapest, and the mark sits on the note it governs; the decoder strips `[…]` prefixes and reads `d` lines.
5. Chord symbols: Verovio imports MusicXML `harmony` as MEI `harm` elements with `tstamp`, which give the `h:` line the same way (none in this file to confirm against).
6. Keep `decode` tolerant of all four line types so an N1 reader can take N2 text (the server's `draft_from_notes` path), and add the new lines to `tests/test_notes.py`'s round-trip.

## 6. Files

| Path | What |
|---|---|
| `research/encoding-tokens/build_base.py` | Chopin .mxl → MusicXML, MEI, verbose and minified JSON, N1 |
| `research/encoding-tokens/n2.py` | the extension encoder; `--inline`, `--words`, `--chords FILE`, `--no-dynamics`, `--no-parts` |
| `research/encoding-tokens/synth_chords.py` | chord symbols from the AnalysisGNN draft, for the cost measurement only |
| `research/encoding-tokens/count_tokens.py` | the token-count script |
| `research/encoding-tokens/counts.tsv`, `respell.tsv` | raw API results behind sections 1, 2 and 4 |
| `research/encoding-tokens/chopin.n1.txt`, `chopin.n2*.txt`, `chopin.notes.min.json`, `chords.json` | the encodings measured above |
