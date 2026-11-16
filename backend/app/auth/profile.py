"""The logged-in user's own account: view the profile (UC5), change the username (UC6),
change the password (UC7) and upload a profile picture."""

import time

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from fastapi_users import InvalidPasswordException
from pydantic import BaseModel
from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert

from app import config
from app.auth.backend import current_user
from app.auth.manager import get_user_manager
from app.auth.models import AccessToken, User, UserPicture
from app.auth.schemas import UserRead

router = APIRouter(prefix="/users", tags=["users"])

USERNAME_MAX = 150  # auth.users.username is varchar(150)
PICTURE_MAX_BYTES = 2 * 1024 * 1024  # also in frontend/src/components/modals/Profile.jsx


class UsernameUpdate(BaseModel):
    username: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


def picture_type(data: bytes) -> str | None:
    """The image type from the file's first bytes, so a renamed file of another kind is refused."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/me", response_model=UserRead)
async def read_current_user(user: User = Depends(current_user)):
    return user


@router.patch("/me", response_model=UserRead)
async def update_username(
    body: UsernameUpdate, user: User = Depends(current_user), user_manager=Depends(get_user_manager)
):
    username = body.username.strip()
    if not username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "USERNAME_EMPTY")
    if len(username) > USERNAME_MAX:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "USERNAME_TOO_LONG")
    return await user_manager.user_db.update(user, {"username": username})


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    request: Request,
    user: User = Depends(current_user),
    user_manager=Depends(get_user_manager),
):
    helper = user_manager.password_helper
    verified, _ = helper.verify_and_update(body.current_password, user.hashed_password)
    if not verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "CHANGE_PASSWORD_WRONG_CURRENT")
    try:
        await user_manager.validate_password(body.new_password, user)
    except InvalidPasswordException as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "CHANGE_PASSWORD_INVALID_PASSWORD", "reason": error.reason},
        )
    # Every other browser is logged out; this one keeps its session. Saved together
    # with the new password (update() commits both).
    this_session = request.cookies.get(config.COOKIE_NAME)
    await user_manager.user_db.session.execute(
        delete(AccessToken).where(AccessToken.user_id == user.id, AccessToken.token != this_session)
    )
    await user_manager.user_db.update(user, {"hashed_password": helper.hash(body.new_password)})


@router.post("/me/picture", response_model=UserRead)
async def upload_picture(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    user_manager=Depends(get_user_manager),
):
    data = await file.read(PICTURE_MAX_BYTES + 1)
    if len(data) > PICTURE_MAX_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "PICTURE_TOO_LARGE")
    content_type = picture_type(data)
    if content_type is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "PICTURE_BAD_TYPE")
    statement = insert(UserPicture).values(user_id=user.id, image=data, content_type=content_type)
    await user_manager.user_db.session.execute(
        statement.on_conflict_do_update(
            index_elements=[UserPicture.user_id],
            set_={
                "image": statement.excluded.image,
                "content_type": statement.excluded.content_type,
                "updated_at": func.now(),
            },
        )
    )
    # The path changes with every upload, so browsers load the new picture instead of
    # a cached old one. Saved together with the picture (update() commits both).
    path = f"/api/v1/users/{user.id}/picture?v={time.time_ns() // 1_000_000}"
    return await user_manager.user_db.update(user, {"profile_picture_url": path})


@router.get("/{user_id}/picture")
async def read_picture(
    user_id: int, user: User = Depends(current_user), user_manager=Depends(get_user_manager)
):
    # Only the owner sees an uploaded picture: no page shows other users.
    picture = None
    if user_id == user.id:
        picture = await user_manager.user_db.session.get(UserPicture, user_id)
    if picture is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PICTURE_NOT_FOUND")
    return Response(
        picture.image,
        media_type=picture.content_type,
        headers={
            # Safe to keep: a new upload gets a new path.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
