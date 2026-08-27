#!/usr/bin/env python3
"""Fill the .env entries that are blank or absent from one that is filled.

    ./run.sh --fix-keys
    ./run.sh --fix-keys --dry-run

Every Google secret in this project is the same Gemini key under five names --
LLM_API_KEY, SEARCH_API_KEY, IMAGE_API_KEY, TTS_API_KEY, VIDEO_API_KEY -- because
the pipeline keeps them separate so one stage can be pointed at a different
account. When an .env is assembled by hand the usual outcome is three filled and
two blank, and the run fails on a key whose value is sitting in the same file
four times.

Only blank or missing entries are written. A filled one is never overwritten,
values are never printed, and nothing outside the Google family is touched --
an empty OPENAI_API_KEY stays empty, because it is a different vendor's key and
guessing it would be wrong rather than merely useless.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENV = REPO / ".env"

#: One Gemini key satisfies all of these. Ordered: a value is looked for from
#: the left, so an explicit GEMINI_API_KEY wins over a per-stage name.
GOOGLE_FAMILY = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "LLM_API_KEY",
    "SEARCH_API_KEY",
    "IMAGE_API_KEY",
    "TTS_API_KEY",
    "VIDEO_API_KEY",
)

#: The names the pipeline actually asks for. GEMINI_API_KEY and GOOGLE_API_KEY
#: are accepted as aliases, so they are sources rather than things to write.
GOOGLE_REQUIRED = ("LLM_API_KEY", "SEARCH_API_KEY", "IMAGE_API_KEY", "TTS_API_KEY", "VIDEO_API_KEY")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Say what would change, change nothing."
    )
    return parser.parse_args()


def read_entries(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip().removeprefix("export ").strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        entries[name.strip()] = value.strip().strip("\"'")
    return entries


def fill(text: str, name: str, value: str) -> str:
    """Set ``name`` to ``value``, replacing a blank line or appending."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip().removeprefix("export ").strip()
        if stripped.split("=", 1)[0].strip() == name:
            lines[index] = f"{name}={value}"
            return "\n".join(lines) + "\n"
    return text.rstrip() + f"\n{name}={value}\n"


def main() -> int:
    args = parse_args()
    if not ENV.exists():
        print(f"FAIL: {ENV} does not exist. ./run.sh --find-key can bring one in.")
        return 1

    text = ENV.read_text(encoding="utf-8")
    entries = read_entries(text)

    source = next((n for n in GOOGLE_FAMILY if entries.get(n)), None)
    if source is None:
        print("FAIL: no Google key has a value, so there is nothing to copy from.")
        print(f"      Fill any one of: {', '.join(GOOGLE_REQUIRED)}")
        return 1

    needed = [n for n in GOOGLE_REQUIRED if not entries.get(n)]
    if not needed:
        print("  every Google key already has a value; nothing to do")
        return 0

    blank = [n for n in needed if n in entries]
    absent = [n for n in needed if n not in entries]
    noun = "entry" if len(needed) == 1 else "entries"
    print(f"  copying the value of {source} into {len(needed)} {noun}")
    if blank:
        print(f"    present but blank : {', '.join(blank)}")
    if absent:
        print(f"    absent            : {', '.join(absent)}")

    if args.dry_run:
        print("\n  --dry-run: nothing written")
        return 0

    value = entries[source]
    for name in needed:
        text = fill(text, name, value)

    # Written through a temporary file so an interrupted write cannot leave a
    # half-truncated .env, which would lose every key at once.
    temporary = ENV.with_suffix(".env.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(ENV)

    remaining = [
        n for n in GOOGLE_REQUIRED if not read_entries(ENV.read_text(encoding="utf-8")).get(n)
    ]
    if remaining:
        print(f"\nFAIL: still empty after writing: {', '.join(remaining)}")
        return 1
    print("\n  done. Next:  ./run.sh --doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
