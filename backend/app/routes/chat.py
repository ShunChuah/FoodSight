# Chat API routes: list, save, rename, pin, and delete chat histories.
from datetime import datetime, timedelta, timezone
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..model import ChatHistory, ChatMessage
from ..schemas import (
    ChatCreate,
    ChatListResponse,
    ChatPinRequest,
    ChatPreflightRequest,
    ChatPreflightResponse,
    ChatRead,
    ChatRenameRequest,
    ChatSendRequest,
    ChatSendResponse,
    DeleteChatResponse,
)
from ..services.chat_service import (
    assess_fnb_query,
    assess_location_requirement,
    generate_assistant_response,
    has_deterministic_fnb_signal,
)
from ..services.llm_service import generate_chat_title


router = APIRouter(prefix="/chats", tags=["chats"])


def get_display_timezone():
    configured_timezone = os.getenv("APP_TIMEZONE", "Asia/Kuala_Lumpur").strip()
    try:
        return ZoneInfo(configured_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("Asia/Kuala_Lumpur")


def to_display_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(get_display_timezone())


def create_chat_title(message: str, use_llm: bool = True) -> str:
    title = ""
    if use_llm:
        try:
            title = generate_chat_title(message).strip()
        except Exception as exc:
            print(f"Chat title generation failed: {exc}", flush=True)

    if title:
        return title[:160]

    clean_message = " ".join(message.strip().split())
    return f"{clean_message[:35]}..." if len(clean_message) > 35 else clean_message


def format_date(value: datetime) -> str:
    # Format used by the sidebar history item.
    return to_display_time(value).strftime("%d %b %Y")


def format_time(value: datetime) -> str:
    # Remove leading zero so the UI shows "9:30 AM" instead of "09:30 AM".
    return to_display_time(value).strftime("%I:%M %p").lstrip("0")


def serialize_message(message: ChatMessage):
    # Convert database rows into the shape expected by React components.
    base = {
        "id": message.id,
        "type": message.role,
        "createdAt": message.created_at,
    }

    if message.role == "user":
        return {**base, "text": message.content}

    return {
        **base,
        "answer": message.content,
        "mapImage": message.map_image,
    }


def get_ordered_messages(chat: ChatHistory) -> list[ChatMessage]:
    # Older user/assistant pairs can share the same timestamp. Their IDs preserve
    # insertion order, so use ID as a deterministic tie-breaker everywhere.
    return sorted(
        chat.messages,
        key=lambda message: (message.created_at, message.id),
    )


def get_session_timestamp(chat: ChatHistory) -> datetime:
    # The sidebar timestamp represents when the session started: the first user query.
    first_user_message = next(
        (
            message
            for message in get_ordered_messages(chat)
            if message.role == "user"
        ),
        None,
    )
    if first_user_message:
        return first_user_message.created_at

    ordered_messages = get_ordered_messages(chat)
    first_message = ordered_messages[0] if ordered_messages else None
    return first_message.created_at if first_message else chat.created_at


def serialize_chat(chat: ChatHistory) -> ChatRead:
    # Build one complete chat response, including formatted sidebar date/time.
    session_timestamp = get_session_timestamp(chat)
    updated_at = chat.updated_at or chat.created_at
    return ChatRead(
        id=chat.id,
        title=chat.title,
        date=format_date(session_timestamp),
        time=format_time(session_timestamp),
        pinned=chat.pinned,
        createdAt=chat.created_at,
        updatedAt=updated_at,
        messages=[
            serialize_message(message)
            for message in get_ordered_messages(chat)
        ],
    )


def get_chat_or_404(db: Session, chat_id: int) -> ChatHistory:
    # Shared lookup helper so each route handles missing chats consistently.
    chat = db.scalar(
        select(ChatHistory)
        .where(ChatHistory.id == chat_id)
        .options(selectinload(ChatHistory.messages))
    )
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat history not found",
        )
    return chat


def build_llm_messages(chat: ChatHistory, user_text: str) -> list[dict[str, str]]:
    # Rebuild prior turns so the LLM receives context for this chat only.
    messages = []

    for message in get_ordered_messages(chat):
        messages.append(
            {
                "role": "assistant" if message.role == "assistant" else "user",
                "content": message.content,
            }
        )

    messages.append({"role": "user", "content": user_text})
    return messages


def build_location_context(payload: ChatSendRequest) -> str:
    if payload.location_name:
        return f"User location area: {payload.location_name.strip()}"
    if payload.latitude is not None and payload.longitude is not None:
        return (
            "User browser coordinates: "
            f"latitude {payload.latitude:.6f}, longitude {payload.longitude:.6f}"
        )
    return "No location context provided."


@router.get("", response_model=ChatListResponse)
def list_chat_histories(db: Session = Depends(get_db)) -> ChatListResponse:
    # Sort pinned chats first, then newest sessions by their first user query time.
    session_timestamp = (
        select(ChatMessage.created_at)
        .where(ChatMessage.chat_id == ChatHistory.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.asc())
        .limit(1)
        .scalar_subquery()
    )
    chats = db.scalars(
        select(ChatHistory)
        .options(selectinload(ChatHistory.messages))
        .order_by(
            ChatHistory.pinned.desc(),
            session_timestamp.desc().nullslast(),
            ChatHistory.created_at.desc(),
        )
    ).all()
    return ChatListResponse(chats=[serialize_chat(chat) for chat in chats])


@router.post("", response_model=ChatRead, status_code=status.HTTP_201_CREATED)
def create_chat_history(
    payload: ChatCreate,
    db: Session = Depends(get_db),
) -> ChatRead:
    # Optional endpoint for creating an empty session before any messages exist.
    title = payload.title.strip() if payload.title else "New Chat"
    chat = ChatHistory(title=title)

    db.add(chat)
    db.commit()
    db.refresh(chat)

    return serialize_chat(chat)


@router.post("/preflight", response_model=ChatPreflightResponse)
def preflight_message(
    payload: ChatPreflightRequest,
    db: Session = Depends(get_db),
) -> ChatPreflightResponse:
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty",
        )

    chat = get_chat_or_404(db, payload.chat_id) if payload.chat_id else None
    prior_messages = build_llm_messages(chat, "")[:-1] if chat else []
    context_lines = []
    for message in prior_messages[-8:]:
        role = "Assistant" if message["role"] == "assistant" else "User"
        content = " ".join(message["content"].strip().split())
        context_lines.append(f"{role}: {content[:1200]}")
    conversation_context = (
        "\n".join(context_lines) if context_lines else "No previous conversation."
    )

    is_fnb, _ = assess_fnb_query(user_text, conversation_context)
    if not is_fnb:
        return ChatPreflightResponse(isFnb=False, locationRequired=False)

    location_required, detected_location = assess_location_requirement(
        user_text,
        conversation_context,
    )
    return ChatPreflightResponse(
        isFnb=True,
        locationRequired=location_required,
        detectedLocation=detected_location,
    )


@router.get("/{chat_id}", response_model=ChatRead)
def get_chat_history(chat_id: int, db: Session = Depends(get_db)) -> ChatRead:
    # Returns one full conversation when a history item is opened/refreshed.
    return serialize_chat(get_chat_or_404(db, chat_id))


@router.post("/messages", response_model=ChatSendResponse)
def send_message(
    payload: ChatSendRequest,
    db: Session = Depends(get_db),
) -> ChatSendResponse:
    # Saves both sides of one turn: user query first, then assistant reply.
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message cannot be empty",
        )

    if payload.chat_id:
        # Existing chat: append the new turn to that session only.
        chat = get_chat_or_404(db, payload.chat_id)
        if not chat.messages:
            chat.title = create_chat_title(
                user_text,
                use_llm=has_deterministic_fnb_signal(user_text),
            )
    else:
        # New draft chat: persist the session only when the first query is sent.
        chat = ChatHistory(
            title=create_chat_title(
                user_text,
                use_llm=has_deterministic_fnb_signal(user_text),
            )
        )
        db.add(chat)
        db.flush()

    llm_messages = build_llm_messages(chat, user_text)
    now = datetime.now(timezone.utc)

    user_message = ChatMessage(
        chat_id=chat.id,
        role="user",
        content=user_text,
        created_at=now,
    )

    # Persist the chat title and user query before any downstream AI/KG work.
    # This keeps the new session visible even when response generation fails.
    chat.updated_at = now
    db.add(user_message)
    db.commit()
    db.refresh(chat)
    db.refresh(user_message)

    try:
        answer, map_image = generate_assistant_response(
            llm_messages,
            build_location_context(payload),
            payload.location_permission_denied,
        )
    except Exception as exc:
        print(f"Assistant response generation failed: {exc}", flush=True)
        answer = (
            "I could not process this request right now. Your question and chat "
            "title were saved, so you can retry in this conversation."
        )
        map_image = None

    assistant_created_at = max(
        datetime.now(timezone.utc),
        user_message.created_at + timedelta(microseconds=1),
    )
    assistant_message = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=answer,
        map_image=map_image,
        created_at=assistant_created_at,
    )

    chat.updated_at = assistant_created_at
    db.add(assistant_message)
    db.commit()
    db.refresh(assistant_message)

    chat = get_chat_or_404(db, chat.id)
    return ChatSendResponse(
        chat=serialize_chat(chat),
        userMessage=serialize_message(user_message),
        assistantMessage=serialize_message(assistant_message),
    )


@router.patch("/{chat_id}/title", response_model=ChatRead)
def rename_chat_history(
    chat_id: int,
    payload: ChatRenameRequest,
    db: Session = Depends(get_db),
) -> ChatRead:
    # Updates only the sidebar title; conversation messages stay unchanged.
    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Title cannot be empty",
        )

    chat = get_chat_or_404(db, chat_id)
    chat.title = title
    chat.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(chat)

    return serialize_chat(chat)


@router.patch("/{chat_id}/pin", response_model=ChatRead)
def update_chat_pin(
    chat_id: int,
    payload: ChatPinRequest,
    db: Session = Depends(get_db),
) -> ChatRead:
    # Pinned chats are sorted above unpinned chats in the history list.
    chat = get_chat_or_404(db, chat_id)
    chat.pinned = payload.pinned
    chat.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(chat)

    return serialize_chat(chat)


@router.delete("/{chat_id}", response_model=DeleteChatResponse)
def delete_chat_history(
    chat_id: int,
    db: Session = Depends(get_db),
) -> DeleteChatResponse:
    # SQLAlchemy cascade removes all messages that belong to this chat.
    chat = get_chat_or_404(db, chat_id)

    db.delete(chat)
    db.commit()

    return DeleteChatResponse(deleted=True, chatId=chat_id)
