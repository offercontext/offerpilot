import json
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from offerpilot.db import init_database
from offerpilot.models import Application, ApplicationEvent, MockInterviewAttempt, Resume
from offerpilot.repositories.mock_interviews import (
    MockInterviewIdempotencyConflict,
    MockInterviewRepository,
    MockInterviewTurnIdempotencyConflict,
)


def _seed(factory):
    with factory() as session:
        application = Application(company_name="Acme", position_name="Engineer", status="interview")
        session.add(application)
        session.flush()
        event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            status="todo",
        )
        second_event = ApplicationEvent(
            application_id=application.id,
            event_type="interview",
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
            status="todo",
        )
        resume = Resume(title="Resume", parsed_data="Python", content_json=json.dumps({"skills": ["Python"]}))
        other_resume = Resume(title="Other", parsed_data="Go", content_json=json.dumps({"skills": ["Go"]}))
        session.add_all([event, second_event, resume, other_resume])
        session.commit()
        return application.id, event.id, second_event.id, resume.id, other_resume.id


def test_start_requires_visible_scheduled_interview_and_selected_resume(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)

    result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    )
    attempt = result.attempt

    assert attempt.application_id == app_id
    assert attempt.event_id == event_id
    assert attempt.resume_id == resume_id


def test_start_rejects_empty_jd_without_provider_call(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)

    with pytest.raises(ValueError, match="jd_text"):
        repo.create_or_replay_start(app_id, event_id, resume_id, "  ", None, "attempt-1", "question-1")


def test_answer_updates_transcript_not_source_fingerprint(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    )
    attempt, turn = result.attempt, result.turn
    source_fingerprint = attempt.source_fingerprint

    updated = repo.submit_answer(attempt.id, 1, "My answer", "answer-1")

    assert updated.source_fingerprint == source_fingerprint
    assert updated.transcript_fingerprint != attempt.transcript_fingerprint
    assert updated.current_turn_no == 1
    assert turn.question_idempotency_key == "question-1"


def test_same_attempt_key_same_input_replays_existing_attempt(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    first_result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    )
    first, first_turn = first_result.attempt, first_result.turn

    replay_result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    )
    replay, replay_turn = replay_result.attempt, replay_result.turn

    assert replay.id == first.id
    assert replay_turn.id == first_turn.id


def test_same_attempt_key_different_input_returns_idempotency_conflict(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, other_resume_id = _seed(factory)
    repo = MockInterviewRepository(factory)
    repo.create_or_replay_start(app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1")

    with pytest.raises(MockInterviewIdempotencyConflict):
        repo.create_or_replay_start(app_id, event_id, other_resume_id, "JD text", None, "attempt-1", "question-2")


def test_same_turn_key_different_answer_returns_turn_idempotency_conflict(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    attempt = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    ).attempt
    repo.submit_answer(attempt.id, 1, "first", "answer-1")

    with pytest.raises(MockInterviewTurnIdempotencyConflict):
        repo.submit_answer(attempt.id, 1, "second", "answer-1")


def test_editing_submitted_answer_requires_new_attempt(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    attempt = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    ).attempt
    repo.submit_answer(attempt.id, 1, "first", "answer-1")

    with pytest.raises(MockInterviewTurnIdempotencyConflict):
        repo.submit_answer(attempt.id, 1, "edited", "answer-2")


def test_initial_question_key_is_persisted_on_first_turn(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)

    result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "initial-question-1"
    )
    turn = result.turn

    assert turn.question_idempotency_key == "initial-question-1"


def test_same_initial_question_key_replays_first_turn(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    first = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "initial-question-1"
    ).attempt

    replay_result = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "initial-question-1"
    )
    replay, turn = replay_result.attempt, replay_result.turn

    assert replay.id == first.id
    assert turn.question_idempotency_key == "initial-question-1"


def test_different_initial_question_key_returns_turn_idempotency_conflict(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "initial-question-1"
    )

    with pytest.raises(MockInterviewTurnIdempotencyConflict):
        repo.create_or_replay_start(
            app_id, event_id, resume_id, "JD text", None, "attempt-1", "initial-question-2"
        )


def test_concurrent_first_start_creates_one_attempt_and_one_provider_owner(tmp_path):
    path = tmp_path / "data.db"
    factory = init_database(path)
    app_id, event_id, _, resume_id, _ = _seed(factory)
    barrier = threading.Barrier(2)
    results = []

    def start() -> None:
        repo = MockInterviewRepository(init_database(path))
        barrier.wait()
        results.append(
            repo.create_or_replay_start(
                app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
            )
        )

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == 2
    with factory() as session:
        assert session.query(MockInterviewAttempt).count() == 1
        assert session.scalar(select(MockInterviewAttempt).where(MockInterviewAttempt.id == results[0].attempt.id)).id == results[1].attempt.id


def test_expired_question_lease_has_one_cas_takeover(tmp_path):
    factory = init_database(tmp_path / "data.db")
    app_id, event_id, _, resume_id, _ = _seed(factory)
    repo = MockInterviewRepository(factory)
    attempt = repo.create_or_replay_start(
        app_id, event_id, resume_id, "JD text", None, "attempt-1", "question-1"
    ).attempt
    with factory() as session:
        stored = session.get(MockInterviewAttempt, attempt.id)
        assert stored is not None
        stored.provider_lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()

    first = repo.claim_question(attempt.id, 1, "question-1")
    second = repo.claim_question(attempt.id, 1, "question-1")

    assert first is not None
    assert second is None
