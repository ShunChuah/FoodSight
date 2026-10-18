import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app import config

logger = logging.getLogger("foodsight.email")


def _send(to: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config.MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as smtp:
        smtp.starttls()
        smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
        smtp.send_message(message)


async def send_email(to: str, subject: str, body: str) -> None:
    if not (config.SMTP_USER and config.SMTP_PASSWORD):
        logger.warning("SMTP is not configured, so this email was not sent.\nTo: %s\nSubject: %s\n%s", to, subject, body)
        return
    try:
        await asyncio.to_thread(_send, to, subject, body)
    except (smtplib.SMTPException, OSError):
        logger.exception("Could not send email to %s. Its content was:\n%s", to, body)
