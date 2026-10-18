from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions

from app import config
from app.auth.backend import auth_backend, current_user, fastapi_users, oauth_backend
from app.auth.manager import GoogleClient, get_user_manager
from app.auth.schemas import ForgotPasswordRequest, ResetPasswordRequest, UserCreate, UserRead

router = APIRouter()

router.include_router(
    fastapi_users.get_auth_router(auth_backend, requires_verification=True),
    prefix="/auth",
    tags=["auth"],
)
router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=["auth"]
)
router.include_router(fastapi_users.get_verify_router(UserRead), prefix="/auth", tags=["auth"])


# Written by hand instead of get_reset_password_router: the use case requires telling the
# user when no account matches the email, which the library deliberately hides.
@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED, tags=["auth"])
async def forgot_password(
    body: ForgotPasswordRequest, request: Request, user_manager=Depends(get_user_manager)
):
    try:
        user = await user_manager.get_by_email(body.email)
    except exceptions.UserNotExists:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "FORGOT_PASSWORD_USER_NOT_FOUND")
    try:
        await user_manager.forgot_password(user, request)
    except exceptions.UserInactive:
        pass


@router.post("/auth/reset-password", tags=["auth"])
async def reset_password(
    body: ResetPasswordRequest, request: Request, user_manager=Depends(get_user_manager)
):
    try:
        await user_manager.reset_password(body.token, body.password, request)
    except (
        exceptions.InvalidResetPasswordToken,
        exceptions.UserNotExists,
        exceptions.UserInactive,
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "RESET_PASSWORD_BAD_TOKEN")
    except exceptions.InvalidPasswordException as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            {"code": "RESET_PASSWORD_INVALID_PASSWORD", "reason": error.reason},
        )


if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET:
    router.include_router(
        fastapi_users.get_oauth_router(
            GoogleClient(config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET),
            oauth_backend,
            config.AUTH_SECRET,
            redirect_url=f"{config.BACKEND_URL}/api/v1/auth/google/callback",
            associate_by_email=True,
            is_verified_by_default=True,
            csrf_token_cookie_secure=config.COOKIE_SECURE,
        ),
        prefix="/auth/google",
        tags=["auth"],
    )
else:

    @router.get("/auth/google/authorize", tags=["auth"])
    async def google_not_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "GOOGLE_NOT_CONFIGURED")


@router.get("/users/me", response_model=UserRead, tags=["users"])
async def read_current_user(user=Depends(current_user)):
    return user
