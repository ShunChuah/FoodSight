from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class ChatHistory(Base):
    __tablename__ = "chat_histories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Owner (auth.users.user_id). The foreign key is added by db/migrations/002_chat_owner.sql,
    # because the auth tables belong to the login models, not to this Base.
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
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
        cascade="all, delete-orphan",
        passive_deletes=True,
        # ID resolves ties for older user/assistant pairs that share a timestamp.
        order_by=lambda: (ChatMessage.created_at, ChatMessage.id),
    )
    query_state: Mapped["ChatQueryState | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False,
    )


class ChatQueryState(Base):
    """Per-chat flags kept between turns (title_generated: the model title was applied)."""

    __tablename__ = "chat_query_states"

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat_histories.id", ondelete="CASCADE"), primary_key=True,
    )
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chat_histories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # role is "user" for user queries and "assistant" for AI/system replies.
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    map_image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    chat: Mapped[ChatHistory] = relationship("ChatHistory", back_populates="messages")
    map_snapshot: Mapped["ChatMessageMap | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False,
    )
    quick_replies: Mapped["ChatMessageQuickReplies | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False,
    )
    graph_snapshot: Mapped["ChatMessageGraph | None"] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, uselist=False,
    )


class ChatMessageQuickReplies(Base):
    """Quick-reply buttons offered with an assistant message."""

    __tablename__ = "chat_message_quick_replies"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True,
    )
    replies: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class ChatMessageMap(Base):
    """Map snapshot saved with an assistant message."""

    __tablename__ = "chat_message_maps"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True,
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class ChatMessageGraph(Base):
    """Knowledge Graph Evidence ({"nodes", "edges"}) shown in View Details."""

    __tablename__ = "chat_message_graphs"

    message_id: Mapped[int] = mapped_column(
        ForeignKey("chat_messages.id", ondelete="CASCADE"), primary_key=True,
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class UserPreference(Base):
    """Per-account settings that follow the user to any browser (theme: "light" or "dark")."""

    __tablename__ = "user_preferences"

    # auth.users.user_id; the foreign key is added by db/migrations/003_user_preferences.sql.
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default="light")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
