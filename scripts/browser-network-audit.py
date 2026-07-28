from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from urllib.request import urlopen

import websockets


def page_websocket_url(debugging_url: str) -> str:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{debugging_url.rstrip('/')}/json/list", timeout=5) as response:
                targets = json.load(response)
            for target in targets:
                if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
                    return str(target["webSocketDebuggerUrl"])
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("no debuggable browser page became available")


async def record(websocket_url: str, output: Path, stop_file: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(websocket_url, open_timeout=5) as websocket:
        await websocket.send(json.dumps({"id": 1, "method": "Network.enable"}))
        with output.open("w", encoding="utf-8") as handle:
            while not stop_file.exists():
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=0.5)
                except TimeoutError:
                    continue
                message = json.loads(raw)
                if message.get("method") != "Network.requestWillBeSent":
                    continue
                request = message.get("params", {}).get("request", {})
                url = request.get("url")
                if isinstance(url, str):
                    handle.write(json.dumps({"kind": "browser_request", "url": url}, ensure_ascii=False) + "\n")
                    handle.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debugging-url", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    args = parser.parse_args()
    websocket_url = page_websocket_url(args.debugging_url)
    asyncio.run(record(websocket_url, args.audit, args.stop_file))


if __name__ == "__main__":
    main()
