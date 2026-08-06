import pytest
from runpy import run_path
from pathlib import Path

_SCRIPT = run_path(
    str(
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "interview-preparation-controlled-provider-diagnostic.py"
    )
)
_validate_redacted_request_metadata = _SCRIPT["_validate_redacted_request_metadata"]


def test_controlled_diagnostic_rejects_missing_request_metadata():
    with pytest.raises(RuntimeError, match="request metadata"):
        _validate_redacted_request_metadata([], expected_calls=1)


def test_controlled_diagnostic_accepts_complete_request_metadata():
    _validate_redacted_request_metadata(
        [
            {
                "kind": "provider_request_metadata",
                "provider_id": "default",
                "provider_type": "openai_compatible",
                "endpoint": {"scheme": "http", "host": "127.0.0.1", "port": 1234},
                "model": "controlled",
                "litellm_model": "openai/controlled",
                "message_count": 2,
                "message_bytes": 10,
                "request_body_bytes": 20,
                "input_fingerprint_sha256": "a" * 64,
                "schema_fingerprint_sha256": "b" * 64,
                "response_mode": "text_json",
                "max_tokens": None,
                "timeout_seconds": None,
            }
        ],
        expected_calls=1,
    )
