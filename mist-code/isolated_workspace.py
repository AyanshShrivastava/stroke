"""
================================================================================
STROKE // ISOLATED PER-TASK WORKSPACE & CHANGE RECONCILIATION ENGINE
================================================================================
Strictly enforces Stroke Requirement 2 & Isolation Safety:
- AI-initiated terminal commands run in an isolated per-task working copy.
- Terminal commands NEVER have unrestricted direct write access to original user files.
- Task IDs are validated as strict identifiers (no traversal, no slashes).
- Symlinks are NOT preserved in isolated workspaces if they can reach files outside the sandbox.
- When a task completes:
    1. Inspects changes made in the isolated workspace.
    2. Identifies new, modified, and deleted files.
    3. REJECTS any change set that includes deletion or renaming (No-Delete Policy).
    4. Verifies source hashes against the initial snapshot before applying changes;
       stops and reports conflicts if the user modified the original file during the task.
    5. Applies new and modified files via atomic byte-exact writes, preserving binaries,
       encodings, and exact line endings.
    6. Automatically backs up every modified file prior to replacement.
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


class WorkspaceConflictError(ValueError):
    """Raised when source files were modified externally during task execution."""
    pass


class TaskWorkspaceSandbox:
    """Manages isolated per-task working copies and safe change reconciliation."""

    def __init__(self, workspace_path: Optional[str] = None):
        self.workspace_path = workspace_path
        self.sandbox_base = paths_service.get_app_data_dir() / "IsolatedTasks"
        self.sandbox_base.mkdir(parents=True, exist_ok=True)
        # In-memory manifest registry for active tasks:
        # task_id -> { "source": Path, "sandbox": Path, "initial_manifest": dict, "created_at": float }
        self._active_tasks: Dict[str, Dict[str, Any]] = {}

    def _compute_hash(self, path: Path) -> str:
        """Computes SHA-256 digest of a local file."""
        return backup_service.compute_file_sha256(path)

    def _build_manifest(self, base_dir: Path) -> Dict[str, str]:
        """Builds relative_path -> sha256 manifest of a directory tree."""
        manifest = {}
        for root, dirs, files in os.walk(base_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d not in (".git", "venv", "node_modules", "__pycache__", ".stroke_scratch")]
            for f in files:
                full_p = Path(root) / f
                try:
                    rel_p = str(full_p.relative_to(base_dir))
                    manifest[rel_p] = self._compute_hash(full_p)
                except Exception:
                    pass
        return manifest

    def _safe_copy_tree(self, source_dir: Path, target_dir: Path):
        """
        Recursively copies source_dir into target_dir.
        CRITICAL SYMLINK SAFETY:
        Symlinks are inspected: if any symlink points outside source_dir,
        it is NOT copied as an active symlink to prevent reaching files outside the sandbox.
        """
        source_canonical = source_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)

        for root, dirs, files in os.walk(source_dir, followlinks=False):
            dirs[:] = [d for d in dirs if d not in (".git", "venv", "node_modules", "__pycache__", ".stroke_scratch")]
            rel_root = Path(root).relative_to(source_dir)
            dest_root = target_dir / rel_root
            dest_root.mkdir(parents=True, exist_ok=True)

            for d in dirs:
                src_d = Path(root) / d
                if src_d.is_symlink():
                    try:
                        resolved_target = src_d.resolve()
                        if not (resolved_target == source_canonical or source_canonical in resolved_target.parents):
                            # Symlink escapes source workspace! OMIT to prevent sandbox escape.
                            print(f"[STROKE SANDBOX WARNING] Omitting escaping directory symlink: {src_d} -> {resolved_target}", flush=True)
                            continue
                    except Exception:
                        continue

            for f in files:
                src_f = Path(root) / f
                dest_f = dest_root / f

                if src_f.is_symlink():
                    try:
                        resolved_target = src_f.resolve()
                        if not (resolved_target == source_canonical or source_canonical in resolved_target.parents):
                            # Symlink escapes source workspace! OMIT to prevent sandbox escape.
                            print(f"[STROKE SANDBOX WARNING] Omitting escaping file symlink: {src_f} -> {resolved_target}", flush=True)
                            continue
                        # If within workspace, copy actual content rather than preserving symlink
                        shutil.copy2(resolved_target, dest_f)
                    except Exception as exc:
                        print(f"[STROKE SANDBOX WARNING] Failed to copy symlink {src_f}: {exc}", flush=True)
                else:
                    try:
                        shutil.copy2(src_f, dest_f)
                    except Exception as exc:
                        print(f"[STROKE SANDBOX WARNING] Failed to copy file {src_f}: {exc}", flush=True)

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
        Validates task_id as a strict identifier.
        """
        clean_task_id = workspace_service.validate_task_id(task_id)

        target_ws = source_workspace or self.workspace_path
        if not target_ws:
            raise ValueError("No workspace specified for task sandbox.")

        source = workspace_service.validate_path_access(target_ws)
        if not source.exists() or not source.is_dir():
            raise NotADirectoryError(f"Source workspace not found: {source}")

        # Ensure sandbox path is strictly within sandbox_base
        task_sandbox = (self.sandbox_base / clean_task_id).resolve()
        if task_sandbox.parent != self.sandbox_base.resolve():
            raise workspace_service.WorkspaceSecurityError(
                f"Task ID escape attempt denied: '{clean_task_id}' resolves outside sandbox base."
            )

        if task_sandbox.exists():
            shutil.rmtree(task_sandbox, ignore_errors=True)
        task_sandbox.mkdir(parents=True, exist_ok=True)

        # Copy source files with strict symlink containment
        self._safe_copy_tree(source, task_sandbox)

        # Record initial snapshot manifest to detect additions, modifications, and deletions
        initial_manifest = self._build_manifest(task_sandbox)

        self._active_tasks[clean_task_id] = {
            "source": source,
            "sandbox": task_sandbox,
            "initial_manifest": initial_manifest,
            "created_at": time.time()
        }

        return {
            "status": "created",
            "task_id": clean_task_id,
            "source_workspace": str(source),
            "isolated_workspace": str(task_sandbox),
            "files_tracked": len(initial_manifest)
        }

    def inspect_task_changes(self, task_id: str) -> Dict[str, Any]:
        """
        Inspects changes between the isolated workspace and the initial state.
        Identifies new_files, modified_files, and deleted_files.
        """
        clean_task_id = workspace_service.validate_task_id(task_id)
        task_data = self._active_tasks.get(clean_task_id)

        if not task_data:
            task_sandbox = (self.sandbox_base / clean_task_id).resolve()
            if not task_sandbox.exists():
                raise KeyError(f"No active isolated workspace found for task ID: {clean_task_id}")
            raise KeyError(f"Task session metadata missing for: {clean_task_id}")

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
            "task_id": clean_task_id,
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
        Enforces:
        1. Hard rejection if ANY deleted files are found (Absolute No-Delete Policy).
        2. Pre-application source hash check: verifies original files on disk still match
           the initial manifest. Stops and raises WorkspaceConflictError if the user changed
           the original file during the task.
        3. Applies modified and new files via byte-exact atomic writes (preserving binary bytes,
           exact line endings, and encodings).
        4. Automatic pre-modification backup for every modified file.
        """
        clean_task_id = workspace_service.validate_task_id(task_id)
        changes = self.inspect_task_changes(clean_task_id)
        task_data = self._active_tasks[clean_task_id]
        sandbox = task_data["sandbox"]
        source = task_data["source"]
        initial_manifest = task_data["initial_manifest"]

        # 1. HARD REJECTION on any file deletion
        if changes["has_deletions"]:
            deleted_list = ", ".join(changes["deleted_files"])
            raise DestructiveChangeSetError(
                f"REJECTED: Task '{clean_task_id}' attempted to delete existing files: [{deleted_list}]. "
                f"Stroke's Absolute No-Delete Policy prohibits applying change sets containing deletions."
            )

        # 2. SOURCE HASH CONFLICT DETECTION
        # Check if the user modified the original files outside the task while it was running
        conflicts = []
        for rel_path in changes["modified_files"]:
            src_file = source / rel_path
            if src_file.exists():
                current_src_hash = self._compute_hash(src_file)
                initial_hash = initial_manifest.get(rel_path)
                if initial_hash and current_src_hash != initial_hash:
                    conflicts.append({
                        "file": rel_path,
                        "initial_hash": initial_hash,
                        "current_source_hash": current_src_hash
                    })

        if conflicts:
            conflict_files = ", ".join([c["file"] for c in conflicts])
            raise WorkspaceConflictError(
                f"Source file conflict detected for task '{clean_task_id}': Original files were modified "
                f"outside the task while it was running: [{conflict_files}]. "
                f"Reconciliation stopped to prevent clobbering user changes."
            )

        applied_new = []
        applied_modified = []
        backups_created = []

        # 3. Apply modified files with pre-modification backups and byte-exact fidelity
        for rel_path in changes["modified_files"]:
            src_file = source / rel_path
            sandbox_file = sandbox / rel_path
            if not sandbox_file.exists():
                continue

            raw_bytes = sandbox_file.read_bytes()
            res = backup_service.atomic_write_file(
                target_path=str(src_file),
                content=raw_bytes,
                make_backup_if_exists=True,
                task_id=clean_task_id,
                description=f"{description} (Modified {rel_path})"
            )
            applied_modified.append(rel_path)
            if res.get("backup"):
                backups_created.append(res["backup"])

        # 4. Apply new files
        for rel_path in changes["new_files"]:
            src_file = source / rel_path
            sandbox_file = sandbox / rel_path
            if not sandbox_file.exists():
                continue

            raw_bytes = sandbox_file.read_bytes()
            src_file.parent.mkdir(parents=True, exist_ok=True)
            res = backup_service.atomic_write_file(
                target_path=str(src_file),
                content=raw_bytes,
                make_backup_if_exists=False,
                task_id=clean_task_id,
                description=f"{description} (Created {rel_path})"
            )
            applied_new.append(rel_path)

        return {
            "status": "success",
            "message": "All verified changes applied safely with automatic version backups.",
            "task_id": clean_task_id,
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
        clean_task_id = workspace_service.validate_task_id(task_id)
        task_data = self._active_tasks.pop(clean_task_id, None)
        task_sandbox = (self.sandbox_base / clean_task_id).resolve()
        if task_sandbox.exists() and task_sandbox.parent == self.sandbox_base.resolve():
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
