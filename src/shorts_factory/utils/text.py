"""Text measurement and wrapping helpers used by the writer and subtitle stages."""

from __future__ import annotations

import re

# Korean text uses both ASCII and full-width sentence punctuation.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。？！])\s+|\n+")  # noqa: RUF001
_CLAUSE_SPLIT = re.compile(r"(?<=[,;、·])\s+")


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def visible_length(text: str) -> int:
    """Character count ignoring whitespace; a proxy for speaking time."""
    return len(re.sub(r"\s+", "", text))


def estimate_duration_sec(text: str, chars_per_sec: float) -> float:
    if chars_per_sec <= 0:
        raise ValueError("chars_per_sec must be positive")
    return round(visible_length(text) / chars_per_sec, 3)


def split_sentences(text: str) -> list[str]:
    parts = [normalize_whitespace(part) for part in _SENTENCE_SPLIT.split(text)]
    return [part for part in parts if part]


def split_for_subtitles(text: str, max_chars: int) -> list[str]:
    """Split narration into cue-sized chunks, preferring sentence boundaries."""
    chunks: list[str] = []
    for sentence in split_sentences(text) or [normalize_whitespace(text)]:
        if not sentence:
            continue
        if len(sentence) <= max_chars:
            chunks.append(sentence)
            continue
        for clause in _CLAUSE_SPLIT.split(sentence):
            clause = normalize_whitespace(clause)
            if not clause:
                continue
            if len(clause) <= max_chars:
                chunks.append(clause)
            else:
                chunks.extend(_hard_wrap(clause, max_chars))
    return _merge_short(chunks, max_chars)


def _merge_short(chunks: list[str], max_chars: int) -> list[str]:
    """Greedily join neighbouring fragments so cues do not flash one word at a time."""
    merged: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if merged and len(merged[-1]) + 1 + len(chunk) <= max_chars:
            merged[-1] = f"{merged[-1]} {chunk}"
        else:
            merged.append(chunk)
    return merged


def _hard_wrap(text: str, max_chars: int) -> list[str]:
    """Wrap on spaces when possible, otherwise cut on character count.

    Korean has few spaces, so a space-only wrapper would return one huge line.
    """
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        while len(word) > max_chars:
            lines.append(word[:max_chars])
            word = word[max_chars:]
        current = word
    if current:
        lines.append(current)
    return lines


def wrap_cue(text: str, max_chars_per_line: int, max_lines: int) -> str:
    """Lay a cue out over at most ``max_lines`` lines."""
    lines = _hard_wrap(normalize_whitespace(text), max_chars_per_line)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    # Too long for the cue box: keep the first lines and fold the rest into the last.
    head = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :])
    return "\n".join([*head, tail])
