import asyncio
import pathlib

import pytest
import websockets

from reflets import bridge as bridge_module
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
