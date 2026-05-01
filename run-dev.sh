#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/Automation_backend"
FRONTEND_DIR="$ROOT_DIR/Automation_frontend"
BACKEND_VENV="$BACKEND_DIR/.venv"
MODE="${1:-system}"

if [[ ! -d "$BACKEND_DIR" ]]; then
  echo "Missing backend directory: $BACKEND_DIR"
  exit 1
fi

if [[ ! -d "$FRONTEND_DIR" ]]; then
  echo "Missing frontend directory: $FRONTEND_DIR"
  exit 1
fi

if [[ ! -d "$BACKEND_VENV" ]]; then
  echo "Missing backend virtualenv: $BACKEND_VENV"
  echo "Create it first (example):"
  echo "  cd Automation_backend && python3.12 -m venv .venv"
  exit 1
fi

backend_cmd="cd \"$BACKEND_DIR\" && source .venv/bin/activate && python manage.py runserver"
frontend_cmd="cd \"$FRONTEND_DIR\" && npm run dev"

start_in_current_terminal() {
  cleanup() {
    echo
    echo "Stopping backend and frontend..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null || true
  }

  trap cleanup EXIT INT TERM

  echo "Starting in current terminal session..."
  (
    cd "$BACKEND_DIR"
    source ".venv/bin/activate"
    python manage.py runserver
  ) &
  BACKEND_PID=$!

  (
    cd "$FRONTEND_DIR"
    npm run dev
  ) &
  FRONTEND_PID=$!

  echo
  echo "Running:"
  echo "  Backend  -> http://127.0.0.1:8000 (pid: $BACKEND_PID)"
  echo "  Frontend -> http://localhost:3000 (pid: $FRONTEND_PID)"
  echo "Press Ctrl+C to stop both."
  echo
  wait
}

start_in_system_terminal() {
  if ! command -v osascript >/dev/null 2>&1; then
    echo "osascript not found. Falling back to current terminal."
    start_in_current_terminal
    return
  fi

  local backend_cmd_escaped frontend_cmd_escaped
  backend_cmd_escaped="${backend_cmd//\"/\\\"}"
  frontend_cmd_escaped="${frontend_cmd//\"/\\\"}"

  echo "Opening 2 separate Terminal tabs:"
  echo "  1) Backend: $backend_cmd"
  echo "  2) Frontend: $frontend_cmd"

  osascript <<EOF
tell application "Terminal"
  activate
  if (count of windows) = 0 then
    do script "$backend_cmd_escaped"
  else
    do script "$backend_cmd_escaped" in selected tab of front window
  end if
  do script "$frontend_cmd_escaped"
end tell
EOF

  echo "Launched in separate Terminal tabs."
}

case "$MODE" in
  current)
    start_in_current_terminal
    ;;
  system)
    start_in_system_terminal
    ;;
  *)
    echo "Usage: ./run-dev.sh [current|system]"
    echo "  system (default): open separate macOS Terminal tabs"
    echo "  current: run both servers in this terminal session"
    exit 1
    ;;
esac
