"""Chord symbols for the Chopin from the AnalysisGNN draft, for measuring the cost of an `h:` line.

The nocturne carries no chord symbols of its own, so these are synthetic: root and quality from the
model's degree and quality predictions (the local key is Eb throughout), one symbol wherever they change.
Output: [[n1_measure, onset_div, symbol], ...]
"""
import json, os, sys
from fractions import Fraction
from pathlib import Path

ENGINE = Path(os.environ.get("SHEET_MUSIC_REPO", Path(__file__).resolve().parents[3] / "sheet-music-analysis"))

raw = json.load(open(ENGINE / "tests/data/chopin_analysisgnn_raw.json"))
notes, tasks = raw["notes"], raw["tasks"]
SCALE = ["Eb", "F", "G", "Ab", "Bb", "C", "D"]  # Eb major
QUALITY = {"major triad": "", "minor triad": "m", "diminished triad": "dim", "dominant seventh chord": "7",
           "half-diminished seventh chord": "m7b5", "diminished seventh chord": "dim7"}
DIV = 48
out, last = [], None
for i in range(len(notes["measure"])):
    degree, quality = tasks["degree1"]["labels"][0][i], tasks["quality"]["labels"][0][i]
    root = SCALE[int(degree.lstrip("#b")) - 1]
    if degree.startswith("#"):
        root = root[0] + ("" if root.endswith("b") else "#")
    symbol = root + QUALITY[quality]
    measure = notes["measure"][i] - 1  # AnalysisGNN counts the pickup as bar 1; N1 calls it m0
    onset = Fraction(notes["offset"][i]).limit_denominator(96)
    if measure == 0:
        onset = Fraction(0)  # the pickup bar holds one eighth; place the symbol at its start
    key = (measure, onset)
    if symbol != last and (not out or out[-1][:2] != [measure, int(onset * DIV)]):
        out.append([measure, int(onset * DIV), symbol])
        last = symbol
json.dump(out, open(sys.argv[1], "w"))
print(len(out), "symbols over", len(set(notes["measure"])), "bars; first:", out[:8])
