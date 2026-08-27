"""Filesystem helpers. Every project write goes through here."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def atomic_write_text(path: str | Path, text: str) -> Path:
    """Write ``text`` to ``path`` so a crash never leaves a half-written file.

    The temporary file is created in the destination directory so ``os.replace``
    is an atomic rename rather than a cross-device copy.
    """
    target = Path(path)
    ensure_dir(target.parent)
    descriptor, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    return atomic_write_text(path, text + "\n")


def atomic_write_model(path: str | Path, model: BaseModel) -> Path:
    return atomic_write_text(path, model.model_dump_json(indent=2) + "\n")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_jsonl(path: str | Path, payload: dict[str, Any]) -> None:
    target = Path(path)
    ensure_dir(target.parent)
    line = json.dumps(payload, ensure_ascii=False, default=str)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def relative_to(path: str | Path, root: str | Path) -> str:
    """POSIX-style path relative to ``root``; falls back to the absolute path."""
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()
