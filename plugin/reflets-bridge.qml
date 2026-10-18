// Reflets bridge: lets the Reflets MCP server read and write the score open in MuseScore Studio 4.7.
// Protocol and design: docs/spec-core.md sections 2 and 3. MIT licence.
//
// No pluginType, so MuseScore runs this as a macro: no dialog, and the object (with its server) stays
// alive until MuseScore quits. An open plugin dialog makes MuseScore refuse notation actions such as
// tie (spec 2.1).
import QtQuick 2.15
import MuseScore 3.0
import FileIO 3.0

MuseScore {
    title: "Reflets Bridge"
    description: "Connects MuseScore to Reflets. Run once per session; it keeps running until MuseScore quits."
    version: "0.1.0"
    requiresScore: false

    readonly property int proto: 1
    readonly property int port: 8731
    property string token: ""
    property var authed: ({})

    FileIO { id: tokenFile }

    function escapeText(s) {
        return String(s).replace(/\\/g, "\\\\").replace(/\n/g, "\\n")
    }

    function frac(f) {
        return f.numerator + "/" + f.denominator
    }

    function newToken() {
        var hex = ""
        for (var i = 0; i < 32; i++)
            hex += Math.floor(Math.random() * 16).toString(16)
        return hex
    }

    // Qt.resolvedUrl gives file:///C:/... on Windows and file:///home/... elsewhere.
    function localPath(url) {
        var p = decodeURIComponent(String(url).replace(/^file:\/\//, ""))
        return /^\/[A-Za-z]:/.test(p) ? p.substring(1) : p
    }

    function measureList() {
        var list = []
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure)
            list.push(m)
        return list
    }

    // pitch is written pitch; under an octave line the sounding pitch is pitch + offset (spec 3.7).
    function noteText(n, offset) {
        return (n.pitch + offset) + ":" + n.tpc1 + ":" + n.tpc2 + (n.tieBack ? ":b" : "") + (n.tieForward ? ":f" : "")
    }

    function chordLine(tick, track, el, grace) {
        var offset = curScore.staves[Math.floor(track / 4)].pitchOffset(fraction(tick, division * 4))
        var ns = []
        for (var i = 0; i < el.notes.length; i++)
            ns.push(noteText(el.notes[i], offset))
        return "C " + tick + " " + track + " " + frac(el.duration)
            + (el.tuplet ? " T" + el.tuplet.actualNotes + ":" + el.tuplet.normalNotes : "")
            + (grace ? " G" + el.noteType : "") + " " + ns.join(",")
    }

    // T, P, S, M, K lines (spec 3.7). K only where a staff's key differs from its previous bar.
    function info() {
        var lines = ["T " + escapeText(curScore.title || curScore.scoreName)]
        for (var p = 0; p < curScore.parts.length; p++) {
            var part = curScore.parts[p]
            lines.push("P " + p + " " + part.startTrack + " " + part.endTrack + " " + part.instrumentId
                + " " + escapeText(part.longName))
        }
        // Wrappers are new objects on every access, so staves are matched to parts by track, not identity.
        for (var s = 0; s < curScore.nstaves; s++) {
            for (var q = 0; q < curScore.parts.length; q++) {
                if (s * 4 >= curScore.parts[q].startTrack && s * 4 < curScore.parts[q].endTrack)
                    lines.push("S " + s + " " + q)
            }
        }
        var keys = []
        var ms = measureList()
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            var tick = m.firstSegment.tick
            lines.push("M " + m.no + " " + (m.irregular ? 1 : 0) + " " + tick + " " + frac(m.timesigActual)
                + " " + frac(m.timesigNominal))
            for (var k = 0; k < curScore.nstaves; k++) {
                var key = curScore.staves[k].key(fraction(tick, division * 4))
                if (keys[k] !== key) {
                    lines.push("K " + tick + " " + k + " " + key)
                    keys[k] = key
                }
            }
        }
        return lines
    }

    // C, R, A lines for bars whose first tick is in [startTick, endTick), all tracks (spec 3.7).
    function read(startTick, endTick) {
        var lines = []
        var ntracks = curScore.ntracks
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure) {
            var mt = m.firstSegment.tick
            if (mt < startTick)
                continue
            if (mt >= endTick)
                break
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                for (var track = 0; track < ntracks; track++) {
                    var el = seg.elementAt(track)
                    if (!el)
                        continue
                    if (el.type === Element.CHORD) {
                        var gs = el.graceNotes
                        for (var g = 0; gs && g < gs.length; g++)
                            lines.push(chordLine(seg.tick, track, gs[g], true))
                        lines.push(chordLine(seg.tick, track, el, false))
                    } else if (el.type === Element.REST) {
                        lines.push("R " + seg.tick + " " + track + " " + frac(el.duration)
                            + (el.tuplet ? " T" + el.tuplet.actualNotes + ":" + el.tuplet.normalNotes : ""))
                    }
                }
                var ann = seg.annotations
                for (var j = 0; ann && j < ann.length; j++) {
                    var a = ann[j]
                    var sub = a.name === "Dynamic" ? a.dynamicType : a.name === "Harmony" ? a.harmonyType : 0
                    lines.push("A " + seg.tick + " " + a.track + " " + a.name + " " + sub + " " + escapeText(a.text))
                }
            }
        }
        return lines
    }

    function fields(words) {
        var f = {}
        for (var i = 0; i < words.length; i++) {
            var eq = words[i].indexOf("=")
            if (eq > 0)
                f[words[i].substring(0, eq)] = words[i].substring(eq + 1)
        }
        return f
    }

    function handle(clientId, text) {
        var head = String(text).split("\n")[0].split(" ")
        var id = head[0]
        var verb = head[1]
        if (verb === "hello") {
            var f = fields(head.slice(2))
            if (f.token !== token)
                return id + " err unauthorized token does not match the plugin's token file"
            authed[clientId] = true
            return id + " ok proto=" + proto + " plugin=reflets-bridge/" + version + " mscore=" + mscoreVersion
                + " division=" + division + " score=" + (curScore ? 1 : 0)
                + " title=" + escapeText(curScore ? (curScore.title || curScore.scoreName) : "")
        }
        // Nothing but hello until this connection has shown the token (spec 2.2).
        if (!authed[clientId])
            return id + " err unauthorized send hello with the token first"
        if (verb === "ping")
            return id + " ok pong"
        if (!curScore)
            return id + " err no-score"
        if (verb === "info")
            return [id + " ok"].concat(info()).join("\n")
        if (verb === "read")
            return [id + " ok"].concat(read(parseInt(head[2]), parseInt(head[3]))).join("\n")
        return id + " err bad-request unknown verb " + escapeText(verb)
    }

    function onClient(clientId) {
        api.websocketserver.onMessage(clientId, function(text) {
            var reply
            try {
                reply = handle(clientId, text)
            } catch (e) {
                reply = String(text).split(" ")[0] + " err bad-request " + escapeText(e)
            }
            api.websocketserver.send(clientId, reply)
        })
    }

    onRun: {
        if (typeof api === "undefined" || !api.websocketserver) {
            api.log.info("reflets-bridge: this MuseScore build has no WebSocket API")
            return
        }
        token = newToken()
        tokenFile.source = localPath(Qt.resolvedUrl("reflets-token.txt"))
        var written = tokenFile.write(token)
        api.websocketserver.listen(port, onClient)
        api.log.info("reflets-bridge " + version + ": listening on " + port + ", token file " + tokenFile.source
            + (written ? "" : " (WRITE FAILED)"))
    }
}
