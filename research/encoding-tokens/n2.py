from __future__ import annotations

import argparse
import os
import base64
import json
import sys
import zipfile
import xml.etree.ElementTree as ET
from fractions import Fraction
from importlib.resources import files
from pathlib import Path

ENGINE = Path(os.environ.get("SHEET_MUSIC_REPO", Path(__file__).resolve().parents[3] / "sheet-music-analysis"))
sys.path.insert(0, str(ENGINE))
import verovio  # noqa: E402

from engine.score import Event, ScoreIndex  # noqa: E402

VERSION = "N2"
KINDS = {
    "major": "", "minor": "m", "augmented": "+", "diminished": "dim", "dominant": "7", "major-seventh": "maj7",
    "minor-seventh": "m7", "diminished-seventh": "dim7", "augmented-seventh": "+7", "half-diminished": "m7b5",
    "major-minor": "mMaj7", "major-sixth": "6", "minor-sixth": "m6", "dominant-ninth": "9", "major-ninth": "maj9",
    "minor-ninth": "m9", "suspended-fourth": "sus4", "suspended-second": "sus2", "power": "5", "none": "N.C.",
}


def load(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    if data[:2] == b"PK":
        with zipfile.ZipFile(path) as z:
            name = [n for n in z.namelist() if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF")][0]
            return z.read(name).decode("utf-8"), data
    return data.decode("utf-8-sig"), data


def index_of(data: bytes, xml: str) -> ScoreIndex:
    tk = verovio.toolkit(False)
    tk.setResourcePath(str(files("verovio") / "data"))
    tk.setOptions({"xmlIdChecksum": True})
    ok = tk.loadZipDataBase64(base64.b64encode(data).decode()) if data[:2] == b"PK" else tk.loadData(xml)
    assert ok, "Verovio could not read the score"
    return ScoreIndex(tk.getMEI())


def read_markup(xml: str, words: bool) -> tuple[list[tuple[str, int, int]], dict, dict]:
    root = ET.fromstring(xml)
    names = {p.get("id"): (p.findtext("part-name") or p.get("id")).strip() for p in root.iter("score-part")}
    parts: list[tuple[str, int, int]] = []
    dynamics: dict[tuple[int, int], list[tuple[Fraction, str]]] = {}
    chords: dict[int, list[tuple[Fraction, str]]] = {}
    first_staff = 1
    for part in root.findall("part"):
        divisions = 1
        staves = 1
        for measure in part.findall("measure"):
            number = int(measure.get("number", "0").lstrip("X") or 0)
            cursor = Fraction(0)
            for child in measure:
                tag = child.tag
                if tag == "attributes":
                    if child.findtext("divisions"):
                        divisions = int(child.findtext("divisions"))
                    if child.findtext("staves"):
                        staves = int(child.findtext("staves"))
                elif tag == "backup":
                    cursor -= Fraction(int(child.findtext("duration")), divisions)
                elif tag == "forward":
                    cursor += Fraction(int(child.findtext("duration")), divisions)
                elif tag == "note":
                    if child.find("chord") is None and child.find("grace") is None:
                        cursor += Fraction(int(child.findtext("duration")), divisions)
                elif tag == "direction":
                    staff = first_staff + int(child.findtext("staff") or 1) - 1
                    onset = cursor + Fraction(int(child.findtext("offset") or 0), divisions)
                    for kind in child.findall("direction-type"):
                        for dyn in kind.findall("dynamics"):
                            for mark in dyn:
                                dynamics.setdefault((number, staff), []).append((onset, mark.tag if mark.tag != "other-dynamics" else mark.text))
                        for wedge in kind.findall("wedge"):
                            symbol = {"crescendo": "<", "diminuendo": ">", "stop": "!"}.get(wedge.get("type"))
                            if symbol:
                                dynamics.setdefault((number, staff), []).append((onset, symbol))
                        if words:
                            for text in kind.findall("words"):
                                if text.text and text.text.strip():
                                    dynamics.setdefault((number, staff), []).append((onset, '"' + text.text.strip() + '"'))
                elif tag == "harmony":
                    onset = cursor + Fraction(int(child.findtext("offset") or 0), divisions)
                    chords.setdefault(number, []).append((onset, chord_symbol(child)))
        parts.append((names[part.get("id")], first_staff, first_staff + staves - 1))
        first_staff += staves
    return parts, dynamics, chords


def chord_symbol(harmony: ET.Element) -> str:
    def pitch(element: ET.Element | None, step: str, alter: str) -> str:
        if element is None:
            return ""
        letter = element.findtext(step) or ""
        semitones = int(float(element.findtext(alter) or 0))
        return letter + ("#" * semitones if semitones > 0 else "b" * -semitones)

    kind = harmony.find("kind")
    suffix = (kind.get("text") if kind is not None and kind.get("text") is not None else KINDS.get(kind.text if kind is not None else "major", kind.text if kind is not None else ""))
    symbol = pitch(harmony.find("root"), "root-step", "root-alter") + suffix
    bass = pitch(harmony.find("bass"), "bass-step", "bass-alter")
    return symbol + ("/" + bass if bass else "")


def units(value: Fraction, div: int) -> int:
    assert (value * div).denominator == 1, value
    return int(value * div)


def encode(index: ScoreIndex, parts, dynamics, chords, inline: bool) -> str:
    div = index.ppq
    lines = [f"{VERSION} div={div} ts={index.meter} ks={index.key_signature or '0'}"]
    if parts:
        lines.append("parts: " + "; ".join(f"{a}-{b} {name}" if a != b else f"{a} {name}" for name, a, b in parts))
    meter = index.meter
    for measure in index.measures:
        header = f"m{measure.number} len={units(measure.length, div)}"
        if measure.meter and measure.meter != meter:
            meter = measure.meter
            header += f" ts={meter}"
        lines.append(header)
        voices: dict[tuple[int, int], list[Event]] = {}
        for event in measure.events:
            voices.setdefault((event.staff, event.layer), []).append(event)
        pending = {staff: list(marks) for (number, staff), marks in dynamics.items() if number == measure.number}
        for (staff, layer), events in sorted(voices.items()):
            marks = pending.get(staff, []) if inline else []
            attach: dict[Fraction, list[str]] = {}
            onsets = {e.onset for e in events if e.pitch and not e.grace}
            for onset, mark in list(marks):
                if onset in onsets:
                    attach.setdefault(onset, []).append(mark)
                    marks.remove((onset, mark))
            lines.append(f"{staff}.{layer}: " + voice(events, div, attach))
        for staff in sorted(pending):
            marks = pending[staff]
            if marks:
                lines.append(f"d{staff}: " + " ".join(f"{units(onset, div)} {mark}" for onset, mark in sorted(marks, key=lambda m: m[0])))
        if measure.number in chords:
            lines.append("h: " + " ".join(f"{units(onset, div)} {symbol}" for onset, symbol in sorted(chords[measure.number], key=lambda c: c[0])))
    return "\n".join(lines)


def voice(events: list[Event], div: int, attach: dict[Fraction, list[str]]) -> str:
    tokens: list[str] = []
    cursor, current = Fraction(0), None
    groups: dict[tuple[Fraction, bool, str, bool], list[Event]] = {}
    for event in events:
        key = (event.onset, event.grace, event.attack if event.grace else "", event.pitch is None)
        groups.setdefault(key, []).append(event)
    for onset, grace, attack, rest in sorted(groups, key=lambda key: (key[0], not key[1], key[3])):
        group = groups[(onset, grace, attack, rest)]
        if onset > cursor:
            gap = units(onset - cursor, div)
            tokens += [str(gap), "r"]
            current, cursor = gap, onset
        if grace:
            tokens.append("g" + "+".join(e.pitch + ("~" if e.tied else "") for e in group))
            continue
        duration = units(group[0].duration, div)
        if duration != current:
            tokens.append(str(duration))
            current = duration
        if rest:
            tokens.append("r")
        else:
            names = "+".join(e.pitch + ("~" if e.tied else "") for e in group)
            marks = attach.get(onset)
            tokens.append(("[" + ",".join(marks) + "]" if marks else "") + names)
        cursor = onset + group[0].duration
    return " ".join(tokens)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("score", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--inline", action="store_true")
    parser.add_argument("--words", action="store_true")
    parser.add_argument("--chords", type=Path)
    parser.add_argument("--no-dynamics", action="store_true")
    parser.add_argument("--no-parts", action="store_true")
    args = parser.parse_args()
    xml, data = load(args.score)
    index = index_of(data, xml)
    parts, dynamics, chords = read_markup(xml, args.words)
    if args.chords:
        for measure, onset, symbol in json.loads(args.chords.read_text()):
            chords.setdefault(measure, []).append((Fraction(onset, index.ppq), symbol))
    if args.no_dynamics:
        dynamics = {}
    if args.no_parts:
        parts = []
    text = encode(index, parts, dynamics, chords, args.inline)
    args.out.write_text(text + "\n")
    print(args.out.name, len(text), "chars;", sum(len(v) for v in dynamics.values()), "dynamic marks;", sum(len(v) for v in chords.values()), "chord symbols")


if __name__ == "__main__":
    main()
