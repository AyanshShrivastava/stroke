"""
================================================================================
STROKE // DESKTOP SUPERVISOR & PACKAGING RELIABILITY TEST SUITE
================================================================================
Tests:
- Port availability scanning and conflict resolution (8501-8550)
- Instance identification and health check verification
- Watchdog crash detection and auto-recovery
- Graceful shutdown and guaranteed TerminalManager cleanup
- Standalone health probe and CLI verification mode
- PyInstaller architecture detection and universal2 handling
- Read-only bundle location guarantees (zero mutable user state bundled)
================================================================================
"""

import os
import sys
import time
import socket
import subprocess
import pytest
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import desktop
from desktop import (
    is_port_available,
    probe_stroke_health,
    verify_desktop_health,
    find_available_port,
    BackendSupervisor,
    _atexit_cleanup,
    DEFAULT_START_PORT,
    DEFAULT_MAX_PORT,
)
from terminal_service import TerminalManager
import build_desktop


class TestDesktopSupervisorPortAndHealth:
    """Tests port scanning, conflict detection, and health probing."""

    def test_is_port_available_with_real_socket(self):
        """Validates socket bind and release detection on loopback."""
        # Find a temporary dynamic port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_sock:
            probe_sock.bind(("127.0.0.1", 0))
            test_port = probe_sock.getsockname()[1]

        # Port is now closed and should be available
        assert is_port_available(test_port) is True

        # Now bind and hold the port open
        held_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            held_sock.bind(("127.0.0.1", test_port))
            held_sock.listen(1)
            # Port should now report busy / unavailable
            assert is_port_available(test_port) is False
        finally:
            held_sock.close()

        # Once closed, should be available again
        assert is_port_available(test_port) is True

    def test_find_available_port_scans_and_resolves_conflicts(self):
        """Verifies port scan order, conflict reporting, and existing Stroke instance handling."""
        # Case 1: First port is free
        with patch("desktop.is_port_available", side_effect=[True]):
            port = find_available_port(start_port=8501, max_port=8550)
            assert port == 8501

        # Case 2: Port 8501 occupied by existing Stroke, 8502 occupied by foreign service, 8503 free
        mock_stroke_health = {
            "status": "healthy",
            "service": "stroke-backend",
            "pid": 99999,
            "instance_id": "stroke-existing-instance"
        }
        with patch("desktop.is_port_available", side_effect=[False, False, True]):
            with patch("desktop.probe_stroke_health", side_effect=[mock_stroke_health, None]):
                port = find_available_port(start_port=8501, max_port=8550)
                assert port == 8503

    def test_find_available_port_exhaustion_raises(self):
        """Verifies RuntimeError when all ports in the scan range (8501-8550) are busy."""
        with patch("desktop.is_port_available", return_value=False):
            with patch("desktop.probe_stroke_health", return_value=None):
                with pytest.raises(RuntimeError) as exc_info:
                    find_available_port(start_port=8501, max_port=8510)
                assert "range 8501 to 8510" in str(exc_info.value)
                assert "All 10 port(s) are occupied" in str(exc_info.value)

    def test_find_available_port_invalid_range_raises(self):
        """Validates error when start_port > max_port."""
        with pytest.raises(ValueError):
            find_available_port(start_port=8550, max_port=8501)

    def test_probe_stroke_health_validates_service_identity(self):
        """Verifies health check parsing: accepts stroke-backend, rejects foreign payloads or errors."""
        # Valid response
        valid_json = b'{"status": "healthy", "service": "stroke-backend", "pid": 1234, "instance_id": "inst-1"}'
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = valid_json
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            data = probe_stroke_health(8501)
            assert data is not None
            assert data["service"] == "stroke-backend"
            assert data["status"] == "healthy"

        # Foreign service response (HTTP 200 but not stroke)
        foreign_json = b'{"status": "ok", "service": "some-other-service"}'
        mock_resp.read.return_value = foreign_json
        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert probe_stroke_health(8501) is None

        # Network/connection error
        with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
            assert probe_stroke_health(8501) is None

    def test_verify_desktop_health_with_identity_checks(self):
        """Tests verify_desktop_health with matching and mismatched PID and instance_id."""
        mock_data = {
            "status": "healthy",
            "service": "stroke-backend",
            "pid": 5555,
            "instance_id": "stroke-test-id"
        }
        with patch("desktop.probe_stroke_health", return_value=mock_data):
            # Matches all
            assert verify_desktop_health(port=8501, expected_pid=5555, expected_instance_id="stroke-test-id") is True
            # Mismatched pid
            assert verify_desktop_health(port=8501, timeout_sec=0.3, expected_pid=9999) is False
            # Mismatched instance_id
            assert verify_desktop_health(port=8501, timeout_sec=0.3, expected_instance_id="wrong-id") is False


class TestBackendSupervisorLifecycleAndCleanups:
    """Tests supervisor boot, crash detection, graceful shutdown, and TerminalManager cleanup."""

    def test_terminal_manager_cleanup_on_supervisor_stop(self):
        """
        Creates an active terminal session and confirms that supervisor.stop()
        reliably stops and purges all sessions from TerminalManager.
        """
        # Ensure clean initial state
        TerminalManager.cleanup_all()

        # Create a real terminal session
        session_info = TerminalManager.create_terminal(caller_uid="internal_daemon")
        session_id = session_info["session_id"]
        assert session_id in [t["session_id"] for t in TerminalManager.list_terminals()]

        # Initialize a supervisor (without running full uvicorn)
        sup = BackendSupervisor(port=8599, auto_restart=False)
        assert len(TerminalManager.list_terminals()) >= 1

        # Execute stop()
        sup.stop()

        # Verify all terminal sessions are terminated and cleaned up
        assert len(TerminalManager.list_terminals()) == 0

    def test_atexit_cleanup_reclaims_terminals(self):
        """Verifies that module-level _atexit_cleanup() reclaims orphaned sessions."""
        TerminalManager.cleanup_all()
        session_info = TerminalManager.create_terminal(caller_uid="internal_daemon")
        assert len(TerminalManager.list_terminals()) == 1

        _atexit_cleanup()
        assert len(TerminalManager.list_terminals()) == 0

    def test_supervisor_fast_failure_detection(self):
        """Verifies that wait_until_healthy returns False immediately if the worker thread died."""
        sup = BackendSupervisor(port=8599, auto_restart=False)
        # Simulate worker thread that died
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        sup.server_thread = mock_thread
        sup._is_running = False

        start = time.time()
        ready = sup.wait_until_healthy(timeout_sec=10.0)
        elapsed = time.time() - start

        # Must fail fast without sleeping for 10 seconds
        assert ready is False
        assert elapsed < 1.0
        assert sup.is_crashed() is True

    def test_supervisor_watchdog_detects_crash_and_attempts_recovery(self):
        """Verifies that the watchdog monitor detects thread termination and triggers recovery."""
        sup = BackendSupervisor(port=8599, auto_restart=True, max_restart_retries=2)
        sup._is_running = True
        sup.restart_count = 0

        # Mock server thread as already dead
        dead_thread = MagicMock()
        dead_thread.is_alive.return_value = False
        sup.server_thread = dead_thread

        # Track restart call
        restart_called = False
        def mock_restart():
            nonlocal restart_called
            restart_called = True
            sup._is_running = True
            live_thread = MagicMock()
            live_thread.is_alive.return_value = True
            sup.server_thread = live_thread
            return True

        sup.restart = mock_restart

        # Mock probe health to report offline
        with patch("desktop.probe_stroke_health", return_value=None):
            sup._start_watchdog()
            # Give watchdog loop time to trigger (it checks every 2s)
            time.sleep(2.5)
            sup.stop()

        assert restart_called is True


class TestDesktopPackagingOptions:
    """Verifies build_desktop.py packaging options, architectures, and read-only bundle safety."""

    def test_normalize_arch(self):
        """Tests canonical CPU architecture mapping."""
        assert build_desktop.normalize_arch("arm64") == "arm64"
        assert build_desktop.normalize_arch("aarch64") == "arm64"
        assert build_desktop.normalize_arch("x86_64") == "x86_64"
        assert build_desktop.normalize_arch("AMD64") == "x86_64"
        assert build_desktop.normalize_arch("x64") == "x86_64"
        assert build_desktop.normalize_arch("universal2") == "universal2"

    def test_rosetta_detection(self):
        """Tests that detect_rosetta_translation returns a boolean without error."""
        result = build_desktop.detect_rosetta_translation()
        assert isinstance(result, bool)

    def test_universal2_compatibility_check(self):
        """Tests check_universal2_compatibility returns (bool, str)."""
        compatible, msg = build_desktop.check_universal2_compatibility()
        assert isinstance(compatible, bool)
        assert isinstance(msg, str)
        assert len(msg) > 0

    def test_readonly_bundle_manifest_validation(self):
        """
        Verifies that validate_bundle_manifest strictly catches and blocks
        any mutable or sensitive user files from being embedded in read-only bundle locations.
        """
        sep = ":"

        # Safe static files
        safe_items = [
            f"index.html{sep}.",
            f"requirements.txt{sep}.",
            f"data/vfx_data.json{sep}data",
            f"data/VFX_ASSET_MANIFEST.md{sep}data",
        ]
        violations = build_desktop.validate_bundle_manifest(safe_items, sep)
        assert violations == []

        # Violations (mutable user database or secret files)
        unsafe_items = [
            f"index.html{sep}.",
            f"data/.vault_key{sep}data",
            f"data/local_firestore_db.json{sep}data",
            f".env{sep}.",
            f"approved_workspaces.json{sep}.",
        ]
        violations = build_desktop.validate_bundle_manifest(unsafe_items, sep)
        assert len(violations) == 4
        assert any(".vault_key" in v for v in violations)
        assert any("local_firestore_db.json" in v for v in violations)
        assert any(".env" in v for v in violations)
        assert any("approved_workspaces.json" in v for v in violations)

    def test_build_desktop_check_config_cli(self):
        """Tests running build_desktop.py --check-config via subprocess."""
        cmd = [sys.executable, os.path.join(_REPO_ROOT, "build_desktop.py"), "--check-config"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        assert proc.returncode == 0
        assert "STROKE BUILD CHECK-CONFIG SUCCESSFUL" in proc.stdout
        assert "All packaging options and read-only location checks PASSED" in proc.stdout


class TestDesktopSubprocessVerifyCLI:
    """Verifies invoking desktop.py --verify from command line."""

    def test_desktop_verify_cli_command(self):
        """Executes desktop.py --verify and confirms clean pass and zero exit code."""
        cmd = [sys.executable, os.path.join(_REPO_ROOT, "desktop.py"), "--verify"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        assert proc.returncode == 0
        assert "Desktop health verification check: PASSED" in proc.stdout
        assert "Backend shutdown complete" in proc.stdout
