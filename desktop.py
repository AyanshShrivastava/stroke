"""
================================================================================
STROKE // DESKTOP CLIENT ENTRYPOINT
Native Window Wrapper for Stroke Cyberpunk Application Stack
================================================================================
Spawns the stateless FastAPI REST backend on a background thread and opens
a dedicated native application window (PyWebView) or system browser interface.
================================================================================
"""

import os
import sys
import time
import socket
import threading
import webbrowser

def find_available_port(start_port=8765):
    """Finds an open loopback TCP port starting from start_port."""
    port = start_port
    while port < 9999:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
            port += 1
    return start_port

def run_backend(port: int):
    """Executes the FastAPI server via Uvicorn in a daemonized background thread."""
    import uvicorn
    from main import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

def check_and_bootstrap_ai():
    """Checks if offline Llama 3.2 GGUF exists; if not, triggers background bootstrap."""
    try:
        import download_model
        if not download_model.is_model_installed():
            print("[STROKE DESKTOP] Offline AI weights not detected. Initiating background auto-download...", flush=True)
            t = threading.Thread(target=download_model.download_model, daemon=True)
            t.start()
        else:
            print("[STROKE DESKTOP] Verified offline Llama 3.2 AI weights in models/ directory.", flush=True)
    except Exception as exc:
        print(f"[STROKE DESKTOP NOTICE] Model bootstrap note: {exc}", flush=True)

def main():
    print("=" * 65)
    print(" [STROKE // NATIVE CYBERPUNK DESKTOP RUNNER]")
    print("=" * 65)

    # Check and bootstrap offline AI model
    check_and_bootstrap_ai()

    port = find_available_port(8765)
    server_url = f"http://127.0.0.1:{port}"

    # Start FastAPI backend thread
    server_thread = threading.Thread(target=run_backend, args=(port,), daemon=True)
    server_thread.start()

    print(f"[STROKE DESKTOP] Backend daemon active at {server_url}")
    print("[STROKE DESKTOP] Initializing native window canvas...")
    time.sleep(1.2)

    # Attempt to open in a frameless/native PyWebView window
    opened_webview = False
    try:
        import webview
        window = webview.create_window(
            title="Stroke // Cyberpunk Matrix Operations",
            url=server_url,
            width=1320,
            height=860,
            background_color="#050505",
            text_select=True,
            zoomable=True,
            min_size=(800, 600)
        )
        opened_webview = True
        webview.start()
    except Exception as exc:
        print(f"[STROKE DESKTOP NOTICE] PyWebView fallback ({exc}). Opening in system browser interface.")

    # Fallback: Launch default browser and keep process alive
    if not opened_webview:
        webbrowser.open(server_url)
        print(f"[STROKE DESKTOP] Client interface active in default browser.")
        print("[STROKE DESKTOP] Press Ctrl+C in this terminal to shut down Stroke.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[STROKE DESKTOP] Shutdown sequence completed.")
            sys.exit(0)

if __name__ == "__main__":
    main()
