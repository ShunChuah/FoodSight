import re

import httpx
from fastapi import Depends
from fastapi_users import BaseUserManager, IntegerIDMixin, InvalidPasswordException
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from httpx_oauth.clients.google import GoogleOAuth2
from httpx_oauth.exceptions import GetIdEmailError
from sqlalchemy import delete

from app import config
from app.auth.email import send_email
from app.auth.models import AccessToken, OAuthAccount, User
from app.database import get_async_session

GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
LINK_MINUTES = config.EMAIL_LINK_LIFETIME_SECONDS // 60
PICTURE_URL_MAX = 500  # auth.users.profile_picture_url is varchar(500)

PASSWORD_RULES = (
    (r".{8,}", "at least 8 characters"),
    (r"[A-Z]", "an uppercase letter"),
    (r"[a-z]", "a lowercase letter"),
    (r"\d", "a number"),
    (r"[^A-Za-z0-9]", "a special character"),
)


async def get_user_db(session=Depends(get_async_session)):
    yield SQLAlchemyUserDatabase(session, User, OAuthAccount)


async def get_access_token_db(session=Depends(get_async_session)):
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


# The stock client reads the People API, which is disabled by default in a Google Cloud project.
class GoogleClient(GoogleOAuth2):
    async def get_id_email(self, token: str) -> tuple[str, str | None]:
        async with self.get_httpx_client() as client:
            response = await client.get(
                GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {token}"}
            )
        if response.status_code >= 400:
            raise GetIdEmailError(response=response)
        profile = response.json()
        # Accounts are linked by email, so only trust an address Google has confirmed.
        email = profile.get("email") if profile.get("email_verified") else None
        return profile["sub"], email


async def fetch_google_profile(access_token: str) -> dict:
    """The Google profile ({"name": ..., "picture": ...}), or {} if Google cannot be reached."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
            )
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        return {}


def picture_url(value) -> str | None:
    """A profile picture link worth saving: https, and short enough for the column."""
    if isinstance(value, str) and value.startswith("https://") and len(value) <= PICTURE_URL_MAX:
        return value
    return None


class UserManager(IntegerIDMixin, BaseUserManager[User, int]):
    reset_password_token_secret = config.AUTH_SECRET
    verification_token_secret = config.AUTH_SECRET
    reset_password_token_lifetime_seconds = config.EMAIL_LINK_LIFETIME_SECONDS
    verification_token_lifetime_seconds = config.EMAIL_LINK_LIFETIME_SECONDS

    async def validate_password(self, password, user):
        missing = [label for pattern, label in PASSWORD_RULES if not re.search(pattern, password)]
        if missing:
            raise InvalidPasswordException(reason="Password must include " + ", ".join(missing) + ".")

    async def on_after_register(self, user, request=None):
        if not user.is_verified:
            await self.request_verify(user, request)

    async def on_after_request_verify(self, user, token, request=None):
        link = f"{config.FRONTEND_URL}/verify?token={token}"
        await send_email(
            user.email,
            "Verify your FoodSight account",
            f"Hi {user.username},\n\nOpen this link to verify your email address:\n{link}\n\n"
            f"The link expires in {LINK_MINUTES} minutes.",
        )

    async def on_after_forgot_password(self, user, token, request=None):
        link = f"{config.FRONTEND_URL}/reset-password?token={token}"
        await send_email(
            user.email,
            "Reset your FoodSight password",
            f"Hi {user.username},\n\nOpen this link to choose a new password:\n{link}\n\n"
            f"The link expires in {LINK_MINUTES} minutes. If you did not ask for this, ignore this email.",
        )

    async def on_after_reset_password(self, user, request=None):
        session = self.user_db.session
        await session.execute(delete(AccessToken).where(AccessToken.user_id == user.id))
        await session.commit()

    async def oauth_callback(self, oauth_name, access_token, account_id, account_email, *args, **kwargs):
        # First sign-in with this Google account: a new user, or an email account
        # linking Google for the first time. Later sign-ins find it already linked.
        first_google_sign_in = await self.user_db.get_by_oauth_account(oauth_name, account_id) is None
        user = await super().oauth_callback(
            oauth_name, access_token, account_id, account_email, *args, **kwargs
        )
        # An email account whose verification link was never opened: whoever registered
        # it chose its password and name, and may not own this address. Google has now
        # confirmed the owner, so the owner gets the account with a password nobody
        # knows (Forgot password sets a real one) and their Google name. Keeping the old
        # password would let that person into the owner's account.
        unproven = not user.is_verified and kwargs.get("is_verified_by_default")
        updates = {}
        if unproven:
            updates["hashed_password"] = self.password_helper.hash(self.password_helper.generate())
            updates["is_verified"] = True
        if first_google_sign_in or not user.username or unproven:
            profile = await fetch_google_profile(access_token)
            if not user.username or unproven:
                name = profile.get("name") or account_email.split("@")[0]
                updates["username"] = name[:150]
            # The Google picture only on the first Google sign-in, and only when the
            # account has none, so a picture the user chose later is never replaced.
            picture = picture_url(profile.get("picture"))
            if first_google_sign_in and picture and not user.profile_picture_url:
                updates["profile_picture_url"] = picture
        if updates:
            user = await self.user_db.update(user, updates)
        return user


async def get_user_manager(user_db=Depends(get_user_db)):
    yield UserManager(user_db)
