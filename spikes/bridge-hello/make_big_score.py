"""Throwaway: write a synthetic orchestral-size MusicXML for the read-speed spike (spec 10, item 4).

    python3 make_big_score.py out.musicxml [bars] [parts]

Every part plays eighth notes in every bar (bars x parts x 8 notes). Part 1 carries a chord symbol
per bar and a dynamic every 8 bars, so the read path also meets annotations.
"""

import sys

STEPS = ["C", "D", "E", "F", "G", "A", "B"]
HARMONY = [("C", "major"), ("A", "minor"), ("F", "major"), ("G", "dominant")]


def note(step, octave):
    return (f"<note><pitch><step>{step}</step><octave>{octave}</octave></pitch>"
            f"<duration>1</duration><type>eighth</type></note>")


def main(out, bars=300, parts=16):
    x = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
         '"http://www.musicxml.org/dtds/partwise.dtd">',
         '<score-partwise version="4.0"><work><work-title>Reflets big score</work-title></work><part-list>']
    for p in range(parts):
        x.append(f'<score-part id="P{p + 1}"><part-name>Part {p + 1}</part-name></score-part>')
    x.append("</part-list>")
    for p in range(parts):
        x.append(f'<part id="P{p + 1}">')
        octave = 5 - (p * 3) // parts
        for b in range(bars):
            x.append(f'<measure number="{b + 1}">')
            if b == 0:
                clef = "<clef><sign>G</sign><line>2</line></clef>" if octave >= 4 else "<clef><sign>F</sign><line>4</line></clef>"
                x.append("<attributes><divisions>2</divisions><key><fifths>0</fifths></key>"
                         f"<time><beats>4</beats><beat-type>4</beat-type></time>{clef}</attributes>")
            if p == 0:
                root, kind = HARMONY[b % len(HARMONY)]
                x.append(f"<harmony><root><root-step>{root}</root-step></root><kind>{kind}</kind></harmony>")
                if b % 8 == 0:
                    x.append('<direction placement="below"><direction-type><dynamics><mf/></dynamics>'
                             "</direction-type></direction>")
            for i in range(8):
                x.append(note(STEPS[(b + i + p) % 7], octave))
            x.append("</measure>")
        x.append("</part>")
    x.append("</score-partwise>")
    with open(out, "w") as f:
        f.write("\n".join(x))


main(sys.argv[1], *(int(a) for a in sys.argv[2:]))
