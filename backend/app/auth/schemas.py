from typing import Annotated

from fastapi_users import schemas
from pydantic import BaseModel, EmailStr, StringConstraints, field_validator

from app import config

Username = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class UserRead(schemas.BaseUser[int]):
    username: str
    profile_picture_url: str | None = None

    # An uploaded picture is saved as a path on this backend ("/api/v1/users/7/picture?v=...")
    # and sent as a full link; a Google picture is already a full link.
    @field_validator("profile_picture_url")
    @classmethod
    def full_link(cls, value):
        return f"{config.BACKEND_URL}{value}" if value and value.startswith("/") else value


class UserCreate(schemas.BaseUserCreate):
    username: Username


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    password: str
