"""Diagnostic for transposed figures inside a voice line (not encoded): split each voice line into beats and count
beats that repeat the previous beat exactly, or transposed by a spelled interval. Only beats with at least three
pitches count, since a one- or two-note beat is trivially a transposition of another. Writes figures.tsv."""
from pathlib import Path

import codecs_n1 as c
from engine.score import beat_length

HERE = Path(__file__).resolve().parent
rows = ["score\tbeats_with_3+_pitches\texact_repeat_of_previous_beat\ttransposed_previous_beat"]
for path in sorted((HERE / "n1").glob("*.n1.txt")):
    head, bars = c.parse(path.read_text())
    settings = dict(p.split("=", 1) for p in head.split()[1:])
    div, ts = int(settings["div"]), settings["ts"]
    beat = int(beat_length(*map(int, ts.split("/"))) * div) if ts else div
    total = exact = moved = 0
    for header, _, voices in bars:
        if "ts=" in header:
            ts = header.split("ts=")[1]
            beat = int(beat_length(*map(int, ts.split("/"))) * div)
        for _, body in voices:
            chunks, onset = {}, 0
            for d, tok in c.items(body):
                chunks.setdefault(onset // beat, []).append((d, tok))
                if d != "g":
                    onset += d
            prev = None
            for k in sorted(chunks):
                text = " ".join(c.render(chunks[k])[0])
                if len(c._pitches(text)) < 3:
                    prev = None
                    continue
                total += 1
                if prev is not None:
                    if text == prev:
                        exact += 1
                    elif c._transposition(prev, text):
                        moved += 1
                prev = text
    rows.append(f"{path.name.removesuffix('.n1.txt')}\t{total}\t{exact}\t{moved}")
(HERE / "figures.tsv").write_text("\n".join(rows) + "\n")
print("\n".join(rows))
