"""
================================================================================
STROKE // AUTHORITATIVE DESKTOP PACKAGING SCRIPT (PyInstaller)
Compiles Stroke into a Standalone Native Executable (.app for macOS, .exe for Windows)
================================================================================
Usage:
  python build_desktop.py [--arch arm64|x86_64|universal2] [--zip]
================================================================================
"""

import os
import sys
import platform
import subprocess
import shutil
import argparse


def parse_args():
    parser = argparse.ArgumentParser(description="Stroke Desktop Packaging Script")
    parser.add_argument(
        "--arch",
        choices=["arm64", "x86_64", "universal2"],
        default=None,
        help="Target CPU architecture (macOS only). Defaults to host architecture."
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Automatically generate distribution ZIP archive in dist/"
    )
    return parser.parse_args()


def run_build():
    args = parse_args()
    system = platform.system()
    host_arch = platform.machine()
    target_arch = args.arch or host_arch

    print("=" * 65)
    print(f" [STROKE COMPILER // PLATFORM: {system.upper()} // ARCH: {target_arch}]")
    print("=" * 65)

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[STROKE BUILD] PyInstaller not detected. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "pywebview", "llama-cpp-python"])

    # Separator for PyInstaller --add-data (; on Windows, : on Unix)
    sep = ";" if system == "Windows" else ":"

    # Core data files to embed in standalone bundle
    add_data = [
        f"index.html{sep}.",
        f"download_model.py{sep}.",
        f"vfx_service.py{sep}.",
        f"mcp_bridge.py{sep}.",
        f"requirements.txt{sep}.",
        f".env.example{sep}."
    ]

    # Embed Elemental Worlds VFX Database assets safely (exclude .vault_key, tokens, user data)
    static_vfx_assets = [
        os.path.join("data", "vfx_data.json"),
        os.path.join("data", "vfx_dump.txt"),
        os.path.join("data", "VFX_ASSET_MANIFEST.md"),
    ]
    for asset in static_vfx_assets:
        if os.path.exists(asset):
            add_data.append(f"{asset}{sep}data")

    # NOTE: Neural models (GGUF) are kept OUTSIDE the read-only application bundle.
    # At runtime, models are downloaded/managed in user application data (~/Library/Application Support/Stroke/Models).
    print("[STROKE BUILD] Neural models are stored externally in user app storage to maintain clean updates.")

    base_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=Stroke",
        "--noconfirm",
        "--clean",
        "--windowed" if system != "Linux" else "--onedir",
    ]

    # Target architecture handling on macOS
    if system == "Darwin" and args.arch:
        if args.arch == "universal2":
            print("[STROKE BUILD NOTICE] Building universal2 binary requires both arm64 and x86_64 dylibs.")
        base_cmd.extend(["--target-arch", args.arch])

    for item in add_data:
        src = item.split(sep)[0]
        if os.path.exists(src):
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
        "parallel_agent_system",
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
    print(" [STROKE BUILD SUCCESSFUL]")
    print(f" Artifacts directory: {dist_dir}")

    if system == "Darwin":
        app_path = os.path.join(dist_dir, "Stroke.app")
        print(f" macOS App Bundle:    {app_path}")
        print(f" Architecture:        {target_arch} ({'Apple Silicon' if target_arch == 'arm64' else 'Intel' if target_arch == 'x86_64' else 'Universal'})")
        print(" Code Signing:        Ad-hoc / Local (Apple Developer ID required for Gatekeeper notarization)")
        if args.zip:
            zip_name = f"Stroke-macOS-{target_arch}.zip"
            zip_path = os.path.join(dist_dir, zip_name)
            print(f"[STROKE BUILD] Archiving into {zip_name}...")
            subprocess.check_call(["zip", "-r", zip_name, "Stroke.app"], cwd=dist_dir)
            print(f" Distribution ZIP:    {zip_path}")

    elif system == "Windows":
        exe_path = os.path.join(dist_dir, "Stroke", "Stroke.exe")
        print(f" Windows Executable:  {exe_path}")
        print(f" Architecture:        {target_arch}")
        print(" Distribution Format: Standalone Portable Folder / ZIP")
        print(" Installer Status:    Portable release (Run Stroke.exe directly). For an installer wizard, use Inno Setup.")
        if args.zip:
            zip_name = f"Stroke-Windows-{target_arch}.zip"
            zip_path = os.path.join(dist_dir, zip_name)
            print(f"[STROKE BUILD] Archiving into {zip_name}...")
            shutil.make_archive(os.path.join(dist_dir, f"Stroke-Windows-{target_arch}"), "zip", os.path.join(dist_dir, "Stroke"))
            print(f" Distribution ZIP:    {zip_path}")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    run_build()
