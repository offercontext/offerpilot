from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import gc
import json
from dataclasses import dataclass
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
from typing import Any

import httpx
import uvicorn
from sqlalchemy import delete, func, select

from offerpilot.ai.agent import ChatModel
from offerpilot.ai.interview_preparation_proposals import (
    InterviewPreparationModelError,
    validate_interview_preparation,
)
from offerpilot.ai.types import Assistant, Message, ToolCall
from offerpilot.api import create_app
from offerpilot.db import session_factory_for_data_dir
from offerpilot.models import (
    Application,
    ApplicationEvidenceBundle,
    ApplicationEvent,
    ApplicationMaterialKit,
    InterviewKnowledgeCaptureAttempt,
    InterviewNote,
    InterviewReviewProposal,
    InterviewPreparationProposal,
    KnowledgeCapturedSourceMetadata,
    KnowledgeEvidence,
    KnowledgeExtractionSnapshot,
    KnowledgeNote,
    KnowledgeNoteEvidence,
    KnowledgeNoteVersion,
    KnowledgeSource,
    MaterialRevisionProposal,
    MockSession,
    OpportunityFitReview,
    OpportunityFitReviewSession,
    OpportunityFitReviewStage,
    Question,
    Resume,
    Wakeup,
)
from offerpilot.repositories.json_contract import canonical_json, sha256_text


@dataclass(frozen=True)
class SmokeStep:
    name: str
    detail: str


@dataclass(frozen=True)
class SmokeReport:
    ok: bool
    steps: list[SmokeStep]


class _SmokeChatModel(ChatModel):
    def __init__(self, application_id: int):
        self._application_id = application_id

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> Assistant:
        if messages and messages[-1].role == "tool":
            return Assistant(content="smoke complete")
        user_message = _latest_user_message(messages)
        if "create application card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="smoke-create-application-card",
                        name="create_application",
                        args=json.dumps(
                            {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        if "create event card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="smoke-create-event-card",
                        name="create_application_event",
                        args=json.dumps(
                            {
                                "application_id": self._application_id,
                                "event_type": "written_test",
                                "subtype": "assessment",
                                "scheduled_at": "2026-07-10T19:00:00+08:00",
                                "duration_minutes": 30,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        return Assistant(
            tool_calls=[
                ToolCall(
                    id="smoke-write-1",
                    name="update_application_status",
                    args=json.dumps({"id": self._application_id, "status": "offer"}),
                )
            ]
        )


class _MutableSmokeChatModel(ChatModel):
    def __init__(self) -> None:
        self.application_id: int | None = None

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
    ) -> Assistant:
        if self.application_id is None:
            raise RuntimeError("smoke application id was not initialized")
        if messages and messages[-1].role == "tool":
            return Assistant(content="http smoke complete")
        user_message = _latest_user_message(messages)
        if "create application card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="http-smoke-create-application-card",
                        name="create_application",
                        args=json.dumps(
                            {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"},
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        if "create event card regression" in user_message:
            return Assistant(
                tool_calls=[
                    ToolCall(
                        id="http-smoke-create-event-card",
                        name="create_application_event",
                        args=json.dumps(
                            {
                                "application_id": self.application_id,
                                "event_type": "written_test",
                                "subtype": "assessment",
                                "scheduled_at": "2026-07-10T19:00:00+08:00",
                                "duration_minutes": 30,
                            },
                            ensure_ascii=False,
                        ),
                    )
                ]
            )
        return Assistant(
            tool_calls=[
                ToolCall(
                    id="http-smoke-write-1",
                    name="update_application_status",
                    args=json.dumps({"id": self.application_id, "status": "offer"}),
                )
            ]
        )


def _latest_user_message(messages: list[Message]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content
    return ""


def _assert_create_application_card(pending_body: dict[str, Any]) -> None:
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("create application card smoke did not request confirmation")
    action = pending_body.get("pending_action", {})
    if action.get("tool_name") != "create_application":
        raise RuntimeError("create application card smoke requested the wrong tool")
    if action.get("human") != "新建投递：牛客网 - agent开发":
        raise RuntimeError("create application card smoke lost the human-readable title")
    expected_args = {"company_name": "牛客网", "position_name": "agent开发", "status": "applied"}
    if action.get("args") != expected_args:
        raise RuntimeError("create application card smoke lost the proposed application fields")
    if action.get("target") != {
        "id": "application-draft-牛客网-agent开发",
        "kind": "application",
        "title": "牛客网",
        "meta": "agent开发 · applied",
        "source": "pending_action",
    }:
        raise RuntimeError("create application card smoke lost target record details")
    if action.get("proposed_changes") != [
        {"field": "company_name", "before": "", "after": "牛客网"},
        {"field": "position_name", "before": "", "after": "agent开发"},
        {"field": "status", "before": "", "after": "applied"},
    ]:
        raise RuntimeError("create application card smoke lost proposed record changes")


def _assert_create_event_card(pending_body: dict[str, Any], application_id: int) -> None:
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("create event card smoke did not request confirmation")
    action = pending_body.get("pending_action", {})
    if action.get("tool_name") != "create_application_event":
        raise RuntimeError("create event card smoke requested the wrong tool")
    if action.get("human") != "新建日程：笔试 · 2026-07-10 19:00 · 30 分钟":
        raise RuntimeError("create event card smoke lost the human-readable schedule title")
    if action.get("target") != {
        "id": f"application-event-draft-{application_id}",
        "kind": "application_event",
        "title": "笔试",
        "meta": "2026-07-10 19:00 · 30 分钟",
        "source": "pending_action",
    }:
        raise RuntimeError("create event card smoke lost target schedule details")
    if action.get("proposed_changes") != [
        {"field": "event_type", "before": "", "after": "written_test"},
        {"field": "subtype", "before": "", "after": "assessment"},
        {"field": "scheduled_at", "before": "", "after": "2026-07-10T19:00:00+08:00"},
        {"field": "duration_minutes", "before": "", "after": 30},
    ]:
        raise RuntimeError("create event card smoke lost proposed schedule changes")
    evidence = action.get("evidence") or []
    if not evidence or evidence[0].get("id") != f"application-{application_id}":
        raise RuntimeError("create event card smoke lost application evidence")


def _reject_pending_chat_action(client: Any, pending_body: dict[str, Any], step: str) -> None:
    rejected = client.post(
        "/api/chat/confirm",
        json={
            "conversation_id": pending_body["conversation_id"],
            "approved": False,
            "confirmation_token": pending_body["pending_action"]["confirmation_token"],
        },
    )
    _assert_status(rejected.status_code, 200, step)


def run_core_smoke(data_dir: Path, static_dir: Path | None = None) -> SmokeReport:
    from fastapi.testclient import TestClient

    steps: list[SmokeStep] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    health = client.get("/api/health")
    _assert_status(health.status_code, 200, "health")
    steps.append(SmokeStep("health", "api health returned ok"))

    if static_dir is not None:
        spa = client.get("/applications/smoke")
        _assert_status(spa.status_code, 200, "spa")
        if "root" not in spa.text:
            raise RuntimeError("spa fallback did not serve index.html")
        steps.append(SmokeStep("spa", "spa fallback served index.html"))

    created = client.post(
        "/api/applications",
        json={"company_name": "Smoke Co", "position_name": "Backend", "status": "applied"},
    )
    _assert_status(created.status_code, 201, "create_application")
    application = created.json()
    application_id = int(application["id"])
    steps.append(SmokeStep("create_application", f"created application #{application_id}"))

    chat_client = TestClient(
        create_app(
            data_dir=data_dir,
            static_dir=static_dir,
            chat_model=_SmokeChatModel(application_id),
        )
    )
    pending = chat_client.post("/api/chat", json={"message": "move to offer", "conversation_id": 0})
    _assert_status(pending.status_code, 200, "chat_pending")
    pending_body = pending.json()
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("chat did not request confirmation")
    before_confirm = client.get(f"/api/applications/{application_id}").json()
    if before_confirm["status"] != "applied":
        raise RuntimeError("write tool mutated before confirmation")
    steps.append(SmokeStep("chat_pending", "write action paused for confirmation"))

    confirmed = chat_client.post(
        "/api/chat/confirm",
        json={
            "conversation_id": pending_body["conversation_id"],
            "approved": True,
            "confirmation_token": pending_body["pending_action"]["confirmation_token"],
        },
    )
    _assert_status(confirmed.status_code, 200, "confirm_action")
    after_confirm = client.get(f"/api/applications/{application_id}").json()
    if after_confirm["status"] != "offer":
        raise RuntimeError("confirmed write did not update application")
    steps.append(SmokeStep("confirm_action", "confirmed write updated application"))

    conversations = chat_client.get("/api/chat/conversations").json()
    if conversations[0]["pending_action"] is not None:
        raise RuntimeError("pending action was not cleared")
    steps.append(SmokeStep("pending_cleared", "pending action cleared after confirmation"))

    _run_chat_card_regression_smoke(chat_client, steps, application_id)

    return SmokeReport(ok=True, steps=steps)


def run_http_smoke(
    data_dir: Path,
    static_dir: Path | None = None,
    *,
    real_ai: bool = False,
) -> SmokeReport:
    if not real_ai:
        return _run_http_smoke(data_dir, static_dir=static_dir, real_ai=False)

    with tempfile.TemporaryDirectory(prefix="offerpilot-real-ai-verify-") as temp_dir:
        isolated_data_dir = Path(temp_dir)
        _copy_real_ai_config(data_dir, isolated_data_dir)
        report = _run_http_smoke(isolated_data_dir, static_dir=static_dir, real_ai=True)
        _assert_real_ai_smoke_data_clean(isolated_data_dir)
        return report


def _run_http_smoke(
    data_dir: Path,
    static_dir: Path | None = None,
    *,
    real_ai: bool = False,
) -> SmokeReport:
    steps: list[SmokeStep] = []
    smoke_resume_ids: list[int] = []
    data_dir.mkdir(parents=True, exist_ok=True)

    _run_unconfigured_chat_smoke(static_dir, steps)

    local_model = None if real_ai else _MutableSmokeChatModel()
    app = create_app(data_dir=data_dir, static_dir=static_dir, chat_model=local_model)
    with _running_server(app) as base_url:
        with httpx.Client(base_url=base_url, timeout=60.0) as client:
            health = client.get("/api/health")
            _assert_status(health.status_code, 200, "http_health")
            steps.append(SmokeStep("http_health", "GET /api/health returned ok"))

            settings = client.get("/api/settings")
            _assert_status(settings.status_code, 200, "http_settings")
            settings_body = settings.json()
            if real_ai and not bool(settings_body.get("has_api_key")):
                raise RuntimeError("real-ai profile requires a configured API key")
            steps.append(SmokeStep("http_settings", "GET /api/settings returned current AI settings"))

            if static_dir is not None:
                spa = client.get("/applications/smoke")
                _assert_status(spa.status_code, 200, "http_spa")
                if "root" not in spa.text:
                    raise RuntimeError("http_spa did not serve index.html")
                steps.append(SmokeStep("http_spa", "GET /applications/smoke served the SPA fallback"))

            marker = str(int(time.time() * 1000))
            company = f"AI HTTP Smoke {marker}"
            created = client.post(
                "/api/applications",
                json={
                    "company_name": company,
                    "position_name": "Verification Engineer",
                    "status": "applied",
                    "source": "smoke",
                },
            )
            _assert_status(created.status_code, 201, "http_create_application")
            application_id = int(created.json()["id"])
            if local_model is not None:
                local_model.application_id = application_id
            steps.append(SmokeStep("http_create_application", f"POST /api/applications created #{application_id}"))

            try:
                listed = client.get("/api/applications", params={"status": "applied"})
                _assert_status(listed.status_code, 200, "http_list_applications")
                if not any(item.get("id") == application_id for item in listed.json()):
                    raise RuntimeError("created application was not returned by list endpoint")
                steps.append(SmokeStep("http_list_applications", "GET /api/applications returned created record"))

                _run_resume_http_smoke(client, steps)
                _run_application_event_http_smoke(client, steps, application_id)

                if real_ai:
                    _run_real_ai_interview_preparation_smoke(client, steps, application_id, smoke_resume_ids)
                    _run_real_ai_material_proposal_smoke(client, steps, application_id, smoke_resume_ids)
                    _run_real_ai_opportunity_fit_smoke(client, steps, application_id, smoke_resume_ids)
                    _run_real_ai_interview_review_smoke(client, steps, application_id)
                    _run_real_ai_interview_knowledge_capture_smoke(client, steps, application_id)
                    _run_real_ai_write_smoke(client, steps, company, application_id)
                else:
                    _run_local_proposal_terminal_smoke(
                        client, steps, application_id, data_dir, smoke_resume_ids
                    )
                    _run_deterministic_chat_smoke(client, steps, application_id)
                    _run_chat_card_regression_smoke(client, steps, application_id, step_prefix="http_")
            finally:
                cleanup = client.delete(f"/api/applications/{application_id}")
                _assert_status(cleanup.status_code, 200, "http_cleanup")
                if real_ai:
                    _cleanup_real_ai_smoke_records(data_dir, application_id, smoke_resume_ids)
                steps.append(SmokeStep("http_cleanup", f"deleted smoke application #{application_id}"))

    return SmokeReport(ok=True, steps=steps)


def _run_real_ai_interview_preparation_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
    resume_ids: list[int] | None = None,
) -> None:
    resume_raw_text = "Built reliable API services; input_snapshot is a literal term here."
    resume_content_json = {
        "raw_text": resume_raw_text,
        "experience": [{"highlights": ["Built reliable API services", "Led a migration."]}],
    }
    resume = client.post(
        "/api/resumes",
        json={
            "title": "AI Interview Preparation Smoke Resume",
            "text": resume_raw_text,
            "content_json": resume_content_json,
        },
    )
    _assert_status(resume.status_code, 201, "http_interview_preparation_resume")
    resume_id = int(resume.json()["id"])
    if resume_ids is not None:
        resume_ids.append(resume_id)
    event = client.post(
        "/api/application-events",
        json={
            "application_id": application_id,
            "event_type": "interview",
            "subtype": "technical",
            "scheduled_at": "2026-07-24T10:00:00Z",
            "duration_minutes": 45,
        },
    )
    _assert_status(event.status_code, 201, "http_interview_preparation_event")
    event_body = event.json()
    event_id = int(event_body["id"])
    scheduled_at = event_body.get("scheduled_at")
    if isinstance(scheduled_at, str) and scheduled_at:
        try:
            scheduled_at = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00")).replace(
                tzinfo=None
            ).isoformat()
        except ValueError:
            pass
    event_snapshot = {
        "id": event_id,
        "application_id": application_id,
        "event_type": event_body.get("event_type", "interview"),
        "subtype": event_body.get("subtype", "technical"),
        "round": event_body.get("round", 0),
        "scheduled_at": scheduled_at,
        "duration_minutes": event_body.get("duration_minutes", 45),
        "status": event_body.get("status", "todo"),
    }
    cases = [
        "Build reliable Python services and explain operational tradeoffs.",
        "Design an API migration with safe rollback and observability.",
        "Review distributed systems failure handling and testing practices.",
    ]
    verified_non_empty = 0
    for index, jd_text in enumerate(cases, start=1):
        request_payload = {
            "event_id": event_id,
            "resume_id": resume_id,
            "jd_text": jd_text,
            "knowledge_selections": [],
            "user_assertions": [f"I led preparation case {index}."],
            "idempotency_key": f"interview-preparation-smoke-{index}",
        }
        snapshot = {
            "event": event_snapshot,
            "jd": {"text": jd_text},
            "resume": {"id": resume_id, "content_json": resume_content_json},
            "knowledge_evidence": [],
            "user_assertions": request_payload["user_assertions"],
        }
        pending_retries = 0
        while True:
            response = client.post(
                f"/api/applications/{application_id}/interview-preparation-proposals",
                json=request_payload,
            )
            body = response.json()
            _assert_interview_preparation_smoke_response_safe(body)
            if response.status_code != 202:
                if response.status_code not in {200, 201}:
                    raise RuntimeError(
                        f"http_interview_preparation_proposal_{index} returned status "
                        f"{response.status_code}, expected 200 or 201"
                    )
                _validate_interview_preparation_proposal_response(
                    body,
                    application_id=application_id,
                    event_id=event_id,
                    resume_id=resume_id,
                    snapshot=snapshot,
                )
                break
            _validate_interview_preparation_pending_response(
                body, request_payload, application_id=application_id, event_id=event_id
            )
            if pending_retries >= 3:
                raise RuntimeError("interview preparation smoke pending result did not complete")
            time.sleep(min(body["retry_after_ms"], 30_000) / 1000)
            pending_retries += 1
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("proposal"), dict):
            raise RuntimeError("interview preparation smoke response did not contain a proposal")
        if body.get("proposal_status") == "normal":
            proposal = body["proposal"]
            if any(
                isinstance(items, list)
                and any(isinstance(item, dict) and item.get("evidence_refs") for item in items)
                for items in proposal.values()
            ):
                verified_non_empty += 1
    if verified_non_empty < 1:
        raise RuntimeError("interview preparation smoke returned no evidence-backed non-empty proposal")
    steps.append(
        SmokeStep(
            "http_interview_preparation_proposal",
            "real AI returned safe interview preparation results with at least one cited result",
        )
    )


def _assert_interview_preparation_smoke_response_safe(body: object) -> None:
    if not isinstance(body, dict):
        raise RuntimeError("interview preparation smoke response was not an object")


def _validate_interview_preparation_proposal_response(
    body: dict[str, object],
    *,
    application_id: int,
    event_id: int,
    resume_id: int,
    snapshot: dict[str, Any],
) -> None:
    expected_fields = {
        "id",
        "application_id",
        "event_id",
        "resume_id",
        "attempt_status",
        "proposal_status",
        "source_fingerprint",
        "source_status",
        "source_states",
        "proposal",
        "proposal_hash",
        "created_at",
    }
    if set(body) != expected_fields:
        raise RuntimeError("interview preparation smoke proposal response fields were invalid")
    if body["attempt_status"] != "ready":
        raise RuntimeError("interview preparation smoke returned an invalid terminal status")
    if body["proposal_status"] not in {"normal", "safe_empty"}:
        raise RuntimeError("interview preparation smoke returned an invalid proposal status")
    if any(
        type(body[field]) is not int or body[field] != expected
        for field, expected in (
            ("application_id", application_id),
            ("event_id", event_id),
            ("resume_id", resume_id),
        )
    ):
        raise RuntimeError("interview preparation smoke proposal response ownership was invalid")
    if type(body["id"]) is not int or body["id"] <= 0:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    if any(
        not isinstance(body[field], str) or not body[field]
        for field in ("source_fingerprint", "proposal_hash")
    ):
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    if not isinstance(body["source_status"], str) or body["source_status"] not in {
        "current",
        "not_checked",
        "source_changed",
    }:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    if not isinstance(body["source_states"], dict):
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    expected_states = {
        "event": "current",
        "resume": "current",
        "jd": "not_checked",
        "knowledge": "current",
    }
    if body["source_states"] != expected_states:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    expected_source_status = "source_changed" if "source_changed" in expected_states.values() else "not_checked"
    if body["source_status"] != expected_source_status:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    expected_source_fingerprint = sha256_text(canonical_json(snapshot))
    if body["source_fingerprint"] != expected_source_fingerprint:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    created_at = body["created_at"]
    if not isinstance(created_at, str) or not created_at:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RuntimeError("interview preparation smoke terminal metadata was invalid") from exc

    proposal = body["proposal"]
    if not isinstance(proposal, dict) or set(proposal) != {
        "preparation_directions",
        "story_prompts",
        "review_points",
        "interviewer_questions",
        "items_to_clarify",
    }:
        raise RuntimeError("interview preparation smoke proposal structure was invalid")
    for items in proposal.values():
        if not isinstance(items, list):
            raise RuntimeError("interview preparation smoke proposal structure was invalid")
        for item in items:
            if not isinstance(item, dict) or set(item) != {"id", "text", "evidence_refs"}:
                raise RuntimeError("interview preparation smoke proposal structure was invalid")
            if not isinstance(item["id"], str) or not isinstance(item["text"], str):
                raise RuntimeError("interview preparation smoke proposal structure was invalid")
            evidence_refs = item["evidence_refs"]
            if not isinstance(evidence_refs, list) or not evidence_refs:
                raise RuntimeError("interview preparation smoke proposal structure was invalid")
            for evidence_ref in evidence_refs:
                if not isinstance(evidence_ref, dict) or set(evidence_ref) != {
                    "source",
                    "path",
                    "excerpt",
                }:
                    raise RuntimeError("interview preparation smoke proposal structure was invalid")
                if not all(isinstance(evidence_ref[field], str) for field in ("source", "path", "excerpt")):
                    raise RuntimeError("interview preparation smoke proposal structure was invalid")
    try:
        validate_interview_preparation(proposal, snapshot)
    except InterviewPreparationModelError as exc:
        raise RuntimeError("interview preparation smoke evidence was not traceable") from exc
    item_count = sum(len(items) for items in proposal.values())
    if body["proposal_status"] == "safe_empty" and item_count != 0:
        raise RuntimeError("interview preparation smoke proposal status was not empty")
    if body["proposal_status"] == "normal" and item_count == 0:
        raise RuntimeError("interview preparation smoke returned an empty proposal")
    if body["proposal_hash"] != sha256_text(canonical_json(proposal)):
        raise RuntimeError("interview preparation smoke terminal metadata was invalid")


def _validate_interview_preparation_pending_response(
    body: dict[str, object],
    request_payload: dict[str, object],
    *,
    application_id: int,
    event_id: int,
) -> None:
    expected_fields = {
        "attempt_status",
        "application_id",
        "event_id",
        "idempotency_key",
        "generation_revision",
        "retry_after_ms",
    }
    if set(body) != expected_fields:
        raise RuntimeError("interview preparation smoke pending response fields were invalid")
    if body["attempt_status"] not in {"generating", "provider_unknown"}:
        raise RuntimeError("interview preparation smoke returned an invalid pending status")
    if body["application_id"] != application_id:
        raise RuntimeError("interview preparation smoke pending application did not match")
    if body["event_id"] != event_id:
        raise RuntimeError("interview preparation smoke pending event did not match")
    if body["idempotency_key"] != request_payload.get("idempotency_key"):
        raise RuntimeError("interview preparation smoke pending key did not match")
    for field in ("generation_revision", "retry_after_ms"):
        value = body[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise RuntimeError("interview preparation smoke pending timing fields were invalid")


def _run_real_ai_material_proposal_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
    resume_ids: list[int] | None = None,
) -> None:
    anchor_resume_id: int | None = None
    resume_id: int | None = None
    try:
        anchor = client.post(
            "/api/resumes",
            json={
                "title": "AI Material Proposal Smoke Anchor",
                "text": "",
                "content_json": {},
            },
        )
        _assert_status(anchor.status_code, 201, "http_material_proposal_resume_anchor")
        anchor_resume_id = int(anchor.json()["id"])
        if resume_ids is not None:
            resume_ids.append(anchor_resume_id)

        created_resume = client.post(
            "/api/resumes",
            json={
                "title": "AI Material Proposal Smoke Resume",
                "text": "Built API services. Led migration.",
                "content_json": {
                    "experience": [{"highlights": ["Built API services", "Led migration"]}],
                    "skills": ["Python"],
                    "raw_text": "Built API services. Led migration.",
                },
            },
        )
        _assert_status(created_resume.status_code, 201, "http_material_proposal_resume")
        resume_id = int(created_resume.json()["id"])
        if resume_ids is not None:
            resume_ids.append(resume_id)

        kit = client.post(
            f"/api/applications/{application_id}/material-kit/generate",
            json={
                "resume_id": resume_id,
                "jd_text": "Evidence QA Engineer: build reliable API quality workflows.",
            },
        )
        _assert_status(kit.status_code, 201, "http_material_proposal_kit")

        proposal = client.post(
            f"/api/applications/{application_id}/material-revision-proposals",
            json={
                "instructions": "Prefer only safe evidence-backed changes.",
                "user_assertions": ["I led the migration."],
            },
        )
        _assert_status(proposal.status_code, 201, "http_material_proposal")
        body = proposal.json()
        _validate_material_proposal_smoke_response(body)
        steps.append(
            SmokeStep(
                "http_material_proposal",
                "real AI returned a verified material proposal",
            )
        )
    finally:
        del anchor_resume_id, resume_id


def _run_real_ai_opportunity_fit_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
    resume_ids: list[int] | None = None,
) -> None:
    anchor_resume_id: int | None = None
    resume_id: int | None = None
    try:
        anchor = client.post(
            "/api/resumes",
            json={"title": "AI Opportunity Fit Smoke Anchor", "text": "", "content_json": {}},
        )
        _assert_status(anchor.status_code, 201, "http_opportunity_fit_resume_anchor")
        anchor_resume_id = int(anchor.json()["id"])
        if resume_ids is not None:
            resume_ids.append(anchor_resume_id)

        created_resume = client.post(
            "/api/resumes",
            json={
                "title": "AI Opportunity Fit Smoke Resume",
                "text": "Built API services and led migration.",
                "content_json": {
                    "raw_text": "Built API services and led migration.",
                    "skills": ["Python"],
                },
            },
        )
        _assert_status(created_resume.status_code, 201, "http_opportunity_fit_resume")
        resume_id = int(created_resume.json()["id"])
        if resume_ids is not None:
            resume_ids.append(resume_id)

        review = client.post(
            f"/api/applications/{application_id}/opportunity-fit-reviews",
            json={
                "resume_id": resume_id,
                "jd_text": "Build reliable API quality workflows.",
                "jd_source_label": "Smoke pasted JD",
                "candidate_assertions": ["I led the migration."],
                "idempotency_key": "f36f6d0b-1d1e-4e9a-aec1-9fef6b2f3b90",
            },
        )
        _assert_status(review.status_code, 201, "http_opportunity_fit_review")
        body = review.json()
        if not isinstance(body, dict) or "triage" not in body or "source_snapshot_json" in body:
            raise RuntimeError("opportunity fit smoke response leaked frozen source data")
        triage = body.get("triage")
        if not isinstance(triage, dict):
            raise RuntimeError("opportunity fit smoke response did not contain triage")
        review_id = body.get("id")
        if not isinstance(review_id, int):
            raise RuntimeError("opportunity fit smoke response did not contain a review id")
        deep_review = client.post(
            f"/api/applications/{application_id}/opportunity-fit-reviews/{review_id}/deep-review"
        )
        _assert_status(deep_review.status_code, 201, "http_opportunity_fit_deep_review")
        deep_body = deep_review.json()
        if not isinstance(deep_body, dict) or not isinstance(deep_body.get("deep_review"), dict):
            raise RuntimeError("opportunity fit smoke response did not contain deep review")
        steps.append(
            SmokeStep(
                "http_opportunity_fit_review",
                "real AI returned a verified opportunity fit triage",
            )
        )
        steps.append(
            SmokeStep(
                "http_opportunity_fit_deep_review",
                "real AI returned a verified opportunity fit deep review",
            )
        )
    finally:
        del anchor_resume_id, resume_id


def _run_real_ai_interview_review_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    cases = [
        {
            "marker": "SMOKE_PRIVATE_INTERVIEW_QUESTION",
            "questions": "SMOKE_PRIVATE_INTERVIEW_QUESTION: explain the migration rollback plan",
            "self_reflection": "I gave a concise answer after clarifying the constraint.",
            "difficulty_points": "I needed more time to structure the tradeoff.",
            "mood": "focused",
        },
        {
            "marker": "SMOKE_PRIVATE_INTERVIEW_REFLECTION",
            "questions": "Explain the cache invalidation strategy.",
            "self_reflection": "SMOKE_PRIVATE_INTERVIEW_REFLECTION: I omitted the failure mode initially.",
            "difficulty_points": "I needed more time to structure the tradeoff.",
            "mood": "nervous",
        },
        {
            "marker": "SMOKE_PRIVATE_INTERVIEW_DIFFICULTY",
            "questions": "How would you debug a slow query?",
            "self_reflection": "I asked for a moment to organize the answer.",
            "difficulty_points": "SMOKE_PRIVATE_INTERVIEW_DIFFICULTY: prioritizing the first diagnostic step",
            "mood": "focused",
        },
    ]
    verified_non_empty = 0
    for index, case in enumerate(cases, start=1):
        event = client.post(
            "/api/application-events",
            json={
                "application_id": application_id,
                "event_type": "interview",
                "subtype": "technical",
                "round": index,
                "scheduled_at": f"2026-07-22T{9 + index:02d}:00:00+08:00",
                "duration_minutes": 45,
                "location": "SMOKE_PRIVATE_LOCATION",
            },
        )
        _assert_status(event.status_code, 201, f"http_interview_review_event_{index}")
        event_body = event.json()
        event_id = event_body.get("id") if isinstance(event_body, dict) else None
        if not isinstance(event_id, int):
            raise RuntimeError("interview review smoke did not return an event id")

        note = client.post(
            f"/api/applications/{application_id}/notes",
            json={
                "company": "AI Interview Review Smoke",
                "position": "Verification Engineer",
                "round": "technical",
                "date": "2026-07-22",
                "questions": case["questions"],
                "self_reflection": case["self_reflection"],
                "difficulty_points": case["difficulty_points"],
                "mood": case["mood"],
                "application_event_id": event_id,
            },
        )
        _assert_status(note.status_code, 201, f"http_interview_review_note_{index}")
        note_body = note.json()
        note_id = note_body.get("id") if isinstance(note_body, dict) else None
        if not isinstance(note_id, int):
            raise RuntimeError("interview review smoke did not return a note id")

        proposal = client.post(
            f"/api/notes/{note_id}/interview-review-proposals",
            json={"idempotency_key": f"interview-review-smoke-{index}"},
        )
        _assert_status(proposal.status_code, 201, f"http_interview_review_proposal_{index}")
        body = proposal.json()
        if not isinstance(body, dict) or not isinstance(body.get("proposal"), dict):
            raise RuntimeError("interview review smoke response did not contain a verified proposal")
        serialized = json.dumps(body, ensure_ascii=False)
        cited = _validate_interview_review_smoke_evidence(
            body["proposal"],
            case["marker"],
            {
                "/questions": case["questions"],
                "/self_reflection": case["self_reflection"],
                "/difficulty_points": case["difficulty_points"],
                "/mood": case["mood"],
            },
        )
        if cited:
            verified_non_empty += 1
        if "SMOKE_PRIVATE_LOCATION" in serialized:
            raise RuntimeError("interview review smoke response leaked frozen source data")
        if "input_snapshot_json" in body or "input_snapshot" in body:
            raise RuntimeError("interview review smoke response exposed the input snapshot")
    if verified_non_empty < 1:
        raise RuntimeError("interview review smoke returned no evidence-backed non-empty proposal")
    steps.append(
        SmokeStep(
            "http_interview_review_proposal",
            "real AI returned three safe interview review proposals with at least one cited result",
        )
    )


def _run_real_ai_interview_knowledge_capture_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    event = client.post(
        "/api/application-events",
        json={
            "application_id": application_id,
            "event_type": "interview",
            "subtype": "knowledge-capture",
            "scheduled_at": "2026-07-24T10:00:00+08:00",
            "duration_minutes": 45,
        },
    )
    _assert_status(event.status_code, 201, "http_interview_knowledge_event")
    event_id = event.json().get("id")
    if not isinstance(event_id, int):
        raise RuntimeError("interview knowledge smoke did not return an event id")
    note = client.post(
        f"/api/applications/{application_id}/notes",
        json={
            "company": "AI Interview Knowledge Smoke",
            "position": "Verification Engineer",
            "round": "technical",
            "date": "2026-07-24",
            "questions": "I explained the rollback plan and the observable safety signal.",
            "self_reflection": "I should have stated the tradeoff before the implementation detail.",
            "difficulty_points": "I needed a moment to structure the tradeoff.",
            "mood": "focused",
            "application_event_id": event_id,
        },
    )
    _assert_status(note.status_code, 201, "http_interview_knowledge_note")
    note_id = note.json().get("id")
    if not isinstance(note_id, int):
        raise RuntimeError("interview knowledge smoke did not return a note id")
    selected = [
        {
            "fragment_id": "smoke-question",
            "path": "/questions",
            "start": 2,
            "end": 63,
            "text": "explained the rollback plan and the observable safety signal.",
        },
        {
            "fragment_id": "smoke-reflection",
            "path": "/self_reflection",
            "start": 0,
            "end": 67,
            "text": "I should have stated the tradeoff before the implementation detail.",
        },
    ]
    preview = client.post(
        f"/api/notes/{note_id}/knowledge-capture/preview",
        json={"attempt_key": "real-ai-interview-knowledge", "mode": "ai", "selected_fragments": selected},
    )
    _assert_status(preview.status_code, 200, "http_interview_knowledge_preview")
    preview_body = preview.json()
    if not isinstance(preview_body, dict) or not isinstance(preview_body.get("preview"), dict):
        raise RuntimeError("interview knowledge smoke preview was not an object")
    if "input_snapshot" in preview_body or "source_fields" in preview_body:
        raise RuntimeError("interview knowledge smoke exposed the input snapshot")
    confirm = client.post(
        f"/api/notes/{note_id}/knowledge-capture/confirm",
        json={
            "attempt_key": preview_body["attempt_key"],
            "note_fingerprint": preview_body["note_fingerprint"],
            "title": "Interview rollback reflection",
            "blocks": preview_body["preview"].get("blocks", []),
        },
    )
    _assert_status(confirm.status_code, 201, "http_interview_knowledge_confirm")
    confirmed = client.get("/api/knowledge/notes")
    _assert_status(confirmed.status_code, 200, "http_interview_knowledge_history")
    if not confirmed.json().get("items"):
        raise RuntimeError("interview knowledge smoke did not return confirmed history")
    steps.append(
        SmokeStep(
            "http_interview_knowledge_capture",
            "real AI preview was reviewed and confirmed into frozen interview knowledge",
        )
    )


def _validate_interview_review_smoke_evidence(
    proposal: Any,
    marker: str,
    expected_excerpts: dict[str, str] | None = None,
) -> bool:
    if not isinstance(proposal, dict):
        raise RuntimeError("interview review smoke proposal was not an object")
    has_verified_evidence = False
    for field in ("summary", "observations", "clarifications", "practice_focuses", "next_questions"):
        values = proposal.get(field)
        items = values if isinstance(values, list) else [values]
        for item in items:
            if not isinstance(item, dict):
                raise RuntimeError("interview review smoke proposal item was not an object")
            refs = item.get("evidence_refs", [])
            if not isinstance(refs, list):
                raise RuntimeError("interview review smoke evidence refs were not an array")
            for ref in refs:
                if (
                    not isinstance(ref, dict)
                    or set(ref) != {"source", "path", "excerpt"}
                    or ref.get("source") != "interview_note"
                    or ref.get("path") not in {"/questions", "/self_reflection", "/difficulty_points", "/mood"}
                    or not isinstance(ref.get("excerpt"), str)
                    or not ref["excerpt"]
                ):
                    raise RuntimeError("interview review smoke returned an invalid evidence reference")
                if expected_excerpts is not None and ref["excerpt"] not in expected_excerpts.get(
                    str(ref["path"]), ""
                ):
                    raise RuntimeError("interview review smoke evidence excerpt did not match note")
                if marker in ref["excerpt"] or expected_excerpts is not None:
                    has_verified_evidence = True
    return has_verified_evidence


def _copy_real_ai_config(source_data_dir: Path, isolated_data_dir: Path) -> None:
    source_config = source_data_dir / "config.json"
    if source_config.is_file():
        shutil.copyfile(source_config, isolated_data_dir / "config.json")


def _cleanup_real_ai_smoke_records(
    data_dir: Path,
    application_id: int,
    resume_ids: list[int],
) -> None:
    session_factory = session_factory_for_data_dir(data_dir)
    try:
        with session_factory() as session:
            session.execute(
                delete(MaterialRevisionProposal).where(
                    MaterialRevisionProposal.application_id == application_id
                )
            )
            note_ids = select(InterviewNote.id).where(InterviewNote.application_id == application_id)
            session.execute(
                delete(InterviewReviewProposal).where(InterviewReviewProposal.note_id.in_(note_ids))
            )
            session.execute(
                delete(InterviewPreparationProposal).where(
                    InterviewPreparationProposal.application_id == application_id
                )
            )
            captured_note_ids = list(
                session.scalars(
                    select(InterviewNote.id).where(InterviewNote.application_id == application_id)
                )
            )
            captured_source_ids = list(
                session.scalars(
                    select(KnowledgeCapturedSourceMetadata.source_id).where(
                        KnowledgeCapturedSourceMetadata.origin_note_id.in_(captured_note_ids)
                    )
                )
            )
            captured_version_ids = list(
                session.scalars(
                    select(KnowledgeNoteVersion.id).where(
                        KnowledgeNoteVersion.source_id.in_(captured_source_ids)
                    )
                )
            )
            captured_knowledge_note_ids = list(
                session.scalars(
                    select(KnowledgeNoteVersion.note_id).where(
                        KnowledgeNoteVersion.id.in_(captured_version_ids)
                    )
                )
            )
            session.execute(delete(KnowledgeNoteEvidence).where(KnowledgeNoteEvidence.note_version_id.in_(captured_version_ids)))
            session.execute(delete(KnowledgeNoteVersion).where(KnowledgeNoteVersion.id.in_(captured_version_ids)))
            session.execute(delete(KnowledgeNote).where(KnowledgeNote.id.in_(captured_knowledge_note_ids)))
            session.execute(delete(KnowledgeEvidence).where(KnowledgeEvidence.source_id.in_(captured_source_ids)))
            session.execute(delete(KnowledgeExtractionSnapshot).where(KnowledgeExtractionSnapshot.source_id.in_(captured_source_ids)))
            session.execute(delete(KnowledgeCapturedSourceMetadata).where(KnowledgeCapturedSourceMetadata.source_id.in_(captured_source_ids)))
            session.execute(delete(KnowledgeSource).where(KnowledgeSource.id.in_(captured_source_ids)))
            session.execute(delete(InterviewKnowledgeCaptureAttempt).where(InterviewKnowledgeCaptureAttempt.note_id.in_(captured_note_ids)))
            session.execute(delete(InterviewNote).where(InterviewNote.application_id == application_id))
            session.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id == application_id))
            session.execute(
                delete(ApplicationMaterialKit).where(
                    ApplicationMaterialKit.application_id == application_id
                )
            )
            session.execute(
                delete(OpportunityFitReview).where(
                    OpportunityFitReview.application_id == application_id
                )
            )
            session.execute(
                delete(ApplicationEvidenceBundle).where(
                    ApplicationEvidenceBundle.application_id == application_id
                )
            )
            session.execute(delete(Application).where(Application.id == application_id))
            if resume_ids:
                session.execute(delete(Resume).where(Resume.id.in_(resume_ids)))
            session.commit()
    finally:
        bind = session_factory.kw.get("bind")
        if bind is not None:
            bind.dispose()


def _cleanup_real_ai_browser_records(
    data_dir: Path,
    application_id: int,
    resume_ids: list[int],
) -> None:
    """Remove only the synthetic records created by the isolated browser harness."""
    _cleanup_real_ai_smoke_records(data_dir, application_id, resume_ids)


def _capture_real_ai_browser_domain_baseline(
    data_dir: Path,
    application_id: int,
    event_ids: list[int] | None = None,
    resume_ids: list[int] | None = None,
) -> dict[str, Any]:
    """Capture scoped data that the interview-preparation browser flow must not mutate."""
    session_factory = session_factory_for_data_dir(data_dir)
    try:
        with session_factory() as session:
            application = session.get(Application, application_id)
            if application is None:
                raise RuntimeError(f"browser smoke application {application_id} is missing")
            selected_event_ids = sorted(event_ids or [])
            selected_resume_ids = sorted(resume_ids or [])
            event_snapshots = {
                str(event_id): _real_ai_browser_event_snapshot(session.get(ApplicationEvent, event_id))
                for event_id in selected_event_ids
            }
            resume_snapshots = {
                str(resume_id): _real_ai_browser_resume_snapshot(session.get(Resume, resume_id))
                for resume_id in selected_resume_ids
            }
            return {
                "application_status": application.status,
                "application_closed_reason": application.closed_reason,
                "application_deleted_at": (
                    application.deleted_at.isoformat() if application.deleted_at is not None else None
                ),
                "material_kit_count": session.scalar(
                    select(func.count())
                    .select_from(ApplicationMaterialKit)
                    .where(ApplicationMaterialKit.application_id == application_id)
                ),
                "material_proposal_count": session.scalar(
                    select(func.count())
                    .select_from(MaterialRevisionProposal)
                    .where(MaterialRevisionProposal.application_id == application_id)
                ),
                "opportunity_fit_count": session.scalar(
                    select(func.count())
                    .select_from(OpportunityFitReview)
                    .where(OpportunityFitReview.application_id == application_id)
                ),
                "opportunity_fit_session_count": session.scalar(
                    select(func.count())
                    .select_from(OpportunityFitReviewSession)
                    .where(OpportunityFitReviewSession.application_id == application_id)
                ),
                "opportunity_fit_stage_count": session.scalar(
                    select(func.count())
                    .select_from(OpportunityFitReviewStage)
                    .where(OpportunityFitReviewStage.application_id == application_id)
                ),
                "question_count": session.scalar(
                    select(func.count()).select_from(Question).where(Question.application_id == application_id)
                ),
                "mock_session_count": session.scalar(
                    select(func.count())
                    .select_from(MockSession)
                    .where(MockSession.application_id == application_id)
                ),
                "reminder_count": session.scalar(select(func.count()).select_from(Wakeup)),
                "knowledge_note_count": session.scalar(select(func.count()).select_from(KnowledgeNote)),
                "knowledge_source_count": session.scalar(select(func.count()).select_from(KnowledgeSource)),
                "knowledge_evidence_count": session.scalar(select(func.count()).select_from(KnowledgeEvidence)),
                "knowledge_capture_attempt_count": session.scalar(
                    select(func.count()).select_from(InterviewKnowledgeCaptureAttempt)
                ),
                "interview_event_count": session.scalar(
                    select(func.count())
                    .select_from(ApplicationEvent)
                    .where(ApplicationEvent.application_id == application_id)
                ),
                "event_snapshot_hash": sha256_text(canonical_json(event_snapshots)),
                "resume_count": session.scalar(
                    select(func.count()).select_from(Resume).where(Resume.deleted_at.is_(None))
                ),
                "resume_snapshot_hash": sha256_text(canonical_json(resume_snapshots)),
                # Memory has no persistent model/table in the current product schema.
                "memory_count": 0,
            }
    finally:
        bind = session_factory.kw.get("bind")
        if bind is not None:
            bind.dispose()


def _assert_real_ai_browser_no_cross_domain_writes(
    data_dir: Path,
    application_id: int,
    baseline: dict[str, Any],
    event_ids: list[int] | None = None,
    resume_ids: list[int] | None = None,
) -> None:
    current = _capture_real_ai_browser_domain_baseline(data_dir, application_id, event_ids, resume_ids)
    differences = {
        key: {"before": baseline.get(key), "after": value}
        for key, value in current.items()
        if baseline.get(key) != value
    }
    if differences:
        raise RuntimeError(
            "real-ai browser flow created cross-domain writes: "
            + json.dumps(differences, ensure_ascii=False, sort_keys=True)
        )


def _real_ai_browser_event_snapshot(event: ApplicationEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "id": event.id,
        "application_id": event.application_id,
        "event_type": event.event_type,
        "subtype": event.subtype,
        "tags": event.tags,
        "round": event.round,
        "scheduled_at": event.scheduled_at.isoformat() if event.scheduled_at else None,
        "duration_minutes": event.duration_minutes,
        "location": event.location,
        "notes": event.notes,
        "status": event.status,
    }


def _real_ai_browser_resume_snapshot(resume: Resume | None) -> dict[str, Any] | None:
    if resume is None:
        return None
    return {
        "id": resume.id,
        "name": resume.name,
        "title": resume.title,
        "parsed_data": resume.parsed_data,
        "parse_status": resume.parse_status,
        "parent_resume_id": resume.parent_resume_id,
        "source": resume.source,
        "content_json": resume.content_json,
        "is_master": resume.is_master,
        "deleted_at": resume.deleted_at.isoformat() if resume.deleted_at else None,
    }


def _assert_real_ai_smoke_data_clean(data_dir: Path) -> None:
    session_factory = session_factory_for_data_dir(data_dir)
    try:
        with session_factory() as session:
            active_resume_count = session.scalar(
                select(func.count()).select_from(Resume).where(Resume.deleted_at.is_(None))
            )
            active_master_count = session.scalar(
                select(func.count())
                .select_from(Resume)
                .where(Resume.deleted_at.is_(None))
                .where(Resume.is_master.is_(True))
            )
            material_kit_count = session.scalar(select(func.count()).select_from(ApplicationMaterialKit))
            proposal_count = session.scalar(select(func.count()).select_from(MaterialRevisionProposal))
            interview_note_count = session.scalar(select(func.count()).select_from(InterviewNote))
            interview_event_count = session.scalar(
                select(func.count()).select_from(ApplicationEvent).where(ApplicationEvent.event_type == "interview")
            )
            interview_proposal_count = session.scalar(select(func.count()).select_from(InterviewReviewProposal))
            interview_preparation_proposal_count = session.scalar(
                select(func.count()).select_from(InterviewPreparationProposal)
            )
            opportunity_fit_review_count = session.scalar(
                select(func.count()).select_from(OpportunityFitReview)
            )
            application_count = session.scalar(select(func.count()).select_from(Application))
            evidence_bundle_count = session.scalar(
                select(func.count()).select_from(ApplicationEvidenceBundle)
            )
            captured_knowledge_count = session.scalar(
                select(func.count()).select_from(KnowledgeNote).where(
                    KnowledgeNote.origin_kind == "confirmed_interview_capture"
                )
            )
    finally:
        bind = session_factory.kw.get("bind")
        if bind is not None:
            bind.dispose()

    if active_resume_count != 0:
        raise RuntimeError("real-ai smoke left active resumes")
    if active_master_count != 0:
        raise RuntimeError("real-ai smoke left active master resumes")
    if material_kit_count != 0:
        raise RuntimeError("real-ai smoke left material kits")
    if proposal_count != 0:
        raise RuntimeError("real-ai smoke left material proposals")
    if interview_note_count != 0:
        raise RuntimeError("real-ai smoke left interview notes")
    if interview_event_count != 0:
        raise RuntimeError("real-ai smoke left interview events")
    if interview_proposal_count != 0:
        raise RuntimeError("real-ai smoke left interview review proposals")
    if interview_preparation_proposal_count != 0:
        raise RuntimeError("real-ai smoke left interview preparation proposals")
    if opportunity_fit_review_count != 0:
        raise RuntimeError("real-ai smoke left opportunity fit reviews")
    if application_count != 0:
        raise RuntimeError("real-ai smoke left applications")
    if evidence_bundle_count != 0:
        raise RuntimeError("real-ai smoke left evidence bundles")
    if captured_knowledge_count != 0:
        raise RuntimeError("real-ai smoke left confirmed interview knowledge")


def _validate_material_proposal_smoke_response(body: object) -> None:
    if not isinstance(body, dict):
        raise RuntimeError("material proposal response was not an object")
    expected_root = {
        "id",
        "application_id",
        "material_kit_id",
        "source_resume_id",
        "status",
        "summary",
        "proposal_sha256",
        "result_resume_id",
        "created_at",
        "changes",
        "source",
        "accepted_change_ids",
        "accepted_at",
        "rejected_at",
    }
    if set(body) != expected_root:
        raise RuntimeError("material proposal response leaked frozen source data")
    changes = body.get("changes")
    if not isinstance(changes, list):
        raise RuntimeError("material proposal response did not contain changes")
    for change in changes:
        if not isinstance(change, dict) or set(change) != {
            "id",
            "path",
            "before",
            "after",
            "rationale",
            "evidence_refs",
        }:
            raise RuntimeError("material proposal response leaked frozen source data")
        refs = change.get("evidence_refs")
        if not isinstance(refs, list):
            raise RuntimeError("material proposal response leaked frozen source data")
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"source", "path", "excerpt"}:
                raise RuntimeError("material proposal response leaked frozen source data")

    source = body.get("source")
    if not isinstance(source, dict) or set(source) != {
        "application",
        "material_kit",
        "resume",
        "latest_evidence_bundle",
        "user_assertions",
    }:
        raise RuntimeError("material proposal response leaked frozen source data")
    if not isinstance(source.get("application"), dict) or set(source["application"]) != {
        "id",
        "company_name",
        "position_name",
    }:
        raise RuntimeError("material proposal response leaked frozen source data")
    if not isinstance(source.get("material_kit"), dict) or set(source["material_kit"]) != {
        "id",
        "jd_excerpt",
    }:
        raise RuntimeError("material proposal response leaked frozen source data")
    if not isinstance(source.get("resume"), dict) or set(source["resume"]) != {"id", "title"}:
        raise RuntimeError("material proposal response leaked frozen source data")
    bundle = source.get("latest_evidence_bundle")
    if bundle is not None and (not isinstance(bundle, dict) or set(bundle) != {"id", "bundle_sha256"}):
        raise RuntimeError("material proposal response leaked frozen source data")
    assertions = source.get("user_assertions")
    if not isinstance(assertions, list) or any(
        not isinstance(item, dict) or set(item) != {"id", "text"} for item in assertions
    ):
        raise RuntimeError("material proposal response leaked frozen source data")


def _run_unconfigured_chat_smoke(static_dir: Path | None, steps: list[SmokeStep]) -> None:
    with tempfile.TemporaryDirectory(prefix="offerpilot-smoke-unconfigured-", ignore_cleanup_errors=True) as temp_dir:
        app = create_app(data_dir=Path(temp_dir), static_dir=static_dir)
        with _running_server(app) as base_url:
            with httpx.Client(base_url=base_url, timeout=30.0) as client:
                response = client.post("/api/chat", json={"message": "hello", "conversation_id": 0})
                _assert_status(response.status_code, 503, "http_unconfigured_chat")
                if "AI is not configured" not in response.json().get("error", ""):
                    raise RuntimeError("unconfigured chat did not return a clear AI setup error")
                steps.append(SmokeStep("http_unconfigured_chat", "POST /api/chat returned setup guidance without API key"))
        del app
        gc.collect()


def _run_resume_http_smoke(client: httpx.Client, steps: list[SmokeStep]) -> None:
    empty_content = {
        "career_intent": {"target_roles": [], "target_locations": []},
        "contact": {},
        "education": [],
        "experience": [],
        "projects": [],
        "skills": [],
        "raw_text": "",
    }
    created = client.post(
        "/api/resumes",
        json={"title": "HTTP Smoke Resume Draft", "source": "dialog", "content_json": empty_content},
    )
    _assert_status(created.status_code, 201, "http_resume_crud")
    resume_id = int(created.json()["id"])
    try:
        updated = client.patch(f"/api/resumes/{resume_id}", json={"title": "HTTP Smoke Resume Draft Updated"})
        _assert_status(updated.status_code, 200, "http_resume_crud")
        fetched = client.get(f"/api/resumes/{resume_id}")
        _assert_status(fetched.status_code, 200, "http_resume_crud")
        if fetched.json()["title"] != "HTTP Smoke Resume Draft Updated":
            raise RuntimeError("resume update was not reflected by get endpoint")
        listed = client.get("/api/resumes")
        _assert_status(listed.status_code, 200, "http_resume_crud")
        if not any(item.get("id") == resume_id for item in listed.json()):
            raise RuntimeError("created resume was not returned by list endpoint")
    finally:
        deleted = client.delete(f"/api/resumes/{resume_id}")
        _assert_status(deleted.status_code, 200, "http_resume_crud")
    steps.append(SmokeStep("http_resume_crud", "resume create, update, read, list, and delete endpoints worked"))


def _run_application_event_http_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    created = client.post(
        "/api/application-events",
        json={
            "application_id": application_id,
            "event_type": "interview",
            "scheduled_at": "2026-07-10T10:00:00Z",
            "duration_minutes": 30,
            "notes": "http smoke",
        },
    )
    _assert_status(created.status_code, 201, "http_application_event_crud")
    event_id = int(created.json()["id"])
    try:
        updated = client.put(
            f"/api/application-events/{event_id}",
            json={
                "application_id": application_id,
                "event_type": "interview",
                "scheduled_at": "2026-07-11T10:00:00Z",
                "duration_minutes": 45,
                "notes": "http smoke updated",
            },
        )
        _assert_status(updated.status_code, 200, "http_application_event_crud")
        fetched = client.get(f"/api/application-events/{event_id}")
        _assert_status(fetched.status_code, 200, "http_application_event_crud")
        if fetched.json()["duration_minutes"] != 45:
            raise RuntimeError("application event update was not reflected by get endpoint")
        listed = client.get("/api/application-events", params={"application_id": application_id})
        _assert_status(listed.status_code, 200, "http_application_event_crud")
        if not any(item.get("id") == event_id for item in listed.json()):
            raise RuntimeError("created application event was not returned by list endpoint")
    finally:
        deleted = client.delete(f"/api/application-events/{event_id}")
        _assert_status(deleted.status_code, 200, "http_application_event_crud")
    steps.append(
        SmokeStep(
            "http_application_event_crud",
            "application event create, update, read, list, and delete endpoints worked",
        )
    )


def _run_local_proposal_terminal_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
    data_dir: Path,
    resume_ids: list[int],
) -> None:
    """Exercise the five proposal terminal contracts without an external provider.

    The local profile intentionally uses a chat model that cannot produce proposal
    JSON.  This keeps the smoke deterministic while proving that each flow has its
    own safe contract-failure behavior and that knowledge capture can fall back to
    a direct, user-confirmed preview.
    """
    resume_content = {
        "raw_text": "Built local smoke services.",
        "skills": ["Python"],
        "experience": [],
        "projects": [],
        "career_intent": {"target_roles": []},
    }
    resume_response = client.post(
        "/api/resumes",
        json={
            "title": "Local proposal terminal smoke resume",
            "text": resume_content["raw_text"],
            "content_json": resume_content,
        },
    )
    _assert_status(resume_response.status_code, 201, "http_proposal_terminal_resume")
    resume_id = int(resume_response.json()["id"])
    resume_ids.append(resume_id)

    session_factory = session_factory_for_data_dir(data_dir)
    try:
        with session_factory() as session:
            session.add(
                ApplicationMaterialKit(
                    application_id=application_id,
                    resume_id=resume_id,
                    jd_snapshot="Build reliable local smoke services.",
                    content_json=canonical_json({"summary": "local smoke kit"}),
                )
            )
            session.commit()
    finally:
        bind = session_factory.kw.get("bind")
        if bind is not None:
            bind.dispose()

    material_response = client.post(
        f"/api/applications/{application_id}/material-revision-proposals",
        json={"instructions": "Highlight reliability.", "user_assertions": []},
    )
    _assert_status(material_response.status_code, 502, "http_material_contract_failure")
    if material_response.json().get("error_code") != "material_proposal_unverifiable":
        raise RuntimeError("material contract failure used the wrong error code")
    if client.get(f"/api/applications/{application_id}/material-revision-proposals").json():
        raise RuntimeError("material contract failure wrote a proposal")

    opportunity_response = client.post(
        f"/api/applications/{application_id}/opportunity-fit-reviews",
        json={
            "resume_id": resume_id,
            "jd_text": "Build reliable local smoke services.",
            "jd_source_label": "local smoke",
            "candidate_assertions": [],
            "idempotency_key": "f3a1bd2e-6f1f-4dd4-bc5f-1a0c9be4f001",
        },
    )
    _assert_status(opportunity_response.status_code, 502, "http_opportunity_contract_failure")
    if opportunity_response.json().get("error_code") != "opportunity_fit_unverifiable":
        raise RuntimeError("opportunity contract failure used the wrong error code")
    if client.get(f"/api/applications/{application_id}/opportunity-fit-reviews").json():
        raise RuntimeError("opportunity contract failure wrote a review")

    event_response = client.post(
        "/api/application-events",
        json={
            "application_id": application_id,
            "event_type": "interview",
            "subtype": "terminal-matrix",
            "scheduled_at": "2026-07-24T10:00:00Z",
            "duration_minutes": 30,
        },
    )
    _assert_status(event_response.status_code, 201, "http_proposal_terminal_event")
    event_id = int(event_response.json()["id"])
    note_response = client.post(
        f"/api/applications/{application_id}/notes",
        json={
            "company": "Local smoke",
            "position": "Verification Engineer",
            "round": "technical",
            "date": "2026-07-24",
            "questions": "I explained the rollback plan.",
            "self_reflection": "I should state the tradeoff earlier.",
            "difficulty_points": "Structuring the answer was difficult.",
            "mood": "focused",
            "application_event_id": event_id,
        },
    )
    _assert_status(note_response.status_code, 201, "http_proposal_terminal_note")
    note_id = int(note_response.json()["id"])

    review_response = client.post(
        f"/api/notes/{note_id}/interview-review-proposals",
        json={"idempotency_key": "local-proposal-matrix-review-01"},
    )
    _assert_status(review_response.status_code, 201, "http_interview_review_safe_empty")
    review_body = review_response.json()
    if review_body.get("proposal", {}).get("observations") != []:
        raise RuntimeError("interview review contract failure was not a safe empty result")
    review_replay = client.post(
        f"/api/notes/{note_id}/interview-review-proposals",
        json={"idempotency_key": "local-proposal-matrix-review-01"},
    )
    _assert_status(review_replay.status_code, 200, "http_interview_review_safe_empty_replay")

    selected_fragment = {
        "fragment_id": "local-question",
        "path": "/questions",
        "start": 0,
        "end": len("I explained the rollback plan."),
        "text": "I explained the rollback plan.",
    }
    no_evidence = client.post(
        f"/api/notes/{note_id}/knowledge-capture/preview",
        json={"attempt_key": "local-proposal-matrix-empty", "mode": "ai", "selected_fragments": []},
    )
    _assert_status(no_evidence.status_code, 422, "http_knowledge_no_evidence")
    knowledge_response = client.post(
        f"/api/notes/{note_id}/knowledge-capture/preview",
        json={
            "attempt_key": "local-proposal-matrix-knowledge-01",
            "mode": "ai",
            "selected_fragments": [selected_fragment],
        },
    )
    _assert_status(knowledge_response.status_code, 200, "http_knowledge_safe_empty")
    if knowledge_response.json().get("preview_status") != "safe_empty":
        raise RuntimeError("knowledge contract failure was not a safe empty preview")
    direct_response = client.post(
        f"/api/notes/{note_id}/knowledge-capture/preview",
        json={
            "attempt_key": "local-proposal-matrix-knowledge-01",
            "mode": "direct",
            "selected_fragments": [selected_fragment],
        },
    )
    _assert_status(direct_response.status_code, 200, "http_knowledge_direct_fallback")
    if direct_response.json().get("preview_status") != "direct_ready":
        raise RuntimeError("knowledge direct fallback was not available")

    preparation_response = client.post(
        f"/api/applications/{application_id}/interview-preparation-proposals",
        json={
            "event_id": event_id,
            "resume_id": resume_id,
            "jd_text": "Build reliable local smoke services.",
            "knowledge_selections": [],
            "user_assertions": [],
            "idempotency_key": "local-proposal-matrix-prep-01",
        },
    )
    _assert_status(preparation_response.status_code, 201, "http_interview_preparation_safe_empty")
    if preparation_response.json().get("proposal_status") != "safe_empty":
        raise RuntimeError("interview preparation contract failure was not a safe empty result")
    steps.append(
        SmokeStep(
            "http_proposal_terminal_matrix",
            "local profile covered contract failures, safe-empty results, no-evidence rejection, replay, and direct knowledge fallback",
        )
    )


def _run_chat_card_regression_smoke(
    client: Any,
    steps: list[SmokeStep],
    application_id: int,
    *,
    step_prefix: str = "",
) -> None:
    create_application_step = f"{step_prefix}chat_create_application_card"
    create_application_pending = client.post(
        "/api/chat",
        json={"message": "create application card regression", "conversation_id": 0},
    )
    _assert_status(create_application_pending.status_code, 200, create_application_step)
    _assert_create_application_card(create_application_pending.json())
    _reject_pending_chat_action(client, create_application_pending.json(), create_application_step)
    steps.append(SmokeStep(create_application_step, "create application confirmation card kept key fields"))

    create_event_step = f"{step_prefix}chat_create_event_card"
    create_event_pending = client.post(
        "/api/chat",
        json={"message": "create event card regression", "conversation_id": 0},
    )
    _assert_status(create_event_pending.status_code, 200, create_event_step)
    _assert_create_event_card(create_event_pending.json(), application_id)
    _reject_pending_chat_action(client, create_event_pending.json(), create_event_step)
    steps.append(SmokeStep(create_event_step, "create event confirmation card kept schedule details"))


def _run_deterministic_chat_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    application_id: int,
) -> None:
    pending = client.post("/api/chat", json={"message": "move to offer", "conversation_id": 0})
    _assert_status(pending.status_code, 200, "http_chat_pending")
    pending_body = pending.json()
    if pending_body.get("type") != "confirmation_required":
        raise RuntimeError("http chat did not request confirmation")
    before_confirm = client.get(f"/api/applications/{application_id}").json()
    if before_confirm["status"] != "applied":
        raise RuntimeError("http write tool mutated before confirmation")
    steps.append(SmokeStep("http_chat_pending", "POST /api/chat paused write action for confirmation"))

    confirmed = client.post(
        "/api/chat/confirm",
        json={
            "conversation_id": pending_body["conversation_id"],
            "approved": True,
            "confirmation_token": pending_body["pending_action"]["confirmation_token"],
        },
    )
    _assert_status(confirmed.status_code, 200, "http_confirm_action")
    after_confirm = client.get(f"/api/applications/{application_id}").json()
    if after_confirm["status"] != "offer":
        raise RuntimeError("http confirmed write did not update application")
    steps.append(SmokeStep("http_confirm_action", "POST /api/chat/confirm updated application"))

    conversations = client.get("/api/chat/conversations")
    _assert_status(conversations.status_code, 200, "http_pending_cleared")
    if conversations.json()[0]["pending_action"] is not None:
        raise RuntimeError("http pending action was not cleared")
    steps.append(SmokeStep("http_pending_cleared", "pending action cleared after confirmation"))


def _run_real_ai_write_smoke(
    client: httpx.Client,
    steps: list[SmokeStep],
    company: str,
    application_id: int,
) -> None:
    prompt = (
        "Verification smoke: use the update_application_status tool to change the existing "
        f"application for {company} with id {application_id} to status offer. "
        "Do not create any other records."
    )
    pending = client.post("/api/chat", json={"message": prompt, "conversation_id": 0})
    _assert_status(pending.status_code, 200, "http_chat_pending")
    pending_body = pending.json()
    conversation_id = int(pending_body["conversation_id"])
    if pending_body.get("type") == "confirmation_required":
        if pending_body.get("pending_action", {}).get("tool_name") != "update_application_status":
            raise RuntimeError("real-ai smoke requested an unexpected pending tool")
        steps.append(SmokeStep("http_chat_pending", "real AI requested write confirmation"))
        confirmed = client.post(
            "/api/chat/confirm",
            json={
                "conversation_id": conversation_id,
                "approved": True,
                "confirmation_token": pending_body["pending_action"]["confirmation_token"],
            },
        )
        _assert_status(confirmed.status_code, 200, "http_confirm_action")
    else:
        steps.append(SmokeStep("http_chat_pending", "real AI completed without pending confirmation"))

    updated = client.get(f"/api/applications/{application_id}")
    _assert_status(updated.status_code, 200, "http_confirm_action")
    if updated.json()["status"] != "offer":
        raise RuntimeError("real-ai smoke did not update the application to offer")
    steps.append(SmokeStep("http_confirm_action", "real AI write updated application"))

    conversations = client.get("/api/chat/conversations")
    _assert_status(conversations.status_code, 200, "http_pending_cleared")
    match = next((item for item in conversations.json() if item["id"] == conversation_id), None)
    if match is None:
        raise RuntimeError("real-ai smoke conversation was not listed")
    if match["pending_action"] is not None:
        raise RuntimeError("real-ai smoke pending action was not cleared")
    steps.append(SmokeStep("http_pending_cleared", "real AI conversation has no pending action"))


@contextmanager
def _running_server(app: Any) -> Any:
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/api/health", timeout=1.0)
            if response.status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        _dispose_smoke_app_database(app)
        raise RuntimeError("http smoke server did not become ready")
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        _dispose_smoke_app_database(app)


def _dispose_smoke_app_database(app: Any) -> None:
    engine = getattr(app.state, "db_engine", None)
    if engine is not None:
        engine.dispose()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _assert_status(actual: int, expected: int, step: str) -> None:
    if actual != expected:
        raise RuntimeError(f"{step} returned status {actual}, expected {expected}")
