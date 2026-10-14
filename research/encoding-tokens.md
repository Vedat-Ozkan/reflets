# Score encodings for the model: sizes, token counts, and an N1 extension

Measured on 2026-10-14 against `sheet-music-analysis` at commit `02c13ec`, file `tests/data/chopin_nocturne_op9_no2.mxl` (Chopin, Op. 9 No. 2: 38 bars including the pickup, 1,253 notes, 2 staves, one part). Scripts and every encoding discussed here are in `research/encoding-tokens/`; the plugin repo is expected next to this one (or at `$SHEET_MUSIC_REPO`).

**Status.** Character counts are measured. Claude token counts are **not**: this session's container has no Anthropic API key (the API answers `401 x-api-key header is required`, there is no `ant` profile and no `ANTHROPIC_API_KEY`), so `count_tokens.py` was written and run but could not get a number. Add `ANTHROPIC_API_KEY` to the environment's secrets and run the one command in section 2; the table in section 1 has a column waiting for the results. The plan's chars ÷ 3.5 rule is shown as a placeholder and labelled as such.

## 1. The three base encodings

| Encoding | File | Characters | Lines | Whitespace words | Relative to N1 | Tokens (claude-fable-5-1) |
|---|---|---|---|---|---|---|
| MusicXML, uncompressed (what is inside the .mxl) | `chopin.musicxml` (regenerate with `build_base.py`) | 509,478 | 18,604 | 22,958 | 88x | not measured, ≈145k by chars ÷ 3.5 |
| MEI from Verovio (reference only) | `chopin.mei` (regenerate) | 263,769 | 3,490 | 14,468 | 46x | not measured, ≈75k |
| JSON per note, verbose (indent 2, same keys) | `chopin.notes.verbose.json` (regenerate) | 130,744 | 10,206 | 17,828 | 23x | not measured, ≈37k |
| JSON per note, minified, short keys | `chopin.notes.min.json` | 56,879 | 1 | 1 | 9.8x | not measured, ≈16k |
| N1 (`engine/notes.py`, `encode(index)`) | `chopin.n1.txt` | 5,797 | 111 | 1,162 | 1x | not measured, ≈1.7k |

The minified JSON carries exactly what N1 carries, so the comparison is fair: `{"div":48,"ts":"12/8","ks":"3f","measures":[{"n":0,"len":24},…],"notes":[{"m":1,"s":1,"v":1,"o":0,"d":72,"p":"G5","t":1},…]}`, one object per note with measure, staff, voice, onset and duration in `div` units, sounding pitch, and `g`/`t` flags for grace and tie. These numbers agree with the plan of 2026-10-14 (5,796 and 58,745 there; the JSON differs by key choice).

Why real token counts matter more here than for prose: N1 is dense symbolic text (`Bb3+Eb4+G4`, `72 G5~`). Claude's tokenizer will not give 3.5 characters per token on it; the pitch names, `+`, `~` and numbers may each be a token. The ratio N1 : JSON : MusicXML is robust (the JSON and XML repeat the same symbols plus syntax), but the absolute N1 count could land anywhere from 1.7k to 3k. That is the number the companion's context budget depends on, which is why the API measurement is worth doing before the encoding is frozen.

## 2. Counting tokens

`research/encoding-tokens/count_tokens.py` calls `client.messages.count_tokens(model="claude-fable-5-1", messages=[{"role": "user", "content": text}])` once per file, subtracts the fixed per-request overhead (measured with a one-character message), and prints tokens, characters and characters per token. It needs `pip install anthropic` and a key:

```sh
cd research/encoding-tokens
python build_base.py out            # writes chopin.musicxml, chopin.mei, chopin.notes.*.json, chopin.n1.txt
ANTHROPIC_API_KEY=… python count_tokens.py out/chopin.musicxml out/chopin.notes.min.json out/chopin.n1.txt \
    chopin.n2.txt chopin.n2-inline.txt chopin.n2-words.txt chopin.n2-chords.txt
```

Run in this container it fails at the client constructor with "Could not resolve authentication method", which is the expected failure with no credential. No result was substituted.

## 3. An N1 extension: rests, part names, dynamics, chord symbols

Prototype encoder: `research/encoding-tokens/n2.py` (not wired into `engine/notes.py`; it imports `engine.score` for the note index and reads the MusicXML itself for the markup that the MEI index drops). The version tag is `N2` so a decoder knows that `r` is now a written rest; the owner may prefer to keep `N1` and make the new lines optional, since every new line type is additive.

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

Cost on the Chopin: +10 characters (`2.1: 24 r` in the pickup bar, where the left hand only rests). The file has six written rests and five of them were already gaps in N1.

### Part names

One header line after the version line: `parts: 1-2 Piano` or `parts: 1 Flute; 2 Oboe; 3-4 Piano; 5 Violin I`. Staff ranges are Verovio's score-wide numbering, which N1's `staff.voice` lines already use, so a part is just a label on a range. `;` separates parts so names may hold spaces; no quotes. Cost: 17 characters here, about 10 per part in general. Transposing instruments stay at sounding pitch as in N1; the line gives the model the instrument, which is what it needs for range and idiom checks, without written pitch.

### Dynamics

Two spellings were built and measured. Marks are the dynamic as printed (`p`, `pp`, `mf`, `ff`, `sf`, `fp`, …), `<` for a crescendo hairpin start, `>` for a diminuendo start, `!` for a hairpin end.

- **Line form.** After the voices of a bar, one line per staff that has marks: `d1: 0 p 144 < 288 !`, onset in `div` units from the bar start, like note durations. Dynamics belong to a staff in MusicXML, not a voice, and a hairpin end usually sits at an onset with no note, so this form represents every mark without special cases.
- **Inline form.** The mark is prefixed to the note that starts at its onset on that staff: `72 [p]G5~`, `[fp,z]Bb4`, `[!]F5`. Cheaper and the model reads the dynamic next to the note it governs. A mark with no note at its onset (9 of the 52 here, hairpin ends at bar ends) falls back to a `d` line.

With `--words` the other direction text (`a tempo`, `cresc.`, `dolciss.`, `rallent. smorz.`, `Andante`) goes into the same lines as quoted text. Pedal marks, articulations, slurs and lyrics are not encoded; pedal would fit the same line form (`ped`, `*`).

One file quirk: bar 13 carries `fp` and a separate `<other-dynamics>z</other-dynamics>`, which N2 writes as `0 fp 0 z`. It is in the source that way.

### Chord symbols

One line per bar for the part, not the staff: `h: 0 Eb 144 Bb7 216 Fm/Ab`. Root, kind as printed (MusicXML `kind text=` when present, else `m`, `7`, `m7`, `dim`, `dim7`, `m7b5`, `+`, `sus4`, `6`, `9`, `maj7`, `N.C.`), and `/bass` when the file gives one. `n2.py` reads `<harmony>` elements from MusicXML; the Chopin has none, so for the measurement `synth_chords.py` derived symbols from the AnalysisGNN draft in `tests/data/chopin_analysisgnn_raw.json` (root from the predicted scale degree in Eb, quality from the predicted quality, one symbol wherever they change). That is 176 symbols, 4.6 per bar, which is denser than a lead sheet (1–2 per bar) because the model's prediction flickers, so the per-symbol figure below is the useful number.

### Measured cost of each addition

| Variant | File | Characters | Δ vs N1 | Items | Characters per item |
|---|---|---|---|---|---|
| N1 | `chopin.n1.txt` | 5,797 | | | |
| + explicit rests | (`n2.py --no-dynamics --no-parts`) | 5,807 | +10 | 1 trailing rest | 10 |
| + part names + dynamics, line form | `chopin.n2.txt` | 6,196 | +399 | 1 part, 52 marks | 7.5 per mark |
| + part names + dynamics, inline form | `chopin.n2-inline.txt` | 6,048 | +251 | 1 part, 43 inline + 9 fallback | 4.5 per mark |
| line form + direction words | `chopin.n2-words.txt` | 6,493 | +696 | 19 words extra | 15.6 per word |
| + chord symbols only (synthetic) | (`--chords --no-dynamics --no-parts`) | 7,155 | +1,358 | 176 symbols | 7.7 per symbol |
| everything, line form (synthetic chords) | `chopin.n2-chords.txt` | 7,544 | +1,747 | | 1.30x N1 |

So the full extension costs about 30% over N1 on a piece with dense marks and an unrealistically dense chord track; with one chord symbol per bar it would be about 12%. The extension stays about 7.5x smaller than the minified JSON that carries no marks at all. Token counts for each variant come from the same `count_tokens.py` run as section 2.

## 4. What to carry into `engine/notes.py`

1. Rests: write every rest `Event` as `r` with its duration, keep gap `r`s, and create rest events on decode. Bump the version tag or document that both readings decode the same way (they do, except that trailing rests now survive).
2. `parts:` header from the MusicXML `part-list`. `ScoreIndex` is built from MEI; Verovio's MEI carries the part labels in `staffDef`/`staffGrp label`, so this can be read there without opening the MusicXML.
3. Dynamics: the MEI has `dynam` elements with `staff` and `tstamp` and `hairpin` elements with `tstamp` and `tstamp2` (both ends in one element), so `ScoreIndex` can collect them as it collects ties. Recommend the inline form with the `d` line fallback: it is cheapest and places the mark on the note, and the decoder needs only to strip `[…]` prefixes and read `d` lines.
4. Chord symbols: Verovio imports MusicXML `harmony` as MEI `harm` elements with `tstamp`, which give the `h:` line the same way (none in this file to confirm against).
5. Keep the existing `decode` tolerant of all four line types so an N1 reader can take N2 text (the server's `draft_from_notes` path), and add the new lines to `tests/test_notes.py`'s round-trip.

## 5. Files

| Path | What |
|---|---|
| `research/encoding-tokens/build_base.py` | Chopin .mxl → MusicXML, MEI, verbose and minified JSON, N1 |
| `research/encoding-tokens/n2.py` | the extension encoder; `--inline`, `--words`, `--chords FILE`, `--no-dynamics`, `--no-parts` |
| `research/encoding-tokens/synth_chords.py` | chord symbols from the AnalysisGNN draft, for the cost measurement only |
| `research/encoding-tokens/count_tokens.py` | the token-count script (needs `ANTHROPIC_API_KEY`) |
| `research/encoding-tokens/chopin.n1.txt`, `chopin.n2*.txt`, `chopin.notes.min.json`, `chords.json` | the encodings measured above |
