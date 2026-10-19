"""Build N1 for the test scores with the engine (verovio + ScoreIndex + notes.encode), as build_base.py does.

Usage: uv run --with verovio python build.py   (writes n1/<name>.n1.txt next to this file)
"""
import base64
from importlib.resources import files
from pathlib import Path

import verovio
from engine import notes
from engine.score import ScoreIndex

DATA = Path(__file__).resolve().parents[4] / "sheet-music-plugin/tests/data"
SCORES = {
    "chopin-nocturne": "chopin_nocturne_op9_no2.mxl",
    "mozart-k458": "export-mozart-k458.musicxml",
    "brahms-118-2": "export-brahms-118-2.musicxml",
    "debussy-clair": "export-debussy-clair.musicxml",
    "bach-bwv64-4": "part_writing_bwv64.4.musicxml",
    "chopin-prelude-4": "chopin_prelude_op28_no4_reading.musicxml",
    "mozart-k545-1": "mozart-k545-1-simulated-scan-reading.musicxml",
    "brahms-fruehlingstrost": "triplet_brahms_fruhlingstrost.musicxml",
    "haydn-104": "piano/haydn-104.mxl",
    "dvorak-9-2": "piano/dvorak-9-2.mxl",
    "mozart-41": "piano/mozart-41.mxl",
}
OUT = Path(__file__).resolve().parent / "n1"


def load(path: Path) -> ScoreIndex:
    raw = path.read_bytes()
    tk = verovio.toolkit(False)
    tk.setResourcePath(str(files("verovio") / "data"))
    tk.setOptions({"xmlIdChecksum": True})
    ok = tk.loadZipDataBase64(base64.b64encode(raw).decode()) if raw[:2] == b"PK" else tk.loadData(raw.decode("utf-8-sig"))
    assert ok, path
    return ScoreIndex(tk.getMEI())


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, file in SCORES.items():
        index = load(DATA / file)
        n1 = notes.encode(index)
        (OUT / f"{name}.n1.txt").write_text(n1 + "\n")
        count = sum(1 for m in index.measures for e in m.events if e.pitch)
        print(name, file, "bars", len(index.measures), "notes", count, "chars", len(n1))
