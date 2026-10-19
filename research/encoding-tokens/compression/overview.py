"""Overview views (idea 4): per bar the top line, plus the bass per beat (V1) or the bass and pitch classes per beat (V2).

Lossy by design. Usage: uv run --with verovio python overview.py   (writes variants/<score>.V1.txt and .V2.txt)

top:   the highest note attacked at each onset, across all staves, skipped while a higher earlier note still
       sounds; written as an N1 voice (durations clipped at the next top note; gaps as rests).
bass:  the lowest note sounding at the start of each beat (held notes count), `r` if nothing sounds.
beats: per beat `|`-separated, the bass with its octave, then the other pitch classes sounding in that beat, low to high.
"""
from fractions import Fraction
from pathlib import Path

from build import DATA, SCORES, load
from engine.reduce import midi

HERE = Path(__file__).resolve().parent


def _units(x, div):
    return int(x * div)


def top_line(measure, div):
    notes = [e for e in measure.events if e.pitch and not e.grace]
    kept = []
    for t in sorted({e.onset for e in notes}):
        top = max((e for e in notes if e.onset == t), key=lambda e: midi(e.pitch))
        if any(e.onset < t < e.onset + e.duration and midi(e.pitch) > midi(top.pitch) for e in notes):
            continue
        kept.append(top)
    toks, cursor, cur = [], Fraction(0), None
    for i, e in enumerate(kept):
        if e.onset > cursor:
            toks += [str(_units(e.onset - cursor, div)), "r"]
            cur = _units(e.onset - cursor, div)
        end = min(e.onset + e.duration, kept[i + 1].onset) if i + 1 < len(kept) else e.onset + e.duration
        d = _units(end - e.onset, div)
        if d != cur:
            toks.append(str(d))
            cur = d
        toks.append(e.pitch + ("~" if e.tied and end == e.onset + e.duration else ""))
        cursor = end
    return " ".join(toks)


def beats(measure):
    notes = [e for e in measure.events if e.pitch and not e.grace]
    n = int(measure.length / measure.beat_length + Fraction(95, 96)) if measure.length else 0
    bass, harm = [], []
    for b in range(n):
        start, end = b * measure.beat_length, (b + 1) * measure.beat_length
        at = sorted((e for e in notes if e.onset <= start < e.onset + e.duration), key=lambda e: midi(e.pitch))
        bass.append(at[0].pitch if at else "r")
        inside = sorted((e for e in notes if e.onset < end and e.onset + e.duration > start), key=lambda e: midi(e.pitch))
        if not inside:
            harm.append("r")
            continue
        low = at[0] if at else inside[0]
        classes = []
        for e in inside:
            pc = e.pitch.rstrip("0123456789")
            if pc != low.pitch.rstrip("0123456789") and pc not in classes:
                classes.append(pc)
        harm.append(" ".join([low.pitch] + classes))
    return bass, harm


def overview(index, with_classes):
    div = index.ppq
    lines = [f"overview div={div} ts={index.meter} ks={index.key_signature or '0'}"]
    for m in index.measures:
        lines.append(f"m{m.number} len={_units(m.length, div)}")
        lines.append("top: " + top_line(m, div))
        bass, harm = beats(m)
        lines.append("beats: " + " | ".join(harm) if with_classes else "bass: " + " ".join(bass))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    out = HERE / "variants"
    out.mkdir(exist_ok=True)
    for name, file in SCORES.items():
        index = load(DATA / file)
        for v, flag in (("V1", False), ("V2", True)):
            (out / f"{name}.{v}.txt").write_text(overview(index, flag))
        print(name, "beat", index.measures[-1].beat_length)
