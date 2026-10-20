import base64, os, re, sys
from importlib.resources import files
from pathlib import Path
import anthropic, verovio
try:
    import tiktoken
except ImportError:
    tiktoken = None
sys.path.insert(0, "/home/user/sheet-music-analysis")
from engine import notes
from engine.score import ScoreIndex

client = anthropic.Anthropic(api_key=os.environ["Anth_Key"])
try:
    enc = tiktoken.get_encoding("o200k_base") if tiktoken else None
except Exception:
    enc = None
def claude(text): return client.messages.count_tokens(model="claude-fable-5-1", messages=[{"role": "user", "content": text}]).input_tokens - 8
def gpt(text): return len(enc.encode(text)) if enc else "n/a"

PITCH = re.compile(r"\b([A-G])(b{1,2}|#{1,2})?(\d)(?=[~+\s]|$)")
FLATS, SHARPS = "BEADGCF", "FCGDAEB"
def body(text, f):
    return "\n".join(PITCH.sub(f, l) if re.match(r"\d+\.\d+:", l) else l for l in text.splitlines())
def dash(m): return m.group(1) + (m.group(2) or "").replace("b", "-") + m.group(3)
def key_relative(ks):
    n, kind = (int(ks[:-1]), ks[-1]) if ks and ks != "0" else (0, "")
    letters = FLATS[:n] if kind == "f" else SHARPS[:n] if kind == "s" else ""
    sign = "b" if kind == "f" else "#"
    def f(m):
        letter, acc, octave = m.group(1), m.group(2) or "", m.group(3)
        if letter in letters:
            acc = "" if acc == sign else "n" if acc == "" else acc
        return letter + acc + octave
    return f

data = Path("/home/user/sheet-music-analysis/tests/data")
out = Path(sys.argv[1]); out.mkdir(exist_ok=True)
print("score\tbars\tnotes\tks\tchars\tclaude N1\tclaude -flat\tclaude key-rel\tgpt N1\tgpt -flat\tgpt key-rel")
for path in sorted(data.glob("*.m*xml*")) + sorted(data.glob("*.mxl")):
    raw = path.read_bytes()
    tk = verovio.toolkit(False); tk.setResourcePath(str(files("verovio") / "data")); tk.setOptions({"xmlIdChecksum": True})
    ok = tk.loadZipDataBase64(base64.b64encode(raw).decode()) if raw[:2] == b"PK" else tk.loadData(raw.decode("utf-8-sig"))
    if not ok: print(path.name, "unreadable"); continue
    index = ScoreIndex(tk.getMEI())
    n1 = notes.encode(index)
    (out / (path.stem + ".n1.txt")).write_text(n1 + "\n")
    variants = [n1, body(n1, dash), body(n1, key_relative(index.key_signature))]
    count = sum(1 for m in index.measures for e in m.events if e.pitch)
    print("\t".join(map(str, [path.name, len(index.measures), count, index.key_signature or "0", len(n1)] + [claude(v) for v in variants] + [gpt(v) for v in variants])))
