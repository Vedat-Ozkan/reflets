import asyncio
import sys

from reflets import server

MOTION = {
    "m1 b1 to m2 b1, 1.1 and 3.1, parallel fifths",
    "m1 b1 to m2 b1, 1.1 and 4.1, parallel fifths",
    "m1 b1 to m2 b1, 3.1 and 4.1, parallel octaves",
    "m4 b1 to m5 b1, 1.1 and 4.1, parallel octaves",
    "m4 b1 to m5 b1, 3.1 and 4.1, parallel fifths",
    "m7 b1 to m8 b1, 1.1 and 4.1, direct fifths",
    "m10 b1 to m11 b1, 1.1 and 4.1, direct octaves",
    "m13 b1, 1.1 and 2.1, voice crossing",
    "m15 b1, 1.1, range",
    "m17 b1 to m18 b1, 1.1 and 2.1, voice overlap",
    "m20 b1 to m21 b1, 1.1 and 2.1, parallel fifths",
    "m20 b1 to m21 b1, 1.1 and 3.1, parallel fifths",
    "m20 b1 to m21 b1, 2.1 and 3.1, parallel octaves",
    "m20 b1 to m21 b1, 2.1 and 3.1, voice overlap",
    "m23 b1, 1.1 and 2.1, spacing",
}
CHORALE = {
    "m4 b3 to m4 b3.5, 3.1 and 4.1, voice overlap",
    "m5 b1 to m5 b1.5, 2.1 and 3.1, voice overlap",
    "m7 b2.5, 2.1, range",
    "m7 b2.5, 2.1 and 3.1, voice crossing",
}
failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def found(report: str) -> set[str]:
    return {line.split(". ", 1)[1].split(":")[0] for line in report.splitlines() if line[:1].isdigit() and ". m" in line}


async def main() -> None:
    title = (await server.load_info()).title
    report = await server.check("all")
    if "motion" in title.lower():
        check("the planted errors are found, each once", found(report) == MOTION and len(found(report)) == len(report.split("\n\nVoice-leading")[1].splitlines()) - 1, report)
        report = await server.check("4-5")
        check("a range finds only its own errors", found(report) == {f for f in MOTION if f.startswith("m4 ")}, report)
        check("a range's table holds only its bars", "\nm4\n" in report and "\nm5\n" in report and "\nm3\n" not in report and "\nm6\n" not in report, report)
    elif "66" in title:
        check("the chorale's findings are numbered as MuseScore numbers its bars", found(report) == CHORALE, report)
        report = await server.check("0-1")
        check("the pickup is bar 0", "\nm0\n" in report and "No rule broken." in report, report)
    else:
        check("a score the rules do not fit says so", "do not apply to bars" in report and "\nm1\n" in report, report)
    sys.exit(1 if failures else 0)


asyncio.run(main())
