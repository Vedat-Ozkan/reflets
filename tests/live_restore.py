import asyncio
import re
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import server

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def looks(lines: list[str]) -> list[tuple[str, ...]]:
    return sorted(tuple(line.split()[1:3] + [word for word in line.split()[4:-1] if word[0] in "SB"]) for line in lines if line.startswith("C "))


def proposal(result: str) -> str:
    return re.search(r"proposal id: (p\d+)", result)[1]


async def refused(call) -> str:
    try:
        await call
    except ToolError as error:
        return str(error)
    return "not refused"


async def main() -> None:
    info = await server.load_info()
    folder = server.checkpoint_folder(info.title)
    saved = set(folder.glob("*"))
    bar, length = info.measures[1].number, int(info.lengths[1] * 4)
    start, whole = await server.read_score(str(bar)), await server.read_score("all")
    span = f"read {info.ticks[1]} {info.ticks[2]}"
    rests = sorted(line for line in await server.request(span) if line.startswith("R "))
    number = int(re.search(r"Checkpoint (\d+)", await server.checkpoint("restore test"))[1])
    idea = f"N1x div=4\nm{bar} len={length}\n1.1: !ff\n1.2: {length // 2} ( C5[stacc] D5 )\n1.2 L1: la la"
    await server.keep(proposal(await server.propose(idea, "restore test", replace=True)))
    changed = await server.read_score(str(bar))
    check("the idea added a dynamic, a staccato, a slur and a lyric", all(token in changed for token in ("!ff", "[stacc]", "( ", "1.2 L1: la la")), changed)
    later = int(re.search(r"Checkpoint (\d+)", await server.checkpoint("with the idea"))[1])
    other = f"N1x div=4\nm{bar} len={length}\n1.2: -( {length} E5[-stacc]"
    await server.keep(proposal(await server.propose(other, "restore test", replace=True)))
    result = await server.restore(later, str(bar))
    check("restore brings back the notes, rhythm, staccato and slur of an idea", await server.read_score(str(bar)) == changed, f"{result}\n{await server.read_score(str(bar))}")
    await server.keep(proposal(result))
    result = await server.restore(number, str(bar))
    check("restore brings the bar back as it was at the checkpoint", await server.read_score(str(bar)) == start, f"{result}\n{await server.read_score(str(bar))}")
    left = sorted(line for line in await server.request(span) if line.startswith("R "))
    check("a voice the checkpoint does not have leaves no rests", left == rests, f"{rests} vs {left}")
    await server.discard(proposal(result))
    check("discarding the restore takes the bar back to the kept idea", await server.read_score(str(bar)) == changed, await server.read_score(str(bar)))
    everything = f"{info.measures[0].number}-{info.measures[-1].number}"
    await server.keep(proposal(await server.restore(number, everything)))
    check("a kept restore of every bar leaves the score as at the checkpoint", await server.read_score("all") == whole)
    again = await server.restore(number, str(bar))
    check("restoring bars already as at the checkpoint changes nothing", "already" in again, again)
    tried = []
    for position, measure in enumerate(info.measures):
        end = info.ticks[position + 1] if position + 1 < len(info.ticks) else 2**31 - 1
        here = f"read {info.ticks[position]} {end}"
        drawn = looks(await server.request(here))
        if not any(len(look) > 2 and look[1] == "0" for look in drawn):
            continue
        before, size = await server.read_score(str(measure.number)), int(info.lengths[position] * 4)
        try:
            emptied = proposal(await server.propose(f"N1x div=4\nm{measure.number} len={size}\n1.1: {size} r", "restore test", replace=True))
        except ToolError as error:
            tried.append(f"bar {measure.number}: {error}")
            continue
        await server.keep(emptied)
        await server.keep(proposal(await server.restore(number, str(measure.number))))
        after = looks(await server.request(here))
        check(f"restore brings back the stem directions and beam modes the checkpoint has (bar {measure.number})", after == drawn and await server.read_score(str(measure.number)) == before, f"{drawn}\n{after}")
        break
    else:
        reason = "; ".join(tried[:3]) if tried else "the score has no stem direction or beam mode set in voice 1.1, so there is nothing to check"
        print(f"SKIP stem directions and beam modes: {reason}")
    error = await refused(server.restore(999, str(bar)))
    check("an unknown checkpoint is refused with the list", "no checkpoint 999" in error and '"restore test"' in error, error)
    for path in set(folder.glob("*")) - saved:
        path.unlink()
    sys.exit(1 if failures else 0)


asyncio.run(main())
