from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .services.shared.messages import response


MAX_MESSAGE_WORDS = 1000
MAX_MESSAGE_CHARACTERS = 5000
ScopeType = Literal["fnb_customer", "fnb_analyst"]
GuardrailStatus = Literal["ready", "unsupported", "out_of_scope"]
GraphStatus = Literal["pending", "ready", "failed"]


class ChatMessageInput(BaseModel):
    message: str = Field(
        ...,
        min_length=1,
        max_length=MAX_MESSAGE_CHARACTERS,
    )

    @field_validator("message", mode="before")
    @classmethod
    def validate_message_words(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        if not value.strip():
            raise ValueError(response("interface.empty_message"))
        if len(value.split()) > MAX_MESSAGE_WORDS:
            raise ValueError(
                response("interface.message_limit", maximum=f"{MAX_MESSAGE_WORDS:,}")
            )
        if len(value) > MAX_MESSAGE_CHARACTERS:
            raise ValueError(f"Your message is too long. Please keep it under {MAX_MESSAGE_CHARACTERS:,} characters.")
        return value


class ChatCreate(BaseModel):
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
    traceId: str | None = None
    traceId: str | None = None


class ChatRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)

    @field_validator("title", mode="before")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if isinstance(value, str) and not value.strip():
            raise ValueError(response("interface.empty_title"))
        return value


class ChatPinRequest(BaseModel):
    pinned: bool


class ChatMessageRead(BaseModel):
    id: int
    type: Literal["user", "assistant"]
    text: str | None = None
    answer: str | None = None
    mapImage: str | None = None
    mapData: dict | None = None
    graphData: dict | None = None
    # None when the answer has no graph evidence; "pending" while it is built after the answer was sent.
    graphStatus: GraphStatus | None = None
    quickReplies: list[str] = Field(default_factory=list)
    createdAt: datetime


class ChatRead(BaseModel):
    id: int
    title: str
    date: str
    time: str
    pinned: bool
    createdAt: datetime
    updatedAt: datetime
    messages: list[ChatMessageRead] = Field(default_factory=list)


class ChatListResponse(BaseModel):
    chats: list[ChatRead]


class ChatSendResponse(BaseModel):
    chat: ChatRead
    userMessage: ChatMessageRead
    assistantMessage: ChatMessageRead


class GraphEvidenceRead(BaseModel):
    graphStatus: GraphStatus | None = None
    graphData: dict | None = None


class DeleteChatResponse(BaseModel):
    deleted: bool
    chatId: int


ThemeName = Literal["light", "dark"]


class PreferencesRead(BaseModel):
    # None until the user has picked a theme; the browser keeps its current one.
    theme: ThemeName | None = None


class PreferencesUpdate(BaseModel):
    theme: ThemeName
