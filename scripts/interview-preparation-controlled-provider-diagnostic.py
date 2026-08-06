from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

from offerpilot.api import create_app
from offerpilot.config import load_config, resolve_data_dir, save_config
from offerpilot.smoke import _run_real_ai_interview_preparation_smoke, _running_server


CONTROLLED_PROPOSAL = {
    "preparation_directions": [
        {
            "id": "controlled-direction",
            "text": "Review the cited resume experience.",
            "evidence_refs": [
                {
                    "source": "resume",
                    "path": "/raw_text",
                    "excerpt": "Built reliable API services; input_snapshot is a literal term here.",
                }
            ],
        }
    ],
    "story_prompts": [],
    "review_points": [],
    "interviewer_questions": [],
    "items_to_clarify": [],
}


class _ControlledProviderHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    calls: list[dict[str, object]] = []

    def do_POST(self) -> None:  # type: ignore[no-untyped-def]
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        request_id = f"controlled-interview-preparation-{len(self.calls) + 1}"
        self.calls.append(
            {
                "request_body_bytes": content_length,
                "response_status": 200,
                "request_id_hash": hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:12],
            }
        )
        payload = {
            "id": request_id,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(CONTROLLED_PROPOSAL, ensure_ascii=False),
                    }
                }
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.send_header("X-Request-ID", request_id)
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_args: object) -> None:
        return


def _controlled_config(source_data: Path, provider_url: str):
    config = load_config(source_data).model_copy(deep=True)
    active = config.active_provider()
    controlled = active.model_copy(
        update={
            "provider": "openai_compatible",
            "api_key": "controlled-diagnostic-key",
            "base_url": provider_url,
            "model": "controlled-interview-preparation",
            "enabled": True,
            "supports_json_schema": False,
        }
    )
    config.providers = [controlled]
    config.active_provider_id = controlled.id
    config.fallback_provider_ids = []
    config.base_url = controlled.base_url
    config.api_key = controlled.api_key
    config.model = controlled.model
    return config


def run_diagnostic(source_data: Path, static_dir: Path | None) -> dict[str, Any]:
    _ControlledProviderHandler.calls = []
    provider = ThreadingHTTPServer(("127.0.0.1", 0), _ControlledProviderHandler)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    started = time.perf_counter()
    previous_no_proxy = os.environ.get("NO_PROXY")
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    try:
        with tempfile.TemporaryDirectory(prefix="offerpilot-interview-preparation-controlled-") as temp_dir:
            data_dir = Path(temp_dir)
            provider_url = f"http://127.0.0.1:{provider.server_port}/v1"
            save_config(data_dir, _controlled_config(source_data, provider_url))
            app = create_app(data_dir=data_dir, static_dir=static_dir)
            with _running_server(app) as base_url:
                with httpx.Client(base_url=base_url, timeout=60.0) as client:
                    created = client.post(
                        "/api/applications",
                        json={
                            "company_name": "controlled diagnostic",
                            "position_name": "interview preparation",
                            "status": "applied",
                        },
                    )
                    created.raise_for_status()
                    application_id = int(created.json()["id"])
                    resume_ids: list[int] = []
                    _run_real_ai_interview_preparation_smoke(
                        client, [], application_id, resume_ids
                    )
                    client.delete(f"/api/applications/{application_id}")
                    for resume_id in resume_ids:
                        client.delete(f"/api/resumes/{resume_id}")
    finally:
        if previous_no_proxy is None:
            os.environ.pop("NO_PROXY", None)
        else:
            os.environ["NO_PROXY"] = previous_no_proxy
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=5)
    return {
        "status": "passed",
        "stage": "interview_preparation",
        "provider": "controlled-local-openai-compatible",
        "endpoint": "http://127.0.0.1:<ephemeral>/v1",
        "model": "controlled-interview-preparation",
        "provider_calls": len(_ControlledProviderHandler.calls),
        "responses": _ControlledProviderHandler.calls,
        "elapsed_ms": max(0, int((time.perf_counter() - started) * 1000)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a redacted interview-preparation provider-boundary diagnostic.")
    parser.add_argument("--source-data", type=Path, default=resolve_data_dir())
    parser.add_argument("--static-dir", type=Path, default=Path("web/dist"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_diagnostic(args.source_data, args.static_dir)
    encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="ascii")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
