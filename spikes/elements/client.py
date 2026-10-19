"""Send a JavaScript snippet to the spike plugin and print the reply.

    uv run python spikes/elements/client.py FILE.js | -e 'return curScore.title'
"""

import asyncio
import json
import sys
from pathlib import Path

import websockets

TOKEN = Path("/mnt/c/Users/Vedat/Documents/MuseScore4/Plugins/reflets-spike/reflets-spike-token.txt")


async def send(code: str) -> str:
    async with websockets.connect("ws://127.0.0.1:8732", max_size=None, open_timeout=10) as ws:
        await ws.send(f"1 hello token={TOKEN.read_text().strip()}")
        hello = await asyncio.wait_for(ws.recv(), 10)
        if " ok" not in hello:
            return hello
        await ws.send("2 js\n" + code)
        return await asyncio.wait_for(ws.recv(), 60)


if __name__ == "__main__":
    code = sys.argv[2] if sys.argv[1] == "-e" else Path(sys.argv[1]).read_text()
    reply = asyncio.run(send(code))
    head, _, rest = reply.partition(" ok ")
    print(json.dumps(json.loads(rest), indent=1) if rest else reply)
