from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from offerpilot.ai.agent import PendingAction
from offerpilot.models import ChatMessage, Conversation


class ChatRepository:
    def __init__(self, session_factory: sessionmaker[Session]):
        self._session_factory = session_factory

    def create_conversation(self, title: str, mode: str = "general", offer_id: int | None = None) -> Conversation:
        conversation = Conversation(title=title, mode=mode, offer_id=offer_id)
        with self._session_factory() as session:
            session.add(conversation)
            session.commit()
            session.refresh(conversation)
            return conversation

    def get_conversation(self, conversation_id: int) -> Conversation | None:
        with self._session_factory() as session:
            return session.get(Conversation, conversation_id)

    def list_conversations(self) -> list[Conversation]:
        statement = select(Conversation).order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        with self._session_factory() as session:
            return list(session.scalars(statement))

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

    def delete_conversation(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
            session.commit()
