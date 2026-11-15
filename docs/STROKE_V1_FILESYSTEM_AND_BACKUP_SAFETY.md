# STROKE V1 — Filesystem & Backup Safety Specification

## 1. Overview
Stroke operates directly on actual user project files without elevated privileges. To protect user data from corruption, data loss, symlink escapes, path traversal, race conditions, and accidental overwrites, Stroke enforces a multi-layered filesystem, workspace confinement, and backup safety architecture.

---

## 2. Workspace Boundaries & Security

### 2.1 Explicit User Approval
- **No Automatic Approval**: Removed all automatic approvals of `Path.cwd()` and broad user home directory paths. Workspaces start as an empty list and require explicit user consent via `add_approved_workspace()` or the native folder picker (`pick_native_folder()`).
- **System Roots & Broad Home Rejection**:
  - Rejects POSIX system directories: `/`, `/bin`, `/sbin`, `/usr`, `/etc`, `/var`, `/tmp`, `/dev`, `/proc`, `/sys`, `/System`, `/Library`, `/Applications`, `/private`, `/private/etc`, `/private/var`, `/private/tmp`.
  - Rejects Windows drive roots (e.g. `C:\`, `D:\`) and Windows system directories (`C:\Windows`, `C:\Program Files`, `C:\Program Files (x86)`).
  - Rejects registering the user home directory root itself (e.g. `~` / `/Users/username` / `C:\Users\username`) as an entire workspace; users must select specific project subfolders.

### 2.2 Canonical Path & Symlink Traversal Protection
- All paths are validated at the **point of access** using [`workspace_service.validate_path_access(target_path)`](file:///Users/ayansh/Desktop/stroke/workspace_service.py).
- Resolves canonical real paths (`os.path.realpath` / `Path.resolve()`).
- **Symlink Escapes**: If a file in an approved workspace is a symlink, the target of the symlink is inspected. If the symlink resolves to a destination outside approved workspaces, access is strictly denied (`WorkspaceSecurityError`).
- **Symlink Loops & Path Traversal**: Circular symlinks and path traversals (`..`) are blocked.

### 2.3 Strict Task ID Validation
- Task IDs are validated using strict alphanumeric format: `^[a-zA-Z0-9_\-]{1,64}$`.
- Untrusted task IDs containing `..`, slashes, backslashes, null bytes, or special characters are rejected before any path joining.

---

## 3. Real Unified-Diff Patch Engine & File Service

### 3.1 Real Unified-Diff Parser (`apply_patch`)
- Uses [`file_service.parse_and_apply_unified_diff`](file:///Users/ayansh/Desktop/stroke/file_service.py):
  - Parses hunk headers (`@@ -orig_start,orig_count +new_start,new_count @@`).
  - **Preserves Untouched Lines**: Proved that all untouched lines before, between, and after hunks survive completely intact.
  - **Preserves Formatting**: Detects and preserves line endings (`\r\n` vs. `\n`), encoding, and final trailing newline status.
  - **Rejects Malformed & Fuzzy Hunks**: Context mismatches, deletion mismatches, overlapping hunks, and missing headers are rejected (`PatchApplicationError`).
  - **Rollback Guarantee**: If any hunk fails to match cleanly, the patch aborts and the original file remains completely untouched.

### 3.2 Incremental Streaming Line-Range Reads
- [`file_service.read_file`](file:///Users/ayansh/Desktop/stroke/file_service.py) streams large files line-by-line without loading entire multi-megabyte/gigabyte files into memory.
- Enforces `max_bytes` returned and bounds checks.
- If an oversized file is read without range bounds, it is rejected with actionable error guidance.

### 3.3 Accurate Batch Status Reporting
- [`file_service.read_multiple_files`](file:///Users/ayansh/Desktop/stroke/file_service.py) accurately reports top-level status:
  - `"error"` when all requested files fail (never falsely reports `"success"`).
  - `"partial_success"` when some files succeed and some fail.
  - `"success"` when all files succeed.

### 3.4 File Classification & Scans
- **Binary Distinction**: Files with null bytes are classified as `"is_binary": True`, avoiding mangled text decoding.
- **Invalid UTF-8**: Non-UTF-8 text files report clear `error_type="invalid_utf8"` errors instead of silent string replacement.
- **Scan Limits**: `list_directory`, `search_files`, and `search_in_files` enforce a 10-second timeout, 50 MB byte limit, 5,000 file limit, and do **not** follow directory symlinks by default (`follow_symlinks=False`).

---

## 4. Version Backups & Recovery Service

### 4.1 Corrupted Index Recovery
- [`backup_service.BackupIndexManager`](file:///Users/ayansh/Desktop/stroke/backup_service.py): If `backups_index.json` is corrupted or malformed, the corrupted file is immediately preserved as `backups_index.json.corrupt.<timestamp>` for forensic analysis, rather than being silently treated as empty and overwritten.

### 4.2 Concurrency & Exclusive Unique Temp Files
- Serialized with `_BACKUP_LOCK = threading.RLock()`.
- Atomic writes use exclusively created unique temporary files (`tempfile.mkstemp` with `os.fsync` and `os.replace`).

### 4.3 Pre-Restore SHA-256 Verification & Path Validation
- In [`backup_service.restore_backup`](file:///Users/ayansh/Desktop/stroke/backup_service.py):
  1. Validates that the backup archive source path resides strictly within the trusted backup directory (`paths_service.get_backups_dir()`).
  2. Validates that the restore destination resides strictly within an approved user workspace.
  3. **Verifies backup SHA-256 BEFORE restoration**: If the backup archive was tampered with or corrupted on disk, restoration aborts before the destination is touched.
  4. Automatically generates a pre-restore safety backup of the destination file.
  5. If writing the restored file fails, the original destination file remains completely untouched.

### 4.4 Byte-Level Binary Comparison
- [`backup_service.compare_backup_to_current`](file:///Users/ayansh/Desktop/stroke/backup_service.py) compares binary files byte-for-byte; never relies on placeholder strings (`"<binary file>"`).

---

## 5. Isolated Task Workspace & Sandbox Containment

### 5.1 Sandboxing & Symlink Containment
- In [`isolated_workspace.TaskWorkspaceSandbox`](file:///Users/ayansh/Desktop/stroke/isolated_workspace.py):
  - Sandboxes are isolated within `paths_service.get_app_data_dir() / "IsolatedTasks"`.
  - **Symlink Containment**: When copying project files into the sandbox, symlinks that point outside the project directory are omitted to prevent the sandbox process from reaching files outside the project.

### 5.2 Source Hash Conflict Detection
- Before `apply_task_changes()` writes modified files back to the user project:
  - Verifies that original files on disk still match their initial snapshot SHA-256 hashes.
  - If the user modified an original file while the background task was executing, the reconciliation **stops and raises `WorkspaceConflictError`**, preventing the AI from clobbering intervening user edits.

### 5.3 Byte-Exact Writing & No-Delete Enforcement
- Writes modified and new files using raw bytes (`read_bytes()`), preserving binary assets, exact line endings, and encodings.
- Any change set containing deletions raises `DestructiveChangeSetError` and is strictly rejected.

---

## 6. Verification & Test Gate

Test Suite: [`test_filesystem_and_backup_safety.py`](file:///Users/ayansh/Desktop/stroke/test_filesystem_and_backup_safety.py) (16 tests, 100% passing):
- `test_01_partial_unified_diff_preserves_every_untouched_line`
- `test_02_multiple_hunks_with_intermediate_untouched_lines`
- `test_03_malformed_and_overlapping_patches_rejected_and_rolled_back`
- `test_04_task_id_strict_validation_and_traversal_blocking`
- `test_05_symlink_escapes_and_sandbox_containment`
- `test_06_symlink_loops_and_path_traversal_denied`
- `test_07_system_roots_and_broad_home_directory_rejected`
- `test_08_no_automatic_cwd_or_home_approval`
- `test_09_incremental_line_range_streaming_on_large_files`
- `test_10_distinguish_binary_files_and_invalid_utf8`
- `test_11_read_multiple_files_batch_status_accuracy`
- `test_12_corrupted_backup_index_preserved_for_recovery`
- `test_13_concurrent_backup_writes_thread_safety`
- `test_14_checksum_tampering_and_invalid_restore_paths_rejected`
- `test_15_source_hash_conflict_detection_in_task_sandbox`
- `test_16_absolute_no_delete_policy_enforcement`
