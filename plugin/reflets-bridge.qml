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
    version: "0.2.0"
    requiresScore: false

    readonly property int proto: 2
    readonly property int port: 8731
    readonly property string ideaColor: "#1565c0"
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

    function offsetAt(track, tick) {
        return curScore.staves[Math.floor(track / 4)].pitchOffset(fraction(tick, division * 4))
    }

    // rewindToTick moves on to the next segment holding something in the cursor's track, so check the tick.
    function elementAt(track, tick) {
        var c = curScore.newCursor()
        c.track = track
        c.rewindToTick(tick)
        if (!c.segment || c.tick !== tick || !c.element)
            throw "nothing in track " + track + " at tick " + tick
        return c.element
    }

    function noteAt(track, tick, sounding) {
        var notes = elementAt(track, tick).notes
        var written = sounding - offsetAt(track, tick)
        for (var i = 0; notes && i < notes.length; i++) {
            if (notes[i].pitch === written)
                return notes[i]
        }
        throw "no note " + sounding + " in track " + track + " at tick " + tick
    }

    // Sets the concert spelling and keeps the instrument's transposition, which is tpc2 - tpc1 in fifths.
    function respell(n, tpc, color) {
        var transposition = n.tpc2 - n.tpc1
        n.tpc1 = tpc
        n.tpc2 = tpc + transposition
        n.color = color
    }

    // Ops of spec 3.8, as one undo step (6.3): v/d/n/r voice passes, then spelling and colour by tick, then
    // g, then ~. Any failure rolls the whole step back. Returns the read-back of [startTick, endTick).
    function write(id, startTick, endTick, label, ops) {
        var c = null, track = 0, step = 0, chords = [], rests = []
        curScore.startCmd("Reflets: " + label)
        try {
            for (; step < ops.length; step++) {
                var w = ops[step].split(" ")
                if (w[0] === "v") {
                    // Spec 6.4: land through voice 1 of the staff, which always has something at the bar
                    // start, then switch track without moving.
                    track = parseInt(w[1])
                    c = curScore.newCursor()
                    c.track = track - track % 4
                    c.rewindToTick(parseInt(w[2]))
                    c.track = track
                } else if (w[0] === "d") {
                    var f = w[1].split("/")
                    c.setDuration(parseInt(f[0]), parseInt(f[1]))
                } else if (w[0] === "n") {
                    var tick = parseInt(w[1])
                    var ns = w[2].split(",")
                    for (var i = 0; i < ns.length; i++)
                        c.addNote(parseInt(ns[i].split(":")[0]) - offsetAt(track, tick), i > 0)
                    chords.push([track, tick, ns])
                } else if (w[0] === "r") {
                    c.addRest()
                    rests.push([track, parseInt(w[1])])
                } else {
                    break
                }
            }
            // After addNote the cursor already sits on the next position, so revisit by tick (spec 6.4).
            for (var j = 0; j < chords.length; j++) {
                for (var k = 0; k < chords[j][2].length; k++) {
                    var pt = chords[j][2][k].split(":")
                    respell(noteAt(chords[j][0], chords[j][1], parseInt(pt[0])), parseInt(pt[1]), ideaColor)
                }
            }
            for (var r = 0; r < rests.length; r++)
                elementAt(rests[r][0], rests[r][1]).color = ideaColor
            for (; step < ops.length; step++) {
                var o = ops[step].split(" ")
                var otrack = parseInt(o[1]), otick = parseInt(o[2])
                if (o[0] === "g") {
                    // The grace action adds a grace note at the main note's pitch, in front of any earlier
                    // ones, so the first grace still on that pitch is the new one (spike round 5).
                    var chord = elementAt(otrack, otick)
                    var main = chord.notes[0]
                    curScore.selection.select(main)
                    cmd(o[3])
                    var gp = o[4].split(":")
                    var gs = chord.graceNotes
                    var added = null
                    for (var g = 0; gs && g < gs.length && !added; g++) {
                        if (gs[g].notes[0].pitch === main.pitch)
                            added = gs[g].notes[0]
                    }
                    if (!added)
                        throw o[3] + " added no grace note"
                    added.pitch = parseInt(gp[0]) - offsetAt(otrack, otick)
                    respell(added, parseInt(gp[1]), ideaColor)
                } else if (o[0] === "~") {
                    // cmd("tie") toggles, so only when the tie is not there yet (spec 6.5).
                    var n = noteAt(otrack, otick, parseInt(o[3]))
                    if (!n.tieForward) {
                        curScore.selection.select(n)
                        cmd("tie")
                    }
                    if (!n.tieForward)
                        throw "tie not made"
                } else {
                    throw "unknown op " + o[0]
                }
            }
        } catch (e) {
            curScore.endCmd(true)
            return id + " err write-failed " + step + " " + escapeText(e)
        }
        curScore.endCmd(false)
        curScore.selection.clear()
        return [id + " ok"].concat(read(startTick, endTick)).join("\n")
    }

    // Sets the colour of every note and rest of the tracks in [startTick, endTick), as one undo step.
    function recolor(startTick, endTick, tracks, color, label) {
        curScore.startCmd("Reflets: " + label)
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure) {
            var mt = m.firstSegment.tick
            if (mt < startTick)
                continue
            if (mt >= endTick)
                break
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                for (var t = 0; t < tracks.length; t++) {
                    var el = seg.elementAt(tracks[t])
                    if (!el)
                        continue
                    if (el.type === Element.REST)
                        el.color = color
                    if (el.type !== Element.CHORD)
                        continue
                    var cs = [el]
                    for (var g = 0; el.graceNotes && g < el.graceNotes.length; g++)
                        cs.push(el.graceNotes[g])
                    for (var i = 0; i < cs.length; i++) {
                        for (var k = 0; k < cs[i].notes.length; k++)
                            cs[i].notes[k].color = color
                    }
                }
            }
        }
        curScore.endCmd(false)
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
        var lines = String(text).split("\n")
        var head = lines[0].split(" ")
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
        // write <startTick> <endTick> <label...>, ops in the body (spec 3.8).
        if (verb === "write")
            return write(id, parseInt(head[2]), parseInt(head[3]), head.slice(4).join(" "), lines.slice(1))
        // color <startTick> <endTick> <track,...> <#rrggbb> <label...>
        if (verb === "color") {
            recolor(parseInt(head[2]), parseInt(head[3]), head[4].split(",").map(Number), head[5], head.slice(6).join(" "))
            return id + " ok"
        }
        // Outside any startCmd. 4.7 renamed the codes; the old ones are silent no-ops there (spec 6.8).
        if (verb === "undo" || verb === "redo") {
            cmd("action://notation/" + verb)
            return id + " ok"
        }
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
