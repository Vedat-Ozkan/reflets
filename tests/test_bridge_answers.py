import asyncio
import json
import pathlib

import pytest
import websockets
from mcp.server.mcpserver.exceptions import ToolError

from reflets import bridge as bridge_module
from reflets import server
from reflets.bridge import PROTO, Bridge, BridgeError


class Plugin:
    def __init__(self, unanswered=()):
        self.received = []
        self.unanswered = list(unanswered)
        self.open = set()

    async def __call__(self, socket):
        self.open.add(socket)
        try:
            async for text in socket:
                rid, verb = text.split(" ")[:2]
                self.received.append(verb)
                if verb == "hello":
                    await socket.send(f"{rid} ok proto={PROTO}")
                elif verb in self.unanswered:
                    self.unanswered.remove(verb)
                else:
                    await socket.send(f"{rid} ok\nanswer to {verb}")
        finally:
            self.open.discard(socket)


def run(plugin, tmp_path: pathlib.Path, scene):
    async def main():
        async with websockets.serve(plugin, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            token = tmp_path / "token.txt"
            token.write_text("secret")
            return await scene(Bridge(port, token))

    return asyncio.run(main())


@pytest.fixture(autouse=True)
def short_wait(monkeypatch):
    monkeypatch.setattr(bridge_module, "TIMEOUT", 0.2)


@pytest.mark.parametrize("line", ["write 0 480 idea\nv 0 0", "color 0 480 0 #000000 keep idea", "undo", "redo"])
def test_a_change_with_no_answer_is_sent_once_and_reported(tmp_path, line):
    verb = line.split(" ")[0].split("\n")[0]
    plugin = Plugin(unanswered=[verb])

    async def scene(bridge):
        with pytest.raises(BridgeError, match="did not answer"):
            await bridge.request(line)

    run(plugin, tmp_path, scene)
    assert plugin.received.count(verb) == 1


def test_a_read_with_no_answer_is_asked_again(tmp_path):
    plugin = Plugin(unanswered=["read"])

    async def scene(bridge):
        return await bridge.request("read 0 480")

    _, lines = run(plugin, tmp_path, scene)
    assert lines == ["answer to read"]
    assert plugin.received.count("read") == 2


def test_a_change_goes_through_a_connection_that_closed_while_idle(tmp_path):
    plugin = Plugin()

    async def scene(bridge):
        await bridge.request("info")
        for socket in list(plugin.open):
            await socket.close()
        await asyncio.sleep(0.05)
        return await bridge.request("write 0 480 idea\nv 0 0")

    _, lines = run(plugin, tmp_path, scene)
    assert lines == ["answer to write"]
    assert plugin.received.count("write") == 1


def test_a_dropped_connection_is_closed(tmp_path):
    plugin = Plugin(unanswered=["read"])

    async def scene(bridge):
        await bridge.request("read 0 480")
        await asyncio.sleep(0.05)
        return len(plugin.open)

    assert run(plugin, tmp_path, scene) == 1


CHORALE = json.loads((pathlib.Path(__file__).parent / "data" / "reading" / "chorale.json").read_text())
INFO = [line for line in CHORALE["info"] if not line.startswith("L ")]
SOPRANO_IDEA = "N1x div=2 ts=4/4 ks=3s\nm2 len=8\n1.1: 1 A4 B4 2 G#4 F#4[fermata] A4"


def tick(line):
    return int(line.split(" ")[1])


def soprano(line, start):
    return line.startswith("C ") and line.split(" ")[2] == "0" and start <= tick(line) < start + 1920


def with_bar_3_soprano_in_bar_2(lines):
    kept = [line for line in lines if not soprano(line, 2400)]
    moved = [" ".join([words[0], str(int(words[1]) - 1920), *words[2:]]) for words in (line.split(" ") for line in lines if soprano(line, 4320))]
    return kept + moved


class Score:
    def __init__(self, lines):
        self.lines = list(lines)
        self.done, self.undone = [], []
        self.writes = []

    def read(self, start, end):
        return [line for line in self.lines if start <= tick(line) < end]

    async def __call__(self, socket):
        async for text in socket:
            rid, verb, *words = text.split("\n")[0].split(" ")
            body = []
            if verb == "hello":
                words = [f"proto={PROTO}", f"division={CHORALE['division']}"]
            elif verb == "info":
                body = INFO
            elif verb == "read":
                body = self.read(int(words[0]), int(words[1]))
            elif verb == "write":
                after, answered = self.writes.pop(0) if self.writes else (self.lines, True)
                if after is not None:
                    self.done.append(self.lines)
                    self.lines = after
                if not answered:
                    continue
                body = self.read(int(words[0]), int(words[1]))
            elif verb == "undo":
                self.undone.append(self.lines)
                self.lines = self.done.pop()
            elif verb == "redo":
                self.done.append(self.lines)
                self.lines = self.undone.pop()
            head = " ".join([rid, "ok", *words]) if verb == "hello" else f"{rid} ok"
            await socket.send("\n".join([head, *body]))


def served(tmp_path, monkeypatch, score, scene):
    async def main():
        async with websockets.serve(score, "127.0.0.1", 0) as listening:
            token = tmp_path / "reflets-token.txt"
            token.write_text("secret")
            monkeypatch.setenv("REFLETS_TOKEN_FILE", str(token))
            monkeypatch.setenv("REFLETS_PORT", str(listening.sockets[0].getsockname()[1]))
            return await scene()

    return asyncio.run(main())


def test_an_answered_write_is_open_and_discard_removes_it(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(changed, True)]

    async def scene():
        written = await server.propose(SOPRANO_IDEA, replace=True)
        assert "Read-back matched" in written
        return await server.discard("p1")

    assert served(tmp_path, monkeypatch, score, scene).startswith("Discarded p1")
    assert score.lines == CHORALE["read"]


def test_a_write_that_landed_with_no_answer_is_open_at_the_next_call(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        return await server.discard("p1")

    assert "Discarded p1" in served(tmp_path, monkeypatch, score, scene)
    assert sorted(score.lines) == sorted(CHORALE["read"])


def test_a_write_that_never_landed_leaves_nothing_and_the_next_propose_works(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    score.writes = [(None, False), (changed, True)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        return await server.propose(SOPRANO_IDEA, replace=True)

    written = served(tmp_path, monkeypatch, score, scene)
    assert "p1 never reached the score" in written
    assert "proposal id: p2" in written
    assert score.lines == changed
    assert list(server.stored()["open"]) == ["p2"]


def test_bars_that_match_neither_state_are_named_and_left_alone(tmp_path, monkeypatch):
    score = Score(CHORALE["read"])
    score.writes = [(with_bar_3_soprano_in_bar_2(CHORALE["read"]), False)]

    async def scene():
        with pytest.raises(ToolError, match="p1"):
            await server.propose(SOPRANO_IDEA, replace=True)
        score.lines = [line for line in score.lines if not (line.startswith("C 2400 4 "))]
        edited = list(score.lines)
        with pytest.raises(ToolError, match="bar 2") as refused:
            await server.discard("p1")
        assert score.lines == edited
        return str(refused.value)

    assert "neither" in served(tmp_path, monkeypatch, score, scene)
    assert server.stored()["open"] == {}


def test_a_restore_whose_second_write_landed_with_no_answer_is_open_at_the_next_call(tmp_path, monkeypatch):
    fermata = "A 3360 0 Fermata fermataAbove "
    changed = with_bar_3_soprano_in_bar_2(CHORALE["read"])
    checkpoint = [line for line in CHORALE["read"] if line != fermata]
    score = Score(changed)
    score.writes = [([line for line in changed if line != fermata], True), (checkpoint, False)]

    async def scene():
        folder = server.checkpoint_folder("bwv66.6.musicxml")
        folder.mkdir(parents=True)
        (folder / "001 before.json").write_text(json.dumps({"name": "before", "saved": "2026-11-13 10:00", "info": INFO, "read": checkpoint}))
        with pytest.raises(ToolError, match="p1, its first step") as lost:
            await server.restore(1, "2")
        assert "nothing changed" not in str(lost.value)
        assert "Discarded p2" in await server.discard("p2")
        return await server.discard("p1")

    assert "Discarded p1" in served(tmp_path, monkeypatch, score, scene)
    assert sorted(score.lines) == sorted(changed)
