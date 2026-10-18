// Throwaway spike: does api.websocketserver work in a v1 dialog plugin, and can WSL reach it?
// Round 2 adds the write-path checks of spec 10: several ops in one undo step, a second voice,
// respelling, ties, annotations, tuplets. Written from scratch against the public plugin API. MIT.
import QtQuick 2.15
import QtQuick.Controls 2.15
import MuseScore 3.0

MuseScore {
    title: "Reflets Bridge Hello"
    description: "Spike: WebSocket server on port 8731 for bridge and write-path checks"
    version: "0.0.3"
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

    // C/R lines for staff 0, all voices, plus A lines for annotations, by segment walk.
    function readBar(bar) {
        if (!curScore)
            return ["noscore"]
        var m = measureAt(bar)
        if (!m)
            return ["nobar " + bar]
        var lines = []
        for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
            for (var track = 0; track < 4; track++) {
                var el = seg.elementAt(track)
                if (!el)
                    continue
                var tup = el.tuplet ? " t=" + el.tuplet.actualNotes + "/" + el.tuplet.normalNotes : ""
                if (el.type === Element.CHORD) {
                    var ns = []
                    for (var i = 0; i < el.notes.length; i++)
                        ns.push(noteText(el.notes[i]))
                    lines.push("C " + seg.tick + " " + track + " " + frac(el.duration) + " " + ns.join(",") + tup)
                } else if (el.type === Element.REST) {
                    lines.push("R " + seg.tick + " " + track + " " + frac(el.duration) + tup)
                }
            }
            var ann = seg.annotations
            for (var j = 0; ann && j < ann.length; j++) {
                var a = ann[j]
                lines.push("A " + seg.tick + " " + a.track + " " + a.name + " harmonyType=" + a.harmonyType
                    + " dynamicType=" + a.dynamicType + " text=" + escapeText(a.text))
            }
        }
        return lines
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
        var target = before === 11 ? 21 : 11
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
            return id + " ok proto=0 plugin=reflets-bridge-hello/0.0.3 mscore=" + mscoreVersion
                + " ws=" + (typeof api.websocketserver) + " score=" + (curScore ? 1 : 0)
                + " title=" + escapeText(title)
        }
        if (verb === "ping")
            return id + " pong"
        if (!curScore)
            return id + " err noscore"
        if (verb === "read")
            return [id + " ok"].concat(readBar(parseInt(head[2]))).join("\n")
        var ops = { multi: opMulti, tie: opTie, annot: opAnnot, tuplet: opTuplet }
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
