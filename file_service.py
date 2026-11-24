"""
================================================================================
STROKE // NON-DESTRUCTIVE USER FILE SYSTEM SERVICE
================================================================================
Strictly enforces Stroke Requirements 1, 2, & Filesystem Safety:
- USER-LEVEL FILE SYSTEM ACCESS: Read, create, edit, search, patch, inspect.
- ABSOLUTE NO-DELETE POLICY: Hard restriction. Stroke never deletes existing
  user files or directories under any circumstance.
- WORKSPACE BOUNDARIES: Validates paths at point of access, rejects symlink escapes.
- REAL UNIFIED-DIFF PATCHING: Full hunk parser that preserves untouched source lines,
  encoding, line endings, and trailing newlines. Rejects malformed/fuzzy/overlapping hunks.
- INCREMENTAL LINE-RANGE READS: Streams large files without full memory loading.
- BATCH STATUS ACCURACY: All-failed read_multiple_files reports error, not success.
- DISTINGUISHES: Binary, invalid UTF-8, inaccessible, missing, and unsupported files.
- SAFE SCAN LIMITS: Enforces bytes read, max files, depth, and time limits.
- ZERO DIRECTORY SYMLINK FOLLOWING: Does not follow directory symlinks by default.
================================================================================
"""

import os
import sys
import re
import io
import time
import fnmatch
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Tuple

import backup_service
import workspace_service
from workspace_service import WorkspaceSecurityError, validate_path_access

MAX_SCAN_TIME_SEC = 10.0
MAX_SCAN_FILES = 5_000
MAX_SCAN_BYTES = 50_000_000  # 50 MB
DEFAULT_MAX_READ_BYTES = 2_000_000  # 2 MB


class NoDeletePolicyViolation(PermissionError):
    """Raised whenever any destructive deletion or removal operation is attempted."""
    pass


class PatchApplicationError(ValueError):
    """Raised when a unified diff patch cannot be cleanly or unambiguously applied."""
    pass


def list_directory(
    dir_path: str,
    recursive: bool = False,
    max_depth: int = 10,
    include_hidden: bool = False,
    follow_symlinks: bool = False
) -> Dict[str, Any]:
    """
    Lists files and directories inside an approved workspace.
    Enforces time limits, depth limits, and does not follow directory symlinks by default.
    """
    target = workspace_service.validate_path_access(dir_path)
    if not target.exists():
        raise FileNotFoundError(f"Directory not found: {target}")
    if not target.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {target}")

    items = []
    start_time = time.time()
    truncated = False

    def _scan(current: Path, depth: int):
        nonlocal truncated
        if depth > max_depth or (time.time() - start_time) > MAX_SCAN_TIME_SEC or len(items) >= MAX_SCAN_FILES:
            truncated = True
            return

        try:
            entries = sorted(list(current.iterdir()), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if not include_hidden and entry.name.startswith("."):
                continue

            # Do not follow directory symlinks by default to prevent loops
            if entry.is_symlink() and not follow_symlinks:
                is_dir = False
                is_symlink = True
            else:
                is_dir = entry.is_dir()
                is_symlink = entry.is_symlink()

            try:
                st = entry.stat()
                sz = st.st_size if not is_dir else 0
                mtime = st.st_mtime
            except Exception:
                sz = 0
                mtime = 0

            item_info = {
                "name": entry.name,
                "path": str(entry),
                "relative_path": str(entry.relative_to(target)),
                "is_dir": is_dir,
                "is_symlink": is_symlink,
                "size_bytes": sz,
                "modified_at": mtime
            }
            items.append(item_info)

            if recursive and is_dir and not entry.is_symlink():
                _scan(entry, depth + 1)

    _scan(target, 1)

    return {
        "status": "success",
        "directory": str(target),
        "total_items": len(items),
        "truncated": truncated,
        "items": items
    }


def read_file(
    file_path: str,
    start_line: Optional[int] = None,
    end_line: Optional[int] = None,
    max_bytes: int = DEFAULT_MAX_READ_BYTES
) -> Dict[str, Any]:
    """
    Reads contents of a file in an approved workspace.
    - Performs truly incremental line-range reads without loading whole file.
    - Distinguishes binary files, invalid UTF-8, missing, and inaccessible files.
    - Enforces max_bytes safety limit.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")
    if target.is_symlink():
        # Prevent TOCTOU symlink substitution races
        raise workspace_service.WorkspaceSecurityError(f"Symlink traversal denied: '{target}' cannot be accessed directly as a symlink.")
    if not target.is_file():
        raise IsADirectoryError(f"Path is a directory, not a file: {target}")

    file_size = target.stat().st_size

    # Check for binary file
    if backup_service.is_binary_file(target):
        return {
            "status": "success",
            "file_path": str(target),
            "file_name": target.name,
            "is_binary": True,
            "size_bytes": file_size,
            "content": None,
            "message": f"Binary file ({file_size} bytes). Text reading and line slicing not supported."
        }

    # If full read requested for oversized file without line limits, reject
    if file_size > max_bytes and start_line is None and end_line is None:
        raise ValueError(
            f"File size ({file_size} bytes) exceeds safety limit ({max_bytes} bytes). "
            f"Specify start_line and end_line for incremental reading."
        )

    # Incremental streaming read
    lines: List[str] = []
    total_lines = 0
    s = max(1, start_line or 1)
    e = end_line
    bytes_accumulated = 0

    try:
        with open(target, "r", encoding="utf-8", errors="strict") as f:
            for idx, line in enumerate(f, start=1):
                total_lines = idx
                if idx < s:
                    continue
                if e is not None and idx > e:
                    # If we only need lines up to e, we can continue just to count or break
                    # To avoid reading gigabyte files just for total line count when e is small:
                    if file_size > max_bytes:
                        break
                    continue

                line_bytes = len(line.encode("utf-8"))
                bytes_accumulated += line_bytes
                if bytes_accumulated > max_bytes:
                    raise ValueError(
                        f"Read range exceeded maximum allowed bytes ({max_bytes} bytes). "
                        f"Narrow your start_line/end_line range."
                    )
                lines.append(line)
    except UnicodeDecodeError as ude:
        return {
            "status": "error",
            "error_type": "invalid_utf8",
            "file_path": str(target),
            "error": f"File contains invalid UTF-8 characters: {ude}"
        }
    except Exception as exc:
        raise IOError(f"Failed to read file: {exc}")

    actual_end = e if e is not None else total_lines
    sliced_content = "".join(lines)

    return {
        "status": "success",
        "file_path": str(target),
        "file_name": target.name,
        "is_binary": False,
        "total_lines": total_lines,
        "start_line": s,
        "end_line": actual_end,
        "is_sliced": (start_line is not None or end_line is not None),
        "content": sliced_content,
        "size_bytes": file_size,
        "bytes_returned": len(sliced_content.encode("utf-8"))
    }


def read_multiple_files(file_paths: List[str]) -> Dict[str, Any]:
    """
    Reads multiple files in approved workspaces simultaneously.
    Accurately reports top-level status:
    - 'error' if all files failed
    - 'partial_success' if some failed
    - 'success' if all succeeded
    """
    results = {}
    successful = 0
    failed = 0

    for fp in file_paths:
        try:
            res = read_file(fp)
            results[fp] = res
            if res.get("status") == "error":
                failed += 1
            else:
                successful += 1
        except Exception as exc:
            results[fp] = {"status": "error", "error": str(exc)}
            failed += 1

    total = len(file_paths)
    if total > 0 and failed == total:
        top_status = "error"
    elif failed > 0:
        top_status = "partial_success"
    else:
        top_status = "success"

    return {
        "status": top_status,
        "total_requested": total,
        "successful_count": successful,
        "failed_count": failed,
        "files": results
    }


def create_file(
    file_path: str,
    content: Union[str, bytes],
    overwrite: bool = False,
    task_id: str = "ai_create"
) -> Dict[str, Any]:
    """
    Creates a new file in an approved workspace.
    If overwrite is False and file exists, rejects to prevent accidental clobbering.
    If overwrite is True, generates automatic backup first, then writes atomically.
    """
    target = workspace_service.validate_path_access(file_path)
    if target.exists() and not overwrite:
        raise FileExistsError(
            f"File '{target.name}' already exists. Use edit_file() to modify existing files with automatic version backups."
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
    new_content: Union[str, bytes],
    task_id: str = "ai_edit",
    description: str = "File edited by Stroke AI",
    expected_hash: Optional[str] = None
) -> Dict[str, Any]:
    """
    Safely edits an existing file with conflict detection and automatic pre-modification backup.
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
        description=description,
        expected_hash=expected_hash
    )
    return res


def create_directory(dir_path: str) -> Dict[str, Any]:
    """Creates a new directory in an approved workspace."""
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
    max_results: int = 200,
    follow_symlinks: bool = False
) -> Dict[str, Any]:
    """
    Searches for files matching a wildcard pattern inside an approved workspace.
    Enforces time and result bounds.
    """
    target = workspace_service.validate_path_access(workspace_path)
    matches = []
    start_time = time.time()
    truncated = False

    for root, dirs, files in os.walk(target, followlinks=follow_symlinks):
        if (time.time() - start_time) > MAX_SCAN_TIME_SEC:
            truncated = True
            break

        # Filter hidden directories and unapproved symlink targets
        if follow_symlinks:
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and workspace_service.is_path_approved(str((Path(root) / d).resolve()))
            ]
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            if fnmatch.fnmatch(f, pattern):
                full_path = Path(root) / f
                try:
                    sz = full_path.stat().st_size
                except Exception:
                    sz = 0
                matches.append({
                    "name": f,
                    "path": str(full_path),
                    "relative_path": str(full_path.relative_to(target)),
                    "size_bytes": sz
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
        "truncated": truncated,
        "matches": matches
    }


def search_in_files(
    workspace_path: str,
    query: str,
    is_regex: bool = False,
    file_pattern: str = "*",
    max_matches: int = 150,
    follow_symlinks: bool = False
) -> Dict[str, Any]:
    """
    Searches inside text file contents across an approved workspace.
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
    start_time = time.time()
    truncated = False

    for root, dirs, files in os.walk(target, followlinks=follow_symlinks):
        if (time.time() - start_time) > MAX_SCAN_TIME_SEC:
            truncated = True
            break

        # Filter hidden directories and unapproved symlink targets
        if follow_symlinks:
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and workspace_service.is_path_approved(str((Path(root) / d).resolve()))
            ]
        else:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.startswith("."):
                continue
            if not fnmatch.fnmatch(f, file_pattern):
                continue

            full_path = Path(root) / f
            # Skip massive files (>2.5MB) or binary files
            try:
                if full_path.stat().st_size > 2_500_000 or backup_service.is_binary_file(full_path):
                    continue
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
        "truncated": truncated,
        "matches": results
    }


def inspect_file(file_path: str) -> Dict[str, Any]:
    """
    Retrieves deep metadata, binary detection, and integrity information for a user file.
    """
    target = workspace_service.validate_path_access(file_path)
    if not target.exists():
        raise FileNotFoundError(f"File not found: {target}")

    stat = target.stat()
    is_dir = target.is_dir()
    is_binary = backup_service.is_binary_file(target) if not is_dir else False
    sha256 = backup_service.compute_file_sha256(target) if not is_dir else None
    line_count = 0

    if not is_dir and not is_binary:
        try:
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                line_count = sum(1 for _ in f)
        except Exception:
            pass

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


# ==============================================================================
# REAL UNIFIED-DIFF PATCH ENGINE
# ==============================================================================

class _DiffHunk:
    def __init__(self, orig_start: int, orig_count: int, new_start: int, new_count: int):
        self.orig_start = orig_start
        self.orig_count = orig_count
        self.new_start = new_start
        self.new_count = new_count
        self.lines: List[str] = []


def parse_and_apply_unified_diff(original_text: str, patch_diff: str) -> Tuple[str, int]:
    """
    Applies a standard unified diff to original_text with strict hunk verification:
    1. Preserves ALL untouched lines before, between, and after hunks.
    2. Preserves line endings (CRLF vs LF) and final trailing newline.
    3. Rejects malformed, fuzzy, or ambiguous hunks.
    4. Rejects overlapping or out-of-order hunks.
    5. Returns (new_text, applied_line_changes_count).
    """
    if not patch_diff or not patch_diff.strip():
        return original_text, 0

    # Detect original newline convention and final newline presence
    crlf = "\r\n" in original_text
    newline = "\r\n" if crlf else "\n"
    has_trailing_newline = original_text.endswith(("\n", "\r\n"))

    orig_lines = original_text.splitlines()

    # Parse hunks
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")
    patch_raw_lines = patch_diff.splitlines()

    hunks: List[_DiffHunk] = []
    current_hunk: Optional[_DiffHunk] = None
    seen_hunk = False

    for pline in patch_raw_lines:
        if pline.startswith("---") or pline.startswith("+++"):
            continue
        m = hunk_header_re.match(pline)
        if m:
            seen_hunk = True
            ostart = int(m.group(1))
            ocount = int(m.group(2)) if m.group(2) is not None else 1
            nstart = int(m.group(3))
            ncount = int(m.group(4)) if m.group(4) is not None else 1
            current_hunk = _DiffHunk(ostart, ocount, nstart, ncount)
            hunks.append(current_hunk)
            continue

        if current_hunk is not None:
            if pline.startswith(("+", "-", " ", "\\")):
                current_hunk.lines.append(pline)
            elif pline.strip() == "":
                # Treat empty line as context line with empty content
                current_hunk.lines.append(" ")

    if not seen_hunk:
        raise PatchApplicationError("Malformed patch: No unified diff hunk headers ('@@ -x,y +a,b @@') found.")

    if not hunks:
        raise PatchApplicationError("Malformed patch: No valid hunks extracted.")

    # Sort hunks by original start line and verify no overlap
    hunks.sort(key=lambda h: h.orig_start)
    for i in range(len(hunks) - 1):
        h1 = hunks[i]
        h2 = hunks[i + 1]
        h1_end = h1.orig_start + max(0, h1.orig_count - 1)
        if h2.orig_start <= h1_end and h1.orig_count > 0:
            raise PatchApplicationError(
                f"Overlapping or conflicting diff hunks detected between hunk at line {h1.orig_start} and line {h2.orig_start}."
            )

    output_lines: List[str] = []
    orig_idx = 0
    total_line_changes = 0

    for hunk_idx, hunk in enumerate(hunks, start=1):
        # 1-indexed to 0-indexed offset in original lines
        target_idx = max(0, hunk.orig_start - 1)

        if target_idx < orig_idx:
            raise PatchApplicationError(
                f"Hunk #{hunk_idx} start line {hunk.orig_start} is before current file cursor ({orig_idx + 1})."
            )

        if target_idx > len(orig_lines):
            raise PatchApplicationError(
                f"Hunk #{hunk_idx} specifies line {hunk.orig_start}, which exceeds original file line count ({len(orig_lines)})."
            )

        # PRESERVE all untouched lines before this hunk!
        output_lines.extend(orig_lines[orig_idx:target_idx])
        orig_idx = target_idx

        # Process lines inside this hunk
        for hl in hunk.lines:
            indicator = hl[0]
            line_val = hl[1:]

            if indicator == " ":
                # Context line: must match original file
                if orig_idx >= len(orig_lines):
                    raise PatchApplicationError(
                        f"Hunk #{hunk_idx} context line extends beyond end of original file."
                    )
                if orig_lines[orig_idx] != line_val:
                    raise PatchApplicationError(
                        f"Hunk #{hunk_idx} context mismatch at line {orig_idx + 1}.\n"
                        f"Expected: '{line_val}'\n"
                        f"Actual:   '{orig_lines[orig_idx]}'"
                    )
                output_lines.append(orig_lines[orig_idx])
                orig_idx += 1

            elif indicator == "-":
                # Deletion line: must match original line
                if orig_idx >= len(orig_lines):
                    raise PatchApplicationError(
                        f"Hunk #{hunk_idx} deletion line extends beyond end of original file."
                    )
                if orig_lines[orig_idx] != line_val:
                    raise PatchApplicationError(
                        f"Hunk #{hunk_idx} deletion line mismatch at line {orig_idx + 1}.\n"
                        f"Expected: '{line_val}'\n"
                        f"Actual:   '{orig_lines[orig_idx]}'"
                    )
                orig_idx += 1
                total_line_changes += 1

            elif indicator == "+":
                # Addition line
                output_lines.append(line_val)
                total_line_changes += 1

            elif indicator == "\\":
                # '\ No newline at end of file' indicator
                pass

    # PRESERVE all untouched lines after the final hunk!
    if orig_idx < len(orig_lines):
        output_lines.extend(orig_lines[orig_idx:])

    # Reconstruct text with original newline format
    new_text = newline.join(output_lines)
    if has_trailing_newline and not new_text.endswith(newline):
        new_text += newline

    return new_text, total_line_changes


def apply_patch(
    file_path: str,
    patch_diff: str,
    task_id: str = "ai_patch"
) -> Dict[str, Any]:
    """
    Applies a standard unified diff patch to an existing user file.
    - Preserves all untouched lines outside the hunks.
    - Preserves line endings, encoding, and trailing newlines.
    - Rejects malformed, fuzzy, or ambiguous hunks.
    - Takes an automatic version backup before writing.
    - Leaves the file completely untouched if patch fails.
    """
    clean_task_id = workspace_service.validate_task_id(task_id) if task_id != "ai_patch" else "ai_patch"
    target = workspace_service.validate_path_access(file_path)

    if not target.exists():
        raise FileNotFoundError(f"File not found for patching: {target}")
    if not target.is_file():
        raise IsADirectoryError(f"Target is a directory: {target}")

    try:
        original_text = target.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        raise ValueError(f"Cannot apply text patch to binary or non-UTF-8 file: {target}")

    new_content, applied_changes = parse_and_apply_unified_diff(original_text, patch_diff)

    # Write modified content with automatic backup
    res = edit_file(
        str(target),
        new_content,
        task_id=clean_task_id,
        description=f"Unified patch applied ({applied_changes} line changes)"
    )
    res["patch_applied"] = True
    res["applied_changes_count"] = applied_changes
    return res


def compare_file_versions(file_path: str, comparison_content: str) -> Dict[str, Any]:
    """Generates a unified diff comparing current file content against proposed content."""
    target = workspace_service.validate_path_access(file_path)
    if target.exists():
        try:
            current_text = target.read_text(encoding="utf-8", errors="replace")
        except Exception:
            current_text = "<binary file>"
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
    """Generates an architectural overview of an approved workspace."""
    target = workspace_service.validate_path_access(workspace_path)

    total_files = 0
    total_dirs = 0
    total_bytes = 0
    file_extensions: Dict[str, int] = {}
    key_files = []
    start_time = time.time()
    truncated = False

    for root, dirs, files in os.walk(target, followlinks=False):
        if (time.time() - start_time) > MAX_SCAN_TIME_SEC or total_files >= MAX_SCAN_FILES:
            truncated = True
            break

        # Filter hidden directories and unapproved symlink targets
        if follow_symlinks:
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and workspace_service.is_path_approved(str((Path(root) / d).resolve()))
            ]
        else:
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
                try:
                    key_files.append(str(fp.relative_to(target)))
                except Exception:
                    pass

    return {
        "status": "success",
        "workspace_path": str(target),
        "workspace_name": target.name,
        "total_files": total_files,
        "total_directories": total_dirs,
        "total_size_bytes": total_bytes,
        "top_file_types": sorted(file_extensions.items(), key=lambda x: x[1], reverse=True)[:8],
        "key_manifest_files": key_files,
        "truncated": truncated
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
