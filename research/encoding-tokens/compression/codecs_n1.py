"""Compressions of N1 note text and their exact inverses. Standard library plus engine.score.transpose.

Every encoder takes N1 text and returns compressed text with the same header; every decoder returns the N1 text.
Order when combined: encode octaves (O), then patterns (P), then back-references (R);
decode back-references, then patterns, then octaves, then re-render durations canonically.

R  bar refs `m9 = m1` (same len, no ts= change, every voice line identical) and voice refs `2.1 = m1`
   (that voice line identical to the same staff.voice line of bar 1). The target is always the first bar
   where that content appears, which is always written out in full.
T  (with R) voice refs with a transposition: `2.1 = m1 +M2` means voice 2.1 of bar 1 moved up a major second,
   spelled by interval (letter steps and semitones), as engine.score.transpose does.
P  repeats inside one voice line: `(X)*n` is X written n times in a row; a single token may be `X*n`.
O  relative octaves: in each voice line the first pitch has its octave; a later pitch may drop its octave digit,
   and then it is the octave that puts it within three letter steps (a fourth) of the reference, accidentals ignored.
   The reference for a chord's first note (or a single note, grace notes included) is the first note of the
   previous token in the line; the reference for a later note in a chord is the chord's first note
   (variant "chain": the previous note in the chord, as LilyPond does). Every voice line starts afresh.
"""
from __future__ import annotations

import re

from engine.score import transpose

LETTERS = "CDEFGAB"
NATURAL = [0, 2, 4, 5, 7, 9, 11]
PITCH = re.compile(r"^([A-G])([#b]*)(\d*)(~?)$")
BAR_REF = re.compile(r"^m(\d+) = m(\d+)$")
VOICE_REF = re.compile(r"^(\d+\.\d+) = m(\d+)(?: ([+-])([PMmAd]+)(\d+))?$")


# ---------- the N1 text as bars ----------

def parse(text: str):
    """[(header, number, [(label, body)])], header line first."""
    lines = text.rstrip("\n").split("\n")
    bars = []
    for line in lines[1:]:
        if line.startswith("m"):
            bars.append([line, int(line.split()[0][1:]), []])
        else:
            label, _, body = line.partition(": ")
            if body == "" and " = " in line:
                label, body = line, None
            bars[-1][2].append((label, body))
    return lines[0], bars


def unparse(head: str, bars) -> str:
    out = [head]
    for header, _, voices in bars:
        out.append(header)
        out += [label if body is None else f"{label}: {body}" for label, body in voices]
    return "\n".join(out) + "\n"


# ---------- durations: a voice body as items, and its canonical N1 rendering ----------

def items(body: str):
    """(duration, token) per note/chord/rest; ('g', token) per grace token."""
    out, cur = [], None
    for tok in body.split():
        if tok.isdigit():
            cur = int(tok)
        elif tok.startswith("g"):
            out.append(("g", tok))
        else:
            out.append((cur, tok))
    return out


def render(seq, cur=None):
    """Canonical N1: a duration only when it changes, except that a rest always has its duration before it."""
    toks = []
    for dur, tok in seq:
        if dur == "g":
            toks.append(tok)
            continue
        if tok == "r" or dur != cur:
            toks.append(str(dur))
            cur = dur
        toks.append(tok)
    return toks, cur


def normalise(body: str) -> str:
    return " ".join(render(items(body))[0])


# ---------- O: relative octaves ----------

def _split(tok):
    grace = tok.startswith("g")
    return ("g" if grace else ""), (tok[1:] if grace else tok).split("+")


def _nearest(ref, letter):
    ref_d = ref[1] * 7 + LETTERS.index(ref[0])
    for octave in (ref[1] - 1, ref[1], ref[1] + 1):
        if abs(octave * 7 + LETTERS.index(letter) - ref_d) <= 3:
            return octave
    raise AssertionError


def _walk(body, chain, encode):
    out, prev_first = [], None
    for tok in body.split():
        if tok.isdigit() or tok == "r":
            out.append(tok)
            continue
        prefix, names = _split(tok)
        new, first, last = [], None, None
        for j, name in enumerate(names):
            letter, acc, octave, tie = PITCH.match(name).groups()
            ref = prev_first if j == 0 else (last if chain else first)
            if encode:
                octave = int(octave)
                written = "" if ref is not None and _nearest(ref, letter) == octave else str(octave)
            else:
                octave = int(octave) if octave else _nearest(ref, letter)
                written = str(octave)
            new.append(letter + acc + written + tie)
            last = (letter, octave)
            if j == 0:
                first = last
        prev_first = first
        out.append(prefix + "+".join(new))
    return " ".join(out)


def octaves_encode(body, chain=False):
    return _walk(body, chain, True)


def octaves_decode(body, chain=False):
    return _walk(body, chain, False)


# ---------- P: repeats inside a voice line ----------

def patterns_encode(body: str) -> str:
    seq = items(body)
    segments, i = [], 0
    while i < len(seq):
        best = None
        for length in range(1, (len(seq) - i) // 2 + 1):
            n = 1
            while seq[i + n * length : i + (n + 1) * length] == seq[i : i + length]:
                n += 1
            if n >= 2 and (best is None or length * n > best[0] * best[1]):
                best = (length, n)
        if best:
            segments.append((seq[i : i + best[0]], best[1]))
            i += best[0] * best[1]
        else:
            segments.append(([seq[i]], 1))
            i += 1
    toks, cur = [], None
    for part, n in segments:
        if n == 1:
            t, cur = render(part, cur)
            toks += t
            continue
        plain, _ = render(part * n, cur)
        durs = [d for d, _ in part if d != "g"]
        last = durs[-1] if durs else cur
        pre = []
        first = next(((d, t) for d, t in part if d != "g"), None)
        if first and first[1] != "r" and first[0] == last and cur != last:
            pre, cur = [str(last)], last
        inner, _ = render(part, last if durs else cur)
        group = (inner[0] if len(inner) == 1 else "(" + " ".join(inner) + ")") + f"*{n}"
        if len(" ".join(pre + [group])) < len(" ".join(plain)):
            toks += pre + [group]
            cur = last
        else:
            toks += plain
            cur = render(part * n, cur)[1]
    return " ".join(toks)


def patterns_decode(body: str) -> str:
    body = re.sub(r"\(([^)]*)\)\*(\d+)", lambda m: " ".join([m.group(1)] * int(m.group(2))), body)
    return " ".join(" ".join([m.group(1)] * int(m.group(2))) if (m := re.fullmatch(r"(\S+)\*(\d+)", t)) else t for t in body.split())


# ---------- intervals for T ----------

def interval_name(d: int, s: int) -> str | None:
    sign = "-" if d < 0 or (d == 0 and s < 0) else "+"
    if sign == "-":
        d, s = -d, -s
    base = NATURAL[d % 7] + 12 * (d // 7)
    diff = s - base
    perfect = d % 7 in (0, 3, 4)
    names = {0: "P", 1: "A", -1: "d", 2: "AA", -2: "dd"} if perfect else {0: "M", -1: "m", 1: "A", -2: "d", 2: "AA", -3: "dd"}
    if diff not in names:
        return None
    return f"{sign}{names[diff]}{d + 1}"


def interval_parse(sign, quality, number):
    d = int(number) - 1
    perfect = d % 7 in (0, 3, 4)
    diff = ({"P": 0, "A": 1, "d": -1, "AA": 2, "dd": -2} if perfect else {"M": 0, "m": -1, "A": 1, "d": -2, "AA": 2, "dd": -3})[quality]
    s = NATURAL[d % 7] + 12 * (d // 7) + diff
    return (-d, -s) if sign == "-" else (d, s)


def _pitches(body):
    return [name for tok in body.split() if not tok.isdigit() and tok != "r" for name in _split(tok)[1]]


def _midi(name):
    letter, acc, octave, _ = PITCH.match(name).groups()
    return NATURAL[LETTERS.index(letter)] + acc.count("#") - acc.count("b") + 12 * int(octave)


def transpose_body(body, d, s):
    out = []
    for tok in body.split():
        if tok.isdigit() or tok == "r":
            out.append(tok)
            continue
        prefix, names = _split(tok)
        out.append(prefix + "+".join(transpose(n.rstrip("~"), d, s) + ("~" if n.endswith("~") else "") for n in names))
    return " ".join(out)


def _transposition(src, dst):
    """(d, s) such that src transposed is dst, or None."""
    if re.sub(r"[A-G][#b]*\d", "P", src) != re.sub(r"[A-G][#b]*\d", "P", dst):
        return None
    a, b = _pitches(src), _pitches(dst)
    if not a:
        return None
    pa, pb = PITCH.match(a[0]).groups(), PITCH.match(b[0]).groups()
    d = (int(pb[2]) * 7 + LETTERS.index(pb[0])) - (int(pa[2]) * 7 + LETTERS.index(pa[0]))
    s = _midi(b[0]) - _midi(a[0])
    if (d, s) == (0, 0):
        return None
    try:
        return (d, s) if transpose_body(src, d, s) == dst else None
    except (ValueError, IndexError):
        return None


# ---------- R: back-references ----------

def refs_encode(text: str, transposed=False) -> str:
    head, bars = parse(text)
    first_bar: dict = {}
    first_voice: dict = {}
    earlier: dict = {}  # label -> [(bar number, body)] written out in full
    out = []
    for header, number, voices in bars:
        length = header.split()[1]
        key = (length, tuple(voices))
        if "ts=" not in header and key in first_bar:
            out.append((f"m{number} = m{first_bar[key]}", number, []))
            continue
        first_bar.setdefault(key, number)
        new = []
        for label, body in voices:
            ref = first_voice.get((label, body))
            if ref is not None and len(f"{label} = m{ref}") < len(f"{label}: {body}"):
                new.append((f"{label} = m{ref}", None))
                continue
            if ref is None and transposed:
                line = None
                for src_number, src in earlier.get(label, []):
                    t = _transposition(src, body)
                    if t and (name := interval_name(*t)) and interval_parse(*re.fullmatch(r"([+-])([PMmAd]+)(\d+)", name).groups()) == t:
                        line = f"{label} = m{src_number} {name}"
                        break
                if line and len(line) < len(f"{label}: {body}"):
                    new.append((line, None))
                    continue  # targets of refs are only lines written out in full
            new.append((label, body))
            if ref is None:
                first_voice[(label, body)] = number
                earlier.setdefault(label, []).append((number, body))
        out.append((header, number, new))
    return unparse(head, out)


def refs_decode(text: str) -> str:
    head, bars = parse(text)
    full: dict = {}  # bar number -> (header, voices)
    out = []
    for header, number, voices in bars:
        if m := BAR_REF.match(header):
            src_header, src_voices = full[int(m.group(2))]
            header = f"m{number} {src_header.split()[1]}"
            voices = list(src_voices)
        else:
            resolved = []
            for label, body in voices:
                if body is None:
                    m = VOICE_REF.match(label)
                    label = m.group(1)
                    body = dict(full[int(m.group(2))][1])[label]
                    if m.group(3):
                        body = transpose_body(body, *interval_parse(m.group(3), m.group(4), m.group(5)))
                resolved.append((label, body))
            voices = resolved
        full[number] = (header, voices)
        out.append((header, number, voices))
    return unparse(head, out)


# ---------- the variants ----------

def _map_bodies(text, f):
    head, bars = parse(text)
    return unparse(head, [(h, n, [(l, f(b) if b is not None else b) for l, b in v]) for h, n, v in bars])


def encode(text: str, variant: str) -> str:
    """variant: any combination of the letters R, P, O (and T with R), or 'Oc' for chained chord octaves."""
    chain = "c" in variant
    if "O" in variant:
        text = _map_bodies(text, lambda b: octaves_encode(b, chain))
    if "P" in variant:
        text = _map_bodies(text, patterns_encode)
    if "R" in variant:
        text = refs_encode(text, transposed="T" in variant)
    return text


def decode(text: str, variant: str) -> str:
    chain = "c" in variant
    if "R" in variant:
        text = refs_decode(text)
    if "P" in variant:
        text = _map_bodies(text, patterns_decode)
    if "O" in variant:
        text = _map_bodies(text, lambda b: octaves_decode(b, chain))
    return _map_bodies(text, normalise)


def stats(text: str) -> dict:
    """What a compressed text uses, so a small saving is visibly not a no-op encoder."""
    return {
        "bar_refs": len(re.findall(r"^m\d+ = m\d+$", text, re.M)),
        "voice_refs": len(re.findall(r"^\d+\.\d+ = m\d+$", text, re.M)),
        "transposed_refs": len(re.findall(r"^\d+\.\d+ = m\d+ [+-]", text, re.M)),
        "groups": len(re.findall(r"\*\d+", text)),
        "octaveless": len(re.findall(r"(?<![A-Za-fh-z])[A-G][#b]*(?=[~+\s]|$)", "\n".join(l.partition(": ")[2] for l in text.splitlines()))),
    }
