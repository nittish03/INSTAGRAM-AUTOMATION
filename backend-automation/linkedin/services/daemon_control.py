from __future__ import annotations

import json
import os
import fcntl
import subprocess
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone


PID_FILE = Path(settings.BASE_DIR) / ".leadway_daemon.pid"
LOCK_FILE = Path(settings.BASE_DIR) / ".leadway_daemon.lock"
LOG_FILE = Path(settings.BASE_DIR) / "logs" / "daemon.log"


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None
    started_at: str


@contextmanager
def _launch_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _read_pid_file() -> dict:
    try:
        return json.loads(PID_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pid_file(pid: int) -> None:
    PID_FILE.write_text(
        json.dumps(
            {
                "pid": pid,
                "started_at": timezone.now().isoformat(),
            }
        )
    )


def _remove_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def _pid_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def daemon_status() -> DaemonStatus:
    data = _read_pid_file()
    pid = data.get("pid")
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid = None

    running = _pid_is_running(pid)
    if pid and not running:
        _remove_pid_file()
        pid = None

    return DaemonStatus(
        running=running,
        pid=pid,
        started_at=str(data.get("started_at") or ""),
    )


def launch_daemon() -> DaemonStatus:
    with _launch_lock():
        current = daemon_status()
        if current.running:
            return current

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log_handle = LOG_FILE.open("a")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        try:
            process = subprocess.Popen(
                [sys.executable, "manage.py", "rundaemon"],
                cwd=settings.BASE_DIR,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        finally:
            log_handle.close()
        _write_pid_file(process.pid)
    return daemon_status()
