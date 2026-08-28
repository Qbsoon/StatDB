"""Tiny i18n layer: EN default, PL toggle, env var can force the language."""

from __future__ import annotations

from typing import Callable

from .en import STRINGS as EN
from .pl import STRINGS as PL

SUPPORTED = ("en", "pl")
DEFAULT = "en"
COOKIE_NAME = "statdb_lang"

_TRANSLATIONS: dict[str, dict[str, str]] = {"en": EN, "pl": PL}


def translations(lang: str) -> dict[str, str]:
    """Return the EN table overlaid with ``lang`` (missing keys fall back to EN)."""
    table = dict(EN)
    if lang != "en" and lang in _TRANSLATIONS:
        table.update(_TRANSLATIONS[lang])
    return table


def resolve_language(*, forced: bool, env_language: str, cookie_language: str | None) -> str:
    """Pick the UI language for the current request.

    Priority: forced env var > user cookie > default (en).
    """
    if forced and env_language in SUPPORTED:
        return env_language
    if cookie_language in SUPPORTED:
        return cookie_language
    return DEFAULT


def make_translator(lang: str) -> Callable[..., str]:
    """Build ``t(msg_key, **kwargs)`` with ``str.format`` interpolation support.

    ``msg_key`` avoids colliding with a format argument named ``key``.
    """
    table = translations(lang)

    def t(msg_key: str, **kwargs: object) -> str:
        text = table.get(msg_key, msg_key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError, ValueError):
                return text
        return text

    return t
