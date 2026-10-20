import json
from pathlib import Path

import codecs_n1 as c

HERE = Path(__file__).resolve().parent
VARIANTS = ["R", "P", "O", "Oc", "RP", "RO", "PO", "RPO", "RT"]

if __name__ == "__main__":
    out = HERE / "variants"
    out.mkdir(exist_ok=True)
    rows = ["score\tvariant\tlossless\tchars\t" + "\t".join(c.stats("").keys())]
    for path in sorted((HERE / "n1").glob("*.n1.txt")):
        n1 = path.read_text()
        score = path.name.removesuffix(".n1.txt")
        head, bars = c.parse(n1)
        for _, _, voices in bars:
            for label, body in voices:
                assert c.normalise(body) == body, (score, label, body)
        for v in VARIANTS:
            text = c.encode(n1, v)
            (out / f"{score}.{v}.txt").write_text(text)
            ok = c.decode(text, v) == n1
            rows.append(f"{score}\t{v}\t{ok}\t{len(text)}\t" + "\t".join(str(x) for x in c.stats(text).values()))
            print(rows[-1])
    (HERE / "lossless.tsv").write_text("\n".join(rows) + "\n")
