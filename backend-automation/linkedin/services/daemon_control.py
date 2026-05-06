from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.utils import timezone

try:
    import fcntl  # type: ignore
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    import msvcrt


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
        if fcntl:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        else:  # Windows
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            else:  # Windows
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


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
        log_handle = LOG_FILE.open("a")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        cmd = [sys.executable, "manage.py", "rundaemon"]
        if handle:
            cmd.extend(["--handle", handle])

        try:
            process = subprocess.Popen(
                cmd,
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


def stop_daemon(timeout_seconds: float = 8.0) -> DaemonStatus:
    """Stop the running daemon process group, if present.

    The daemon is launched with ``start_new_session=True`` so we can terminate
    the whole process group cleanly via ``os.killpg``.
    """
    with _launch_lock():
        current = daemon_status()
        if not current.running or not current.pid:
            return current

        pid = current.pid
        try:
            # Prefer signaling the daemon process group so child processes
            # (if any) don't outlive the parent worker.
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            _remove_pid_file()
            return daemon_status()
        except Exception:
            # Fallback: terminate just the root process.
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                _remove_pid_file()
                return daemon_status()

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not _pid_is_running(pid):
                _remove_pid_file()
                return daemon_status()
            time.sleep(0.2)

        # Hard kill if graceful shutdown timed out.
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        # Give OS a short moment to reap the process.
        time.sleep(0.2)
        _remove_pid_file()
        return daemon_status()
