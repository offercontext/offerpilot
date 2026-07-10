from offerpilot.ai.agent import PendingAction
from offerpilot.ai.types import Message
from offerpilot.db import init_database
from offerpilot.repositories.chat import ChatRepository


def test_resolve_pending_confirmation_atomically_persists_result_and_clears_state(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    pending = PendingAction("write-1", "update_application_status", '{"id":1}', "update")
    repo.set_pending_action(conversation.id, pending)
    repo.set_pending_clarification(conversation.id, pending, "clarify")
    repo.set_last_write_undo(conversation.id, {"kind": "previous"})
    tool_message = Message(role="tool", content='{"id":1,"status":"offer"}', tool_call_id="write-1")
    undo = {"kind": "update_application_status", "application_id": 1}

    resolved = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        tool_message,
        undo,
    )
    replayed = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        tool_message,
        undo,
    )

    assert resolved is not None
    assert replayed is None
    assert repo.get_pending_action(conversation.id) is None
    assert repo.get_pending_clarification(conversation.id) is None
    assert repo.get_last_write_undo(conversation.id) == undo
    messages = repo.list_messages(conversation.id)
    assert [(message.role, message.tool_call_id) for message in messages] == [("tool", "write-1")]


def test_resolve_pending_confirmation_cas_does_not_clear_newer_pending(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    expected = PendingAction("write-1", "update_application_status", '{"id":1}', "first")
    newer = PendingAction("write-2", "update_application_status", '{"id":2}', "second")
    repo.set_pending_action(conversation.id, newer)

    resolved = repo.resolve_pending_confirmation(
        conversation.id,
        expected,
        Message(role="tool", content='{"id":1}', tool_call_id="write-1"),
        {},
    )

    assert resolved is None
    assert repo.get_pending_action(conversation.id) == newer
    assert repo.list_messages(conversation.id) == []


def test_resolve_pending_confirmation_preserves_existing_undo(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    pending = PendingAction("write-1", "update_application_status", '{"id":1}', "update")
    previous = {"kind": "create_application", "application_id": 9}
    repo.set_pending_action(conversation.id, pending)
    repo.set_last_write_undo(conversation.id, previous)

    resolved = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        Message(role="tool", content="rejected", tool_call_id="write-1"),
        None,
    )

    assert resolved is not None
    assert repo.get_last_write_undo(conversation.id) == previous


def test_resolve_pending_confirmation_clears_existing_undo(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    pending = PendingAction("write-1", "update_application_status", '{"id":1}', "update")
    repo.set_pending_action(conversation.id, pending)
    repo.set_last_write_undo(conversation.id, {"kind": "old"})

    resolved = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        Message(role="tool", content="ambiguous failure", tool_call_id="write-1"),
        {},
    )

    assert resolved is not None
    assert repo.get_last_write_undo(conversation.id) is None


def test_clear_last_write_undo_if_matches_preserves_newer_undo(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    old = {"kind": "update_application_status", "application_id": 1}
    newer = {"kind": "create_application", "application_id": 2}
    repo.set_last_write_undo(conversation.id, newer)

    stale_clear = repo.clear_last_write_undo_if_matches(conversation.id, old)
    matching_clear = repo.clear_last_write_undo_if_matches(conversation.id, newer)

    assert stale_clear is False
    assert matching_clear is True
    assert repo.get_last_write_undo(conversation.id) is None


def test_confirmation_continuation_rejects_stale_conversation_generation(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    pending = PendingAction("write-1", "update_application_status", '{"id":1}', "first")
    repo.set_pending_action(conversation.id, pending)
    generation = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        Message(role="tool", content='{"ok":true}', tool_call_id="write-1"),
        {"kind": "undo"},
    )
    repo.append_message(conversation.id, "user", content="newer activity")
    stale_pending = PendingAction("write-2", "update_application_status", '{"id":2}', "old")

    persisted = repo.persist_confirmation_continuation(
        conversation.id,
        generation,
        [
            {
                "role": "assistant",
                "content": "stale continuation",
                "tool_calls": '[{"id":"write-2"}]',
                "tool_call_id": "",
                "provider_blocks": "",
            }
        ],
        pending=stale_pending,
    )

    assert persisted is None
    assert repo.get_pending_action(conversation.id) is None
    assert [message.content for message in repo.list_messages(conversation.id)] == [
        '{"ok":true}',
        "newer activity",
    ]


def test_confirmation_continuation_generation_is_consumed_once(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    pending = PendingAction("write-1", "update_application_status", '{"id":1}', "first")
    chained = PendingAction("write-2", "update_application_status", '{"id":2}', "second")
    repo.set_pending_action(conversation.id, pending)
    generation = repo.resolve_pending_confirmation(
        conversation.id,
        pending,
        Message(role="tool", content='{"ok":true}', tool_call_id="write-1"),
        {"kind": "undo"},
    )
    messages = [
        {
            "role": "assistant",
            "content": "next",
            "tool_calls": '[{"id":"write-2"}]',
            "tool_call_id": "",
            "provider_blocks": "",
        }
    ]

    first = repo.persist_confirmation_continuation(
        conversation.id,
        generation,
        messages,
        pending=chained,
    )
    replay = repo.persist_confirmation_continuation(
        conversation.id,
        generation,
        messages,
        pending=chained,
    )

    assert first is not None
    assert replay is None
    assert repo.get_pending_action(conversation.id) == chained
    assert [message.content for message in repo.list_messages(conversation.id)] == [
        '{"ok":true}',
        "next",
    ]
