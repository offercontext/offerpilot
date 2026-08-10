from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from offerpilot.db import init_database
from offerpilot.models import (
    InterviewNote,
    InterviewStory,
    InterviewStoryUserAssertion,
    InterviewStoryVersion,
    InterviewStoryVersionEvidenceLink,
    MockInterviewAttempt,
    MockInterviewTurn,
    Resume,
)
from offerpilot.repositories.interview_stories import (
    InterviewStoriesRepository,
    StoryConflictError,
    StoryValidationError,
    canonical_story_content,
    derive_story_source_states,
    materialize_selected_sources,
    story_request_fingerprint,
    validate_story_evidence_links,
)


def test_canonical_story_content_assigns_stable_target_ids_to_duplicate_text() -> None:
    content = canonical_story_content(
        {
            "title": "同一个项目",
            "blocks": [
                {"kind": "situation", "text": "重复文本", "fact_mode": "evidence_backed"},
                {"kind": "action", "text": "重复文本", "fact_mode": "evidence_backed"},
                {"kind": "reflection", "text": "我的复盘", "fact_mode": "user_view"},
            ],
            "capability_labels": ["沟通", "沟通"],
            "applicable_questions": ["你遇到过什么挑战？"],
            "fact_gap_codes": ["missing_result"],
        }
    )

    assert content["title"] == {"id": "title", "text": "同一个项目"}
    assert [block["id"] for block in content["blocks"]] == [
        "situation_001",
        "action_001",
        "reflection_001",
    ]
    assert [item["id"] for item in content["capability_labels"]] == [
        "capability_001",
        "capability_002",
    ]
    assert content["blocks"][2]["fact_mode"] == "user_view"


def test_materialize_selected_sources_limits_to_allowed_original_fields_and_paths(tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    with factory() as session:
        resume = Resume(
            name="筱哲",
            title="后端工程师",
            content_json=json.dumps({"项目/名": "处理 emoji 🚀 与 NFD e\u0301"}, ensure_ascii=False),
        )
        note = InterviewNote(
            company="星云数据",
            position="后端工程师",
            questions="如何排查线上延迟？",
            self_reflection="我先确认了指标。",
            difficulty_points="没有立即给出量化结果。",
            mood="平静",
        )
        attempt = MockInterviewAttempt(
            application_id=1,
            event_id=1,
            resume_id=1,
            idempotency_key="mock-story-source-key",
            input_snapshot_json="{}",
            source_fingerprint="mock-fingerprint",
            attempt_status="feedback_ready",
            transcript_fingerprint="transcript",
            completed_at=datetime.now(timezone.utc),
        )
        session.add_all([resume, note, attempt])
        session.flush()
        turn = MockInterviewTurn(
            attempt_id=attempt.id,
            turn_no=1,
            question_idempotency_key="mock-question-key",
            turn_idempotency_key="mock-answer-key",
            question_text="请介绍一个项目。",
            answer_text="我用分段定位解决了延迟。",
            turn_status="answered",
        )
        session.add(turn)
        session.commit()

        snapshot = materialize_selected_sources(
            session,
            [
                {"source_kind": "interview_note", "source_id": note.id, "path": "/questions"},
                {
                    "source_kind": "resume_version",
                    "source_id": resume.id,
                    "path": "/content_json/项目~1名",
                },
                {
                    "source_kind": "mock_turn",
                    "source_id": attempt.id,
                    "path": "/turns/001/answer",
                },
            ],
            ["我确认这是我负责的项目。"],
        )

    factory.kw["bind"].dispose()

    assert [item["source_kind"] for item in snapshot.sources] == [
        "interview_note",
        "mock_turn",
        "resume_version",
        "user_assertion",
    ]
    assert snapshot.sources[2]["excerpt"] == "处理 emoji 🚀 与 NFD e\u0301"
    assert snapshot.sources[0]["excerpt"] == "如何排查线上延迟？"
    assert snapshot.sources[3]["path"] == "/statement"


@pytest.mark.parametrize(
    ("selection", "message"),
    [
        ({"source_kind": "knowledge", "source_id": 1, "path": "/text"}, "source kind"),
        ({"source_kind": "interview_note", "source_id": 1, "path": "/proposal_json"}, "path"),
        ({"source_kind": "mock_turn", "source_id": 1, "path": "/turns/1/answer"}, "path"),
        ({"source_kind": "mock_turn", "source_id": 1, "path": "/turns/\u0660\u0660\u0661/answer"}, "path"),
        ({"source_kind": "resume_version", "source_id": 1, "path": "/title"}, "path"),
        ({"source_kind": "resume_version", "source_id": 1, "path": "/content_json/a~2b"}, "path"),
    ],
)
def test_materialize_selected_sources_rejects_non_story_evidence(selection, message, tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    with factory() as session:
        with pytest.raises(StoryValidationError, match=message):
            materialize_selected_sources(session, [selection], [])
    factory.kw["bind"].dispose()


def test_resume_source_rejects_unicode_digit_array_index_alias(tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    with factory() as session:
        resume = Resume(
            name="筱哲",
            content_json=json.dumps({"items": ["可引用文本"]}, ensure_ascii=False),
        )
        session.add(resume)
        session.commit()

        with pytest.raises(StoryValidationError, match="path"):
            materialize_selected_sources(
                session,
                [
                    {
                        "source_kind": "resume_version",
                        "source_id": resume.id,
                        "path": "/content_json/items/١",
                    }
                ],
                [],
            )
    factory.kw["bind"].dispose()


def _manual_content() -> dict[str, object]:
    return {
        "title": "Order service recovery",
        "blocks": [
            {"kind": "situation", "text": "Latency increased", "fact_mode": "evidence_backed"},
            {"kind": "action", "text": "I isolated the bottleneck", "fact_mode": "evidence_backed"},
            {"kind": "reflection", "text": "I should communicate earlier", "fact_mode": "user_view"},
        ],
        "capability_labels": ["incident response"],
        "applicable_questions": ["Tell me about an incident"],
        "fact_gap_codes": ["missing_result"],
    }


def _links_for_content(content, snapshot) -> list[dict[str, str]]:
    note = next(item for item in snapshot.sources if item["source_kind"] == "interview_note")
    assertion = next(item for item in snapshot.sources if item["source_kind"] == "user_assertion")

    def source_fields(item: dict[str, str]) -> dict[str, str]:
        return {
            "source_kind": item["source_kind"],
            "source_stable_id": item["source_stable_id"],
            "source_version_or_snapshot": item["source_version_or_snapshot"],
            "source_path": item["path"],
            "excerpt": item["excerpt"],
        }

    targets = [
        ("title", content["title"]["id"]),
        *[("block", item["id"]) for item in content["blocks"]],
        *[("capability_label", item["id"]) for item in content["capability_labels"]],
        *[("applicable_question", item["id"]) for item in content["applicable_questions"]],
    ]
    return [
        {
            "target_kind": target_kind,
            "target_id": target_id,
            **source_fields(assertion if target_id == "reflection_001" else note),
        }
        for target_kind, target_id in targets
    ]


def _create_note(session) -> InterviewNote:
    note = InterviewNote(
        company="Nebula Data",
        position="Backend Engineer",
        questions="How did you handle the incident?",
        self_reflection="I should communicate earlier",
        difficulty_points="I need a measurable result",
        mood="calm",
    )
    session.add(note)
    session.flush()
    return note


def test_evidence_links_require_exact_target_and_frozen_source_identity(tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    with factory() as session:
        note = _create_note(session)
        session.commit()
        content = canonical_story_content(_manual_content())
        snapshot = materialize_selected_sources(
            session,
            [{"source_kind": "interview_note", "source_id": note.id, "path": "/questions"}],
            ["I own this incident response."],
        )
        links = _links_for_content(content, snapshot)

        canonical = validate_story_evidence_links(content, links, snapshot)
        assert len(canonical) == 6

        forged = [dict(item) for item in links]
        forged[0]["source_path"] = "/self_reflection"
        with pytest.raises(StoryValidationError, match="source"):
            validate_story_evidence_links(content, forged, snapshot)

        incomplete = links[:-1]
        with pytest.raises(StoryValidationError, match="targets require evidence"):
            validate_story_evidence_links(content, incomplete, snapshot)
    factory.kw["bind"].dispose()


def test_manual_story_version_cas_assertions_and_read_time_source_states(tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    repository = InterviewStoriesRepository(factory)
    with factory() as session:
        note = _create_note(session)
        note_id = note.id
        session.commit()
        content = canonical_story_content(_manual_content())
        snapshot = materialize_selected_sources(
            session,
            [{"source_kind": "interview_note", "source_id": note_id, "path": "/questions"}],
            ["I own this incident response."],
        )
    created = repository.create_manual_story(
        content=_manual_content(),
        evidence_links=_links_for_content(content, snapshot),
        selections=[{"source_kind": "interview_note", "source_id": note_id, "path": "/questions"}],
        assertions=["I own this incident response."],
        expected_current_version_id=None,
    )
    version_id = created["current_version_id"]
    assert created["story_revision"] == 1
    assert created["version"]["version_number"] == 1
    assert created["version"]["assertions"] == [
        {"id": created["version"]["assertions"][0]["id"], "statement": "I own this incident response.", "frozen": True}
    ]
    assertion_link = next(
        item for item in created["version"]["evidence_links"] if item["source_kind"] == "user_assertion"
    )
    assert assertion_link["source_stable_id"] == str(created["version"]["assertions"][0]["id"])

    with pytest.raises(StoryConflictError, match="stale"):
        repository.create_manual_version(
            story_id=created["id"],
            content=_manual_content(),
            evidence_links=_links_for_content(content, snapshot),
            selections=[{"source_kind": "interview_note", "source_id": note_id, "path": "/questions"}],
            assertions=["I own this incident response."],
            expected_current_version_id=version_id,
            expected_story_revision=99,
        )

    with factory() as session:
        assert session.scalar(select(InterviewStoryVersion).where(InterviewStoryVersion.story_id == created["id"])) is not None
        assert len(list(session.scalars(select(InterviewStoryUserAssertion)))) == 1
        note = session.get(InterviewNote, note_id)
        assert note is not None
        note.questions = "How did you coordinate the recovery?"
        session.commit()
        version = session.get(InterviewStoryVersion, version_id)
        assert version is not None
        states = derive_story_source_states(session, version)
        assert {item["state"] for item in states} >= {"changed", "frozen_user_assertion"}
        assert session.scalar(select(InterviewStoryVersionEvidenceLink).where(InterviewStoryVersionEvidenceLink.story_version_id == version_id)) is not None
        assert session.get(InterviewStory, created["id"]).current_version_id == version_id

    archived = repository.archive(story_id=created["id"], expected_story_revision=1)
    assert archived["status"] == "archived"
    with pytest.raises(StoryConflictError, match="archived"):
        repository.create_manual_version(
            story_id=created["id"],
            content=_manual_content(),
            evidence_links=_links_for_content(content, snapshot),
            selections=[{"source_kind": "interview_note", "source_id": note_id, "path": "/questions"}],
            assertions=["I own this incident response."],
            expected_current_version_id=version_id,
            expected_story_revision=2,
        )
    restored = repository.restore(story_id=created["id"], expected_story_revision=2)
    assert restored["status"] == "active"
    factory.kw["bind"].dispose()


def test_invalid_manual_save_rolls_back_all_story_rows_and_fingerprint_is_order_stable(tmp_path) -> None:
    factory = init_database(tmp_path / "story.db")
    repository = InterviewStoriesRepository(factory)
    with factory() as session:
        note = _create_note(session)
        session.commit()
        with pytest.raises(StoryValidationError, match="targets require evidence"):
            repository.create_manual_story(
                content=_manual_content(),
                evidence_links=[],
                selections=[{"source_kind": "interview_note", "source_id": note.id, "path": "/questions"}],
                assertions=["I own this incident response."],
                expected_current_version_id=None,
            )
        assert list(session.scalars(select(InterviewStory))) == []
        assert list(session.scalars(select(InterviewStoryVersion))) == []
        assert list(session.scalars(select(InterviewStoryUserAssertion))) == []

    selections = [
        {"source_kind": "interview_note", "source_id": 2, "path": "/questions"},
        {"source_kind": "resume_version", "source_id": 1, "path": "/content_json/name"},
    ]
    assert story_request_fingerprint(
        target_story_id=None,
        expected_current_version_id=None,
        expected_story_revision=None,
        selections=selections,
        assertions=["statement"],
    ) == story_request_fingerprint(
        target_story_id=None,
        expected_current_version_id=None,
        expected_story_revision=None,
        selections=list(reversed(selections)),
        assertions=["statement"],
    )
    factory.kw["bind"].dispose()
