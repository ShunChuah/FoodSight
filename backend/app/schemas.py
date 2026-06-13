# API request/response shapes shared by FastAPI routes and the React frontend.
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


MAX_MESSAGE_WORDS = 1000
MAX_MESSAGE_CHARACTERS = 5000
ScopeType = Literal["fnb_customer", "fnb_analyst"]
GuardrailStatus = Literal[
    "ready",
    "clarification_required",
    "unsupported",
    "out_of_scope",
]


class ChatMessageInput(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_CHARACTERS,
    )

    @field_validator("message")
    @classmethod
    def validate_message_words(cls, value: str) -> str:
        if len(value.split()) > MAX_MESSAGE_WORDS:
            raise ValueError(
                f"Message cannot exceed {MAX_MESSAGE_WORDS} words."
            )
        return value


class ChatCreate(BaseModel):
    # Optional title for manually creating an empty chat session.
    title: str | None = Field(default=None, max_length=160)


class ChatSendRequest(ChatMessageInput):
    # chat_id is null for a draft new chat; backend creates the session on send.
    chat_id: int | None = None
    location_name: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    location_permission_denied: bool = False
    preflight_token: str | None = Field(default=None, max_length=12000)


class ChatPreflightRequest(ChatMessageInput):
    chat_id: int | None = None


class ChatPreflightResponse(BaseModel):
    status: GuardrailStatus
    isFnb: bool
    scope: ScopeType | None = None
    message: str | None = None
    locationRequired: bool
    detectedLocation: str | None = None
    decisionToken: str


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
