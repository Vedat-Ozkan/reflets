"""Reading accuracy at low and medium effort (docs/spec-core.md section 11, decision 22).

Sonnet 5.5 gets the server instructions and a read_score tool that serves the live read_score text captured from
MuseScore by tests/reading_capture.py (tests/data/reading/*.json), one question per conversation. Each question asks
which notes start or sound at a beat of one voice, or the lowest or highest note of a voice in a bar; the answer is
computed from the score's index. Medium effort passes at 95%; low effort is reported.

    Anth_Key=... uv run --with anthropic python tests/reading_accuracy.py questions
    Anth_Key=... uv run --with anthropic python tests/reading_accuracy.py run research/reading-accuracy-<date>.json
"""

import asyncio
import json
import os
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
from pathlib import Path

from reflets import server
from reflets.score import build_index, parse_info

SCORES = ["chorale", "nocturne", "groups", "lyrics"]
PER_SCORE = 10
KINDS = ["start"] * 4 + ["sound"] * 4 + ["lowest", "highest"]
EFFORTS = ["low", "medium"]
MODEL = "claude-sonnet-5-5"
GATE = 0.95
UNITS = {Fraction(1): "a quarter note", Fraction(3, 2): "a dotted quarter note", Fraction(2): "a half note", Fraction(1, 2): "an eighth note"}
ANSWER = 'End your reply with one line of JSON, {"answer": [...]}, listing the pitches as sounding pitches spelled as in read_score (Bb4, F#3).'


def beat_text(offset: Fraction, beat: Fraction) -> str:
    value = 1 + offset / beat
    return str(int(value)) if value.denominator == 1 else f"{float(value):g}"


def questions() -> list[dict]:
    rng = random.Random(22)
    asked = []
    for name in SCORES:
        saved = json.loads(Path(f"tests/data/reading/{name}.json").read_text())
        info = parse_info(saved["info"])
        index = build_index(info, saved["read"], saved["division"])
        notes = [e for m in index.measures if m.number > 0 for e in m.events if e.pitch and not e.grace]
        for kind in rng.sample(KINDS, len(KINDS)) * 3:
            if sum(q["score"] == name for q in asked) == PER_SCORE:
                break
            while True:
                pick = rng.choice(notes)
                measure = next(m for m in index.measures if m.number == pick.measure)
                voice = [e for e in measure.events if e.pitch and not e.grace and (e.staff, e.layer) == (pick.staff, pick.layer)]
                where = f"bar {measure.number}, voice {pick.staff}.{pick.layer} (staff {pick.staff}, voice {pick.layer})"
                if kind in ("lowest", "highest"):
                    ordered = sorted({e.pitch for e in voice}, key=lambda p: notes_key(p))
                    truth = [ordered[0] if kind == "lowest" else ordered[-1]]
                    text = f"In {where}, which is the {kind} note? Do not count grace notes."
                    break
                step = measure.beat_length / 2
                if kind == "start":
                    offset = pick.onset
                    if offset % step:
                        continue
                    truth = sorted({e.pitch for e in voice if e.onset == offset})
                    verb = "start exactly at"
                else:
                    held = [o for o in range(int(measure.length / step)) if pick.onset < o * step < pick.onset + pick.duration]
                    if not held:
                        continue
                    offset = rng.choice(held) * step
                    truth = sorted({e.pitch for e in voice if e.onset <= offset < e.onset + e.duration})
                    verb = "are sounding (started earlier and still held, or starting) at"
                text = (f"In {where}, which notes {verb} beat {beat_text(offset, measure.beat_length)}? Beats count from 1 "
                        f"at the start of the bar, a beat here is {UNITS[measure.beat_length]}, and beat 2.5 is halfway "
                        "through beat 2. Do not count grace notes.")
                break
            if any(q["question"].startswith(text) for q in asked):
                continue
            asked.append({"id": f"{name}-{sum(q['score'] == name for q in asked) + 1}", "score": name, "kind": kind, "question": f"{text} {ANSWER}", "truth": truth})
    return asked


def notes_key(pitch: str) -> int:
    letter, accidentals, octave = pitch[0], pitch[1:-1], int(pitch[-1])
    return octave * 12 + "C D EF G A B".index(letter) + accidentals.count("#") - accidentals.count("b")


def read_score(name: str, bars: str) -> str:
    windows = json.loads(Path(f"tests/data/reading/{name}.json").read_text())["windows"]
    key = "all" if bars.strip().lower() == "all" else bars.strip()
    key = key if "-" in key or key == "all" else f"{key}-{key}"
    return windows.get(key, f'Error: bars must be "all" or a range like "5-12" of bars the score has, not {bars!r}')


def ask(client, question: dict, effort: str, system: str, tool: dict) -> dict:
    messages = [{"role": "user", "content": question["question"]}]
    thought, calls, output = False, [], 0
    for _ in range(12):
        response = client.messages.create(
            model=MODEL, max_tokens=16000, system=system, tools=[tool], messages=messages,
            thinking={"type": "adaptive", "display": "summarized"}, output_config={"effort": effort},
        )
        output += response.usage.output_tokens
        thought = thought or any(block.type == "thinking" and block.thinking for block in response.content)
        messages.append({"role": "assistant", "content": response.content})
        uses = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not uses:
            break
        calls += [use.input.get("bars", "all") for use in uses]
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": use.id, "content": read_score(question["score"], use.input.get("bars", "all"))}
            for use in uses
        ]})
    reply = "".join(block.text for block in response.content if block.type == "text")
    found = re.findall(r'\{"answer":.*?\}', reply)
    try:
        answer = sorted(json.loads(found[-1])["answer"]) if found else None
    except (json.JSONDecodeError, TypeError):
        answer = None
    return {**question, "effort": effort, "answer": answer, "right": answer == question["truth"], "thought": thought,
            "calls": calls, "output_tokens": output, "stop": response.stop_reason, "reply": reply[-400:]}


def run(path: str) -> None:
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ.get("Anth_Key") or None)
    listed = asyncio.run(server.mcp.list_tools())
    spec = next(tool for tool in listed if tool.name == "read_score")
    tool = {"name": "read_score", "description": spec.description, "input_schema": spec.input_schema}
    asked = questions()
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda job: ask(client, job[0], job[1], server.mcp.instructions, tool),
                                [(q, effort) for effort in EFFORTS for q in asked]))
    Path(path).write_text(json.dumps({"model": MODEL, "results": results}, indent=1))
    for effort in EFFORTS:
        done = [r for r in results if r["effort"] == effort]
        right = sum(r["right"] for r in done)
        thinking = [r for r in done if r["thought"]]
        print(f"{effort}: {right}/{len(done)} right; thought first in {len(thinking)}, of those right {sum(r['right'] for r in thinking)}")
        for r in done:
            if not r["right"]:
                print(f"  WRONG {r['id']} {r['kind']}: truth {r['truth']} answer {r['answer']} thought={r['thought']} calls={r['calls']}")
    medium = [r for r in results if r["effort"] == "medium"]
    passed = sum(r["right"] for r in medium) >= GATE * len(medium)
    print(("PASS" if passed else "FAIL") + f" medium effort at {GATE:.0%}")
    sys.exit(0 if passed else 1)


if sys.argv[1] == "questions":
    for q in questions():
        print(q["id"], q["kind"], q["truth"], "|", q["question"].split(" Beats count")[0].split(" Do not")[0])
else:
    run(sys.argv[2])
