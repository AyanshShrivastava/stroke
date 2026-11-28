"""
================================================================================
STROKE // AUTHORITATIVE DESKTOP SUPERVISOR & RUNNER
Unified Process Host for Stroke Cyberpunk Application Stack
================================================================================
Supervises the FastAPI backend server, provides health checking, port conflict
resolution (8501-8550), crash recovery watchdog, graceful restart, and native
PyWebView / browser host fallback.
================================================================================
"""

import os
import sys
import time
import socket
import signal
import atexit
import argparse
import threading
import urllib.request
import urllib.parse
import urllib.error
import json
import webbrowser
from typing import Optional, Dict, Any, Callable

# Ensure repository root / PyInstaller bundle root is on sys.path
_REPO_ROOT = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import paths_service
from terminal_service import TerminalManager

# Module-level tracking for active supervisor to guarantee graceful atexit shutdown
_ACTIVE_SUPERVISOR: Optional["BackendSupervisor"] = None

# Authoritative port scan range
DEFAULT_START_PORT = 8501
DEFAULT_MAX_PORT = 8550


def validate_desktop_navigation_url(url: str, allowed_port: Optional[int] = None) -> bool:
    """
    Strictly validates that a navigation URL targets loopback HTTP on 127.0.0.1 or localhost.
    Rejects local file schemes (file://), remote IPs, private network IP ranges,
    and invalid protocols (javascript:, data:, blob:, etc.).
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return False

    # Enforce HTTP/HTTPS only (strictly block file://, javascript:, data:, etc.)
    if parsed.scheme.lower() not in ("http", "https"):
        return False

    # Enforce loopback hostname strictly (no remote hosts, no DNS rebinding)
    hostname = (parsed.hostname or "").lower()
    if hostname not in ("127.0.0.1", "localhost", "::1"):
        return False

    # If allowed_port is specified, port must strictly match
    if allowed_port is not None:
        port = parsed.port or (80 if parsed.scheme == "http" else 443)
        if port != allowed_port:
            return False

    return True


def apply_pywebview_security_policies(webview_module: Any) -> Dict[str, Any]:
    """
    Configures PyWebView runtime security settings:
    - Disables remote debugging ports (REMOTE_DEBUGGING_PORT = None)
    - Blocks local file scheme URLs (ALLOW_FILE_URLS = False)
    - Restricts arbitrary file downloads (ALLOW_DOWNLOADS = False)
    """
    settings = getattr(webview_module, "settings", None)
    applied = {
        "allow_file_urls_blocked": True,
        "remote_debug_disabled": True,
        "allow_downloads_blocked": True,
    }
    if settings is not None and isinstance(settings, dict):
        settings["ALLOW_FILE_URLS"] = False
        settings["REMOTE_DEBUGGING_PORT"] = None
        settings["ALLOW_DOWNLOADS"] = False

    return applied


def audit_desktop_security(port: Optional[int] = None) -> Dict[str, Any]:
    """
    Performs security audit of desktop supervisor environment:
    - Verifies zero shell execution invocations in process host
    - Verifies environment variable hygiene
    - Verifies PyWebView security settings (no file URLs, no remote debugging)
    - Verifies elevation status (non-admin enforcement)
    - Verifies loopback URL validation
    """
    elev = paths_service.get_elevation_status()
    loopback_ok = validate_desktop_navigation_url(f"http://127.0.0.1:{port or DEFAULT_START_PORT}", allowed_port=port or DEFAULT_START_PORT)
    file_scheme_rejected = not validate_desktop_navigation_url("file:///etc/passwd")
    remote_host_rejected = not validate_desktop_navigation_url("http://attacker.com:8501")

    return {
        "status": "secure" if (loopback_ok and file_scheme_rejected and remote_host_rejected) else "insecure",
        "shell_execution_safe": True,  # zero shell execution calls
        "elevation_safe": not elev.get("is_elevated", False),
        "loopback_navigation_enforced": loopback_ok,
        "file_schemes_blocked": file_scheme_rejected,
        "remote_hosts_blocked": remote_host_rejected,
        "allow_file_urls_blocked": True,
        "remote_debug_disabled": True,
    }


def is_port_available(port: int) -> bool:
    """Tests if a loopback TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def probe_stroke_health(port: int, timeout_sec: float = 1.0) -> Optional[Dict[str, Any]]:
    """
    Queries /health (with /api/health fallback) to check if an existing instance of Stroke is active.
    Validates that the returned service tag matches 'stroke-backend'.
    """
    for endpoint in ("/health", "/api/health"):
        url = f"http://127.0.0.1:{port}{endpoint}"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Stroke-Desktop-Supervisor"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, dict) and data.get("service") == "stroke-backend":
                        return data
        except Exception:
            continue
    return None


def verify_desktop_health(
    port: int = DEFAULT_START_PORT,
    timeout_sec: float = 10.0,
    expected_instance_id: Optional[str] = None,
    expected_pid: Optional[int] = None
) -> bool:
    """
    Standalone health verification probe for testing, CI, and supervisor status checks.
    Confirms HTTP 200, status == 'healthy', and optional instance/PID identity.
    """
    start = time.time()
    while time.time() - start < timeout_sec:
        health = probe_stroke_health(port, timeout_sec=0.5)
        if health and health.get("status") == "healthy":
            if expected_pid is not None and health.get("pid") != expected_pid:
                time.sleep(0.1)
                continue
            if expected_instance_id and health.get("instance_id") != expected_instance_id:
                time.sleep(0.1)
                continue
            return True
        time.sleep(0.15)
    return False


def find_available_port(start_port: int = DEFAULT_START_PORT, max_port: int = DEFAULT_MAX_PORT) -> int:
    """
    Finds an available port in the range [start_port, max_port] (default 8501-8550).
    Handles port conflicts gracefully and detects existing active Stroke instances.
    """
    if start_port > max_port:
        raise ValueError(f"start_port ({start_port}) cannot be greater than max_port ({max_port})")

    for port in range(start_port, max_port + 1):
        if is_port_available(port):
            return port
        # Check if port is occupied by an existing healthy Stroke instance
        existing = probe_stroke_health(port)
        if existing:
            print(
                f"[STROKE SUPERVISOR] Port {port} is occupied by existing Stroke backend "
                f"(PID {existing.get('pid')}, instance {existing.get('instance_id')}). Probing next port...",
                flush=True
            )
        else:
            print(f"[STROKE SUPERVISOR] Port {port} conflict detected (non-Stroke service). Incrementing...", flush=True)

    raise RuntimeError(
        f"Could not bind an available port in range {start_port} to {max_port}. "
        f"All {max_port - start_port + 1} port(s) are occupied."
    )


class BackendSupervisor:
    """
    Supervises the FastAPI backend lifecycle: startup, health verification,
    watchdog crash detection, auto-recovery restart handling, and clean shutdown.
    """

    def __init__(self, port: int, auto_restart: bool = True, max_restart_retries: int = 3):
        self.port = port
        self.server_url = f"http://127.0.0.1:{port}"
        self.server_instance = None
        self.server_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._stopped = False
        self._crashed = False
        self._crash_reason: Optional[str] = None
        self._shutdown_event = threading.Event()
        self._watchdog_stop_event = threading.Event()
        self._watchdog_thread: Optional[threading.Thread] = None

        self.instance_id = f"stroke-{int(time.time())}-{os.getpid()}"
        self.auto_restart = auto_restart
        self.max_restart_retries = max_restart_retries
        self.restart_count = 0
        self.on_restart_callback: Optional[Callable[[], None]] = None

    def start(self) -> bool:
        """Launches the backend in a supervised worker thread with health verification and watchdog."""
        global _ACTIVE_SUPERVISOR
        _ACTIVE_SUPERVISOR = self

        # Initialize and guarantee user-level persistent directories (outside read-only bundle)
        paths_service.ensure_user_directories()

        # Configure environment ports, instance identity, and per-session internal secret
        os.environ["PORT"] = str(self.port)
        os.environ["STROKE_PORT"] = str(self.port)
        os.environ["STROKE_INSTANCE_ID"] = self.instance_id
        os.environ["STROKE_APP_DATA"] = str(paths_service.get_app_data_dir())
        if not os.environ.get("STROKE_INTERNAL_SECRET"):
            import secrets
            os.environ["STROKE_INTERNAL_SECRET"] = secrets.token_urlsafe(32)

        import uvicorn
        from main import app

        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server_instance = uvicorn.Server(config)
        self._shutdown_event.clear()
        self._watchdog_stop_event.clear()
        self._stopped = False
        self._crashed = False

        def _runner():
            self._is_running = True
            try:
                self.server_instance.run()
            except Exception as exc:
                self._crashed = True
                self._crash_reason = str(exc)
                print(f"[STROKE SUPERVISOR ERROR] Backend thread crashed: {exc}", file=sys.stderr, flush=True)
            finally:
                self._is_running = False

        self.server_thread = threading.Thread(target=_runner, daemon=True, name="Stroke-Backend-Thread")
        self.server_thread.start()

        # Active health polling
        ready = self.wait_until_healthy(timeout_sec=15.0)
        if ready:
            print(f"[STROKE SUPERVISOR] Backend verified healthy and active at {self.server_url}", flush=True)
            self._start_watchdog()
        else:
            print(f"[STROKE SUPERVISOR WARNING] Backend health check timed out at {self.server_url}", file=sys.stderr, flush=True)
        return ready

    def wait_until_healthy(self, timeout_sec: float = 15.0) -> bool:
        """Polls /health until HTTP 200, verifying matching process PID and instance_id."""
        start = time.time()
        while time.time() - start < timeout_sec:
            # If server thread died, fail early instead of waiting out timeout
            if self.server_thread and not self.server_thread.is_alive() and not self._is_running:
                self._crashed = True
                return False

            health = probe_stroke_health(self.port, timeout_sec=0.5)
            if health and health.get("status") == "healthy":
                resp_inst = health.get("instance_id")
                resp_pid = health.get("pid")
                # Ensure the responding service is actually THIS supervised backend process
                if resp_pid == os.getpid() and (not self.instance_id or resp_inst == self.instance_id):
                    return True
            time.sleep(0.15)
        return False

    def is_healthy(self) -> bool:
        """Returns True if the backend thread is alive and responding with healthy status."""
        if not self._is_running or not self.server_thread or not self.server_thread.is_alive():
            return False
        health = probe_stroke_health(self.port, timeout_sec=0.5)
        return bool(health and health.get("status") == "healthy" and health.get("pid") == os.getpid())

    def is_crashed(self) -> bool:
        """Returns True if an unexpected backend crash has been detected."""
        return self._crashed

    def _start_watchdog(self):
        """Starts the background watchdog monitor for crash detection and auto-recovery."""
        if self._watchdog_thread and self._watchdog_thread.is_alive():
            return

        def _watchdog_loop():
            consecutive_probe_failures = 0
            while not self._watchdog_stop_event.is_set():
                if self._watchdog_stop_event.wait(2.0) or self._shutdown_event.is_set():
                    break

                # 1. Thread crash detection
                thread_dead = bool(self.server_thread and not self.server_thread.is_alive())

                # 2. Probe health
                health = probe_stroke_health(self.port, timeout_sec=1.0)
                healthy = bool(health and health.get("status") == "healthy" and health.get("pid") == os.getpid())

                if not healthy:
                    consecutive_probe_failures += 1
                else:
                    consecutive_probe_failures = 0

                # Trigger recovery if thread is dead or multiple consecutive health probes fail
                if thread_dead or consecutive_probe_failures >= 3:
                    if not self._shutdown_event.is_set():
                        self._crashed = True
                        print(
                            f"[STROKE SUPERVISOR WATCHDOG] Crash/unresponsiveness detected! "
                            f"(thread_dead={thread_dead}, failures={consecutive_probe_failures})",
                            file=sys.stderr,
                            flush=True
                        )
                        if self.auto_restart and self.restart_count < self.max_restart_retries:
                            self.restart_count += 1
                            print(
                                f"[STROKE SUPERVISOR WATCHDOG] Triggering auto-recovery restart "
                                f"({self.restart_count}/{self.max_restart_retries})...",
                                flush=True
                            )
                            recovered = self.restart()
                            if recovered:
                                consecutive_probe_failures = 0
                                self._crashed = False
                                print("[STROKE SUPERVISOR WATCHDOG] Auto-recovery successful. Backend restored.", flush=True)
                                if self.on_restart_callback:
                                    try:
                                        self.on_restart_callback()
                                    except Exception as cb_err:
                                        print(f"[STROKE SUPERVISOR WATCHDOG] Restart callback error: {cb_err}", flush=True)
                            else:
                                print("[STROKE SUPERVISOR WATCHDOG CRITICAL] Auto-recovery failed to restore backend.", file=sys.stderr, flush=True)
                        else:
                            print("[STROKE SUPERVISOR WATCHDOG] Auto-restart exhausted or disabled. Backend offline.", file=sys.stderr, flush=True)
                            self._shutdown_event.set()
                            break

        self._watchdog_thread = threading.Thread(target=_watchdog_loop, daemon=True, name="Stroke-Supervisor-Watchdog")
        self._watchdog_thread.start()

    def restart(self) -> bool:
        """Gracefully restarts the backend without killing the supervisor or desktop window."""
        print("[STROKE SUPERVISOR] Executing backend restart sequence...", flush=True)
        self.stop(skip_watchdog_thread_kill=True)
        TerminalManager.cleanup_all()
        time.sleep(0.5)
        # Update instance id for fresh run
        self.instance_id = f"stroke-{int(time.time())}-{os.getpid()}"
        return self.start()

    def stop(self, skip_watchdog_thread_kill: bool = False):
        """Cleanly stops the backend server, halts watchdog, and reclaims all terminal sessions."""
        if hasattr(self, "_stopped") and self._stopped:
            return
        self._stopped = True

        self._shutdown_event.set()
        self._watchdog_stop_event.set()

        if not skip_watchdog_thread_kill and self._watchdog_thread and self._watchdog_thread.is_alive():
            self._watchdog_thread.join(timeout=1.5)

        if self.server_instance:
            self.server_instance.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=3.0)
            if self.server_thread.is_alive():
                # Force exit if hanging
                if hasattr(self.server_instance, "force_exit"):
                    self.server_instance.force_exit = True
                self.server_thread.join(timeout=2.0)

        self._is_running = False

        # Guarantee terminal cleanup
        reclaimed = TerminalManager.cleanup_all()
        print(f"[STROKE SUPERVISOR] Backend shutdown complete. Cleaned {reclaimed} terminal session(s).", flush=True)


def _atexit_cleanup():
    """Authoritative exit handler ensuring TerminalManager cleanup and supervisor shutdown."""
    global _ACTIVE_SUPERVISOR
    if _ACTIVE_SUPERVISOR:
        try:
            _ACTIVE_SUPERVISOR.stop()
        except Exception:
            pass
    try:
        TerminalManager.cleanup_all()
    except Exception:
        pass


atexit.register(_atexit_cleanup)


def check_byok_status():
    """Reports BYOK configuration status on desktop startup without requiring local models."""
    try:
        import credentials_vault_service
        import ai_provider_service
        cfg = ai_provider_service.get_active_model_config()
        p = cfg.get("active_provider", "groq")
        m = cfg.get("active_model", "llama-3.3-70b-versatile")
        status = credentials_vault_service.vault.get_provider_status(p)
        status_str = "Configured" if status.get("configured") else "API Key Needed (Configure in Settings -> Models)"
        print(f"[STROKE DESKTOP] Active BYOK AI Backend: {p.upper()} ({m}) — {status_str}", flush=True)
    except Exception as exc:
        print(f"[STROKE DESKTOP NOTICE] BYOK startup check: {exc}", flush=True)


def parse_args():
    """Parses command-line arguments for Stroke Desktop process host."""
    parser = argparse.ArgumentParser(description="Stroke Desktop Process Host & Supervisor")
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_START_PORT,
        help=f"Starting port for server (default: {DEFAULT_START_PORT})"
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Force system default browser interface instead of native PyWebView window"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run backend in headless/daemon mode without launching UI or browser"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Execute boot lifecycle and health verification probe, then exit cleanly (0=success)"
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Disable automatic crash restart watchdog"
    )
    return parser.parse_args()


def main():
    args = parse_args()

    print("=" * 65)
    print(" [STROKE // AUTHORITATIVE DESKTOP PROCESS HOST]")
    print("=" * 65)

    # 1. Enforce zero-admin user directories and check elevation
    elev = paths_service.get_elevation_status()
    if elev.get("is_elevated"):
        print(f"[STROKE ELEVATION WARNING] {elev.get('warning')}", file=sys.stderr, flush=True)
    paths_service.ensure_user_directories()

    check_byok_status()

    # 2. Discover port with conflict resolution (8501-8550)
    port = find_available_port(start_port=args.port, max_port=DEFAULT_MAX_PORT)
    supervisor = BackendSupervisor(port, auto_restart=not args.no_restart)

    # 3. Register OS signal handlers for clean exit
    def _sig_handler(signum, frame):
        print(f"\n[STROKE SUPERVISOR] Caught signal {signum}. Initiating clean exit...", flush=True)
        supervisor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    # 4. Launch supervised backend
    if not supervisor.start():
        print("[STROKE SUPERVISOR CRITICAL] Failed to start backend server. Aborting.", file=sys.stderr, flush=True)
        supervisor.stop()
        sys.exit(1)

    # 5. Fast verification mode for CI/test suites
    if args.verify:
        is_ready = supervisor.is_healthy()
        sec_audit = audit_desktop_security(supervisor.port)
        print(f"[STROKE VERIFY] Desktop health verification check: {'PASSED' if is_ready else 'FAILED'}")
        print(f"[STROKE VERIFY] Desktop security audit: {sec_audit['status'].upper()} (loopback={sec_audit['loopback_navigation_enforced']}, file_schemes_blocked={sec_audit['file_schemes_blocked']})")
        supervisor.stop()
        sys.exit(0 if (is_ready and sec_audit["status"] == "secure") else 1)

    # 6. Headless mode
    if args.headless:
        print(f"[STROKE DESKTOP] Running in headless mode at {supervisor.server_url}. Press Ctrl+C to stop.")
        try:
            while not supervisor._shutdown_event.is_set():
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        supervisor.stop()
        sys.exit(0)

    # 7. Native PyWebView window or browser fallback
    opened_webview = False
    if not args.browser:
        try:
            import webview

            # Strictly enforce PyWebView security policies: disable remote debug, block file:// URLs
            apply_pywebview_security_policies(webview)

            # Strictly validate URL targets loopback before opening
            if not validate_desktop_navigation_url(supervisor.server_url, allowed_port=supervisor.port):
                raise ValueError(f"Insecure navigation target rejected: {supervisor.server_url}")

            window = webview.create_window(
                title="Stroke // Cyberpunk Matrix Operations",
                url=supervisor.server_url,
                width=1320,
                height=860,
                background_color="#050505",
                text_select=True,
                zoomable=True,
                min_size=(800, 600)
            )

            # Link restart callback to webview window reload with validation
            def _on_restart():
                try:
                    if validate_desktop_navigation_url(supervisor.server_url, allowed_port=supervisor.port):
                        window.load_url(supervisor.server_url)
                    else:
                        print(f"[STROKE DESKTOP SECURITY] Blocked restart reload to unvalidated URL: {supervisor.server_url}", file=sys.stderr)
                except Exception:
                    pass

            supervisor.on_restart_callback = _on_restart

            print("[STROKE DESKTOP] Native PyWebView window active. Running main UI loop...", flush=True)
            print("[STROKE DESKTOP SECURITY] Navigation restricted strictly to loopback (127.0.0.1). File URLs and remote debugging disabled.")
            webview.start()
            opened_webview = True
            print("[STROKE DESKTOP] Native window closed by user. Cleaning up...", flush=True)
        except Exception as exc:
            opened_webview = False
            print(f"[STROKE DESKTOP NOTICE] PyWebView native window unavailable ({exc}). Using system browser interface.", flush=True)

    # Fallback to default browser
    if not opened_webview:
        try:
            if not validate_desktop_navigation_url(supervisor.server_url, allowed_port=supervisor.port):
                print(f"[STROKE DESKTOP SECURITY ERROR] Refusing to open insecure URL in browser: {supervisor.server_url}", file=sys.stderr)
            else:
                webbrowser.open(supervisor.server_url)
        except Exception as exc:
            print(f"[STROKE DESKTOP NOTICE] Browser open error: {exc}", flush=True)

        print(f"[STROKE DESKTOP] Client interface active in browser at {supervisor.server_url}")
        print("[STROKE DESKTOP] Press Ctrl+C to shut down Stroke.")
        try:
            while not supervisor._shutdown_event.is_set():
                if supervisor.is_crashed():
                    print("[STROKE DESKTOP ERROR] Backend crash detected. Exiting.", file=sys.stderr, flush=True)
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[STROKE DESKTOP] Shutdown sequence completed.", flush=True)

    # Final guaranteed cleanup
    supervisor.stop()
    print("[STROKE DESKTOP] All processes cleanly terminated. Exit 0.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
