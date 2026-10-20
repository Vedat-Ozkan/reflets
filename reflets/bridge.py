from __future__ import annotations

import asyncio
import os
from pathlib import Path

import websockets

PROTO = 16
CLIENT = "reflets-server/0.2.0"
TIMEOUT = 10
NOT_RUNNING = (
    "Reflets cannot reach MuseScore. Open MuseScore Studio 4.7, open your score, and run "
    "Plugins > Reflets Bridge once (it keeps running until MuseScore quits)."
)


class BridgeError(Exception):
    pass


def token_file() -> Path:
    if "REFLETS_TOKEN_FILE" in os.environ:
        return Path(os.environ["REFLETS_TOKEN_FILE"])
    return Path.home() / "Documents" / "MuseScore4" / "Plugins" / "reflets-bridge" / "reflets-token.txt"


class Bridge:
    def __init__(self) -> None:
        self.url = f"ws://127.0.0.1:{os.environ.get('REFLETS_PORT', '8731')}"
        self.socket = None
        self.next_id = 1
        self.hello: dict[str, str] = {}
        self.lock = asyncio.Lock()

    async def request(self, line: str) -> tuple[list[str], list[str]]:
        async with self.lock:
            for attempt in (1, 2):
                try:
                    if self.socket is None:
                        await self._connect()
                    return await self._send(line)
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed):
                    self.socket = None
                    if attempt == 2:
                        raise BridgeError(NOT_RUNNING) from None
        raise AssertionError("unreachable")

    async def _connect(self) -> None:
        try:
            token = token_file().read_text().strip()
        except FileNotFoundError:
            raise BridgeError(f"{NOT_RUNNING} (No token file at {token_file()}.)") from None
        self.socket = await websockets.connect(self.url, open_timeout=TIMEOUT, max_size=None)
        self.next_id = 1
        try:
            words, _ = await self._send(f"hello proto={PROTO} token={token} client={CLIENT}")
        except BridgeError:
            self.socket = None
            raise
        self.hello = dict(word.split("=", 1) for word in words if "=" in word)
        if self.hello.get("proto") != str(PROTO):
            self.socket = None
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
            reply = await asyncio.wait_for(self.socket.recv(), TIMEOUT)
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
                    + f". The token file is {token_file()}; set REFLETS_TOKEN_FILE if MuseScore's plugin folder is elsewhere."
                )
            raise BridgeError(f"The bridge plugin reported {code}: {message}")
        return words[2:], lines[1:]
