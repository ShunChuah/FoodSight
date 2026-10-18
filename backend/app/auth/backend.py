from fastapi import Depends
from fastapi.responses import RedirectResponse
from fastapi_users import FastAPIUsers
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy

from app import config
from app.auth.manager import get_access_token_db, get_user_manager
from app.auth.models import User

COOKIE_SETTINGS = dict(
    cookie_name=config.COOKIE_NAME,
    cookie_max_age=config.SESSION_LIFETIME_SECONDS,
    cookie_secure=config.COOKIE_SECURE,
    cookie_httponly=True,
    cookie_samesite="lax",
)


class RedirectCookieTransport(CookieTransport):
    """After a Google login the browser is on the backend URL, so send it back to the frontend."""

    async def get_login_response(self, token):
        response = RedirectResponse(f"{config.FRONTEND_URL}/chat", status_code=302)
        return self._set_login_cookie(response, token)


def get_database_strategy(access_token_db=Depends(get_access_token_db)):
    return DatabaseStrategy(access_token_db, lifetime_seconds=config.SESSION_LIFETIME_SECONDS)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=CookieTransport(**COOKIE_SETTINGS),
    get_strategy=get_database_strategy,
)
oauth_backend = AuthenticationBackend(
    name="cookie-oauth",
    transport=RedirectCookieTransport(**COOKIE_SETTINGS),
    get_strategy=get_database_strategy,
)

fastapi_users = FastAPIUsers[User, int](get_user_manager, [auth_backend])
current_user = fastapi_users.current_user(active=True, verified=True)
