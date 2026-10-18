from fastapi_users_db_sqlalchemy import (
    SQLAlchemyBaseOAuthAccountTable,
    SQLAlchemyBaseUserTable,
)
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTable
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from app.database import Base

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
    # Empty only for the instant between a Google sign-up and UserManager.oauth_callback filling it.
    username: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    oauth_accounts: Mapped[list[OAuthAccount]] = relationship("OAuthAccount", lazy="joined")


class AccessToken(SQLAlchemyBaseAccessTokenTable[int], Base):
    __tablename__ = "access_token"
    __table_args__ = {"schema": "auth"}

    @declared_attr
    def user_id(cls) -> Mapped[int]:
        return mapped_column(Integer, ForeignKey(USER_FK, ondelete="cascade"), nullable=False)
