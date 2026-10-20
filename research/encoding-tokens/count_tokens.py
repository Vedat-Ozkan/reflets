import os
import sys
from pathlib import Path
import anthropic

MODEL = "claude-fable-5-1"
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("Anth_Key"))


def count(text: str) -> int:
    return client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text}]).input_tokens


if __name__ == "__main__":
    baseline = count("x")
    print(f"model={MODEL} baseline={baseline}")
    print("file\ttokens\tchars\tchars/token")
    for path in sys.argv[1:]:
        text = Path(path).read_text()
        tokens = count(text) - baseline + 1
        print(f"{Path(path).name}\t{tokens}\t{len(text)}\t{len(text) / tokens:.2f}")
