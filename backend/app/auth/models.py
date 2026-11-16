from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTable,
    SQLAlchemyBaseUserTable,
)
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTable
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.database import AuthBase as Base

# Tables are created by the SQL files in db/migrations/, not by SQLAlchemy.
USER_FK = "auth.users.user_id"


class OAuthAccount(SQLAlchemyBaseOAuthAccountTable[int], Base):
    __tablename__ = "oauth_account"
    __table_args__ = {"schema": "auth"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)

    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey(USER_FK, ondelete="cascade"), nullable=False)


class User(SQLAlchemyBaseUserTable[int], Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: Mapped[int] = mapped_column("user_id", Integer, primary_key=True)
    hashed_password: Mapped[str] = mapped_column("password", Text, nullable=False)
    username: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    # A link to the profile picture; empty means the frontend shows its default image.
    profile_picture_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")


# A picture uploaded on the website (db/migrations/025_user_picture.sql), one per user.
class UserPicture(Base):
    __tablename__ = "user_picture"
    __table_args__ = {"schema": "auth"}

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey(USER_FK, ondelete="cascade"), primary_key=True
    )
    image: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccessToken(SQLAlchemyBaseAccessTokenTable[int], Base):
    __tablename__ = "access_token"
    __table_args__ = {"schema": "auth"}

    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey(USER_FK, ondelete="cascade"), nullable=False)
