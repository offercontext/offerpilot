from __future__ import annotations

from datetime import datetime, timezone

import pytest

from offerpilot.db import init_database
from offerpilot.models import Application, ApplicationEvent, InterviewNote, InterviewReviewProposal
from offerpilot.repositories.adaptive_interview_practice import (
    AdaptivePracticeConflict,
    AdaptivePracticeNotFound,
    AdaptivePracticeRepository,
)
from offerpilot.repositories.json_contract import canonical_json, sha256_text


def _setup(tmp_path):
    session_factory = init_database(tmp_path / "data.db")
    with session_factory() as session:
        application = Application(company_name="云栖智能", position_name="后端工程师", source="web")
        session.add(application)
        session.flush()
        event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime(2026, 8, 12, 10, tzinfo=timezone.utc),
            duration_minutes=60,
            status="done",
        )
        session.add(event)
        session.flush()
        note = InterviewNote(
            application_id=application.id,
            application_event_id=event.id,
            company="云栖智能",
            position="后端工程师",
            questions="请说明一次线上延迟排查。",
            self_reflection="回答时先讲了过程，没有先给结论。",
            difficulty_points="被追问影响范围时卡住了。",
            mood="有些紧张",
        )
        session.add(note)
        session.flush()
        snapshot = {
            "note": {
                "questions": note.questions,
                "self_reflection": note.self_reflection,
                "difficulty_points": note.difficulty_points,
                "mood": note.mood,
            },
            "event": {"id": event.id},
        }
        proposal_payload = {
            "summary": {"text": "复盘包含可练习问题。", "evidence_refs": []},
            "observations": [],
            "clarifications": [],
            "practice_focuses": [
                {
                    "id": "focus-difficulty",
                    "text": "拆解影响范围追问。",
                    "evidence_refs": [
                        {
                            "source": "interview_note",
                            "path": "/difficulty_points",
                            "excerpt": note.difficulty_points,
                        }
                    ],
                },
                {
                    "id": "focus-reflection",
                    "text": "练习先结论后事实。",
                    "evidence_refs": [
                        {
                            "source": "interview_note",
                            "path": "/self_reflection",
                            "excerpt": note.self_reflection,
                        }
                    ],
                },
            ],
            "next_questions": [],
        }
        proposal = InterviewReviewProposal(
            note_id=note.id,
            application_event_id=event.id,
            idempotency_key="review-1",
            input_snapshot_json=canonical_json(snapshot),
            source_fingerprint=sha256_text(canonical_json(snapshot)),
            proposal_json=canonical_json(proposal_payload),
            proposal_hash=sha256_text(canonical_json(proposal_payload)),
        )
        session.add(proposal)
        session.commit()
        return session_factory, application.id, event.id, note.id, proposal.id


def test_recommendations_are_deterministic_and_start_is_idempotent(tmp_path) -> None:
    session_factory, application_id, event_id, note_id, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)

    recommendations = repository.list_recommendations()
    assert [item["focus_id"] for item in recommendations] == [
        "focus-difficulty",
        "focus-reflection",
    ]
    assert recommendations[0]["drill_kind"] == "difficulty_breakdown"
    assert recommendations[0]["source_excerpt"] == "被追问影响范围时卡住了。"

    first, created = repository.start(
        proposal_id=proposal_id,
        focus_id="focus-difficulty",
        expected_source_fingerprint=recommendations[0]["source_fingerprint"],
        idempotency_key="practice-start-1",
    )
    replay, replay_created = repository.start(
        proposal_id=proposal_id,
        focus_id="focus-difficulty",
        expected_source_fingerprint=recommendations[0]["source_fingerprint"],
        idempotency_key="practice-start-1",
    )

    assert created is True
    assert replay_created is False
    assert first["id"] == replay["id"]
    assert first["application_id"] == application_id
    assert first["application_event_id"] == event_id
    assert first["interview_note_id"] == note_id
    assert repository.list_recommendations() == [recommendations[1]]


def test_start_rejects_changed_source_and_changed_idempotent_input(tmp_path) -> None:
    session_factory, _, _, note_id, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)
    recommendations = repository.list_recommendations()
    recommendation = recommendations[0]
    reflection = recommendations[1]
    repository.start(
        proposal_id=proposal_id,
        focus_id=recommendation["focus_id"],
        expected_source_fingerprint=recommendation["source_fingerprint"],
        idempotency_key="practice-start-1",
    )

    with pytest.raises(AdaptivePracticeConflict, match="idempotency"):
        repository.start(
            proposal_id=proposal_id,
            focus_id="focus-reflection",
            expected_source_fingerprint=recommendation["source_fingerprint"],
            idempotency_key="practice-start-1",
        )

    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.self_reflection = "内容已经变化"
        session.commit()
    with pytest.raises(AdaptivePracticeConflict, match="source"):
        repository.start(
            proposal_id=proposal_id,
            focus_id=recommendation["focus_id"],
            expected_source_fingerprint=reflection["source_fingerprint"] + "-stale",
            idempotency_key="practice-start-2",
        )


def test_complete_uses_revision_cas_and_preserves_frozen_history(tmp_path) -> None:
    session_factory, _, _, note_id, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)
    recommendation = repository.list_recommendations()[0]
    plan, _ = repository.start(
        proposal_id=proposal_id,
        focus_id=recommendation["focus_id"],
        expected_source_fingerprint=recommendation["source_fingerprint"],
        idempotency_key="practice-start-1",
    )

    completed, created = repository.complete(
        plan_id=plan["id"],
        expected_revision=1,
        response_text="先明确影响范围，再说明定位路径，最后给出恢复结果。",
        reflection_text="下一次先给结论。",
        self_assessment="clearer",
        idempotency_key="practice-complete-1",
    )
    replay, replay_created = repository.complete(
        plan_id=plan["id"],
        expected_revision=1,
        response_text="先明确影响范围，再说明定位路径，最后给出恢复结果。",
        reflection_text="下一次先给结论。",
        self_assessment="clearer",
        idempotency_key="practice-complete-1",
    )

    assert created is True
    assert replay_created is False
    assert completed["status"] == "completed"
    assert completed["revision"] == 2
    assert replay["id"] == completed["id"]
    assert completed["source_status"] == "current"

    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.difficulty_points = "来源已经变化"
        session.commit()
    history = repository.list_plans()
    assert history[0]["source_status"] == "changed"
    assert history[0]["source_excerpt"] == "被追问影响范围时卡住了。"

    with pytest.raises(AdaptivePracticeConflict, match="idempotency"):
        repository.complete(
            plan_id=plan["id"],
            expected_revision=1,
            response_text="改变后的回答",
            reflection_text="下一次先给结论。",
            self_assessment="clearer",
            idempotency_key="practice-complete-1",
        )


def test_deleted_application_hides_recommendations_and_plans(tmp_path) -> None:
    session_factory, application_id, _, _, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)
    recommendation = repository.list_recommendations()[0]
    plan, _ = repository.start(
        proposal_id=proposal_id,
        focus_id=recommendation["focus_id"],
        expected_source_fingerprint=recommendation["source_fingerprint"],
        idempotency_key="practice-start-1",
    )
    with session_factory() as session:
        application = session.get(Application, application_id)
        assert application is not None
        application.deleted_at = datetime.now(timezone.utc)
        session.commit()

    assert repository.list_recommendations() == []
    assert repository.list_plans() == []
    with pytest.raises(AdaptivePracticeNotFound):
        repository.get(plan["id"])
    with pytest.raises(AdaptivePracticeNotFound):
        repository.start(
            proposal_id=proposal_id,
            focus_id=recommendation["focus_id"],
            expected_source_fingerprint=recommendation["source_fingerprint"],
            idempotency_key="practice-start-1",
        )


def test_note_or_event_deletion_hides_frozen_plan(tmp_path) -> None:
    session_factory, _, event_id, note_id, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)
    recommendation = repository.list_recommendations()[0]
    plan, _ = repository.start(
        proposal_id=proposal_id,
        focus_id=recommendation["focus_id"],
        expected_source_fingerprint=recommendation["source_fingerprint"],
        idempotency_key="practice-start-hidden",
    )
    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        session.delete(note)
        session.commit()
    assert repository.list_plans() == []
    with pytest.raises(AdaptivePracticeNotFound):
        repository.get(plan["id"])

    session_factory2, _, event_id2, _, proposal_id2 = _setup(tmp_path / "event")
    repository2 = AdaptivePracticeRepository(session_factory2)
    recommendation2 = repository2.list_recommendations()[0]
    plan2, _ = repository2.start(
        proposal_id=proposal_id2,
        focus_id=recommendation2["focus_id"],
        expected_source_fingerprint=recommendation2["source_fingerprint"],
        idempotency_key="practice-start-event-hidden",
    )
    with session_factory2() as session:
        event = session.get(ApplicationEvent, event_id2)
        assert event is not None
        session.delete(event)
        session.commit()
    assert repository2.list_plans() == []
    with pytest.raises(AdaptivePracticeNotFound):
        repository2.get(plan2["id"])


def test_appending_to_source_marks_plan_changed_and_invalidates_old_recommendation(tmp_path) -> None:
    session_factory, _, _, note_id, proposal_id = _setup(tmp_path)
    repository = AdaptivePracticeRepository(session_factory)
    recommendation = repository.list_recommendations()[0]
    plan, _ = repository.start(
        proposal_id=proposal_id,
        focus_id=recommendation["focus_id"],
        expected_source_fingerprint=recommendation["source_fingerprint"],
        idempotency_key="practice-start-source-hash",
    )
    with session_factory() as session:
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.difficulty_points = note.difficulty_points + " 后来补充了新的细节。"
        session.commit()

    assert repository.get(plan["id"])["source_status"] == "changed"
    with pytest.raises(AdaptivePracticeConflict, match="source"):
        repository.start(
            proposal_id=proposal_id,
            focus_id="focus-reflection",
            expected_source_fingerprint=recommendation["source_fingerprint"],
            idempotency_key="practice-start-stale-field",
        )
