"""Can claude-sonnet-5-5 WRITE each compression? It gets the legend and bars 1-8 of a score in N1 and rewrites them in the
compressed form; our decoder expands its text and the result must equal the N1 excerpt exactly.

Usage: uv run --with anthropic python write_test.py   (writes writing/<score>.<variant>.json and writing.tsv)
"""
import json
import re
from pathlib import Path

import anthropic

import codecs_n1 as c
import legends

HERE = Path(__file__).resolve().parent
MODEL, EFFORT = "claude-sonnet-5-5", "medium"
SCORES = ["chopin-nocturne", "mozart-k545-1", "chopin-prelude-4"]
VARIANTS = ["R", "P", "O", "RPO"]
TRIALS = ["", "#2"]  # a second, independent sample of each
FEATURE = {
    "R": "Use a bar reference wherever a bar repeats an earlier bar, and a voice reference wherever only a voice line repeats.",
    "P": "Use a repeat group wherever a voice line repeats a figure in a row.",
    "O": "Drop every octave digit that the relative-octave rule lets you drop.",
    "RPO": "Use references, repeat groups and relative octaves wherever the rules allow.",
}
PROMPT = """This is a compact text encoding of a score. {legend}

Rewrite the score below in this compressed form. {feature} It must expand back to exactly the same notes. Reply with the rewritten text only, in a single code block.

{score}"""


def excerpt(n1, first=1, last=8):
    head, bars = c.parse(n1)
    return c.unparse(head, [b for b in bars if first <= b[1] <= last])


def diff_bars(a, b):
    _, x = c.parse(a)
    _, y = c.parse(b)
    xa = {n: (h, v) for h, n, v in x}
    ya = {n: (h, v) for h, n, v in y}
    return sorted(n for n in set(xa) | set(ya) if xa.get(n) != ya.get(n))


if __name__ == "__main__":
    client = anthropic.Anthropic()
    out = HERE / "writing"
    out.mkdir(exist_ok=True)
    rows = ["score\tvariant\ttrial\texact\tbars_wrong\tuses_feature\tin\tout"]
    for s in SCORES:
        ref = excerpt((HERE / "n1" / f"{s}.n1.txt").read_text())
        for v, trial in [(v, t) for v in VARIANTS for t in TRIALS]:
            f = out / f"{s}.{v}{trial}.json"
            if f.exists():
                d = json.loads(f.read_text())
            else:
                resp = None
                for attempt in range(3):
                    try:
                        resp = client.messages.create(model=MODEL, max_tokens=16000, output_config={"effort": EFFORT},
                                                      messages=[{"role": "user", "content": PROMPT.format(legend=legends.legend(v), feature=FEATURE[v], score=ref)}])
                        break
                    except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError):
                        continue
                text = "".join(b.text for b in resp.content if b.type == "text")
                m = re.search(r"```[^\n]*\n(.*?)```", text, re.S)
                body = (m.group(1) if m else text).strip() + "\n"
                try:
                    decoded = c.decode(body, v)
                    wrong = diff_bars(decoded, ref)
                    error = None
                except Exception as e:  # any malformed text the model wrote counts as a failure, recorded
                    decoded, wrong, error = None, None, repr(e)
                st = c.stats(body)
                d = {"score": s, "variant": v, "model": resp.model, "written": body, "decoded": decoded, "exact": decoded == ref,
                     "bars_wrong": wrong, "error": error, "stats": st, "expected_stats": c.stats(c.encode(ref, v)),
                     "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}}
                f.write_text(json.dumps(d, indent=1))
            uses = {k: f"{d['stats'][k]}/{d['expected_stats'][k]}" for k in d["stats"] if d["expected_stats"][k]}
            rows.append(f"{s}\t{v}\t{trial or '#1'}\t{d['exact']}\t{d['bars_wrong'] if d['error'] is None else d['error']}\t{uses}\t{d['usage']['in']}\t{d['usage']['out']}")
            print(rows[-1], flush=True)
    (HERE / "writing.tsv").write_text("\n".join(rows) + "\n")
