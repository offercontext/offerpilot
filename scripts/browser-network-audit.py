from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlparse

import websockets


def page_websocket_url(debugging_url: str, expected_url: str) -> str:
    expected = urlparse(expected_url)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{debugging_url.rstrip('/')}/json/list", timeout=5) as response:
                targets = json.load(response)
            for target in targets:
                target_url = urlparse(str(target.get("url", "")))
                if (
                    target.get("type") == "page"
                    and target.get("webSocketDebuggerUrl")
                    and target_url.scheme == expected.scheme
                    and target_url.netloc == expected.netloc
                    and target_url.path.rstrip("/") == expected.path.rstrip("/")
                ):
                    return str(target["webSocketDebuggerUrl"])
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("no debuggable browser page became available")


async def record(websocket_url: str, output: Path, stop_file: Path, ready_file: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    async with websockets.connect(websocket_url, open_timeout=5) as websocket:
        await websocket.send(json.dumps({"id": 1, "method": "Network.enable"}))
        while True:
            message = json.loads(await websocket.recv())
            if message.get("id") == 1 and "error" not in message:
                ready_file.touch()
                break
            if message.get("id") == 1:
                raise RuntimeError("browser rejected the Network.enable CDP command")
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
    parser.add_argument("--expected-url", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()
    websocket_url = page_websocket_url(args.debugging_url, args.expected_url)
    asyncio.run(record(websocket_url, args.audit, args.stop_file, args.ready_file))


if __name__ == "__main__":
    main()
