# API request/response shapes shared by FastAPI routes and the React frontend.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ChatCreate(BaseModel):
    # Optional title for manually creating an empty chat session.
    title: str | None = Field(default=None, max_length=160)


class ChatSendRequest(BaseModel):
    # chat_id is null for a draft new chat; backend creates the session on send.
    message: str = Field(..., min_length=1)
    chat_id: int | None = None


class ChatRenameRequest(BaseModel):
    # New sidebar title entered from inline rename.
    title: str = Field(..., min_length=1, max_length=160)


class ChatPinRequest(BaseModel):
    # Stores whether the chat should stay at the top of history.
    pinned: bool


class ChatMessageRead(BaseModel):
    # Frontend-friendly message shape for rendering user and assistant bubbles.
    id: int
    type: Literal["user", "assistant"]
    text: str | None = None
    answer: str | None = None
    mapImage: str | None = None
    createdAt: datetime


class ChatRead(BaseModel):
    # Full chat session returned to the frontend after list/send/rename/pin.
    id: int
    title: str
    date: str
    time: str
    pinned: bool
    createdAt: datetime
    updatedAt: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatListResponse(BaseModel):
    # Wrapper used by GET /chats.
    chats: list[ChatRead]


class ChatSendResponse(BaseModel):
    # Returned after saving one user query and one assistant response.
    chat: ChatRead
    userMessage: ChatMessageRead
    assistantMessage: ChatMessageRead


class DeleteChatResponse(BaseModel):
    # Confirms which chat was removed.
    deleted: bool
    chatId: int
