import asyncio
import os
import sys
import tempfile
from pathlib import Path

import websockets
from engine import draft

from reflets import server
from reflets.bridge import Bridge

failures = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + name + (f": {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(name)


async def silent(socket) -> None:
    async for _ in socket:
        pass


async def main() -> None:
    report = await server.doctor()
    check("a running bridge passes every line", "FAIL" not in report and "NOTE" not in report and "Score open" in report, report)

    token = os.environ.get("REFLETS_TOKEN_FILE")
    os.environ["REFLETS_TOKEN_FILE"] = "/nonexistent/reflets-token.txt"
    report = await server.doctor()
    check("a wrong plugin folder is named", "No plugin file at /nonexistent" in report and "REFLETS_TOKEN_FILE" in report, report)
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder) / "reflets-bridge.qml").write_text("    readonly property int proto: 20\n")
        os.environ["REFLETS_TOKEN_FILE"] = f"{folder}/reflets-token.txt"
        report = await server.doctor()
    check("a plugin file of another protocol is named", f"protocol 20; this server speaks {server.PROTO}" in report, report)
    if token:
        os.environ["REFLETS_TOKEN_FILE"] = token

    python = draft.ANALYSISGNN_PYTHON
    draft.ANALYSISGNN_PYTHON = "/nonexistent/python"
    report = await server.doctor()
    check("a missing model is a note, not a failure", "NOTE No AnalysisGNN model at /nonexistent/python" in report and "FAIL" not in report, report)
    draft.ANALYSISGNN_PYTHON = python

    os.environ["REFLETS_PORT"] = "8739"
    server.bridge = Bridge()
    report = await server.doctor()
    check("a closed port is named", "Nothing listens on ws://127.0.0.1:8739" in report, report)

    async with websockets.serve(silent, "127.0.0.1", 8739):
        server.bridge = Bridge()
        report = await server.doctor()
    check("another server on the port is named", "does not answer as the Reflets bridge" in report, report)
    sys.exit(1 if failures else 0)


asyncio.run(main())
