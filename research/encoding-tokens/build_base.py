import base64, json, os, sys, zipfile
from fractions import Fraction
from pathlib import Path
ENGINE = Path(os.environ.get("SHEET_MUSIC_REPO", Path(__file__).resolve().parents[3] / "sheet-music-analysis"))
sys.path.insert(0, str(ENGINE))
import verovio
from importlib.resources import files
from engine import notes
from engine.score import ScoreIndex

MXL = Path(ENGINE / "tests/data/chopin_nocturne_op9_no2.mxl")
OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

tk = verovio.toolkit(False)
tk.setResourcePath(str(files("verovio") / "data"))
tk.setOptions({"xmlIdChecksum": True})
assert tk.loadZipDataBase64(base64.b64encode(MXL.read_bytes()).decode())
mei = tk.getMEI()
index = ScoreIndex(mei)
div = index.ppq

n1 =notes.encode(index)
(OUT / "chopin.n1.txt").write_text(n1 + "\n")

rows = []
for m in index.measures:
    for e in m.events:
        if not e.pitch:
            continue
        row = {"m": m.number, "s": e.staff, "v": e.layer, "o": int(e.onset * div), "d": int(e.duration * div), "p": e.pitch}
        if e.grace:
            row["g"] = 1
        if e.tied:
            row["t"] = 1
        rows.append(row)
doc = {"div": div, "ts": index.meter, "ks": index.key_signature, "measures": [{"n": m.number, "len": int(m.length * div)} for m in index.measures], "notes": rows}
(OUT / "chopin.notes.min.json").write_text(json.dumps(doc, separators=(",", ":")))
(OUT / "chopin.notes.verbose.json").write_text(json.dumps(doc, indent=2))

with zipfile.ZipFile(MXL) as z:
    name = [n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META-INF")][0]
    xml = z.read(name).decode("utf-8")
(OUT / "chopin.musicxml").write_text(xml)

(OUT / "chopin.mei").write_text(mei)

print("notes", len(rows), "measures", len(index.measures), "div", div)
for f in ["chopin.n1.txt", "chopin.notes.min.json", "chopin.notes.verbose.json", "chopin.musicxml", "chopin.mei"]:
    print(f, len((OUT / f).read_text()))
