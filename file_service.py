"""
================================================================================
STROKE // NON-DESTRUCTIVE USER FILE SYSTEM SERVICE
================================================================================
Strictly enforces Stroke Requirements 1 & 2:
- USER-LEVEL FILE SYSTEM ACCESS: Read, create, edit, search, patch, inspect.
- ABSOLUTE NO-DELETE POLICY: Hard restriction. Stroke never deletes existing
  user files or directories under any circumstance.
- ZERO ELEVATION: Operates purely under standard logged-in user permissions.
- AUTOMATIC BACKUPS: Pre-modification backups are generated automatically
  before any user file modification.
================================================================================
"""

import os
import sys
import re
import difflib
import fnmatch
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

import backup_service
import workspace_service
from workspace_service import WorkspaceSecurityError


class NoDeletePolicyViolation(PermissionError):
    """Raised whenever any destructive deletion or removal operation is attempted."""
    pass


def list_directory(
    dir_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    include_hidden: bool = False
) -> Dict[str, Any]:
    """
    Lists files and directories inside an approved workspace.
    Returns structured metadata for each item.
    """
    target = workspace_service.validate_path_access(dir_path)
    if not target.exists():
        raise FileNotFoundError(f"Directory not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {target}")

    items = []
    
    def _scan(current: Path, depth: int):
        if depth > max_depth:
            return
        try:
            entries = sorted(list(current.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if not include_hidden and entry.name.startswith("."):
                continue
            is_dir = entry.is_dir()
            item_info = {
                "name": entry.name,
                "path": str(entry),
                "relative_path": str(entry.relative_to(target)),
                "is_dir": is_dir,
                "size_bytes": entry.stat().st_size if not is_dir else 0,
                "modified_at": entry.stat().st_mtime
            }
            items.append(item_info)
            if recursive and is_dir:
                _scan(entry, depth + 1)

    _scan(target, 1)

    return {
        "status": "success",
        "directory": str(target),
        "total_items": len(items),
        "items": items
    }


def read_file(
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_bytes: int = 2_000_000
) -> Dict[str, Any]:
    """
    Reads contents of a file in an approved workspace.
    Supports optional 1-indexed line slicing.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if not target.is_file():
        raise IsADirectoryError(f"Path is a directory, not a file: {target}")

    file_size = target.stat().st_size
    if file_size > max_bytes and start_line is None:
        raise ValueError(f"File size ({file_size} bytes) exceeds safety limit ({max_bytes} bytes). Specify start_line/end_line to read in chunks.")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise IOError(f"Failed to read file: {exc}")

    lines = content.splitlines(keepends=True)
    total_lines = len(lines)

    if start_line is not None or end_line is not None:
        s = max(1, start_line or 1)
        e = min(total_lines, end_line or total_lines)
        if s > e:
            sliced_content = ""
        else:
            sliced_content = "".join(lines[s - 1:e])
        is_sliced = True
    else:
        sliced_content = content
        is_sliced = False
        s = 1
        e = total_lines

    return {
        "status": "success",
        "file_path": str(target),
        "file_name": target.name,
        "total_lines": total_lines,
        "start_line": s,
        "end_line": e,
        "is_sliced": is_sliced,
        "content": sliced_content,
        "size_bytes": file_size
    }


def read_multiple_files(file_paths: List[str]) -> Dict[str, Any]:
    """Reads multiple files in an approved workspace in a single round-trip."""
    results = {}
    for fp in file_paths:
        try:
            results[fp] = read_file(fp)
        except Exception as exc:
            results[fp] = {"status": "error", "error": str(exc)}

    return {
        "status": "success",
        "total_requested": len(file_paths),
        "files": results
    }


def create_file(
    file_path: str,
    content: str,
    overwrite: bool = False,
    task_id: str = "ai_create"
) -> Dict[str, Any]:
    """
    Creates a new file in an approved workspace.
    If the file already exists:
    - If overwrite is False, rejects to prevent unintentional replacement.
    - If overwrite is True, generates a full backup first, then writes atomically.
    Never deletes anything.
    """
    target = workspace_service.validate_path_access(file_path)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"File '{target.name}' already exists. Use edit_file() to modify existing user files with automatic version backups."
        )

    res = backup_service.atomic_write_file(
        target_path=str(target),
        content=content,
        make_backup_if_exists=True,
        task_id=task_id,
        description=f"Created/overwritten file via Stroke file service ({task_id})"
    )
    return res


def edit_file(
    file_path: str,
    new_content: str,
    task_id: str = "ai_edit",
    description: str = "File edited by Stroke AI"
) -> Dict[str, Any]:
    """
    Safely edits an existing file.
    Always generates an automatic full version backup before applying changes.
    Enforces atomic writing.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"Cannot edit non-existent file: {target}. Use create_file() instead.")
    if not target.is_file():
        raise IsADirectoryError(f"Target is a directory: {target}")

    res = backup_service.atomic_write_file(
        target_path=str(target),
        content=new_content,
        make_backup_if_exists=True,
        task_id=task_id,
        description=description
    )
    return res


def create_directory(dir_path: str) -> Dict[str, Any]:
    """Creates a new directory (and any necessary parent directories) in an approved workspace."""
    target = workspace_service.validate_path_access(dir_path)
    if target.exists():
        if target.is_dir():
            return {"status": "success", "message": "Directory already exists", "path": str(target)}
        raise FileExistsError(f"A file already exists at this path: {target}")

    target.mkdir(parents=True, exist_ok=True)
    return {
        "status": "success",
        "message": "Directory created successfully",
        "path": str(target)
    }


def search_files(
    workspace_path: str,
    pattern: str = "*",
    max_results: int = 200
) -> Dict[str, Any]:
    """
    Searches for files matching a filename wildcard pattern (e.g. '*.py', '*hitbox*.luau').
    """
    target = workspace_service.validate_path_access(workspace_path)
    matches = []

    for root, dirs, files in os.walk(target):
        # Filter hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            if fnmatch.fnmatch(f, pattern):
                full_path = Path(root) / f
                matches.append({
                    "name": f,
                    "path": str(full_path),
                    "relative_path": str(full_path.relative_to(target)),
                    "size_bytes": full_path.stat().st_size
                })
                if len(matches) >= max_results:
                    break
        if len(matches) >= max_results:
            break

    return {
        "status": "success",
        "workspace": str(target),
        "pattern": pattern,
        "match_count": len(matches),
        "matches": matches
    }


def search_in_files(
    workspace_path: str,
    query: str,
    is_regex: bool = False,
    file_pattern: str = "*",
    max_matches: int = 150
) -> Dict[str, Any]:
    """
    Searches inside file contents across a workspace.
    Returns matched file paths, line numbers, and line text.
    """
    target = workspace_service.validate_path_access(workspace_path)
    results = []

    if is_regex:
        try:
            pattern_re = re.compile(query, re.IGNORECASE)
        except re.error as err:
            raise ValueError(f"Invalid regular expression '{query}': {err}")
    else:
        query_lower = query.lower()

    match_count = 0

    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            if not fnmatch.fnmatch(f, file_pattern):
                continue

            full_path = Path(root) / f
            # Skip massive files or binary files
            if full_path.stat().st_size > 2_500_000:
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            lines = content.splitlines()
            for idx, line in enumerate(lines, start=1):
                matched = bool(pattern_re.search(line)) if is_regex else (query_lower in line.lower())
                if matched:
                    results.append({
                        "file_path": str(full_path),
                        "relative_path": str(full_path.relative_to(target)),
                        "line_number": idx,
                        "line_text": line.strip()[:200]
                    })
                    match_count += 1
                    if match_count >= max_matches:
                        break
            if match_count >= max_matches:
                break
        if match_count >= max_matches:
            break

    return {
        "status": "success",
        "workspace": str(target),
        "query": query,
        "match_count": match_count,
        "matches": results
    }


def inspect_file(file_path: str) -> Dict[str, Any]:
    """
    Retrieves deep metadata and integrity information for a user file.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")

    stat = target.stat()
    is_dir = target.is_dir()
    
    sha256 = backup_service.compute_file_sha256(target) if not is_dir else None
    line_count = 0
    is_binary = False

    if not is_dir:
        try:
            with open(target, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
        except Exception:
            is_binary = True

    backups = backup_service.list_backups(str(target)) if not is_dir else []

    return {
        "status": "success",
        "file_path": str(target),
        "file_name": target.name,
        "is_dir": is_dir,
        "size_bytes": stat.st_size,
        "created_at": stat.st_ctime,
        "modified_at": stat.st_mtime,
        "line_count": line_count,
        "is_binary": is_binary,
        "sha256": sha256,
        "available_backups_count": len(backups)
    }


def apply_patch(
    file_path: str,
    patch_diff: str,
    task_id: str = "ai_patch"
) -> Dict[str, Any]:
    """
    Applies a standard unified diff patch to an existing user file.
    Creates an automatic backup before modifying.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found for patching: {target}")

    original_text = target.read_text(encoding="utf-8", errors="replace")
    original_lines = original_text.splitlines(keepends=True)

    # Parse unified diff patch chunks
    patched_lines = list(original_lines)
    patch_lines = patch_diff.strip().splitlines()

    # Apply line-by-line substitutions or unified diff hunks
    hunk_pattern = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    current_hunk = None
    applied_changes = 0

    new_lines = []
    orig_idx = 0

    for pl in patch_lines:
        if pl.startswith("---") or pl.startswith("+++"):
            continue
        m = hunk_pattern.match(pl)
        if m:
            continue
        if pl.startswith("+"):
            new_lines.append(pl[1:] + "\n")
            applied_changes += 1
        elif pl.startswith("-"):
            orig_idx += 1
            applied_changes += 1
        elif pl.startswith(" "):
            new_lines.append(pl[1:] + "\n")
            orig_idx += 1

    if new_lines:
        new_content = "".join(new_lines)
    else:
        # Fallback if patch was raw replacement
        new_content = patch_diff

    # Write modified content with auto-backup
    res = edit_file(
        str(target),
        new_content,
        task_id=task_id,
        description=f"Unified patch applied ({applied_changes} line changes)"
    )
    res["patch_applied"] = True
    return res


def compare_file_versions(file_path: str, comparison_content: str) -> Dict[str, Any]:
    """Generates a side-by-side / unified diff between current file and proposed content."""
    target = workspace_service.validate_path_access(file_path)
    if target.exists():
        current_text = target.read_text(encoding="utf-8", errors="replace")
    else:
        current_text = ""

    diff_lines = list(difflib.unified_diff(
        current_text.splitlines(keepends=True),
        comparison_content.splitlines(keepends=True),
        fromfile=f"Current ({target.name})",
        tofile=f"Proposed Content"
    ))

    return {
        "status": "success",
        "file_path": str(target),
        "is_identical": current_text == comparison_content,
        "diff": "".join(diff_lines)
    }


def inspect_workspace(workspace_path: str) -> Dict[str, Any]:
    """Generates a high-level architectural overview of a project workspace."""
    target = workspace_service.validate_path_access(workspace_path)
    
    total_files = 0
    total_dirs = 0
    total_bytes = 0
    file_extensions: Dict[str, int] = {}
    key_files = []

    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        total_dirs += len(dirs)
        for f in files:
            if f.startswith("."):
                continue
            total_files += 1
            fp = Path(root) / f
            try:
                sz = fp.stat().st_size
                total_bytes += sz
            except Exception:
                pass
            ext = fp.suffix.lower() or "<no_ext>"
            file_extensions[ext] = file_extensions.get(ext, 0) + 1
            if f in ("main.py", "package.json", "Cargo.toml", "index.html", "requirements.txt", "README.md"):
                key_files.append(str(fp.relative_to(target)))

    return {
        "status": "success",
        "workspace_path": str(target),
        "workspace_name": target.name,
        "total_files": total_files,
        "total_directories": total_dirs,
        "total_size_bytes": total_bytes,
        "top_file_types": sorted(file_extensions.items(), key=lambda x: x[1], reverse=True)[:8],
        "key_manifest_files": key_files
    }


# ==============================================================================
# ABSOLUTE NO-DELETE POLICY ENFORCEMENT
# ==============================================================================

def delete_file(*args, **kwargs):
    """Explicitly prohibited by Stroke Absolute No-Delete Policy."""
    raise NoDeletePolicyViolation(
        "STROKE SECURITY VIOLATION: Deletion of existing user files is strictly prohibited by Stroke's Absolute No-Delete Policy."
    )

def remove_directory(*args, **kwargs):
    """Explicitly prohibited by Stroke Absolute No-Delete Policy."""
    raise NoDeletePolicyViolation(
        "STROKE SECURITY VIOLATION: Deletion of directories is strictly prohibited by Stroke's Absolute No-Delete Policy."
    )
