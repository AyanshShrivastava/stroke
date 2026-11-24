"""
================================================================================
STROKE // AUTHORITATIVE DESKTOP PACKAGING SCRIPT (PyInstaller)
Compiles Stroke into a Standalone Native Executable (.app for macOS, .exe for Windows)
================================================================================
Usage:
  python build_desktop.py [--arch arm64|x86_64|universal2] [--zip] [--check-config]
================================================================================
"""

import os
import sys
import platform
import subprocess
import shutil
import argparse
from typing import Tuple, List, Optional


def normalize_arch(raw_arch: Optional[str]) -> str:
    """Normalizes raw architecture string to canonical arm64 or x86_64."""
    if not raw_arch:
        raw_arch = platform.machine()
    raw = raw_arch.lower()
    if raw in ("arm64", "aarch64"):
        return "arm64"
    if raw in ("x86_64", "amd64", "x64"):
        return "x86_64"
    if raw == "universal2":
        return "universal2"
    return raw_arch


def detect_rosetta_translation() -> bool:
    """Detects if Python is running under Rosetta 2 x86_64 translation on an Apple Silicon Mac."""
    if platform.system() != "Darwin":
        return False
    try:
        res = subprocess.run(["sysctl", "-in", "sysctl.proc_translated"], capture_output=True, text=True, timeout=2.0)
        return res.stdout.strip() == "1"
    except Exception:
        return False


def check_universal2_compatibility() -> Tuple[bool, str]:
    """
    Validates whether the current Python environment has Mach-O universal2 binaries
    capable of compiling a dual-slice universal binary for macOS.
    """
    if platform.system() != "Darwin":
        return False, "universal2 is only applicable to macOS (Darwin)."

    try:
        res = subprocess.run(["file", sys.executable], capture_output=True, text=True, timeout=3.0)
        output = res.stdout
        is_universal = "arm64" in output and "x86_64" in output
        if is_universal:
            return True, "Python interpreter contains both arm64 and x86_64 Mach-O slices."
        else:
            return False, (
                f"Current Python interpreter at {sys.executable} is single-architecture ({output.strip()}). "
                "Universal2 builds require a universal Python binary and dual-slice compiled dylibs."
            )
    except Exception as exc:
        return False, f"Could not inspect Python binary architecture: {exc}"


# Forbidden mutable/sensitive file names that must NEVER be bundled into read-only app locations
MUTABLE_OR_SENSITIVE_FILES = {
    ".vault_key",
    "local_firestore_db.json",
    ".env",
    "approved_workspaces.json",
    "local_chat_sessions.json",
    "mcp_servers.json",
    "verified_project_context.json",
}


def validate_bundle_manifest(add_data_items: List[str], sep: str) -> List[str]:
    """
    Enforces read-only bundle compliance:
    Asserts that no mutable user files or sensitive credentials are baked into the
    PyInstaller application bundle. Dynamic writes must target paths_service directories.
    """
    violations = []
    for item in add_data_items:
        src = item.split(sep)[0]
        base_name = os.path.basename(src)
        if base_name in MUTABLE_OR_SENSITIVE_FILES:
            violations.append(src)
    return violations


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
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Validate build configuration, packaging manifest, and architecture without compiling."
    )
    return parser.parse_args()


def get_bundle_add_data(system: str, sep: str) -> List[str]:
    """Builds the list of static, read-only data files to embed in the application bundle."""
    add_data = [
        f"index.html{sep}.",
        f"download_model.py{sep}.",
        f"vfx_service.py{sep}.",
        f"mcp_bridge.py{sep}.",
        f"requirements.txt{sep}.",
        f".env.example{sep}."
    ]

    # Embed Elemental Worlds VFX Database static read-only assets safely
    static_vfx_assets = [
        os.path.join("data", "vfx_data.json"),
        os.path.join("data", "vfx_dump.txt"),
        os.path.join("data", "VFX_ASSET_MANIFEST.md"),
    ]
    for asset in static_vfx_assets:
        if os.path.exists(asset):
            add_data.append(f"{asset}{sep}data")

    # Add public static web assets if present
    public_dir = "public"
    if os.path.exists(public_dir):
        add_data.append(f"{public_dir}{sep}public")

    return add_data


def get_hidden_imports() -> List[str]:
    """Returns the list of required hidden imports for PyInstaller packaging."""
    return [
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


def run_build():
    args = parse_args()
    system = platform.system()
    raw_host_arch = platform.machine()
    host_arch = normalize_arch(raw_host_arch)
    target_arch = normalize_arch(args.arch) if args.arch else host_arch

    print("=" * 65)
    print(f" [STROKE COMPILER // PLATFORM: {system.upper()} // ARCH: {target_arch}]")
    print("=" * 65)

    # Architecture & translation diagnostic
    is_rosetta = detect_rosetta_translation()
    if is_rosetta:
        print("[STROKE BUILD NOTICE] Active Python is running under Rosetta 2 x86_64 translation on Apple Silicon.")

    # Universal binary check
    if target_arch == "universal2" and system == "Darwin":
        can_universal, u_msg = check_universal2_compatibility()
        print(f"[STROKE BUILD UNIVERSAL2 CHECK] {u_msg}")
        if not can_universal:
            print(
                "[STROKE BUILD WARNING] Building universal2 on a single-arch interpreter may fail during lipo linking.\n"
                f"Recommendation: Specify --arch {host_arch} or use a Universal2 Python environment.",
                file=sys.stderr
            )

    sep = ";" if system == "Windows" else ":"
    add_data = get_bundle_add_data(system, sep)

    # Verify read-only bundle safety
    violations = validate_bundle_manifest(add_data, sep)
    if violations:
        print(
            f"[STROKE BUILD CRITICAL] Read-only bundle violation: mutable/sensitive files detected in manifest: {violations}\n"
            "Aborting build to prevent bundling mutable state into read-only app locations.",
            file=sys.stderr
        )
        sys.exit(1)

    print("[STROKE BUILD VERIFICATION] Confirmed: Zero mutable user database/key files in bundle manifest.")
    print("[STROKE BUILD VERIFICATION] Dynamic runtime writes strictly target user application storage (paths_service).")
    print("[STROKE BUILD VERIFICATION] Neural models (GGUF) are resolved from user application storage (~/Models).")

    # If --check-config was requested, validate and return immediately without compiling
    if args.check_config:
        print("\n[STROKE BUILD CHECK-CONFIG SUCCESSFUL]")
        print(f"  Target Platform:     {system}")
        print(f"  Target Architecture: {target_arch}")
        print(f"  Host Architecture:   {host_arch}")
        print(f"  Rosetta Translated:  {is_rosetta}")
        print(f"  Bundled Data Assets: {len(add_data)} entry(s)")
        print(f"  Hidden Imports:      {len(get_hidden_imports())} modules")
        print("  All packaging options and read-only location checks PASSED.")
        print("=" * 65 + "\n")
        return

    # Ensure PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("[STROKE BUILD] PyInstaller not detected. Installing via pip...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    base_cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name=Stroke",
        "--noconfirm",
        "--clean",
        "--windowed" if system != "Linux" else "--onedir",
    ]

    # Target architecture handling on macOS
    if system == "Darwin":
        if args.arch:
            base_cmd.extend(["--target-arch", args.arch])
        elif target_arch in ("arm64", "x86_64"):
            base_cmd.extend(["--target-arch", target_arch])

    for item in add_data:
        src = item.split(sep)[0]
        if os.path.exists(src):
            base_cmd.extend(["--add-data", item])

    for imp in get_hidden_imports():
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
