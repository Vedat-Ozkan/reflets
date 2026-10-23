import asyncio
import re
import sys

from reflets import server
from reflets.restore import bare_idea, writable

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def proposal(result: str) -> str:
    return re.search(r"proposal id: (p\d+)", result)[1]


async def main() -> None:
    info = await server.load_info()
    bar = info.measures[2].number
    length = int(info.lengths[2] * 4)
    start = await server.read_score(str(bar))
    header = f"N1x div=4\nm{bar} len={length}\n1.1: "
    written = [proposal(await server.propose(bare_idea(writable(start), start.splitlines()[0]), "lines: bare", replace=True))]
    written.append(proposal(await server.propose(header + f"<( {length // 4} C5 D5 E5 <) F5", "lines: a hairpin the bridge makes", replace=True)))
    written.append(proposal(await server.propose(header + f"{length // 4} G4 A4 B4 C5", "lines: new notes under it", replace=True)))
    written.append(proposal(await server.propose(header + f"-<( {length // 4} G4 A4 B4 -<) C5", "lines: the hairpin removed", replace=True)))
    line = next(line for line in (await server.read_score(str(bar))).splitlines() if line.startswith("1.1:"))
    check("a hairpin the bridge made is removed after the notes under it were rewritten", "<(" not in line and "G4" in line, line)
    for proposal_id in reversed(written):
        await server.discard(proposal_id)
    check("the bar is as before after the discards", await server.read_score(str(bar)) == start)
    sys.exit(1 if failures else 0)


asyncio.run(main())
