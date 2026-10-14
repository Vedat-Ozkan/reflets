I've finished exploring `/home/kema/projects/sheet-music-plugin`. Paths below are relative to that folder. No code ran: the facts come from source, tests and docs.

## 1. What the engine exposes

**Core data model, `engine/score.py` (standard library only)**
- `Event`: id, measure, staff, onset and duration (in quarter notes), pitch (a string like `"Eb4"`, at sounding pitch; `None` for a rest), grace, layer (the voice), tied, segment, attack.
- `Measure`: number (a pickup is 0), index, beat_length, meter, declared_length, events, segments. Methods: `offset_of(beat)`, `beat_of(offset)`, `segment_at`, `length`.
- `ScoreIndex(mei: str)` is built from Verovio's MEI, not from MusicXML directly. The other constructor is `ScoreIndex.from_measures(measures, meter, key_signature)`. Methods: `measure(n)`, `measure_range`, `find_note(measure, beat, staff, pitch)`, `ppq`, `locate_segment`.
- The usual way in is `ScoreIndex(load_toolkit(musicxml_bytes).getMEI())`.
- Only the first key signature is stored. Bars split around a repeat are joined into one measure, and bars are renumbered when the file's numbers repeat or go backwards.
- Transposing instruments are converted to sounding pitch. Pitch is spelled from the MEI accidental, so C# and Db stay distinct, and "x" becomes "##".

**Module by module**

| Module | Entry points | Input → output | Dependencies |
|---|---|---|---|
| `notes.py` | `encode(index, first, last)`, `decode(text)`, `NotesError` | ScoreIndex ↔ N1 text | stdlib only (deliberately, so the model's environment can import it) |
| `reduce.py` | `as_text(index, first, last)` (the beat-by-beat notes table), `midi()` | ScoreIndex → text | stdlib |
| `harmony.py` | `chord(key, label)` → `Chord(root, tones, bass, seventh, third)`; `mismatches(annotations, index)` | RomanText label, or annotation dicts plus ScoreIndex → list[str] | stdlib |
| `part_writing.py` | `applies(index)`, `check(index, chords=None)`, `as_text(index, chords)` | ScoreIndex (plus optional `draft.Chord` spans) → findings | imports music21 lazily, inside `check` |
| `check_analysis.py` | `from_text`, `from_musicxml`, `from_score`, `student_labels`, `compare_labels`, `as_text`, `ClarificationNeeded` | typed text or MusicXML → `Label(measure, beat, key, figure)` | music21 (key), plus `comparison.py` (music21 roman) |
| `draft.py` | `draft(index)`, `draft_from_notes(text)`, `build(raw, index)`, `as_text`, `as_annotations`, `run_analysisgnn(bytes, kind)` | ScoreIndex or N1 → `Draft(chords, cadences, phrase_ends, pedals, non_chord_tones)` | runs a separate `.venv-agnn` subprocess (`engine/models/analysisgnn_runner.py`) |
| `annotations.py` | `AnnotationList` (version 1, style current/abrsm/figured_bass) with annotation types Harmony, Cadence, Phrase, Region, NonChordTone, VoiceLeading, Callout; positions as `Position` / `NoteRef` | pydantic schema | pydantic |
| `annotate.py` | `render(score_bytes, annotations, measures, view, role, piano, student_labels)` → `Engraving`; `check(annotations, index)` raises `AnnotationError` | MusicXML bytes | Verovio, plus `overlay.py`, `slurs.py`, `text.py` (fontTools, PIL) |
| `render.py` | `load_toolkit(bytes)`, `engrave`, `engrave_tall`, `engrave_pages`; `Engraving.png()` / `.pdf()` | MusicXML (plain or .mxl) → SVG, PNG, PDF | verovio, resvg_py, PIL; PDF uses cairosvg + pikepdf, falling back to a PIL image PDF |
| `export.py` | `export_musicxml(original_bytes, analysis_dict)` | writes harmony labels into the original file as a `roman-analysis` lyric line on the bottom staff, or as a direction where no note starts on that beat | stdlib plus Verovio (for the index) |
| `notation.py` | `numeral(label, key, style, size)`, `abrsm()`, `figured_bass()` | label → typeset text pieces | music21 imported lazily, for figured bass only |
| `piano.py` | `reduce(score, measures, keep)` | MusicXML → two-staff piano MusicXML | music21 (heavy) |
| Others | `correct.py` (music21 + Verovio), `read_pdf.py` (pikepdf, Audiveris), `triplets.py`, `tuplet_rests.py` | | |

**Wired into the server (`server/app.py`)**
- `draft_analysis`, through `make_draft`: MusicXML → index → N1 encode → model → `draft.build` → `draft.as_text` + `reduce.as_text` + `part_writing.as_text` + `check_analysis.as_text`.
- `draft_from_notes`: N1 text in.
- `render_analysis`: `annotate.render` (including piano) + `export_musicxml`.
- `read_pdf` and `correct_bars`.

**Wired into the skill (`skill/scripts/`)**
- `notes_table.py` (`reduce`), `model_notes.py` (`notes.encode` + `check_analysis.student_labels`).
- `render_analysis.py` (render + export), `read_pdf.py`, `correct_score.py`.

**Engine-only (not called by the server or skill)**
- `harmony.mismatches`: only `harmony.chord` / `Chord` are used, by part_writing.
- `render(student_labels=...)` and the `check_display` overlay: the server's render call doesn't pass student labels.
- `comparison.from_romantext`, which appears to be for the evaluation code.

## 2. Is MusicXML the only input?

No. There is a path that skips MusicXML: `notes.decode(text)` builds measures and events and calls `ScoreIndex.from_measures`.

That decoded index works with:
- `part_writing.check`
- `draft.build`
- `check_analysis.compare_labels` / `as_text`
- `harmony` functions
- `reduce.as_text` (by its signature, not tested)

The server's `draft_from_notes` does exactly this: `draft.draft_from_notes(notes)` plus `note_list.decode(notes)`, then the part-writing and student-check sections.

Engraving, `annotate.render`, `export` and `piano` all need MusicXML bytes, because they go through Verovio.

**What N1 keeps:**
- Spelled pitch: C#4 and Db4 survive unchanged.
- Staff and voice (`staff.layer`), grace notes (`g`, grace chords as one token), ties (`~`), chords (`+`).
- Bar numbers including the pickup, bar length (`len=`), meter changes, and the first key signature (`ks=3f`).
- Tuplets only as durations in `div` units (the lowest common denominator); there is no tuplet markup.

**What N1 drops:**
- Rests: a rest becomes a gap token (`r`) and no rest Event is created on decode; trailing rests disappear.
- Part and instrument identity: staves are numbered across the whole score.
- Written pitch (only sounding pitch), clefs, key-signature changes, slurs, dynamics, articulations, lyrics, text and harmony symbols, repeats/voltas, beaming, and grace type.
- Decoded Event ids are synthetic (`m1-1.1-0`).

Also, the model runner (`score_from_notes`) always sets the key signature as "major" and reads the octave as the last single digit of the pitch.

Round-trip equality is tested in `tests/test_notes.py`.

## 3. Part-writing checks (`engine/part_writing.py`)

**Rules:** `parallel_fifths`, `parallel_octaves` (including unisons), `direct_fifths` / `direct_octaves` (outer voices, soprano leap), `voice_crossing`, `voice_overlap`, `spacing` (adjacent upper voices more than an octave apart), `range` (SATB ranges from Open Music Theory, C4–G5 / G3–D5 / C3–G4 / F2–D4), `doubled_leading_tone`, `unresolved_seventh`, `unresolved_leading_tone` (outer voices at V–I).

**When it runs at all:** `applies()` gates it. It needs 2–4 single-line voices (staff/layer pairs), at most 4 staves, and at least 60% of onsets shared by all voices (chorale-style texture). Otherwise it returns no findings.

**Inputs:** a ScoreIndex, plus optional `draft.Chord` spans for key and labels. Without spans it estimates keys with music21 over 4-bar windows and filters passing, neighbour, anticipation and leaping-leading-note decorations first.

**Results:** `Finding(bars, beats, voices, rule, why)`. `as_text` groups findings into numbered spots, with JSON NoteRefs and arrow labels ready to paste into an annotation list.

## 4. Tests

The suite is end-to-end on real files; there are no mocks of the engine.
- The only monkeypatching swaps the server's storage for `LocalStore(tmp_path)` (in `test_host_render`, `test_part_writing_draft`, `test_student_check_draft`).
- Real Verovio runs throughout. Some tests run the real AnalysisGNN, for example `test_note_list_path_gets_the_same_section` and `make_draft`.
- `tests/conftest.py` has session fixtures `chopin` (`tests/data/chopin_nocturne_op9_no2.mxl`) and `chopin_annotations` (`examples/chopin_op9_no2_m1-8.json`). In a git worktree it borrows `.venv-agnn`, the model checkpoint, `out/engraving` and `spike/omr/truth` from the main checkout. A missing git-ignored fixture becomes a skip with a reason, not a failure.

**Golden output:** there is a single golden file, `tests/golden/chopin_m1-8_all.png`.
- `test_annotate.py::test_matches_golden_image` renders at width 800, converts to grayscale, requires the same size and a mean pixel difference below 1.0.
- If the golden file is missing, the test writes it and skips.
- Other render tests assert on SVG strings: callout circles, ">PAC<", colours per view.

**Representative tests:**
- `test_part_writing.py`: planted errors in `part_writing_motion.musicxml` and `part_writing_tendency.musicxml`, music21 corpus Bach chorales with reviewed expected hits, and many regression cases. There is also an audit against `tests/data/reference/part_writing_audit.json`.
- `test_export.py`: real scores; checks that the notes are unchanged after export and that `from_musicxml` reads the labels back.
- `test_host_render.py`: calls the server tool and checks PNG bytes equal to `render()`, the downloads' headers, the skill scripts run by subprocess, and Latin-1 and malformed-file cases.
- `test_check_analysis.py`: typed grammar (`typed_inputs.json`, 138 cases) and real MuseScore exports.

**Fixtures in `tests/data`:**
- Chopin .mxl, Audiveris readings and a PDF.
- 18 Bach chorale XMLs (`part_writing_bwv*`) and the planted part-writing files.
- `export-*` scores (Brahms, Debussy, Mozart) and `export_placement`.
- Triplet scores; folders `tuplet_rests/`, `pdf_warnings/` (PDFs and variants), `check_analysis/` (MuseScore .mscx and .musicxml), `check_display/`, `awkward/`, `reference/`.
- Raw model output JSONs (`chopin_analysisgnn_raw.json`, `cadential_64_raw.json`).

Some tests depend on files outside `tests/`: `out/engraving/scores/bach-269.mxl` (git-ignored), `spike/export/*.musicxml`, `examples/engraving/*.json`, and the music21 corpus.

## 5. Tools

**`tools/robustness.py`** (`--no-model`, `--only`, `--matching`)
- Runs about 20 scores: music21 corpus, ASAP / MuseTrainer downloads, and PDFs through Audiveris.
- Stages: read, table, note-list round trip, engrave, model on the whole piece, model on an excerpt, check that the draft's positions resolve, render the draft.
- Writes `out/robustness/report.json` plus PNGs and prints one status line per score.

**`tools/engraving_check.py`** (`--tag`, `--style`)
- Renders 9 hand-checked passages from `examples/engraving/*.json` (Bach to Dvořák, including quartets and symphonies).
- Counts overlay labels that overlap or sit tight, and collisions between the music's own text and the notes.
- Writes PNG and PDF to `out/engraving/<tag>/` and a `report.json`. Its docstring calls the count a first filter, not a verdict.

## 6. Docs

- **`docs/plan.md` sections:** Context, What changed from the handoff, Architecture, Steps, Risks, Verification, Housekeeping.
- **Last five engineering-log entries:**
  - 36. Engine work for later phases, cross-reviewed by Codex
  - 37. The voice-leading report offered in the chat
  - 38. A night of Codex work, checked by Claude
  - 39. Check my analysis: the plumbing
  - 42. PDF reading: a tie no longer goes to the sparse reading

  (40 and 41 are absent.)
- **`docs/annotation-spec.md`:** describes AnnotationList v1 as "the contract": positions only, never pixels, plus the style table (current / abrsm / figured_bass).
- **`docs/check-analysis-inputs.md`, MuseScore Studio 4.7.5 export:**
  - Native Roman-numeral harmony exports as `<harmony><numeral>` for 9 of the 12 test labels. The other 3 (N6, Ger65, Fr43) export as `<root-step text="">C</root-step><kind text="…">none</kind>`; ordinary chord text uses that same shape. No lyrics are written.
  - Information is lost: ii65→ii, V7/V→V, viio7/ii→vii, viiø7→vii, It+6→I6. Only the root's case, a leading b/#, and a 6 or 64 inversion survive.
  - The doc says not to promise faithful checking of complex MuseScore analysis; use typed labels or lyrics instead.
  - `export.py` writes analysis as lyrics for this reason.
- **`docs/companion-notes-2026-10-14.md`** already covers the companion: MuseScore MCP servers, bundling locally, modes, name, open questions. It says `.venv-agnn` is about 1.4 GB and should be an optional download.

## 7. Dependencies

- **`pyproject.toml`:** Python ≥3.11 (the venv is CPython 3.11). Packages: music21≥10.5, verovio≥6.3, resvg-py, mcp≥2.2, httpx, uvicorn, pillow, python-multipart, fonttools, pydantic≥2.8, google-cloud-storage, cairosvg, pikepdf. Dev: pytest, pypdf.
- **Installed sizes:** `.venv` is 383 MB in total, of which music21 is 114 MB, verovio 29 MB, fontTools 25 MB, google 7 MB, PIL 6.9 MB, pikepdf 3.5 MB, resvg_py 2.9 MB, cairocffi/cairosvg under 1 MB, plus numpy and matplotlib pulled in by music21.
- **Model environment:** `.venv-agnn` is 1.2 GB on disk, with torch 2.5 CPU, torch-geometric, partitura and its own music21. Pins are in `server/requirements-agnn.txt`; it is built in `Dockerfile.base`.
- **System library:** cairo (`libcairo2`) is needed for the vector PDF.
- **The skill's sandbox install** is `verovio resvg-py cairosvg pikepdf pillow fonttools pydantic` (no music21), plus music21 only for `--piano`.
- **Without music21** you can still: index, use N1, build the notes table, use `harmony`, engrave and render (except figured-bass style and piano), and export.
- **music21 is required for:** `part_writing.check`, `check_analysis` and `comparison`, `piano`, `correct`, and figured bass.