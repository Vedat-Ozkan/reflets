import asyncio
import http.server
import json
import threading
from pathlib import Path

import numpy as np
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from reflets import audio, hum as humming, server

CHORALE = json.loads((Path(__file__).parent / "data/reading/chorale.json").read_text())
KEY = humming.Key(0, True, 0, 1.0)


class CapturedScore:
    hello = {"division": str(CHORALE["division"])}

    async def request(self, line):
        return [], CHORALE["info" if line == "info" else "read"]


@pytest.fixture
def takes(monkeypatch, tmp_path):
    monkeypatch.setenv("REFLETS_TOKEN_FILE", str(tmp_path / "token.txt"))
    monkeypatch.setattr(server, "bridge", CapturedScore())
    monkeypatch.setattr(server, "last_delays", {})
    monkeypatch.setattr(server, "last_keys", {})
    monkeypatch.setattr(audio, "record", lambda play, starts: audio.Take(np.zeros(1), starts, 0.05, "mic"))
    monkeypatch.setattr(audio, "echo", lambda take, beats: None)
    monkeypatch.setattr(humming, "calibration", lambda sound, starts: 0.3)
    seen = []

    def hummed(sound, starts, tempo, meter, bars, grid, guess, reach, known=None):
        seen.append((guess, known))
        return humming.Transcription([humming.Placed(0, 2, 60)], KEY, 0.0, 0.2, guess, None)

    async def write_idea(idea, label, replace):
        return "written"

    monkeypatch.setattr(humming, "hummed", hummed)
    monkeypatch.setattr(server, "write_idea", write_idea)
    return seen


def hum(**options):
    numbers = server.parse_info(CHORALE["info"]).numbers
    return asyncio.run(server.hum(start_bar=numbers[-1] + 1, bars=1, **options))


def test_a_new_calibration_is_used_by_the_next_take(takes):
    hum()
    hum()
    assert takes[1][0] == 0.2
    hum(calibrate=True)
    hum()
    assert takes[2] == (0.3, KEY)


def test_the_last_take_still_comes_before_an_older_calibration(takes):
    hum(calibrate=True)
    hum()
    hum()
    assert [guess for guess, _ in takes] == [0.3, 0.2]
    assert [known for _, known in takes] == [None, KEY]


class Uploads(http.server.BaseHTTPRequestHandler):
    stored: list[str] = []
    refuse: set[str] = set()

    def do_PUT(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        name = self.path.rsplit("/", 1)[1]
        if name in self.refuse:
            self.refuse.discard(name)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"try later")
            return
        self.stored.append(name)
        self.send_response(201)
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def uploads(monkeypatch, tmp_path):
    Uploads.stored, Uploads.refuse = [], set()
    monkeypatch.setenv("REFLETS_TOKEN_FILE", str(tmp_path / "token.txt"))
    site = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Uploads)
    threading.Thread(target=site.serve_forever, daemon=True).start()
    monkeypatch.setenv("REFLETS_TAKES_URL", f"http://127.0.0.1:{site.server_port}")
    folder = tmp_path / server.TEST_FOLDER
    folder.mkdir()
    for stem in ("take-1", "take-2"):
        (folder / f"{stem}.wav").write_bytes(b"sound")
        (folder / f"{stem}.json").write_text("{}")
    yield folder
    site.shutdown()


def send():
    return asyncio.run(server.hum_test(send=True, code="tester"))


def test_a_details_file_that_failed_is_sent_on_the_next_try(uploads):
    Uploads.refuse = {"take-1.json"}
    with pytest.raises(ToolError, match="try later"):
        send()
    assert send() == "Sent 2 takes. Thank the user: they go to the developer only."
    assert sorted(Uploads.stored) == ["take-1.json", "take-1.wav", "take-2.json", "take-2.wav"]
    assert not list(uploads.glob("*.*"))


def test_all_takes_go_in_one_try(uploads):
    assert send() == "Sent 2 takes. Thank the user: they go to the developer only."
    assert sorted(path.name for path in (uploads / "sent").iterdir()) == ["take-1.json", "take-1.wav", "take-2.json", "take-2.wav"]
