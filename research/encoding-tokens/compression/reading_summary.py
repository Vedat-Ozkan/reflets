"""Usage: python reading_summary.py [reading|reading-high]. Summarise reading/*.json: per variant correct / null / wrong, the wrong answers, and the cost at $2 / $10 per MTok."""
import json
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
from reading import READ_SET, VARIANTS, grade, questions, text_of

DIR = sys.argv[1] if len(sys.argv) > 1 else "reading"

# answers recomputed with the current rules (a note tied from the previous one is not an attack); the questions must be unchanged
SETS = {s: questions(s, text_of(s, "N1")) for s in READ_SET}
per = defaultdict(lambda: {"correct": 0, "null": 0, "wrong": 0, "in": 0, "out": 0, "wrongs": [], "errors": []})
for f in sorted((HERE / DIR).glob("*.json")):
    d = json.loads(f.read_text())
    p = per[d["variant"]]
    assert d["questions"] == SETS[d["score"]][0]
    stored = d["truth"]  # as asked: a note tied from the previous one counted as an attack
    d["truth"] = SETS[d["score"]][1]
    # either reading of "attacked" for a tied-over note is accepted; only nocturne q7 and prelude q5 differ
    d["grades"] = {q: max(grade(q, d["answers"].get(q), d["truth"][q]), grade(q, d["answers"].get(q), stored[q]), key=["wrong", "null", "correct"].index) for q in d["truth"]}
    for q, g in d["grades"].items():
        p[g] += 1
        if g != "correct":
            p["wrongs"].append(f"{d['score']} {q} ({g}): got {json.dumps(d['answers'].get(q))}, truth {json.dumps(d['truth'][q])}")
    if d["usage"]:
        p["in"] += d["usage"]["in"]
        p["out"] += d["usage"]["out"]
    if d["error"] or d["retries"]:
        p["errors"].append(f"{d['score']}: retries={d['retries']} error={d['error']}")
rows = ["variant\tcorrect\tnull\twrong\tinput_tokens\toutput_tokens\tcost_usd"]
total = 0
for v in VARIANTS:
    p = per[v]
    cost = p["in"] * 2e-6 + p["out"] * 10e-6
    total += cost
    rows.append(f"{v}\t{p['correct']}\t{p['null']}\t{p['wrong']}\t{p['in']}\t{p['out']}\t{cost:.2f}")
print("\n".join(rows))
print(f"total cost ${total:.2f}")
for v in VARIANTS:
    for w in per[v]["wrongs"] + per[v]["errors"]:
        print(v, "|", w)
(HERE / f"{DIR}.tsv").write_text("\n".join(rows) + f"\n# total cost ${total:.2f}\n")
