#!/usr/bin/env bash
# One command, from a cold terminal to a finished Short.
#
#   ./run.sh "ATM은 어떻게 지폐를 셀까?"
#   ./run.sh --script-only "김치는 어떻게 발효될까?"   # stop before anything is paid for
#   ./run.sh --resume third                          # continue an existing project
#   ./run.sh --probe                                 # one cheap fal call, then stop
#   ./run.sh --doctor                                # just the environment check
#   ./run.sh --find-key                              # copy an API key from another .env
#   ./run.sh --setup --project-root D:/shorts-projects   # write config/settings.local.yaml
#   ./run.sh --fix-keys                              # fill blank Gemini keys from a filled one
#
# Everything that used to be a separate paste lives here: pulling, the virtualenv,
# the dependency install, the environment check, and the run. Each step says what
# it is doing and stops on the first real problem rather than failing three steps
# later with something unrelated.
set -uo pipefail

cd "$(dirname "$0")" || exit 1
GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[0;33m'; DIM='\033[2m'; OFF='\033[0m'
step() { printf "${DIM}--${OFF} %s\n" "$1"; }
ok()   { printf "${GREEN}ok${OFF} %s\n" "$1"; }
die()  { printf "${RED}stop${OFF} %s\n" "$1" >&2; exit 1; }
warn() { printf "${YELLOW}!!${OFF} %s\n" "$1" >&2; }

RESUME=""; SCRIPT_ONLY=0; TOPIC=""; MODE="run"
while [ $# -gt 0 ]; do
  case "$1" in
    --resume)      RESUME="${2:-}"; shift 2 ;;
    --script-only) SCRIPT_ONLY=1; shift ;;
    --skip-pull)   SKIP_PULL=1; shift ;;
    --probe)       MODE="probe"; shift ;;
    --doctor)      MODE="doctor"; shift ;;
    --find-key)    MODE="findkey"; shift ;;
    --setup)       MODE="setup"; shift ;;
    --fix-keys)    MODE="fixkeys"; shift ;;
    --dry-run)     SETUP_ARGS="${SETUP_ARGS:-} --dry-run"; shift ;;
    --project-root) SETUP_ARGS="--project-root ${2:-}"; shift 2 ;;
    --font)        SETUP_ARGS="${SETUP_ARGS:-} --font ${2:-}"; shift 2 ;;
    --force)       SETUP_ARGS="${SETUP_ARGS:-} --force"; shift ;;
    -h|--help)     sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)             TOPIC="$1"; shift ;;
  esac
done
if [ "$MODE" = "run" ]; then
  [ -n "$RESUME" ] || [ -n "$TOPIC" ] || die "give me a topic:  ./run.sh \"ATM은 어떻게 지폐를 셀까?\""
fi

# -- 1. latest code ---------------------------------------------------------
# `git pull` aborting on a dirty tree, and the run continuing anyway against
# half-old code, is what wasted a previous session. Stash first, always.
if [ -z "${SKIP_PULL:-}" ] && [ -d .git ]; then
  step "pulling the latest code"
  BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  git stash push --quiet --include-untracked --message "run.sh autostash" 2>/dev/null && STASHED=1 || STASHED=0
  if git pull --quiet --ff-only origin "$BRANCH" 2>/dev/null; then
    ok "up to date with origin/$BRANCH"
  else
    warn "could not fast-forward from origin/$BRANCH; running the code you have"
  fi
  [ "$STASHED" = "1" ] && git stash pop --quiet 2>/dev/null
fi

# -- 2. python --------------------------------------------------------------
# Two things differ on Windows, and this script assumed neither. `python3` is
# usually absent -- the launcher is `py`, and the name `python3` is often a
# Microsoft Store stub that answers to the name and runs nothing. And a venv
# there is .venv/Scripts/python.exe, not .venv/bin/python, so even a venv that
# built correctly was then looked for in a directory that does not exist.
venv_python() {
  for candidate in .venv/bin/python .venv/Scripts/python.exe; do
    [ -x "$candidate" ] && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

host_python() {
  for candidate in py python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    # Run something, rather than trusting the name: the Store stub exists on
    # PATH, prints a line about the Store, and cannot execute code.
    "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" \
      >/dev/null 2>&1 && { printf '%s' "$candidate"; return 0; }
  done
  return 1
}

if ! PY="$(venv_python)"; then
  step "creating the virtualenv (first run only, takes a minute)"
  HOST="$(host_python)" || die "no Python 3.12+ found. Install it:  winget install Python.Python.3.12
      (if 'python3' opens the Microsoft Store, that is the stub, not Python)"
  step "using $HOST"
  "$HOST" -m venv .venv || die "could not create .venv with $HOST; the output above says why"
  PY="$(venv_python)" || die ".venv was created but has no python in bin/ or Scripts/"
fi

if ! $PY -c "import shorts_factory" 2>/dev/null; then
  step "installing dependencies (first run only)"
  $PY -m pip install --quiet --upgrade pip >/dev/null 2>&1
  $PY -m pip install --quiet -e ".[dev]" || die "dependency install failed; the output above says why"
fi
ok "python ready"

# -- 3. the modes that stop before the pipeline -----------------------------
# Both of these run through $PY, which is the venv interpreter. Reaching for a
# bare `python` is what breaks on Ubuntu, where only python3 exists and only
# when the venv happens to be active.
if [ "$MODE" = "probe" ]; then
  step "one fal call, so a wrong field name costs a clip and not a run"
  exec $PY scripts/probe_fal.py "$@"
fi
if [ "$MODE" = "doctor" ]; then
  exec $PY scripts/doctor.py
fi
if [ "$MODE" = "setup" ]; then
  step "writing config/settings.local.yaml for this machine"
  # shellcheck disable=SC2086 -- SETUP_ARGS is a deliberate word list
  exec $PY scripts/setup_local.py ${SETUP_ARGS:-}
fi
if [ "$MODE" = "fixkeys" ]; then
  step "filling blank Gemini keys from one that has a value"
  # shellcheck disable=SC2086 -- SETUP_ARGS is a deliberate word list
  exec $PY scripts/fill_keys.py ${SETUP_ARGS:-}
fi
if [ "$MODE" = "findkey" ]; then
  exec bash scripts/import_key.sh "${TOPIC:-FAL}"
fi

# -- 4. environment ---------------------------------------------------------
# Checked before anything is billed, because every one of these has already
# failed a real run once: a missing key, a stripped ffmpeg, a mock left on.
step "checking ffmpeg, keys and providers"
if ! $PY scripts/doctor.py; then
  die "the check above failed. Fix what it names, then run this again."
fi

# -- 5. the run -------------------------------------------------------------
# Where finished projects land. Asked of the config rather than assumed to be
# ./projects, because project_root is routinely pointed at another drive to
# keep several GB of video off the one the code lives on.
latest_project() {
  $PY -c "
import sys
from pathlib import Path
from shorts_factory.config import load_config
try:
    root = Path(load_config('config').settings.project_root)
except Exception:
    sys.exit(0)
if not root.is_absolute():
    root = Path.cwd() / root
dirs = [d for d in root.glob('*') if d.is_dir()] if root.is_dir() else []
if dirs:
    print(max(dirs, key=lambda d: d.stat().st_mtime))
" 2>/dev/null
}

if [ -n "$RESUME" ]; then
  step "resuming $RESUME"
  $PY -m shorts_factory resume "$RESUME"; STATUS=$?
elif [ "$SCRIPT_ONLY" = "1" ]; then
  step "writing the script only -- nothing here is billed beyond research and the writer"
  $PY -m shorts_factory create "$TOPIC" --until write; STATUS=$?
else
  step "full run -- you get one look at the script before anything expensive happens"
  $PY -m shorts_factory create "$TOPIC"; STATUS=$?
fi

echo
if [ "$STATUS" = "0" ]; then
  LATEST="$(latest_project)"
  if [ -n "$LATEST" ] && [ -f "$LATEST/output/final.mp4" ]; then
    ok "done: $LATEST/output/final.mp4"
  elif [ -n "$LATEST" ] && [ -f "$LATEST/output/mock_preview.mp4" ]; then
    warn "this run used a mock provider somewhere, so it is $LATEST/output/mock_preview.mp4"
    warn "and not a real Short. config/settings.local.yaml is where providers are set."
  elif [ -n "$LATEST" ]; then
    ok "done: $LATEST"
  fi
else
  echo "the run stopped. Nothing already paid for is lost -- to carry on:"
  LATEST="$(latest_project)"
  [ -n "$LATEST" ] && echo "    ./run.sh --resume $(basename "$LATEST")"
fi
exit $STATUS
