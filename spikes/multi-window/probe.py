import asyncio

import websockets

PORTS = range(8751, 8756)


async def status(port: int) -> str:
    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}", open_timeout=2) as ws:
            await ws.send("1 status")
            return await asyncio.wait_for(ws.recv(), 2)
    except (OSError, asyncio.TimeoutError) as error:
        return f"nothing ({type(error).__name__})"


async def main() -> None:
    for port in PORTS:
        print(port, await status(port))


asyncio.run(main())
