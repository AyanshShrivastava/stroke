"""
================================================================================
STROKE // APPROVED WORKSPACE & PERMISSIONS SERVICE
================================================================================
Strictly enforces Stroke Workspace Boundaries:
- Stroke must work with the user's actual computer files within explicit workspaces.
- Stroke remembers approved workspaces securely in per-user app data.
- NEVER silently grants access to the entire computer or automatically approves cwd/home.
- Every workspace must be explicitly approved by the user.
- System roots, system directories, and broad home-directory roots are strictly rejected.
- Validates canonical real paths at the point of access, including symlink targets.
- Prevents symlink traversal, loops, path races, and access outside approved roots.
- Validates task IDs as strict identifiers; never joins untrusted task IDs into paths.
================================================================================
"""

import os
import sys
import re
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import paths_service

TASK_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")

DISALLOWED_ROOTS = {
    "/", "/bin", "/sbin", "/usr", "/usr/bin", "/usr/sbin",
    "/etc", "/var", "/tmp", "/dev", "/proc", "/sys",
    "/System", "/Library", "/Applications", "/private",
    "/private/etc", "/private/var", "/private/tmp"
}

DISALLOWED_PREFIXES_WINDOWS = (
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)"
)


class WorkspaceSecurityError(PermissionError):
    """Raised when an operation attempts to access files outside approved workspaces."""
    pass


def validate_task_id(task_id: str) -> str:
    """
    Validates that task_id is a strict alphanumeric/hyphen/underscore identifier.
    Rejects directory traversal characters ('..', '/', '\\', null bytes).
    """
    if not task_id or not isinstance(task_id, str):
        raise WorkspaceSecurityError("Task ID must be a non-empty string.")
    clean_id = task_id.strip()
    if not TASK_ID_REGEX.match(clean_id):
        raise WorkspaceSecurityError(
            f"Invalid task ID '{task_id}'. Task IDs must be 1-64 alphanumeric characters, underscores, or hyphens."
        )
    return clean_id


class WorkspaceManager:
    """Manages the persistent list of user-approved workspace directories."""

    def __init__(self):
        self.config_path = paths_service.get_workspaces_config_path()
        self._ensure_config()

    def _ensure_config(self):
        """Initializes approved workspaces configuration with an empty list if not present."""
        if not self.config_path.exists():
            self._save_workspaces([])

    def _read_workspaces(self) -> List[str]:
        """Reads approved workspaces list from disk without silent defaults."""
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("approved_workspaces", [])
        except Exception as exc:
            print(f"[STROKE WORKSPACE WARNING] Error reading {self.config_path}: {exc}", flush=True)
        return []

    def _save_workspaces(self, workspaces: List[str]):
        """Persists approved workspaces list atomically."""
        clean = []
        for w in workspaces:
            try:
                resolved = str(Path(w).resolve())
                if resolved not in clean and Path(resolved).exists() and Path(resolved).is_dir():
                    clean.append(resolved)
            except Exception:
                pass

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temp_cfg = self.config_path.with_suffix(".tmp")
        with open(temp_cfg, "w", encoding="utf-8") as f:
            json.dump({"approved_workspaces": clean}, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_cfg, self.config_path)

    def get_approved_workspaces(self) -> List[str]:
        """
        Returns canonical paths to explicitly approved workspace folders.
        Never automatically injects cwd or home directory.
        """
        existing = self._read_workspaces()
        valid = [w for w in existing if Path(w).exists() and Path(w).is_dir()]
        return valid

    def add_approved_workspace(self, folder_path: str, label: Optional[str] = None) -> Dict[str, Any]:
        """
        Validates and registers an explicitly user-approved project folder.
        Rejects system roots, system directories, and broad user home roots.
        """
        if not folder_path or not str(folder_path).strip():
            raise ValueError("Folder path cannot be empty.")

        p = Path(folder_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Selected folder does not exist: {p}")
        if not p.is_dir():
            raise NotADirectoryError(f"Selected path is not a directory: {p}")

        resolved_str = str(p)

        raw_clean = str(folder_path).strip().rstrip("/\\") or "/"
        if resolved_str in DISALLOWED_ROOTS or raw_clean in DISALLOWED_ROOTS:
            raise WorkspaceSecurityError(
                f"System-level root directory cannot be registered as a workspace: '{resolved_str}'"
            )

        # 2. Reject Windows drive roots and system directories
        os_name = paths_service.get_current_os()
        if os_name == "windows":
            # Reject drive roots (e.g. C:\, D:\)
            if len(p.parts) <= 1 or p == Path(p.anchor):
                raise WorkspaceSecurityError(
                    f"Drive root cannot be registered as an entire workspace: '{resolved_str}'"
                )
            for win_disallowed in DISALLOWED_PREFIXES_WINDOWS:
                if resolved_str.lower().startswith(win_disallowed.lower()):
                    raise WorkspaceSecurityError(
                        f"Windows system directory cannot be registered as a workspace: '{resolved_str}'"
                    )
        else:
            # POSIX root check
            if p == Path("/") or resolved_str in ("/", "/root"):
                raise WorkspaceSecurityError(
                    f"Filesystem root cannot be registered as an entire workspace."
                )
            if resolved_str.startswith(("/System", "/private/etc", "/private/var/root", "/private/var/db", "/Library/Apple", "/Library/System")):
                raise WorkspaceSecurityError(
                    f"OS system directory cannot be registered as a workspace: '{resolved_str}'"
                )

        # 3. Reject broad home-directory roots (user must pick a specific project subfolder)
        try:
            home = paths_service.get_home_dir().resolve()
        except Exception:
            home = Path.home().resolve()

        if p == home or resolved_str == str(home):
            raise WorkspaceSecurityError(
                f"User home directory root cannot be registered as an entire workspace: '{resolved_str}'. "
                f"Please register a specific project directory inside your user profile."
            )

        workspaces = self._read_workspaces()
        if resolved_str not in workspaces:
            workspaces.append(resolved_str)
            self._save_workspaces(workspaces)

        return {
            "status": "approved",
            "workspace": resolved_str,
            "label": label or p.name or resolved_str,
            "total_approved": len(workspaces)
        }

    def remove_approved_workspace(self, folder_path: str) -> bool:
        """Removes a folder from the approved workspaces registry."""
        try:
            resolved_str = str(Path(folder_path).resolve())
            workspaces = self._read_workspaces()
            if resolved_str in workspaces:
                workspaces.remove(resolved_str)
                self._save_workspaces(workspaces)
                return True
        except Exception:
            pass
        return False

    def clear_approved_workspaces(self) -> bool:
        """Clears all approved workspaces."""
        self._save_workspaces([])
        return True

    def _is_canonical_approved(self, canonical: Path, allow_app_data: bool = False) -> bool:
        """Checks if a canonical path resides strictly inside an approved workspace."""
        for ws in self.get_approved_workspaces():
            try:
                ws_path = Path(ws).resolve()
                if canonical == ws_path or ws_path in canonical.parents:
                    return True
            except Exception:
                continue

        if allow_app_data:
            try:
                app_data = paths_service.get_app_data_dir().resolve()
                if canonical == app_data or app_data in canonical.parents:
                    return True
            except Exception:
                pass

        return False

    def is_path_approved(self, target_path: str, allow_app_data: bool = False) -> bool:
        """
        Validates whether target_path resides strictly inside at least one approved workspace.
        Resolves symlinks and prevents traversal.
        """
        try:
            p = Path(target_path)
            canonical = p.resolve(strict=False)
            
            # If symlink, also inspect real target
            if p.is_symlink():
                real_target = Path(os.path.realpath(str(p)))
                if not self._is_canonical_approved(real_target, allow_app_data=allow_app_data):
                    return False

            return self._is_canonical_approved(canonical, allow_app_data=allow_app_data)
        except Exception:
            return False

    def validate_path_access(self, target_path: str, allow_app_data: bool = False) -> Path:
        """
        Enforces workspace boundary permissions at the point of access.
        - Resolves canonical real path.
        - Inspects symlink targets to prevent symlink traversal escapes.
        - Rejects access outside approved workspaces.
        """
        if not target_path:
            raise WorkspaceSecurityError("Target path cannot be empty.")

        p = Path(target_path)
        try:
            canonical = p.resolve(strict=False)
        except (RuntimeError, OSError) as exc:
            raise WorkspaceSecurityError(f"Invalid path or symlink loop detected: {target_path} ({exc})")

        # Symlink escape prevention: inspect resolved target of symlink
        if p.is_symlink():
            try:
                real_target = Path(os.path.realpath(str(p)))
            except (RuntimeError, OSError) as exc:
                raise WorkspaceSecurityError(f"Symlink traversal or loop detected: {p} ({exc})")
            if not self._is_canonical_approved(real_target, allow_app_data=allow_app_data):
                raise WorkspaceSecurityError(
                    f"Symlink traversal denied: Symlink '{p}' points to target '{real_target}' outside approved workspaces."
                )

        if not self._is_canonical_approved(canonical, allow_app_data=allow_app_data):
            raise WorkspaceSecurityError(
                f"Access denied: '{canonical}' is outside user-approved workspaces. "
                f"Please explicitly approve this project directory in Stroke Workspace Settings."
            )

        return canonical


_WORKSPACE_MANAGER = WorkspaceManager()


def get_approved_workspaces() -> List[str]:
    """Retrieves list of canonical approved project workspaces."""
    return _WORKSPACE_MANAGER.get_approved_workspaces()


def list_approved_workspaces() -> List[Dict[str, str]]:
    """Retrieves structured list of approved project workspaces."""
    raw = _WORKSPACE_MANAGER.get_approved_workspaces()
    return [{"path": p, "name": Path(p).name or p} for p in raw]


def add_approved_workspace(folder_path: str, label: Optional[str] = None) -> Dict[str, Any]:
    """Adds a new folder to approved workspaces with explicit user consent."""
    return _WORKSPACE_MANAGER.add_approved_workspace(folder_path, label=label)


def approve_workspace(folder_path: str, label: Optional[str] = None) -> Dict[str, Any]:
    """Alias for add_approved_workspace."""
    return add_approved_workspace(folder_path, label=label)


def remove_approved_workspace(folder_path: str) -> bool:
    """Removes a folder from approved workspaces."""
    return _WORKSPACE_MANAGER.remove_approved_workspace(folder_path)


def clear_approved_workspaces() -> bool:
    """Clears all approved workspaces."""
    return _WORKSPACE_MANAGER.clear_approved_workspaces()


def is_path_approved(target_path: str, allow_app_data: bool = False) -> bool:
    """Checks if a path is inside approved workspaces."""
    return _WORKSPACE_MANAGER.is_path_approved(target_path, allow_app_data=allow_app_data)


def validate_path_access(target_path: str, allow_app_data: bool = False) -> Path:
    """Enforces workspace boundary permissions at point of access."""
    return _WORKSPACE_MANAGER.validate_path_access(target_path, allow_app_data=allow_app_data)


def pick_native_folder() -> Optional[str]:
    """
    Spawns the operating system's native file picker dialog to let the user
    select a project directory.
    - macOS: AppleScript / osascript choose folder
    - Windows: PowerShell FolderBrowserDialog
    - Linux / Fallback: tkinter.filedialog
    Adds selected folder to approved workspaces upon user confirmation.
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
