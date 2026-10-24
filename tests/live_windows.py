import asyncio
import re
import sys
import time

from reflets import server
from reflets.bridge import chosen

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def call(coro):
    return await asyncio.create_task(coro)


async def main() -> None:
    windows = await call(server.windows())
    titles = [info.title for _, info in windows]
    check("at least two windows with different scores answer", len(set(titles)) >= 2, str(titles))
    if failures:
        sys.exit(1)
    report = await call(server.score_info())
    current = re.search(r'\n"(.*)": ', report)[1]
    check("score_info names the other open scores", all(f'"{title}"' in report.split("Also open", 1)[-1] for title in titles if title != current), report)
    other, info = next((window, info) for window, info in reversed(windows) if info.title != current)
    folder = server.checkpoint_folder(info.title)
    saved = set(folder.glob("*"))
    bar, length = info.measures[1].number, int(info.lengths[1] * 4)
    idea = f"N1x div=4\nm{bar} len={length}\n1.2: {length} C5"

    async def in_other(coro_factory):
        chosen.set(other)
        return await coro_factory()

    start = await call(in_other(lambda: server.read_score(str(bar))))
    written = re.search(r"proposal id: (p\d+)", await call(in_other(lambda: server.propose(idea, "other window"))))[1]
    result = await call(server.discard(written))
    after = await call(in_other(lambda: server.read_score(str(bar))))
    check(f'discard from the window used last ("{current}") reaches "{info.title}"', f"Discarded {written}" in result and after == start, result)
    written = re.search(r"proposal id: (p\d+)", await call(in_other(lambda: server.propose(idea, "other window"))))[1]
    result = await call(server.keep(written))
    check(f'keep reaches "{info.title}"', f"Kept {written}" in result and "C5" in await call(in_other(lambda: server.read_score(str(bar)))), result)

    async def undo_twice():
        await server.request("undo")
        await server.request("undo")

    await call(in_other(undo_twice))
    check("the bar is as before", await call(in_other(lambda: server.read_score(str(bar)))) == start)
    for path in set(folder.glob("*")) - saved:
        path.unlink()
    if not saved and folder.exists():
        folder.rmdir()

    stale = server.token_file().parent / "reflets-token-8740.txt"
    stale.write_text("stale")
    try:
        times = []
        for _ in range(2):
            began = time.monotonic()
            await call(server.score_info())
            times.append(time.monotonic() - began)
        check("a token file nothing answers costs one short wait, then none, and is removed",
              times[0] < 5 and times[1] < 1 and not stale.exists(), str(times))
    finally:
        stale.unlink(missing_ok=True)
    sys.exit(1 if failures else 0)


asyncio.run(main())
