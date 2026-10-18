// Throwaway spike: does api.websocketserver work in a v1 dialog plugin, and can WSL reach it?
// Round 2 adds the write-path checks of spec 10: several ops in one undo step, a second voice,
// respelling, ties, annotations, tuplets. Round 3 adds tie and dynamic variants; install.sh also
// installs this file as a non-dialog (macro) plugin on port 8732, to test whether the open dialog
// is what makes MuseScore refuse cmd("tie") ("no one can handle the action: tie" in its log).
// Round 4 adds whole-score read timing, bar numbers, writeScore and readScore. Since round 3 only the
// macro install is used. Written from scratch against the public plugin API. MIT.
import QtQuick 2.15
import QtQuick.Controls 2.15
import MuseScore 3.0

MuseScore {
    title: "Reflets Bridge Hello"
    description: "Spike: WebSocket server on port 8731 for bridge and write-path checks"
    version: "0.0.6"
    pluginType: "dialog"
    requiresScore: false
    width: 420
    height: 220

    property int port: 8731
    property int received: 0
    property var registered: ({})
    property string status: "starting"
    property string lastLine: ""

    function escapeText(s) {
        return String(s).replace(/\\/g, "\\\\").replace(/\n/g, "\\n")
    }

    function frac(f) {
        return f ? f.numerator + "/" + f.denominator : "?"
    }

    // Bars are numbered from 1 as on screen; no pickup in the scratch score.
    function measureAt(bar) {
        var m = curScore.firstMeasure
        for (var i = 1; i < bar && m; i++)
            m = m.nextMeasure
        return m
    }

    function noteText(n) {
        return n.pitch + ":" + n.tpc1 + ":" + n.tpc2 + (n.tieBack ? ":b" : "") + (n.tieForward ? ":f" : "")
    }

    function chordLine(kind, tick, track, el) {
        var ns = []
        for (var i = 0; i < el.notes.length; i++)
            ns.push(noteText(el.notes[i]))
        var tup = el.tuplet ? " t=" + el.tuplet.actualNotes + "/" + el.tuplet.normalNotes : ""
        return kind + " " + tick + " " + track + " " + frac(el.duration) + " " + ns.join(",") + tup
    }

    // C/R lines for every track of bars [from, to], G lines for grace chords before their chord,
    // A lines for annotations, by segment walk. Round 4 widened this from staff 0 of one bar.
    function readRange(from, to) {
        var lines = []
        var ntracks = curScore.ntracks
        var m = measureAt(from)
        for (var bar = from; m && bar <= to; bar++, m = m.nextMeasure) {
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                for (var track = 0; track < ntracks; track++) {
                    var el = seg.elementAt(track)
                    if (!el)
                        continue
                    if (el.type === Element.CHORD) {
                        var gs = el.graceNotes
                        for (var g = 0; gs && g < gs.length; g++)
                            lines.push(chordLine("G", seg.tick, track, gs[g]) + " type=" + gs[g].noteType)
                        lines.push(chordLine("C", seg.tick, track, el))
                    } else if (el.type === Element.REST) {
                        var tup = el.tuplet ? " t=" + el.tuplet.actualNotes + "/" + el.tuplet.normalNotes : ""
                        lines.push("R " + seg.tick + " " + track + " " + frac(el.duration) + tup)
                    }
                }
                var ann = seg.annotations
                for (var j = 0; ann && j < ann.length; j++) {
                    var a = ann[j]
                    lines.push("A " + seg.tick + " " + a.track + " " + a.name + " harmonyType=" + a.harmonyType
                        + " dynamicType=" + a.dynamicType + " velocity=" + a.velocity + " text=" + escapeText(a.text))
                }
            }
        }
        return lines
    }

    function readBar(bar) {
        if (!measureAt(bar))
            return ["nobar " + bar]
        return readRange(bar, bar)
    }

    // Bar numbering facts for spec 10 item 5: index from 1, the plugin's no, irregular, tick, length.
    function barInfo(from, to) {
        var lines = []
        var m = measureAt(from)
        for (var i = from; m && i <= to; i++, m = m.nextMeasure)
            lines.push("M " + i + " no=" + m.no + " irregular=" + m.irregular + " tick=" + m.firstSegment.tick
                + " ticks=" + (m.ticks && m.ticks.numerator !== undefined ? frac(m.ticks) : m.ticks)
                + " actual=" + frac(m.timesigActual) + " nominal=" + frac(m.timesigNominal))
        return lines
    }

    function countBars() {
        var n = 0
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure)
            n++
        return n
    }

    function chordAt(bar, tick, track) {
        for (var seg = measureAt(bar).firstSegment; seg; seg = seg.nextInMeasure) {
            if (seg.tick === tick) {
                var el = seg.elementAt(track)
                if (el && el.type === Element.CHORD)
                    return el
            }
        }
        return null
    }

    // Spec 6.4 steps 1-2: land through voice 1 of the staff, then switch track without moving.
    function land(bar, track) {
        var c = curScore.newCursor()
        c.track = 0
        c.rewindToTick(measureAt(bar).firstSegment.tick)
        c.track = track
        return c
    }

    // Bar 1: voice 1 C4+E4 quarter, pitch 63 quarter respelled, G4 half; voice 2 C4 whole. One command.
    function opMulti() {
        var t0 = measureAt(1).firstSegment.tick
        curScore.startCmd("Reflets: multi")
        var c = land(1, 0)
        c.setDuration(1, 4)
        c.addNote(60, false)
        c.addNote(64, true)
        c.addNote(63, false)
        c.setDuration(1, 2)
        c.addNote(67, false)
        c = land(1, 1)
        c.setDuration(1, 1)
        c.addNote(60, false)
        // Spelling pass by tick (spec 6.4): flip whatever MuseScore chose for pitch 63.
        var n = chordAt(1, t0 + 480, 0).notes[0]
        var before = n.tpc1
        // tpc: Eb is 11, D# is 23 (round 2 used 21, which is C#).
        var target = before === 11 ? 23 : 11
        n.tpc1 = target
        n.tpc2 = target
        curScore.endCmd(false)
        return "spelling " + before + "->" + target
    }

    // Bar 2: G4 G4 quarters then a half rest, tie the first to the second with cmd("tie").
    function opTie() {
        curScore.startCmd("Reflets: tie")
        var c = land(2, 0)
        c.setDuration(1, 4)
        c.addNote(67, false)
        c.addNote(67, false)
        c.setDuration(1, 2)
        c.addRest()
        var t0 = measureAt(2).firstSegment.tick
        var n = chordAt(2, t0, 0).notes[0]
        var sel = curScore.selection.select(n)
        cmd("tie")
        curScore.endCmd(false)
        return "select=" + sel
    }

    // Bar 4: same notes as opTie, but the tie action is dispatched after endCmd, outside the undo lock.
    function opTieOutside() {
        curScore.startCmd("Reflets: tieout notes")
        var c = land(4, 0)
        c.setDuration(1, 4)
        c.addNote(67, false)
        c.addNote(67, false)
        c.setDuration(1, 2)
        c.addRest()
        curScore.endCmd(false)
        var n = chordAt(4, measureAt(4).firstSegment.tick, 0).notes[0]
        var sel = curScore.selection.select(n)
        cmd("tie")
        return "select=" + sel
    }

    // Bar 5: dynamicType only. Bar 6: text, then dynamicType. One command.
    function opDyn() {
        curScore.startCmd("Reflets: dyn")
        var c = land(5, 0)
        var d1 = newElement(Element.DYNAMIC)
        c.add(d1)
        d1.dynamicType = DynamicType.MF
        c = land(6, 0)
        var d2 = newElement(Element.DYNAMIC)
        c.add(d2)
        d2.text = "mf"
        d2.dynamicType = DynamicType.MF
        curScore.endCmd(false)
        return "MF=" + DynamicType.MF
    }

    // Select the main note at (bar, tick), dispatch a grace action, then respell the new grace note,
    // which MuseScore creates at the main note's pitch. Earlier graces were already moved off that
    // pitch, so the new one is the only grace still on it.
    function addGrace(bar, tick, action, pitch, tpc) {
        var chord = chordAt(bar, tick, 0)
        var main = chord.notes[0]
        curScore.selection.select(main)
        cmd(action)
        var gs = chord.graceNotes
        for (var i = 0; i < gs.length; i++) {
            var n = gs[i].notes[0]
            if (n.pitch === main.pitch) {
                n.pitch = pitch
                n.tpc1 = tpc
                n.tpc2 = tpc
                return action + "@" + tick + ":" + i + "/" + gs.length
            }
        }
        return action + "@" + tick + ":none/" + gs.length
    }

    // Bar 1: C5 D5 E5 F5 quarters; an acciaccatura C#5 before D5, two grace16 before E5 (G5 added
    // first, then F5), a grace8after G5 after F5. All in one command.
    function opGrace() {
        var t0 = measureAt(1).firstSegment.tick
        curScore.startCmd("Reflets: grace")
        var c = land(1, 0)
        c.setDuration(1, 4)
        c.addNote(72, false)
        c.addNote(74, false)
        c.addNote(76, false)
        c.addNote(77, false)
        var r = [addGrace(1, t0 + 480, "acciaccatura", 73, 21),
                 addGrace(1, t0 + 960, "grace16", 79, 15),
                 addGrace(1, t0 + 960, "grace16", 77, 13),
                 addGrace(1, t0 + 1440, "grace8after", 79, 15)]
        curScore.endCmd(false)
        return r.join(" ")
    }

    // Bar 1 beat 1: chord symbol, dynamic, staff text; text set after cursor.add (spec 6.7).
    function opAnnot() {
        curScore.startCmd("Reflets: annot")
        var c = land(1, 0)
        var h = newElement(Element.HARMONY)
        c.add(h)
        h.text = "Cmaj7"
        var d = newElement(Element.DYNAMIC)
        c.add(d)
        d.text = "mf"
        var s = newElement(Element.STAFF_TEXT)
        c.add(s)
        s.text = "reflets"
        curScore.endCmd(false)
        return "ok"
    }

    // Bar 3: an eighth-note triplet on beat 1, the rest left to MuseScore.
    function opTuplet() {
        curScore.startCmd("Reflets: tuplet")
        var c = land(3, 0)
        c.addTuplet(fraction(3, 2), fraction(1, 4))
        c.setDuration(1, 8)
        c.addNote(72, false)
        c.addNote(74, false)
        c.addNote(76, false)
        curScore.endCmd(false)
        return "ok"
    }

    function handle(text) {
        var lines = String(text).split("\n")
        var head = lines[0].split(" ")
        var id = head[0]
        var verb = head[1]
        if (verb === "hello") {
            var title = curScore ? curScore.scoreName : ""
            return id + " ok proto=0 plugin=reflets-bridge-hello/0.0.6 port=" + port + " mscore=" + mscoreVersion
                + " ws=" + (typeof api.websocketserver) + " score=" + (curScore ? 1 : 0)
                + " title=" + escapeText(title)
        }
        if (verb === "ping")
            return id + " pong"
        // Before the score check: opening a file with no score open is the case being tested.
        if (verb === "open") {
            var before = curScore ? curScore.scoreName : "none"
            var sc = readScore(head[2])
            return id + " ok before=" + escapeText(before) + " returned=" + (sc ? escapeText(sc.scoreName) : "null")
                + " current=" + escapeText(curScore ? curScore.scoreName : "none")
        }
        if (!curScore)
            return id + " err noscore"
        if (verb === "read")
            return [id + " ok"].concat(readBar(parseInt(head[2]))).join("\n")
        if (verb === "stats") {
            var parts = []
            for (var p = 0; p < curScore.parts.length; p++)
                parts.push(escapeText(curScore.parts[p].longName))
            return id + " ok bars=" + countBars() + " nmeasures=" + curScore.nmeasures + " nstaves=" + curScore.nstaves
                + " ntracks=" + curScore.ntracks + " parts=" + parts.join("|")
        }
        if (verb === "bars")
            return [id + " ok"].concat(barInfo(parseInt(head[2]), parseInt(head[3]))).join("\n")
        // readall <from> <to> [count]: whole-range walk; "count" returns only the totals, to separate
        // walk time from transfer time.
        if (verb === "readall") {
            var t0 = Date.now()
            var rl = readRange(parseInt(head[2]), parseInt(head[3]))
            var ms = Date.now() - t0
            var body = rl.join("\n")
            var sum = id + " ok lines=" + rl.length + " chars=" + body.length + " walk_ms=" + ms
            return head[4] === "count" ? sum : sum + "\n" + body
        }
        if (verb === "export") {
            var t1 = Date.now()
            var okw = writeScore(curScore, head[2], "musicxml")
            return id + " ok written=" + okw + " ms=" + (Date.now() - t1)
        }
        var ops = { multi: opMulti, tie: opTie, tieout: opTieOutside, grace: opGrace, annot: opAnnot, tuplet: opTuplet, dyn: opDyn }
        if (ops[verb])
            return id + " ok " + ops[verb]()
        if (verb === "undo") {
            // 4.7 renamed undo; the old code is a silent no-op there (spec 6.8).
            cmd("action://notation/undo")
            return id + " ok"
        }
        return id + " err unknown_verb " + escapeText(verb)
    }

    function onClient(clientId) {
        if (registered[clientId])
            return
        registered[clientId] = true
        status = "client " + clientId + " connected"
        api.websocketserver.onMessage(clientId, function(text) {
            received++
            lastLine = String(text).split("\n")[0]
            var reply
            try {
                reply = handle(text)
            } catch (e) {
                reply = String(text).split(" ")[0] + " err exception " + escapeText(e)
            }
            api.websocketserver.send(clientId, reply)
        })
    }

    onRun: {
        if (typeof api === "undefined" || !api.websocketserver) {
            status = "api.websocketserver is UNDEFINED in this build"
            return
        }
        var r = api.websocketserver.listen(port, onClient)
        status = "listening on " + port + " (listen returned " + r + ")"
        if (api.log)
            api.log.info("reflets-bridge-hello: " + status)
    }

    Column {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 8
        Label { text: "Reflets Bridge Hello (spike)"; font.bold: true }
        Label { text: "MuseScore " + mscoreVersion }
        Label { text: status; wrapMode: Text.Wrap; width: parent.width }
        Label { text: "messages received: " + received }
        Label { text: "last: " + lastLine; elide: Text.ElideRight; width: parent.width }
        Label { text: "Keep this window open while testing." }
    }
}
