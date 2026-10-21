from __future__ import annotations

import re
from fractions import Fraction

from reflets import n1x

VOICE = re.compile(r"(\d+\.\d+: )(.*)")


def unglissed(match: re.Match) -> str:
    names = [name for name in match[1].split(",") if not name.removeprefix("-").startswith("gliss")]
    return f"[{','.join(names)}]" if names else ""


def body(text: str) -> list[str]:
    return [line for line in n1x.expand(text).splitlines() if re.match(r"m\d+ |\d+\.\d+( L\d+)?:", line)]


def writable(text: str) -> list[str]:
    return [re.sub(r"\[([^\]\"]*)\]", unglissed, line) for line in body(text)]


def closed(lines: list[str]) -> set[tuple[int, int]]:
    stacks: dict[tuple[str, str], list[tuple[int, int]]] = {}
    found = set()
    for row, line in enumerate(lines):
        match = VOICE.fullmatch(line)
        for column, word in enumerate(n1x.TOKEN.findall(match[2]) if match else []):
            token = n1x.LINE_TOKEN.fullmatch(re.sub(r"@\d+$", "", word))
            if not token:
                continue
            stack = stacks.setdefault((match[1], token[1] + token[4]), [])
            if token[3] == "(":
                stack.append((row, column))
            elif stack:
                found |= {stack.pop(), (row, column)}
    return found


def marks(lines: list[str], header: str) -> set[tuple[str, str, Fraction, str]]:
    idea = n1x.decode("\n".join([header, *lines]))
    return {
        (f"m{bar.number}", f"{staff}.{layer}", moment, token)
        for bar in idea.bars
        for (staff, layer), voice in bar.voices.items()
        for moment, token in voice.marks
        if not n1x.is_line(token)
    }


def bare_idea(lines: list[str], header: str, keep: set[tuple[str, str, Fraction, str]] = frozenset()) -> str:
    lines_closed = closed(lines)
    div = int(re.search(r"div=(\d+)", header)[1])
    gone = sorted(marks(lines, header) - keep, key=lambda mark: mark[2])
    result, bar = [header], ""
    for row, line in enumerate(lines):
        match = VOICE.fullmatch(line)
        if re.match(r"m\d+ ", line):
            bar = line.split()[0]
        if not match:
            if " L" in line:
                result.append(line.split(":")[0] + ":")
            else:
                result.append(" ".join(word if re.fullmatch(r"m\d+", word) or word.startswith(("len=", "ts=", "ks=")) else "-" + word for word in line.split()))
            continue
        words = n1x.TOKEN.findall(match[2])
        cell = match[1].split(":")[0]
        result.append(match[1] + " ".join(
            [
                ("-" + word if (row, column) in lines_closed else word) if n1x.is_line(re.sub(r"@\d+$", "", word)) else removed(word)
                for column, word in enumerate(words)
                if n1x.is_line(re.sub(r"@\d+$", "", word)) or not n1x.MARK.fullmatch(re.sub(r"@\d+$", "", word))
            ]
            + [f"-{token}@{n1x.units(moment, div)}" for where, at, moment, token in gone if (where, at) == (bar, cell)]
        ))
    return "\n".join(result)


def removed(word: str) -> str:
    if word.startswith("g") or word.isdigit() or word == "}":
        return word
    word = re.sub(r"(?<=[\[,])(?!-)", "-", word)
    if word.endswith("{"):
        return word
    if re.match(r"[A-G]", word):
        return re.sub(r":(?!-)(?=[A-Za-z])", ":-", word)
    return word if word.startswith(("[", "r", "-")) else "-" + word


def bars(lines: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for line in lines:
        if re.match(r"m\d+ ", line):
            number = line.split()[0]
            result[number] = []
        result[number].append(line)
    return result


def target_idea(now: list[str], then: list[str], header: str) -> str:
    result = [header]
    current = bars(now)
    for number, lines in bars(then).items():
        length = re.search(r"len=(\d+)", lines[0])[1]
        written = {line.split(":")[0] for line in lines if VOICE.fullmatch(line)}
        cells = [line.split(":")[0] for line in current.get(number, []) if VOICE.fullmatch(line)]
        result += lines + [f"{cell}: {length} r" for cell in cells if cell not in written]
    return "\n".join(result)
