"""Download the takes testers sent with hum_test into out/hum-tests/<tester code>/, then delete them from the bucket.

    REFLETS_TAKES_ADMIN=<admin token> uv run python -m eval.hum_pull

Score them with eval.hum_takes --folder out/hum-tests (every tester) or out/hum-tests/<code>.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

from reflets.server import TAKES_URL

FOLDER = Path(__file__).parent.parent / "out" / "hum-tests"


def call(method: str, path: str) -> bytes:
    url = os.environ.get("REFLETS_TAKES_URL", TAKES_URL)
    request = Request(f"{url}/takes{path}", method=method, headers={"Authorization": f"Bearer {os.environ['REFLETS_TAKES_ADMIN']}"})
    with urlopen(request, timeout=60) as response:
        return response.read()


def main() -> None:
    keys = json.loads(call("GET", ""))
    for key in keys:
        target = FOLDER / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(call("GET", f"/{key}"))
        call("DELETE", f"/{key}")
    print(f"{len(keys)} files into {FOLDER}")


if __name__ == "__main__":
    main()
