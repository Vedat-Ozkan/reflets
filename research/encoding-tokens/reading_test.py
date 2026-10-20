import base64, json, os, re, sys
from fractions import Fraction
from importlib.resources import files
from pathlib import Path
import anthropic, verovio
sys.path.insert(0, "/home/user/sheet-music-analysis")
from engine import notes
from engine.score import ScoreIndex

MXL = Path("/home/user/sheet-music-analysis/tests/data/chopin_nocturne_op9_no2.mxl")
tk = verovio.toolkit(False); tk.setResourcePath(str(files("verovio") / "data")); tk.setOptions({"xmlIdChecksum": True})
tk.loadZipDataBase64(base64.b64encode(MXL.read_bytes()).decode())
index = ScoreIndex(tk.getMEI())
n1 = notes.encode(index)

PITCH = re.compile(r"\b([A-G])(b{1,2}|#{1,2})?(\d)(?=[~+\s]|$)")
def body(text, f): return "\n".join(PITCH.sub(f, l) if re.match(r"\d+\.\d+:", l) else l for l in text.splitlines())
def dash(m): return m.group(1) + (m.group(2) or "").replace("b", "-") + m.group(3)
def key_rel(m):
    letter, acc, octave = m.group(1), m.group(2) or "", m.group(3)
    if letter in "BEA": acc = "" if acc == "b" else "n" if acc == "" else acc
    return letter + acc + octave

LEGEND = {
 "N1": "Pitches are spelled with b for flat and # for sharp (Bb4, C#5).",
 "dash": "Pitches are spelled with - for flat and # for sharp (B-4, C#5).",
 "key-relative": "Pitches are spelled relative to the key signature ks=3f (B flat, E flat, A flat): B4 means B flat 4, E5 means E flat 5, A3 means A flat 3; a natural on those letters is written with n (Bn4). Other letters are as written; # is sharp and b is flat on them.",
}
VARIANTS = {"N1": n1, "dash": body(n1, dash), "key-relative": body(n1, key_rel)}

def at(bar, beat, staff):
    m = index.measure(bar); off = m.offset_of(beat)
    return sorted({e.pitch for e in m.events if e.pitch and not e.grace and e.staff == staff and e.onset == off})
def sounding(bar, beat, staff):
    m = index.measure(bar); off = m.offset_of(beat)
    return sorted({e.pitch for e in m.events if e.pitch and not e.grace and e.staff == staff and e.onset <= off < e.onset + e.duration})
truth = {
 "q1": at(7, 1, 2), "q2": sorted({m.number for m in index.measures for e in m.events if e.tied and e.staff == 1}), "q3": min((e for e in index.measure(12).events if e.pitch and e.staff == 2), key=lambda e: (int(e.pitch[-1]), "CDEFGAB".index(e.pitch[0]))).pitch, "q4": sum(1 for e in index.measure(7).events if e.grace), "q5": sorted({e.pitch for e in index.measure(4).events if e.pitch and e.staff == 1 and e.onset == index.measure(4).length - Fraction(1, 2)}), "q6": sounding(16, 2, 2),}
QUESTIONS = """The text below is a compact encoding of a piano score. Header: div = units per quarter note, ts = time signature, ks = key signature (3f = three flats). Each `mN len=…` starts bar N (m0 is the pickup). Each `staff.voice:` line is one voice; staff 1 is the right hand, staff 2 the left hand. A bare number sets the duration in div units for the notes after it; `+` joins the notes of a chord; `r` is a rest; a leading `g` marks a grace note; a trailing `~` ties the note to the next. {legend} Beats are dotted-quarter beats of the 12/8 bar: beat 1 starts at 0, beat 2 at 72, beat 3 at 144, beat 4 at 216 div units.

Answer these questions from the text only, as JSON with keys q1..q6 and no other text. Spell every pitch in the answer as letter, b/# accidental, octave, e.g. Bb4, C#5, G5 (sounding pitch, resolved against the key signature where the text is key-relative).
q1: the left-hand (staff 2) notes attacked exactly at bar 7 beat 1, as a sorted list.
q2: the bar numbers in which the right hand (staff 1) has a tie (~), as a sorted list.
q3: the lowest left-hand note in bar 12.
q4: how many grace notes bar 7 contains (an integer).
q5: the right-hand notes attacked on the last eighth note (the last 24 units) of bar 4, as a list.
q6: the left-hand notes sounding at bar 16 beat 2 (attacked at or before 72 and not yet over), as a sorted list.

{score}"""

client = anthropic.Anthropic(api_key=os.environ["Anth_Key"])
def norm(v):
    if isinstance(v, list): return sorted(str(x).replace("-", "b") for x in v)
    return str(v).replace("-", "b")
results = {}
for name, text in VARIANTS.items():
    resp = client.messages.create(model="claude-fable-5-1", max_tokens=4000, output_config={"effort": "medium"},
                                  messages=[{"role": "user", "content": QUESTIONS.format(legend=LEGEND[name], score=text)}])
    answer = "".join(b.text for b in resp.content if b.type == "text")
    try:
        parsed = json.loads(re.search(r"\{.*\}", answer, re.S).group(0))
    except Exception:
        parsed = {}
    score = {q: norm(parsed.get(q)) == norm(truth[q]) for q in truth}
    results[name] = {"answers": parsed, "correct": score, "usage": {"in": resp.usage.input_tokens, "out": resp.usage.output_tokens}, "stop": resp.stop_reason}
    print(name, sum(score.values()), "/", len(score), score, resp.usage.input_tokens, "in", resp.usage.output_tokens, "out", resp.stop_reason)
print("truth", {q: norm(v) if isinstance(v, list) else v for q, v in truth.items()})
json.dump({"truth": {q: v for q, v in truth.items()}, "results": results}, open(sys.argv[1], "w"), indent=1, default=str)
