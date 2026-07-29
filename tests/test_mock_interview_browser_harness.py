import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from offerpilot.ai.mock_interview import MockInterviewContractError, SAFE_EMPTY_FEEDBACK, validate_feedback
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import (
    Application,
    ApplicationEvent,
    MockInterviewAttempt,
    MockInterviewFeedbackProposal,
    MockInterviewReviewDraft,
    MockInterviewTurn,
    Resume,
)
from offerpilot.smoke import _cleanup_real_ai_smoke_records, _assert_real_ai_smoke_data_clean


def test_mock_interview_smoke_requires_four_array_safe_empty_shape():
    assert set(SAFE_EMPTY_FEEDBACK) == {
        "schema_version", "proposal_status", "strengths", "practice_points",
        "follow_up_questions", "next_practice_steps",
    }
    assert all(SAFE_EMPTY_FEEDBACK[field] == [] for field in (
        "strengths", "practice_points", "follow_up_questions", "next_practice_steps"
    ))


def test_browser_harness_requires_real_two_turn_draft_and_browser_network_evidence():
    script = (Path(__file__).parents[1] / "scripts" / "mock-interview-real-ai-browser-harness.ps1").read_text(encoding="utf-8")
    assert "Count -ge 2" in script
    assert "review_draft" in script
    assert "sec_fetch_mode" in script
    assert "provider_proxy_connect" in script or "provider-egress-proxy.py" in script


def test_browser_harness_rejects_non_https_provider_before_starting_proxy():
    script = (Path(__file__).parents[1] / "scripts" / "mock-interview-real-ai-browser-harness.ps1").read_text(encoding="utf-8")
    assert "requires an HTTPS provider endpoint" in script


def test_browser_harness_requires_cdp_network_audit():
    script = (Path(__file__).parents[1] / "scripts" / "mock-interview-real-ai-browser-harness.ps1").read_text(encoding="utf-8")
    auditor = (Path(__file__).parents[1] / "scripts" / "browser-network-audit.py").read_text(encoding="utf-8")
    assert "MOCK_INTERVIEW_CDP_URL" in script
    assert "Network.requestWillBeSent" in auditor
    assert "CDP browser request audit is missing" in script


def test_browser_harness_binds_cdp_to_local_target_and_ready_handshake():
    script = (Path(__file__).parents[1] / "scripts" / "mock-interview-real-ai-browser-harness.ps1").read_text(encoding="utf-8")
    auditor = (Path(__file__).parents[1] / "scripts" / "browser-network-audit.py").read_text(encoding="utf-8")
    assert "--expected-url" in script
    assert "--ready-file" in script
    assert "--expected-url" in auditor
    assert "--ready-file" in auditor
    assert "ExitCode" in script
    assert "/json/version" in auditor
    assert "Target.createTarget" in auditor
    assert "Target.setAutoAttach" in auditor
    assert "Target.setDiscoverTargets" in auditor
    assert "Page.navigate" in auditor
    assert "Find-FlowRequestIndex" in script
    assert "review-drafts" in script
    assert "turns/[0-9]+/question" in script
    assert "answerPathMatch" in script
    assert "target_id" in script
    assert "session_id" in script


def test_mock_interview_smoke_rejects_untraceable_turn_evidence():
    proposal = {
        **SAFE_EMPTY_FEEDBACK,
        "proposal_status": "normal",
        "strengths": [{
            "id": "s1", "text": "亮点",
            "evidence_refs": [{"source": "turn", "path": "/turns/001/answer", "excerpt": "伪造"}],
        }],
    }
    with pytest.raises(MockInterviewContractError, match="excerpt_mismatch"):
        validate_feedback(proposal, {"jd": {"text": "JD"}, "resume": {"content_json": {}}}, [
            {"turn_no": 1, "answer": "真实回答"},
        ])


def test_mock_interview_smoke_rejects_noncanonical_turn_evidence_path():
    proposal = {
        **SAFE_EMPTY_FEEDBACK,
        "proposal_status": "normal",
        "strengths": [{
            "id": "s1", "text": "亮点",
            "evidence_refs": [{"source": "turn", "path": "/turns/1/answer", "excerpt": "真实回答"}],
        }],
    }
    with pytest.raises(MockInterviewContractError, match="unknown_evidence_ref"):
        validate_feedback(proposal, {"jd": {"text": "JD"}, "resume": {"content_json": {}}}, [
            {"turn_no": 1, "answer": "真实回答"},
        ])


def test_mock_interview_cleanup_deletes_draft_children_before_attempt(tmp_path):
    data_dir = tmp_path / "data"
    factory = session_factory_for_data_dir(data_dir)
    with factory() as session:
        application = Application(company_name="Smoke", position_name="QA")
        session.add(application)
        session.flush()
        event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime(2026, 7, 28, 10, tzinfo=timezone.utc),
        )
        resume = Resume(title="Smoke", content_json=json.dumps({}))
        session.add_all([event, resume])
        session.flush()
        attempt = MockInterviewAttempt(
            application_id=application.id, event_id=event.id, resume_id=resume.id,
            idempotency_key="attempt", input_snapshot_json="{}", source_fingerprint="source",
            attempt_status="feedback_ready", generation_revision=1, provider_call_token="token",
            transcript_fingerprint="transcript",
        )
        session.add(attempt)
        session.flush()
        turn = MockInterviewTurn(
            attempt_id=attempt.id, turn_no=1, question_idempotency_key="question",
            turn_status="answered", answer_text="answer",
        )
        proposal = MockInterviewFeedbackProposal(
            attempt_id=attempt.id, idempotency_key="feedback", input_snapshot_json="{}",
            source_fingerprint="source", transcript_fingerprint="transcript",
            proposal_json=json.dumps(SAFE_EMPTY_FEEDBACK), proposal_hash="hash",
            proposal_status="safe_empty",
        )
        session.add_all([turn, proposal])
        session.flush()
        session.add(MockInterviewReviewDraft(
            attempt_id=attempt.id, proposal_id=proposal.id, confirmation_idempotency_key="confirm",
            application_id=application.id, event_id=event.id, selected_blocks_json="[]",
            content_hash="content", source_fingerprint="source",
        ))
        session.commit()
        application_id = application.id
        resume_id = resume.id
    bind = factory.kw.get("bind")
    if bind is not None:
        bind.dispose()

    _cleanup_real_ai_smoke_records(data_dir, application_id, [resume_id])
    _assert_real_ai_smoke_data_clean(data_dir)
    factory = session_factory_for_data_dir(data_dir)
    with factory() as session:
        assert session.scalar(select(MockInterviewAttempt.id)) is None
