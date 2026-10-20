from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
t = defaultdict(dict)
for line in (HERE / "counts.tsv").read_text().splitlines()[2:]:
    score, v, tokens, _ = line.split("\t")
    t[score][v] = int(tokens)
variants = list(next(iter(t.values())))
print("| Score | " + " | ".join(variants) + " |")
print("|---" * (len(variants) + 1) + "|")
for score in list(t) + ["total"]:
    row = t[score] if score != "total" else {v: sum(t[s][v] for s in t) for v in variants}
    cells = [f"{row['N1']:,}"] + [f"{row[v]:,} ({100 * (row['N1'] - row[v]) / row['N1']:+.0f}%)".replace("(+", "(-").replace("(--", "(+") for v in variants[1:]]
    print(f"| {score} | " + " | ".join(cells) + " |")
