import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from linkedin.services import daemon_control
from linkedin.services.daemon_control import DaemonStatus

os.environ["LEADPILOT_ENCRYPTION_KEY"] = "a" * 32


def _assert_child_is_detached(test, kwargs):
    """Daemon must spawn a child detached from the dev server.

    POSIX uses ``start_new_session``; Windows uses ``creationflags`` with the
    detached-process / new-process-group bits. Either is acceptable.
    """
    detached = bool(
        kwargs.get("start_new_session") or kwargs.get("creationflags")
    )
    test.assertTrue(detached, "daemon child must be detached from launcher")


def _assert_dashboard_heartbeat_enabled(test, cmd):
    test.assertIn("--heartbeat-timeout-seconds", cmd)
    timeout_idx = cmd.index("--heartbeat-timeout-seconds")
    test.assertEqual(cmd[timeout_idx + 1], "45.0")


class DaemonControlServiceTests(TestCase):
    def test_launch_daemon_starts_rundaemon_once(self):
        with TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "daemon.pid"
            lock_file = Path(tmp) / "daemon.lock"
            log_file = Path(tmp) / "logs" / "daemon.log"
            process = MagicMock(pid=12345)

            with patch.object(daemon_control, "PID_FILE", pid_file), patch.object(
                daemon_control,
                "LOCK_FILE",
                lock_file,
            ), patch.object(
                daemon_control,
                "LOG_FILE",
                log_file,
            ), patch.object(daemon_control, "_pid_is_running", side_effect=[False, True]), patch.object(
                daemon_control.subprocess,
                "Popen",
                return_value=process,
            ) as mock_popen:
                status = daemon_control.launch_daemon()

        self.assertTrue(status.running)
        self.assertEqual(status.pid, 12345)
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertIn("manage.py", args[0])
        self.assertIn("rundaemon", args[0])
        self.assertIn("--launcher-pid", args[0])
        _assert_dashboard_heartbeat_enabled(self, args[0])
        self.assertNotIn("--handle", args[0])
        _assert_child_is_detached(self, kwargs)

    def test_launch_daemon_passes_handle_to_subprocess(self):
        with TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "daemon.pid"
            lock_file = Path(tmp) / "daemon.lock"
            log_file = Path(tmp) / "logs" / "daemon.log"
            process = MagicMock(pid=99999)

            with patch.object(daemon_control, "PID_FILE", pid_file), patch.object(
                daemon_control,
                "LOCK_FILE",
                lock_file,
            ), patch.object(
                daemon_control,
                "LOG_FILE",
                log_file,
            ), patch.object(daemon_control, "_pid_is_running", side_effect=[False, True]), patch.object(
                daemon_control.subprocess,
                "Popen",
                return_value=process,
            ) as mock_popen:
                daemon_control.launch_daemon(handle="alice")

        args, kwargs = mock_popen.call_args
        self.assertIn("--handle", args[0])
        self.assertIn("manage.py", args[0])
        self.assertIn("rundaemon", args[0])
        handle_idx = args[0].index("--handle")
        self.assertEqual(args[0][handle_idx + 1], "alice")
        self.assertIn("--launcher-pid", args[0])
        _assert_dashboard_heartbeat_enabled(self, args[0])
        _assert_child_is_detached(self, kwargs)

    def test_state_files_live_outside_project_dir(self):
        """Daemon state must not be written into BASE_DIR or Django will reload."""
        from django.conf import settings

        base = Path(settings.BASE_DIR).resolve()
        for path in (
            daemon_control.PID_FILE,
            daemon_control.LOCK_FILE,
            daemon_control.LOG_FILE,
            daemon_control.HEARTBEAT_FILE,
        ):
            resolved = Path(path).resolve()
            try:
                resolved.relative_to(base)
            except ValueError:
                continue
            self.fail(
                f"daemon state file {resolved} is inside BASE_DIR {base}; "
                "this triggers runserver autoreload on every write"
            )

    def test_touch_daemon_heartbeat_throttles_writes(self):
        with TemporaryDirectory() as tmp:
            heartbeat = Path(tmp) / "daemon.heartbeat"
            with patch.object(daemon_control, "HEARTBEAT_FILE", heartbeat):
                daemon_control._last_heartbeat_write_at = 0.0
                daemon_control.touch_daemon_heartbeat(force=True)
                first_mtime = heartbeat.stat().st_mtime_ns

                # Immediate second call should be skipped by the throttle.
                daemon_control.touch_daemon_heartbeat()
                second_mtime = heartbeat.stat().st_mtime_ns

        self.assertEqual(
            first_mtime,
            second_mtime,
            "throttled heartbeat should not rewrite file on rapid polls",
        )

    def test_launch_daemon_does_not_spawn_duplicate_when_pid_running(self):
        with TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "daemon.pid"
            lock_file = Path(tmp) / "daemon.lock"
            log_file = Path(tmp) / "logs" / "daemon.log"
            pid_file.write_text(json.dumps({"pid": 12345, "started_at": "now"}))

            with patch.object(daemon_control, "PID_FILE", pid_file), patch.object(
                daemon_control,
                "LOCK_FILE",
                lock_file,
            ), patch.object(
                daemon_control,
                "LOG_FILE",
                log_file,
            ), patch.object(daemon_control, "_pid_is_running", return_value=True), patch.object(
                daemon_control.subprocess,
                "Popen",
            ) as mock_popen:
                status = daemon_control.launch_daemon()

        self.assertTrue(status.running)
        self.assertEqual(status.pid, 12345)
        mock_popen.assert_not_called()

    def test_stop_daemon_when_running_removes_pid_file(self):
        with TemporaryDirectory() as tmp:
            pid_file = Path(tmp) / "daemon.pid"
            lock_file = Path(tmp) / "daemon.lock"
            log_file = Path(tmp) / "logs" / "daemon.log"
            pid_file.write_text(json.dumps({"pid": 12345, "started_at": "now"}))

            with patch.object(daemon_control, "PID_FILE", pid_file), patch.object(
                daemon_control, "LOCK_FILE", lock_file
            ), patch.object(
                daemon_control, "LOG_FILE", log_file
            ), patch.object(
                daemon_control, "_pid_is_running", side_effect=[True, False, False]
            ), patch.object(
                daemon_control,
                "_terminate_process_tree",
                return_value=True,
            ) as mock_terminate:
                status = daemon_control.stop_daemon(timeout_seconds=0.1)

        self.assertFalse(status.running)
        self.assertIsNone(status.pid)
        mock_terminate.assert_called()

    def test_pid_is_running_handles_generic_oserror(self):
        with patch.object(daemon_control.os, "kill", side_effect=OSError("winerror11")):
            self.assertFalse(daemon_control._pid_is_running(12345))


class DaemonControlApiTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="daemon_staff", password="testpass123", is_staff=True)
        self.viewer = User.objects.create_user(username="daemon_viewer", password="testpass123")

    def test_launch_requires_staff(self):
        self.client.login(username="daemon_viewer", password="testpass123")

        response = self.client.post("/api/daemon/launch/")

        self.assertEqual(response.status_code, 403)

    def test_launch_is_disabled_in_production(self):
        self.client.login(username="daemon_staff", password="testpass123")

        with patch.dict(os.environ, {"ENV": "production"}):
            response = self.client.post("/api/daemon/launch/")

        self.assertEqual(response.status_code, 409)

    def test_launch_is_disabled_for_non_local_hosts_by_default(self):
        self.client.login(username="daemon_staff", password="testpass123")

        with override_settings(ALLOWED_HOSTS=["example.com", "testserver"]):
            response = self.client.post("/api/daemon/launch/", HTTP_HOST="example.com")

        self.assertEqual(response.status_code, 409)

    def test_launch_can_be_explicitly_enabled_for_non_local_hosts(self):
        self.client.login(username="daemon_staff", password="testpass123")
        status = DaemonStatus(running=True, pid=12345, started_at="2026-05-04T13:30:00Z")

        with override_settings(ALLOWED_HOSTS=["example.com", "testserver"]), patch.dict(
            os.environ,
            {"DASHBOARD_DAEMON_LAUNCH_ENABLED": "true"},
            clear=False,
        ), patch("linkedin.services.daemon_control.launch_daemon", return_value=status):
            response = self.client.post("/api/daemon/launch/", HTTP_HOST="example.com")

        self.assertEqual(response.status_code, 200)

    def test_launch_returns_daemon_status(self):
        self.client.login(username="daemon_staff", password="testpass123")
        status = DaemonStatus(running=True, pid=12345, started_at="2026-05-04T13:30:00Z")

        with patch("linkedin.services.daemon_control.launch_daemon", return_value=status) as mock_launch:
            response = self.client.post("/api/daemon/launch/")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["daemon"]["running"])
        self.assertEqual(response.json()["daemon"]["pid"], 12345)
        mock_launch.assert_called_once_with(handle="daemon_staff")

    def test_launch_error_response_is_sanitized(self):
        self.client.login(username="daemon_staff", password="testpass123")

        with patch("linkedin.services.daemon_control.launch_daemon", side_effect=OSError("/secret/path")):
            response = self.client.post("/api/daemon/launch/")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"], "Failed to launch daemon")
        self.assertNotIn("secret", response.content.decode())

    def test_status_returns_daemon_status(self):
        self.client.login(username="daemon_staff", password="testpass123")
        status = DaemonStatus(running=False, pid=None, started_at="")

        with patch("linkedin.services.daemon_control.daemon_status", return_value=status):
            response = self.client.get("/api/daemon/status/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["daemon"]["running"])

    def test_stop_requires_staff(self):
        self.client.login(username="daemon_viewer", password="testpass123")

        response = self.client.post("/api/daemon/stop/")

        self.assertEqual(response.status_code, 403)

    def test_stop_returns_daemon_status(self):
        self.client.login(username="daemon_staff", password="testpass123")
        status = DaemonStatus(running=False, pid=None, started_at="")

        with patch("linkedin.services.daemon_control.stop_daemon", return_value=status) as mock_stop:
            response = self.client.post("/api/daemon/stop/")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["daemon"]["running"])
        mock_stop.assert_called_once()
