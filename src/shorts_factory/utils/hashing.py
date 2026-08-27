"""Deterministic hashes used for idempotency (spec section 24)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: dict[str, Any]) -> str:
    """Hash a dict in a key-order-independent, type-stable way."""
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return sha256_text(encoded)


def asset_prompt_hash(
    *,
    provider: str,
    model: str,
    prompt: str,
    duration_sec: float,
    aspect_ratio: str,
    negative_constraints: list[str] | None = None,
) -> str:
    """Identity of a generation request.

    Two requests with the same hash produce interchangeable assets, so a
    completed asset with a matching hash is reused instead of re-billed.
    """
    return stable_hash(
        {
            "provider": provider,
            "model": model,
            "prompt": prompt,
            # Round so float noise in scene timing does not invalidate a cache hit.
            "duration_sec": round(float(duration_sec), 2),
            "aspect_ratio": aspect_ratio,
            "negative": sorted(negative_constraints or []),
        }
    )
