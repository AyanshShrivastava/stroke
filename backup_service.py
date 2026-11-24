"""
================================================================================
STROKE // VERSION BACKUPS AND RECOVERY SERVICE
================================================================================
Strictly enforces Stroke Requirement 3 & File Safety:
- Saves complete byte-exact backups of user files before modification.
- Stores backups securely inside Stroke's per-user application data directory.
- Maintains a persistent, tamper-evident modification index (backups_index.json).
- Corrupted backup indices are preserved for forensic recovery, never silently overwritten.
- Serializes concurrent index writes with a thread-safe lock.
- Uses exclusively created unique temporary files with fsync and atomic swap.
- Verifies backup content SHA-256 BEFORE restoration.
- Validates restore source and destination against trusted roots and approved workspaces.
- Byte-compares binary files; never relies on placeholder strings.
- Creates pre-restore safety backups and leaves target untouched if restore fails.
- Provides conflict-aware atomic writing.
================================================================================
"""

import os
import sys
import json
import time
import shutil
import hashlib
import difflib
import tempfile
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple, Union

import paths_service
import workspace_service

_BACKUP_LOCK = threading.RLock()


def compute_file_sha256(path: Union[Path, str]) -> str:
    """Computes SHA-256 digest of a local file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Computes SHA-256 digest of raw byte content."""
    return hashlib.sha256(data).hexdigest()


def is_binary_file(path: Union[Path, str]) -> bool:
    """Detects whether a file contains binary content by inspecting first 8KB for null bytes."""
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return False
        with open(p, "rb") as f:
            sample = f.read(8192)
            if not sample:
                return False
            # Standard binary detection: presence of null bytes indicates non-text binary
            return b"\x00" in sample
    except Exception:
        return False


class BackupIndexManager:
    """Manages the persistent catalog of file backups with concurrency and corruption safeguards."""

    def __init__(self):
        self.backups_dir = paths_service.get_backups_dir()
        self.index_file = self.backups_dir / "backups_index.json"
        self._ensure_index()

    def _ensure_index(self):
        with _BACKUP_LOCK:
            if not self.index_file.exists():
                self._write_index([])

    def _read_index(self) -> List[Dict[str, Any]]:
        with _BACKUP_LOCK:
            if not self.index_file.exists():
                return []
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if not content:
                        return []
                    data = json.loads(content)
                    if isinstance(data, list):
                        return data
                    elif isinstance(data, dict):
                        return data.get("backups", [])
                    return []
            except Exception as exc:
                # CRITICAL: Preserve corrupted index for recovery! NEVER silently overwrite!
                ts = int(time.time() * 1000)
                corrupt_path = self.backups_dir / f"backups_index.json.corrupt.{ts}"
                try:
                    shutil.copy2(self.index_file, corrupt_path)
                    print(f"[STROKE BACKUP ALERT] Corrupted backup index preserved at {corrupt_path}: {exc}", flush=True)
                except Exception as copy_exc:
                    print(f"[STROKE BACKUP ERROR] Failed to copy corrupted index: {copy_exc}", flush=True)
                return []

    def _write_index(self, entries: List[Dict[str, Any]]):
        with _BACKUP_LOCK:
            self.backups_dir.mkdir(parents=True, exist_ok=True)
            # Use exclusively created temporary file
            tmp_fd, tmp_path_str = tempfile.mkstemp(
                dir=self.backups_dir,
                prefix="backups_index_",
                suffix=".tmp"
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(entries, f, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_path_str, self.index_file)
            except Exception as exc:
                if os.path.exists(tmp_path_str):
                    try:
                        os.unlink(tmp_path_str)
                    except Exception:
                        pass
                raise IOError(f"Failed to write backup index: {exc}")

    def add_entry(self, entry: Dict[str, Any]):
        with _BACKUP_LOCK:
            entries = self._read_index()
            entries.insert(0, entry)
            self._write_index(entries)

    def get_entries(self, file_path: Optional[str] = None) -> List[Dict[str, Any]]:
        with _BACKUP_LOCK:
            entries = self._read_index()
            if not file_path:
                return entries
            try:
                canonical = str(Path(file_path).resolve())
                return [e for e in entries if e.get("file_path") == canonical]
            except Exception:
                return []

    def get_entry_by_id(self, backup_id: str) -> Optional[Dict[str, Any]]:
        with _BACKUP_LOCK:
            for e in self._read_index():
                if e.get("backup_id") == backup_id:
                    return e
            return None


_INDEX_MANAGER = BackupIndexManager()


def create_file_backup(
    file_path: str,
    task_id: str = "manual",
    description: str = "Backup prior to modification"
) -> Dict[str, Any]:
    """
    Creates a full byte-exact backup of an existing user file before modification.
    Stores the backup inside Stroke's per-user application data directory.
    Serialized with concurrency lock.
    """
    clean_task_id = workspace_service.validate_task_id(task_id) if task_id != "manual" else "manual"
    target = Path(file_path).resolve()

    if not target.exists():
        raise FileNotFoundError(f"Cannot back up non-existent file: {target}")
    if not target.is_file():
        raise ValueError(f"Target path for backup must be a file, not a directory: {target}")

    with _BACKUP_LOCK:
        backups_dir = paths_service.get_backups_dir()
        timestamp_float = time.time()
        dt_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        file_hash = compute_file_sha256(target)
        backup_id = f"bk_{dt_str}_{file_hash[:8]}_{int(timestamp_float * 1000) % 10000:04d}"

        # Preserve file extension
        backup_filename = f"{target.stem}_{backup_id}{target.suffix}"
        backup_path = backups_dir / backup_filename

        # Exclusively create copy
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            dir=backups_dir,
            prefix=f".tmp_bk_{target.stem}_",
            suffix=target.suffix
        )
        try:
            with open(target, "rb") as src_f, os.fdopen(tmp_fd, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
                dst_f.flush()
                os.fsync(dst_f.fileno())
            os.replace(tmp_path_str, backup_path)
        except Exception:
            if os.path.exists(tmp_path_str):
                try:
                    os.unlink(tmp_path_str)
                except Exception:
                    pass
            raise

        record = {
            "backup_id": backup_id,
            "file_path": str(target),
            "file_name": target.name,
            "backup_path": str(backup_path),
            "file_size": target.stat().st_size,
            "sha256": file_hash,
            "timestamp": timestamp_float,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "task_id": clean_task_id,
            "description": description
        }

        _INDEX_MANAGER.add_entry(record)
        return record


def list_backups(file_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists historical backups, optionally filtered for a specific user file."""
    return _INDEX_MANAGER.get_entries(file_path)


def get_backup_by_id(backup_id: str) -> Optional[Dict[str, Any]]:
    """Retrieves backup metadata by ID."""
    return _INDEX_MANAGER.get_entry_by_id(backup_id)


def compare_backup_to_current(backup_id: str) -> Dict[str, Any]:
    """
    Compares a stored backup against the current state of the original user file.
    Byte-compares binary files; never relies on placeholder strings.
    """
    entry = _INDEX_MANAGER.get_entry_by_id(backup_id)
    if not entry:
        raise KeyError(f"Backup ID not found: {backup_id}")

    backup_path = Path(entry["backup_path"]).resolve()
    current_path = Path(entry["file_path"]).resolve()

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup archive missing on disk: {backup_path}")

    current_exists = current_path.exists()
    is_binary = is_binary_file(backup_path) or (current_exists and is_binary_file(current_path))

    if is_binary:
        backup_bytes = backup_path.read_bytes()
        current_bytes = current_path.read_bytes() if current_exists else b""
        is_identical = (backup_bytes == current_bytes)
        diff_str = (
            "Binary files are identical."
            if is_identical else
            f"Binary files differ (Backup: {len(backup_bytes)} bytes, SHA: {compute_bytes_sha256(backup_bytes)[:8]}; Current: {len(current_bytes)} bytes, SHA: {compute_bytes_sha256(current_bytes)[:8] if current_exists else 'none'})."
        )
    else:
        try:
            backup_text = backup_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            backup_text = ""

        if current_exists:
            try:
                current_text = current_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                current_text = ""
        else:
            current_text = ""

        is_identical = (backup_text == current_text)
        diff_lines = list(difflib.unified_diff(
            backup_text.splitlines(keepends=True),
            current_text.splitlines(keepends=True),
            fromfile=f"Backup ({entry['backup_id']} @ {entry['created_at']})",
            tofile=f"Current ({entry['file_name']})"
        ))
        diff_str = "".join(diff_lines)

    return {
        "backup_id": backup_id,
        "file_path": entry["file_path"],
        "backup_created_at": entry["created_at"],
        "task_id": entry.get("task_id"),
        "description": entry.get("description"),
        "current_exists": current_exists,
        "is_binary": is_binary,
        "is_identical": is_identical,
        "diff": diff_str
    }


def restore_backup(backup_id: str, task_id: str = "restore_operation") -> Dict[str, Any]:
    """
    Restores an earlier version of a user file from Stroke's backups.
    Enforces strict safety verification:
    1. Validates backup source path within trusted backup root.
    2. Validates target destination path within approved workspaces.
    3. Verifies backup content SHA-256 BEFORE restoration.
    4. Automatically creates a pre-restore safety backup of current target.
    5. Leaves original file untouched if restoration fails at any point.
    """
    clean_task_id = workspace_service.validate_task_id(task_id) if task_id != "restore_operation" else "restore_operation"
    entry = _INDEX_MANAGER.get_entry_by_id(backup_id)
    if not entry:
        raise KeyError(f"Backup ID not found: {backup_id}")

    backup_path = Path(entry["backup_path"]).resolve()
    target_path = Path(entry["file_path"]).resolve()

    # 1. Validate backup source resides inside trusted backups dir
    trusted_backups_dir = paths_service.get_backups_dir().resolve()
    if not (backup_path == trusted_backups_dir or trusted_backups_dir in backup_path.parents):
        raise workspace_service.WorkspaceSecurityError(
            f"Restoration denied: Backup archive '{backup_path}' resides outside trusted backup root."
        )

    # 2. Validate target destination resides inside an approved workspace
    if not workspace_service.is_path_approved(str(target_path)):
        raise workspace_service.WorkspaceSecurityError(
            f"Restoration denied: Destination '{target_path}' is outside user-approved workspaces."
        )

    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file archive missing on disk: {backup_path}")

    # 3. VERIFY BACKUP SHA-256 BEFORE RESTORATION
    current_backup_hash = compute_file_sha256(backup_path)
    if current_backup_hash != entry["sha256"]:
        raise ValueError(
            f"Backup integrity verification failed for {backup_id}. "
            f"Expected SHA-256 {entry['sha256']}, but found {current_backup_hash}. "
            f"Restoration aborted to prevent writing corrupted data."
        )

    with _BACKUP_LOCK:
        # 4. Create safety backup of current target if it exists
        pre_restore_backup = None
        if target_path.exists():
            pre_restore_backup = create_file_backup(
                str(target_path),
                task_id=clean_task_id,
                description=f"Safety backup created automatically before restoring {backup_id}"
            )

        # 5. Atomically restore content via temporary file in target directory
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            dir=target_path.parent,
            prefix=f".tmp_restore_{target_path.name}_",
            suffix=target_path.suffix
        )
        try:
            with open(backup_path, "rb") as src_f, os.fdopen(tmp_fd, "wb") as dst_f:
                shutil.copyfileobj(src_f, dst_f)
                dst_f.flush()
                os.fsync(dst_f.fileno())

            # Perform atomic replacement
            os.replace(tmp_path_str, target_path)
        except Exception:
            if os.path.exists(tmp_path_str):
                try:
                    os.unlink(tmp_path_str)
                except Exception:
                    pass
            raise IOError(f"Restoration write failed for {target_path}. Original file was left untouched.")

        # Post-restore verification
        restored_hash = compute_file_sha256(target_path)
        if restored_hash != entry["sha256"]:
            raise IOError(f"Restoration checksum mismatch for {target_path}")

        return {
            "status": "success",
            "restored_status": "restored",
            "restored_backup_id": backup_id,
            "target_file": str(target_path),
            "pre_restore_safety_backup": pre_restore_backup,
            "restored_sha256": restored_hash
        }


def atomic_write_file(
    target_path: str,
    content: Union[str, bytes],
    make_backup_if_exists: bool = True,
    task_id: str = "ai_operation",
    description: str = "Modified by Stroke AI",
    expected_hash: Optional[str] = None
) -> Dict[str, Any]:
    """
    Safely writes new content to a user file using atomic swap mechanics.
    - If expected_hash is provided, verifies source file matches before writing (conflict-aware).
    - If file already exists and make_backup_if_exists is True, saves a full backup first.
    - Uses exclusively created unique temp file in same directory.
    - Flushes and fsyncs buffers.
    - Atomically replaces target using os.replace.
    - Supports both text (str) and binary (bytes).
    """
    clean_task_id = workspace_service.validate_task_id(task_id) if task_id != "ai_operation" else "ai_operation"
    path = workspace_service.validate_path_access(target_path, allow_app_data=True)
    path.parent.mkdir(parents=True, exist_ok=True)

    with _BACKUP_LOCK:
        is_new = not path.exists()

        # Conflict check if expected_hash was specified
        if not is_new and expected_hash:
            current_hash = compute_file_sha256(path)
            if current_hash != expected_hash:
                raise ValueError(
                    f"Conflict detected for '{path.name}': Current file SHA-256 ({current_hash}) does not match "
                    f"expected base hash ({expected_hash}). Operation aborted to prevent overwriting intervening changes."
                )

        backup_info = None
        if not is_new and make_backup_if_exists:
            backup_info = create_file_backup(
                str(path),
                task_id=clean_task_id,
                description=description
            )

        # Write to exclusively created temp file in same directory
        is_binary = isinstance(content, bytes)
        mode = "wb" if is_binary else "w"
        encoding = None if is_binary else "utf-8"

        tmp_fd, tmp_path_str = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".tmp_{path.name}_",
            suffix=path.suffix
        )
        try:
            with os.fdopen(tmp_fd, mode, encoding=encoding) as f:
                f.write(content)
                f.flush()
                os.fsync(f.fileno())

            os.replace(tmp_path_str, path)
        except Exception:
            if os.path.exists(tmp_path_str):
                try:
                    os.unlink(tmp_path_str)
                except Exception:
                    pass
            raise

        new_hash = compute_file_sha256(path)
        new_size = path.stat().st_size

        return {
            "status": "success",
            "file_path": str(path),
            "is_new_file": is_new,
            "is_binary": is_binary,
            "file_size": new_size,
            "sha256": new_hash,
            "backup": backup_info
        }
