"""Does claude-sonnet-5-5 still read the score under each compression? Eight questions per score, answers computed
from the N1 text (own parser, cross-checked against the engine index), asked once per score and variant.

Usage: uv run --with anthropic --with verovio python reading.py dry|pilot|run [effort]
  dry    print questions and answers, estimate cost from token counts, no API calls
  pilot  one call (nocturne, N1) to measure output tokens
  run    every score x variant; writes reading/<score>.<variant>.json (reading-high/ at effort high)
"""
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

import anthropic

import codecs_n1 as c
import legends
from build import DATA, SCORES, load
from engine.reduce import midi

HERE = Path(__file__).resolve().parent
MODEL = "claude-sonnet-5-5"
EFFORT = sys.argv[2] if len(sys.argv) > 2 else "medium"  # the second pass used "high"
READ_SET = ["chopin-nocturne", "mozart-k545-1", "bach-bwv64-4", "chopin-prelude-4", "brahms-fruehlingstrost", "haydn-104"]
VARIANTS = ["N1", "N1#2", "R", "P", "O", "RP", "RO", "PO", "RPO", "RT", "V1", "V2"]


def events(n1):
    """{bar: [(label, staff, onset, dur, pitch, grace, chord_index_in_line, tied_from_previous)]} from N1 text.
    A note tied from the previous note of its voice (across bar lines too) sounds but is not attacked."""
    _, bars = c.parse(n1)
    out, pending = {}, {}
    for _, number, voices in bars:
        evs = []
        for label, body in voices:
            onset = 0
            for k, (d, tok) in enumerate(c.items(body)):
                if tok == "r":
                    onset += d
                    pending[label] = set()
                    continue
                grace = d == "g"
                names = (tok[1:] if grace else tok).split("+")
                for name in names:
                    evs.append((label, int(label.split(".")[0]), onset, 0 if grace else d, name.rstrip("~"), grace, k, not grace and name.rstrip("~") in pending.get(label, set())))
                if not grace:
                    onset += d
                    pending[label] = {n.rstrip("~") for n in names if n.endswith("~")}
        out[number] = evs
    return out


def low(ps):
    return min(ps, key=midi)


def high(ps):
    return max(ps, key=midi)


def questions(score, n1):
    rng = random.Random(score)
    ev = events(n1)
    _, bars = c.parse(n1)
    lines = {(n, label): body for _, n, voices in bars for label, body in voices}
    r_text, p_text, o_text = c.encode(n1, "R"), c.encode(n1, "P"), c.encode(n1, "O")
    _, rb = c.parse(r_text)
    ref_bars = [n for h, n, v in rb if " = " in h or any(b is None for _, b in v)]
    _, pb = c.parse(p_text)
    group_lines = [(n, l) for _, n, v in pb for l, b in v if b and "*" in b]
    _, ob = c.parse(o_text)
    octaveless = {(n, l) for _, n, v in ob for l, b in v if b and re.search(r"[A-G][#b]*(?=[~+\s]|$)", b)}
    numbers = [n for _, n, _ in bars if n > 0]

    def pick(pool, fallback):
        pool = [x for x in pool if x in fallback] or fallback
        return rng.choice(sorted(pool))

    qs, truth = {}, {}
    # q1 chord in a compressed line, at an offset after the start
    cand = [(n, l) for (n, l) in lines if n > 0 and any(e[0] == l and e[2] > 0 and not e[5] and sum(1 for f in ev[n] if f[0] == l and f[2] == e[2] and not f[5]) > 1 for e in ev[n])]
    if not cand:
        cand = [(n, l) for (n, l) in lines if n > 0 and any(e[0] == l and e[2] > 0 for e in ev[n])]
    n, l = pick(set(group_lines) | {(b, x) for b in ref_bars for x in ["1.1", "2.1", "3.1", "4.1"]} | octaveless, cand)
    offs = sorted({e[2] for e in ev[n] if e[0] == l and e[2] > 0 and not e[5] and sum(1 for f in ev[n] if f[0] == l and f[2] == e[2] and not f[5]) > 1}) or sorted({e[2] for e in ev[n] if e[0] == l and e[2] > 0 and not e[5]})
    o = rng.choice(offs)
    qs["q1"] = f"Which pitches are attacked (grace notes excluded) in voice {l} of bar {n} at offset {o}? A list, low to high."
    truth["q1"] = sorted({e[4] for e in ev[n] if e[0] == l and e[2] == o and not e[5] and not e[7]}, key=midi)
    # q2 bass at the start of a bar
    sounding = [b for b in numbers if any(e[2] == 0 and not e[5] for e in ev[b])]
    n = pick(ref_bars, sounding)
    qs["q2"] = f"What is the lowest pitch sounding at the very start (offset 0) of bar {n}, in any staff (grace notes excluded)?"
    truth["q2"] = low([e[4] for e in ev[n] if e[2] == 0 and not e[5]])
    # q3 highest attacked in a bar
    n = pick(ref_bars + [b for b, _ in group_lines], numbers)
    qs["q3"] = f"What is the highest pitch attacked in bar {n}, across all staves (grace notes excluded)?"
    truth["q3"] = high([e[4] for e in ev[n] if not e[5] and not e[7]])
    # q4 identical bars, or identical voice lines
    key = {nn: (h.split()[1], tuple(v)) for h, nn, v in bars}
    groups = Counter(key.values())
    best, count = groups.most_common(1)[0]
    if count > 1:
        y = min(nn for nn in key if key[nn] == best)
        qs["q4"] = f"List every bar (other than bar {y}) that is identical to bar {y} in every voice: same voices, notes and durations."
        truth["q4"] = sorted(nn for nn in key if key[nn] == best and nn != y)
    else:
        vg = Counter((lab, body) for (nn, lab), body in lines.items())
        (lab, body), _ = vg.most_common(1)[0]
        y = min(nn for (nn, lb), bd in lines.items() if (lb, bd) == (lab, body))
        qs["q4"] = f"List every bar (other than bar {y}) in which voice {lab} is identical (same notes and durations) to voice {lab} of bar {y}."
        truth["q4"] = sorted(nn for (nn, lb), bd in lines.items() if (lb, bd) == (lab, body) and nn != y)
    # q5 attacks in one staff of a bar
    n, l = pick(group_lines, [(b, x) for (b, x) in lines if b > 0])
    s = int(l.split(".")[0])
    qs["q5"] = f"How many notes are attacked in staff {s} of bar {n}, all voices of that staff? Count each note of a chord separately; exclude grace notes."
    truth["q5"] = sum(1 for e in ev[n] if e[1] == s and not e[5] and not e[7])
    # q6 range of an inner or lower voice over four bars
    labels = Counter(lab for (_, lab) in lines)
    lab = rng.choice(sorted([x for x in labels if x != "1.1"] or ["1.1"]))
    starts = [b for b in numbers if all(b + k in ev for k in range(4))]
    x = pick([b for (b, lb) in octaveless if lb == lab], starts)
    ps = [e[4] for k in range(4) for e in ev[x + k] if e[0] == lab and not e[5]]
    while not ps:
        x = rng.choice(starts)
        ps = [e[4] for k in range(4) for e in ev[x + k] if e[0] == lab and not e[5]]
    qs["q6"] = f"In voice {lab}, across bars {x} to {x + 3}, what are the lowest and the highest pitch (grace notes excluded)? As {{\"low\": …, \"high\": …}}."
    truth["q6"] = {"low": low(ps), "high": high(ps)}
    # q7 how often one pitch is attacked in a voice over two bars
    pairs = [(b, lb) for (b, lb) in lines if b > 0 and b + 1 in ev]
    b, lb = pick(group_lines, pairs)
    cnt = Counter(e[4] for k in range(2) for e in ev[b + k] if e[0] == lb and not e[5])
    p = sorted(cnt, key=lambda q: (-cnt[q], midi(q)))[0]
    qs["q7"] = f"How many times is the pitch {p} attacked in voice {lb} in bars {b} and {b + 1} together (grace notes excluded)?"
    truth["q7"] = sum(1 for k in range(2) for e in ev[b + k] if e[0] == lb and not e[5] and not e[7] and e[4] == p)
    # q8 the top voice of one bar in order
    with_top = [b for b in numbers if (b, "1.1") in lines]
    n = pick(ref_bars, with_top)
    seq = []
    for k in sorted({e[6] for e in ev[n] if e[0] == "1.1" and not e[5] and not e[7]}):
        seq.append("+".join(sorted((e[4] for e in ev[n] if e[0] == "1.1" and e[6] == k and not e[7]), key=midi)))
    qs["q8"] = f"List the attacks of voice 1.1 in bar {n} in order (grace notes excluded); write a chord as its pitches joined by + low to high, e.g. \"C4+E4\"."
    truth["q8"] = seq
    return qs, truth


def norm(q, v):
    if v is None:
        return None
    if q in ("q4",):
        return sorted(int(str(x).lstrip("m")) for x in v)  # "m7" is a bar number written the way the text writes it
    if q in ("q5", "q7"):
        return int(v)
    if q in ("q2", "q3") and isinstance(v, list) and len(v) == 1:
        v = v[0]  # a one-pitch list for a one-pitch question is a format slip, not a misreading
    if q == "q1":
        return sorted(map(str, v))
    if q == "q6":
        return {"low": str(v.get("low")), "high": str(v.get("high"))}
    if q == "q8":
        return ["+".join(sorted(str(x).split("+"))) for x in v]
    return str(v)


def grade(q, answer, truth):
    try:
        a = norm(q, answer)
    except (TypeError, ValueError, AttributeError):
        return "wrong"
    if a is None:
        return "null"
    t = norm(q, truth)
    return "correct" if a == t else "wrong"


PROMPT = """The text below encodes a score. {legend}
Offsets are in div units from the start of the bar.

Answer from the text only, as JSON with keys q1..q8 and no other text. Write every pitch with letter, accidental (b or #) and absolute octave, e.g. Bb4, C#5, G5. If the text does not contain enough information to answer a question, answer null for it.
{questions}

{score}"""


def text_of(score, v):
    if v.startswith("N1"):
        return (HERE / "n1" / f"{score}.n1.txt").read_text()
    return (HERE / "variants" / f"{score}.{v}.txt").read_text()


def ask(client, prompt):
    """Returns (answers, last response, retries, error, tokens summed over every attempt, for the cost)."""
    last, spent = None, {"in": 0, "out": 0}
    for attempt in range(3):
        try:
            resp = client.messages.create(model=MODEL, max_tokens=16000, output_config={"effort": EFFORT}, messages=[{"role": "user", "content": prompt}])
        except (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError) as e:
            last = repr(e)
            time.sleep(5 + 10 * attempt)
            continue
        spent["in"] += resp.usage.input_tokens
        spent["out"] += resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:  # the first JSON object; the model sometimes adds notes after it
            parsed, _ = json.JSONDecoder().raw_decode(text[text.index("{"):])
        except (ValueError, json.JSONDecodeError):
            last = f"unparsed, stop={resp.stop_reason}: {text[:200]!r}"
            continue
        return parsed, resp, attempt, None, spent
    return {}, None, 3, last, spent


def check_against_index(score, n1):
    """The parser's non-grace note count per bar must match the engine index."""
    index = load(DATA / SCORES[score])
    ev = events(n1)
    for m in index.measures:
        assert sum(1 for e in m.events if e.pitch and not e.grace) == sum(1 for e in ev[m.number] if not e[5]), (score, m.number)


if __name__ == "__main__":
    mode = sys.argv[1]
    sets = {s: questions(s, text_of(s, "N1")) for s in READ_SET}
    if mode == "dry":
        counts = {}
        for line in (HERE / "counts.tsv").read_text().splitlines()[2:]:
            sc, v, t, _ = line.split("\t")
            counts[(sc, v)] = int(t)
        total_in = 0
        for s, (qs, truth) in sets.items():
            check_against_index(s, text_of(s, "N1"))
            print(s)
            for q in qs:
                print(" ", q, qs[q], "->", truth[q])
            total_in += sum(counts[(s, v.split("#")[0])] + 900 for v in VARIANTS)
        print("input tokens", total_in)
        sys.exit()
    client = anthropic.Anthropic()
    out = HERE / ("reading" if EFFORT == "medium" else f"reading-{EFFORT}")
    out.mkdir(exist_ok=True)
    jobs = [("chopin-nocturne", "N1")] if mode == "pilot" else [(s, v) for s in READ_SET for v in VARIANTS]
    for s, v in jobs:
        f = out / f"{s}.{v}.json"
        if f.exists() and mode == "run":
            continue
        qs, truth = sets[s]
        prompt = PROMPT.format(legend=legends.legend(v.split("#")[0]), questions="\n".join(f"{q}: {t}" for q, t in qs.items()), score=text_of(s, v))
        parsed, resp, retries, error, spent = ask(client, prompt)
        grades = {q: grade(q, parsed.get(q), truth[q]) for q in qs}
        record = {"score": s, "variant": v, "model": resp.model if resp else None, "effort": EFFORT, "questions": qs, "truth": truth,
                  "answers": parsed, "grades": grades, "retries": retries, "error": error,
                  "usage": spent,
                  "stop": resp.stop_reason if resp else None}
        f.write_text(json.dumps(record, indent=1))
        print(s, v, Counter(grades.values()), record["usage"], record["stop"], error or "", flush=True)
