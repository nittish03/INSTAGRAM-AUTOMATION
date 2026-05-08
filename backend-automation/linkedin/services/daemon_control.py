from __future__ import annotations

import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone as dt_timezone
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.utils import timezone

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt


IS_WINDOWS = platform.system().lower().startswith("win")


@lru_cache(maxsize=1)
def _state_dir() -> Path:
    """Daemon state directory.

    Important: state files MUST live OUTSIDE ``settings.BASE_DIR``. The Django
    dev server (runserver) and project file watchers (Watchman, fsevents) treat
    the project directory as a hot path; heartbeat/pid/log writes inside it
    cause the dev server to restart, producing the dreaded
    ``ECONNREFUSED 127.0.0.1:8000`` cascade in the frontend the moment the
    daemon is launched.
    """
    override = os.environ.get("LEADWAY_STATE_DIR", "").strip()
    base = Path(override).expanduser() if override else Path.home() / ".leadway"
    base.mkdir(parents=True, exist_ok=True)
    return base


PID_FILE = _state_dir() / "daemon.pid"
LOCK_FILE = _state_dir() / "daemon.lock"
LOG_FILE = _state_dir() / "daemon.log"
HEARTBEAT_FILE = _state_dir() / "daemon.heartbeat"


# Throttle heartbeat writes so dashboard polling does not hammer the disk.
# 5 seconds is well within the daemon's ``heartbeat_timeout_seconds`` default of 45s.
_HEARTBEAT_THROTTLE_SECONDS = 5.0
_last_heartbeat_write_at: float = 0.0


@dataclass
class DaemonStatus:
    running: bool
    pid: int | None
    started_at: str


def read_daemon_logs(limit: int = 300) -> dict:
    """Return recent daemon logs for the Control Center live log view."""
    safe_limit = max(20, min(int(limit or 300), 2000))
    if not LOG_FILE.exists():
        return {
            "exists": False,
            "path": str(LOG_FILE),
            "lines": [],
            "sizeBytes": 0,
            "modifiedAt": "",
        }

    try:
        content = LOG_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {
            "exists": True,
            "path": str(LOG_FILE),
            "lines": ["[log read error] Unable to read daemon log file."],
            "sizeBytes": 0,
            "modifiedAt": "",
        }

    all_lines = content.splitlines()
    tail = all_lines[-safe_limit:]
    stat = LOG_FILE.stat()
    return {
        "exists": True,
        "path": str(LOG_FILE),
        "lines": tail,
        "sizeBytes": int(stat.st_size),
        "modifiedAt": datetime.fromtimestamp(stat.st_mtime, tz=dt_timezone.utc).isoformat(),
    }


@contextmanager
def _launch_lock():
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("w") as lock_file:
        if fcntl:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # Windows
            # msvcrt.locking needs at least one byte at the current offset.
            lock_file.write("\0")
            lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # Windows
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass


def _read_pid_file() -> dict:
    try:
        return json.loads(PID_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_pid_file(pid: int, *, launcher_pid: int | None = None) -> None:
    PID_FILE.write_text(
        json.dumps(
            {
                "pid": pid,
                "launcher_pid": launcher_pid,
                "started_at": timezone.now().isoformat(),
            }
        )
    )


def _remove_pid_file() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def touch_daemon_heartbeat(*, force: bool = False) -> None:
    """Mark frontend/backend liveness for the daemon's auto-stop check.

    Called on every dashboard poll, so we throttle disk writes to avoid
    needless I/O pressure on the project directory.
    """
    global _last_heartbeat_write_at
    now = time.monotonic()
    if not force and (now - _last_heartbeat_write_at) < _HEARTBEAT_THROTTLE_SECONDS:
        return
    try:
        HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(
            json.dumps({"at": timezone.now().isoformat()}),
        )
        _last_heartbeat_write_at = now
    except OSError:
        # Heartbeat is best-effort; do not break API responses if disk is full.
        pass


def read_daemon_heartbeat_age_seconds() -> float | None:
    """Return heartbeat staleness in seconds, or None if no heartbeat exists."""
    try:
        payload = json.loads(HEARTBEAT_FILE.read_text())
        raw = payload.get("at")
        if not raw:
            return None
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        now = datetime.now(ts.tzinfo or dt_timezone.utc)
        return max((now - ts).total_seconds(), 0.0)
    except Exception:
        return None


def _pid_is_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        # Windows raises generic OSError (e.g. WinError 11) for stale/invalid
        # PIDs. Treat as "not running" instead of breaking /api/daemon/status/.
        return False
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


def _detach_popen_kwargs() -> dict:
    """Return Popen kwargs that detach the child from this process.

    On POSIX we use ``start_new_session=True`` so we can later signal the
    daemon's whole process group via ``os.killpg``. On Windows we use
    creation flags equivalent to ``setsid`` + detach: a new process group +
    a detached process so the child does not inherit our console handles
    (which on Windows would otherwise tie the daemon's lifecycle to the
    dev server's terminal and crash both on launch).
    """
    if IS_WINDOWS:
        creationflags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "DETACHED_PROCESS", 0)
        )
        return {
            "creationflags": creationflags,
            # Keep stdout/stderr handles open for the log file pipe.
            "close_fds": False,
        }
    return {"start_new_session": True}


def launch_daemon(handle: str | None = None) -> DaemonStatus:
    """Spawn ``manage.py rundaemon``, optionally pinning it to a Django user.

    When ``handle`` is provided the daemon will only operate against that
    user's LinkedIn profiles. Multi-tenant frontends pass
    ``request.user.username`` so each admin's launch uses their own
    accounts even though the host can only run one daemon at a time.
    """
    with _launch_lock():
        current = daemon_status()
        if current.running:
            return current

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Fresh daemon run starts with a clean log buffer so the Control
        # Center "Daemon Logs (Live)" tab only shows the current run.
        log_handle = LOG_FILE.open("w", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        cmd = [sys.executable, "manage.py", "rundaemon"]
        if handle:
            cmd.extend(["--handle", handle])
        launcher_pid = os.getpid()
        cmd.extend(["--launcher-pid", str(launcher_pid)])
        touch_daemon_heartbeat(force=True)

        popen_kwargs = {
            "cwd": settings.BASE_DIR,
            "env": env,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            **_detach_popen_kwargs(),
        }

        try:
            process = subprocess.Popen(cmd, **popen_kwargs)
        finally:
            log_handle.close()
        _write_pid_file(process.pid, launcher_pid=launcher_pid)
    return daemon_status()


def _terminate_process_tree(pid: int, *, hard: bool = False) -> bool:
    """Best-effort signal/kill of the daemon process and its children.

    Returns True if the OS reported success at sending the signal/kill.
    Cross-platform: uses ``taskkill /T`` on Windows and ``os.killpg`` on
    POSIX.
    """
    if IS_WINDOWS:
        cmd = ["taskkill", "/T", "/PID", str(pid)]
        if hard:
            cmd.insert(2, "/F")
        try:
            result = subprocess.run(cmd, capture_output=True, check=False)
            return result.returncode == 0
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
                return True
            except (ProcessLookupError, OSError):
                return False

    sig = signal.SIGKILL if hard else signal.SIGTERM
    try:
        os.killpg(pid, sig)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        try:
            os.kill(pid, sig)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False


def stop_daemon(timeout_seconds: float = 8.0) -> DaemonStatus:
    """Stop the running daemon process group, if present.

    Cross-platform: graceful TERM first, then hard KILL after timeout.
    """
    with _launch_lock():
        current = daemon_status()
        if not current.running or not current.pid:
            return current

        pid = current.pid
        _terminate_process_tree(pid, hard=False)

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not _pid_is_running(pid):
                _remove_pid_file()
                return daemon_status()
            time.sleep(0.2)

        # Hard kill if graceful shutdown timed out.
        _terminate_process_tree(pid, hard=True)

        # Give OS a short moment to reap the process.
        time.sleep(0.2)
        _remove_pid_file()
        return daemon_status()
