import asyncio
import json
import re
import subprocess
import sys

from mcp.server.mcpserver.exceptions import ToolError

from reflets import server

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def fresh(call: str) -> str:
    code = f"import asyncio\nfrom reflets import server\nprint(asyncio.run(server.{call}))"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    return done.stdout + done.stderr


async def main() -> None:
    info = await server.load_info()
    folder = server.checkpoint_folder(info.title)
    saved = set(folder.glob("*"))
    bar, length = info.measures[1].number, int(info.lengths[1] * 4)
    start = await server.read_score(str(bar))
    idea = repr(f"N1x div=4\nm{bar} len={length}\n1.2: {length} C5")
    written = re.search(r"proposal id: (p\d+)", fresh(f"propose({idea}, 'on disk')"))[1]
    check("a proposal from a server that has quit is open in a new one", written in json.loads(server.proposals_file().read_text())["open"])
    result = fresh(f"discard({written!r})")
    check("a new server discards it", f"Discarded {written}" in result and await server.read_score(str(bar)) == start, result)
    written = re.search(r"proposal id: (p\d+)", fresh(f"propose({idea}, 'on disk')"))[1]
    result = fresh(f"keep({written!r})")
    check("a new server keeps one", f"Kept {written}" in result and "C5" in await server.read_score(str(bar)), result)
    await server.request("undo")
    await server.request("undo")
    check("ids are not reused", int(written[1:]) > 1 and re.search(r"proposal id: (p\d+)", await server.propose(idea[1:-1].replace("\\n", "\n"), "on disk"))[1] != written)
    data = json.loads(server.proposals_file().read_text())
    latest = max(data["open"], key=lambda key: int(key[1:]))
    data["open"][latest]["title"] = "Another score"
    server.proposals_file().write_text(json.dumps(data))
    try:
        await server.discard(latest)
        error = "not refused"
    except ToolError as refused:
        error = str(refused)
    check("a proposal written in another score is refused", '"Another score"' in error and "Nothing was done" in error, error)
    data["open"][latest]["title"] = info.title
    server.proposals_file().write_text(json.dumps(data))
    await server.discard(latest)
    check("the bar is as before", await server.read_score(str(bar)) == start)
    for tool in ("discard", "keep"):
        written = re.search(r"proposal id: (p\d+)", await server.propose(idea[1:-1].replace("\\n", "\n"), "undone"))[1]
        await server.request("undo")
        try:
            result = await getattr(server, tool)(written)
        except ToolError as refused:
            result = str(refused)
        check(f"{tool} of a proposal undone in MuseScore closes it", "no longer in the score" in result
              and written not in json.loads(server.proposals_file().read_text())["open"]
              and await server.read_score(str(bar)) == start, result)
    other, other_length = info.measures[2].number, int(info.lengths[2] * 4)
    other_start = await server.read_score(str(other))
    first = f"N1x div=4\nm{bar} len={length}\n1.1: {length} C5"
    second = f"N1x div=4\nm{other} len={other_length}\n1.2: {other_length} C5"
    for later in ("open", "kept"):
        a = re.search(r"proposal id: (p\d+)", await server.propose(first, "A", replace=True))[1]
        b = re.search(r"proposal id: (p\d+)", await server.propose(second, "B"))[1]
        if later == "kept":
            await server.keep(b)
        try:
            result = await server.discard(a)
        except ToolError as refused:
            result = str(refused)
        open_ids = json.loads(server.proposals_file().read_text())["open"]
        check(f"discard of A with B {later} after it writes bar {bar} back", "undo steps" in result
              and await server.read_score(str(bar)) == start and a not in open_ids, result)
        check(f"B, {later}, stays in bar {other}", await server.read_score(str(other)) != other_start and (b in open_ids) == (later == "open"))
        if later == "open":
            print(f"LOOK in MuseScore (read carries no colour): bar {bar} is black and as before, bar {other}'s C5 is still {server.IDEA_COLOUR}")
            try:
                result = await server.discard(b)
            except ToolError as refused:
                result = str(refused)
            check("then discard of B puts its bar back too", f"Discarded {b}" in result and await server.read_score(str(other)) == other_start
                  and await server.read_score(str(bar)) == start, result)
        else:
            steps = int(re.search(r"in (\d+) undo steps", result)[1]) if "undo steps" in result else 0
            for _ in range(steps + 3):
                await server.request("undo")
            check("undoing the write-back, the keep, B and A leaves both bars as before",
                  await server.read_score(str(bar)) == start and await server.read_score(str(other)) == other_start)
    for path in set(folder.glob("*")) - saved:
        path.unlink()
    sys.exit(1 if failures else 0)


asyncio.run(main())
