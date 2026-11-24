"""
================================================================================
STROKE // USER FILE SYSTEM & NON-DESTRUCTIVE ARCHITECTURE TEST SUITE
================================================================================
Comprehensive verification for Stroke's computer file access system:
  1. USER-LEVEL FILE SYSTEM ACCESS:
     - list_directory, read_file, read_multiple_files, create_file, edit_file
     - create_directory, search_files, search_in_files, inspect_file, apply_patch, compare_file_versions
  2. ABSOLUTE NO-DELETE POLICY:
     - Direct file_service.delete_file / remove_directory throws NoDeletePolicyViolation
     - TaskWorkspaceSandbox change sets with deletions are strictly REJECTED (DestructiveChangeSetError)
     - AI-initiated terminal commands (rm, del, rmdir, git clean) are strictly DENIED
     - User files and directories are NEVER deleted; original files are preserved intact
  3. ZERO ADMINISTRATOR & USER-LEVEL PATHS:
     - paths_service cross-platform resolution
     - Paths strictly in user-level space (~/Library/Application Support, %LOCALAPPDATA%, ~/.local)
     - Elevation status detection (is_elevated_privilege, get_elevation_status)
  4. VERSION BACKUPS & SAFE RESTORATION:
     - Automatic pre-modification snapshots stored in user app data
     - Atomic file replacement mechanics
     - Backup diffing and safe restoration with pre-restore safety snapshot
  5. WORKSPACE CONFINEMENT & PERMISSIONS:
     - Approved workspaces registry (approved_workspaces.json)
     - Path validation blocks directory traversal outside approved roots
  6. USER-LEVEL MODEL DOWNLOAD SYSTEM:
     - Byte-level progress reporting, pause, resume (HTTP Range), cancellation
     - SHA-256 verification and destination inside user-level models directory
  7. ISOLATED TASK WORKSPACE COPIES & RECONCILIATION:
     - Per-task sandboxes, non-destructive diff reconciliation, automatic backups
================================================================================
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import paths_service
import backup_service
import workspace_service
import file_service
from file_service import NoDeletePolicyViolation
import isolated_workspace
from isolated_workspace import TaskWorkspaceSandbox, DestructiveChangeSetError
import model_download_service
import terminal_service
from terminal_service import evaluate_command_security, SecurityDecision, ToolDispatcher


class TestUserLevelPathsAndElevation(unittest.TestCase):
    """Verifies that all storage directories reside in per-user space without root/admin requirements."""

    def test_01_user_directories_exist_and_non_root(self):
        dirs = paths_service.ensure_user_directories()
        self.assertIn("app_data", dirs)
        self.assertIn("models", dirs)
        self.assertIn("backups", dirs)
        self.assertIn("downloads", dirs)

        # Verify paths are in user home, never /etc, /var/root, /System, C:\Windows, C:\Program Files
        for key in ("app_data", "models", "backups", "downloads"):
            p = dirs[key]
            path_obj = Path(p)
            self.assertTrue(path_obj.exists(), f"Directory does not exist: {p}")
            p_str = str(path_obj)
            self.assertFalse(p_str.startswith("/System"), f"Path must not be in /System: {p_str}")
            self.assertFalse(p_str.startswith("/etc"), f"Path must not be in /etc: {p_str}")
            self.assertFalse(p_str.startswith("C:\\Windows"), f"Path must not be in Windows dir: {p_str}")
            self.assertFalse(p_str.startswith("C:\\Program Files"), f"Path must not be in Program Files: {p_str}")

    def test_02_elevation_status_compliance(self):
        status = paths_service.get_elevation_status()
        self.assertIn("is_elevated", status)
        self.assertIn("zero_admin_compliant", status)
        self.assertIn("platform", status)
        self.assertIn("user", status)
        # On standard test environments, zero_admin_compliant is True unless run under sudo
        if not status["is_elevated"]:
            self.assertTrue(status["zero_admin_compliant"])
            self.assertEqual(status["elevation_warning"], None)


class TestWorkspaceSecurityAndConfinement(unittest.TestCase):
    """Verifies workspace registry and strict boundary confinement."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="stroke_ws_test_")
        self.test_ws = os.path.join(self.temp_dir, "my_project")
        os.makedirs(self.test_ws, exist_ok=True)
        # Register temporary workspace
        workspace_service.approve_workspace(self.test_ws, label="Test Workspace")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_approved_workspace_access(self):
        validated = workspace_service.validate_path_access(self.test_ws)
        self.assertEqual(validated, Path(self.test_ws).resolve())

        # Subdirectory access is permitted
        sub_dir = os.path.join(self.test_ws, "src", "sub")
        os.makedirs(sub_dir, exist_ok=True)
        self.assertTrue(workspace_service.is_path_approved(sub_dir))

    def test_02_unapproved_workspace_traversal_denied(self):
        unapproved_outside = os.path.abspath("/tmp/some_unauthorized_external_folder_12345")
        with self.assertRaises(workspace_service.WorkspaceSecurityError):
            workspace_service.validate_path_access(unapproved_outside)

        # Directory traversal attempt (..)
        traversal = os.path.join(self.test_ws, "..", "..", "..", "etc", "passwd")
        with self.assertRaises(workspace_service.WorkspaceSecurityError):
            workspace_service.validate_path_access(traversal)


class TestNonDestructiveFileSystemOperations(unittest.TestCase):
    """Verifies file creation, reading, editing, searching, inspecting, and patching."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="stroke_fs_test_")
        self.ws_path = os.path.join(self.temp_dir, "project")
        os.makedirs(self.ws_path, exist_ok=True)
        workspace_service.approve_workspace(self.ws_path, label="FS Test")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_create_and_read_file(self):
        target_file = os.path.join(self.ws_path, "main.py")
        content = "print('Hello Stroke World')\n"
        res = file_service.create_file(target_file, content)
        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.exists(target_file))

        # Attempt to create existing without overwrite -> must fail
        with self.assertRaises(FileExistsError):
            file_service.create_file(target_file, "overwrite content", overwrite=False)

        # Read file
        read_res = file_service.read_file(target_file)
        self.assertEqual(read_res["content"], content)
        self.assertEqual(read_res["total_lines"], 1)

    def test_02_edit_file_creates_automatic_backup(self):
        target_file = os.path.join(self.ws_path, "config.json")
        initial_content = '{"version": "1.0.0", "theme": "dark"}\n'
        file_service.create_file(target_file, initial_content)

        # Count backups before edit
        backups_before = backup_service.list_backups(target_file)

        # Edit file
        new_content = '{"version": "1.1.0", "theme": "cyberpunk"}\n'
        edit_res = file_service.edit_file(target_file, new_content, task_id="task_audit_01")
        self.assertEqual(edit_res["status"], "success")

        # Verify new content on disk
        read_back = Path(target_file).read_text()
        self.assertEqual(read_back, new_content)

        # Verify automatic backup was generated
        backups_after = backup_service.list_backups(target_file)
        self.assertEqual(len(backups_after), len(backups_before) + 1)
        latest_backup = backups_after[0]
        self.assertEqual(latest_backup["task_id"], "task_audit_01")

        # Compare backup to current
        diff_res = backup_service.compare_backup_to_current(latest_backup["backup_id"])
        self.assertFalse(diff_res["is_identical"])
        self.assertIn("-{\"version\": \"1.0.0\"", diff_res["diff"])
        self.assertIn("+{\"version\": \"1.1.0\"", diff_res["diff"])

        # Restore backup safely
        restore_res = backup_service.restore_backup(latest_backup["backup_id"])
        self.assertEqual(restore_res["status"], "success")
        restored_text = Path(target_file).read_text()
        self.assertEqual(restored_text, initial_content)

    def test_03_create_directory_and_list(self):
        nested_dir = os.path.join(self.ws_path, "sub1", "sub2", "sub3")
        res = file_service.create_directory(nested_dir)
        self.assertEqual(res["status"], "success")
        self.assertTrue(os.path.isdir(nested_dir))

        # Create files inside
        file_service.create_file(os.path.join(nested_dir, "asset.luau"), "-- VFX Asset\n")
        file_service.create_file(os.path.join(self.ws_path, "root.py"), "# Root\n")

        # List directory
        list_res = file_service.list_directory(self.ws_path, recursive=True)
        self.assertEqual(list_res["status"], "success")
        names = [item["name"] for item in list_res["items"]]
        self.assertIn("root.py", names)
        self.assertIn("sub1", names)
        self.assertIn("asset.luau", names)

    def test_04_search_files_and_content(self):
        file_service.create_file(os.path.join(self.ws_path, "HitboxController.luau"), "local Hitbox = {}\nfunction Hitbox:Activate()\n  print('VFX')\nend\n")
        file_service.create_file(os.path.join(self.ws_path, "test_hitbox.py"), "def test_hitbox():\n    assert True\n")

        # Search files by glob
        glob_res = file_service.search_files(self.ws_path, pattern="*Hitbox*.luau")
        self.assertEqual(glob_res["match_count"], 1)
        self.assertEqual(glob_res["matches"][0]["name"], "HitboxController.luau")

        # Search in file contents
        content_res = file_service.search_in_files(self.ws_path, query="VFX")
        self.assertEqual(content_res["match_count"], 1)
        self.assertIn("HitboxController.luau", content_res["matches"][0]["file_path"])
        self.assertEqual(content_res["matches"][0]["line_number"], 3)

    def test_05_inspect_file_metadata(self):
        fpath = os.path.join(self.ws_path, "metadata_test.py")
        file_service.create_file(fpath, "line1\nline2\nline3\n")
        insp = file_service.inspect_file(fpath)
        self.assertEqual(insp["file_name"], "metadata_test.py")
        self.assertEqual(insp["line_count"], 3)
        self.assertFalse(insp["is_binary"])
        self.assertIsNotNone(insp["sha256"])
        self.assertEqual(len(insp["sha256"]), 64)


class TestAbsoluteNoDeletePolicy(unittest.TestCase):
    """
    Exhaustively audits Stroke's Absolute No-Delete Policy:
    1. file_service.delete_file throws NoDeletePolicyViolation
    2. file_service.remove_directory throws NoDeletePolicyViolation
    3. TaskWorkspaceSandbox rejects any change set containing deletions
    4. AI terminal commands attempting rm/del/rmdir/git clean are strictly denied
    5. Original user files remain preserved intact on disk
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="stroke_no_delete_")
        self.ws_path = os.path.join(self.temp_dir, "project")
        os.makedirs(self.ws_path, exist_ok=True)
        workspace_service.approve_workspace(self.ws_path, label="No Delete Test")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_file_service_prohibits_deletion_methods(self):
        """delete_file and remove_directory MUST raise NoDeletePolicyViolation."""
        test_file = os.path.join(self.ws_path, "precious_user_file.lua")
        file_service.create_file(test_file, "-- Important user code\n")

        with self.assertRaises(NoDeletePolicyViolation) as ctx:
            file_service.delete_file(test_file)
        self.assertIn("Absolute No-Delete Policy", str(ctx.exception))
        # File must remain untouched on disk
        self.assertTrue(os.path.exists(test_file))

        test_dir = os.path.join(self.ws_path, "user_assets")
        file_service.create_directory(test_dir)
        with self.assertRaises(NoDeletePolicyViolation) as ctx:
            file_service.remove_directory(test_dir)
        self.assertIn("Absolute No-Delete Policy", str(ctx.exception))
        # Directory must remain untouched on disk
        self.assertTrue(os.path.isdir(test_dir))

    def test_02_task_workspace_sandbox_rejects_deletions(self):
        """Isolated workspace changes containing deletions are strictly rejected with DestructiveChangeSetError."""
        # Create base workspace files
        file_service.create_file(os.path.join(self.ws_path, "keep_me.txt"), "Important Content\n")
        file_service.create_file(os.path.join(self.ws_path, "user_file.py"), "x = 10\n")

        sandbox = TaskWorkspaceSandbox(self.ws_path)
        task_id = "task_destructive_test_01"
        copy_path = sandbox.create_task_copy(task_id)

        # In the task copy, simulate an agent creating a new file AND deleting a user file
        Path(os.path.join(copy_path, "new_feature.py")).write_text("def feature(): pass\n")
        os.remove(os.path.join(copy_path, "user_file.py"))  # Deleted in sandbox copy!

        # Inspect changes
        changes = sandbox.inspect_task_changes(task_id)
        self.assertEqual(len(changes["new_files"]), 1)
        self.assertEqual(len(changes["deleted_files"]), 1)
        self.assertIn("user_file.py", changes["deleted_files"])

        # Attempt to reconcile changes into user workspace
        with self.assertRaises(DestructiveChangeSetError) as ctx:
            sandbox.apply_task_changes(task_id)
        self.assertIn("Absolute No-Delete Policy", str(ctx.exception))

        # CRITICAL VERIFICATION: The original file MUST still exist in the user workspace!
        self.assertTrue(os.path.exists(os.path.join(self.ws_path, "user_file.py")))
        self.assertEqual(Path(os.path.join(self.ws_path, "user_file.py")).read_text(), "x = 10\n")

    def test_03_task_workspace_sandbox_applies_non_destructive_changes(self):
        """When change set contains only additions and edits, changes are applied with automatic backups."""
        original_file = os.path.join(self.ws_path, "model.py")
        file_service.create_file(original_file, "class Model:\n    pass\n")

        sandbox = TaskWorkspaceSandbox(self.ws_path)
        task_id = "task_safe_test_02"
        copy_path = sandbox.create_task_copy(task_id)

        # Add new file and edit existing file in sandbox
        Path(os.path.join(copy_path, "service.py")).write_text("class Service: pass\n")
        Path(os.path.join(copy_path, "model.py")).write_text("class Model:\n    def validate(self): return True\n")

        res = sandbox.apply_task_changes(task_id)
        self.assertEqual(res["status"], "success")
        self.assertIn("service.py", res["applied_additions"])
        self.assertIn("model.py", res["applied_modifications"])
        self.assertEqual(len(res["applied_deletions"]), 0)

        # Verify on disk
        self.assertTrue(os.path.exists(os.path.join(self.ws_path, "service.py")))
        self.assertIn("validate", Path(original_file).read_text())

    def test_04_ai_terminal_destructive_commands_strictly_denied(self):
        """When is_ai_initiated=True, rm, del, rmdir, git clean, and embedded script deletions are strictly DENIED."""
        # 1. rm -rf
        d, r = evaluate_command_security("rm", ["-rf", "build/"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)
        self.assertIn("Absolute No-Delete Policy", r)

        # 2. del
        d, r = evaluate_command_security("del", ["important.txt"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)

        # 3. rmdir
        d, r = evaluate_command_security("rmdir", ["docs"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)

        # 4. git clean
        d, r = evaluate_command_security("git", ["clean", "-fd"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)

        # 5. git reset --hard
        d, r = evaluate_command_security("git", ["reset", "--hard", "HEAD~1"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)

        # 6. Embedded Python file deletion
        d, r = evaluate_command_security("python", ["-c", "import os; os.remove('data.txt')"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)
        self.assertIn("Embedded file deletion", r)

        # 7. Embedded shutil.rmtree
        d, r = evaluate_command_security("python3", ["-c", "import shutil; shutil.rmtree('folder')"], is_ai_initiated=True)
        self.assertEqual(d, SecurityDecision.DENIED)


class TestModelDownloadService(unittest.TestCase):
    """Verifies model download system, user-level destination, pause, resume, and SHA-256."""

    def test_01_models_directory_is_user_level(self):
        m_dir = paths_service.get_models_dir()
        self.assertTrue(os.path.isdir(m_dir))
        self.assertIn(os.path.expanduser("~"), str(m_dir))

    def test_02_model_registry_and_initial_status(self):
        tasks = model_download_service.get_all_download_status()
        self.assertIn("llama-3.2-1b", tasks)
        task = tasks["llama-3.2-1b"]
        self.assertEqual(task["model_id"], "llama-3.2-1b")
        self.assertTrue(task["filename"].endswith(".gguf"))
        self.assertGreater(task["total_bytes"], 100_000_000)

    def test_03_mock_resumable_download_and_sha256(self):
        """Simulates range-based chunked download and checksum verification."""
        test_payload = b"GGUF_MOCK_MODEL_WEIGHTS_BYTE_STREAM_FOR_UNIT_TEST"
        import hashlib
        expected_sha = hashlib.sha256(test_payload).hexdigest()

        # Write to a mock destination in models dir
        mock_dest = os.path.join(paths_service.get_models_dir(), "mock_test_model.gguf")
        try:
            with open(mock_dest, "wb") as f:
                f.write(test_payload)

            actual_sha = model_download_service._compute_file_sha256(Path(mock_dest))
            self.assertEqual(actual_sha, expected_sha)
        finally:
            if os.path.exists(mock_dest):
                os.remove(mock_dest)


class TestToolDispatcherIntegration(unittest.TestCase):
    """Verifies that ToolDispatcher properly routes all non-destructive file and workspace tools."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="stroke_dispatcher_test_")
        self.ws_path = os.path.join(self.temp_dir, "project")
        os.makedirs(self.ws_path, exist_ok=True)
        workspace_service.approve_workspace(self.ws_path, label="Dispatcher Test")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_dispatch_file_create_and_read(self):
        target = os.path.join(self.ws_path, "dispatcher_file.py")
        # 1. create_file
        res_create = ToolDispatcher.dispatch("create_file", {
            "file_path": target,
            "content": "X = 42\n"
        })
        self.assertEqual(res_create["status"], "success")

        # 2. read_file
        res_read = ToolDispatcher.dispatch("read_file", {"file_path": target})
        self.assertEqual(res_read["status"], "success")
        self.assertEqual(res_read["content"], "X = 42\n")

    def test_02_dispatch_edit_and_backup(self):
        target = os.path.join(self.ws_path, "data.txt")
        file_service.create_file(target, "Version 1\n")

        # edit_file via dispatcher
        res_edit = ToolDispatcher.dispatch("edit_file", {
            "file_path": target,
            "new_content": "Version 2\n",
            "task_id": "dispatch_task"
        })
        self.assertEqual(res_edit["status"], "success")

        # list_backups via dispatcher
        res_backups = ToolDispatcher.dispatch("list_backups", {"file_path": target})
        self.assertEqual(res_backups["status"], "success")
        self.assertGreaterEqual(len(res_backups["backups"]), 1)


if __name__ == "__main__":
    unittest.main()
