import asyncio
import json
import re
import sys
from pathlib import Path

from reflets import server

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def saved(result: str) -> tuple[int, Path]:
    found = re.search(r"Checkpoint (\d+) .* saved: ([A-Z]):/(\S.*)$", result, re.M)
    return int(found[1]), Path(f"/mnt/{found[2].lower()}/{found[3]}")


async def main() -> None:
    info = await server.load_info()
    folder = server.checkpoint_folder(info.title)
    before = set(folder.glob("*")) if folder.exists() else set()
    first, score = saved(await server.checkpoint("before the idea"))
    stored = json.loads(score.with_suffix(".json").read_text())
    check("a named checkpoint is a MusicXML file", score.read_text().count("<measure") >= len(info.measures), str(score))
    check("it keeps the bridge's lines for the whole score", server.parse_info(stored["info"]).title == info.title and stored["read"], str(stored)[:300])
    bar, length = info.measures[1].number, int(info.lengths[1] * 4)
    start = await server.read_score(str(bar))
    written = re.search(r"proposal id: (p\d+)", await server.propose(f"N1x div=4\nm{bar} len={length}\n1.2: {length} C5", "checkpoint test"))[1]
    kept = await server.keep(written)
    second, kept_score = saved(kept)
    check("keep saves a checkpoint named after the idea", second == first + 1 and '"keep checkpoint test"' in kept, kept)
    later = json.loads(kept_score.with_suffix(".json").read_text())
    check("the keep checkpoint holds the kept notes", len(later["read"]) > len(stored["read"]), f"{len(later['read'])} vs {len(stored['read'])}")
    third, odd = saved(await server.checkpoint('a/b: "c"?'))
    check("a name with characters Windows refuses still saves", odd.exists() and third == second + 1, str(odd))
    listing = await server.restore()
    check("the list names each checkpoint by number", all(f'{n}. "{name}"' in listing for n, name in ((first, "before the idea"), (second, "keep checkpoint test"), (third, 'a/b: "c"?'))), listing)
    await server.request("undo")
    await server.request("undo")
    check("the bar is as before", await server.read_score(str(bar)) == start)
    for path in set(folder.glob("*")) - before:
        path.unlink()
    if not before:
        folder.rmdir()
    sys.exit(1 if failures else 0)


asyncio.run(main())
