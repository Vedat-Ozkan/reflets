# Reflets core spec: bridge plugin, MCP server, wire protocols, write path

Status: draft 1, 2026-10-14; slice 1 (reading the open score: `score_info`, `read_score`) and slice 2 (ideas in place: `propose`, `discard`, `keep`) built 2026-10-18, with "As built in slice N" notes where it narrows the design. Written from the planning handoff (`notes.md`, `docs/plan-2026-10-14.md`, `research/`). This document fixes the design of the core so that the first release slice (read the open score reliably, run rule-based checks, write a proposed idea into MuseScore for audition, approve or discard; `plan:13`) can be implemented, and so that the later modes bolt on without changing the protocols.

Every design choice cites a line in `research/`. Owner decisions cite `docs/plan-2026-10-14.md` or `notes.md`. Where the research says a fact is unverified at runtime, the choice is marked **[spike]** and listed in section 10; the design does not silently depend on it.

## 0. Citation keys and confidence marks

| Key | File |
|---|---|
| `api:N` | `research/musescore-4.7.5-plugin-api-matrix.md`, line N (read from MuseScore source at tag v4.7.5) |
| `hosts:N` | `research/hosts-sdks-licensing.md`, line N |
| `rig:N` | `research/test-rig-wsl2.md`, line N |
| `engine:N` | `research/sheet-music-engine-surface.md`, line N (the existing analysis engine in `sheet-music-plugin`) |
| `deep:N` | `research/deep-research-2026-10-14.json`, line N (deep-research workflow, 3-vote verified claims) |
| `plan:N` | `docs/plan-2026-10-14.md`, line N |
| `src:N` | `research/musescore-source-reads-2026-10-15.md`, line N (direct reads of MuseScore source at tags 4.4.4, 4.6.2 and 4.7.5, and of the engine at commit 02c13ec, done 2026-10-15) |
| `notes:N` | `notes.md`, line N |

Marks: **[verified]** read in MuseScore 4.7.5 source or a primary document. **[reported]** a third-party reproduction that was not independently re-run (`deep:89`, `deep:77`). **[spike]** must be tried on a real MuseScore before code depends on it.

## 1. Scope

In scope for the core:

1. **Bridge plugin**: one QML file installed in the user's MuseScore plugin folder. It has no window (2.1), listens on a local WebSocket port, and executes read and write requests against the open score.
2. **MCP server**: a Python package the user's harness starts over stdio. It owns the connection to the plugin, converts between the two wire protocols, calls the analysis engine, and exposes fewer than ten tools.
3. **Protocol A**: plugin to server. Line-oriented text with request ids, an application-level ping, and client-side reconnect.
4. **Protocol B**: model to server. The N1 compact note list from the engine, extended with rests, part identity, dynamics and chord symbols. The same grammar is used for reading and for writing ideas.
5. **Write path**: one undo step per idea, verified by read-back.
6. **Ideas into MuseScore**: in place (one undo step) and as a new tab built from a temporary MusicXML file.

Out of scope here: the critic, teacher, collaborator and assistant prompts (`notes:83-86`); the AnalysisGNN draft and PDF reading (`notes:67-68`); any UI inside MuseScore beyond the bridge window (`plan:14`); the full verification rig (`plan:134`, outlined in section 9 only as far as it constrains the design).

```
Harness (Claude Code first; Claude Desktop, Codex CLI)          plan:14
   │  MCP over stdio                                            hosts:50
   ▼
reflets server (Python, MCPServer, imports engine/)             hosts:50, engine:9
   │  Protocol A: WebSocket text frames, ws://127.0.0.1:PORT    deep:6, rig:27
   ▼
Reflets bridge plugin (QML, legacy v1 plugin, no dialog)       api:90, api:114
   │  PluginAPI v1: curScore, Cursor, startCmd/endCmd, cmd()    api:11, api:31, api:17
   ▼
the open score in MuseScore Studio 4 (GUI only)                 deep:28
```

## 2. Placement decisions

### 2.1 The plugin is a legacy v1 QML plugin without a dialog

- A v1 plugin gets exactly `api.log`, `api.engraving`, `api.websocket`, `api.websocketserver` (`api:90`). That is everything the bridge needs; the v2 extension API adds interactive and theme objects and deliberately omits process and filesystem (`api:92`), so v2 buys nothing for the bridge and costs a manifest.json.
- Manifest: no `pluginType` (a "macro" plugin), `requiresScore: false` (`api:114`: `"false"` maps to UI context `Any`). The manifest is a line scan of the `MuseScore {` block, so these properties are written as plain literal lines (`api:114`).
- **Why no dialog** (spike, `research/spike-bridge-hello-2026-10-18.md`, round 3): while a v1 plugin's dialog is open, MuseScore refuses every notation action gated on the score page being current. `cmd("tie")` logs `no one can handle the action: tie` with the dialog open, inside or outside `startCmd`, and works with no dialog open. Undo and redo are not affected (own enabler). So a dialog bridge cannot tie, and probably cannot dispatch most other notation actions.
- Lifecycle: a macro plugin is created by `component.create()` and then never deleted (`src/framework/extensions/internal/legacy/extpluginrunner.cpp:49-61` at v4.7.5), so its object, and the server it started in `onRun`, live until MuseScore quits. The plugin is started once per session from the Plugins menu and cannot be stopped except by quitting MuseScore. This relies on the runner not deleting the object, which is unspecified behaviour; recheck on each new MuseScore release.
- One server per MuseScore: all v1 plugins share one `WebSocketServerApi` object (`src/framework/network/api/websocketserverapi.cpp` at v4.7.5). A second `listen()` on another port fails silently but replaces the new-connection callback, so the most recently started plugin answers new connections. Running the bridge twice is harmless (the new instance takes over); running another bridge plugin (mcp-score, ghchen99) in the same session steals the connection, which `hello` detects.
- Qt 6 and QtQuick.Controls 2 idioms only, because a plugin not written for Qt 6 is silently not listed (`deep:49`, `deep:56`).
- No status window. Status is reported through `hello` and the server's tool errors; `api.log.info` lines go to MuseScore's log file.

### 2.2 The plugin listens, the server connects

`api.websocketserver` has `listen`, `onMessage`, `send` and nothing else: no close, no disconnect callback, text frames only (`deep:6`). The research's own conclusion is adopted: the plugin is the listener and the MCP server is the reconnecting client (`deep:13`).

Port: the API default is 8084 when the port is negative (`deep:6`); mcp-score and ghchen99 both use 8765 (`notes:157`, `deep:93`). Reflets uses its own default, **8731**, a constant in the plugin file and settable on the server (`REFLETS_PORT`). Reason: a stale plugin instance keeps serving its port after a restart (`deep:81`), and a stale mcp-score plugin on 8765 would otherwise answer a Reflets connection with the wrong protocol. The `hello` handshake (3.5) identifies the plugin in any case.

Security: `listen()` binds all interfaces, not loopback (`deep:6`). On the owner's machine Windows already had inbound Allow rules for MuseScore 4 on the Public profile, so no prompt appeared and other devices on the network can likely connect. Decided 2026-10-18 (open question 4): a shared secret. At `onRun` the plugin writes a random token to a file under Documents/MuseScore4 with `FileIO` (`api:20`); the server reads it and sends it in `hello`; the plugin answers nothing else on a connection until a matching `hello`. No TLS, no accounts.

### 2.3 Music logic lives in Python, the plugin stays thin

- Plugin code is cached at MuseScore startup, so every plugin change costs a MuseScore restart (`deep:81`, `deep:89`).
- Plugin `console.log` output is discarded (`deep:28`); diagnostics must go over the socket.
- The Python side can be tested in-process with the SDK client (`rig:41`) and from the Inspector CLI (`rig:40`).

Rule: the plugin does only what requires the PluginAPI (walk the score, place notes, run commands) and emits a raw line format that mirrors the API's fields (3.7). All conversion to and from the model-facing format, all validation, all caching and all music reasoning are in the server.

### 2.4 The server is Python, importing the engine

- Python MCP SDK v2.3.0 (2026-10-02): `FastMCP` is now `MCPServer`, stdio servers divert stray stdout to stderr, `ToolError` carries a model-visible message, Python >= 3.11 (`hosts:50`). The engine already depends on `mcp>=2.2` and Python >= 3.11 (`engine:147`). Decision recorded in the plan: Python server importing the engine in-process (`plan:97`).
- The engine's N1 encoder and decoder are stdlib-only (`engine:17`), and a decoded N1 index works with `part_writing.check`, `draft.build`, `harmony` and `reduce.as_text` without MusicXML (`engine:48`, `engine:50-55`). This is the path the critic uses on live reads.

### 2.5 Supported MuseScore versions

- Official 4.7 builds, tested on 4.7.5 (owner decision, 2026-10-18). The WebSocket API exists from 4.4.2 (`deep:17`, `deep:24`), but 4.4.3 stubs `readScore`/`writeScore` (`api-gaps` 3.2) and the undo codes differ before 4.7 (6.8), so older versions are refused at `hello` rather than half supported. The plugin checks `api.websocketserver` at start and shows a message if it is undefined, which happens in some distro builds (`deep:17`, `deep:24`).
- GUI only: the console and `--extension` contexts have no WebSocket API on 4.7 (`deep:28`, `deep:34`).
- The owner's Windows install is 4.7.5, where the bridge spike passed (`research/spike-bridge-hello-2026-10-18.md`). Test matrix: 4.7.5.
- Version is read from `mscoreVersion` (major*10000 + minor*100 + patch, 40705 for 4.7.5; `api:21`) and reported in `hello` so the server can refuse unknown versions with a clear message.

## 3. Protocol A: plugin to server

### 3.1 Transport

WebSocket, text frames only (`deep:6`). The server connects to the literal `ws://127.0.0.1:<port>`, never `localhost`, because under WSL2 mirrored networking only 127.0.0.1 is documented and `::1` is not supported (`rig:27`, `rig:30`).

Found in the element spike (2026-10-19): `api.websocketserver` is shared by every plugin in the MuseScore process, and the last plugin to call `listen` receives every connection, whatever port it listens on. Another plugin that uses the WebSocket server, run after the bridge, takes Reflets' connections; `doctor` (5.2) should detect a reply that is not the bridge's `hello`.

### 3.2 Framing

One WebSocket frame is one message. A message is UTF-8 text split on `\n`. Line 1 is the header. Lines 2 onward are the body. Text fields (titles, annotation text) are always the last field of their line and are escaped: `\` becomes `\\`, newline becomes `\n`.

```
request   <id> <verb> [<arg> ...]
          <body line>*
response  <id> ok [<summary> ...]
          <body line>*
          <id> err <code> <message>
```

- `<id>` is a decimal integer, increasing per connection, starting at 1. The plugin echoes it. The server discards any response whose id it is not waiting for, which happens after a reconnect, since the plugin cannot observe disconnection and has no close method (`deep:6`, `deep:13`).
- One request is in flight at a time. The plugin is single-threaded QML and the server serialises its queue. The id exists to detect stale replies, not to multiplex.
- Why a line format and not JSON: the read body is already a line-per-event list that the server turns into the model-facing N1x (section 4), and the compact format is about ten times smaller than minified JSON-per-note (`plan:54`, `plan:56`). Keeping the plugin's output line-oriented means no double encoding and no JSON builder in QML. JSON would have worked over text frames too; this is a cost choice, not a capability one.

### 3.3 Liveness: application-level ping

As built in slice 1 (2026-10-18): no ping loop. The server connects on the first tool call and, if a request fails on a dropped socket, reconnects once (3.4) before reporting that MuseScore is not reachable. The ping loop below waits until something needs it. The plugin registers `onMessage` once per connection, in its new-connection callback, which runs once per client id; and it admits a connection only after a `hello` with the token (2.2).

- The server sends `ping` every 5 s while idle and treats two missed `pong`s as a dead connection, closes its socket and reconnects. The API offers no disconnect callback and no close, so liveness can only be detected at application level (`deep:13`); mcp-score polls a ping every 2 s for readiness (`deep:93`).
- The plugin registers `onMessage` once per client id (ids start at 2001; `deep:6`); registering twice double-delivers messages (`deep:6`, `deep:13`). The plugin keeps a set of ids it has registered.
- The plugin cannot drop a client. It keeps the id map and answers whoever speaks. The server's hello (3.5) is the only admission control in v1.

### 3.4 Reconnect: client side, never blocking startup

As built in slice 1: no state machine or backoff; connect lazily on the first tool call (which already keeps startup instant, about 0.4 s to import), one retry per request. `score_info` returns the not-reachable text as its result; the other tools raise it as `ToolError`.

- Server states: `disconnected`, `connecting`, `hello`, `ready`. Backoff 0.5 s, 1 s, 2 s, 5 s, then 5 s steady.
- The server never waits for MuseScore at startup. Codex kills a server that takes more than 10 s to start (`hosts:19`) and Claude Code waits at most `MCP_TIMEOUT`, 30 s, for pending servers (`hosts:37`). The process must answer the MCP handshake within a second and connect to the plugin in the background.
- A tool called while not `ready` raises `ToolError` with the user-facing instruction "open MuseScore, open your score, run Plugins > Reflets Bridge" (`hosts:50`: `ToolError` reaches the model; other exceptions are flattened to "Error executing tool").

### 3.5 Handshake

```
1 hello proto=1 client=reflets-server/0.1
1 ok proto=1 plugin=reflets-bridge/0.1 mscore=40705 score=1 title=Nocturne\ in\ E\ flat
```

- `mscore` is `mscoreVersion` (`api:21`). `score=0` when `curScore` is null (`api:11`).
- A `proto` mismatch produces a server-side message telling the user to update the plugin file and restart MuseScore, because the plugin is cached at startup (`deep:81`).
- The plugin picks its action-code table (6.8) from `mscoreVersion` at hello time.

### 3.6 Verbs

| Verb | Args | Body in | Body out | PluginAPI used |
|---|---|---|---|---|
| `hello` | `proto=` `client=` | | | `mscoreVersion` `api:21`, `curScore` `api:11` |
| `ping` | | | | |
| `info` | | | `T`, `P`, `S`, `M`, `K` lines (3.7) | `title`/`metaTag` `api:36`, `parts` `api:70`, `staves` `api:69`, measures `api:66`, `Staff.key(frac)`/`timeSig(frac)` `api:69` |
| `fp` | `[<fromNo> <toNo>]` | | `H` lines | same walk as `read`, hashed in the plugin |
| `read` | `<startTick> <endTick> [<track>,...]` | | `M`, `C`, `R`, `A` lines | `Segment.tick/annotations/elementAt` `api:65`, `Chord` `api:63`, `Note` `api:60`, `DurationElement.duration/tuplet` `api:61`, `Tuplet` `api:64` |
| `write` | `<label> <startTick> <endTick>` | op lines (3.8) | read-back `C`, `R`, `A` lines for all tracks in range, or `err` after rollback | `startCmd`/`endCmd` `api:31`, `Cursor` `api:45-50`, `Note.tpc1/tpc2` `api:60`, `Selection.select` `api:80`, `cmd` `api:17` |
| `undo` | `<startTick> <endTick>` | | read-back of the range | `cmd(UNDO)` with version code `deep:60` |
| `select` | `<startTick> <endTick> <startStaff> <endStaff>` | | | `selectRange` `api:81` |
| `export` | `<ext> <path>` | | | `writeScore(curScore, path, ext)` `api:14` **[spike]** |
| `open` | `<path>` | | | `readScore(path)` `api:13` **[spike]** |
| `appendMeasures` | `<n>` | | | `appendMeasures` `api:33`, only inside `write` (6.11) |

Reserved for later layouts, not in v1: `mute <partIdx> <0|1>` via writable `Channel.mute` (`api:71`); `addPart`/`removePart` via `appendPart`/`removeParts` (`api:34`), both for layout A (`notes:144`).

Verbs the API cannot support and that are therefore absent: list open scores (`api:127`), new score (`api:128`), silent open (`api:129`), write or close a non-current score (`api:130`), insert or remove measures (`api:132`), `cmd()` with arguments (`api:134`), playback state (`api:109`), change events (`api:126`).

As built in slice 2 (protocol 2, plugin 0.2.0): `write <startTick> <endTick> <label...>` takes the label last, so it may contain spaces; `undo` and `redo` take no range and return only `ok`, and the server reads the range itself; a new verb `color <startTick> <endTick> <track,...> <#rrggbb> <label...>` sets the colour of every note and rest of those tracks as one undo step, for `keep` (7.1). Not built yet: `fp`, `select`, `export`, `open`, `appendMeasures`.

### 3.7 Read body: raw event lines

The plugin emits one line per API object it visits. Field order is fixed; unknown trailing fields are ignored by the server so fields can be added without a protocol bump.

```
T <title>                                      metaTag("workTitle")           api:36
P <partIdx> <startTrack> <endTrack> <instrumentId> <longName>                 api:70
S <staffIdx> <partIdx> <clefType@0> <lines>                                   api:69
M <no> <irregular> <tick> <ticks> <actN>/<actD> <nomN>/<nomD>                api:66, src:85
K <tick> <staffIdx> <key>                      Staff.key(frac) at bar start   api:69
C <tick> <track> <z>/<n> [T<a>:<b>] [G<noteType>] [!<artic>,..] <note>[,<note>..]
R <tick> <track> <z>/<n> [T<a>:<b>]
A <tick> <track> <kind> <text>
H <no> <hash>
```

- `C` is a chord (one or more notes at one onset in one voice). `<note>` is `<pitch>:<tpc1>:<tpc2>[:b][:f]`: MIDI pitch, concert tonal pitch class, written tonal pitch class, tie-back flag, tie-forward flag. The pitch is the sounding pitch: `Note.pitch` excludes octave lines, so the plugin adds `Staff.pitchOffset(tick)` (since 4.6); without it, 8va passages read an octave low (slice 1, compared against the engine's N1 of the nocturne). A write under an octave line must subtract the offset again. Sources: `Chord.notes` (`api:63`), `Note.pitch/tpc1/tpc2/tieBack/tieForward` (`api:60`). The tonal pitch class is what distinguishes C sharp from D flat, which harmony analysis needs and which MIDI pitch alone loses (`notes:173`); the engine keeps spelled pitch (`engine:11`).
- `<z>/<n>` is `DurationElement.duration` as numerator and denominator (`api:61`); `T<a>:<b>` is `Tuplet.actualNotes:normalNotes` (`api:64`, there is no ratio property). `G<noteType>` marks a grace note by `Note.noteType` (`api:60`); grace chords come from `Chord.graceNotes` (`api:63`) and are emitted before their parent chord with the parent's tick.
- `!<artic>` lists `Chord.articulations` by name (`api:63`). Carried in the raw format for later use; not in N1x v1 (4.2).
- `A` kinds: `dyn` (`dynamicType`), `harm` (`harmonyType` plus `text`), `text` (staff text), `tempo` (`tempo`, `text`), all from `Segment.annotations` as generic items with those properties (`api:59`, `api:65`), typed by `ScoreElement.name` (`api:58`). Lyrics (`ChordRest.lyrics`, `api:62`) are not emitted in v1.
- `M` carries `no` and `irregular` (`api:66`). The on-screen number is `no + 1`, `noOffset` is already folded into `no`, and an irregular bar does not advance the count, so a pickup shares its `no` with the bar after it and the server labels it bar 0 (`src:85-86`, `src:90`). Confirmed against the screen in spike 5.
- Ticks are integers (`Segment.tick`, `api:65`); the server converts to quarter-note offsets with the `division` constant (`api:21`), which is sent once in `info`.
- Transposing instruments: the server derives spelled sounding pitch from `pitch` and `tpc1` (concert), matching the engine, which analyses at sounding pitch (`engine:11`); `tpc2` is kept so a write-back can set both.

**Fingerprint `H` lines.** There is no change signal: `scoreStateChanged` is declared but never emitted anywhere in the repository (`api:9`, `api:126`), and the claim that it works was refuted 0-3 (`deep:150`). The fallback named in the notes is polling or a "check now" (`notes:183`). Reflets does "check now" on demand: at each tool call the server requests `fp`, compares per-measure hashes with its cache, and re-reads only the measures that changed. That meets the no-full-re-reads target (`plan:12`). The hash is djb2 over the measure's `C`, `R`, `A` lines across all tracks, computed in the plugin so only one short line per bar crosses the socket. **[spike]** time the `fp` walk on a 300-bar orchestral score; it runs on MuseScore's UI thread.

### 3.8 Write body: ops

Writes are sequential per voice and bar, in note-entry order, because the cursor only lands reliably where its track already has content and advances by itself after each entry (`src:35`, `src:43-44`, `src:56`).

```
v <track> <barTick>            start a voice pass: land at the bar in voice 1 of the staff, then switch to <track>
d <z>/<n>                      duration for the entries that follow
n <note>[,<note>..]            chord at the cursor, <note> = <pitch>:<tpc1>:<tpc2>; advances the cursor
r                              rest at the cursor; advances
t <a>:<b> <z>/<n>              tuplet of a:b over total duration z/n, followed by its n and r entries
a <track> <tick> <kind> <text> dyn | harm | text, after all voice passes
~ <track> <tick> <pitch>       tie the note at (track, tick, pitch) forward, last
g <track> <tick> <kind> <note> grace note on the chord at (track, tick); kind is the action code
                               (acciaccatura, appoggiatura, grace4, grace16, grace32, grace8after, ...)
```

Execution order inside one `write`: the `v` passes in track order, each a run of `d`, `t`, `n`, `r` lines that must fill the bar exactly (`src:58`); then a spelling pass that revisits each written chord by tick to set `tpc1` and `tpc2` (`src:59`); then `a`; then `~` last, because a tie needs both notes to exist (6.5). The server compiles N1x into this list; the plugin never parses music, only ops.

As built in slice 2: `n <tick> <pitch>:<tpc1>[,...]` and `r <tick>` carry the tick the server computed, so the spelling and colour pass finds each chord by tick, not from the cursor. The plugin keeps the instrument's transposition when spelling (`tpc2 = tpc1 + (old tpc2 - old tpc1)`) and subtracts `pitchOffset` (3.7); the transposition part is untested, since the test score is for piano. Live test: `tests/live_write.py`. Order: voice passes, spelling and colour, `g`, `~`. `t` and `a` are not compiled yet: ideas with tuplets, dynamics or chord symbols are refused.

### 3.9 Error codes

`no-score` (`curScore` null, `api:11`), `bad-request`, `unsupported` (verb not available on this version), `write-failed <opIndex> <why>` (rolled back), `verify-failed <firstMismatch>` (rolled back), `export-failed`, `open-failed`. Every `err` on `write` means `endCmd(true)` was called and the score is as it was (`api:31`).

### 3.10 Sizes

The server reads in windows of bars (4.4), so one response is one frame of at most a few thousand lines. The 38-bar Chopin nocturne, 1,253 notes, is about 1,300 `C` lines in this format; the N1 version of the same bars is 5,796 characters (`plan:54`). No chunking protocol is needed in v1.

## 4. Protocol B: model to server (N1x)

### 4.1 Base: N1

The engine's N1 note list (`engine/notes.py`) round-trips through `encode`/`decode` (`engine:75`), keeps spelled pitch, staff and voice, grace notes, ties, chords, bar numbers including a pickup, bar length, meter changes and the first key signature (`engine:61-65`), and is stdlib-only by design so the model's environment can import it (`engine:17`). On the Chopin measurement it is 5,796 characters against 58,745 for minified JSON-per-note and 509,478 for MusicXML (`plan:49-54`). The directional evidence that compact text beats event-per-token formats is ABC at about 38% of MIDI-event token length (`deep:116`), with the caveat that Reflets must measure its own encoding with Claude's tokenizer on polyphonic scores (`deep:121`).

### 4.2 Extensions: N1x

N1 drops rests, part identity, clefs, key changes, slurs, dynamics, articulations, lyrics, chord symbols and tuplet markup (`engine:68-71`). N1x carries every element a MuseScore user can read and write (open question 17), as additions to N1's grammar (`src:94-95`). Plain N1 stays valid for its existing callers (`src:100`); the header tag `N1x` marks the extended text. Decided 2026-10-19 with the owner after the element survey (`research/musescore-4.7.5-element-coverage.md`) and the compression study (`research/encoding-compression-2026-10-18.md`); not built yet.

Illustration (the nocturne's opening; slur and pedal placement is made up):

```
N1x div=48 ts=12/8 ks=3f
title="Nocturne Op.9 No.2" composer="Chopin"
P1 "Piano" staves=1-2 instr=piano
m0 len=24
1.1: q60 s"Andante" x"espress. dolce" !p 24 Bb4
2.1: 24 r
m1 len=288
1.1: ( 72 G5~ 24 G5 F5 G5 ) ( 72 F5[ten] 48 Eb5 24 Bb4 )
2.1: ped( 24 Eb2 G3+Eb4 Bb3+Eb4+G4 ped)@72 ped( 24 Eb3 ...
m9 = m1
```

**Header lines**, after the version line: `title="…"`, `composer="…"` (score metadata), and one `P<n> "<name>" staves=<a>-<b> instr=<instrumentId>` per part. Quoted text escapes `"` as `\"`.

**Bar line fields**, on the `mN len=` line: `ts=` and `ks=` where the meter or key changes (open question 12); `rep=start|end|both` and `x=<count>` for repeats; `volta=1` or `volta=1,2` on each bar under an ending (consecutive bars with the same value are one volta); `bar=double|final|dashed|…` for a bar line the user set; `break=line|page|section`; `jump=<type>` (D.C., D.S. al Coda, … by MuseScore's jump type) and `mark=segno|coda|fine|tocoda|…`.

**Marks at a moment**, written just before the note or rest they fall on, or after a note with `@<offset>` (in `div` units from the bar start) when they fall inside it (open question 18): `!mf` dynamic, `"G7"` chord symbol, `x"…"` expression, `s"…"` staff text, `S"…"` system text, `q60` or `q60"Andante"` tempo in quarter notes per minute, `R"A"` rehearsal mark, `fb"6/4"` figured bass, `pt"pizz."` playing technique, `clef=bass` clef change. Tempo, rehearsal marks, system text, jumps, markers and voltas are system objects that MuseScore keeps on track 0, so they appear in staff 1 voice 1.

**Lines** with a start and an end, in the voice line of their track: `( … )` slur; `<( … <)` crescendo and `>( … >)` diminuendo hairpin; `cresc( … cresc)` and `dim( … dim)` text lines; `ped( … ped)` pedal; `8va( … 8va)`, also `8vb`, `15ma`, `15mb`, `22ma`; `tr( … tr)` trill line; `vib(`, `lr(` (let ring), `pm(` (palm mute); `line"text"( … line)` text line. An opener goes before the note the line starts on; a closer after the note it ends with (the line ends at that note's end), or with `@<offset>`. Lines may cross bars. Pitches stay sounding pitches under octave lines.

**Decorations of a note or chord**, in brackets right after it: `G5[stacc,acc]`, `Eb4+G4[arp]`. Short names for the common ones (`stacc`, `staccis`, `ten`, `acc`, `marc`, `port`, `fermata`, `breath`, `caesura`, `arp`, `arp-up`, `arp-down`, `tr`, `mord`, `prall`, `turn`, `trem8` to `trem64`, `lv`, `paren`), MuseScore's own symbol name for any other (`[articStressAbove]`), so nothing is lost. Engraving choices appear only where the user changed MuseScore's default: `up`/`down` stem, `beam=none|start|mid|…`, `head=x|…`, `staff+1`/`staff-1` cross-staff. Grace types other than the default (a single grace is an acciaccatura, a group 16ths) go on the grace token: `gD5[appog]`, `gD5[after]`. Fingering goes on the note: `C4'1+E4'3+G4'5`.

**Groups**: braces group notes. Brackets before the braces apply to every note inside, written once (open question 21): `[stacc]{ 12 C4 D4 E4 F4 }`; a note can add its own: `D4[acc]`. A ratio before the braces makes the group a tuplet, with durations inside still in `div` units of actual time: `3:2{ 16 C5 D5 E5 }`, `3:2[acc]{ … }`. Explicit ratios keep tuplets from being rewritten as dotted values.

**Lyrics**, one line per verse under the voice line, one syllable per note in order, grace notes and rests skipped, ABC style: `1.1 L1: Ah vous di- rai- je`. A trailing `-` continues the word, `_` holds the previous syllable over one more note, `*` skips a note.

**Repeated bars** (open question 20): `mN = mK` for a bar identical to bar K in every voice and mark, `s.v = mK` for one voice. K is always a bar written out in full within the same text. No transposed references, relative octaves, repeat groups or pitch shapes (open questions 20, 21). Spelling stays `Bb4` (open question 19).

**In ideas**: a voice line replaces everything in that voice for that bar: notes, rests, decorations, marks and the lines that start or end in it, so the read-back shows exactly what was written. A line that holds only marks, with no durations, notes or rests, changes those marks and leaves the notes alone. A system object is rewritten only through staff 1 voice 1.

**Read but not written** (the plugin API cannot, `research/musescore-4.7.5-element-coverage.md`): glissando, two-chord tremolo and chord lines (`[gliss]`, `[trem2]`, `[fall]` and the like are refused in ideas, with the reason), instrument changes with a real instrument (only the label could be added), fretboard diagram dots and harp pedal states. Bar lines other than repeats and key changes on transposing staves are partial; title and composer are written outside the undo step, so `discard` cannot remove them.

Rules for N1x:

- It lives next to `notes.py` in the engine, stdlib-only (`engine:17`), with a round-trip test in the style of `tests/test_notes.py` (`engine:75`).
- `decode` returns a `ScoreIndex` via `from_measures` (`engine:8`, `engine:48`), so `part_writing.check`, `draft.build`, `harmony` and `reduce.as_text` run on it unchanged (`engine:50-55`); the new elements live in additive fields.

### 4.3 One grammar for reading and writing

The model writes an idea as an N1x fragment for a bar range and a part. The server decodes it, validates it against the score's meter and part layout, and compiles it to Protocol A ops. A parse error is returned as `ToolError` naming the offending token and bar (`hosts:50`). Using the read format as the write format means the model has seen hundreds of examples of the grammar before it writes, and the tool description does not have to teach a second language. This follows the research conclusion to put verbosity into a compact encoding and a batched write mini-DSL rather than into many tools (`deep:112`).

As built in slice 2: ideas are plain N1 (`engine.notes.decode`), no engine change. Each voice line replaces that voice in that bar; voices and bars not written are untouched; a voice line of rests only empties the voice, and silence at the end of a line becomes rests. Durations that note entry cannot take in one value are split into tied notes; durations needing a tuplet are refused. N1 has no grace type, so a single grace is written as `acciaccatura` and a group as `grace16`; grace chords are refused. A tie needs the next note of that voice, in the idea, back to back on the same pitch. `len=` must equal the score's bar.

### 4.4 Read windows and the token budget

- Claude Code warns at 10,000 tokens of MCP output and caps at 25,000 by default (`hosts:41`); results over 50,000 characters are written to a file instead (`plan:69`).
- Measured density: about 1,700 tokens for 38 bars of dense two-hand piano (`plan:54`), so roughly 45 tokens per bar at that texture. The server estimates tokens as characters / 3.5 (`plan:56`), returns the whole score when the estimate is under 6,000 tokens, and otherwise returns the first 16 bars with a one-line notice of the total. A request estimated over 18,000 tokens is refused with a suggestion to narrow the bar or part range. Real counts are measured with the token-count API during implementation (`plan:56`, `deep:121`).
- `read_score(since=<fp>)` returns only bars whose fingerprint changed since the last read, for the "check what I've written so far" loop (`notes:185`).

### 4.5 Positions

Bars and beats in model-facing text follow the engine's `Finding(bars, beats, ...)` and `Position`/`NoteRef` conventions (`engine:85`, `engine:23`), with a pickup numbered 0 (`engine:7`). Bar numbers must equal what the user sees in MuseScore; the server computes them from `Measure.no`, `noOffset` and `irregular` (`api:66`). **[spike]** verify against the on-screen numbers with and without a pickup.

## 5. MCP tools

Constraints from the research: fewer than ten compact tools, three to five marked always loaded, since Claude Code defers all MCP tool schemas behind tool search by default (`deep:112`, `hosts:42`); upfront descriptions and server instructions are cut at 4,096 characters, deferred descriptions at 16,384 (`hosts:42`); tool names over 128 characters are dropped (`hosts:45`); 58 tools cost about 55,000 tokens before the first message, which is the failure mode to avoid (`deep:105`).

### 5.1 The eight tools

| Tool | Always loaded | Read-only | Purpose |
|---|---|---|---|
| `score_info` | yes | yes | Connection state, MuseScore version, title, parts with staves, bar count, meter and key, current fingerprint. Also the health check. |
| `read_score` | yes | yes | N1x for a bar range and optional part filter; `since=` for changed bars only. |
| `check` | yes | yes | Rule-based critic on a bar range: the ten voice-leading rules (`engine:79`) and the beat-by-beat notes table (`engine:18`), as text. |
| `propose` | yes | no | Write an N1x idea into the score, in place as one undo step or as a new tab (section 7). Returns the read-back summary and a proposal id. |
| `discard` | no | no | Undo the last Reflets proposal if the score has not changed since (6.9). |
| `render` | no | yes | Engrave a bar range to PNG through the engine, with optional annotations (`engine:24-25`). Needs `export` (section 7.3). |
| `analyze` | no | yes | Notes table and, when the optional model environment is installed, the harmony draft (`engine:22`, `engine:57`). |
| `doctor` | no | yes | Diagnostics: plugin file present in the plugin folder (`api:113`), port reachable, MuseScore version, WebSocket API present (`deep:17`), engine extras installed. |

Four always loaded, within the three-to-five guidance (`deep:112`). `_meta["anthropic/alwaysLoad"]: true` on those four (`hosts:42`). Tool annotations set `readOnlyHint` on the six read tools so Codex's `writes` approval mode prompts only for `propose` and `discard` (`hosts:10`). `anthropic/requiresUserInteraction` is not set on any tool, since it forces a prompt on every call (`hosts:43`).

Results are plain text, not `structuredContent`, because structured output is validated against a schema and costs tokens for keys (`hosts:50`); the N1x text is the structure. Errors the model should act on are raised as `ToolError` (`hosts:50`).

### 5.2 Tool contracts

**`score_info()`** → one short paragraph:

```
MuseScore 4.7.5, Reflets bridge 0.1, connected.
"Nocturne in E flat" — 2 parts: P1 Piano (staves 1-2). 38 bars, 12/8, E flat major, pickup: no. fp=3f9a.
```
When not connected, the same text explains what to do and the other tools are not needed.

**`read_score(bars="1-8", parts="P1", since=None)`** → N1x. Defaults as in 4.4.

**`check(bars="1-8", parts=None, rules="voice-leading")`** → the engine's `part_writing.as_text` findings grouped into numbered spots with bar and beat (`engine:85`), preceded by the notes table for the range (`engine:18`). The voice-leading checker applies only to two to four single-line voices with at least 60% shared onsets (`engine:81`); when it does not apply, the tool says so in one line rather than returning silence. Requires the `[checks]` extra (music21, `engine:153`); without it the tool returns the notes table and a one-line install hint.

**`propose(idea, mode="in_place", label="idea 1", replace=False)`** → text:

```
Written: bars 5-8, P2, 23 notes, 2 rests, 1 tie, as one undo step "Reflets: idea 1". Read-back matched.
Press Play in MuseScore. Call discard("p3") to remove it, or keep working.
proposal id: p3
```
`idea` is N1x for the target bars and parts. `mode="new_tab"` follows 7.3. `replace=True` is required when the target cells are not rests (6.4).

**`discard(proposal_id)`** → confirms the undo, or refuses with the reason (6.9).

**`keep(proposal_id)`** → turns the idea's notes black as their own undo step, `Reflets: keep <label>`, and closes the proposal (7.1). Added in slice 2, owner decision 2026-10-18; nine tools in all. As built, `propose`, `read_score` and `score_info` are always loaded; `discard` and `keep` are deferred.

**`render(bars, parts=None, annotations=None)`** → path to a PNG the harness can open, plus one line of text. Large outputs go to a file anyway (`plan:69`).

**`analyze(bars)`** → notes table and harmony draft text (`engine:57`).

**`doctor()`** → a checklist with pass or fail per line.

### 5.3 Server instructions

The MCP server instructions, under 4,096 characters (`hosts:42`), carry: one paragraph on what Reflets is, the workflow (`score_info` → `read_score` → `check` → `propose` → the user listens → `discard` or keep), and a twenty-line N1x cheat sheet. Tool descriptions stay under about 1,500 characters each and refer to the cheat sheet.

### 5.4 Idle token cost target

| Item | Budget |
|---|---|
| Server instructions | about 1,000 tokens |
| Four always-loaded descriptions | about 1,500 tokens |
| Four deferred descriptions | 0 until searched (`hosts:42`) |
| One `read_score` of 16 bars of piano | about 700 tokens (`plan:54`) |

Against 55,000 tokens for a 58-tool setup (`deep:105`). Measured during implementation with the token-count API (`plan:56`).

### 5.5 Host registration

- Claude Code: `.mcp.json` at the project root, with an approval prompt on first use (`hosts:35`), or `claude mcp add -s user reflets -- reflets-server` (`hosts:36`). Headless test runs use `--mcp-config` with `--strict-mcp-config` and `--allowedTools "mcp__reflets__*"` (`hosts:37`, `hosts:39`).
- Codex CLI and the Codex surface in the ChatGPT desktop app: `codex mcp add reflets -- reflets-server` (`hosts:20`), `[mcp_servers.reflets]` with `startup_timeout_sec` default 10 (`hosts:19`). The ChatGPT chat product itself cannot reach a local server (`hosts:8`, `hosts:13`).
- Claude Desktop: `claude_desktop_config.json` on macOS and Windows; the Linux path is undocumented (`hosts:28`). Server stderr lands in `mcp-server-reflets.log` (`hosts:28`), so the server logs to stderr and never to stdout (`hosts:50`, `hosts:52`).

## 6. Write path

### 6.1 Preconditions, checked in the server

- Connected and a score open (`api:11`).
- The target bar range exists. Bars beyond the end can only be appended, never inserted (`api:33`, `api:132`); `propose` appends when the idea runs past the last bar and says so in its result.
- The target tracks exist in `info` (`api:70`).
- The idea's durations fill each bar exactly under the bar's actual meter (`api:66`), with tuplets that do not cross a bar line (`api:49` rejects cross-measure tuplets).
- Every tick the plugin will rewind to lies inside the score: `rewindToTick` has no null check on the segment it finds (`src:34`, `src:61`).

### 6.2 Snapshot

Before writing, the server `read`s the full tick range across all tracks. This pre-snapshot serves the read-back comparison (6.6) and `discard` (6.9).

### 6.3 One undo step

```
score.startCmd("Reflets: <label>")       api:31
  ... ops ...
  ... read back ...
score.endCmd(false)   on match           api:31
score.endCmd(true)    on any failure     api:31  (rollback)
```

`startCmd` locks the undo stack so every change, including those made through `cmd()`, commits as a single command, and `endCmd(true)` rolls back (`api:31`). This is what makes "discard = one Ctrl+Z" true for layout B (`notes:146`).

Commands dispatched inside the lock that open their own `startCmd`/`endCmd`, such as the tie toggle, add nothing at that level because both calls return at once while the stack is locked (`src:65`), so the whole write stays one macro. `endCmd` also forces a rollback when an engraving error is set (`src:67`).

### 6.4 Placing notes and rests

Per `v` pass (one voice, one bar):

1. `cursor = score.newCursor()` (`api:39`). Leave `inputStateMode` at `INPUT_STATE_INDEPENDENT`, the default (`api:46`); in that mode the cursor has its own input state (`src:37`). `INPUT_STATE_SYNC_WITH_SCORE` plus `staffIdx` was reported to write to the wrong staff because it shares the GUI's live input state (`deep:81`, **[reported]**); the research's recommendation is independent mode with an explicit track (`deep:89`).
2. Land: `cursor.track = <staff> * 4` (voice 1 of the target staff), then `cursor.rewindToTick(<barTick>)` (`api:45`). `rewindToTick` moves on to the first segment that has an element in the cursor's track (`src:34-35`), and voice 1 always has a chord or rest at the bar's first segment, so the cursor is now on the bar start. Then `cursor.track = <track>`, which changes the track without moving the segment (`src:36`); if that voice is empty, note entry fills it with rests (`src:51`, `src:57`).
3. For each entry: `cursor.setDuration(z, n)` on a `d` line (`api:49`; an invalid duration silently becomes a quarter, `src:33`, so the server validates first); `cursor.addNote(pitch)` for the first note of an `n` line and `cursor.addNote(pitch, true)` for each further chord member, which joins the chord just written (`src:42`, `src:60`); `cursor.addRest()` for `r` (`api:49`). After each `addNote` or `addRest` the cursor's own input state advances to the next input position (`src:43-44`), so the next entry lands after it.
4. `t`: `cursor.addTuplet(ratio, duration)` (`api:49`) at the current position, then its `n` and `r` entries; cross-measure tuplets are rejected (`api:49`).

Spelling pass, after all voice passes: for each chord written, find its segment by tick (`findSegmentAtTick`, `api:33`), take `elementAt(track)` (`api:65`), its `notes` (`api:63`), and set `tpc1` and `tpc2` (`api:60`, writable). `cursor.element` cannot be used for this: after `addNote` the cursor already sits on the next position (`src:43`, `src:59`).

Existing content: `addNote` overwrites. Note entry carves a gap of the requested duration out of whatever the voice holds and never inserts time (`src:48`). A duration longer than the remaining bar spills into the next bar with an automatic tie (`src:50`), which is why 6.1 requires exact bar fills. Policy: `propose` requires `replace=True` when the pre-snapshot shows anything but rests in the target cells; the read-back (6.6) checks the result either way.

Grace notes are written in v1 (decided 2026-10-18, spike round 5, `research/spike-bridge-hello-2026-10-18.md`): there is no cursor entry for them (`api:49`), so per `g` op, after all voice passes and the spelling pass, the plugin selects the main chord's first note, dispatches the grace action, and sets `pitch`, `tpc1`, `tpc2` on the new grace note, which MuseScore creates at the main note's pitch. New graces before a note are inserted at the front of `graceNotes`, so the server emits a note's before-graces in reverse order. Like ties, this needs the dialog-free plugin (2.1).

### 6.5 Ties

There is no API to create a tie: `Cursor::add` has no TIE case, `tieBack`/`tieForward` are read-only, and `newElement(TIE)` plus `cursor.add` crashed MuseScore 4.6.5 (`deep:70`). The only path is `cmd("tie")` over a selection, which toggles (`deep:70`). Procedure per `~` op, after all notes exist:

1. The server emits `~` only when it has written both the note and a same-pitch successor in the same part and staff, since that is what `searchTieNote` looks for (`src:76`), and because 4.7.5 falls back to adding a brand-new tied note when a lone selected note has no successor (`src:74`).
2. Find the note at (track, tick, pitch) from a fresh read; `selection.select(note)` (`api:80`; the call is refused if the selection is locked or the element type cannot be recorded, both reported as `write-failed`). A single selected note gives the tie command exactly that note (`src:72`).
3. Read `note.tieForward` (`api:60`). If already set, skip the command: the toggle would remove it (`deep:70`, `src:73`).
4. `cmd("tie")` (`api:17`); the code is `tie` on 4.4.4, 4.6.2 and 4.7.5 (`src:15`). Confirmed on 4.7.5 inside `startCmd`, one undo step with the notes, **only when no plugin dialog is open** (2.1, `research/spike-bridge-hello-2026-10-18.md`). The command's own `startCmd`/`endCmd` are no-ops under the plugin's lock (`src:65`), so the tie stays inside the one undo step; the same core logic exists on 4.4.4 (`src:75`).
5. Re-read `tieForward`. If still null, `verify-failed` → rollback. Direct Tie creation is never attempted (`deep:77`).

Selection inside an active command: `select(e)` has no undo-stack guard, only the lock and type checks (`api:80`, `api:84`); the claim that `selectRange` is refused inside `startCmd` was refuted 0-3 (`deep:175`). `selectRange` inside a command is applied deferred by tick (`api:81`), which is why ties use `select(note)`, not `selectRange`.

### 6.6 Read-back verification, inside the command

After the ops, the plugin re-walks `[startTick, endTick)` on **all** tracks, not just the target (`deep:89`: a target-only read-back can confirm a wrong write). The server compares against the expected state: pre-snapshot with the target tracks' cells replaced by the idea. Any difference, including on a non-target track, is `verify-failed`, and the plugin calls `endCmd(true)`. This is the only correctness signal available, because `cmd()` dispatches any string unmapped and an unknown action is a silent no-op (`api:17`, `deep:66`, `plan:64`), `setDuration` silently substitutes a quarter (`api:49`), and `addNote` may land on the wrong staff (`deep:81`).

The read-back is of the score model, not the layout, so `doLayout` (`api:32`) is not required for it; `endCmd` notifies the notation of the change (`api:31`). **[spike]** confirm that annotations added with `undoAddElement` are visible to `Segment.annotations` before `endCmd`.

As built in slice 2: the plugin commits with `endCmd(false)` and returns the read-back; the server compares it with the expected state and, on a mismatch, sends `undo` and checks the range is back to the pre-snapshot. Comparing inside the command would need the expected state in the plugin, against 2.3; the undo path is the one `discard` already depends on. Compared per (bar, track): pitch, concert tpc, written duration, tie flags, grace type and order, and every `A` line. One expected difference is allowed: a tie running into or out of the idea from a bar outside it is cut, because its note was replaced; the result says so. A plugin exception rolls back with `endCmd(true)` and returns `write-failed <op> <why>`.

### 6.7 Annotations

Per `a` op: `newElement(type)` (`api:18`), position the cursor (6.4 steps 1 to 2), `cursor.add(el)`, which routes Harmony, Dynamic and StaffText through the default `undoAddElement` path (`api:50`), then set `text`, `dynamicType` or `harmonyType` (`api:59`). Dynamics need both, text first: `dynamicType` alone gives the right type and velocity but empty, invisible text; `text` alone shows "mf" but leaves `dynamicType` at 0 (OTHER) (spike, `research/spike-bridge-hello-2026-10-18.md`). Chord symbol text set after `cursor.add` did not crash on 4.7.5. Text is set **after** insertion because chord symbols crashed when text was set before (`notes:169`, **[reported]**). Verified by the `A` lines in the read-back.

### 6.8 Version-branched action codes

The table lives in the plugin, selected by `mscoreVersion` (`api:21`) at hello, and is echoed to the server so unknown versions are refused up front.

| Action | 40402 to 40699 | 40700 and up | Source |
|---|---|---|---|
| undo | `undo` | `action://notation/undo` | renamed in 4.7; plain `undo` is a silent no-op there (`deep:60`, `src:13`); mcp-score branches by version (`deep:60`) |
| redo | `redo` | `action://notation/redo` | same rename (`src:14`) |
| tie | `tie` | `tie` | unchanged at all three tags (`src:15`, `src:23`) |
| append-measures | `append-measures` | same | unchanged (`src:18`); used by 6.11 if `appendMeasures` ever needs the action path |
| file-export | `file-export` | same | unchanged (`src:20`); fallback route if `writeScore` fails (7.3) |
| play, stop | `play`, `stop` | same | unchanged (`src:19`); not used by the core, reserved for the playback-check idea |

With the 4.7 floor (2.5) only the right column is used; the left stays as a record of why older versions are refused. Only undo and redo need the branch; everything else the core dispatches is stable from 4.4.4 to 4.7.5 (`src:25`). Every `cmd()` is still followed by a read-back (6.6), so a wrong code fails loudly instead of silently.

### 6.9 Discard

`discard(p)`:

1. Re-read the proposal's range. If it differs from the post-write read-back stored with `p`, the user has edited since; refuse, and tell the user to use Ctrl+Z themselves. Undo would otherwise remove their edit.
2. `undo` verb → `cmd(UNDO)` with the version code (6.8), outside any `startCmd`.
3. Read back; it must equal the pre-snapshot, else report a mismatch and stop (the code may have been a silent no-op, `deep:60`).

As built in slice 2: when step 3 fails, the last undo step was something else, such as an edit the user made elsewhere in the score after the idea; the server sends `redo` to put it back, checks the range equals the post-write state again, and tells the model the user can remove the idea with Edit > Undo. Tested live: an idea in bar 10 written after an idea in bars 5-6 survives a discard of the older one.

### 6.10 Highlighting

After `endCmd`, `select <startTick> <endTick> <startStaff> <endStaff>` runs `selectRange` (`api:81`) so the user sees where the idea landed. Done after the command, since inside one it is deferred (`api:81`). Not part of correctness.

### 6.11 Appending bars

When the idea extends past the last bar, `appendMeasures(n)` (`api:33`) runs inside the same command so the append is part of the one undo step.

### 6.12 Not written in v1

Slurs and hairpins, which fall through `cursor.add` with no spanner handling (`api:50`); lyrics; articulations; key and time changes mid-idea (possible through `cursor.add` of KeySig and TimeSig, `api:50`, deferred); clefs; bar lines (`notes:169`); parts and staves (`api:34`, reserved for layout A).

Superseded 2026-10-19 by open question 17: everything in 4.2 is written in v1 except the kinds listed there as read only. Each kind's write path (properties, `newElement` plus `cursor.add`, `Chord.add`/`Note.add`, or an action over a list selection) is in `research/musescore-4.7.5-element-coverage.md`; parts and staves stay reserved for layout A.

### 6.13 Checkpoints and restore (first release, not built)

Decided 2026-10-18 (open question 16). MuseScore's undo history is linear, interleaves the user's edits with ideas, and is lost when the score closes, so it cannot take the user back to a chosen state after many rounds. Three parts:

1. **Checkpoint files.** The server asks the plugin to `export` the whole score (`writeScore`, confirmed on 4.7.5: 32 ms, no dialog, spike round 4) to a checkpoint file. Nothing is lost across sessions. Going back to a whole checkpoint means the user opens that file: the plugin cannot replace the open score (`readScore` refuted, 7.2).
2. **Restore bars from a checkpoint.** The server reads the checkpoint, compares it bar by bar with the current score, and writes the chosen bars back through the write path (section 6) as one undo step verified by read-back. Bars outside the request keep the user's later edits. It restores only what the write path can write; the checkpoint file covers the rest.
3. **Proposals and checkpoints persist on disk** next to the score, so a restart of the harness does not lose open ideas.

Open: whether checkpoints are named by the user, made automatically at each `keep`, or both. Comes after `check`, because restore is only as faithful as the write path (slice 3).

## 7. Ideas into MuseScore

Three layouts were sketched: A extra staves, B in place, C separate tab (`notes:140`, `notes:142-146`, `notes:148`). Decided 2026-10-18 after the spikes: **B only in the first release**; A later, for comparing several ideas, once adding and removing staves in one undo step is tested (`api:34`, `api:71`); **C dropped**, because `readScore` cannot open a tab (7.2) and a separate-window preview would be slow, re-imported through MusicXML, and invisible to the bridge.

### 7.1 In place (layout B)

UX additions decided with B: the idea's notes are coloured (writable `color`, in the same undo step) and set back to black on keep, in addition to the selection of 6.10; `discard` goes through Reflets, which refuses when the bars changed since the write (6.9), so a user edit made after the idea is never undone by mistake; "next idea" is a discard plus a new write.

As built in slice 2: idea notes, rests and grace notes are `#1565c0`; keep is the `keep` tool (5.2); the selection of 6.10 is not built.

`propose(mode="in_place")` → section 6 → the user presses Play (there is no playback API, `api:109`; the notes already assume the user presses play, `notes:184`) → keep by doing nothing, or `discard` (6.9), which is the one Ctrl+Z (`notes:146`).

### 7.2 New tab (layout C) with readScore and writeScore on a temporary file (dropped, kept as a record)

1. **Export the current score**: `export musicxml <tmp>/reflets-<uuid>.musicxml` → `writeScore(curScore, path, "musicxml")` (`api:14`; `musicxml` is a registered writer, `api:122`). The path is unique per call because the export goes through the export scenario, which may show overwrite dialogs (`api:14`). **[spike]** The 4.7.5 source implements it for the current score (`api:13-14`), but the handbook said readScore and writeScore were not functional in MuseScore 4 (`deep:38`), and the research asks for a prototype before depending on it (`deep:45`).
2. **Splice in the server**: parse the MusicXML with the standard library, replace the target part's bars with the idea, keep the other parts for context, optionally trim to the idea's bars plus two on each side, and write `<tmp>/reflets-idea-<uuid>.musicxml`. The engine's `ScoreIndex` is not needed for the splice; it is used afterwards to validate the result (`engine:9`).
3. **Open as a new tab**: `open <path>` → `readScore(path)` opens a real project in a new tab (`api:13`). Non-interactive open is not available (`api:13`, `api:129`). **Refuted on 4.7.5** (spike round 4, `research/spike-bridge-hello-2026-10-18.md`): with a score already open, `readScore` starts a second MuseScore process with the file and returns the old score; the bridge cannot see the new window. It loads into the bridge's window only when no score is open. **Layout C as written does not work; needs a redesign before implementation.**
4. **The idea tab is now the current score.** Every later `read`, `info` and `write` targets it, because the API only sees the current score (`api:11`, `api:127`). The server tracks this: `hello`/`info` return the title and fingerprint, and `score_info` says "current tab is the idea score" until the user switches back. `propose` refuses to write while the current score is an idea tab.
5. **Approve**: the user switches back to their score and the model calls `propose(mode="in_place")` with the same idea. **Discard**: the user closes the idea tab; the plugin can only close the current score (`api:15`, `api:130`), so the server never closes tabs on the user's behalf.

File paths across WSL2 and Windows: mirrored networking shares `127.0.0.1` (`plan:37`, `rig:27`) but not paths. The server setting `REFLETS_TMP` names a directory both sides can read; when the server runs in WSL and MuseScore on Windows it is under `/mnt/c/...` and the path sent in `open` is translated to Windows form. `readScore` reads any path (`api:13`); `writeScore` goes through the export scenario rather than the `FileIO` path guard (`api:14`, `api:20`). **[spike]** whether the export scenario restricts the destination.

### 7.3 Shared with render and analyze

`render` and `analyze` use the same `export` step because engraving and annotation need MusicXML bytes (`engine:24-25`, `engine:59`). If `writeScore` turns out not to work on some version, the fallback is to ask the user to save and run the MuseScore command line on the saved file (`rig:34`); no plugin can be run from the command line (`api:120`, `rig:19`), so the fallback only sees the last saved state.

## 8. Server internals

- Package `reflets` with a `reflets-server` console script; stdio transport; `MCPServer` from `mcp>=2.3` (`hosts:50`). Logging to stderr only (`hosts:52`; the SDK diverts stray stdout, `hosts:50`).
- Startup under one second, no network at import time (`hosts:19`).
- Connection manager as in 3.3 and 3.4, one request in flight, request ids per connection.
- Cache: raw `M`/`C`/`R`/`A` lines per measure keyed by fingerprint; `info` refreshed on each `fp` mismatch of the part or measure tables.
- Engine dependency tiers: core (index, N1x, notes table, harmony, engrave, render, export, no music21; `engine:152`); music21 for `part_writing.check` (`engine:153`, 114 MB, `engine:148`) is a required dependency of Reflets (open question 7), so `check` always works; the AnalysisGNN environment is a separate optional download (`engine:22`, `notes:67`).
- Settings: `REFLETS_PORT` (default 8731), `REFLETS_TMP`, `REFLETS_LOG`.
- Licence: plugin and server MIT; the plugin is written from scratch against the public API and does not copy the GPL-3.0 `dev_test_websocket` sample (`hosts:57`, `hosts:58`, `hosts:63`).

## 9. Verification constraints that shaped the design

The full strategy is pending in the plan (`plan:134`). The design already assumes:

- End-to-end tests against a real GUI MuseScore, because the WebSocket API is undefined in the console context (`deep:34`): the AppImage extracted with `--appimage-extract` (`rig:9`) under WSLg on `DISPLAY=:0`, where 4.6+ forces xcb unless `MU_QT_QPA_PLATFORM` is set (`rig:6`), with `LIBGL_ALWAYS_SOFTWARE=1` as the first flag to try (`rig:8`); or Xvfb as mcp-score does (`deep:93`). Windows runs by hand on the owner's 4.7.5 (`plan:16`, `plan:35`).
- Readiness is a successful `hello`, not the window appearing; a malformed plugin produces no error at all (`deep:56`).
- Independent checking of writes: save, then `mscore -o out.musicxml` under offscreen (`rig:34`) or `unzip -p score.mscz score.mscx` for a diffable XML (`rig:35`), compared with `musicdiff` (`rig:36`). Fixtures with planted errors, as the engine's tests do (`engine:100`, `engine:89`).
- Model-free driving through the Inspector CLI (`rig:40`) and the in-process SDK client (`rig:41`); model-in-the-loop through `claude -p --mcp-config --strict-mcp-config --allowedTools "mcp__reflets__*"` (`rig:42`), which draws on plan limits rather than per-run billing (`rig:43`).
- Any plugin change means restarting MuseScore and checking for a stale port holder (`deep:89`).

## 10. Spikes before implementation, in order

Status 2026-10-18 (owner's Windows 4.7.5, `research/spike-bridge-hello-2026-10-18.md`): 1 writeScore works (32 ms, no dialog); readScore opens a new process when a score is open, so 7.2 needs a redesign. 2, 3 (macro plugin only, 2.1), 7, 8 (on 4.7.5), 9 confirmed. 4: whole-score walk of 300 bars × 16 staves (38,400 notes) takes 214–238 ms on the UI thread and returns 971 KB; a 16- or 32-bar window takes 17 ms; the 38-bar nocturne takes 6–7 ms. 5: pickup and first full bar both have `no=0`, pickup `irregular=true`; not compared with the screen. 6: socket half confirmed; WSLg GUI not run. Annotation `text` comes back with MuseScore markup (`<sym>dynamicPiano</sym>`, `<font .../>`), which the server must strip.

These are the **[spike]** marks above. Each is a short experiment on the owner's Windows 4.4.3 and on 4.7.5 in the rig. They replace the first-spike list in the notes (`notes:179-185`, `notes:187`).

1. `writeScore(curScore, tmp, "musicxml")` with unsaved edits, and `readScore(tmp)` opening a new tab, on 4.4.3 and 4.7.5 (`api:13-14` versus `deep:38`). Decides section 7.2 and `render`. Also whether any dialog appears (`api:14`).
2. The write procedure of 6.4 on a real score: landing through voice 1 then `track`, an empty voice 2, an occupied bar, chord members through `addNote(p, true)`, and the spelling pass by tick. The source says it works (`src:56-60`); confirm on 4.4.3 and 4.7.5.
3. `cmd("tie")` after `selection.select(note)` inside `startCmd`, on both versions. The code is `tie` on all three tags and the toggle logic is read (`src:15`, `src:72-76`); confirm the tie shows in the read-back.
4. `fp` walk time on a 300-bar orchestral score (`api:126`). Decides whether on-demand fingerprinting is enough or needs a bar-range argument by default.
5. Bar numbers: the plugin's `no` and `irregular` against the screen, with a pickup (`src:85-86`, `src:88`, `src:90`).
6. The AppImage GUI under WSLg (`rig:5-9`) and the WSL to Windows socket with `nc -vz 127.0.0.1 8731` (`rig:30`).
7. Annotation `text` set after `cursor.add`, and visibility in `Segment.annotations` before `endCmd` (`notes:169`, `api:65`).
8. `api.websocketserver` present in the owner's 4.4.3 Windows build (`deep:17`).
9. Rows of the capability matrix with no surviving evidence: reading tuplets, grace notes, dynamics, chord symbols, part metadata; writing rests, tuplets, chord symbols, dynamics (`deep:136`). The read-back design catches failures, but the spike tells us what works at all.

## 11. Open questions for the owner

1. **Engine packaging.** Decided 2026-10-18: a dependency on the `sheet-music-plugin` package; engine changes Reflets needs are made there. Also decided 2026-10-18: during development Reflets uses a detached worktree of that repository's `main` (`../sheet-music-engine`), so its branch work can't change Reflets; engine changes are additive, keeping the hosted app's default output unchanged; a pinned git tag replaces the worktree for public release. Original question: import the engine from the `sheet-music-plugin` package as a dependency, or copy `engine/` into this repository (`notes:13`, `plan:20`)? The spec assumes an importable package named `engine`.
2. **Layouts.** Decided 2026-10-18: B only, A later, C dropped (section 7). Original question: B and C in the first release, A later (`notes:140`, `notes:142-146`, `notes:148`)? A needs `appendPart`, `removeParts` and `Channel.mute` in the plugin (`api:34`, `api:71`).
3. **Version floor.** Decided 2026-10-18: require 4.7 (2.5). Original question: support 4.4.2 and up, which keeps your 4.4.3 install in scope (`plan:35`) but means version-branched action codes (`deep:60`) and a three-version test matrix (`deep:93`), or require 4.7?
4. **Local security.** Decided 2026-10-18: shared token (2.2). Original question: the plugin binds all interfaces (`deep:6`). Document the firewall prompt only, or add a shared token the plugin writes to Documents/MuseScore4 with `FileIO` (`api:20`) and the server reads before `hello`?
5. **Port.** Decided 2026-10-18: 8731.
6. **What `check` covers in v1.** Decided 2026-10-18: ship with the current rules and say when they do not apply. Original question: The engine's voice-leading rules apply only to chorale-like textures (`engine:81`); melody-versus-accompaniment clash detection and voicing checks are new engine work (`notes:129`). Ship `check` with the current rules and say when they do not apply, or hold the tool until the new checks exist?
7. **music21.** Decided 2026-10-18: required. Original question: `check` needs the 114 MB `[checks]` extra (`engine:148`, `engine:153`). Required install, or optional with a hint?
8. **Codex.** Decided 2026-10-18: later, after Claude Code works. Original question: Document the Codex surface (CLI and the ChatGPT desktop app's Codex side) as a supported host in v1 (`hosts:13-14`)?
9. **Change detection.** Decided 2026-10-18: on demand only; reads are cheap (17 ms per 16–32 bar window, spike round 4). Original question: On-demand fingerprinting only, or also a timer in the plugin that raises a "changed" flag, at a UI-thread cost (`api:126`, `notes:183`)?
10. **Overwrite policy.** Decided 2026-10-18: refuse without `replace=True`. Original question: Should `propose` refuse to write over existing notes without `replace=True` (6.4), or always replace?
11. **Pending research.** Answered 2026-10-18: the report landed (`research/bridges-wire-protocols-and-roadmap.md`, summarised in the plan) and confirmed the design. Original question: the study of existing bridges' wire protocols and the MuseScore 4.8 roadmap was still running when the handoff was made (`plan:113`). Wait for it, or proceed with this design?
12. **Key changes.** Decided 2026-10-18: support them when reading: the plugin's `K` lines (3.7), a `ks=` on the bar header in N1x the way `ts=` marks meter changes, and a per-bar key in the engine's `ScoreIndex` (a change in `sheet-music-plugin`). Writing key changes in ideas stays out of v1 (6.12). Original question: The engine keeps only the first key signature (`engine:10`); N1x drops later ones too. Acceptable for v1?
13. **Grace notes in ideas.** Decided 2026-10-18: included in v1 (3.8, 6.4). Confirmed writable 2026-10-18 (spike round 5): select the main note, dispatch `acciaccatura`/`appoggiatura`/`grace4`/`grace16`/`grace32`/`grace8after`/…, then set the new grace note's `pitch`, `tpc1`, `tpc2`; one undo step with the idea. New graces before a note are inserted at the front, so the server adds them in reverse order. Original question: Not writable in v1 (6.4). Acceptable?
14. **Licence.** Decided 2026-10-18: MIT for both plugin and server (`hosts:63`).
15. **Keeping an idea.** Decided 2026-10-18: a `keep(proposal_id)` tool turns the idea's notes black as its own undo step (5.2, 7.1). Original question: idea notes are written in colour; how do they turn black once the user keeps the idea: a keep tool, recolouring on the next propose, or no colour for now?
16. **Going back after many iterations.** Decided 2026-10-18: in the first release, checkpoint files, restoring chosen bars from a checkpoint through the write path, and proposals and checkpoints kept on disk (6.13). Original question: with only MuseScore's linear undo history, how does a user who has made many additions and removals go back to a specific earlier state?
17. **What Claude can read and write.** Decided 2026-10-18: in the first release, Claude reads and writes every element a MuseScore user can read and write, not only notes, dynamics and chord symbols: per-note notation (articulations, ornaments, fingering, lyrics, noteheads, tremolos, arpeggios), lines (slurs, hairpins, pedal, octave lines, trills, voltas), text of every kind (expression, staff, tempo, rehearsal), fermatas and breaths, bar-level elements (bar lines, repeats, jumps, markers, key, time and clef changes). This widens 4.2 and 6.12; a feasibility survey of the 4.7.5 plugin API and a live spike decide how each kind is read and written, and any kind the API cannot write is listed with the reason. Measured cost on the nocturne (1,259 notes): about 160 per-note and line elements and 50 text elements, estimated at +10% and +3% on about 6,000 tokens; scores with an articulation on most notes cost more. Original question: N1x v1 carries dynamics and chord symbols only and drops articulations, slurs, hairpins, pedal, lyrics, clefs and text (4.2). Should Claude see everything in the score?
18. **A mark inside a held note.** Decided 2026-10-18: written after that note with `@` and its offset from the start of the bar in `div` units, e.g. `"Bb7"@72`. Original question: a dynamic or chord symbol is placed before the note it falls on; where does one go when no note starts there?
19. **Pitch spelling.** Decided 2026-10-18: keep `Bb4`, the simplest form; neither music21's `B-4` nor key-relative spelling. Original question: `B-4` saves 2–10% of Claude tokens in flat keys and key-relative spelling 3–17% (`research/encoding-tokens.md`); adopt either for N1x now that Reflets is Claude Code first?
20. **Compression.** Decided 2026-10-19: N1x writes a bar or one voice that repeats an earlier bar as a back-reference, `mN = mK` or `s.v = mK`, always pointing at a bar written out in full within the same read; no transposed references, no relative octaves, no repeat groups; an overview view (top line and bass) comes after the first release. Measured in `research/encoding-compression-2026-10-18.md`: references save 7% median per score (25% on the nocturne, 46% on a Mozart symphony) with no loss in reading; relative octaves saved 15% but Claude misread and miswrote octaves silently. Original question: can Claude's token use for reading scores go lower, and which of back-references, repeat groups, relative octaves and an overview view are worth it?
21. **Shapes.** Decided 2026-10-19: a decoration shared by a run of notes is written once for the group, e.g. `[stacc]{ 12 C4 D4 E4 F4 }`, with every pitch still written out; scales, arpeggios and other pitch-generating shapes are not part of N1x. Original question: could N1x save tokens by writing a scale or arpeggio as a shape, and an articulation shared by its notes once for all of them? Shapes hide pitches the way relative octaves did, which Claude misread and miswrote silently (`research/encoding-compression-2026-10-18.md`); transposed figures were 0–3% of beats there.
22. **Reading accuracy without thinking.** Decided 2026-10-19: the server instructions tell Claude to find the bar and count through its voice line before saying which note sounds where, and release preparation tests reading at low and medium effort, through `read_score` on bar windows, with questions whose answers are computed from the score. Original question: in the compression study, Sonnet at effort medium answered 40 of 80 questions right when it did not think first, against 372 of 400 when it did, under plain N1 too (`research/encoding-compression-2026-10-18.md`); what should Reflets do about it?
