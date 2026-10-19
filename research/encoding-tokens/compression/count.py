"""Claude token counts (count_tokens API, claude-opus-5-5) for N1, every variant and every legend.

Usage: uv run --with anthropic python count.py   (ANTHROPIC_API_KEY in the environment; writes counts.tsv, legend_counts.tsv)
"""
import time
from pathlib import Path

import anthropic

import legends

MODEL = "claude-opus-5-5"
HERE = Path(__file__).resolve().parent
VARIANTS = ["R", "P", "O", "Oc", "RP", "RO", "PO", "RPO", "RT", "V1", "V2"]
client = anthropic.Anthropic()


def count(text: str) -> int:
    for attempt in range(3):
        try:
            return client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text}]).input_tokens
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError):
            time.sleep(2 + 4 * attempt)
    raise RuntimeError("count_tokens failed three times")


if __name__ == "__main__":
    baseline = count("x")  # fixed per-request overhead, subtracted as count_tokens.py does
    rows = [f"# model={MODEL} baseline={baseline}", "score\tvariant\ttokens\tchars"]
    for path in sorted((HERE / "n1").glob("*.n1.txt")):
        score = path.name.removesuffix(".n1.txt")
        for v in ["N1"] + VARIANTS:
            f = path if v == "N1" else HERE / "variants" / f"{score}.{v}.txt"
            text = f.read_text()
            rows.append(f"{score}\t{v}\t{count(text) - baseline + 1}\t{len(text)}")
            print(rows[-1], flush=True)
    (HERE / "counts.tsv").write_text("\n".join(rows) + "\n")
    leg = ["variant\ttokens\tchars"]
    for v in ["N1"] + VARIANTS:
        text = legends.legend(v)
        leg.append(f"{v}\t{count(text) - baseline + 1}\t{len(text)}")
    (HERE / "legend_counts.tsv").write_text("\n".join(leg) + "\n")
    print("\n".join(leg))
