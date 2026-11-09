"""
================================================================================
STROKE // ISOLATED PER-TASK WORKSPACE & CHANGE RECONCILIATION ENGINE
================================================================================
Strictly enforces Stroke Requirement 2:
- AI-initiated terminal commands run in an isolated per-task working copy.
- Terminal commands NEVER have unrestricted direct write access to original user files.
- When a task completes:
    1. Inspects changes made in the isolated workspace.
    2. Identifies new files.
    3. Identifies modified files.
    4. Identifies deleted files.
    5. Rejects any change set that includes deletion or renaming.
    6. Applies only new and modified files through the controlled file service.
    7. Backs up every existing file before modifying it.
================================================================================
"""

import os
import sys
import shutil
import hashlib
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Set

import paths_service
import backup_service
import workspace_service


class DestructiveChangeSetError(PermissionError):
    """Raised when an isolated task change set contains file deletions or renamings."""
    pass


class TaskWorkspaceSandbox:
    """Manages isolated per-task working copies and safe change reconciliation."""

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path = workspace_path
        self.sandbox_base = paths_service.get_app_data_dir() / "IsolatedTasks"
        self.sandbox_base.mkdir(parents=True, exist_ok=True)
        # In-memory manifest registry for active tasks: task_id -> { "source": Path, "sandbox": Path, "initial_manifest": dict }
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

    def _compute_hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _build_manifest(self, base_dir: Path) -> Dict[str, str]:
        manifest = {}
        for root, dirs, files in os.walk(base_dir):
            dirs[:] = [d for d in dirs if d not in (".git", "venv", "node_modules", "__pycache__", ".stroke_scratch")]
            for f in files:
                full_p = Path(root) / f
                try:
                    rel_p = str(full_p.relative_to(base_dir))
                    manifest[rel_p] = self._compute_hash(full_p)
                except Exception:
                    pass
        return manifest

    def create_task_copy(self, task_id: str, copy_all: bool = True) -> str:
        """Helper to create an isolated task copy directory."""
        res = self.create_task_workspace(self.workspace_path, task_id, copy_all=copy_all)
        return res["isolated_workspace"]

    def create_task_workspace(
        self,
        source_workspace: Optional[str] = None,
        task_id: str = "default_task",
        copy_all: bool = True
    ) -> Dict[str, Any]:
        """
        Creates an isolated, non-elevated per-task working copy in Stroke app data.
        Returns the path to the isolated sandbox directory for terminal execution.
        """
        target_ws = source_workspace or self.workspace_path
        if not target_ws:
            raise ValueError("No workspace specified for task sandbox.")
        source = workspace_service.validate_path_access(target_ws)
        if not source.exists() or not source.is_dir():
            raise NotADirectoryError(f"Source workspace not found: {source}")

        task_sandbox = self.sandbox_base / task_id
        if task_sandbox.exists():
            shutil.rmtree(task_sandbox, ignore_errors=True)
        task_sandbox.mkdir(parents=True, exist_ok=True)

        # Copy project files while excluding large dependency trees to keep copy fast
        ignore_patterns = shutil.ignore_patterns(".git", "venv", "node_modules", "__pycache__", ".stroke_scratch", "*.pyc")
        
        for item in source.iterdir():
            if item.name in (".git", "venv", "node_modules", "__pycache__", ".stroke_scratch"):
                continue
            dest = task_sandbox / item.name
            if item.is_dir():
                shutil.copytree(item, dest, ignore=ignore_patterns, symlinks=True)
            else:
                shutil.copy2(item, dest)

        # Record initial snapshot manifest to detect additions, modifications, and deletions
        initial_manifest = self._build_manifest(task_sandbox)

        self._active_tasks[task_id] = {
            "source": source,
            "sandbox": task_sandbox,
            "initial_manifest": initial_manifest,
            "created_at": time.time()
        }

        return {
            "status": "created",
            "task_id": task_id,
            "source_workspace": str(source),
            "isolated_workspace": str(task_sandbox),
            "files_tracked": len(initial_manifest)
        }

    def inspect_task_changes(self, task_id: str) -> Dict[str, Any]:
        """
        Inspects changes between the isolated workspace and the original state.
        Identifies:
        - new_files
        - modified_files
        - deleted_files
        """
        task_data = self._active_tasks.get(task_id)
        if not task_data:
            # Check if directory exists on disk
            task_sandbox = self.sandbox_base / task_id
            if not task_sandbox.exists():
                raise KeyError(f"No active isolated workspace found for task ID: {task_id}")
            raise KeyError(f"Task session metadata missing for: {task_id}")

        sandbox = task_data["sandbox"]
        source = task_data["source"]
        initial_manifest = task_data["initial_manifest"]

        current_sandbox_manifest = self._build_manifest(sandbox)

        new_files: List[str] = []
        modified_files: List[str] = []
        deleted_files: List[str] = []

        # Detect deleted files (in initial manifest but absent in sandbox)
        for rel_path, initial_hash in initial_manifest.items():
            if rel_path not in current_sandbox_manifest:
                deleted_files.append(rel_path)
            elif current_sandbox_manifest[rel_path] != initial_hash:
                modified_files.append(rel_path)

        # Detect new files (in sandbox but absent in initial manifest)
        for rel_path in current_sandbox_manifest:
            if rel_path not in initial_manifest:
                new_files.append(rel_path)

        return {
            "task_id": task_id,
            "source_workspace": str(source),
            "isolated_workspace": str(sandbox),
            "new_files": sorted(new_files),
            "modified_files": sorted(modified_files),
            "deleted_files": sorted(deleted_files),
            "has_deletions": len(deleted_files) > 0,
            "total_changes": len(new_files) + len(modified_files) + len(deleted_files)
        }

    def apply_task_changes(
        self,
        task_id: str,
        description: str = "Verified AI coding changes applied"
    ) -> Dict[str, Any]:
        """
        Reconciles changes from the isolated workspace back to the original source project.
        ENFORCES ABSOLUTE NO-DELETE POLICY:
        - If ANY deleted files are found, REJECTS the entire change set immediately.
        - For every modified file, creates an automatic version backup first.
        - Safely writes new and modified files via atomic safe writes.
        """
        changes = self.inspect_task_changes(task_id)
        task_data = self._active_tasks[task_id]
        sandbox = task_data["sandbox"]
        source = task_data["source"]

        # 1. HARD REJECTION on any file deletion
        if changes["has_deletions"]:
            deleted_list = ", ".join(changes["deleted_files"])
            raise DestructiveChangeSetError(
                f"REJECTED: Task '{task_id}' attempted to delete existing files: [{deleted_list}]. "
                f"Stroke's Absolute No-Delete Policy prohibits applying change sets containing deletions."
            )

        applied_new = []
        applied_modified = []
        backups_created = []

        # 2. Apply modified files with pre-modification backups
        for rel_path in changes["modified_files"]:
            src_file = source / rel_path
            sandbox_file = sandbox / rel_path
            if not sandbox_file.exists():
                continue

            content = sandbox_file.read_text(encoding="utf-8", errors="replace")
            res = backup_service.atomic_write_file(
                target_path=str(src_file),
                content=content,
                make_backup_if_exists=True,
                task_id=task_id,
                description=f"{description} (Modified {rel_path})"
            )
            applied_modified.append(rel_path)
            if res.get("backup"):
                backups_created.append(res["backup"])

        # 3. Apply new files
        for rel_path in changes["new_files"]:
            src_file = source / rel_path
            sandbox_file = sandbox / rel_path
            if not sandbox_file.exists():
                continue

            content = sandbox_file.read_text(encoding="utf-8", errors="replace")
            src_file.parent.mkdir(parents=True, exist_ok=True)
            res = backup_service.atomic_write_file(
                target_path=str(src_file),
                content=content,
                make_backup_if_exists=False,
                task_id=task_id,
                description=f"{description} (Created {rel_path})"
            )
            applied_new.append(rel_path)

        return {
            "status": "success",
            "message": "All verified changes applied safely with automatic version backups.",
            "task_id": task_id,
            "source_workspace": str(source),
            "new_files_created": applied_new,
            "applied_additions": applied_new,
            "modified_files_applied": applied_modified,
            "applied_modifications": applied_modified,
            "applied_deletions": [],
            "backups_generated": backups_created
        }

    def cleanup_task_workspace(self, task_id: str):
        """Cleans up internal sandbox temp copy after task resolution."""
        task_data = self._active_tasks.pop(task_id, None)
        task_sandbox = self.sandbox_base / task_id
        if task_sandbox.exists():
            shutil.rmtree(task_sandbox, ignore_errors=True)


_TASK_SANDBOX = TaskWorkspaceSandbox()


def create_task_workspace(source_workspace: str, task_id: str) -> Dict[str, Any]:
    return _TASK_SANDBOX.create_task_workspace(source_workspace, task_id)


def inspect_task_changes(task_id: str) -> Dict[str, Any]:
    return _TASK_SANDBOX.inspect_task_changes(task_id)


def apply_task_changes(task_id: str, description: str = "Verified AI changes") -> Dict[str, Any]:
    return _TASK_SANDBOX.apply_task_changes(task_id, description)


def cleanup_task_workspace(task_id: str):
    _TASK_SANDBOX.cleanup_task_workspace(task_id)
