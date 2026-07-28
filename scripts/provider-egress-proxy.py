from __future__ import annotations

import argparse
import json
import selectors
import socket
import socketserver
from pathlib import Path


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        request = self._read_headers()
        if not request:
            return
        first_line = request.split(b"\r\n", 1)[0].decode("ascii", "replace")
        method, target, _ = first_line.split(" ", 2)
        if method.upper() != "CONNECT" or ":" not in target:
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, port_text = target.rsplit(":", 1)
        port = int(port_text)
        expected_host = self.server.expected_host  # type: ignore[attr-defined]
        expected_port = self.server.expected_port  # type: ignore[attr-defined]
        expected_scheme = self.server.expected_scheme  # type: ignore[attr-defined]
        audit_path = self.server.audit_path  # type: ignore[attr-defined]
        if host != expected_host or port != expected_port:
            _append_audit(audit_path, expected_scheme, host, port, "rejected")
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            return
        upstream = socket.create_connection((host, port), timeout=20)
        try:
            _append_audit(audit_path, expected_scheme, host, port, "connected")
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _tunnel(self.request, upstream)
        finally:
            upstream.close()

    def _read_headers(self) -> bytes:
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 64 * 1024:
            chunk = self.request.recv(4096)
            if not chunk:
                return b""
            data += chunk
        return data


def _append_audit(path: Path, scheme: str, host: str, port: int, status: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "kind": "provider_proxy_connect",
            "scheme": scheme,
            "host": host,
            "port": port,
            "status": status,
        }) + "\n")


def _tunnel(client: socket.socket, upstream: socket.socket) -> None:
    selector = selectors.DefaultSelector()
    selector.register(client, selectors.EVENT_READ, upstream)
    selector.register(upstream, selectors.EVENT_READ, client)
    try:
        while True:
            events = selector.select(timeout=30)
            if not events:
                return
            for key, _ in events:
                data = key.fileobj.recv(64 * 1024)
                if not data:
                    return
                key.data.sendall(data)
    finally:
        selector.close()


class ThreadingProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[ProxyHandler], args: argparse.Namespace):
        super().__init__(address, handler)
        self.audit_path = Path(args.audit)
        self.expected_scheme = args.expected_scheme
        self.expected_host = args.expected_host
        self.expected_port = args.expected_port


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--expected-scheme", required=True)
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--expected-port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingProxy(("127.0.0.1", args.port), ProxyHandler, args)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
