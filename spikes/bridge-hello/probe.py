"""Throwaway spike client for reflets-bridge-hello.qml.

    python3 probe.py                       # hello + 20 pings
    python3 probe.py "read 1" multi "read 1" undo "read 1"
                                           # hello, then each argument as one request, in order
"""

import asyncio
import statistics
import sys
import time

import websockets

URL = "ws://127.0.0.1:8731"
TIMEOUT = 5


async def request(ws, rid, line):
    await ws.send(f"{rid} {line}")
    reply = await asyncio.wait_for(ws.recv(), TIMEOUT)
    # The plugin echoes the id; anything else is a stale reply (spec 3.2).
    if reply.split(" ", 1)[0] != str(rid):
        raise RuntimeError(f"id mismatch: sent {rid}, got {reply!r}")
    return reply


async def main(lines):
    async with websockets.connect(URL, open_timeout=TIMEOUT) as ws:
        print(await request(ws, 1, "hello proto=0 client=probe"))
        for rid, line in enumerate(lines, start=2):
            print(f"> {line}")
            print(await request(ws, rid, line))
        if lines:
            return
        rtts = []
        for rid in range(2, 22):
            t = time.perf_counter()
            reply = await request(ws, rid, "ping")
            rtts.append((time.perf_counter() - t) * 1000)
            if reply != f"{rid} pong":
                raise RuntimeError(f"bad pong: {reply!r}")
        print(f"20 pongs, rtt ms min {min(rtts):.2f} median {statistics.median(rtts):.2f} max {max(rtts):.2f}")


try:
    asyncio.run(main(sys.argv[1:]))
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
