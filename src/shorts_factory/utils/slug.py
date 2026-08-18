"""Project slug generation.

Topics are usually Korean, so a naive ASCII slugifier would collapse every
project to an empty string. Hangul is transliterated to a readable romanisation
and anything left over falls back to a hash suffix.
"""

from __future__ import annotations

import re
import unicodedata

from .hashing import sha256_text

_INITIALS = [
    "g",
    "kk",
    "n",
    "d",
    "tt",
    "r",
    "m",
    "b",
    "pp",
    "s",
    "ss",
    "",
    "j",
    "jj",
    "ch",
    "k",
    "t",
    "p",
    "h",
]
_VOWELS = [
    "a",
    "ae",
    "ya",
    "yae",
    "eo",
    "e",
    "yeo",
    "ye",
    "o",
    "wa",
    "wae",
    "oe",
    "yo",
    "u",
    "wo",
    "we",
    "wi",
    "yu",
    "eu",
    "ui",
    "i",
]
_FINALS = [
    "",
    "k",
    "k",
    "k",
    "n",
    "n",
    "n",
    "t",
    "l",
    "k",
    "m",
    "l",
    "l",
    "l",
    "p",
    "l",
    "m",
    "p",
    "p",
    "t",
    "t",
    "ng",
    "t",
    "t",
    "k",
    "t",
    "p",
    "t",
]

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3


def romanize_hangul(text: str) -> str:
    """Approximate Revised Romanisation. Good enough for directory names."""
    out: list[str] = []
    for char in text:
        code = ord(char)
        if _HANGUL_BASE <= code <= _HANGUL_LAST:
            index = code - _HANGUL_BASE
            initial = index // (21 * 28)
            vowel = (index % (21 * 28)) // 28
            final = index % 28
            out.append(_INITIALS[initial] + _VOWELS[vowel] + _FINALS[final])
        else:
            out.append(char)
    return "".join(out)


def slugify(text: str, *, max_length: int = 48) -> str:
    """Return a filesystem- and URL-safe slug for ``text``."""
    romanized = romanize_hangul(text)
    normalized = unicodedata.normalize("NFKD", romanized)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", ascii_only).strip("-")
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    if not cleaned:
        cleaned = "project-" + sha256_text(text)[:8]
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip("-")
    return cleaned


def unique_slug(base: str, taken: set[str]) -> str:
    """Append ``-2``, ``-3`` ... until the slug is free."""
    if base not in taken:
        return base
    counter = 2
    while f"{base}-{counter}" in taken:
        counter += 1
    return f"{base}-{counter}"
