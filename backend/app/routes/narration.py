# The Cinematic AI tour's spoken explanations. A line already made is served from the database for free;
# a new one is made by the speech service, within a per-user limit since each costs money.

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..auth.backend import current_user
from ..auth.models import User
from ..database import get_db
from ..model import NarrationAudio
from ..rate_limit import RateLimiter, wait_text
from ..services.shared.messages import response as user_response
from ..services.shared.speech import MAX_NARRATION_CHARACTERS, SpeechError, narration_key, speech_settings, synthesise

router = APIRouter(prefix="/narration", tags=["narration"])

narration_limiter = RateLimiter(((config.NARRATION_LIMIT_PER_HOUR, 60 * 60), (config.NARRATION_LIMIT_PER_DAY, 24 * 60 * 60)))
# Saved lines never change, so the browser may keep them too.
AUDIO_HEADERS = {"Cache-Control": "private, max-age=86400"}


class NarrationRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_NARRATION_CHARACTERS)

    @field_validator("text")
    @classmethod
    def tidy(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError(user_response("interface.empty_message"))
        return value


@router.post("", response_class=Response)
def narrate(payload: NarrationRequest, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Response:
    settings = speech_settings()
    key = narration_key(payload.text, settings)
    saved = db.get(NarrationAudio, key)
    if saved:
        return Response(saved.audio, media_type="audio/mpeg", headers={**AUDIO_HEADERS, "X-Narration": "saved"})

    wait = narration_limiter.hit(f"user:{user.id}")
    if wait:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, headers={"Retry-After": str(wait)},
                            detail=user_response("interface.narration_limited", wait=wait_text(wait)))
    try:
        audio = synthesise(payload.text, settings)
    except SpeechError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=user_response("interface.narration_unavailable")) from exc
    db.add(NarrationAudio(key=key, audio=audio))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # Another request saved the same line first.
    return Response(audio, media_type="audio/mpeg", headers={**AUDIO_HEADERS, "X-Narration": "new"})
