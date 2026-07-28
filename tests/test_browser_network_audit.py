from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import websockets


class _FakeCdp:
    def __init__(
        self,
        *,
        reject_network: bool = False,
        wrong_target: bool = False,
        no_attach: bool = False,
        drop_after_navigation: bool = False,
    ) -> None:
        self.reject_network = reject_network
        self.wrong_target = wrong_target
        self.no_attach = no_attach
        self.drop_after_navigation = drop_after_navigation
        self.expected_url = "http://127.0.0.1:18766/"
        self.ready = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ws_server = None
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        assert self.ready.wait(5)
        assert self.loop is not None and self.ws_server is not None
        ws_port = self.ws_server.sockets[0].getsockname()[1]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # type: ignore[no-untyped-def]
                if self.path != "/json/version":
                    self.send_error(404)
                    return
                payload = json.dumps({
                    "webSocketDebuggerUrl": f"ws://127.0.0.1:{ws_port}/devtools/browser",
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):  # type: ignore[no-untyped-def]
                return

        self.http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()
        self.debugging_url = f"http://127.0.0.1:{self.http_server.server_port}"

    async def handler(self, websocket):  # type: ignore[no-untyped-def]
        async for raw in websocket:
            message = json.loads(raw)
            command_id = message["id"]
            method = message["method"]
            session_id = message.get("sessionId")
            if method == "Target.createTarget":
                if not self.no_attach:
                    attached_id = "wrong-target" if self.wrong_target else "main-target"
                    await websocket.send(json.dumps({
                        "method": "Target.attachedToTarget",
                        "params": {
                            "sessionId": "main-session",
                            "targetInfo": {"targetId": attached_id, "type": "page", "url": "about:blank"},
                        },
                    }))
                await websocket.send(json.dumps({"id": command_id, "result": {"targetId": "main-target"}}))
            elif method == "Network.enable" and self.reject_network:
                await websocket.send(json.dumps({"id": command_id, "error": {"code": -1}}))
            else:
                await websocket.send(json.dumps({"id": command_id, "result": {}}))
                if method == "Page.navigate":
                    await websocket.send(json.dumps({
                        "method": "Network.requestWillBeSent",
                        "sessionId": session_id,
                        "params": {"request": {"url": self.expected_url}},
                    }))
                    if self.drop_after_navigation:
                        await asyncio.sleep(0.1)
                        await websocket.close()

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.ws_server = self.loop.run_until_complete(self._start_server())
        self.ready.set()
        self.loop.run_forever()

    async def _start_server(self):  # type: ignore[no-untyped-def]
        return await websockets.serve(self.handler, "127.0.0.1", 0)

    def close(self) -> None:
        self.http_server.shutdown()
        assert self.loop is not None and self.ws_server is not None
        async def stop_server() -> None:
            self.ws_server.close()
            await self.ws_server.wait_closed()
            self.loop.stop()

        self.loop.call_soon_threadsafe(lambda: asyncio.create_task(stop_server()))
        self.thread.join(timeout=5)


def _run_auditor(
    tmp_path: Path,
    fake: _FakeCdp,
    timeout: str = "2",
    stop_delay_seconds: float = 0,
) -> subprocess.CompletedProcess[str]:
    root = Path(__file__).parents[1]
    audit = tmp_path / "browser.jsonl"
    stop = tmp_path / "stop"
    ready = tmp_path / "ready"
    process = subprocess.Popen(
        [
            sys.executable,
            str(root / "scripts" / "browser-network-audit.py"),
            "--debugging-url", fake.debugging_url,
            "--expected-url", fake.expected_url,
            "--audit", str(audit),
            "--stop-file", str(stop),
            "--ready-file", str(ready),
            "--ready-timeout-seconds", timeout,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and process.poll() is None and not ready.exists():
        time.sleep(0.05)
    if ready.exists():
        if stop_delay_seconds:
            time.sleep(stop_delay_seconds)
        stop.touch()
    returncode = process.wait(timeout=10)
    return subprocess.CompletedProcess(process.args, returncode, process.stdout.read(), process.stderr.read())


def test_browser_network_audit_uses_browser_target_and_records_navigation(tmp_path):
    fake = _FakeCdp()
    try:
        result = _run_auditor(tmp_path, fake)
        assert result.returncode == 0, result.stderr
        assert "18766" in (tmp_path / "browser.jsonl").read_text(encoding="utf-8")
    finally:
        fake.close()


def test_browser_network_audit_fails_closed_for_wrong_target_and_network_rejection(tmp_path):
    for kwargs in ({"wrong_target": True}, {"reject_network": True}):
        fake = _FakeCdp(**kwargs)
        try:
            result = _run_auditor(tmp_path / str(len(kwargs)), fake, timeout="0.5")
            assert result.returncode != 0
        finally:
            fake.close()


def test_browser_network_audit_fails_closed_on_ready_timeout(tmp_path):
    fake = _FakeCdp(no_attach=True)
    try:
        result = _run_auditor(tmp_path / "timeout", fake, timeout="0.2")
        assert result.returncode != 0
        assert not (tmp_path / "timeout" / "ready").exists()
    finally:
        fake.close()


def test_browser_network_audit_propagates_post_ready_disconnect(tmp_path):
    fake = _FakeCdp(drop_after_navigation=True)
    try:
        result = _run_auditor(tmp_path / "disconnect", fake, stop_delay_seconds=0.5)
        assert result.returncode != 0
    finally:
        fake.close()
