#!/usr/bin/env python3
"""Create config/settings.local.yaml for this machine.

    ./run.sh --setup
    ./run.sh --setup --project-root D:/shorts-projects

The two settings that differ per machine are the subtitle font and where the
several gigabytes of video per Short are written. Both were being edited by
hand, in YAML, from instructions in a chat window -- which is how a backslash
in a Windows path or a mis-indented block becomes a failed run twenty minutes
later.

Comments in the file are preserved: it is copied from the example, which
explains every setting, and only the specific lines needed are rewritten.
Nothing already set by hand is overwritten unless --force is given.
"""

from __future__ import annotations

import argparse
import platform
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "config" / "settings.local.yaml.example"
TARGET = REPO / "config" / "settings.local.yaml"

#: A font that can render Korean, per platform. The shipped default is the
#: Linux one, so a Windows machine burns subtitles in a fallback font or not at
#: all until this is changed.
DEFAULT_FONTS = {
    "Windows": "Malgun Gothic",
    "Darwin": "Apple SD Gothic Neo",
    "Linux": "Noto Sans CJK KR",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        help="Where projects are written, e.g. D:/shorts-projects. Forward "
        "slashes on Windows too -- a backslash is an escape character in YAML.",
    )
    parser.add_argument(
        "--font",
        help=f"Subtitle font. Default for this OS: "
        f"{DEFAULT_FONTS.get(platform.system(), 'Noto Sans CJK KR')}",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing values.")
    return parser.parse_args()


def key_line(key: str) -> re.Pattern[str]:
    """Matches a real setting or a commented-out one, and nothing else.

    ``#project_root: projects`` is a setting waiting to be switched on.
    ``#   project_root: D:/shorts-projects`` inside a comment block is
    documentation, and rewriting it deletes the explanation while leaving the
    real line untouched -- which is how the first version of this produced a
    file with the key on two lines. The difference is the indentation after the
    comment marker, so at most one space is allowed.
    """
    return re.compile(rf"^(#\s?)?{re.escape(key)}:")


def set_scalar(text: str, key: str, value: str, *, force: bool) -> tuple[str, str]:
    """Set a top-level ``key: value``, commented-out or absent or already set."""
    pattern = key_line(key)
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not pattern.match(line):
            continue
        stripped = line.lstrip("#").strip()
        already_set = not line.lstrip().startswith("#")
        if already_set and not force:
            current = stripped.split(":", 1)[1].strip()
            return text, f"kept {key}: {current}"
        lines[index] = f"{key}: {value}"
        return "\n".join(lines) + "\n", f"set {key}: {value}"
    return text.rstrip() + f"\n\n{key}: {value}\n", f"set {key}: {value}"


def set_nested(text: str, block: str, key: str, value: str, *, force: bool) -> tuple[str, str]:
    """Set ``key`` under a top-level ``block:``, creating the block if needed."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == f"{block}:"), None)
    if start is None:
        return (
            text.rstrip() + f"\n\n{block}:\n  {key}: {value}\n",
            f"set {block}.{key}: {value}",
        )
    for index in range(start + 1, len(lines)):
        line = lines[index]
        # The block ends at the first line that is neither indented nor blank.
        if line.strip() and not line.startswith((" ", "\t")):
            break
        if re.match(rf"^\s*(#\s?)?{re.escape(key)}:", line):
            if not line.lstrip().startswith("#") and not force:
                current = line.split(":", 1)[1].strip()
                return text, f"kept {block}.{key}: {current}"
            lines[index] = f"  {key}: {value}"
            return "\n".join(lines) + "\n", f"set {block}.{key}: {value}"
        end = index
    else:
        end = len(lines) - 1
    lines.insert(end + 1, f"  {key}: {value}")
    return "\n".join(lines) + "\n", f"set {block}.{key}: {value}"


def main() -> int:
    args = parse_args()
    system = platform.system()

    if not TARGET.exists():
        if not EXAMPLE.exists():
            print(f"FAIL: {EXAMPLE} is missing; cannot start from anything.")
            return 1
        TARGET.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"  created {TARGET.name} from the example")
    else:
        print(f"  {TARGET.name} already exists; only filling in what is unset")

    text = TARGET.read_text(encoding="utf-8")
    notes: list[str] = []

    font = args.font or DEFAULT_FONTS.get(system, "Noto Sans CJK KR")
    text, note = set_nested(text, "subtitles", "font_name", font, force=args.force)
    notes.append(note)

    if args.project_root:
        root = args.project_root.replace("\\", "/")
        if root != args.project_root:
            print("  note: backslashes turned into forward slashes; YAML treats \\ as an escape")
        text, note = set_scalar(text, "project_root", root, force=args.force)
        notes.append(note)

    # A silently duplicated top-level key is the failure mode of editing YAML
    # by pattern: PyYAML takes the last one without complaint, so the file looks
    # fine and means something other than it reads.
    duplicates = [
        key
        for key in ("project_root", "subtitles")
        if sum(bool(re.match(rf"^{key}:", ln)) for ln in text.splitlines()) > 1
    ]
    if duplicates:
        print(f"FAIL: would have written {', '.join(duplicates)} twice; file left alone.")
        return 1

    TARGET.write_text(text, encoding="utf-8")

    print(f"\n  {system} detected")
    for note in notes:
        print(f"    {note}")

    # Validated here rather than discovered by the next command, because a
    # config this file just wrote is exactly the one worth checking.
    sys.path.insert(0, str(REPO / "src"))
    try:
        from shorts_factory.config import load_config

        config = load_config(REPO / "config", load_env=False)
    except Exception as exc:
        print(f"\nFAIL: the file it just wrote does not load: {exc}")
        return 1

    print(f"\n  project_root  {config.settings.project_root}")
    print(f"  font          {config.settings.subtitles.font_name}")
    providers = config.settings.providers.as_dict()
    mocks = [k for k, v in providers.items() if v == "mock"]
    if mocks:
        print(f"\n  still on mock: {', '.join(mocks)}")
        print("  A run with any mock in it produces mock_preview.mp4, never a Short.")
    else:
        print(f"\n  providers     {', '.join(f'{k}={v}' for k, v in providers.items())}")
    print("\n  Next:  ./run.sh --doctor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
