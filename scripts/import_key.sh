#!/usr/bin/env bash
# Find an API key in another .env on this machine and copy it into this one.
#
#   bash scripts/import_key.sh FAL
#   bash scripts/import_key.sh                 # same, FAL is the default
#
# Keys tend to live in whichever project first needed them, and copying the one
# you need by hand means opening a file full of secrets in an editor and
# pasting a value around. This never prints a value: it reports file paths and
# variable NAMES, and appends the matching lines straight from one file to the
# other.
set -uo pipefail

PATTERN="${1:-FAL}"
TARGET="$(cd "$(dirname "$0")/.." && pwd)/.env"
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; DIM='\033[2m'; OFF='\033[0m'

printf "${DIM}--${OFF} looking for a %s key in .env files outside this project\n" "$PATTERN"

# $HOME first: it is on the Linux filesystem and searching it is instant. The
# Windows mount under WSL is a 9p filesystem where a deep find takes minutes, so
# it is only reached when the fast search finds nothing.
mapfile -t CANDIDATES < <(
  find "$HOME" -maxdepth 5 -name '.env' -type f 2>/dev/null | grep -vFx "$TARGET"
)
if [ "${#CANDIDATES[@]}" -eq 0 ] && [ -d /mnt/c/Users ]; then
  printf "${DIM}--${OFF} nothing under \$HOME; trying the Windows drive (slower)\n"
  mapfile -t CANDIDATES < <(
    find /mnt/c/Users -maxdepth 5 -name '.env' -type f 2>/dev/null | grep -vFx "$TARGET"
  )
fi

FOUND=()
for f in "${CANDIDATES[@]:-}"; do
  [ -n "$f" ] || continue
  names="$(grep -oE "^(export +)?[A-Za-z_]*${PATTERN}[A-Za-z_0-9]*" "$f" 2>/dev/null \
           | sed 's/^export *//' | sort -u | tr '\n' ' ')"
  if [ -n "$names" ]; then
    printf "${GREEN}found${OFF} %s\n       %s\n" "$f" "$names"
    FOUND+=("$f")
  fi
done

if [ "${#FOUND[@]}" -eq 0 ]; then
  printf "${RED}stop${OFF}  no .env on this machine has a %s key in it.\n" "$PATTERN"
  echo "      Searched ${#CANDIDATES[@]} file(s). If the key lives somewhere this did"
  echo "      not reach, append it yourself without opening the file:"
  echo "          grep -h '^${PATTERN}' /path/to/that/.env >> $TARGET"
  exit 1
fi

if [ "${#FOUND[@]}" -gt 1 ]; then
  printf "${YELLOW}!!${OFF}    more than one file has one. Pick the right one and run:\n"
  echo "          grep -hE '^(export +)?[A-Za-z_]*${PATTERN}[A-Za-z_0-9]*=' <file> \\"
  echo "            | sed 's/^export //' >> $TARGET"
  exit 1
fi

SOURCE="${FOUND[0]}"
BEFORE="$(grep -cE "^[A-Za-z_]*${PATTERN}" "$TARGET" 2>/dev/null || echo 0)"
if [ "$BEFORE" -gt 0 ]; then
  printf "${YELLOW}!!${OFF}    %s already has a %s entry; not adding a second one.\n" \
    "$TARGET" "$PATTERN"
  exit 0
fi

# Appended verbatim, so the value passes between two files and never through a
# terminal, a clipboard or a shell history entry.
[ -s "$TARGET" ] && [ -n "$(tail -c 1 "$TARGET")" ] && echo >> "$TARGET"
grep -hE "^(export +)?[A-Za-z_]*${PATTERN}[A-Za-z_0-9]*=" "$SOURCE" \
  | sed 's/^export //' >> "$TARGET"

ADDED="$(grep -oE "^[A-Za-z_]*${PATTERN}[A-Za-z_0-9]*" "$TARGET" | sort -u | tr '\n' ' ')"
printf "${GREEN}ok${OFF}    copied into %s: %s\n" "$TARGET" "$ADDED"
echo
echo "      Check it reaches the provider:"
echo "          ./run.sh --probe"
