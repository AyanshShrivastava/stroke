"""
================================================================================
STROKE // AUTHORITATIVE DESKTOP SUPERVISOR & RUNNER
Unified Process Host for Stroke Cyberpunk Application Stack
================================================================================
Supervises the FastAPI backend server, provides health checking, port conflict
resolution, crash recovery, graceful restart, and native PyWebView / browser host.
================================================================================
"""

import os
import sys
import time
import socket
import signal
import threading
import urllib.request
import urllib.error
import json
import webbrowser
from typing import Optional

# Ensure repository root is on sys.path
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from terminal_service import TerminalManager


def is_port_available(port: int) -> bool:
    """Tests if a loopback TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


def probe_stroke_health(port: int, timeout_sec: float = 1.0) -> Optional[dict]:
    """Queries /health to check if an existing instance of Stroke is active."""
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Stroke-Desktop-Supervisor"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("service") == "stroke-backend":
                    return data
    except Exception:
        pass
    return None


def find_available_port(start_port: int = 8501, max_attempts: int = 50) -> int:
    """
    Finds an available port starting from start_port.
    Handles port conflicts and reports whether an existing Stroke service was detected.
    """
    port = start_port
    for _ in range(max_attempts):
        if is_port_available(port):
            return port
        # Check if port is occupied by an existing healthy Stroke instance
        existing = probe_stroke_health(port)
        if existing:
            print(f"[STROKE SUPERVISOR] Port {port} is occupied by existing Stroke backend (PID {existing.get('pid')}). Probing next port...", flush=True)
        else:
            print(f"[STROKE SUPERVISOR] Port {port} conflict detected (non-Stroke service). Incrementing...", flush=True)
        port += 1

    raise RuntimeError(f"Could not bind an available port in range {start_port} to {start_port + max_attempts}")


class BackendSupervisor:
    """
    Supervises the FastAPI backend lifecycle: startup, health verification,
    crash recovery, restart handling, and clean shutdown.
    """

    def __init__(self, port: int):
        self.port = port
        self.server_url = f"http://127.0.0.1:{port}"
        self.server_instance = None
        self.server_thread: Optional[threading.Thread] = None
        self._is_running = False
        self._shutdown_event = threading.Event()
        self.instance_id = f"stroke-{int(time.time())}-{os.getpid()}"

    def start(self) -> bool:
        """Launches the backend in a supervised worker thread."""
        import uvicorn
        from main import app

        # Configure environment port for child handlers
        os.environ["PORT"] = str(self.port)
        os.environ["STROKE_PORT"] = str(self.port)
        os.environ["STROKE_INSTANCE_ID"] = self.instance_id

        config = uvicorn.Config(
            app=app,
            host="127.0.0.1",
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self.server_instance = uvicorn.Server(config)

        def _runner():
            self._is_running = True
            try:
                self.server_instance.run()
            except Exception as exc:
                print(f"[STROKE SUPERVISOR ERROR] Backend thread crashed: {exc}", file=sys.stderr, flush=True)
            finally:
                self._is_running = False

        self.server_thread = threading.Thread(target=_runner, daemon=True, name="Stroke-Backend-Thread")
        self.server_thread.start()

        # Active health polling
        ready = self.wait_until_healthy(timeout_sec=15.0)
        if ready:
            print(f"[STROKE SUPERVISOR] Backend verified healthy and active at {self.server_url}", flush=True)
        else:
            print(f"[STROKE SUPERVISOR WARNING] Backend health check timed out at {self.server_url}", file=sys.stderr, flush=True)
        return ready

    def wait_until_healthy(self, timeout_sec: float = 15.0) -> bool:
        """Polls /health until HTTP 200, verifying matching process PID and instance_id."""
        start = time.time()
        while time.time() - start < timeout_sec:
            health = probe_stroke_health(self.port, timeout_sec=0.5)
            if health and health.get("status") == "healthy":
                resp_inst = health.get("instance_id")
                resp_pid = health.get("pid")
                # Ensure the responding service is actually THIS supervised backend process
                if resp_pid == os.getpid() and (not self.instance_id or resp_inst == self.instance_id):
                    return True
            time.sleep(0.15)
        return False

    def restart(self) -> bool:
        """Gracefully restarts the backend without killing the supervisor or desktop window."""
        print("[STROKE SUPERVISOR] Executing backend restart sequence...", flush=True)
        self.stop()
        TerminalManager.cleanup_all()
        time.sleep(0.5)
        return self.start()

    def stop(self):
        """Cleanly stops the backend server and reclaims all terminal sessions."""
        if self.server_instance:
            self.server_instance.should_exit = True
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=3.0)
        self._is_running = False
        reclaimed = TerminalManager.cleanup_all()
        print(f"[STROKE SUPERVISOR] Backend shutdown complete. Cleaned {reclaimed} terminal session(s).", flush=True)


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


def main():
    print("=" * 65)
    print(" [STROKE // AUTHORITATIVE DESKTOP PROCESS HOST]")
    print("=" * 65)

    check_byok_status()

    # Discover port with conflict resolution
    port = find_available_port(start_port=8501)
    supervisor = BackendSupervisor(port)

    # Register OS signal handlers for clean exit
    def _sig_handler(signum, frame):
        print(f"\n[STROKE SUPERVISOR] Caught signal {signum}. Initiating clean exit...", flush=True)
        supervisor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    # Launch supervised backend
    if not supervisor.start():
        print("[STROKE SUPERVISOR CRITICAL] Failed to start backend server. Aborting.", file=sys.stderr, flush=True)
        supervisor.stop()
        sys.exit(1)

    # Attempt to open native PyWebView window
    opened_webview = False
    try:
        import webview
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
        print("[STROKE DESKTOP] Native PyWebView window active. Running main UI loop...", flush=True)
        webview.start()
        # When webview.start() returns cleanly, the window was opened and closed by the user
        opened_webview = True
        print("[STROKE DESKTOP] Native window closed by user. Cleaning up...", flush=True)
    except Exception as exc:
        opened_webview = False
        print(f"[STROKE DESKTOP NOTICE] PyWebView native window unavailable ({exc}). Using system browser interface.", flush=True)

    # Fallback to default browser
    if not opened_webview:
        webbrowser.open(supervisor.server_url)
        print(f"[STROKE DESKTOP] Client interface active in default browser at {supervisor.server_url}")
        print("[STROKE DESKTOP] Press Ctrl+C to shut down Stroke.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[STROKE DESKTOP] Shutdown sequence completed.", flush=True)

    # Final cleanup
    supervisor.stop()
    print("[STROKE DESKTOP] All processes cleanly terminated. Exit 0.", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
