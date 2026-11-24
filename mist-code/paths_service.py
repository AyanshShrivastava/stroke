"""
================================================================================
STROKE // USER-LEVEL COMPUTER PATHS & ELEVATION MANAGEMENT SERVICE
================================================================================
Strictly enforces standard user-level filesystem directories and zero-admin
privileges across Windows, macOS, and Linux.

Operating System Path Specifications:
- WINDOWS:
    Application Installation: %LOCALAPPDATA%\\Programs\\Stroke
    Application Data:         %LOCALAPPDATA%\\Stroke
    Models:                   %LOCALAPPDATA%\\Stroke\\Models
    Backups:                  %LOCALAPPDATA%\\Stroke\\Backups
    Downloads:                %USERPROFILE%\\Downloads
- MACOS:
    Application Installation: ~/Applications/Stroke.app
    Application Data:         ~/Library/Application Support/Stroke
    Models:                   ~/Library/Application Support/Stroke/Models
    Backups:                  ~/Library/Application Support/Stroke/Backups
    Downloads:                ~/Downloads
- LINUX:
    Application Installation: ~/.local/bin/stroke
    Application Data:         ~/.local/share/Stroke
    Models:                   ~/.local/share/Stroke/Models
    Backups:                  ~/.local/share/Stroke/Backups
    Downloads:                ~/Downloads
================================================================================
"""

import os
import sys
import platform
import getpass
from pathlib import Path
from typing import Dict, Any, Optional


def get_current_os() -> str:
    """Returns the standardized current operating system: 'windows', 'darwin', or 'linux'."""
    sys_name = platform.system().lower()
    if "windows" in sys_name:
        return "windows"
    if "darwin" in sys_name or "mac" in sys_name:
        return "darwin"
    return "linux"


def get_current_username() -> str:
    """Retrieves the currently logged-in standard user username."""
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or os.environ.get("USERNAME") or "user"


def get_home_dir() -> Path:
    """Returns the user home directory."""
    return Path.home().resolve()


def get_app_data_dir() -> Path:
    """
    Returns Stroke's per-user application data directory.
    - Honors STROKE_APP_DATA / STROKE_DATA_DIR environment variables if set.
    - Windows: %LOCALAPPDATA%\\Stroke
    - macOS:   ~/Library/Application Support/Stroke
    - Linux:   ~/.local/share/Stroke
    """
    env_dir = os.environ.get("STROKE_APP_DATA") or os.environ.get("STROKE_DATA_DIR")
    if env_dir:
        app_dir = Path(env_dir).resolve()
        app_dir.mkdir(parents=True, exist_ok=True)
        return app_dir

    os_name = get_current_os()
    home = get_home_dir()

    if os_name == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = home / "AppData" / "Local"
        app_dir = base / "Stroke"
    elif os_name == "darwin":
        app_dir = home / "Library" / "Application Support" / "Stroke"
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg_data) if xdg_data else home / ".local" / "share"
        app_dir = base / "Stroke"

    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir.resolve()


def get_models_dir() -> Path:
    """
    Returns Stroke's user-level models directory.
    - Windows: %LOCALAPPDATA%\\Stroke\\Models
    - macOS:   ~/Library/Application Support/Stroke/Models
    - Linux:   ~/.local/share/Stroke/Models
    """
    models_dir = get_app_data_dir() / "Models"
    models_dir.mkdir(parents=True, exist_ok=True)
    return models_dir.resolve()


def get_backups_dir() -> Path:
    """
    Returns Stroke's user-level version backups directory.
    - Windows: %LOCALAPPDATA%\\Stroke\\Backups
    - macOS:   ~/Library/Application Support/Stroke/Backups
    - Linux:   ~/.local/share/Stroke/Backups
    """
    backups_dir = get_app_data_dir() / "Backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    return backups_dir.resolve()


def get_downloads_dir() -> Path:
    """Returns the user's primary Downloads folder."""
    home = get_home_dir()
    downloads = home / "Downloads"
    if not downloads.exists():
        downloads.mkdir(parents=True, exist_ok=True)
    return downloads.resolve()


def get_app_installation_dir() -> Path:
    """
    Returns the designated user-level application installation location.
    - Windows: %LOCALAPPDATA%\\Programs\\Stroke
    - macOS:   ~/Applications/Stroke.app (creates ~/Applications if missing)
    - Linux:   ~/.local/bin
    """
    os_name = get_current_os()
    home = get_home_dir()

    if os_name == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = Path(local_app_data) if local_app_data else home / "AppData" / "Local"
        install_dir = base / "Programs" / "Stroke"
    elif os_name == "darwin":
        user_apps = home / "Applications"
        user_apps.mkdir(parents=True, exist_ok=True)
        install_dir = user_apps / "Stroke.app"
        install_dir.mkdir(parents=True, exist_ok=True)
    else:
        user_bin = home / ".local" / "bin"
        user_bin.mkdir(parents=True, exist_ok=True)
        install_dir = user_bin

    return install_dir


def get_workspaces_config_path() -> Path:
    """Path to the approved workspaces JSON configuration."""
    return get_app_data_dir() / "approved_workspaces.json"


def get_user_chats_path() -> Path:
    """Path to the user chat sessions JSON file."""
    return get_app_data_dir() / "local_chat_sessions.json"


def get_mcp_config_path() -> Path:
    """Path to the user MCP servers JSON configuration."""
    return get_app_data_dir() / "mcp_servers.json"


def get_legacy_mcp_config_path() -> Path:
    """Path to the legacy MCP config JSON file in user app data."""
    return get_app_data_dir() / "mcp_config.json"


def get_verified_project_context_path() -> Path:
    """Path to the verified project context JSON file."""
    return get_app_data_dir() / "verified_project_context.json"


def get_local_firestore_db_path() -> Path:
    """Path to the local disk-backed Firestore database."""
    return get_app_data_dir() / "local_firestore_db.json"


def get_vfx_dir() -> Path:
    """Path to the user-learned VFX dataset directory."""
    vfx_dir = get_app_data_dir() / "vfx"
    vfx_dir.mkdir(parents=True, exist_ok=True)
    return vfx_dir.resolve()


def atomic_write_json(file_path: Path, data: Any) -> None:
    """Safely and atomically writes JSON data to file_path using a temporary file and replace."""
    import json
    file_path = Path(file_path).resolve()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(f"{file_path.suffix}.tmp.{os.getpid()}")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except Exception:
                pass


def migrate_legacy_data(legacy_source_dir: Optional[Path] = None) -> Dict[str, bool]:
    """
    Safely migrates legacy data files from the source/package directory to
    the user application-data directory if the destination does not exist yet.
    Never overwrites existing user data and never writes into read-only package dirs.
    """
    source_dir = legacy_source_dir if legacy_source_dir else (Path(__file__).resolve().parent / "data")
    results = {}

    mappings = {
        "local_chat_sessions.json": get_user_chats_path(),
        "mcp_servers.json": get_mcp_config_path(),
        "mcp_config.json": get_legacy_mcp_config_path(),
        "verified_project_context.json": get_verified_project_context_path(),
        "local_firestore_db.json": get_local_firestore_db_path(),
    }

    for filename, dest_path in mappings.items():
        src_path = Path(source_dir) / filename
        if src_path.exists() and not dest_path.exists():
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_bytes(src_path.read_bytes())
                results[filename] = True
            except Exception:
                results[filename] = False
        else:
            results[filename] = False

    return results


def ensure_user_directories() -> Dict[str, str]:
    """
    Verifies and initializes all Stroke user-level folders without root/admin permissions.
    Returns directory paths for diagnostics.
    """
    app_data = get_app_data_dir()
    models = get_models_dir()
    backups = get_backups_dir()
    downloads = get_downloads_dir()
    install_dir = get_app_installation_dir()
    vfx_dir = get_vfx_dir()
    migrate_legacy_data()

    return {
        "app_data": str(app_data),
        "models": str(models),
        "backups": str(backups),
        "downloads": str(downloads),
        "install_dir": str(install_dir),
        "vfx_dir": str(vfx_dir),
        "os": get_current_os(),
        "user": get_current_username()
    }


def is_elevated_privilege() -> bool:
    """
    Detects whether Stroke was accidentally launched with administrator or root privileges.
    - Unix/macOS: checks if effective user ID is 0.
    - Windows: checks if current process has administrator token via Shell32.
    """
    os_name = get_current_os()

    if os_name in ("darwin", "linux"):
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False
    elif os_name == "windows":
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
        except Exception:
            return False
    return False


def get_elevation_status() -> Dict[str, Any]:
    """
    Returns full elevation state, warnings, and non-privileged launch guidance.
    Enforces Stroke Requirement 8: Never run as administrator.
    """
    elevated = is_elevated_privilege()
    username = get_current_username()
    os_name = get_current_os()

    if elevated:
        if os_name == "windows":
            warning = "CRITICAL WARNING: Stroke was launched with Administrator privileges. Stroke does not require administrative elevation and runs in standard user mode."
            guidance = "Close this instance and relaunch Stroke from your user Start Menu or regular command prompt without 'Run as Administrator'."
        else:
            warning = "CRITICAL WARNING: Stroke was launched as root/superuser (sudo). Stroke does not require root privileges and should only run as your standard user."
            guidance = f"Terminate this process and run 'python desktop.py' or open Stroke as standard user '{username}' without 'sudo'."
    else:
        warning = None
        guidance = "Stroke is operating securely under standard user permissions."

    return {
        "is_elevated": elevated,
        "zero_admin_compliant": not elevated,
        "current_user": username,
        "user": username,
        "operating_system": os_name,
        "platform": os_name,
        "warning": warning,
        "elevation_warning": warning,
        "guidance": guidance,
        "status": "elevated_warning" if elevated else "healthy_standard_user"
    }
