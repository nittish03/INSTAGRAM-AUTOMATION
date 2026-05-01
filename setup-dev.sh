#!/usr/bin/env bash
# One-shot setup for any machine.
# Brings backend (Python venv + deps + Playwright + migrations) and
# frontend (Node deps) to a known-good, identical state.
#
# Re-runs are safe (idempotent).

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/Automation_backend"
FRONTEND_DIR="$ROOT_DIR/Automation_frontend"
BACKEND_VENV="$BACKEND_DIR/.venv"
PY_VERSION_FILE="$BACKEND_DIR/.python-version"

step() { printf "\n\033[1;36m== %s ==\033[0m\n" "$*"; }
warn() { printf "\033[1;33m[warn] %s\033[0m\n" "$*"; }
fail() { printf "\033[1;31m[error] %s\033[0m\n" "$*"; exit 1; }

[[ -d "$BACKEND_DIR" ]] || fail "Missing $BACKEND_DIR"
[[ -d "$FRONTEND_DIR" ]] || fail "Missing $FRONTEND_DIR"

# ---------- Python ----------
step "Resolving Python interpreter"

PY_REQUIRED=""
if [[ -f "$PY_VERSION_FILE" ]]; then
  PY_REQUIRED="$(tr -d '\r\n[:space:]' < "$PY_VERSION_FILE")"
  echo "Pinned Python: $PY_REQUIRED (from .python-version)"
fi

PY_BIN=""
if [[ -n "$PY_REQUIRED" ]] && command -v pyenv >/dev/null 2>&1; then
  pyenv install -s "$PY_REQUIRED"
  PY_BIN="$(pyenv prefix "$PY_REQUIRED")/bin/python"
fi

if [[ -z "$PY_BIN" ]]; then
  PY_MAJOR_MINOR="${PY_REQUIRED%.*}"
  for cand in "python${PY_MAJOR_MINOR:-3.12}" python3.12 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      PY_BIN="$(command -v "$cand")"
      break
    fi
  done
fi

[[ -n "$PY_BIN" ]] || fail "No suitable Python interpreter found"
echo "Using: $PY_BIN ($($PY_BIN --version 2>&1))"

# ---------- Backend venv ----------
step "Backend virtualenv ($BACKEND_VENV)"

if [[ ! -x "$BACKEND_VENV/bin/python" ]]; then
  "$PY_BIN" -m venv "$BACKEND_VENV"
fi

VENV_PY="$BACKEND_VENV/bin/python"
echo "Venv python: $($VENV_PY --version 2>&1)"

step "Installing backend requirements"
"$VENV_PY" -m pip install --upgrade pip wheel
"$VENV_PY" -m pip install -r "$BACKEND_DIR/requirements/local.txt"

step "Installing Playwright Chromium"
"$VENV_PY" -m playwright install chromium

step "Running Django checks + migrations"
( cd "$BACKEND_DIR" && "$VENV_PY" manage.py check )
( cd "$BACKEND_DIR" && "$VENV_PY" manage.py migrate --no-input )

# ---------- Frontend ----------
step "Frontend dependencies"
if ! command -v npm >/dev/null 2>&1; then
  fail "npm is required. Install Node.js first (e.g. via nvm)."
fi
( cd "$FRONTEND_DIR" && npm install )

step "Setup complete"
cat <<EOF

You can now start dev servers with:
  ./run-dev.sh           # opens separate terminal tabs (default)
  ./run-dev.sh current   # both servers in this terminal
  ./run-dev-single.sh    # convenience wrapper for 'current'

To rerun this setup later (e.g. after pulling new commits):
  ./setup-dev.sh
EOF
