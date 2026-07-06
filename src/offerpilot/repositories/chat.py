from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

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
    ) -> ChatMessage:
        message = ChatMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
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

    def delete_conversation(self, conversation_id: int) -> None:
        with self._session_factory() as session:
            session.execute(delete(ChatMessage).where(ChatMessage.conversation_id == conversation_id))
            conversation = session.get(Conversation, conversation_id)
            if conversation is not None:
                session.delete(conversation)
            session.commit()
