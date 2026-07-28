from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import TextIO
from urllib.request import urlopen

import websockets


class BrowserAudit:
    def __init__(self, websocket: websockets.ClientConnection, output: Path, stop_file: Path) -> None:
        self.websocket = websocket
        self.output = output
        self.stop_file = stop_file
        self.next_id = 1
        self.pending: dict[int, asyncio.Future[dict[str, object]]] = {}
        self.target_sessions: dict[str, str] = {}
        self.pending_targets: dict[str, tuple[str, object]] = {}
        self.owned_targets: set[str] = set()
        self.main_target_id: str | None = None
        self.main_session_id: str | None = None
        self.main_network_ready = asyncio.Event()
        self.reader_error: BaseException | None = None
        self.handle: TextIO | None = None
        self.network_ready_targets: set[str] = set()

    async def send(
        self,
        method: str,
        params: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> dict[str, object]:
        command_id = self.next_id
        self.next_id += 1
        future: asyncio.Future[dict[str, object]] = asyncio.get_running_loop().create_future()
        self.pending[command_id] = future
        message: dict[str, object] = {"id": command_id, "method": method}
        if params:
            message["params"] = params
        if session_id:
            message["sessionId"] = session_id
        await self.websocket.send(json.dumps(message))
        response = await future
        if "error" in response:
            raise RuntimeError(f"CDP command failed: {method}")
        return response

    async def reader(self) -> None:
        try:
            async for raw in self.websocket:
                message = json.loads(raw)
                command_id = message.get("id")
                if isinstance(command_id, int) and command_id in self.pending:
                    self.pending.pop(command_id).set_result(message)
                    continue
                if message.get("method") == "Target.attachedToTarget":
                    await self.attached(message["params"])
                elif message.get("method") == "Network.requestWillBeSent":
                    await self.record_request(message)
            if not self.stop_file.exists():
                self.reader_error = RuntimeError("CDP connection closed before audit stop")
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self.reader_error = exc
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(exc)

    async def attached(self, params: object) -> None:
        if not isinstance(params, dict):
            return
        session_id = params.get("sessionId")
        target_info = params.get("targetInfo")
        if not isinstance(session_id, str) or not isinstance(target_info, dict):
            return
        target_id = target_info.get("targetId")
        opener_id = target_info.get("openerId")
        if not isinstance(target_id, str):
            return
        if self.main_target_id is None:
            self.pending_targets[target_id] = (session_id, target_info)
            return
        owned = target_id == self.main_target_id or opener_id == self.main_target_id or opener_id in self.owned_targets
        if not owned:
            asyncio.create_task(self.send("Target.detachFromTarget", {"sessionId": session_id}))
            return
        self.pending_targets.pop(target_id, None)
        self.target_sessions[target_id] = session_id
        if target_id == self.main_target_id:
            self.main_session_id = session_id
        asyncio.create_task(self.enable_target(target_id, session_id))

    async def enable_target(self, target_id: str, session_id: str) -> None:
        try:
            await self.send("Network.enable", session_id=session_id)
            await self.send("Page.enable", session_id=session_id)
            await self.send("Runtime.runIfWaitingForDebugger", session_id=session_id)
            self.owned_targets.add(target_id)
            self.network_ready_targets.add(target_id)
            if target_id == self.main_target_id:
                self.main_network_ready.set()
        except RuntimeError as exc:
            self.reader_error = exc

    async def record_request(self, message: dict[str, object]) -> None:
        session_id = message.get("sessionId")
        if not isinstance(session_id, str) or session_id not in self.target_sessions.values():
            return
        target_id = next(
            (candidate for candidate, candidate_session in self.target_sessions.items() if candidate_session == session_id),
            None,
        )
        params = message.get("params")
        request = params.get("request") if isinstance(params, dict) else None
        method = request.get("method") if isinstance(request, dict) else None
        url = request.get("url") if isinstance(request, dict) else None
        if target_id and isinstance(method, str) and isinstance(url, str) and self.handle is not None:
            self.handle.write(json.dumps({
                "kind": "browser_request",
                "target_id": target_id,
                "session_id": session_id,
                "method": method,
                "url": url,
            }, ensure_ascii=False) + "\n")
            self.handle.flush()

    async def run(self, base_url: str, ready_file: Path, ready_timeout_seconds: float) -> None:
        reader_task = asyncio.create_task(self.reader())
        try:
            await self.send("Target.setDiscoverTargets", {"discover": True})
            await self.send("Target.setAutoAttach", {
                "autoAttach": True,
                "waitForDebuggerOnStart": True,
                "flatten": True,
            })
            created = await self.send("Target.createTarget", {"url": "about:blank"})
            result = created.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("targetId"), str):
                raise RuntimeError("CDP did not create the dedicated browser target")
            self.main_target_id = result["targetId"]
            pending_targets = list(self.pending_targets.items())
            self.pending_targets.clear()
            for target_id, (session_id, _target_info) in pending_targets:
                if target_id == self.main_target_id:
                    self.target_sessions[target_id] = session_id
                    self.main_session_id = session_id
                    asyncio.create_task(self.enable_target(target_id, session_id))
                else:
                    asyncio.create_task(self.send("Target.detachFromTarget", {"sessionId": session_id}))
            if self.main_target_id in self.network_ready_targets:
                self.main_session_id = self.target_sessions.get(self.main_target_id)
                self.owned_targets.add(self.main_target_id)
                self.main_network_ready.set()
            deadline = time.monotonic() + ready_timeout_seconds
            while not self.main_network_ready.is_set() and time.monotonic() < deadline:
                if self.reader_error is not None:
                    raise self.reader_error
                await asyncio.sleep(0.05)
            if not self.main_network_ready.is_set() or self.main_session_id is None:
                raise RuntimeError("dedicated browser target did not complete Network.enable")
            with self.output.open("w", encoding="utf-8") as handle:
                self.handle = handle
                await self.send("Page.navigate", {"url": base_url}, self.main_session_id)
                ready_file.touch()
                while not self.stop_file.exists():
                    if self.reader_error is not None:
                        raise self.reader_error
                    await asyncio.sleep(0.1)
                if self.reader_error is not None:
                    raise self.reader_error
        finally:
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)


def browser_websocket_url(debugging_url: str) -> str:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{debugging_url.rstrip('/')}/json/version", timeout=5) as response:
                version = json.load(response)
            websocket_url = version.get("webSocketDebuggerUrl")
            if isinstance(websocket_url, str) and websocket_url:
                return websocket_url
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError("browser-level CDP endpoint did not become available")


async def main_async(args: argparse.Namespace) -> None:
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.ready_file.parent.mkdir(parents=True, exist_ok=True)
    websocket_url = browser_websocket_url(args.debugging_url)
    async with websockets.connect(websocket_url, open_timeout=5) as websocket:
        audit = BrowserAudit(websocket, args.audit, args.stop_file)
        await audit.run(args.expected_url, args.ready_file, args.ready_timeout_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debugging-url", required=True)
    parser.add_argument("--expected-url", required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--stop-file", type=Path, required=True)
    parser.add_argument("--ready-file", type=Path, required=True)
    parser.add_argument("--ready-timeout-seconds", type=float, default=30)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
