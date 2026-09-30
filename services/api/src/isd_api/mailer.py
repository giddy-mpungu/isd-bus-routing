"""Sending email over SMTP (Phase 5.2).

Provider-neutral by the product owner's choice of 2026-09-30: any SMTP
service (Amazon SES, Postmark, Brevo, Google Workspace, a district's own
server) works through the `ISD_API_SMTP_*` settings; locally and in the
laptop demo it's a Mailpit test inbox. Plain text only: it reads the same
in every mail app and on every phone.

Routers hand messages to FastAPI's BackgroundTasks, so a slow or failing
mail server never delays a response or reveals, by timing, whether an
address has an account. A failure is logged without the message itself,
since bodies carry one-time links.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from isd_api.config import settings

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    body: str


def is_configured() -> bool:
    return bool(settings.smtp_host and settings.mail_from)


def send(email: Email) -> None:
    """Delivers one message; raises on failure."""
    if not is_configured():
        raise RuntimeError("Email isn't configured (ISD_API_SMTP_HOST, ISD_API_MAIL_FROM)")
    assert settings.smtp_host is not None and settings.mail_from is not None
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = email.to
    message["Subject"] = email.subject
    message.set_content(email.body)

    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if settings.smtp_security == "ssl":
        smtp = smtplib.SMTP_SSL(
            settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS, context=context
        )
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=TIMEOUT_SECONDS)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


def send_quietly(email: Email) -> None:
    """For background tasks: a failure is logged, never raised."""
    try:
        send(email)
    except Exception:
        # Deliberately not the message: it may hold a one-time link.
        logger.exception("Couldn't send the %r email", email.subject)
