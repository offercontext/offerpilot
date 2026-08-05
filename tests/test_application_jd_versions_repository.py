import base64
import hashlib
import json

import pytest

from offerpilot.db import init_database
from offerpilot.repositories.application_jd_versions import (
    ApplicationJDService,
    JDVersionConflictError,
    JDVersionValidationError,
)
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository


def _service(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    application = ApplicationsRepository(session_factory).create(
        ApplicationCreate(company_name="星云数据", position_name="后端工程师")
    )
    return ApplicationJDService(session_factory), application.id


def _valid(service, application_id, **overrides):
    values = {
        "application_id": application_id,
        "jd_text": "后端工程师\n负责 API 设计 🧭",
        "source_url": None,
        "source_kind": "ui",
        "expected_current_version_id": None,
        "idempotency_key": "jd-key-000000001",
    }
    values.update(overrides)
    return service.create_version(**values)


def test_rejects_invalid_jd_url_and_idempotency_inputs_without_inserting(tmp_path):
    service, application_id = _service(tmp_path)

    invalid_values = [None, 1, "", "   ", "x" * 60_001]
    for value in invalid_values:
        with pytest.raises(JDVersionValidationError):
            _valid(service, application_id, jd_text=value)

    invalid_urls = [1, object(), "relative/path", "javascript:alert(1)", "data:text/plain,x", "file:///tmp/a", "https://"]
    for url in invalid_urls:
        with pytest.raises(JDVersionValidationError):
            _valid(service, application_id, source_url=url)

    invalid_keys = ["short", "bad key with spaces", "中文幂等键", "x" * 129]
    for key in invalid_keys:
        with pytest.raises(JDVersionValidationError):
            _valid(service, application_id, idempotency_key=key)

    assert service.list_versions(application_id, 0, 50) == []


def test_expected_current_version_requires_strict_positive_integer_or_none(tmp_path):
    service, application_id = _service(tmp_path)
    valid = {
        "application_id": application_id,
        "jd_text": "后端工程师",
        "source_url": None,
        "source_kind": "ui",
        "idempotency_key": "jd-key-000000002",
    }
    for value in (True, False, "1", 0, -1):
        with pytest.raises(JDVersionValidationError):
            service.create_version(**valid, expected_current_version_id=value)

    result = service.create_version(**valid, expected_current_version_id=None)
    assert result.version.version_number == 1


def test_fingerprint_preserves_raw_jd_bytes_and_normalizes_url(tmp_path):
    service, application_id = _service(tmp_path)
    text = "  中文\n😀  "
    result = _valid(service, application_id, jd_text=text, source_url="  https://example.invalid/job  ")
    expected_payload = {
        "jd_text_utf8_b64": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "source_url": "https://example.invalid/job",
        "source_kind": "ui",
    }
    expected_request_hash = hashlib.sha256(
        json.dumps(expected_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert result.version.content_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert result.version.request_fingerprint_sha256 == expected_request_hash
    assert result.version.source_url == "https://example.invalid/job"

    whitespace = _valid(
        service,
        application_id,
        jd_text="different",
        source_url="   ",
        idempotency_key="jd-key-000000003",
        expected_current_version_id=result.version.id,
    )
    assert whitespace.version.source_url is None


def test_replay_precedes_cas_and_conflicts_do_not_mutate_original(tmp_path):
    service, application_id = _service(tmp_path)
    first = _valid(service, application_id)
    replay = _valid(service, application_id, expected_current_version_id=999)
    assert replay.replayed is True
    assert replay.version.id == first.version.id

    with pytest.raises(JDVersionConflictError) as error:
        _valid(service, application_id, jd_text="changed")
    assert error.value.code == "application_jd_idempotency_conflict"
    assert len(service.list_versions(application_id, 0, 50)) == 1

    second = _valid(
        service,
        application_id,
        jd_text="第二版",
        idempotency_key="jd-key-000000004",
        expected_current_version_id=first.version.id,
    )
    assert second.version.version_number == 2
    assert _valid(service, application_id, expected_current_version_id=None).version.id == first.version.id


def test_current_version_and_freeze_are_explicit_and_preview_is_stable(tmp_path):
    service, application_id = _service(tmp_path)
    text = "a" * 239 + "\n😀"
    result = _valid(service, application_id, jd_text=text, idempotency_key="jd-key-000000005")
    current = service.get_current(application_id)
    assert current is not None
    assert current.id == result.version.id
    frozen = service.freeze(current)
    assert frozen.jd_version_id == current.id
    assert frozen.jd_text == text
    assert service.list_versions(application_id, 0, 50)[0].preview == text[:240] + "…"

    with pytest.raises(JDVersionConflictError):
        service.require_current_version(application_id, 0)
    with pytest.raises(JDVersionConflictError):
        service.require_current_version(application_id, current.id + 1)
