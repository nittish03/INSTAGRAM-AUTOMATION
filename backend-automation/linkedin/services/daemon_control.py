from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone as dt_timezone
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
HEARTBEAT_FILE = Path(settings.BASE_DIR) / ".leadway_daemon.heartbeat"


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


def touch_daemon_heartbeat() -> None:
    """Mark frontend/backend app heartbeat for daemon liveness checks."""
    HEARTBEAT_FILE.write_text(
        json.dumps({"at": timezone.now().isoformat()}),
    )


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
        # Fresh daemon run should start with a clean log buffer so Control
        # Center "Daemon Logs (Live)" only shows the current run.
        log_handle = LOG_FILE.open("w")
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        cmd = [sys.executable, "manage.py", "rundaemon"]
        if handle:
            cmd.extend(["--handle", handle])
        launcher_pid = os.getpid()
        cmd.extend(["--launcher-pid", str(launcher_pid)])
        touch_daemon_heartbeat()

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
        _write_pid_file(process.pid, launcher_pid=launcher_pid)
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
