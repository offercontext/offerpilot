from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from offerpilot.db import init_database
from offerpilot.models import InterviewNote, MockInterviewAttempt, MockInterviewTurn, Resume
from offerpilot.repositories.interview_stories import (
    StoryValidationError,
    canonical_story_content,
    materialize_selected_sources,
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
