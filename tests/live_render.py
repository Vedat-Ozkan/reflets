import asyncio
import re
import sys
from pathlib import Path

from PIL import Image

from reflets import server

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def images(result: str) -> list[Path]:
    return [Path(path) for path in re.findall(r"(/\S+\.png)", result)]


def red(path: Path) -> int:
    pixels = Image.open(path).convert("RGB").get_flattened_data()
    return sum(1 for r, g, b in pixels if r > 180 and g < 90 and b < 90)


def blue(path: Path) -> int:
    pixels = Image.open(path).convert("RGB").get_flattened_data()
    return sum(1 for r, g, b in pixels if b > 150 and r < 60 and 60 < g < 140)


async def main() -> None:
    title = (await server.load_info()).title
    plain = await server.render("1-4")
    check("plain bars give a PNG", images(plain) and all(path.exists() and Image.open(path).width > 0 for path in images(plain)), plain)
    check("plain bars draw nothing red", all(red(path) == 0 for path in images(plain)), plain)
    info = await server.load_info()
    bar, length = info.measures[1].number, int(info.lengths[1] * 4)
    written = re.search(r"proposal id: (p\d+)", await server.propose(f"N1x div=4\nm{bar} len={length}\n1.2: {length} C5", "render"))[1]
    idea = await server.render(str(bar))
    await server.discard(written)
    check("an idea not yet kept is rendered in its colour", blue(images(idea)[0]) > 20, idea)
    drawn = await server.render("1-5", check=True)
    if "motion" in title.lower():
        check("the findings are listed and drawn in red", "2 numbered spot(s)" in drawn and "1. m2 b1" in drawn and "2. m5 b1" in drawn and red(images(drawn)[0]) > 50, drawn)
    elif "66" in title:
        drawn = await server.render("0-7", check=True)
        check("findings after a pickup are drawn on the bars MuseScore numbers", "m4 b3" in drawn and "m7 b2.5" in drawn and red(images(drawn)[0]) > 50, drawn)
    else:
        check("a score the rules do not fit is rendered with a note", "do not apply" in drawn and images(drawn), drawn)
    check("the export file is gone", not list(server.token_file().parent.glob("reflets-export-*")))
    sys.exit(1 if failures else 0)


asyncio.run(main())
