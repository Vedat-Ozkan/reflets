import asyncio
import os
import sys
import tempfile
from pathlib import Path

import websockets
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
    report = await server.score_info()
    check("score_info on a running bridge shows no checklist", "connected" in report and "PASS" not in report, report)
    report = await server.diagnose()
    check("a running bridge passes every line", "FAIL" not in report and "NOTE" not in report and "Score open" in report, report)

    token = os.environ.get("REFLETS_TOKEN_FILE")
    os.environ["REFLETS_TOKEN_FILE"] = "/nonexistent/reflets-token.txt"
    report = await server.diagnose()
    check("a wrong plugin folder is named", "No plugin file at /nonexistent" in report and "REFLETS_TOKEN_FILE" in report, report)
    with tempfile.TemporaryDirectory() as folder:
        (Path(folder) / "reflets-bridge.qml").write_text("    readonly property int proto: 20\n")
        os.environ["REFLETS_TOKEN_FILE"] = f"{folder}/reflets-token.txt"
        report = await server.diagnose()
    check("a plugin file of another protocol is named", f"protocol 20; this server speaks {server.PROTO}" in report, report)
    if token:
        os.environ["REFLETS_TOKEN_FILE"] = token
    else:
        del os.environ["REFLETS_TOKEN_FILE"]

    named = {name: os.environ.pop(name, None) for name in ("ANALYSISGNN_PYTHON", "ANALYSISGNN_CHECKPOINT")}
    report = await server.diagnose()
    check("an unset model is a note naming the variables and the setup", "NOTE No AnalysisGNN model (ANALYSISGNN_PYTHON and "
          "ANALYSISGNN_CHECKPOINT are not set)" in report and "Draft model" in report and "site-packages" not in report and "FAIL" not in report, report)
    os.environ["ANALYSISGNN_PYTHON"], os.environ["ANALYSISGNN_CHECKPOINT"] = "/nonexistent/python", named["ANALYSISGNN_CHECKPOINT"] or "/nonexistent/model.ckpt"
    report = await server.diagnose()
    check("a missing model file is named", "NOTE No AnalysisGNN model (nothing at /nonexistent/python" in report and "FAIL" not in report, report)
    for name, value in named.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    os.environ["REFLETS_PORT"] = "8739"
    server.bridge = Bridge()
    report = await server.score_info()
    check("score_info names a closed port in its checklist", "Nothing listens on ws://127.0.0.1:8739" in report and "PASS Token file" in report, report)

    async with websockets.serve(silent, "127.0.0.1", 8739):
        server.bridge = Bridge()
        report = await server.diagnose()
    check("another server on the port is named", "does not answer as the Reflets bridge" in report, report)
    sys.exit(1 if failures else 0)


asyncio.run(main())
