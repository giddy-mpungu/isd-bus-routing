"""Translations (Phase 5): what families and drivers read, in their language.

Decided by the product owner on 2026-10-07: Spanish first, for the sign-in,
family and driver screens and the emails families get; the staff console
stays in English. Spanish ships marked as awaiting review by a fluent
speaker (docs/translation.md has the reviewer's checklist).

Phrases are keyed by their English text, so English needs no catalog and
the code stays readable. Each other language is one dict in its own module
(`es.py`); adding a language is adding a module and a line to `CATALOGS`.
A phrase may hold `{name}` placeholders, filled the same way in every
language. A phrase missing from a catalog falls back to English.

Three ways text gets translated:
- `tr(lang, phrase, **values)` where the code builds the text (emails).
- `translate_message(lang, message)` for a finished English message,
  matched against the catalog's phrases, placeholders included.
- the HTTPException handler in main.py, which does the same for every
  error's `detail`, in the language the request asked for.
"""

from __future__ import annotations

import re
from functools import lru_cache

from fastapi import Request

from isd_api.i18n import es

DEFAULT = "en"
# Each language's own name, for the language picker.
LANGUAGES = {"en": "English", "es": "Español"}
CATALOGS: dict[str, dict[str, str]] = {"es": es.PHRASES}

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def normalize(code: str | None) -> str:
    """A supported language code for `code` ("es-US" -> "es"), else English."""
    if not code:
        return DEFAULT
    base = code.strip().lower().replace("_", "-").split("-", 1)[0]
    return base if base in LANGUAGES else DEFAULT


def from_accept_language(header: str | None) -> str:
    """The first supported language in an Accept-Language header, by weight."""
    if not header:
        return DEFAULT
    choices: list[tuple[float, int, str]] = []
    for index, part in enumerate(header.split(",")):
        code, _, params = part.strip().partition(";")
        weight = 1.0
        if params.strip().startswith("q="):
            try:
                weight = float(params.strip()[2:])
            except ValueError:
                weight = 0.0
        if code and weight > 0:
            choices.append((-weight, index, code))
    for _, _, code in sorted(choices):
        base = code.strip().lower().split("-", 1)[0]
        if base in LANGUAGES:
            return base
    return DEFAULT


def request_language(request: Request) -> str:
    """FastAPI dependency: the language this request asked for."""
    return from_accept_language(request.headers.get("accept-language"))


def tr(lang: str, phrase: str, **values: object) -> str:
    """`phrase` in `lang`, with its placeholders filled."""
    template = CATALOGS.get(lang, {}).get(phrase, phrase)
    return template.format(**values) if values else template


# Placeholders that only ever hold a number.
_NUMBERS = {"count", "riders", "capacity"}
# A template with less fixed text than this ("{count} days") is only used
# through tr(), never to recognise a finished message.
_MIN_FIXED_TEXT = 20


def _capture(name: str) -> str:
    return f"(?P<{name}>\\d+)" if name in _NUMBERS else f"(?P<{name}>.+?)"


@lru_cache(maxsize=4)
def _patterns(lang: str) -> list[tuple[re.Pattern[str], str]]:
    patterns = []
    for phrase, translated in CATALOGS.get(lang, {}).items():
        if not _PLACEHOLDER.search(phrase):
            continue
        pieces = [piece for piece in re.split(r"(\{\w+\})", phrase) if piece]
        fixed = "".join(p for p in pieces if not _PLACEHOLDER.fullmatch(p))
        if len(fixed.strip()) < _MIN_FIXED_TEXT:
            continue
        regex = "".join(
            _capture(p[1:-1]) if _PLACEHOLDER.fullmatch(p) else re.escape(p) for p in pieces
        )
        patterns.append((re.compile(f"^{regex}$", re.S), translated))
    return patterns


def translate_message(lang: str, message: str) -> str:
    """A finished English `message` in `lang`, or unchanged if it isn't a
    known phrase. A placeholder's value is translated too when it is a
    phrase itself ("completed" in "This assignment is already completed.")."""
    catalog = CATALOGS.get(lang)
    if not catalog:
        return message
    if message in catalog:
        return catalog[message]
    for pattern, translated in _patterns(lang):
        match = pattern.match(message)
        if match:
            values = {name: catalog.get(value, value) for name, value in match.groupdict().items()}
            return translated.format(**values)
    return message
