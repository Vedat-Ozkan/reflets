import asyncio
import json
import sys
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError

from reflets import server
from reflets.score import parse_info


async def main() -> None:
    _, info_lines = await server.bridge.request("info")
    _, read_lines = await server.bridge.request("read 0 2147483647")
    numbers = [measure.number for measure in parse_info(info_lines).measures]
    windows = {}
    for bars in ["all"] + [f"{a}-{b}" for i, a in enumerate(numbers) for b in numbers[i:]]:
        try:
            windows[bars] = await server.read_score(bars)
        except ToolError as error:
            windows[bars] = f"Error: {error}"
    saved = {"info": info_lines, "read": read_lines, "division": int(server.bridge.hello["division"]), "windows": windows}
    Path(sys.argv[1]).write_text(json.dumps(saved))
    print(f"{parse_info(info_lines).title}: bars {numbers[0]}-{numbers[-1]}, {len(windows)} windows saved to {sys.argv[1]}")


asyncio.run(main())
