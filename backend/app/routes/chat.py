# Chat API routes: list, save, rename, pin, and delete chat histories.
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..database import get_db
from ..model import ChatHistory, ChatMessage
from ..schemas import (
    ChatCreate,
    ChatListResponse,
    ChatPinRequest,
    ChatRead,
    ChatRenameRequest,
    ChatSendRequest,
    ChatSendResponse,
    DeleteChatResponse,
)
from ..services.openai_service import generate_assistant_response, generate_chat_title


router = APIRouter(prefix="/chats", tags=["chats"])


def create_chat_title(message: str) -> str:
    # Delegates title generation to OpenAI, with fallback handled in the service.
    return generate_chat_title(message)


def format_date(value: datetime) -> str:
    # Format used by the sidebar history item.
    return value.strftime("%d %b %Y")


def format_time(value: datetime) -> str:
    # Remove leading zero so the UI shows "9:30 AM" instead of "09:30 AM".
    return value.strftime("%I:%M %p").lstrip("0")


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


def get_session_timestamp(chat: ChatHistory) -> datetime:
    # The sidebar timestamp represents when the session started: the first user query.
    first_user_message = next(
        (message for message in chat.messages if message.role == "user"),
        None,
    )
    if first_user_message:
        return first_user_message.created_at

    first_message = chat.messages[0] if chat.messages else None
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
        messages=[serialize_message(message) for message in chat.messages],
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


def build_openai_messages(chat: ChatHistory, user_text: str) -> list[dict[str, str]]:
    # Rebuild prior turns so OpenAI receives context for the selected chat only.
    messages = []

    for message in chat.messages:
        messages.append(
            {
                "role": "assistant" if message.role == "assistant" else "user",
                "content": message.content,
            }
        )

    messages.append({"role": "user", "content": user_text})
    return messages


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
            chat.title = create_chat_title(user_text)
    else:
        # New draft chat: persist the session only when the first query is sent.
        chat = ChatHistory(title=create_chat_title(user_text))
        db.add(chat)
        db.flush()

    answer, map_image = generate_assistant_response(
        build_openai_messages(chat, user_text)
    )
    now = datetime.now(timezone.utc)

    user_message = ChatMessage(
        chat_id=chat.id,
        role="user",
        content=user_text,
        created_at=now,
    )
    assistant_message = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=answer,
        map_image=map_image,
        created_at=now,
    )

    chat.updated_at = now
    db.add_all([user_message, assistant_message])
    db.commit()

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
