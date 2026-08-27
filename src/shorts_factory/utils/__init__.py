"""Small, dependency-light helpers shared across the package."""

from .files import (
    append_jsonl,
    atomic_write_json,
    atomic_write_model,
    atomic_write_text,
    ensure_dir,
    read_json,
    read_jsonl,
    relative_to,
)
from .hashing import asset_prompt_hash, sha256_file, sha256_text, stable_hash
from .logging import bind_project_log, configure_logging, get_logger
from .slug import slugify, unique_slug
from .text import (
    estimate_duration_sec,
    normalize_whitespace,
    split_for_subtitles,
    split_sentences,
    visible_length,
    wrap_cue,
)
from .timing import distribute_durations

__all__ = [
    "append_jsonl",
    "asset_prompt_hash",
    "atomic_write_json",
    "atomic_write_model",
    "atomic_write_text",
    "bind_project_log",
    "configure_logging",
    "distribute_durations",
    "ensure_dir",
    "estimate_duration_sec",
    "get_logger",
    "normalize_whitespace",
    "read_json",
    "read_jsonl",
    "relative_to",
    "sha256_file",
    "sha256_text",
    "slugify",
    "split_for_subtitles",
    "split_sentences",
    "stable_hash",
    "unique_slug",
    "visible_length",
    "wrap_cue",
]
