"""
================================================================================
STROKE // DESKTOP PACKAGING SCRIPT (PyInstaller)
Compiles Stroke into a Standalone Native Executable (.app for macOS, .exe for Windows)
================================================================================
Usage:
  python build_desktop.py
================================================================================
"""

import os
import sys
import platform
import subprocess
import shutil

def run_build():
    system = platform.system()
    print("=" * 65)
    print(f" [STROKE COMPILER // TARGET PLATFORM: {system.upper()}]")
    print("=" * 65)

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[STROKE BUILD] PyInstaller not detected. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "pywebview", "llama-cpp-python"])

    # Separator for PyInstaller --add-data (; on Windows, : on Unix)
    sep = ";" if system == "Windows" else ":"

    # Data files to embed in standalone binary
    add_data = [
        f"index.html{sep}.",
        f"download_model.py{sep}.",
        f"vfx_service.py{sep}.",
        f"mcp_bridge.py{sep}.",
        f"requirements.txt{sep}.",
        f".env.example{sep}."
    ]

    # Embed Elemental Worlds VFX Database assets safely (exclude .vault_key and user data)
    static_vfx_assets = [
        os.path.join("data", "vfx_data.json"),
        os.path.join("data", "vfx_dump.txt"),
        os.path.join("data", "VFX_ASSET_MANIFEST.md"),
    ]
    for asset in static_vfx_assets:
        if os.path.exists(asset):
            add_data.append(f"{asset}{sep}data")

    # If offline neural models exist locally, bundle them directly for all-in-one distribution
    if os.path.exists("models"):
        add_data.append(f"models{sep}models")

    base_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=Stroke",
        "--noconfirm",
        "--clean",
        "--windowed" if system != "Linux" else "--onedir",
    ]

    for item in add_data:
        if os.path.exists(item.split(sep)[0]):
            base_cmd.extend(["--add-data", item])

    # Hidden imports required by FastAPI, Uvicorn, BYOK AI Providers, and Stroke Services
    hidden_imports = [
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "pydantic",
        "httpx",
        "firebase_admin",
        "google.cloud.firestore",
        "google.cloud.firestore_v1",
        "webview",
        "llama_cpp",
        "paths_service",
        "backup_service",
        "workspace_service",
        "file_service",
        "isolated_workspace",
        "model_download_service",
        "credentials_vault_service",
        "ai_provider_service",
        "project_context_service",
        "multimodal_service",
        "luau_analyzer",
        "agent_orchestrator",
        "auth_service",
        "local_firestore",
        "eval_harness",
        "observability",
        "migration_service",
        "terminal_service",
        "coding_loop",
        "github_service",
        "keyring",
        "cryptography",
    ]

    for imp in hidden_imports:
        base_cmd.extend(["--hidden-import", imp])

    base_cmd.append("desktop.py")

    print("[STROKE BUILD] Executing compilation command...")
    print(" ".join(base_cmd))
    subprocess.check_call(base_cmd)

    dist_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")
    print("\n" + "=" * 65)
    print(f" [STROKE BUILD SUCCESSFUL]")
    print(f" Artifacts available at: {dist_dir}")
    if system == "Darwin":
        print(f" macOS Application: {os.path.join(dist_dir, 'Stroke.app')}")
    elif system == "Windows":
        print(f" Windows Executable: {os.path.join(dist_dir, 'Stroke', 'Stroke.exe')}")
    print("=" * 65 + "\n")

if __name__ == "__main__":
    run_build()
