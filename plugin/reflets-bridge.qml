import QtQuick 2.15
import MuseScore 3.0
import FileIO 3.0

MuseScore {
    title: "Reflets Bridge"
    description: "Connects MuseScore to Reflets. Run once per session; it keeps running until MuseScore quits."
    version: "0.8.0"
    requiresScore: false

    readonly property int proto: 8
    readonly property int port: 8731
    readonly property string ideaColor: "#1565c0"
    property string token: ""
    property var authed: ({})
    property var symNames: null

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

    function symName(id) {
        if (!symNames) {
            symNames = {}
            for (var k in SymId) {
                if (typeof SymId[k] === "number")
                    symNames[SymId[k]] = k
            }
        }
        return symNames[id] || String(id)
    }

    function noteText(n, offset) {
        var t = (n.pitch + offset) + ":" + n.tpc1 + ":" + n.tpc2 + (n.tieBack ? ":b" : "")
        if (n.tieForward)
            t += n.tieForward.name === "LaissezVib" ? ":l" : ":f"
        t += (n.hasParentheses ? ":p" : "") + (n.headGroup ? ":h" + n.headGroup : "")
        for (var i = 0; n.elements && i < n.elements.length; i++) {
            if (n.elements[i].name === "Fingering")
                t += ":F" + encodeURIComponent(n.elements[i].text)
        }
        for (var j = 0; n.spannerForward && j < n.spannerForward.length; j++) {
            if (n.spannerForward[j].name === "Glissando")
                t += ":g" + n.spannerForward[j].glissType
        }
        return t
    }

    function tupletFlags(el) {
        var flags = ""
        for (var t = el.tuplet; t; t = t.tuplet)
            flags = " T" + t.actualNotes + ":" + t.normalNotes + ":" + frac(t.duration) + flags
        return flags
    }

    function chordLine(tick, track, el, grace) {
        var offset = curScore.staves[Math.floor(track / 4)].pitchOffset(fraction(tick, division * 4))
        var ns = []
        for (var i = 0; i < el.notes.length; i++)
            ns.push(noteText(el.notes[i], offset))
        var arts = []
        for (var j = 0; el.articulations && j < el.articulations.length; j++)
            arts.push(symName(el.articulations[j].symbol))
        return "C " + tick + " " + track + " " + frac(el.duration)
            + tupletFlags(el)
            + (grace ? " G" + el.noteType : "") + (arts.length ? " !" + arts.join(",") : "")
            + (el.arpeggio ? " A" + el.arpeggio.arpeggioType : "")
            + (el.tremoloSingleChord ? " M" + el.tremoloSingleChord.tremoloType : "")
            + (el.stemDirection ? " S" + el.stemDirection : "") + (el.beamMode ? " B" + el.beamMode : "")
            + (el.staffMove ? " X" + el.staffMove : "") + " " + ns.join(",")
    }

    function word(s) {
        return s ? escapeText(s).replace(/ /g, "\\s") : "-"
    }

    function barLines(m, tick) {
        var lines = []
        for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
            if (seg.segmentType !== Segment.EndBarLine)
                continue
            var bl = seg.elementAt(0)
            if (bl && !bl.generated)
                lines.push("B " + tick + " " + bl.barlineType)
        }
        var els = m.elements
        for (var i = 0; els && i < els.length; i++) {
            var e = els[i]
            if (e.type === Element.LAYOUT_BREAK)
                lines.push("L " + tick + " " + e.layoutBreakType)
            else if (e.type === Element.JUMP)
                lines.push("J " + tick + " " + word(e.jumpTo) + " " + word(e.playUntil) + " " + word(e.continueAt)
                    + " " + escapeText(e.text))
            else if (e.type === Element.MARKER)
                lines.push("Q " + tick + " " + e.markerType + " " + word(e.label) + " " + escapeText(e.text))
        }
        return lines
    }

    function voltas() {
        var lines = []
        var sp = curScore.spanners
        for (var i = 0; sp && i < sp.length; i++) {
            var v = sp[i]
            if (v.type !== Element.VOLTA)
                continue
            var endings = []
            var ve = v.volta_ending
            for (var j = 0; ve && j < ve.length; j++)
                endings.push(ve[j])
            lines.push("V " + v.spannerTick.ticks + " " + v.spannerTicks.ticks + " " + (endings.join(",") || "-")
                + " " + escapeText(v.beginText))
        }
        return lines
    }

    function info() {
        var lines = ["T " + escapeText(curScore.title || curScore.scoreName), "X composer " + escapeText(curScore.composer)]
        for (var p = 0; p < curScore.parts.length; p++) {
            var part = curScore.parts[p]
            lines.push("P " + p + " " + part.startTrack + " " + part.endTrack + " " + part.instrumentId
                + " " + escapeText(part.longName))
        }
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
                + " " + frac(m.timesigNominal) + " " + (m.repeatStart ? 1 : 0) + " " + (m.repeatEnd ? 1 : 0)
                + " " + m.repeatCount)
            lines = lines.concat(barLines(m, tick))
            for (var k = 0; k < curScore.nstaves; k++) {
                var key = curScore.staves[k].key(fraction(tick, division * 4))
                if (keys[k] !== key) {
                    lines.push("K " + tick + " " + k + " " + key)
                    keys[k] = key
                }
            }
        }
        return lines.concat(voltas())
    }

    function clefLines(seg) {
        var lines = []
        for (var s = 0; s < curScore.nstaves; s++) {
            var clef = seg.elementAt(s * 4)
            if (clef && !clef.generated)
                lines.push("F " + seg.tick + " " + (s * 4) + " " + clef.concertClefType)
        }
        return lines
    }

    function spannerLines(startTick, endTick) {
        var lines = []
        var sp = curScore.spanners
        for (var i = 0; sp && i < sp.length; i++) {
            var v = sp[i]
            if (v.name === "Volta")
                continue
            var tick = v.spannerTick.ticks
            var end = tick + v.spannerTicks.ticks
            var e = v.endElement
            var grace = (v.name === "Slur" || v.name === "HammerOnPullOff") && e && e.noteType > 0 && e.noteType < 32
            if ((v.name === "Slur" || v.name === "HammerOnPullOff") && e && e.actualDuration)
                end = e.fraction.ticks + (grace ? 0 : e.actualDuration.ticks)
            if (!(tick >= startTick && tick < endTick || end > startTick && end <= endTick))
                continue
            var sub = v.name === "HairPin" ? v.hairpinType : v.name === "Ottava" ? v.ottavaType
                : v.name === "Trill" ? v.trillType : v.name === "Vibrato" ? v.vibratoType
                : v.name === "TextLine" ? (v.systemFlag ? 1 : 0) : 0
            lines.push("N " + tick + " " + end + (grace ? "g" : "") + " " + v.track + " " + v.spannerTrack2 + " " + v.name + " " + sub
                + " " + escapeText(v.beginText || ""))
        }
        return lines
    }

    function lyricLines(tick, track, el) {
        var lines = []
        for (var y = 0; el.lyrics && y < el.lyrics.length; y++) {
            var ly = el.lyrics[y]
            lines.push("Y " + tick + " " + track + " " + ly.verse + " " + ly.syllabic + " " + ly.lyricTicks.ticks
                + " " + escapeText(ly.plainText))
        }
        return lines
    }

    function heldLyrics(startTick) {
        var lines = []
        var m = curScore.firstMeasure
        while (m && m.firstSegment.tick < startTick)
            m = m.nextMeasure
        var open = curScore.ntracks
        var done = {}
        for (var p = 0; p < curScore.parts.length; p++) {
            var part = curScore.parts[p]
            for (var t = part.startTrack; part.lyricCount === 0 && t < part.endTrack; t++) {
                done[t] = true
                open--
            }
        }
        for (var bar = m ? m.prevMeasure : curScore.lastMeasure; bar && open > 0; bar = bar.prevMeasure) {
            var sung = {}
            for (var seg = bar.lastSegment; seg; seg = seg.prevInMeasure) {
                for (var track = 0; track < curScore.ntracks; track++) {
                    var el = done[track] ? null : seg.elementAt(track)
                    if (el && el.type === Element.REST) {
                        done[track] = true
                        open--
                    }
                    if (!el || el.type !== Element.CHORD)
                        continue
                    sung[track] = true
                    if (!el.lyrics || !el.lyrics.length)
                        continue
                    done[track] = true
                    open--
                    var held = lyricLines(seg.tick, track, el).filter(function(line) {
                        var w = line.split(" ")
                        return Number(w[1]) + Number(w[5]) >= startTick
                    })
                    lines = lines.concat(held)
                }
            }
            for (var t2 = 0; t2 < curScore.ntracks; t2++) {
                if (!done[t2] && !sung[t2]) {
                    done[t2] = true
                    open--
                }
            }
        }
        return lines
    }

    function read(startTick, endTick) {
        var lines = startTick > 0 && curScore.hasLyrics ? heldLyrics(startTick) : []
        var ntracks = curScore.ntracks
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure) {
            var mt = m.firstSegment.tick
            if (mt < startTick && !(m.nextMeasure && m.nextMeasure.firstSegment.tick === startTick))
                continue
            if (mt >= endTick)
                break
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                if (seg.segmentType === Segment.Clef) {
                    if (seg.tick >= startTick && seg.tick < endTick)
                        lines = lines.concat(clefLines(seg))
                    continue
                }
                if (mt < startTick)
                    continue
                for (var track = 0; track < ntracks; track++) {
                    var el = seg.elementAt(track)
                    if (!el)
                        continue
                    if (el.type === Element.CHORD) {
                        var gs = el.graceNotes
                        for (var g = 0; gs && g < gs.length; g++)
                            lines.push(chordLine(seg.tick, track, gs[g], true))
                        lines.push(chordLine(seg.tick, track, el, false))
                        lines = lines.concat(lyricLines(seg.tick, track, el))
                    } else if (el.type === Element.BREATH) {
                        lines.push("A " + seg.tick + " " + track + " Breath " + symName(el.symbol) + " ")
                    } else if (el.type === Element.REST) {
                        lines.push("R " + seg.tick + " " + track + " " + frac(el.duration)
                            + tupletFlags(el))
                    }
                }
                var ann = seg.annotations
                for (var j = 0; ann && j < ann.length; j++) {
                    var a = ann[j]
                    var sub = a.name === "Dynamic" ? a.dynamicType : a.name === "Harmony" ? a.harmonyType
                        : a.name === "Tempo" ? a.tempo : a.name === "PlayTechAnnotation" ? a.playTechType
                        : a.name === "Fermata" ? symName(a.symbol) : 0
                    lines.push("A " + seg.tick + " " + a.track + " " + a.name + " " + sub + " " + escapeText(a.text || ""))
                }
            }
        }
        return lines.concat(spannerLines(startTick, endTick))
    }

    function offsetAt(track, tick) {
        return curScore.staves[Math.floor(track / 4)].pitchOffset(fraction(tick, division * 4))
    }

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

    function respell(n, tpc, color) {
        var transposition = n.tpc2 - n.tpc1
        n.tpc1 = tpc
        n.tpc2 = tpc + transposition
        n.color = color
    }

    function write(id, startTick, endTick, label, ops) {
        var c = null, track = 0, step = 0, chords = [], rests = []
        curScore.startCmd("Reflets: " + label)
        try {
            for (; step < ops.length; step++) {
                var w = ops[step].split(" ")
                if (w[0] === "v") {
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
        if (verb === "write")
            return write(id, parseInt(head[2]), parseInt(head[3]), head.slice(4).join(" "), lines.slice(1))
        if (verb === "color") {
            recolor(parseInt(head[2]), parseInt(head[3]), head[4].split(",").map(Number), head[5], head.slice(6).join(" "))
            return id + " ok"
        }
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
