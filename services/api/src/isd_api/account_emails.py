"""The account emails (Phase 5.2): "Forgot password", the password-changed
notice and the set-up email for a new account. Wording is plain and says
what to do if the person didn't expect it."""

from __future__ import annotations

from datetime import timedelta

from isd_api.config import settings
from isd_api.mailer import Email
from isd_api.models import User

SIGNATURE = "\n\nisd-bus-routing, your district's school transportation system\n"


def _link(token: str) -> str:
    return f"{settings.web_url}/reset-password#token={token}"


def _duration(lifetime: timedelta) -> str:
    minutes = int(lifetime.total_seconds() // 60)
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return f"{days} day" + ("s" if days != 1 else "")
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" + ("s" if hours != 1 else "")
    return f"{minutes} minutes"


def reset_email(user: User, token: str, lifetime: timedelta) -> Email:
    return Email(
        to=user.email,
        subject="Reset your bus app password",
        body=(
            f"Hello {user.full_name},\n\n"
            "Someone asked to reset the password for your account. To choose a new one, "
            f"open this link within {_duration(lifetime)}. It works once:\n\n"
            f"{_link(token)}\n\n"
            "If you didn't ask, you can ignore this email: your password stays the same."
            + SIGNATURE
        ),
    )


def setup_email(user: User, token: str, lifetime: timedelta) -> Email:
    return Email(
        to=user.email,
        subject="Set up your bus app account",
        body=(
            f"Hello {user.full_name},\n\n"
            "Your school district's transportation office created an account for you. "
            f"To choose your password, open this link within {_duration(lifetime)}. "
            "It works once:\n\n"
            f"{_link(token)}\n\n"
            f"Afterwards, sign in at {settings.web_url}/login with this email address.\n\n"
            "If you weren't expecting this, contact your transportation office." + SIGNATURE
        ),
    )


def password_changed_email(user: User) -> Email:
    return Email(
        to=user.email,
        subject="Your bus app password was changed",
        body=(
            f"Hello {user.full_name},\n\n"
            "The password for your account was just changed, and you were signed out on "
            "your other devices.\n\n"
            "If this wasn't you, contact your transportation office straight away." + SIGNATURE
        ),
    )
