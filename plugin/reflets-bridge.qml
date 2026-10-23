import QtQuick 2.15
import MuseScore 3.0
import FileIO 3.0
import QtQuick.Window 2.15

MuseScore {
    title: "Reflets Bridge"
    description: "Connects MuseScore to Reflets. Run once per session; it keeps running until MuseScore quits."
    version: "0.24.6"
    requiresScore: false

    readonly property int proto: 24
    readonly property int port: 8731
    readonly property string ideaColor: "#1565c0"
    property string token: ""
    property var authed: ({})
    property var symNames: null
    property bool badgeWaiting: false
    property bool badgeInMain: false

    FileIO { id: tokenFile }

    Window {
        id: badge
        title: "Reflets status"
        width: pill.width
        height: pill.height
        x: (Screen.width - width) / 2
        y: 106
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus
        color: "transparent"
        Rectangle {
            id: pill
            width: badgeRow.implicitWidth + 36
            height: 36
            x: (parent.width - width) / 2
            y: badgeInMain ? 106 : 0
            z: 1000000
            visible: opacity > 0
            radius: height / 2
            color: ideaColor
            opacity: 0
            Behavior on opacity { NumberAnimation { duration: 200 } }
            Row {
                id: badgeRow
                anchors.centerIn: parent
                spacing: 10
                Rectangle {
                    width: 6
                    height: 6
                    radius: 3
                    color: "white"
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: "Reflets"
                    color: "white"
                    font.family: "Inter"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
                Text {
                    id: badgeText
                    color: "white"
                    font.family: "Inter"
                    font.pixelSize: 14
                }
                Text {
                    id: badgeTime
                    color: "white"
                    opacity: 0.6
                    font.family: "Inter"
                    font.pixelSize: 14
                }
            }
        }
    }

    Timer {
        id: badgeTimer
        interval: 6000
        onTriggered: {
            pill.opacity = 0
            badgeHide.restart()
        }
    }

    Timer {
        id: badgeHide
        interval: 250
        onTriggered: badge.hide()
    }

    Connections {
        target: Qt.application
        function onStateChanged() {
            if (Qt.application.state !== Qt.ApplicationActive) {
                pill.opacity = 0
                badge.hide()
            } else if (badgeWaiting)
                showBadge()
        }
    }

    function status(text) {
        badgeText.text = text
        badgeTime.text = Qt.formatTime(new Date(), "hh:mm")
        badgeWaiting = Qt.application.state !== Qt.ApplicationActive
        if (!badgeWaiting)
            showBadge()
    }

    function showBadge() {
        badgeWaiting = false
        badgeHide.stop()
        if (!badgeInMain)
            badge.show()
        pill.opacity = 1
        badgeTimer.restart()
    }

    function escapeText(s) {
        return String(s).replace(/\\/g, "\\\\").replace(/\n/g, "\\n")
    }

    function unescapeText(s) {
        return String(s).replace(/\\(n|\\)/g, function(m, ch) { return ch === "n" ? "\n" : "\\" })
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
        var shifts = []
        for (var ks = 0; ks < curScore.nstaves; ks++) {
            var first = keySigAt(ks, 0, false)
            shifts.push(first ? first.actualKey - first.concertKey : 0)
        }
        var ms = measureList()
        for (var i = 0; i < ms.length; i++) {
            var m = ms[i]
            var tick = m.firstSegment.tick
            lines.push("M " + m.no + " " + (m.irregular ? 1 : 0) + " " + tick + " " + frac(m.timesigActual)
                + " " + frac(m.timesigNominal) + " " + (m.repeatStart ? 1 : 0) + " " + (m.repeatEnd ? 1 : 0)
                + " " + m.repeatCount)
            lines = lines.concat(barLines(m, tick))
            for (var k = 0; k < curScore.nstaves; k++) {
                var key = curScore.staves[k].key(fraction(tick, division * 4)) - shifts[k]
                key += key > 7 ? -12 : key < -7 ? 12 : 0
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

    function graceEnd(v) {
        var e = v.endElement
        return (v.name === "Slur" || v.name === "HammerOnPullOff") && e && e.noteType > 0 && e.noteType < 32 ? true : false
    }

    function spannerEnd(v) {
        var e = v.endElement
        if ((v.name === "Slur" || v.name === "HammerOnPullOff") && e && e.actualDuration)
            return e.fraction.ticks + (graceEnd(v) ? 0 : e.actualDuration.ticks)
        return v.spannerTick.ticks + v.spannerTicks.ticks
    }

    function spannerList() {
        var list = []
        var sp = curScore.spanners
        for (var i = 0; sp && i < sp.length; i++) {
            if (sp[i].name !== "Volta")
                list.push(sp[i])
        }
        return list
    }

    function spannerIn(v, tracks, startTick, endTick) {
        var tick = v.spannerTick.ticks, end = spannerEnd(v)
        var ends = graceEnd(v) ? end >= startTick && end < endTick : end > startTick && end <= endTick
        return tracks.indexOf(v.track) >= 0 && tick >= startTick && tick < endTick || tracks.indexOf(v.spannerTrack2) >= 0 && ends
    }

    function spannerLines(startTick, endTick) {
        var lines = []
        var sp = spannerList()
        for (var i = 0; i < sp.length; i++) {
            var v = sp[i]
            var tick = v.spannerTick.ticks
            var end = spannerEnd(v)
            var grace = graceEnd(v)
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
                        lines.push(breathLine(seg.tick, track, el))
                    } else if (el.type === Element.REST) {
                        lines.push("R " + seg.tick + " " + track + " " + frac(el.duration)
                            + tupletFlags(el))
                    }
                }
                var ann = seg.annotations
                for (var j = 0; ann && j < ann.length; j++) {
                    if (ann[j].name !== "PlayCountText")
                        lines.push(annotationLine(seg.tick, ann[j]))
                }
            }
        }
        return lines.concat(spannerLines(startTick, endTick))
    }

    function annotationLine(tick, a) {
        var sub = a.name === "Dynamic" ? a.dynamicType : a.name === "Harmony" ? a.harmonyType
            : a.name === "Tempo" ? a.tempo : a.name === "PlayTechAnnotation" ? a.playTechType
            : a.name === "Fermata" ? symName(a.symbol) : 0
        return "A " + tick + " " + a.track + " " + a.name + " " + sub + " " + escapeText(a.text || "")
    }

    function breathLine(tick, track, el) {
        return "A " + tick + " " + track + " Breath " + symName(el.symbol) + " "
    }

    function removeSpanner(tick, track, end, name) {
        var sp = spannerList()
        for (var i = 0; i < sp.length; i++) {
            var v = sp[i]
            if (v.name === name && v.track === track && v.spannerTick.ticks === tick && spannerEnd(v) === end) {
                removeElement(v)
                return
            }
        }
        throw "no " + name + " from " + tick + " to " + end + " in track " + track
    }

    function removeMark(line) {
        var tick = parseInt(line.split(" ")[1])
        for (var m = curScore.firstMeasure; m && m.firstSegment.tick <= tick; m = m.nextMeasure) {
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                if (seg.tick !== tick)
                    continue
                for (var track = 0; track < curScore.ntracks; track++) {
                    var el = seg.elementAt(track)
                    if (el && (seg.segmentType === Segment.Clef && "F " + tick + " " + track + " " + el.concertClefType === line
                               || el.type === Element.BREATH && breathLine(tick, track, el) === line)) {
                        removeElement(el)
                        return
                    }
                }
                var ann = seg.annotations
                for (var j = 0; ann && j < ann.length; j++) {
                    if (annotationLine(tick, ann[j]) === line) {
                        removeElement(ann[j])
                        return
                    }
                }
            }
        }
        throw "no mark to remove: " + line
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

    function cursorAt(track, tick) {
        var c = curScore.newCursor()
        var order = [track]
        for (var t = 0; t < curScore.ntracks; t++) {
            if (t !== track)
                order.push(t)
        }
        for (var i = 0; i < order.length; i++) {
            c.track = order[i]
            c.rewindToTick(tick)
            if (c.segment && c.tick === tick) {
                c.track = track
                return c
            }
        }
        throw "no note or rest at tick " + tick
    }

    function deleteRests(track, startTick, endTick) {
        var doomed = []
        for (var m = curScore.firstMeasure; m && m.firstSegment.tick < endTick; m = m.nextMeasure) {
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                var el = seg.tick >= startTick && seg.tick < endTick ? seg.elementAt(track) : null
                if (el && el.type === Element.REST)
                    doomed.push(el)
            }
        }
        for (var k = 0; k < doomed.length; k++)
            removeElement(doomed[k])
    }

    function clearVoice(track, startTick, endTick, notes) {
        var doomed = []
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure) {
            var mt = m.firstSegment.tick
            if (mt >= endTick)
                break
            if (m.nextMeasure && m.nextMeasure.firstSegment.tick < startTick)
                continue
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                if (seg.tick < startTick || seg.tick >= endTick || mt < startTick)
                    continue
                var cr = notes ? seg.elementAt(track) : null
                for (var g = 0; cr && cr.type === Element.CHORD && cr.graceNotes && g < cr.graceNotes.length; g++)
                    doomed.push(cr.graceNotes[g])
            }
        }
        for (var k = 0; k < doomed.length; k++)
            removeElement(doomed[k])
        for (var left = notes ? 1000 : 0; left > 0; left--) {
            var top = firstTuplet(track, startTick, endTick)
            if (!top)
                return doomed.length > 0 || left < 1000
            removeElement(top)
        }
        if (notes)
            throw "the tuplets in track " + track + " could not be removed"
        return false
    }

    function firstTuplet(track, startTick, endTick) {
        var c = curScore.newCursor()
        c.track = track - track % 4
        c.rewindToTick(startTick)
        c.track = track
        for (; c.segment && c.tick < endTick; c.next()) {
            var t = c.element ? c.element.tuplet : null
            if (t) {
                while (t.tuplet)
                    t = t.tuplet
                return t
            }
        }
        return null
    }

    function addMark(track, tick, kind, value, text) {
        var c = cursorAt(track, tick)
        var el = newElement(Element[kind])
        if (kind === "CLEF") {
            el.concertClefType = value
            el.transposingClefType = value
        }
        if (kind === "TEMPO_TEXT") {
            el.tempo = value
            el.tempoFollowText = false
        }
        c.add(el)
        if (kind === "CLEF")
            return
        el.text = text
        if (kind === "DYNAMIC")
            el.dynamicType = value
        if (kind === "TEMPO_TEXT")
            el.tempo = value
        el.color = ideaColor
    }

    function measureStart(tick) {
        var start = 0
        for (var m = curScore.firstMeasure; m && m.firstSegment.tick <= tick; m = m.nextMeasure)
            start = m.firstSegment.tick
        return start
    }

    function chordEnding(track, end) {
        var c = curScore.newCursor()
        c.track = track - track % 4
        c.rewindToTick(measureStart(end - 1))
        c.track = track
        var found = null
        for (; c.segment && c.tick < end; c.next()) {
            var e = c.element
            if (e && e.type === Element.CHORD && c.tick + e.actualDuration.ticks === end)
                found = e
        }
        if (!found)
            throw "no note in track " + track + " ends at tick " + end
        return found
    }

    function lastGrace(track, tick) {
        var gs = elementAt(track, tick).graceNotes
        for (var g = gs ? gs.length - 1 : -1; g >= 0; g--) {
            if (gs[g].noteType < 32)
                return gs[g]
        }
        throw "no grace note in track " + track + " at tick " + tick
    }

    function addSlur(track, tick, track2, end, grace, color) {
        var first = elementAt(track, tick)
        if (first.type !== Element.CHORD)
            throw "a slur starts on a note; track " + track + " has a rest at tick " + tick
        var last = grace ? lastGrace(track2, end) : chordEnding(track2, end)
        var start = first.notes[0]
        if (track2 === track && (grace ? end === tick : last.fraction.ticks === tick)) {
            if (!first.graceNotes || !first.graceNotes.length || grace && first.graceNotes.length < 2)
                throw "a slur needs two notes; track " + track + " has one at tick " + tick
            start = first.graceNotes[0].notes[0]
        }
        curScore.selection.select(start)
        curScore.selection.select(last.notes[0], true)
        cmd("add-slur")
        cmd("escape")
        var sp = spannerList()
        for (var i = 0; i < sp.length; i++) {
            if (sp[i].name === "Slur" && sp[i].track === track && sp[i].spannerTick.ticks === tick)
                sp[i].color = color
        }
    }

    function addLine(w) {
        var track = parseInt(w[1]), tick = parseInt(w[2]), track2 = parseInt(w[3]), end = parseInt(w[4])
        var kind = w[6], sub = parseInt(w[7]), text = unescapeText(w.slice(8).join(" "))
        if (kind === "SLUR") {
            addSlur(track, tick, track2, end, w[5] === "1", ideaColor)
            return
        }
        var el = newElement(Element[kind])
        if (kind === "HAIRPIN") {
            el.hairpinType = sub
            if (sub >= 2) {
                el.beginText = sub === 2 ? "cresc." : "dim."
                el.continueText = sub === 2 ? "(cresc.)" : "(dim.)"
            }
        } else if (kind === "OTTAVA") {
            el.ottavaType = sub
        } else if (kind === "TRILL") {
            el.trillType = sub
        } else if (kind === "VIBRATO") {
            el.vibratoType = sub
        } else if (text) {
            el.beginText = text
        }
        el.spannerTick = fraction(tick, division * 4)
        el.spannerTicks = fraction(end - tick, division * 4)
        if (track2 !== track)
            el.spannerTrack2 = track2
        var c = curScore.newCursor()
        c.filter = Segment.EndBarLine
        c.track = track - track % 4
        c.rewind(Cursor.SCORE_START)
        while (c.segment && c.tick <= tick)
            c.next()
        c.track = track
        if (!c.segment)
            throw "no bar line at the end of the bar at tick " + tick
        c.add(el)
        el.color = ideaColor
    }

    function decorate(track, tick, pitch, what, value) {
        if ((what === "fermata" || what === "breath" || what === "art") && SymId[value] === undefined)
            throw "MuseScore has no symbol " + value
        if (what === "fermata" || what === "breath") {
            var c = cursorAt(track, tick)
            var mark = newElement(what === "fermata" ? Element.FERMATA : Element.BREATH)
            mark.symbol = SymId[value]
            c.add(mark)
            return
        }
        if (pitch !== "-") {
            var n = noteAt(track, tick, parseInt(pitch))
            if (what === "head") {
                n.headGroup = parseInt(value)
            } else if (what === "finger") {
                finger(n, "F" + encodeURIComponent(value))
            } else {
                curScore.selection.select(n)
                cmd(what === "lv" ? "lv" : "add-parentheses")
            }
            return
        }
        var chord = elementAt(track, tick)
        if (what === "move") {
            chord.staffMove = parseInt(value)
            return
        }
        if (what === "stem") {
            chord.stemDirection = parseInt(value)
            return
        }
        if (what === "beam") {
            chord.beamMode = parseInt(value)
            return
        }
        var el
        if (what === "art") {
            el = newElement(value.indexOf("ornament") === 0 ? Element.ORNAMENT : Element.ARTICULATION)
            el.symbol = SymId[value]
        } else if (what === "arp") {
            el = newElement(Element.ARPEGGIO)
            el.arpeggioType = parseInt(value)
        } else {
            el = newElement(Element.TREMOLO_SINGLECHORD)
            el.tremoloType = parseInt(value)
        }
        chord.add(el)
    }

    function lyricOf(chord, verse) {
        for (var y = 0; chord.lyrics && y < chord.lyrics.length; y++) {
            if (chord.lyrics[y].verse === verse)
                return chord.lyrics[y]
        }
        return null
    }

    function chordBefore(track, tick, wanted) {
        var m = curScore.firstMeasure
        while (m.nextMeasure && m.nextMeasure.firstSegment.tick <= tick)
            m = m.nextMeasure
        for (; m; m = m.prevMeasure) {
            for (var seg = m.lastSegment; seg; seg = seg.prevInMeasure) {
                var el = seg.tick <= tick ? seg.elementAt(track) : null
                var found = el && el.type === Element.CHORD ? wanted(el) : null
                if (found)
                    return [seg.tick, found]
            }
        }
        return null
    }

    function lyricBefore(track, tick, verse) {
        return chordBefore(track, tick, function(chord) { return lyricOf(chord, verse) })
    }

    function hold(ly, track, tick, bound) {
        var c = curScore.newCursor()
        c.track = track
        c.rewindToTick(tick)
        var last = tick
        for (c.next(); c.segment && c.tick <= bound; c.next()) {
            if (c.element && c.element.type === Element.CHORD)
                last = c.tick
        }
        ly.lyricTicks = fraction(last - tick, division * 4)
    }

    function setLyric(track, tick, verse, continues, bound, text) {
        var chord = elementAt(track, tick)
        if (chord.type !== Element.CHORD)
            throw "a syllable goes on a note; track " + track + " has a rest at tick " + tick
        var old = lyricOf(chord, verse)
        if (old)
            removeElement(old)
        var before = lyricBefore(track, tick - 1, verse)
        var joined = before !== null && (before[1].syllabic === 1 || before[1].syllabic === 3)
        var ly = newElement(Element.LYRICS)
        ly.verse = verse
        cursorAt(track, tick).add(ly)
        ly.text = text
        ly.syllabic = continues ? (joined ? 3 : 1) : (joined ? 2 : 0)
        hold(ly, track, tick, bound)
        ly.color = ideaColor
    }

    function unword(s) {
        return s === "-" ? "" : unescapeText(s.replace(/\\s/g, " "))
    }

    function measureAt(tick) {
        var m = curScore.firstMeasure
        while (m.nextMeasure && m.nextMeasure.firstSegment.tick <= tick)
            m = m.nextMeasure
        return m
    }

    function annotationTexts(from, texts) {
        for (var am = from; am; am = am.nextMeasure) {
            for (var seg = am.firstSegment; seg; seg = seg.nextInMeasure) {
                var ann = seg.annotations
                var seen = {}
                for (var a = 0; ann && a < ann.length; a++) {
                    var key = seg.tick + " " + ann[a].track + " " + ann[a].name
                    seen[key] = (seen[key] || 0) + 1
                    key += " " + seen[key]
                    if (texts[key] === undefined)
                        texts[key] = ann[a].text
                    else if (texts[key] !== ann[a].text)
                        ann[a].text = texts[key]
                }
            }
        }
        return texts
    }

    function rehang(before, after) {
        for (var i = 0; i < before.length; i++) {
            var o = before[i].split(" ")
            if (o[5] !== "Slur" || o[2].slice(-1) !== "g" || after.indexOf(before[i]) >= 0)
                continue
            for (var j = 0; j < after.length; j++) {
                var n = after[j].split(" ")
                if (n[5] === "Slur" && n[1] === o[1] && n[3] === o[3] && before.indexOf(after[j]) < 0) {
                    removeSpanner(parseInt(n[1]), parseInt(n[3]), parseInt(n[2]), "Slur")
                    addSlur(parseInt(o[3]), parseInt(o[1]), parseInt(o[4]), parseInt(o[2]), true, "#000000")
                    break
                }
            }
        }
    }

    function keySigAt(staff, tick, exact) {
        var found = null
        for (var km = curScore.firstMeasure; km && km.firstSegment.tick <= tick; km = km.nextMeasure) {
            for (var seg = km.firstSegment; seg; seg = seg.nextInMeasure) {
                if (seg.segmentType === Segment.KeySig && seg.elementAt(staff * 4) && (exact ? seg.tick === tick : seg.tick <= tick))
                    found = seg.elementAt(staff * 4)
            }
        }
        return found
    }

    function barChange(tick, w) {
        var m = measureAt(tick)
        var what = w[0]
        if (what === "rep") {
            m.repeatStart = w[1] === "1"
            m.repeatEnd = w[2] === "1"
            m.repeatCount = parseInt(w[3])
            return
        }
        if (what === "bar") {
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                if (seg.segmentType !== Segment.EndBarLine)
                    continue
                for (var s = 0; s < curScore.nstaves; s++) {
                    var bl = seg.elementAt(s * 4)
                    if (bl)
                        bl.barlineType = parseInt(w[1])
                }
            }
            return
        }
        if (what === "len") {
            m.timesigActual = fraction(parseInt(w[1]), parseInt(w[2]))
            return
        }
        if (what === "meter" || what === "meter-") {
            var texts = annotationTexts(m.prevMeasure || m, {})
            var slurs = spannerLines(tick, 2147483647)
            if (what === "meter") {
                var ts = newElement(Element.TIMESIG)
                ts.timesig = fraction(parseInt(w[1]), parseInt(w[2]))
                var tc = curScore.newCursor()
                tc.track = 0
                tc.rewindToTick(tick)
                tc.add(ts)
            } else {
                var found = null
                for (var ms = m.firstSegment; ms && !found; ms = ms.nextInMeasure) {
                    if (ms.segmentType === Segment.TimeSig && ms.elementAt(0))
                        found = ms.elementAt(0)
                }
                if (!found)
                    throw "no time signature at tick " + tick
                removeElement(found)
            }
            var back = measureAt(tick)
            annotationTexts(back.prevMeasure || back, texts)
            rehang(slurs, spannerLines(tick, 2147483647))
            return
        }
        if (what === "key" || what === "key-") {
            for (var st = 0; st < curScore.nstaves; st++) {
                if (what === "key-") {
                    var gone = keySigAt(st, tick, true)
                    if (!gone)
                        throw "no key signature at tick " + tick + " on staff " + st
                    removeElement(gone)
                    continue
                }
                var last = keySigAt(st, tick, false)
                var concert = parseInt(w[1])
                var written = concert + (last ? last.actualKey - last.concertKey : 0)
                written += written > 7 ? -12 : written < -7 ? 12 : 0
                if (last && last.parent.tick === tick)
                    removeElement(last)
                var ks = newElement(Element.KEYSIG)
                ks.concertKey = concert
                ks.actualKey = written
                var kc = curScore.newCursor()
                kc.track = st * 4
                kc.rewindToTick(tick)
                kc.add(ks)
            }
            return
        }
        if (what === "volta-") {
            var sp = curScore.spanners
            for (var i = 0; sp && i < sp.length; i++) {
                var v = sp[i]
                if (v.type === Element.VOLTA && v.spannerTick.ticks <= tick && tick < v.spannerTick.ticks + v.spannerTicks.ticks) {
                    removeElement(v)
                    return
                }
            }
            throw "no volta over tick " + tick
        }
        var el
        if (what === "break+") {
            el = newElement(Element.LAYOUT_BREAK)
            el.layoutBreakType = parseInt(w[1])
        } else if (what === "jump+") {
            el = newElement(Element.JUMP)
            el.text = unescapeText(w.slice(4).join(" "))
            el.jumpTo = unword(w[1])
            el.playUntil = unword(w[2])
            el.continueAt = unword(w[3])
        } else if (what === "mark+") {
            el = newElement(Element.MARKER)
            el.markerType = parseInt(w[1])
        }
        if (el) {
            var c = curScore.newCursor()
            c.track = 0
            c.rewindToTick(m.firstSegment.tick)
            c.add(el)
            return
        }
        var els = m.elements
        for (var j = 0; els && j < els.length; j++) {
            var e = els[j]
            if (what === "break-" && e.type === Element.LAYOUT_BREAK && e.layoutBreakType === parseInt(w[1])
                    || what === "jump-" && e.type === Element.JUMP && e.jumpTo === unword(w[1]) && e.playUntil === unword(w[2])
                        && e.continueAt === unword(w[3])
                    || what === "mark-" && e.type === Element.MARKER && e.markerType === parseInt(w[1])) {
                removeElement(e)
                return
            }
        }
        throw "no " + w.join(" ") + " in the bar at tick " + tick
    }

    function finger(n, field) {
        if (!field)
            return
        var f = newElement(Element.FINGERING)
        n.add(f)
        f.text = decodeURIComponent(field.substring(1))
    }

    function respell(n, tpc, color) {
        var transposition = n.tpc2 - n.tpc1
        n.tpc1 = tpc
        n.tpc2 = tpc + transposition
        n.color = color
    }

    function write(id, startTick, endTick, label, ops) {
        var c = null, track = 0, step = 0, chords = [], rests = [], changed = false
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
                    if (w.length > 1)
                        rests.push([track, parseInt(w[1])])
                } else if (w[0] === "m") {
                    curScore.appendMeasures(parseInt(w[1]))
                } else if (w[0] === "x") {
                    changed = clearVoice(parseInt(w[1]), parseInt(w[2]), parseInt(w[3]), w[4] === "1") || changed
                } else if (w[0] === "t") {
                    var ratio = w[1].split(":"), total = w[2].split("/")
                    c.addTuplet(fraction(parseInt(ratio[0]), parseInt(ratio[1])), fraction(parseInt(total[0]), parseInt(total[1])))
                } else if (w[0] === "l" && w[6] === "OTTAVA") {
                    addLine(w)
                } else if (w[0] === "z") {
                    removeSpanner(parseInt(w[1]), parseInt(w[2]), parseInt(w[3]), w[4])
                } else if (w[0] === "y") {
                    removeMark(w.slice(1).join(" "))
                } else if (w[0] === "b") {
                    barChange(parseInt(w[1]), w.slice(2))
                } else {
                    break
                }
                changed = changed || "vdx".indexOf(w[0]) < 0
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
                    var gp = o[4].split(",")[0].split(":")
                    var gs = chord.graceNotes
                    var added = null
                    for (var g = 0; gs && g < gs.length && !added; g++) {
                        if (gs[g].notes[0].pitch === main.pitch)
                            added = gs[g].notes[0]
                    }
                    if (!added)
                        throw o[3] + " added no grace note"
                    var gns = o[4].split(",")
                    added.pitch = parseInt(gp[0]) - offsetAt(otrack, otick)
                    respell(added, parseInt(gp[1]), ideaColor)
                    finger(added, gp[2])
                    for (var q = 1; q < gns.length; q++) {
                        var more = newElement(Element.NOTE)
                        var mp = gns[q].split(":")
                        more.pitch = parseInt(mp[0]) - offsetAt(otrack, otick)
                        added.parent.add(more)
                        respell(more, parseInt(mp[1]), ideaColor)
                        finger(more, mp[2])
                    }
                } else if (o[0] === "a") {
                    addMark(otrack, otick, o[3], parseFloat(o[4]), unescapeText(o.slice(5).join(" ")))
                } else if (o[0] === "e") {
                    decorate(otrack, otick, o[3], o[4], o.slice(5).join(" "))
                } else if (o[0] === "l") {
                    addLine(o)
                } else if (o[0] === "b") {
                    barChange(parseInt(o[1]), o.slice(2))
                } else if (o[0] === "^") {
                    var from = chordBefore(otrack, otick - 1, function(chord) { return chord })
                    if (!from)
                        throw "no note before tick " + otick + " in track " + otrack + " to tie from"
                    var back = noteAt(otrack, from[0], parseInt(o[3]))
                    if (!back.tieForward) {
                        curScore.selection.select(back)
                        cmd("tie")
                    }
                    if (!back.tieForward)
                        throw "tie not made"
                } else if (o[0] === "w") {
                    setLyric(otrack, otick, parseInt(o[3]), o[4] === "1", parseInt(o[5]), unescapeText(o.slice(6).join(" ")))
                } else if (o[0] === "u") {
                    var gone = lyricOf(elementAt(otrack, otick), parseInt(o[3]))
                    if (!gone)
                        throw "no syllable in track " + otrack + " at tick " + otick
                    removeElement(gone)
                } else if (o[0] === "h") {
                    var held = lyricBefore(otrack, otick, parseInt(o[3]))
                    if (!held)
                        throw "no syllable before tick " + otick + " in track " + otrack + " to hold"
                    hold(held[1], otrack, held[0], parseInt(o[4]))
                } else if (o[0] === "~") {
                    if (o[4] && !noteAt(otrack, parseInt(o[4]), parseInt(o[3])))
                        throw "no note to tie to"
                    var n = noteAt(otrack, otick, parseInt(o[3]))
                    if (!n.tieForward) {
                        curScore.selection.select(n)
                        cmd("tie")
                    }
                    if (!n.tieForward)
                        throw "tie not made"
                } else if (o[0] === "k") {
                    deleteRests(otrack, otick, parseInt(o[3]))
                } else {
                    throw "unknown op " + o[0]
                }
                changed = true
            }
        } catch (e) {
            curScore.endCmd(true)
            if (changed)
                cmd("action://notation/undo")
            return id + " err write-failed " + step + " " + escapeText(e)
        }
        curScore.endCmd(false)
        var staves = ops.filter(function(op) { return op[0] === "v" }).map(function(op) { return Math.floor(parseInt(op.split(" ")[1]) / 4) })
        if (staves.length) {
            var first = Math.min.apply(null, staves), last = Math.max.apply(null, staves) + 1
            curScore.selection.selectRange(startTick, endTick, first, last)
            cmd("notation-move-left")
            curScore.selection.selectRange(startTick, endTick, first, last)
        } else
            curScore.selection.clear()
        return [id + " ok"].concat(read(startTick, endTick)).join("\n")
    }

    function recolor(startTick, endTick, tracks, color, label) {
        curScore.startCmd("Reflets: " + label)
        var sp = spannerList()
        for (var i = 0; i < sp.length; i++) {
            if (!(sp[i].systemFlag && tracks.indexOf(0) < 0) && spannerIn(sp[i], tracks, startTick, endTick))
                sp[i].color = color
        }
        for (var m = curScore.firstMeasure; m; m = m.nextMeasure) {
            var mt = m.firstSegment.tick
            if (mt < startTick)
                continue
            if (mt >= endTick)
                break
            for (var seg = m.firstSegment; seg; seg = seg.nextInMeasure) {
                var ann = seg.annotations
                for (var a = 0; ann && a < ann.length; a++) {
                    if (tracks.indexOf(ann[a].track) >= 0 && ann[a].name !== "Fermata")
                        ann[a].color = color
                }
                for (var t = 0; t < tracks.length; t++) {
                    var el = seg.elementAt(tracks[t])
                    if (!el)
                        continue
                    if (el.type === Element.REST)
                        el.color = color
                    if (el.type !== Element.CHORD)
                        continue
                    for (var y = 0; el.lyrics && y < el.lyrics.length; y++)
                        el.lyrics[y].color = color
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
            status("Claude connected")
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
        if (verb === "write") {
            var reply = write(id, parseInt(head[2]), parseInt(head[3]), head.slice(4).join(" "), lines.slice(1))
            status((reply.indexOf(id + " ok") === 0 ? "wrote " : "could not write ") + head.slice(4).join(" "))
            return reply
        }
        if (verb === "color") {
            recolor(parseInt(head[2]), parseInt(head[3]), head[4].split(",").map(Number), head[5], head.slice(6).join(" "))
            status("kept " + head.slice(6).join(" "))
            return id + " ok"
        }
        if (verb === "export")
            return id + (writeScore(curScore, head.slice(2).join(" "), "musicxml") ? " ok" : " err export-failed writeScore returned false")
        if (verb === "undo" || verb === "redo") {
            cmd("action://notation/" + verb)
            status(verb)
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
        if (typeof ui !== "undefined" && ui && ui.rootItem) {
            pill.parent = ui.rootItem
            badgeInMain = true
        }
        status("listening")
        api.log.info("reflets-bridge " + version + ": listening on " + port + ", token file " + tokenFile.source
            + (written ? "" : " (WRITE FAILED)"))
    }
}
