import os
from datetime import datetime, timedelta, timezone
from time import perf_counter
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..auth.backend import current_user
from ..auth.models import User
from ..database import get_db
from ..model import (
    ChatHistory,
    ChatMessage,
    ChatMessageGraphJob,
    ChatMessageMap,
    ChatMessageQuickReplies,
    ChatQueryState,
)
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
    GraphEvidenceRead,
)
from ..services.chatbot.graph_jobs import graph_status, start_graph_job
from ..services.chatbot.pipeline import (
    AssistantTurn,
    assess_query_guardrails,
    format_conversation_context,
    generate_assistant_response,
    get_response_budget_seconds,
)
from ..services.chatbot.preflight_token import (
    create_guardrail_token,
    verify_guardrail_token,
)
from ..services.chatbot.titles import (
    GENERIC_TITLES,
    create_temporary_chat_title,
    generated_title,
)
from ..services.shared.diagnostics import log_request_timing, log_timing, timing_token_fields, trace_request
from ..services.shared.messages import response as user_response

# Every route needs a verified user and only sees that user's chats.
router = APIRouter(prefix="/chats", tags=["chats"])
TITLE_GENERATED = "title_generated"


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


def format_date(value: datetime) -> str:
    return to_display_time(value).strftime("%d %b %Y")


def format_time(value: datetime) -> str:
    return to_display_time(value).strftime("%I:%M %p").lstrip("0")


def serialize_message(message: ChatMessage):
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
        "mapData": message.map_snapshot.data if message.map_snapshot else None,
        "graphData": message.graph_snapshot.data if message.graph_snapshot else None,
        "graphStatus": graph_status(message),
        "quickReplies": message.quick_replies.replies if message.quick_replies else [],
    }


def get_ordered_messages(chat: ChatHistory) -> list[ChatMessage]:
    # Older user/assistant pairs can share a timestamp; ids keep insertion order, so they break ties everywhere.
    return sorted(
        chat.messages,
        key=lambda message: (message.created_at, message.id),
    )


def get_session_timestamp(chat: ChatHistory) -> datetime:
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


def get_chat_or_404(db: Session, chat_id: int, user_id: int) -> ChatHistory:
    # Another user's chat is reported as not found, so chat ids reveal nothing.
    chat = db.scalar(
        select(ChatHistory)
        .where(ChatHistory.id == chat_id, ChatHistory.user_id == user_id)
        .options(
            selectinload(ChatHistory.messages).selectinload(ChatMessage.map_snapshot),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.quick_replies),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.graph_snapshot),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.graph_job),
            selectinload(ChatHistory.query_state),
        )
    )
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=user_response("interface.chat_not_found"),
        )
    return chat


def title_generated(chat: ChatHistory | None) -> bool:
    return bool(chat and chat.query_state and chat.query_state.state.get(TITLE_GENERATED))


def title_needed(chat: ChatHistory, first_turn: bool) -> bool:
    if title_generated(chat):
        return False
    if first_turn:
        return True
    first_question = next((m.content for m in get_ordered_messages(chat) if m.role == "user"), "")
    return chat.title == create_temporary_chat_title(first_question) or chat.title in GENERIC_TITLES


def build_llm_messages(
    chat: ChatHistory,
    user_text: str | None = None,
) -> list[dict[str, str]]:
    messages = []

    for message in get_ordered_messages(chat):
        messages.append(
            {
                "role": "assistant" if message.role == "assistant" else "user",
                "content": message.content,
            }
        )

    if user_text is not None:
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
def list_chat_histories(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChatListResponse:
    session_timestamp = (
        select(ChatMessage.created_at)
        .where(ChatMessage.chat_id == ChatHistory.id, ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.asc())
        .limit(1)
        .scalar_subquery()
    )
    chats = db.scalars(
        select(ChatHistory)
        .where(ChatHistory.user_id == user.id)
        .options(
            selectinload(ChatHistory.messages).selectinload(ChatMessage.map_snapshot),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.quick_replies),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.graph_snapshot),
            selectinload(ChatHistory.messages).selectinload(ChatMessage.graph_job),
        )
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
    user: User = Depends(current_user),
) -> ChatRead:
    title = payload.title.strip() if payload.title else "New Chat"
    chat = ChatHistory(title=title, user_id=user.id)

    db.add(chat)
    db.commit()
    db.refresh(chat)

    return serialize_chat(chat)


@router.post("/preflight", response_model=ChatPreflightResponse)
@trace_request
def preflight_message(
    payload: ChatPreflightRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChatPreflightResponse:
    preflight_started_at = perf_counter()
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=user_response("interface.empty_message"),
        )

    chat = get_chat_or_404(db, payload.chat_id, user.id) if payload.chat_id else None
    prior_messages = build_llm_messages(chat) if chat else []
    decision = assess_query_guardrails(user_text, format_conversation_context(prior_messages))
    response = ChatPreflightResponse(
        status=decision.status,
        isFnb=decision.scope in {"fnb_customer", "fnb_analyst"},
        scope=decision.scope,
        message=decision.message,
        locationRequired=decision.location_required,
        detectedLocation=decision.detected_location,
        traceId=timing_token_fields()["trace_id"],
        decisionToken=create_guardrail_token(user_text, payload.chat_id, decision),
    )
    log_timing(
        "chat.preflight.total",
        preflight_started_at,
        decision=decision.status,
    )
    return response


@router.get("/{chat_id}", response_model=ChatRead)
def get_chat_history(
    chat_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChatRead:
    return serialize_chat(get_chat_or_404(db, chat_id, user.id))


@router.post("/messages", response_model=ChatSendResponse)
@trace_request
def send_message(
    payload: ChatSendRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChatSendResponse:
    send_started_at = perf_counter()
    user_text = payload.message.strip()
    if not user_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=user_response("interface.empty_message"),
        )

    guardrail_started_at = perf_counter()
    prior_chat = get_chat_or_404(db, payload.chat_id, user.id) if payload.chat_id else None
    preflight_decision = verify_guardrail_token(payload.preflight_token, user_text, payload.chat_id)
    guardrail_source = "token"
    if not preflight_decision:
        guardrail_source = "reassessed"
        prior_messages = build_llm_messages(prior_chat) if prior_chat else []
        preflight_decision = assess_query_guardrails(user_text, format_conversation_context(prior_messages))
    log_timing(
        "chat.send.guardrails",
        guardrail_started_at,
        total_started_at=send_started_at,
        source=guardrail_source,
        decision=preflight_decision.status,
    )

    session_title = create_temporary_chat_title(user_text)
    first_turn = not payload.chat_id or not prior_chat.messages
    if payload.chat_id:
        chat = prior_chat
        if not chat.messages:
            chat.title = session_title
    else:
        chat = ChatHistory(title=session_title, user_id=user.id)
    wants_title = title_needed(chat, first_turn)

    llm_messages = build_llm_messages(chat, user_text)
    now = datetime.now(timezone.utc)

    generation_started_at = perf_counter()
    generation_status = "success"
    try:
        turn = generate_assistant_response(
            llm_messages,
            build_location_context(payload),
            payload.location_permission_denied,
            preflight_decision,
            deadline=send_started_at + get_response_budget_seconds(),
            title_needed=wants_title,
        )
    except Exception as exc:
        generation_status = "error"
        print(f"Assistant response generation failed: {exc}", flush=True)
        turn = AssistantTurn(user_response("errors.unexpected"))
    title = generated_title(turn.chat_title, user_text) if wants_title else None
    if title:
        chat.title = title
    log_timing(
        "chat.send.generation",
        generation_started_at,
        status=generation_status,
        total_started_at=send_started_at,
    )
    log_request_timing("chat.request.answer_ready", status=generation_status)

    assistant_created_at = max(
        datetime.now(timezone.utc),
        now + timedelta(microseconds=1),
    )

    persist_started_at = perf_counter()
    if not payload.chat_id:
        db.add(chat)
        db.flush()

    user_message = ChatMessage(
        chat_id=chat.id,
        role="user",
        content=user_text,
        created_at=now,
    )
    assistant_message = ChatMessage(
        chat_id=chat.id,
        role="assistant",
        content=turn.answer,
        map_snapshot=ChatMessageMap(data=turn.map_data) if turn.map_data is not None else None,
        graph_job=ChatMessageGraphJob(status="pending") if turn.build_graph else None,
        quick_replies=ChatMessageQuickReplies(replies=turn.quick_replies) if turn.quick_replies else None,
        created_at=assistant_created_at,
    )

    if title:
        if chat.query_state:
            chat.query_state.state = {**chat.query_state.state, TITLE_GENERATED: True}
        else:
            chat.query_state = ChatQueryState(state={TITLE_GENERATED: True})

    chat.updated_at = assistant_created_at
    db.add(user_message)
    db.add(assistant_message)
    db.commit()
    db.refresh(chat)
    db.refresh(user_message)
    db.refresh(assistant_message)

    chat = get_chat_or_404(db, chat.id, user.id)
    response = ChatSendResponse(
        chat=serialize_chat(chat),
        userMessage=serialize_message(user_message),
        assistantMessage=serialize_message(assistant_message),
    )
    if turn.build_graph:
        start_graph_job(assistant_message.id, turn.build_graph)
    log_timing(
        "chat.send.persist",
        persist_started_at,
        total_started_at=send_started_at,
    )
    log_timing(
        "chat.send.total",
        send_started_at,
        status="degraded" if generation_status == "error" else "success",
    )
    log_request_timing("chat.request.total", status="degraded" if generation_status == "error" else "success")
    return response


@router.get("/{chat_id}/messages/{message_id}/graph", response_model=GraphEvidenceRead)
def get_graph_evidence(
    chat_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> GraphEvidenceRead:
    message = db.scalar(
        select(ChatMessage)
        .join(ChatHistory)
        .where(ChatMessage.id == message_id, ChatMessage.chat_id == chat_id, ChatHistory.user_id == user.id)
        .options(selectinload(ChatMessage.graph_snapshot), selectinload(ChatMessage.graph_job))
    )
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=user_response("interface.chat_not_found"),
        )
    return GraphEvidenceRead(
        graphStatus=graph_status(message),
        graphData=message.graph_snapshot.data if message.graph_snapshot else None,
    )


@router.patch("/{chat_id}/title", response_model=ChatRead)
def rename_chat_history(
    chat_id: int,
    payload: ChatRenameRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> ChatRead:
    title = payload.title.strip()
    if not title:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=user_response("interface.empty_title"),
        )

    chat = get_chat_or_404(db, chat_id, user.id)
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
    user: User = Depends(current_user),
) -> ChatRead:
    chat = get_chat_or_404(db, chat_id, user.id)
    chat.pinned = payload.pinned
    chat.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(chat)

    return serialize_chat(chat)


@router.delete("/{chat_id}", response_model=DeleteChatResponse)
def delete_chat_history(
    chat_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> DeleteChatResponse:
    chat = get_chat_or_404(db, chat_id, user.id)

    db.delete(chat)
    db.commit()

    return DeleteChatResponse(deleted=True, chatId=chat_id)
