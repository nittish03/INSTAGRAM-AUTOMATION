#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend-automation"
FRONTEND_DIR="$ROOT_DIR/frontend-automation"
BACKEND_VENV="$BACKEND_DIR/.venv"
MODE="system"
MODE_SET=0
RUN_DAEMON=0

usage() {
  echo "Usage: ./run-dev.sh [current|system] [--daemon|-d]"
  echo "  system (default): open separate macOS Terminal tabs"
  echo "  current: run servers in this terminal session"
  echo "  --daemon, -d: also run the LinkedIn daemon"
}

for arg in "$@"; do
  case "$arg" in
    current|system)
      if [[ "$MODE_SET" -eq 1 ]]; then
        echo "Only one mode may be provided."
        usage
        exit 1
      fi
      MODE="$arg"
      MODE_SET=1
      ;;
    --daemon|--with-daemon|-d)
      RUN_DAEMON=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $arg"
      usage
      exit 1
      ;;
  esac
done

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
  echo "  cd backend-automation && python3.12 -m venv .venv"
  exit 1
fi

backend_cmd="cd \"$BACKEND_DIR\" && source .venv/bin/activate && python manage.py runserver"
daemon_cmd="cd \"$BACKEND_DIR\" && source .venv/bin/activate && python manage.py rundaemon"
frontend_cmd="cd \"$FRONTEND_DIR\" && npm run dev"

start_in_current_terminal() {
  cleanup() {
    echo
    echo "Stopping dev processes..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
    [[ -n "${DAEMON_PID:-}" ]] && kill "$DAEMON_PID" 2>/dev/null || true
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

  if [[ "$RUN_DAEMON" -eq 1 ]]; then
    (
      cd "$BACKEND_DIR"
      source ".venv/bin/activate"
      python manage.py rundaemon
    ) &
    DAEMON_PID=$!
  fi

  echo
  echo "Running:"
  echo "  Backend  -> http://127.0.0.1:8000 (pid: $BACKEND_PID)"
  echo "  Frontend -> http://localhost:3000 (pid: $FRONTEND_PID)"
  if [[ "$RUN_DAEMON" -eq 1 ]]; then
    echo "  Daemon   -> rundaemon (pid: $DAEMON_PID)"
  fi
  echo "Press Ctrl+C to stop all."
  echo
  wait
}

start_in_system_terminal() {
  if ! command -v osascript >/dev/null 2>&1; then
    echo "osascript not found. Falling back to current terminal."
    start_in_current_terminal
    return
  fi

  local backend_cmd_escaped frontend_cmd_escaped daemon_cmd_escaped
  backend_cmd_escaped="${backend_cmd//\"/\\\"}"
  frontend_cmd_escaped="${frontend_cmd//\"/\\\"}"
  daemon_cmd_escaped="${daemon_cmd//\"/\\\"}"

  if [[ "$RUN_DAEMON" -eq 1 ]]; then
    echo "Opening 3 separate Terminal tabs:"
  else
    echo "Opening 2 separate Terminal tabs:"
  fi
  echo "  1) Backend: $backend_cmd"
  echo "  2) Frontend: $frontend_cmd"
  if [[ "$RUN_DAEMON" -eq 1 ]]; then
    echo "  3) Daemon: $daemon_cmd"
  fi

  osascript <<EOF
tell application "Terminal"
  activate
  if (count of windows) = 0 then
    do script "$backend_cmd_escaped"
  else
    do script "$backend_cmd_escaped" in selected tab of front window
  end if
  do script "$frontend_cmd_escaped"
  if $RUN_DAEMON = 1 then
    do script "$daemon_cmd_escaped"
  end if
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
    usage
    exit 1
    ;;
esac
