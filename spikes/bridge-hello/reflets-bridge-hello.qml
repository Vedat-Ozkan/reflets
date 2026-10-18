// Throwaway spike: does api.websocketserver work in a v1 dialog plugin, and can WSL reach it?
// Written from scratch against the public plugin API. MIT.
import QtQuick 2.15
import QtQuick.Controls 2.15
import MuseScore 3.0

MuseScore {
    title: "Reflets Bridge Hello"
    description: "Spike: WebSocket server on port 8731 answering hello, ping, read1, write1, undo"
    version: "0.0.2"
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

    // One line per chord or rest in bar 1 of staff 0, all four voices, by segment walk.
    function readBar1() {
        if (!curScore)
            return ["noscore"]
        var lines = []
        var m = curScore.firstMeasure
        for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
            for (var track = 0; track < 4; track++) {
                var el = seg.elementAt(track)
                if (!el)
                    continue
                if (el.type === Element.CHORD) {
                    var ns = []
                    for (var i = 0; i < el.notes.length; i++) {
                        var n = el.notes[i]
                        ns.push(n.pitch + ":" + n.tpc1 + ":" + n.tpc2)
                    }
                    lines.push("C " + seg.tick + " " + track + " " + frac(el.duration) + " " + ns.join(","))
                } else if (el.type === Element.REST) {
                    lines.push("R " + seg.tick + " " + track + " " + frac(el.duration))
                }
            }
        }
        return lines
    }

    // Middle C quarter at the start of bar 1, staff 0, voice 1, as one undo step (spec 6.3, 6.4).
    function writeBar1() {
        if (!curScore)
            return "noscore"
        curScore.startCmd("Reflets: write1")
        var c = curScore.newCursor()
        c.track = 0
        c.rewindToTick(curScore.firstMeasure.firstSegment.tick)
        c.setDuration(1, 4)
        c.addNote(60, false)
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
            return id + " ok proto=0 plugin=reflets-bridge-hello/0.0.2 mscore=" + mscoreVersion
                + " ws=" + (typeof api.websocketserver) + " score=" + (curScore ? 1 : 0)
                + " title=" + escapeText(title)
        }
        if (verb === "ping")
            return id + " pong"
        if (verb === "read1")
            return [id + " ok"].concat(readBar1()).join("\n")
        if (verb === "write1") {
            var r = writeBar1()
            return [id + " " + r].concat(readBar1()).join("\n")
        }
        if (verb === "undo") {
            // 4.7 renamed undo; the old code is a silent no-op there (spec 6.8).
            var code = mscoreVersion >= 40700 ? "action://notation/undo" : "undo"
            cmd(code)
            return [id + " ok " + code].concat(readBar1()).join("\n")
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
