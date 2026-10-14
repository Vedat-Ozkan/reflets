"""Count Claude tokens for each encoding file with the Anthropic count_tokens API.

Usage: python count_tokens.py FILE [FILE ...]   (needs ANTHROPIC_API_KEY)
Prints one line per file: tokens, characters, chars per token.
"""
import sys
from pathlib import Path
import anthropic

MODEL = "claude-fable-5-1"
client = anthropic.Anthropic()


def count(text: str) -> int:
    return client.messages.count_tokens(model=MODEL, messages=[{"role": "user", "content": text}]).input_tokens


if __name__ == "__main__":
    baseline = count("x")  # the fixed per-request overhead, subtracted from every file
    print(f"model={MODEL} baseline={baseline}")
    print("file\ttokens\tchars\tchars/token")
    for path in sys.argv[1:]:
        text = Path(path).read_text()
        tokens = count(text) - baseline + 1
        print(f"{Path(path).name}\t{tokens}\t{len(text)}\t{len(text) / tokens:.2f}")
