from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.agent import PendingAction
from offerpilot.ai.types import Message
from offerpilot.models import ChatMessage, Conversation


class ChatRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_conversation(
        self,
        title: str,
        mode: str = "general",
        context_type: str = "workspace",
        context_ref: str = "",
    ) -> Conversation:
        conversation = Conversation(
            title=title,
            mode=mode,
            context_type=context_type or "workspace",
            context_ref=context_ref or "",
        )
        with self._session_factory() as session:
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        with self._session_factory() as session:
            return session.get(Conversation, conversation_id)

    def list_conversations(self, include_archived: bool = False) -> list[Conversation]:
        statement = select(Conversation)
        if not include_archived:
            statement = statement.where(Conversation.archived_at.is_(None))
        statement = statement.order_by(
            Conversation.pinned_at.is_(None).asc(),
            Conversation.pinned_at.desc(),
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def update_conversation(
        self, conversation_id: int, values: dict[str, Any]
    ) -> Conversation | None:
        if not values:
            return self.get_conversation(conversation_id)
        with self._session_factory() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None
            for key, value in values.items():
                setattr(conversation, key, value)
            conversation.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(conversation)
            return conversation

    def append_message(
        self,
        conversation_id: int,
        role: str,
        content: str = "",
        tool_calls: str = "",
        tool_call_id: str = "",
        provider_blocks: str = "",
    ) -> ChatMessage:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
            provider_blocks=provider_blocks,
        )
        with self._session_factory() as session:
            session.add(message)
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(updated_at=datetime.now(timezone.utc))
            )
            session.commit()
            session.refresh(message)
            return message

    def list_messages(self, conversation_id: int) -> list[ChatMessage]:
        statement = (
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.id.asc())
        )
        with self._session_factory() as session:
            return list(session.scalars(statement))

    def get_pending_action(self, conversation_id: int) -> PendingAction | None:
        with self._session_factory() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or not conversation.pending_tool_name:
                return None
            return PendingAction(
                tool_call_id=conversation.pending_tool_call_id,
                tool_name=conversation.pending_tool_name,
                args=conversation.pending_args,
                human=conversation.pending_human or conversation.pending_tool_name,
            )

    def set_pending_action(self, conversation_id: int, pending: PendingAction) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    pending_tool_call_id=pending.tool_call_id,
                    pending_tool_name=pending.tool_name,
                    pending_args=pending.args,
                    pending_human=pending.human,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def set_pending_action_if_empty(
        self,
        conversation_id: int,
        pending: PendingAction,
    ) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(Conversation.pending_tool_name == "")
                .values(
                    pending_tool_call_id=pending.tool_call_id,
                    pending_tool_name=pending.tool_name,
                    pending_args=pending.args,
                    pending_human=pending.human,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            return getattr(result, "rowcount", 0) == 1

    def persist_chained_confirmation_if_empty(
        self,
        conversation_id: int,
        pending: PendingAction,
        messages: list[dict[str, str]],
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(Conversation.pending_tool_name == "")
                .where(Conversation.clarification_tool_name == "")
                .values(
                    pending_tool_call_id=pending.tool_call_id,
                    pending_tool_name=pending.tool_name,
                    pending_args=pending.args,
                    pending_human=pending.human,
                    clarification_tool_call_id="",
                    clarification_tool_name="",
                    clarification_args="",
                    clarification_human="",
                    clarification_question="",
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                session.rollback()
                return False
            for message in messages:
                session.add(
                    ChatMessage(
                        conversation_id=conversation_id,
                        role=message.get("role", ""),
                        content=message.get("content", ""),
                        tool_calls=message.get("tool_calls", ""),
                        tool_call_id=message.get("tool_call_id", ""),
                        provider_blocks=message.get("provider_blocks", ""),
                    )
                )
            session.commit()
            return True

    def persist_confirmation_clarification_if_empty(
        self,
        conversation_id: int,
        pending: PendingAction,
        question: str,
        messages: list[dict[str, str]],
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(Conversation.pending_tool_name == "")
                .where(Conversation.clarification_tool_name == "")
                .values(
                    pending_tool_call_id="",
                    pending_tool_name="",
                    pending_args="",
                    pending_human="",
                    clarification_tool_call_id=pending.tool_call_id,
                    clarification_tool_name=pending.tool_name,
                    clarification_args=pending.args,
                    clarification_human=pending.human,
                    clarification_question=question,
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                session.rollback()
                return False
            for message in messages:
                session.add(
                    ChatMessage(
                        conversation_id=conversation_id,
                        role=message.get("role", ""),
                        content=message.get("content", ""),
                        tool_calls=message.get("tool_calls", ""),
                        tool_call_id=message.get("tool_call_id", ""),
                        provider_blocks=message.get("provider_blocks", ""),
                    )
                )
            session.commit()
            return True

    def clear_pending_action(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    pending_tool_call_id="",
                    pending_tool_name="",
                    pending_args="",
                    pending_human="",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def resolve_pending_confirmation(
        self,
        conversation_id: int,
        expected: PendingAction,
        tool_message: Message,
        undo: dict[str, Any],
    ) -> bool:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session:
            result = session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(Conversation.pending_tool_call_id == expected.tool_call_id)
                .where(Conversation.pending_tool_name == expected.tool_name)
                .where(Conversation.pending_args == expected.args)
                .values(
                    pending_tool_call_id="",
                    pending_tool_name="",
                    pending_args="",
                    pending_human="",
                    clarification_tool_call_id="",
                    clarification_tool_name="",
                    clarification_args="",
                    clarification_human="",
                    clarification_question="",
                    last_write_undo_json=(json.dumps(undo, ensure_ascii=False) if undo else ""),
                    updated_at=now,
                )
            )
            if getattr(result, "rowcount", 0) != 1:
                session.rollback()
                return False
            session.add(
                ChatMessage(
                    conversation_id=conversation_id,
                    role=tool_message.role,
                    content=tool_message.content,
                    tool_call_id=tool_message.tool_call_id,
                )
            )
            session.commit()
            return True

    def get_pending_clarification(self, conversation_id: int) -> tuple[PendingAction, str] | None:
        with self._session_factory() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or not conversation.clarification_tool_name:
                return None
            return (
                PendingAction(
                    tool_call_id=conversation.clarification_tool_call_id,
                    tool_name=conversation.clarification_tool_name,
                    args=conversation.clarification_args,
                    human=conversation.clarification_human or conversation.clarification_tool_name,
                ),
                conversation.clarification_question,
            )

    def set_pending_clarification(
        self,
        conversation_id: int,
        pending: PendingAction,
        question: str,
    ) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    clarification_tool_call_id=pending.tool_call_id,
                    clarification_tool_name=pending.tool_name,
                    clarification_args=pending.args,
                    clarification_human=pending.human,
                    clarification_question=question,
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def clear_pending_clarification(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    clarification_tool_call_id="",
                    clarification_tool_name="",
                    clarification_args="",
                    clarification_human="",
                    clarification_question="",
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def get_last_write_undo(self, conversation_id: int) -> dict[str, Any] | None:
        with self._session_factory() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None or not conversation.last_write_undo_json:
                return None
            try:
                payload = json.loads(conversation.last_write_undo_json)
            except json.JSONDecodeError:
                return None
            return payload if isinstance(payload, dict) else None

    def set_last_write_undo(self, conversation_id: int, undo: dict[str, Any]) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(
                    last_write_undo_json=json.dumps(undo, ensure_ascii=False),
                    updated_at=datetime.now(timezone.utc),
                )
            )
            session.commit()

    def clear_last_write_undo(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(last_write_undo_json="", updated_at=datetime.now(timezone.utc))
            )
            session.commit()

    def clear_last_write_undo_if_matches(
        self,
        conversation_id: int,
        expected: dict[str, Any],
    ) -> bool:
        with self._session_factory() as session:
            result = session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .where(
                    Conversation.last_write_undo_json == json.dumps(expected, ensure_ascii=False)
                )
                .values(last_write_undo_json="", updated_at=datetime.now(timezone.utc))
            )
            session.commit()
            return getattr(result, "rowcount", 0) == 1

    def delete_conversation(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id)
            )
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
            session.commit()
