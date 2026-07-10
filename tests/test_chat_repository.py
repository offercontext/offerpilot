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

    assert resolved is True
    assert replayed is False
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

    assert resolved is False
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

    assert resolved is True
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

    assert resolved is True
    assert repo.get_last_write_undo(conversation.id) is None


def test_set_pending_action_if_empty_does_not_overwrite_newer_pending(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    newer = PendingAction("write-2", "update_application_status", '{"id":2}', "second")
    chained = PendingAction("write-3", "update_application_status", '{"id":3}', "third")
    repo.set_pending_action(conversation.id, newer)

    replaced = repo.set_pending_action_if_empty(conversation.id, chained)

    assert replaced is False
    assert repo.get_pending_action(conversation.id) == newer


def test_set_pending_action_if_empty_sets_chained_pending(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    chained = PendingAction("write-3", "update_application_status", '{"id":3}', "third")

    replaced = repo.set_pending_action_if_empty(conversation.id, chained)

    assert replaced is True
    assert repo.get_pending_action(conversation.id) == chained


def test_persist_chained_confirmation_if_empty_commits_messages_and_state_together(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    chained = PendingAction("write-3", "update_application_status", '{"id":3}', "third")
    messages = [
        {
            "role": "assistant",
            "content": "next write",
            "tool_calls": '[{"id":"write-3"}]',
            "tool_call_id": "",
            "provider_blocks": "",
        }
    ]

    persisted = repo.persist_chained_confirmation_if_empty(
        conversation.id,
        chained,
        messages,
    )

    assert persisted is True
    assert repo.get_pending_action(conversation.id) == chained
    stored = repo.list_messages(conversation.id)
    assert [(message.role, message.content, message.tool_calls) for message in stored] == [
        ("assistant", "next write", '[{"id":"write-3"}]')
    ]


def test_persist_chained_confirmation_if_empty_loses_without_partial_changes(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    newer = PendingAction("write-2", "update_application_status", '{"id":2}', "second")
    chained = PendingAction("write-3", "update_application_status", '{"id":3}', "third")
    repo.set_pending_action(conversation.id, newer)
    repo.set_pending_clarification(conversation.id, newer, "newer question")

    persisted = repo.persist_chained_confirmation_if_empty(
        conversation.id,
        chained,
        [
            {
                "role": "assistant",
                "content": "abandoned write",
                "tool_calls": '[{"id":"write-3"}]',
                "tool_call_id": "",
                "provider_blocks": "",
            }
        ],
    )

    assert persisted is False
    assert repo.get_pending_action(conversation.id) == newer
    assert repo.get_pending_clarification(conversation.id) == (newer, "newer question")
    assert repo.list_messages(conversation.id) == []


def test_persist_confirmation_clarification_if_empty_is_atomic(tmp_path):
    repo = ChatRepository(init_database(tmp_path / "data.db"))
    conversation = repo.create_conversation("confirm")
    clarification = PendingAction("write-3", "create_application", "{}", "create")
    messages = [
        {
            "role": "assistant",
            "content": "which company?",
            "tool_calls": "",
            "tool_call_id": "",
            "provider_blocks": "",
        }
    ]

    persisted = repo.persist_confirmation_clarification_if_empty(
        conversation.id,
        clarification,
        "which company?",
        messages,
    )

    assert persisted is True
    assert repo.get_pending_action(conversation.id) is None
    assert repo.get_pending_clarification(conversation.id) == (
        clarification,
        "which company?",
    )
    assert [message.content for message in repo.list_messages(conversation.id)] == [
        "which company?"
    ]


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
