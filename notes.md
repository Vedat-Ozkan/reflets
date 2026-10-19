# Composing companion: notes from 2026-10-14

Planning notes from one conversation. Nothing here is built yet. The analysis app gets finished and revised first; the companion starts in the next few weeks.

## 1. What the owner is planning

A second product, separate from the analysis app: a free, open-source AI companion for composing, installed from a GitHub repo and run locally.

- **Audience:** composition students first, then working composers.
- **Roles to start with:** critic, collaborator, teacher, assistant. More modes to brainstorm.
- **Collaborator writes music only when called on**, never automatically.
- **Runs locally, not served online.** No hosting cost to us and no daily cap. The AI reasoning comes from the user's own Claude, ChatGPT or Codex subscription (through MCP) or their own API key; rule-based checks run on the user's machine. Budget stays free, about $5/month.
- **Bundles the analysis app's engine**, so the full analysis toolkit runs free and unlimited locally, not tied to our online tools.
- **The online analysis app stays, side by side**, "more like a preview" for people who use Claude or ChatGPT in a browser.
- **Starts as a personal project**, hopefully grows.
- **Order:** finish and polish the analysis app first, then the companion.

## 2. Existing MCP servers for music apps

Checked on GitHub on 2026-10-14.

| Project | App | Last real work | Licence | Reads the score back? | Verdict |
|---|---|---|---|---|---|
| [tskovlund/mcp-score](https://github.com/tskovlund/mcp-score) | MuseScore (Dorico connect too) | 48 commits since July; last 2026-10-12; CI against MuseScore 4.4, 4.6, 4.7 | MIT | Yes: by passage, bar, selection; MusicXML generation; render through MuseScore's command line | Best base. Needs MuseScore 4.4.2+ and Python 3.14 |
| [ghchen99/mcp-musescore](https://github.com/ghchen99/mcp-musescore) | MuseScore 3/4 | 19 commits since July; last 2026-10-07; 117 stars | MIT | Yes: `get_score()` | Good, smaller. Has a mock MuseScore for tests |
| [JordanSucher/musescore-mcp](https://github.com/JordanSucher/musescore-mcp) | MuseScore | April 2025 | None | Partly | Abandoned. No licence, so its code can't be reused |
| [chrischall/musescore-mcp](https://www.getdrio.com/mcp/io-github-chrischall-musescore-mcp) | musescore.com | | | | Unrelated: searches the online sheet music library |
| [romanstark/dorico-maestro](https://github.com/romanstark/dorico-maestro) | Dorico | Created August 2026, last 2026-10-13, 2 stars | AGPL-3.0 | Only through a MusicXML export the user confirms | Active but early; reuse means AGPL |
| [happycastle114/dorico-mcp-server](https://github.com/happycastle114/dorico-mcp-server) | Dorico | January 2026 | None | Only the selection | Stale, unusable as a base |
| Sibelius | | | | | None found |
| [ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) | Ableton Live | Active, about 3,200 stars | MIT | | Popular, but a DAW, not notation |
| [veenastudio/flstudio-mcp](https://github.com/veenastudio/flstudio-mcp) | FL Studio | July 2025 | None | | Stale, DAW |
| [tylerjharden/flemcee](https://github.com/tylerjharden/flemcee) | FL Studio | February 2026 | None | | Small, DAW |

Dorico's limit is Steinberg's, not the projects': Maestro's README says the Remote Control API "cannot read bar contents back". On the [Steinberg forum](https://forums.steinberg.net/t/anyone-using-the-dorico-mcp/1032267) a user couldn't get the handshake to work and others said they wouldn't trust third-party servers.

No AI feedback or critique tool inside a notation app was found. What exists generates or suggests: Hookpad Aria (Hooktheory, lead sheets), Scaler (DAW chord plugin), Sibelius 2023.6 chord suggestions.

## 3. How the companion differs from the MuseScore MCP servers

Both existing servers are connectors: they let a chatbot read and write notes, and all musical judgement comes from the chatbot.

| | ghchen99 | mcp-score | Companion |
|---|---|---|---|
| Read the open score | Yes | Yes | Yes |
| Write notes and markings | Yes | Yes, plus dynamics, chord symbols, transposition | Yes |
| Music knowledge of its own | None | None ("analysis tools" only read notes) | Core: harmony, voice leading, ranges, cadences, key areas |
| Works without a chat AI | No | No | Yes: rule-based checks run locally and free |
| Feedback while you write | No | No | Yes, if MuseScore allows it (unverified) |
| Teaching: exercise rules, explanations, progress | No | No | Yes |
| Draws the analysis on the score | No | No | Yes (our engraving engine) |

**Standalone if** the core value works without a chatbot (live panel, exercise mode, drawn analysis). If it were mainly "talk to Claude about your score", it would be mcp-score plus a few tools.

**Unproven:** whether our engine beats a plain chatbot reading the raw notes. A user with mcp-score and Claude can already ask "check my voice leading". The comparison against plain ChatGPT and Claude (approved 2026-10-13) answers this for both products; 2–3 pieces, cost quoted first.

**Relationship to mcp-score:** its connection code is plumbing. Reuse or depend on its bridge (MIT), credit it, and possibly offer a few analysis tools back to its users as a route to them. Forking adds little.

## 4. Bundling the analysis app locally

The online server never does the analysis reasoning; the user's chat AI does. The server provides three things, all of which can run locally.

| Part | Today | Locally |
|---|---|---|
| Score reading, notes table, rendering (`engine/`, `skill/scripts/`) | Already runs in Claude's sandbox via the skill | Ready. Python plus Verovio, small install |
| Analysis reasoning | User's chat AI | Unchanged. "Unlimited" = up to the user's own AI plan limits |
| AnalysisGNN draft (`draft_from_notes`) | Our server only, under the daily cap | Possible but heavy: `.venv-agnn` is 1.4 GB (PyTorch and graph libraries). Best as an optional download; analysis works without it |
| PDF reading (Audiveris fork) | Downloaded on first use | `skill/scripts/read_pdf.py` only fetches the Ubuntu x86_64 package. Mac and Windows need their own builds or a Java install. Biggest porting job |
| Daily cap, cloud storage, result cards | Server only | Not needed |

**Where it works:** Claude Desktop and Claude Code (local MCP), Codex CLI (MCP). ChatGPT desktop: unverified. claude.ai and ChatGPT in the browser cannot reach a local program, so the online app stays the route there.

**Licences:** our code MIT; AnalysisGNN checkpoint MIT; Audiveris AGPL (shipping the fork means pointing to its source, as the site footer already does).

**Costs and catches:** large install with the model and PDF reading; testing on Mac, Windows and Linux; every engine change ships online and locally (same code, separate releases).

**While finishing the analysis app:** keep the engine runnable without the online parts (cloud storage, daily cap). It already is.

## 5. Modes

Starting four:

1. **Critic:** harmony, voice leading, ranges and playability, doublings and balance, phrase shape and form, idiomatic writing for each instrument.
2. **Collaborator (on request only):** continue a phrase, harmonise a melody, write a bass line or countermelody, offer alternative chords, orchestrate a piano sketch.
3. **Teacher:** explain why, in a chosen style, with examples from real repertoire.
4. **Assistant:** parts, transposition, cues, consistent dynamics and articulations, layout proofreading.

Brainstormed, not decided:

- **Check against an exercise:** set the rules (four-part chorale, first-species counterpoint, figured bass) and get feedback only against those.
- **Write like a composer:** "how would Mozart or Brahms handle this modulation?", with real examples from a corpus.
- **Reharmonise:** several alternatives for a passage, side by side.
- **Orchestration:** piano sketch to ensemble draft, then check balance, doublings, ranges.
- **Form overview:** a map of phrases, cadences and key areas so far.
- **Playback check:** what will sound muddy or thin (low thirds, crowded registers, covered melodies).
- **Pre-print proofread:** page turns, cues, missing dynamics, transposition errors.
- **Mentor log:** remember recurring mistakes across sessions and track improvement.
- **Assignment mode for teachers:** hints but no answers (some syllabi ban AI help).
- **Listener:** compare versions by playback ("A or B?") and say what changed.

**Design rule for cost:** rule-based checks run constantly and instantly; the AI runs only when the user asks.

## 6. Core use cases (owner)

The AI proposes; the engine checks each idea before the user sees it.

### "I've written the melody, not sure about the chords and accompaniment"

1. Read the melody: key, phrases, cadence points, strong-beat notes (the engine does most of this).
2. Ask about influences: "Bach chorale", "Chopin nocturne", "film score", "folk song", or a piece the user analysed.
3. Suggest 2–3 harmonisations (plain, richer, adventurous), each checked for clashes, voice leading and cadences.
4. Show them: in MuseScore, where the user listens and approves or discards (see section 7).
5. Accompaniment on request: block chords, Alberti bass, arpeggios, waltz pattern; then refine ("simpler in bars 5–8").

New work: harmonising a bare melody (the engine analyses existing chords), accompaniment patterns, the display.

### "My chords clash / sound wrong, why?"

The engine names the cause:

- **Melody vs chord:** a non-chord melody note on a strong beat, never resolved.
- **Voice leading:** parallel fifths or octaves, doubled leading tone, leading tone that doesn't rise.
- **Function:** a chord against where the phrase is heading; weak or missing cadence.
- **Voicing:** thirds too low (muddy), big gaps, crossed voices.
- **Harmonic rhythm:** changes at odd moments against the metre.

Then for each problem, e.g. "bar 6, beat 3: the melody's F clashes with the E in the chord; three fixes", each checked and shown on the score.

Already built: chord analysis, non-chord tones, voice-leading report (Phase 4), check my analysis (Phase 3). New: melody-vs-accompaniment clash detection, voicing checks, suggesting fixes.

### Limits

- "Sounds bad" is partly taste; explanations follow the conventions of a chosen style.
- Classical first; pop and jazz weaker until the jazz work (v2).
- The model draft gets full chord labels right about half the time, so the AI review step stays.
- Whether Claude or ChatGPT writes good harmonisations, even with checking, is untested.

## 7. Ideas go into MuseScore (owner)

The user listens with MuseScore's own sounds and approves or discards each idea. Three possible layouts; the owner chooses after a spike with real screenshots.

| Option | How it looks | Listening | Approve | Discard |
|---|---|---|---|---|
| A. Extra staves | "Idea 1", "Idea 2" under the user's music | Mute or solo in the mixer, play | Copy into the real staff; idea staves removed | Idea staff removed |
| B. In place, one at a time | Written into the user's staff | Press play | Keep it | One Ctrl+Z (whole idea = one undo step) |
| C. Separate score tab | Each idea is its own short score | Play in that tab | Copied back into the main score | Close the tab |

A is best for comparing, B simplest, C safest (the user's score is untouched until approval).

## 8. How the MuseScore MCP servers connect

Not through MusicXML. Read from both projects' plugin code and [mcp-score's plugin docs](https://github.com/tskovlund/mcp-score/blob/main/docs/musescore-plugin.md).

```
Claude / ChatGPT
   │  (MCP)
Python MCP server  ── WebSocket, localhost:8765, JSON messages ──►  QML plugin inside MuseScore
                                                                      │  MuseScore plugin API
                                                                      ▼
                                                                    the open score
```

1. A QML plugin inside MuseScore starts a WebSocket server (`api.websocketserver`, MuseScore 4.4.2+). Its window must stay open; MuseScore 4 has no persistent docked plugins.
2. The Python MCP server connects and sends commands like `{"command": "addNote", "params": {"pitch": 60}}`.
3. Reading: the plugin walks the score with a cursor and returns notes as JSON (MIDI pitch, start time, duration, voice).
4. Writing: notes are placed one at a time by the cursor, each command wrapped in `startCmd`/`endCmd` as one undo step; mcp-score rolls a failed sequence back.
5. MusicXML only at the edges: mcp-score's generator writes a file you open, and its render tool exports a saved file through MuseScore's command line.

Plugin API gaps mcp-score found by crashing MuseScore: bar lines can't be added through the cursor; chord symbols crash if text is set before insertion; no `Score.transpose` in MuseScore 4; the undo command was renamed in 4.7; plugins can't be started from the command line.

**Implications:**

- **Note spelling:** ghchen99 sends MIDI pitch, which can't tell C♯ from D♭. Harmony analysis needs the spelling (MuseScore stores it per note). Unchecked whether mcp-score's reader sends it.
- **Into our engine (which reads MusicXML):** (a) convert the plugin's JSON, carrying ties, tuplets, voices and grace notes; or (b) export the open score as MusicXML from the plugin, if MuseScore 4 allows it with unsaved edits (MuseScore 3 had `writeScore`; unverified for 4). The command-line export only sees the last saved file.
- **Writing ideas back:** note by note is slow and fragile for long passages. If a plugin can open a MusicXML file as a new score, option C is far simpler.

## 9. First spike when companion work starts

1. Can MuseScore 4's plugin API export the open score as MusicXML, unsaved edits included?
2. Does mcp-score's reader return note spelling?
3. Can a plugin open a MusicXML file as a new score?
4. Can a plugin add and remove staves, and mute or solo them?
5. Can a plugin learn that the score changed? A [forum report](https://musescore.org/en/node/321637) says `onScoreStateChanged` doesn't work in MuseScore 4; the fallback is polling or a "check now" button.
6. Can a plugin start playback? The 3.x docs list "run plugin when audio is playing" as out of reach; the user probably presses play.
7. Does mcp-score plus our tools in Claude Desktop handle "check what I've written so far" from start to finish?

Then: screenshots of each workable layout from section 7 for the owner to choose.

## 10. Name

The owner likes **Reflets** (ruh-FLAY): "reflections", from Debussy's *Reflets dans l'eau* (Images, book 1). The tool reflects the composer's work back to them, which is its feedback role.

Clash check, 2026-10-14 (not a trademark search):

- No music software named Reflets found. Closest: **Reflow**, a Mac/iOS notation app (similar sound, different word).
- **Reflets.info** is a French investigative news site; GitHub has a few small repos for its readers. Different field, but it ranks for the bare word.
- GitHub: nothing music-related; the largest similar name is `damien-schneider/reflet` (feedback-board tool, singular "reflet", 39 stars).
- Domains: `reflets.app`, `reflets.dev`, `reflets.io` are registered. `reflets.music` and `getreflets.com` had no DNS records, which suggests but doesn't prove they are free.
- Not yet checked: trademark registers (Canada's CIPO first, then the USPTO), app stores.

Names considered and set aside: Tutti (an iPad sheet-music reader and other apps use it), Ossia (ossia score, an open-source music sequencer, about 2,100 GitHub stars, owns ossia.io), Stand Partner, Continuo, Colla Parte, Cantus, Guido, Oppure, Ébauche, Esquisse, En Dehors. Avoid anything with "Muse" (MuseScore trademark), Maestro, Aria, Cadenza, Scaler, Second Ear.

## 11. Open questions

- Is ChatGPT desktop able to use a local MCP server? Answered 2026-10-14: only through its Codex side, not the chat surface (`research/hosts-sdks-licensing.md` lines 13-14); Codex support comes after Claude Code (spec open question 8).
- Which further modes from section 5 make the first release? Answered 2026-10-14: the critic only; teacher, assistant and collaborator come after (`docs/plan-2026-10-14.md` line 13).
- Trademark check for Reflets; domain choice.
- Mac and Windows builds for PDF reading.

## Sources

- [JordanSucher/musescore-mcp README](https://cdn.jsdelivr.net/gh/JordanSucher/musescore-mcp@main/README.md)
- [ghchen99/mcp-musescore README](https://glama.ai/mcp/servers/@ghchen99/mcp-musescore/blob/88456968de2750cd3d90c1ef30cae30dd24f6d17/README.md)
- [chrischall/musescore-mcp](https://www.getdrio.com/mcp/io-github-chrischall-musescore-mcp)
- [Dorico MCP Server (happycastle114)](https://glama.ai/mcp/servers/happycastle114/dorico-mcp-server)
- [Dorico Maestro](https://glama.ai/mcp/servers/cx97vl88sy)
- [Steinberg forum: Anyone using the Dorico MCP](https://forums.steinberg.net/t/anyone-using-the-dorico-mcp/1032267)
- [veenastudio/flstudio-mcp](https://glama.ai/mcp/servers/veenastudio/flstudio-mcp)
- [Flemcee worklog](https://glama.ai/mcp/servers/@tylerjharden/flemcee/blob/b674076840cd40bd4f362022901a62b699390da6/WORKLOG.md)
- [DAW MCP servers (LobeHub)](https://lobehub.com/mcp?q=daw)
- [MuseScore forum: onUpdate / onChange trigger for plugin?](https://musescore.org/en/node/321637)
- [MuseScore Plugins for 3.x handbook](https://musescore.org/handbook/developers-handbook/plugins-3x)
- [Hookpad Aria: A Copilot for Songwriters (ISMIR 2024)](https://ismir2024program.ismir.net/lbd_489.html)
- [AI tools for songwriting (Ditto Music)](https://dittomusic.com/blog/ai-for-songwriting-tools-to-step-up-your-game)
- GitHub API data for each repository above, read 2026-10-14.
