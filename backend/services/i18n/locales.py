"""Locale validation shared by every endpoint that accepts an explicit
output-language request (Intelligence Copilot chat, generated report
summaries).

This is the one place a request-supplied locale string is allowed to become
part of an LLM prompt. It is deliberately an explicit allow-list backed by
`config.SUPPORTED_LOCALES`, not free-form user input passed straight through -
see CLAUDE.md's "Do not allow arbitrary locale input to alter prompts or
system instructions." The interface language, the source-document language
(articles.source_language, detected separately - see analysis/language.py),
and this AI-output locale are three independent concepts; this module only
ever governs the third one.
"""

from __future__ import annotations

import config

# Display names for the locale picker / error messages. Keyed on the same
# codes as config.SUPPORTED_LOCALES - adding a language means adding it here
# and to that tuple, nothing else in this module changes.
LOCALE_NAMES = {
    "en": "English",
    "ar": "Arabic",
}

# One explicit output-language instruction per supported locale, appended to
# an existing system prompt rather than replacing it. Kept short and
# unconditional-sounding on purpose (an LLM system prompt, not user-facing
# copy) and never built from the raw request value - only ever looked up by
# an already-validated code from normalize_locale().
LANGUAGE_INSTRUCTIONS = {
    "en": "Respond in English.",
    "ar": (
        "Respond in Arabic (Modern Standard Arabic). Keep proper names, "
        "organization names, and any directly quoted source text exactly as "
        "given rather than translating them."
    ),
}


class UnsupportedLocaleError(ValueError):
    """A request named a locale outside config.SUPPORTED_LOCALES."""

    def __init__(self, locale):
        self.locale = locale
        super().__init__(f"Unsupported locale: {locale!r}")


def normalize_locale(value, *, default: str | None = None) -> str:
    """Validate a request-supplied locale string.

    A missing/blank value returns `default` (config.DEFAULT_LOCALE when not
    given) - only an explicitly-supplied, unrecognized value is an error.
    Raises UnsupportedLocaleError otherwise, which callers turn into a
    stable-coded 400 (see services/common/api_errors.py).
    """
    default = default or config.DEFAULT_LOCALE
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if not normalized:
        return default
    if normalized not in config.SUPPORTED_LOCALES:
        raise UnsupportedLocaleError(normalized)
    return normalized


def locale_display_name(locale: str) -> str:
    return LOCALE_NAMES.get(locale, locale)


def language_instruction(locale: str) -> str:
    return LANGUAGE_INSTRUCTIONS.get(locale, LANGUAGE_INSTRUCTIONS[config.DEFAULT_LOCALE])
