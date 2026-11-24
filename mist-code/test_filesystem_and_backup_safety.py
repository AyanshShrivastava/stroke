"""
================================================================================
STROKE // FILESYSTEM AND BACKUP SAFETY TEST SUITE
================================================================================
Verification Gate:
  1. Partial unified diff regression: prove every untouched line survives.
  2. Multi-hunk diffs: prove intermediate untouched lines survive.
  3. Malformed, fuzzy, and overlapping patches rejected with rollback.
  4. Task ID strict validation: traversal IDs ('../../etc', slashes) rejected.
  5. Symlink escapes: accessing escaping symlinks rejected; sandboxes omit them.
  6. Symlink loops: circular symlinks detected without crashing/looping.
  7. System roots and broad home directory rejected as workspaces.
  8. No automatic approval: cwd and home not automatically approved.
  9. Incremental streaming line-range reads on large files.
  10. Distinguish binary files and invalid UTF-8 without silent data corruption.
  11. Batch read_multiple_files status accuracy (error on all-failed).
  12. Corrupted backup index preserved for forensic recovery, never silently lost.
  13. Concurrent backup operations serialized safely without race conditions.
  14. Checksum tampering and invalid restore paths strictly rejected before restore.
  15. Source hash conflict detection in isolated workspace sandboxes.
  16. Absolute No-Delete policy strictly enforced across all operations.
================================================================================
"""

import os
import json
import shutil
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import paths_service
import workspace_service
from workspace_service import WorkspaceSecurityError, WorkspaceManager
import backup_service
import file_service
from file_service import NoDeletePolicyViolation, PatchApplicationError
import isolated_workspace
from isolated_workspace import TaskWorkspaceSandbox, DestructiveChangeSetError, WorkspaceConflictError


class TestFilesystemAndBackupSafety(unittest.TestCase):

    def setUp(self):
        self.test_root = tempfile.mkdtemp(prefix="stroke_safety_test_")
        self.user_app_data = Path(self.test_root) / "AppData"
        self.user_app_data.mkdir(parents=True, exist_ok=True)

        self.workspace_dir = Path(self.test_root) / "project_alpha"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

        # Patch paths_service to test isolation
        self.patcher_app_data = mock.patch(
            "paths_service.get_app_data_dir",
            return_value=self.user_app_data
        )
        self.patcher_app_data.start()

        # Update service singletons to test config
        workspace_service._WORKSPACE_MANAGER = WorkspaceManager()
        backup_service._INDEX_MANAGER = backup_service.BackupIndexManager()
        isolated_workspace._TASK_SANDBOX = TaskWorkspaceSandbox()

        # Explicitly approve only project_alpha
        workspace_service.approve_workspace(str(self.workspace_dir), label="Alpha Project")

    def tearDown(self):
        self.patcher_app_data.stop()
        if os.path.exists(self.test_root):
            shutil.rmtree(self.test_root, ignore_errors=True)

    # --------------------------------------------------------------------------
    # 1. PARTIAL UNIFIED DIFF REGRESSION: EVERY UNTOUCHED LINE SURVIVES
    # --------------------------------------------------------------------------
    def test_01_partial_unified_diff_preserves_every_untouched_line(self):
        target_file = self.workspace_dir / "module.py"
        # Generate 100 lines with varying content
        lines = [f"line_{i:03d} = 'value_{i}' # Context {i}" for i in range(1, 101)]
        original_content = "\n".join(lines) + "\n"
        target_file.write_text(original_content, encoding="utf-8")

        # Unified diff modifying only lines 45-47 (with 3 lines of context before and after)
        diff_patch = (
            "--- a/module.py\n"
            "+++ b/module.py\n"
            "@@ -42,8 +42,9 @@\n"
            " line_042 = 'value_42' # Context 42\n"
            " line_043 = 'value_43' # Context 43\n"
            " line_044 = 'value_44' # Context 44\n"
            "-line_045 = 'value_45' # Context 45\n"
            "-line_046 = 'value_46' # Context 46\n"
            "+line_045 = 'REPLACED_45' # Modified\n"
            "+line_046 = 'REPLACED_46' # Modified\n"
            "+line_046_extra = 'NEW_LINE' # Added\n"
            " line_047 = 'value_47' # Context 47\n"
            " line_048 = 'value_48' # Context 48\n"
            " line_049 = 'value_49' # Context 49\n"
        )

        res = file_service.apply_patch(str(target_file), diff_patch, task_id="test_diff_1")
        self.assertTrue(res["patch_applied"])

        new_content = target_file.read_text(encoding="utf-8")
        new_lines = new_content.splitlines()

        # 1. Prove every single line from 1 to 44 survived untouched
        for i in range(1, 45):
            expected = f"line_{i:03d} = 'value_{i}' # Context {i}"
            self.assertEqual(new_lines[i - 1], expected, f"Line {i} was corrupted or dropped!")

        # 2. Prove lines 45-47 were correctly patched
        self.assertEqual(new_lines[44], "line_045 = 'REPLACED_45' # Modified")
        self.assertEqual(new_lines[45], "line_046 = 'REPLACED_46' # Modified")
        self.assertEqual(new_lines[46], "line_046_extra = 'NEW_LINE' # Added")

        # 3. Prove every single line from 47 to 100 survived untouched
        # Note: 1 line was added so new indices are shifted by +1
        for i in range(47, 101):
            expected = f"line_{i:03d} = 'value_{i}' # Context {i}"
            self.assertEqual(new_lines[i], expected, f"Line {i} was corrupted or dropped!")

        # 4. Prove total lines is exactly 101 (100 - 2 + 3)
        self.assertEqual(len(new_lines), 101)

    # --------------------------------------------------------------------------
    # 2. MULTI-HUNK DIFFS: INTERMEDIATE UNTOUCHED LINES SURVIVE
    # --------------------------------------------------------------------------
    def test_02_multiple_hunks_with_intermediate_untouched_lines(self):
        target_file = self.workspace_dir / "multi_hunk.txt"
        lines = [f"Record {i}" for i in range(1, 61)]
        target_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        # Patch with two separate hunks: at line 10 and line 50
        diff_patch = (
            "--- a/multi_hunk.txt\n"
            "+++ b/multi_hunk.txt\n"
            "@@ -8,5 +8,5 @@\n"
            " Record 8\n"
            " Record 9\n"
            "-Record 10\n"
            "+Record 10 (Hunk 1 Modified)\n"
            " Record 11\n"
            " Record 12\n"
            "@@ -48,5 +48,5 @@\n"
            " Record 48\n"
            " Record 49\n"
            "-Record 50\n"
            "+Record 50 (Hunk 2 Modified)\n"
            " Record 51\n"
            " Record 52\n"
        )

        res = file_service.apply_patch(str(target_file), diff_patch, task_id="test_multi_hunk")
        self.assertTrue(res["patch_applied"])

        new_lines = target_file.read_text(encoding="utf-8").splitlines()
        # Verify hunk 1 modification
        self.assertEqual(new_lines[9], "Record 10 (Hunk 1 Modified)")
        # Verify intermediate lines (Record 13 to Record 47) survived completely
        for i in range(13, 48):
            self.assertEqual(new_lines[i - 1], f"Record {i}")
        # Verify hunk 2 modification
        self.assertEqual(new_lines[49], "Record 50 (Hunk 2 Modified)")
        # Verify post-hunk lines survived
        self.assertEqual(new_lines[59], "Record 60")

    # --------------------------------------------------------------------------
    # 3. MALFORMED, FUZZY, AND OVERLAPPING PATCHES REJECTED WITH ROLLBACK
    # --------------------------------------------------------------------------
    def test_03_malformed_and_overlapping_patches_rejected_and_rolled_back(self):
        target_file = self.workspace_dir / "guarded.py"
        original_content = "def calculate():\n    return 42\n"
        target_file.write_text(original_content, encoding="utf-8")
        orig_hash = backup_service.compute_file_sha256(target_file)

        # Case A: Context mismatch (fuzzy / hallucinated context)
        fuzzy_patch = (
            "--- a/guarded.py\n"
            "+++ b/guarded.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def non_matching_context():\n"
            "-    return 42\n"
            "+    return 999\n"
        )
        with self.assertRaises(PatchApplicationError):
            file_service.apply_patch(str(target_file), fuzzy_patch)
        self.assertEqual(target_file.read_text(encoding="utf-8"), original_content)
        self.assertEqual(backup_service.compute_file_sha256(target_file), orig_hash)

        # Case B: Malformed patch (no hunk headers)
        malformed_patch = "Just some text without hunk headers\n+new line"
        with self.assertRaises(PatchApplicationError):
            file_service.apply_patch(str(target_file), malformed_patch)
        self.assertEqual(target_file.read_text(encoding="utf-8"), original_content)

        # Case C: Overlapping hunks
        overlapping_patch = (
            "--- a/guarded.py\n"
            "+++ b/guarded.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def calculate():\n"
            "-    return 42\n"
            "+    return 100\n"
            "@@ -1,2 +1,2 @@\n"
            " def calculate():\n"
            "-    return 42\n"
            "+    return 200\n"
        )
        with self.assertRaises(PatchApplicationError):
            file_service.apply_patch(str(target_file), overlapping_patch)
        self.assertEqual(target_file.read_text(encoding="utf-8"), original_content)

    # --------------------------------------------------------------------------
    # 4. TASK ID STRICT VALIDATION AND TRAVERSAL BLOCKING
    # --------------------------------------------------------------------------
    def test_04_task_id_strict_validation_and_traversal_blocking(self):
        malicious_ids = [
            "../../etc",
            "../escape",
            "task/subtask",
            "task\\windows_escape",
            "",
            "   ",
            "task\x00nullbyte",
            "..",
            ".",
            "task@special#chars$",
            "a" * 65  # exceeds 64 chars
        ]

        for bad_id in malicious_ids:
            with self.assertRaises((WorkspaceSecurityError, ValueError)):
                workspace_service.validate_task_id(bad_id)

            with self.assertRaises((WorkspaceSecurityError, ValueError)):
                isolated_workspace.create_task_workspace(str(self.workspace_dir), bad_id)

        # Valid task IDs must pass
        valid_ids = ["task_001", "TASK-894", "ai-edit_2026", "a", "123_abc-XYZ"]
        for good_id in valid_ids:
            self.assertEqual(workspace_service.validate_task_id(good_id), good_id)

    # --------------------------------------------------------------------------
    # 5. SYMLINK ESCAPES AND SANDBOX CONTAINMENT
    # --------------------------------------------------------------------------
    def test_05_symlink_escapes_and_sandbox_containment(self):
        # 1. Create a private file outside approved workspaces
        external_dir = Path(self.test_root) / "unapproved_secrets"
        external_dir.mkdir(parents=True, exist_ok=True)
        secret_file = external_dir / "secret.env"
        secret_file.write_text("API_KEY=top_secret_12345", encoding="utf-8")

        # 2. Inside the approved workspace, create a symlink pointing to the external file
        symlink_in_ws = self.workspace_dir / "escape_symlink.env"
        try:
            os.symlink(secret_file, symlink_in_ws)
        except OSError:
            self.skipTest("Symlinks not supported on this platform/privilege level")

        # 3. Direct access through file_service must be DENIED
        with self.assertRaises(WorkspaceSecurityError):
            file_service.validate_path_access(str(symlink_in_ws))

        with self.assertRaises(WorkspaceSecurityError):
            file_service.read_file(str(symlink_in_ws))

        # 4. In TaskWorkspaceSandbox: verify escaping symlink is NOT preserved in sandbox
        sandbox_res = isolated_workspace.create_task_workspace(str(self.workspace_dir), "symlink_test_task")
        sandbox_path = Path(sandbox_res["isolated_workspace"])
        sandbox_symlink = sandbox_path / "escape_symlink.env"

        # The escaping symlink must NOT exist as a functional symlink pointing outside!
        if sandbox_symlink.exists():
            resolved = sandbox_symlink.resolve()
            self.assertFalse(
                str(resolved).startswith(str(external_dir)),
                "Escaping symlink was preserved in isolated sandbox!"
            )

    # --------------------------------------------------------------------------
    # 6. SYMLINK LOOPS AND PATH TRAVERSAL DENIED
    # --------------------------------------------------------------------------
    def test_06_symlink_loops_and_path_traversal_denied(self):
        loop_link_a = self.workspace_dir / "loop_a"
        loop_link_b = self.workspace_dir / "loop_b"
        try:
            os.symlink(loop_link_b, loop_link_a)
            os.symlink(loop_link_a, loop_link_b)
        except OSError:
            self.skipTest("Symlinks not supported")

        with self.assertRaises(WorkspaceSecurityError):
            file_service.validate_path_access(str(loop_link_a))

        # Dot-dot traversal outside workspace
        outside_path = str(self.workspace_dir / ".." / ".." / "etc" / "passwd")
        with self.assertRaises(WorkspaceSecurityError):
            file_service.validate_path_access(outside_path)

    # --------------------------------------------------------------------------
    # 7. SYSTEM ROOTS AND BROAD HOME DIRECTORY REJECTED AS WORKSPACES
    # --------------------------------------------------------------------------
    def test_07_system_roots_and_broad_home_directory_rejected(self):
        disallowed = ["/", "/etc", "/bin", "/System", "/var"]
        for root in disallowed:
            if os.path.exists(root):
                with self.assertRaises(WorkspaceSecurityError):
                    workspace_service.approve_workspace(root)

        # Home directory root
        home = str(Path.home().resolve())
        with self.assertRaises(WorkspaceSecurityError):
            workspace_service.approve_workspace(home)

    # --------------------------------------------------------------------------
    # 8. NO AUTOMATIC CWD OR HOME APPROVAL
    # --------------------------------------------------------------------------
    def test_08_no_automatic_cwd_or_home_approval(self):
        # Create fresh isolated workspace manager
        empty_config = Path(self.test_root) / "empty_workspaces.json"
        with mock.patch("paths_service.get_workspaces_config_path", return_value=empty_config):
            mgr = WorkspaceManager()
            workspaces = mgr.get_approved_workspaces()
            self.assertEqual(workspaces, [], "Initial workspaces must be empty list; never cwd or home")

            # Path.cwd() must NOT be automatically approved
            self.assertFalse(mgr.is_path_approved(str(Path.cwd().resolve())))

    # --------------------------------------------------------------------------
    # 9. INCREMENTAL LINE-RANGE STREAMING ON LARGE FILES
    # --------------------------------------------------------------------------
    def test_09_incremental_line_range_streaming_on_large_files(self):
        big_file = self.workspace_dir / "large_dataset.txt"
        with open(big_file, "w", encoding="utf-8") as f:
            for i in range(1, 5001):
                f.write(f"Line number {i} with padding data for testing\n")

        # Range read: lines 200 to 205
        res = file_service.read_file(str(big_file), start_line=200, end_line=205, max_bytes=10000)
        self.assertEqual(res["status"], "success")
        self.assertTrue(res["is_sliced"])
        self.assertEqual(res["start_line"], 200)
        self.assertEqual(res["end_line"], 205)
        lines = res["content"].splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[0], "Line number 200 with padding data for testing")
        self.assertEqual(lines[-1], "Line number 205 with padding data for testing")

        # Full read without slicing on file exceeding limit raises ValueError
        with self.assertRaises(ValueError):
            file_service.read_file(str(big_file), max_bytes=500)

    # --------------------------------------------------------------------------
    # 10. DISTINGUISH BINARY FILES AND INVALID UTF-8
    # --------------------------------------------------------------------------
    def test_10_distinguish_binary_files_and_invalid_utf8(self):
        # Binary file
        binary_file = self.workspace_dir / "binary_asset.bin"
        raw_binary = b"\x00\x01\x02\x03\xFF\xFE\x00\x00PNG_DATA"
        binary_file.write_bytes(raw_binary)

        res_bin = file_service.read_file(str(binary_file))
        self.assertTrue(res_bin["is_binary"])
        self.assertIsNone(res_bin["content"])

        # Invalid UTF-8 file
        bad_utf8 = self.workspace_dir / "invalid_utf8.txt"
        bad_utf8.write_bytes(b"Good start\x80\x81not valid utf8")

        res_utf8 = file_service.read_file(str(bad_utf8))
        self.assertEqual(res_utf8["status"], "error")
        self.assertEqual(res_utf8["error_type"], "invalid_utf8")

        # Binary comparison in backup_service
        bk_info = backup_service.create_file_backup(str(binary_file), task_id="bin_test")
        comp = backup_service.compare_backup_to_current(bk_info["backup_id"])
        self.assertTrue(comp["is_binary"])
        self.assertTrue(comp["is_identical"])

        # Tamper binary file
        binary_file.write_bytes(b"\x00\x01\x02\x03DIFFERENT_DATA")
        comp2 = backup_service.compare_backup_to_current(bk_info["backup_id"])
        self.assertFalse(comp2["is_identical"])

    # --------------------------------------------------------------------------
    # 11. BATCH READ_MULTIPLE_FILES STATUS ACCURACY
    # --------------------------------------------------------------------------
    def test_11_read_multiple_files_batch_status_accuracy(self):
        good1 = self.workspace_dir / "good1.txt"
        good1.write_text("content 1", encoding="utf-8")
        good2 = self.workspace_dir / "good2.txt"
        good2.write_text("content 2", encoding="utf-8")

        # All succeeded -> 'success'
        res_all_good = file_service.read_multiple_files([str(good1), str(good2)])
        self.assertEqual(res_all_good["status"], "success")
        self.assertEqual(res_all_good["successful_count"], 2)
        self.assertEqual(res_all_good["failed_count"], 0)

        # Partial -> 'partial_success'
        res_partial = file_service.read_multiple_files([str(good1), str(self.workspace_dir / "nonexistent.txt")])
        self.assertEqual(res_partial["status"], "partial_success")
        self.assertEqual(res_partial["successful_count"], 1)
        self.assertEqual(res_partial["failed_count"], 1)

        # All failed -> 'error' (NOT success!)
        res_all_failed = file_service.read_multiple_files([
            str(self.workspace_dir / "nonexistent1.txt"),
            str(self.workspace_dir / "nonexistent2.txt")
        ])
        self.assertEqual(res_all_failed["status"], "error")
        self.assertEqual(res_all_failed["successful_count"], 0)
        self.assertEqual(res_all_failed["failed_count"], 2)

    # --------------------------------------------------------------------------
    # 12. CORRUPTED BACKUP INDEX PRESERVED FOR RECOVERY
    # --------------------------------------------------------------------------
    def test_12_corrupted_backup_index_preserved_for_recovery(self):
        index_file = paths_service.get_backups_dir() / "backups_index.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)
        corrupted_content = "{'bad_json': true, [truncated"
        index_file.write_text(corrupted_content, encoding="utf-8")

        mgr = backup_service.BackupIndexManager()
        # Reading corrupted index should preserve the corrupted file
        entries = mgr._read_index()
        self.assertEqual(entries, [])

        # Verify a .corrupt. file was created in the backups directory
        corrupt_files = list(paths_service.get_backups_dir().glob("backups_index.json.corrupt.*"))
        self.assertTrue(len(corrupt_files) > 0, "Corrupted index must be preserved for forensic recovery!")
        self.assertEqual(corrupt_files[0].read_text(encoding="utf-8"), corrupted_content)

    # --------------------------------------------------------------------------
    # 13. CONCURRENT BACKUP WRITES THREAD SAFETY
    # --------------------------------------------------------------------------
    def test_13_concurrent_backup_writes_thread_safety(self):
        test_file = self.workspace_dir / "concurrent_test.txt"
        test_file.write_text("initial version", encoding="utf-8")

        def worker(thread_idx):
            backup_service.create_file_backup(
                str(test_file),
                task_id=f"thread_{thread_idx}",
                description=f"Concurrent backup from thread {thread_idx}"
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        backups = backup_service.list_backups(str(test_file))
        self.assertEqual(len(backups), 8, "All 8 concurrent backups must be recorded in the index")

    # --------------------------------------------------------------------------
    # 14. CHECKSUM TAMPERING AND INVALID RESTORE PATHS REJECTED
    # --------------------------------------------------------------------------
    def test_14_checksum_tampering_and_invalid_restore_paths_rejected(self):
        target = self.workspace_dir / "tamper_test.txt"
        target.write_text("original clean content", encoding="utf-8")
        orig_hash = backup_service.compute_file_sha256(target)

        bk = backup_service.create_file_backup(str(target), task_id="tamper_task")
        bk_path = Path(bk["backup_path"])

        # Tamper with the backup file on disk
        bk_path.write_text("MALICIOUS INJECTED CONTENT", encoding="utf-8")

        # Restore MUST FAIL before writing anything
        with self.assertRaises(ValueError):
            backup_service.restore_backup(bk["backup_id"])

        # Verify target file on disk was LEFT UNTOUCHED
        self.assertEqual(target.read_text(encoding="utf-8"), "original clean content")
        self.assertEqual(backup_service.compute_file_sha256(target), orig_hash)

    # --------------------------------------------------------------------------
    # 15. SOURCE HASH CONFLICT DETECTION IN TASK SANDBOX
    # --------------------------------------------------------------------------
    def test_15_source_hash_conflict_detection_in_task_sandbox(self):
        source_file = self.workspace_dir / "concurrent_code.py"
        source_file.write_text("def hello(): return 'world'\n", encoding="utf-8")

        sandbox = TaskWorkspaceSandbox(str(self.workspace_dir))
        task_id = "conflict_task_01"
        res = sandbox.create_task_workspace(str(self.workspace_dir), task_id)
        sandbox_dir = Path(res["isolated_workspace"])

        # AI modifies file in the sandbox
        sandbox_file = sandbox_dir / "concurrent_code.py"
        sandbox_file.write_text("def hello(): return 'ai_modified'\n", encoding="utf-8")

        # User modifies original file outside the task while it was running!
        source_file.write_text("def hello(): return 'user_modified_meanwhile'\n", encoding="utf-8")

        # Applying task changes must detect conflict and REJECT
        with self.assertRaises(WorkspaceConflictError):
            sandbox.apply_task_changes(task_id)

        # Verify user modification was NOT clobbered!
        self.assertEqual(source_file.read_text(encoding="utf-8"), "def hello(): return 'user_modified_meanwhile'\n")

    # --------------------------------------------------------------------------
    # 16. ABSOLUTE NO-DELETE POLICY ENFORCEMENT
    # --------------------------------------------------------------------------
    def test_16_absolute_no_delete_policy_enforcement(self):
        with self.assertRaises(NoDeletePolicyViolation):
            file_service.delete_file("/path/to/file")

        with self.assertRaises(NoDeletePolicyViolation):
            file_service.remove_directory("/path/to/dir")

        # Deletion in isolated workspace change set
        target = self.workspace_dir / "to_delete.txt"
        target.write_text("content", encoding="utf-8")

        sandbox = TaskWorkspaceSandbox(str(self.workspace_dir))
        task_id = "delete_attempt_task"
        res = sandbox.create_task_workspace(str(self.workspace_dir), task_id)
        sandbox_dir = Path(res["isolated_workspace"])

        # Delete file in sandbox
        (sandbox_dir / "to_delete.txt").unlink()

        with self.assertRaises(DestructiveChangeSetError):
            sandbox.apply_task_changes(task_id)

        # Original file must survive intact
        self.assertTrue(target.exists())


if __name__ == "__main__":
    unittest.main()
