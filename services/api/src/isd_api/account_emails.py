"""The account emails (Phase 5.2): "Forgot password", the password-changed
notice and the set-up email for a new account. Wording is plain and says
what to do if the person didn't expect it.

Each email is written in the person's chosen language (isd_api/i18n),
English until they choose one. `compose` is shared with the other emails
families get (bus-time changes, answered correction requests)."""

from __future__ import annotations

from datetime import timedelta

from isd_api import i18n
from isd_api.config import settings
from isd_api.i18n import tr
from isd_api.mailer import Email
from isd_api.models import User

SIGNATURE = "isd-bus-routing, your district's school transportation system"
# Until a fluent speaker has reviewed a language (docs/translation.md).
REVIEW_NOTE = (
    "This translation is waiting for review. If anything is unclear, contact your "
    "transportation office."
)


def language_of(user: User) -> str:
    return i18n.normalize(user.preferred_language)


def compose(lang: str, user: User, subject: str, paragraphs: list[str]) -> Email:
    """An email to `user`: a greeting, the paragraphs (already in `lang`),
    and the signature."""
    closing = [tr(lang, REVIEW_NOTE)] if lang in i18n.REVIEW_PENDING else []
    body = "\n\n".join(
        [tr(lang, "Hello {name},", name=user.full_name), *paragraphs, *closing, tr(lang, SIGNATURE)]
    )
    return Email(to=user.email, subject=subject, body=body + "\n")


def _link(token: str) -> str:
    return f"{settings.web_url}/reset-password#token={token}"


def _duration(lang: str, lifetime: timedelta) -> str:
    minutes = int(lifetime.total_seconds() // 60)
    if minutes % (24 * 60) == 0:
        days = minutes // (24 * 60)
        return tr(lang, "{count} day" if days == 1 else "{count} days", count=days)
    if minutes % 60 == 0:
        hours = minutes // 60
        return tr(lang, "{count} hour" if hours == 1 else "{count} hours", count=hours)
    return tr(lang, "{count} minutes", count=minutes)


def reset_email(user: User, token: str, lifetime: timedelta) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "Reset your bus app password"),
        [
            tr(
                lang,
                "Someone asked to reset the password for your account. To choose a new one, "
                "open this link within {duration}. It works once:",
                duration=_duration(lang, lifetime),
            ),
            _link(token),
            tr(lang, "If you didn't ask, you can ignore this email: your password stays the same."),
        ],
    )


def setup_email(user: User, token: str, lifetime: timedelta) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "Set up your bus app account"),
        [
            tr(
                lang,
                "Your school district's transportation office created an account for you. "
                "To choose your password, open this link within {duration}. It works once:",
                duration=_duration(lang, lifetime),
            ),
            _link(token),
            tr(
                lang,
                "Afterwards, sign in at {url} with this email address.",
                url=f"{settings.web_url}/login",
            ),
            tr(lang, "If you weren't expecting this, contact your transportation office."),
        ],
    )


def mfa_reset_email(user: User) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "Your bus app two-step sign-in was reset"),
        [
            tr(
                lang,
                "Your transportation office reset two-step sign-in on your account, and you "
                "were signed out everywhere. Next time you sign in you'll set up your "
                "authenticator app again.",
            ),
            tr(
                lang,
                "If you didn't ask for this, contact your transportation office straight away.",
            ),
        ],
    )


def mfa_turned_off_email(user: User) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "Two-step sign-in was turned off"),
        [
            tr(lang, "Two-step sign-in was just turned off for your account."),
            tr(
                lang,
                "If this wasn't you, change your password and contact your transportation "
                "office straight away.",
            ),
        ],
    )


def recovery_code_used_email(user: User, left: int) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "A recovery code was used to sign in"),
        [
            tr(
                lang,
                "Someone signed in to your account with one of your recovery codes instead of "
                "the authenticator app. You have {count} left; you can make new ones on your "
                "Account page.",
                count=left,
            ),
            tr(lang, "If this wasn't you, contact your transportation office straight away."),
        ],
    )


def password_changed_email(user: User) -> Email:
    lang = language_of(user)
    return compose(
        lang,
        user,
        tr(lang, "Your bus app password was changed"),
        [
            tr(
                lang,
                "The password for your account was just changed, and you were signed out on "
                "your other devices.",
            ),
            tr(lang, "If this wasn't you, contact your transportation office straight away."),
        ],
    )
