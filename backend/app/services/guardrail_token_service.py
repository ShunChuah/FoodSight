import base64
import hashlib
import hmac
import json
import os
import time

from .chat_service import GuardrailDecision


TOKEN_TTL_SECONDS = 300


def create_guardrail_token(
    message: str,
    chat_id: int | None,
    decision: GuardrailDecision,
) -> str:
    payload = {
        "message_hash": _message_hash(message),
        "chat_id": chat_id,
        "status": decision.status,
        "scope": decision.scope,
        "message": decision.message,
        "location_required": decision.location_required,
        "detected_location": decision.detected_location,
        "query_understanding": decision.query_understanding,
        "expires_at": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    encoded_payload = _encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        _token_secret(),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_encode(signature)}"


def verify_guardrail_token(
    token: str | None,
    message: str,
    chat_id: int | None,
) -> GuardrailDecision | None:
    if not token:
        return None
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        supplied_signature = _decode(encoded_signature)
        expected_signature = hmac.new(
            _token_secret(),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None

        payload = json.loads(_decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    if payload.get("expires_at", 0) < int(time.time()):
        return None
    if payload.get("message_hash") != _message_hash(message):
        return None
    if payload.get("chat_id") != chat_id:
        return None

    status = payload.get("status")
    scope = payload.get("scope")
    if status not in {
        "ready",
        "clarification_required",
        "unsupported",
        "out_of_scope",
    }:
        return None
    if scope not in {None, "fnb_customer", "fnb_analyst"}:
        return None
    return GuardrailDecision(
        status=status,
        scope=scope,
        message=payload.get("message"),
        location_required=bool(payload.get("location_required")),
        detected_location=payload.get("detected_location"),
        query_understanding=(
            payload.get("query_understanding")
            if isinstance(payload.get("query_understanding"), dict)
            else None
        ),
    )


def _message_hash(message: str) -> str:
    normalized = " ".join(message.strip().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _token_secret() -> bytes:
    configured = os.getenv("GUARDRAIL_TOKEN_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    return b"foodsight-local-development-secret"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
