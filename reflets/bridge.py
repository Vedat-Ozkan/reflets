from __future__ import annotations

import asyncio
import contextvars
import functools
import os
import platform
import subprocess
from importlib.metadata import version
from pathlib import Path

import websockets

PROTO = 24
CLIENT = f"reflets-server/{version('reflets')}"
TIMEOUT = 10
OTHER_TIMEOUT = 1
CHANGES_THE_SCORE = {"write", "color", "undo", "redo"}
NOT_RUNNING = (
    "Reflets cannot reach MuseScore. Open MuseScore Studio 4.7, open your score, and run "
    "Plugins > Reflets Bridge once (it keeps running until MuseScore quits)."
)


NO_ANSWER = (
    "MuseScore did not answer, so this change may or may not have reached the score. It was not sent again. "
    "Read the bars to see which happened."
)


class BridgeError(Exception):
    pass


def token_file() -> Path:
    if "REFLETS_TOKEN_FILE" in os.environ:
        return Path(os.environ["REFLETS_TOKEN_FILE"])
    return documents() / "MuseScore4" / "Plugins" / "reflets-bridge" / "reflets-token.txt"


@functools.cache
def documents() -> Path:
    wsl = "microsoft" in platform.uname().release.lower()
    if os.name != "nt" and not wsl:
        return Path.home() / "Documents"
    folder = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"], capture_output=True, text=True
    ).stdout.strip()
    if not wsl:
        return Path(folder)
    return Path(subprocess.run(["wslpath", "-u", folder], capture_output=True, text=True).stdout.strip())


def written(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


class Bridge:
    def __init__(self, port: int, token: Path, open_timeout: float = TIMEOUT) -> None:
        self.url = f"ws://127.0.0.1:{port}"
        self.token = token
        self.open_timeout = open_timeout
        self.dead: float | None = None
        self.socket = None
        self.next_id = 1
        self.hello: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def request(self, line: str) -> tuple[list[str], list[str]]:
        async with self.lock:
            for _ in range(2):
                try:
                    if self.socket is None:
                        await self._connect()
                    return await self._send(line)
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed):
                    await self._drop()
            raise BridgeError(NOT_RUNNING)

    async def _drop(self) -> None:
        socket, self.socket = self.socket, None
        if socket is not None:
            await socket.close()

    async def _connect(self) -> None:
        try:
            token = self.token.read_text().strip()
        except FileNotFoundError:
            raise BridgeError(f"{NOT_RUNNING} (No token file at {self.token}.)") from None
        self.socket = await websockets.connect(self.url, open_timeout=self.open_timeout, close_timeout=OTHER_TIMEOUT, max_size=None)
        self.next_id = 1
        try:
            words, _ = await self._send(f"hello proto={PROTO} token={token} client={CLIENT}")
        except BridgeError:
            await self._drop()
            raise
        self.hello = dict(word.split("=", 1) for word in words if "=" in word)
        if self.hello.get("proto") != str(PROTO):
            await self._drop()
            newer = int(self.hello.get("proto", "0")) > PROTO
            raise BridgeError(
                f"The Reflets Bridge plugin speaks protocol {self.hello.get('proto')}, this server {PROTO}. "
                + ("Restart the Reflets server (in Claude Code: /mcp, then reconnect reflets)." if newer
                   else "Install the plugin file that came with this server and restart MuseScore.")
            )

    async def _send(self, line: str) -> tuple[list[str], list[str]]:
        rid = self.next_id
        self.next_id += 1
        await self.socket.send(f"{rid} {line}")
        while True:
            try:
                reply = await asyncio.wait_for(self.socket.recv(), TIMEOUT)
            except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed):
                if line.split(maxsplit=1)[0] not in CHANGES_THE_SCORE:
                    raise
                await self._drop()
                raise BridgeError(NO_ANSWER) from None
            lines = reply.split("\n")
            words = lines[0].split(" ")
            if words[0] == str(rid):
                break
        if words[1] != "ok":
            code = words[2] if len(words) > 2 else "error"
            message = " ".join(words[3:])
            if code == "no-score":
                raise BridgeError("MuseScore has no score open. Ask the user to open their score.")
            if code == "unauthorized":
                raise BridgeError(
                    "The Reflets Bridge plugin refused the connection: " + message
                    + f". The token file is {self.token}; set REFLETS_TOKEN_FILE if MuseScore's plugin folder is elsewhere."
                )
            raise BridgeError(f"The bridge plugin reported {code}: {message}")
        return words[2:], lines[1:]

    async def listening(self, timeout: float = OTHER_TIMEOUT) -> bool:
        host, port = self.url.removeprefix("ws://").rsplit(":", 1)
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), timeout)
        except (OSError, asyncio.TimeoutError):
            return False
        writer.close()
        return True

    async def active(self) -> int:
        words, _ = await self.request("ping")
        return int(dict(word.split("=", 1) for word in words if "=" in word).get("active", 0))


chosen: contextvars.ContextVar[Bridge | None] = contextvars.ContextVar("chosen", default=None)


class Bridges:
    def __init__(self) -> None:
        self.known: dict[Path, Bridge] = {}

    @property
    def first(self) -> Bridge:
        return self.at(token_file(), int(os.environ.get("REFLETS_PORT", "8731")))

    def at(self, token: Path, port: int, open_timeout: float = TIMEOUT) -> Bridge:
        if token not in self.known:
            self.known[token] = Bridge(port, token, open_timeout)
        return self.known[token]

    def found(self) -> list[Bridge]:
        more = sorted(path for path in token_file().parent.glob("reflets-token-*.txt") if path.stem.rsplit("-", 1)[1].isdigit())
        others = [self.at(path, int(path.stem.rsplit("-", 1)[1]), OTHER_TIMEOUT) for path in more]
        first = self.first
        first.open_timeout = OTHER_TIMEOUT if others else TIMEOUT
        return [bridge for bridge in [first] + others if bridge.dead != written(bridge.token)] or [first]

    async def pick(self) -> Bridge:
        found = self.found()
        if len(found) == 1:
            return found[0]
        live = []
        for bridge in found:
            try:
                live.append((await bridge.active(), bridge))
            except BridgeError:
                if await bridge.listening():
                    continue
                bridge.dead = written(bridge.token)
                if bridge is not self.first:
                    bridge.token.unlink(missing_ok=True)
        return max(live, key=lambda pair: pair[0])[1] if live else self.first

    async def request(self, line: str) -> tuple[list[str], list[str]]:
        bridge = chosen.get()
        if bridge is None:
            bridge = await self.pick()
            chosen.set(bridge)
        return await bridge.request(line)

    @property
    def current(self) -> Bridge:
        return chosen.get() or self.first

    @property
    def hello(self) -> dict[str, str]:
        return self.current.hello

    @property
    def socket(self):
        return self.current.socket
