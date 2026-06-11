# Database tables for chat sessions and their user/assistant messages.
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ChatHistory(Base):
    # Stores one chat session shown in the sidebar history.
    __tablename__ = "chat_histories"

    # Basic session metadata.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # created_at is when the session row was created; updated_at changes on edits/messages.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )

    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="chat",
        # Deleting a chat should remove its full user/assistant conversation.
        cascade="all, delete-orphan",
        passive_deletes=True,
        # ID resolves ties for older user/assistant pairs that share a timestamp.
        order_by=lambda: (ChatMessage.created_at, ChatMessage.id),
    )


class ChatMessage(Base):
    # Stores one message inside a chat session.
    __tablename__ = "chat_messages"

    # chat_id links the message back to its parent chat session.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat_histories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # role is "user" for user queries and "assistant" for AI/system replies.
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Optional map preview image shown for assistant responses.
    map_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Lets SQLAlchemy navigate from a message back to its chat.
    chat: Mapped[ChatHistory] = relationship("ChatHistory", back_populates="messages")
