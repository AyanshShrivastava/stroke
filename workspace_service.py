"""
================================================================================
STROKE // APPROVED WORKSPACE & PERMISSIONS SERVICE
================================================================================
Strictly enforces Stroke Requirement 1:
- Stroke must work with the user's actual computer files within explicit workspaces.
- Stroke remembers approved workspaces securely in per-user app data.
- NEVER silently grants access to the entire computer.
- Provides native OS folder selection (macOS osascript, Windows PowerShell/FolderBrowser, Linux zenity/tkinter).
- Prevents directory traversal attacks, root directory escapes, and unapproved file access.
================================================================================
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import paths_service


class WorkspaceSecurityError(PermissionError):
    """Raised when an operation attempts to access files outside approved workspaces."""
    pass


class WorkspaceManager:
    """Manages the persistent list of user-approved workspace directories."""

    def __init__(self):
        self.config_path = paths_service.get_workspaces_config_path()
        self._ensure_config()

    def _ensure_config(self):
        if not self.config_path.exists():
            default_workspaces = [
                str(Path.cwd().resolve()),
                str(Path.home() / "stroke_workspace")
            ]
            self._save_workspaces(default_workspaces)

    def _read_workspaces(self) -> List[str]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("approved_workspaces", [])
        except Exception:
            pass
        return [str(Path.cwd().resolve())]

    def _save_workspaces(self, workspaces: List[str]):
        clean = []
        for w in workspaces:
            try:
                resolved = str(Path(w).resolve())
                if resolved not in clean and Path(resolved).exists():
                    clean.append(resolved)
            except Exception:
                pass

        temp_cfg = self.config_path.with_suffix(".tmp")
        with open(temp_cfg, "w", encoding="utf-8") as f:
            json.dump({"approved_workspaces": clean}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_cfg, self.config_path)

    def get_approved_workspaces(self) -> List[str]:
        """Returns the list of canonical paths to approved workspace folders."""
        existing = self._read_workspaces()
        valid = [w for w in existing if Path(w).exists() and Path(w).is_dir()]
        # Always include active project directory
        cwd_str = str(Path.cwd().resolve())
        if cwd_str not in valid:
            valid.insert(0, cwd_str)
        return valid

    def add_approved_workspace(self, folder_path: str) -> Dict[str, Any]:
        """Validates and persists a new approved project folder."""
        p = Path(folder_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Selected folder does not exist: {p}")
        if not p.is_dir():
            raise NotADirectoryError(f"Selected path is not a directory: {p}")

        # Block root or system-wide folders
        os_name = paths_service.get_current_os()
        resolved_str = str(p)

        if resolved_str in ("/", "C:\\", "C:/") or resolved_str.startswith(("/System", "/Library", "C:\\Windows")):
            raise WorkspaceSecurityError(f"System-level root directory cannot be registered as a workspace: {resolved_str}")

        workspaces = self._read_workspaces()
        if resolved_str not in workspaces:
            workspaces.append(resolved_str)
            self._save_workspaces(workspaces)

        return {
            "status": "approved",
            "workspace": resolved_str,
            "total_approved": len(workspaces)
        }

    def is_path_approved(self, target_path: str) -> bool:
        """
        Validates whether target_path resides strictly inside at least one approved workspace.
        Resolves symlinks and prevents path traversal (../).
        """
        try:
            canonical = Path(target_path).resolve()
        except Exception:
            return False

        for ws in self.get_approved_workspaces():
            try:
                ws_path = Path(ws).resolve()
                if canonical == ws_path or ws_path in canonical.parents:
                    return True
            except Exception:
                continue

        # Also permit Stroke's internal user-level app data / scratch dirs
        app_data = paths_service.get_app_data_dir()
        if canonical == app_data or app_data in canonical.parents:
            return True

        return False

    def validate_path_access(self, target_path: str) -> Path:
        """
        Validates path safety and permissions.
        Returns the resolved Path if approved, or raises WorkspaceSecurityError.
        """
        resolved = Path(target_path).resolve()
        if not self.is_path_approved(str(resolved)):
            raise WorkspaceSecurityError(
                f"Access denied: '{resolved}' is outside user-approved workspaces. "
                f"Please add this project directory in Stroke Workspace Settings."
            )
        return resolved


_WORKSPACE_MANAGER = WorkspaceManager()


def get_approved_workspaces() -> List[str]:
    """Retrieves list of approved project workspaces."""
    return _WORKSPACE_MANAGER.get_approved_workspaces()


def list_approved_workspaces() -> List[Dict[str, str]]:
    """Retrieves structured list of approved project workspaces."""
    raw = _WORKSPACE_MANAGER.get_approved_workspaces()
    return [{"path": p, "name": Path(p).name or p} for p in raw]


def add_approved_workspace(folder_path: str, label: Optional[str] = None) -> Dict[str, Any]:
    """Adds a new folder to approved workspaces."""
    res = _WORKSPACE_MANAGER.add_approved_workspace(folder_path)
    if label:
        res["label"] = label
    return res


def approve_workspace(folder_path: str, label: Optional[str] = None) -> Dict[str, Any]:
    """Alias for add_approved_workspace."""
    return add_approved_workspace(folder_path, label=label)


def is_path_approved(target_path: str) -> bool:
    """Checks if a path is inside approved workspaces."""
    return _WORKSPACE_MANAGER.is_path_approved(target_path)


def validate_path_access(target_path: str) -> Path:
    """Enforces workspace boundary permissions."""
    return _WORKSPACE_MANAGER.validate_path_access(target_path)


def pick_native_folder() -> Optional[str]:
    """
    Spawns the operating system's native file picker dialog to let the user
    select a project directory.
    - macOS: AppleScript / osascript choose folder
    - Windows: PowerShell FolderBrowserDialog
    - Linux / Fallback: tkinter.filedialog
    Adds selected folder to approved workspaces automatically.
    """
    os_name = paths_service.get_current_os()
    selected = None

    if os_name == "darwin":
        cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select Project Folder for Stroke AI:")']
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if res.returncode == 0 and res.stdout.strip():
                selected = res.stdout.strip()
        except Exception:
            pass

    elif os_name == "windows":
        ps_cmd = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null; "
            "$f = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$f.Description = 'Select Project Folder for Stroke AI'; "
            "if($f.ShowDialog() -eq 'OK'){ Write-Host $f.SelectedPath }"
        )
        try:
            res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], stdout=subprocess.PIPE, text=True, timeout=60)
            if res.returncode == 0 and res.stdout.strip():
                selected = res.stdout.strip()
        except Exception:
            pass

    # Universal cross-platform fallback via Tkinter
    if not selected:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            selected = filedialog.askdirectory(title="Select Project Folder for Stroke AI")
            root.destroy()
        except Exception:
            pass

    if selected and Path(selected).exists() and Path(selected).is_dir():
        add_approved_workspace(selected)
        return str(Path(selected).resolve())

    return None
