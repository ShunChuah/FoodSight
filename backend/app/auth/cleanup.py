import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app import config
from app.auth.models import AccessToken
from app.database import async_session_maker

CLEANUP_EVERY_SECONDS = 60 * 60

logger = logging.getLogger("foodsight")


async def delete_expired_tokens():
    """Delete session tokens older than the session length.

    The login library refuses an expired token but never deletes it, so without
    this every login would leave a row in auth.access_token for good.
    """
    oldest_valid = datetime.now(timezone.utc) - timedelta(seconds=config.SESSION_LIFETIME_SECONDS)
    async with async_session_maker() as session:
        await session.execute(delete(AccessToken).where(AccessToken.created_at < oldest_valid))
        await session.commit()


async def run_token_cleanup():
    """Clean up now, then every hour, for as long as the backend runs."""
    while True:
        try:
            await delete_expired_tokens()
        except Exception:
            # Catch everything: an error that escaped would stop the cleanup for good.
            logger.exception("Could not delete expired session tokens; trying again in an hour")
        await asyncio.sleep(CLEANUP_EVERY_SECONDS)
