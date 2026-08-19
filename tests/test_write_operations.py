from __future__ import annotations

from uuid import uuid4

import pytest

from offerpilot.agent_runtime.journal import NullRunRecorder
from offerpilot.ai.agent import PendingAction
from offerpilot.ai.tool_runtime.context import ToolCapability, ToolExecutionContext
from offerpilot.ai.tool_runtime.contracts import (
    BindingAudit,
    ExecutionAuthorization,
    PreparedToolCall,
    ProviderToolContract,
    REQUIRED_UNDO_TOOL_NAMES,
    TRANSACTIONAL_TYPED_WRITE_NAMES,
    ToolExceptionMapping,
    ToolSpec,
    WriteContract,
)
from offerpilot.ai.write_operations import (
    COMPENSATION_OPERATION_NAMES,
    LEDGER_KEY_FILENAME,
    LEGACY_WRITE_OPERATION_NAMES,
    REQUIRED_UNDO_OPERATION_NAMES,
    TYPED_WRITE_OPERATION_NAMES,
    OperationFailed,
    WriteOperationCoordinator,
    WriteOperationError,
    WriteOperationRepository,
    compensation_operation_id,
    load_or_create_ledger_key,
)
from offerpilot.db import init_database
from offerpilot.repositories.application_events import ApplicationEventsRepository
from offerpilot.repositories.applications import ApplicationCreate, ApplicationsRepository
from offerpilot.repositories.chat import ChatRepository
from offerpilot.repositories.jd import JDAnalysesRepository
from offerpilot.repositories.notes import NotesRepository
from offerpilot.repositories.offers import OffersRepository
from offerpilot.repositories.resumes import ResumesRepository


def test_write_operation_manifests_are_exact() -> None:
    assert frozenset(TYPED_WRITE_OPERATION_NAMES) == TRANSACTIONAL_TYPED_WRITE_NAMES
    assert len(TYPED_WRITE_OPERATION_NAMES) == 12
    assert LEGACY_WRITE_OPERATION_NAMES == (
        "save_application_jd_version",
        "create_application_submission_snapshot",
        "record_application_outcome",
    )
    assert COMPENSATION_OPERATION_NAMES == (
        "undo:update_application_status",
        "undo:create_application",
        "undo:create_application_event",
        "undo:add_note",
    )
    assert REQUIRED_UNDO_OPERATION_NAMES == REQUIRED_UNDO_TOOL_NAMES


@pytest.mark.parametrize(
    ("kind", "expected"),
    (
        ("undo:update_application_status", "f5cb2151-0014-5ac3-b392-01cb650c67af"),
        ("undo:create_application", "007fcd71-31a0-5489-a474-9fe0ab59bb90"),
        ("undo:create_application_event", "920dc6a7-e9b8-5484-8749-9a1cf37b1b06"),
        ("undo:add_note", "9d8c2d9c-8a14-5e26-bad1-9fd5fb5ef73c"),
    ),
)
def test_compensation_operation_id_matches_design_golden(kind: str, expected: str) -> None:
    parent = "00000000-0000-4000-8000-000000000001"
    assert compensation_operation_id(parent, kind) == expected


def test_ledger_key_is_independent_and_missing_key_fails_closed(tmp_path) -> None:
    sessions = init_database(tmp_path / "offerpilot.db")
    key = load_or_create_ledger_key(tmp_path, sessions)
    repository = WriteOperationRepository(sessions, key)
    chat = ChatRepository(sessions, repository)
    conversation = chat.create_conversation("workspace", "", "general")
    pending = PendingAction(
        tool_call_id="write-1",
        tool_name="update_application_status",
        args='{"id":1,"status":"offer"}',
        human="update",
        operation_id=str(uuid4()),
    )
    assert chat.persist_pending_action(conversation.id, pending, [])

    key_path = tmp_path / LEDGER_KEY_FILENAME
    key_path.unlink()
    with pytest.raises(WriteOperationError, match="operation_unavailable"):
        load_or_create_ledger_key(tmp_path, sessions)


def test_mapped_domain_failure_rolls_back_executor_savepoint(tmp_path) -> None:
    sessions = init_database(tmp_path / "offerpilot.db")
    key = load_or_create_ledger_key(tmp_path, sessions)
    repository = WriteOperationRepository(sessions, key)
    chat = ChatRepository(sessions, repository)
    conversation = chat.create_conversation("workspace", "", "general")
    operation_id = str(uuid4())
    pending = PendingAction(
        tool_call_id="write-savepoint",
        tool_name="create_application",
        args="{}",
        human="create",
        operation_id=operation_id,
    )
    assert chat.persist_pending_action(conversation.id, pending, [])

    applications = ApplicationsRepository(sessions)
    events = ApplicationEventsRepository(sessions)
    notes = NotesRepository(sessions)
    offers = OffersRepository(sessions)
    resumes = ResumesRepository(sessions)
    context = ToolExecutionContext(
        capabilities=frozenset({ToolCapability.APPLICATIONS_WRITE}),
        current_bindings={},
        applications=applications,
        events=events,
        notes=notes,
        offers=offers,
        resumes=resumes,
        jd_analyses=JDAnalysesRepository(sessions),
        run_recorder=NullRunRecorder(),
    )
    parameters = {"type": "object", "properties": {}}
    contract = ProviderToolContract(
        payload={
            "type": "function",
            "function": {
                "name": "create_application",
                "description": "create",
                "parameters": parameters,
            },
        },
        name="create_application",
        description="create",
        parameters=parameters,
    )

    def mutate_then_fail(_args, bound_context):
        bound_context.applications.create(ApplicationCreate("partial", "write"))
        raise ValueError("conflict")

    spec = ToolSpec(
        contract=contract,
        kind="write",
        decoder=lambda values: values,
        executor=mutate_then_fail,
        confirmation_policy="required",
        exception_map=(ToolExceptionMapping(ValueError, "conflict", "domain_conflict"),),
        write_contract=WriteContract(),
    )
    prepared = PreparedToolCall(
        tool_call_id=pending.tool_call_id,
        spec=spec,
        arguments={},
        typed_args={},
        arguments_digest="sha256:args",
        contract_fingerprint="sha256:contract",
        binding=BindingAudit("unbound", 0),
    )
    authorization = ExecutionAuthorization(
        pending_identity=object(),
        pending_action_revision=1,
        tool_call_id=pending.tool_call_id,
        tool_name=pending.tool_name,
        arguments_digest=prepared.arguments_digest,
        operation_id=operation_id,
    )

    execution, record = WriteOperationCoordinator(repository).execute_primary(
        operation_id=operation_id,
        conversation_id=conversation.id,
        prepared=prepared,
        context=context,
        authorization=authorization,
        request_fingerprint="hmac-sha256:" + "a" * 64,
    )

    assert isinstance(execution, OperationFailed)
    assert record is not None
    assert applications.list() == []
