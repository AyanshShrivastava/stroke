"""
Stroke AI // Terminal Security and Process Lifecycle Test Suite
Exhaustively validates:
  1. Client-controlled approved=true bypass elimination.
  2. Zero-Trust loopback boundary & HTTP 401 unauthenticated rejection.
  3. One-time server-side approval records (exact command, argv, UID, session, cwd, expiry).
  4. Atomic approval consumption & anti-replay protection.
  5. Expiration enforcement for approval tokens.
  6. Command and argv mismatch rejection.
  7. Cross-user (UID) approval theft rejection.
  8. Session cwd mutation rejection.
  9. Prohibited commands (Zero Administrator Policy / No-Delete Policy) deny even with approval.
  10. Unknown session ID rejection without auto-creation (HTTP 404).
  11. Stopped session read-only enforcement (HTTP 400).
  12. Session capacity management (10 limit) protecting active running processes (HTTP 429).
  13. Child process environment sanitization & secret stripping.
  14. Windows and POSIX os.pathsep PATH construction.
  15. Process tree termination on timeout and cancellation.
  16. 256 KB bounded stream buffering without pipe deadlocks.
"""

import os
import sys
import time
import subprocess
import threading
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

from fastapi.testclient import TestClient
import main
from main import app
import terminal_service
from terminal_service import (
    TerminalManager,
    TerminalSession,
    ApprovalRecord,
    _APPROVAL_REGISTRY,
    _APPROVAL_LOCK,
    evaluate_command_security,
    SecurityDecision,
    get_sanitized_child_env,
    MAX_OUTPUT_BYTES,
    MAX_SESSIONS,
    DEFAULT_WORKSPACE
)
import auth_service


class TestTerminalSecurityAndLifecycle(unittest.TestCase):
    """Audits terminal security boundaries, server-side approvals, and process lifecycles."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_user = {
            "uid": "test_security_engineer",
            "email": "engineer@stroke.ai",
            "email_verified": True
        }
        self.auth_headers = {"Authorization": "Bearer mock-security-token"}
        # Clean terminal manager state before each test
        TerminalManager.cleanup_all()
        with _APPROVAL_LOCK:
            _APPROVAL_REGISTRY.clear()

    def tearDown(self):
        TerminalManager.cleanup_all()
        with _APPROVAL_LOCK:
            _APPROVAL_REGISTRY.clear()

    # --------------------------------------------------------------------------
    # 1. Client Approval Bypass Elimination
    # --------------------------------------------------------------------------
    def test_01_client_approved_param_ignored(self):
        """Client passing approved=True or attempting kwargs injection cannot bypass policy."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid="test_user")
        session_id = session_res["session_id"]

        # Run command requiring approval (e.g. python -c "print(1)")
        # Passing approved=True directly should be ignored
        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "print('bypass')"],
            approved=True,  # Attacker tries to bypass
            caller_uid="test_user"
        )
        self.assertEqual(result["status"], "requires_approval")
        self.assertIn("approval_id", result)

    # --------------------------------------------------------------------------
    # 2. Zero-Trust Loopback Boundary (HTTP 401)
    # --------------------------------------------------------------------------
    def test_02_loopback_unauthenticated_rejected_401(self):
        """Unauthenticated loopback HTTP requests to terminal endpoints return 401 Unauthorized."""
        res_create = self.client.post("/terminal/create", json={})
        self.assertEqual(res_create.status_code, 401)

        res_run = self.client.post("/terminal/run", json={"session_id": "fake", "command": "ls"})
        self.assertEqual(res_run.status_code, 401)

        res_appr = self.client.post("/terminal/approval/respond", json={"approval_id": "fake", "approved": True})
        self.assertEqual(res_appr.status_code, 401)

        res_out = self.client.get("/terminal/fake/output")
        self.assertEqual(res_out.status_code, 401)

    # --------------------------------------------------------------------------
    # 3. Server Approval Record Generation
    # --------------------------------------------------------------------------
    def test_03_server_approval_record_generation(self):
        """Triggering a sensitive command generates a one-time server ApprovalRecord with 300s TTL."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "import sys; print(sys.version)"],
            caller_uid=self.mock_user["uid"]
        )
        self.assertEqual(result["status"], "requires_approval")
        approval_id = result["approval_id"]

        with _APPROVAL_LOCK:
            self.assertIn(approval_id, _APPROVAL_REGISTRY)
            record = _APPROVAL_REGISTRY[approval_id]
            self.assertEqual(record.uid, self.mock_user["uid"])
            self.assertEqual(record.session_id, session_id)
            self.assertEqual(record.command, "python")
            self.assertEqual(record.args, ["-c", "import sys; print(sys.version)"])
            self.assertFalse(record.consumed)
            self.assertGreater(record.expires_at, time.time() + 250)

    # --------------------------------------------------------------------------
    # 4. Atomic Consumption & Anti-Replay
    # --------------------------------------------------------------------------
    def test_04_approval_atomic_consumption_and_replay_rejection(self):
        """Approval record is popped/consumed atomically. Second attempt must be rejected."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "print('atomic_test')"],
            caller_uid=self.mock_user["uid"]
        )
        approval_id = result["approval_id"]

        # First consumption: approved
        first_resp = TerminalManager.respond_to_approval(
            approval_id=approval_id,
            approved=True,
            caller_uid=self.mock_user["uid"]
        )
        self.assertEqual(first_resp.get("state"), "completed")
        self.assertIn("atomic_test", first_resp.get("stdout", ""))

        # Second consumption: replayed approval must fail
        replay_resp = TerminalManager.respond_to_approval(
            approval_id=approval_id,
            approved=True,
            caller_uid=self.mock_user["uid"]
        )
        self.assertEqual(replay_resp.get("status"), "error")
        self.assertTrue(replay_resp.get("error") in ("approval_not_found_or_already_consumed", "approval_replayed"))

    # --------------------------------------------------------------------------
    # 5. Expiration Enforcement
    # --------------------------------------------------------------------------
    def test_05_approval_expiry_rejection(self):
        """Expired approvals (time.time() > expires_at) must be rejected immediately."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "print('expired_test')"],
            caller_uid=self.mock_user["uid"]
        )
        approval_id = result["approval_id"]

        # Force record expiration
        with _APPROVAL_LOCK:
            _APPROVAL_REGISTRY[approval_id].expires_at = time.time() - 10

        exp_resp = TerminalManager.respond_to_approval(
            approval_id=approval_id,
            approved=True,
            caller_uid=self.mock_user["uid"]
        )
        self.assertEqual(exp_resp.get("status"), "error")
        self.assertEqual(exp_resp.get("error"), "approval_expired")

    # --------------------------------------------------------------------------
    # 6. Command & Argv Mismatch Rejection
    # --------------------------------------------------------------------------
    def test_06_approval_command_argv_mismatch_rejection(self):
        """Directly presenting a mismatched approval record to session execution must fail."""
        session = TerminalSession("term-test-mismatch", DEFAULT_WORKSPACE, owner_uid="user1")
        record = ApprovalRecord(
            approval_id="appr-1",
            uid="user1",
            session_id="term-test-mismatch",
            cwd=session.cwd,
            command="python",
            args=["-c", "print('safe')"],
            rationale="Test rationale",
            created_at=time.time(),
            expires_at=time.time() + 300,
            consumed=True
        )

        # Attacker tries to execute a different command using the approval record
        mismatch_cmd_res = session.execute_command("cat", ["safe.txt"], _approval_record=record)
        self.assertEqual(mismatch_cmd_res.get("status"), "error")
        self.assertEqual(mismatch_cmd_res.get("error"), "approval_command_mismatch")

        # Attacker tries to execute different arguments
        mismatch_args_res = session.execute_command("python", ["-c", "print('malicious')"], _approval_record=record)
        self.assertEqual(mismatch_args_res.get("status"), "error")
        self.assertEqual(mismatch_args_res.get("error"), "approval_args_mismatch")

    # --------------------------------------------------------------------------
    # 7. Cross-User UID Mismatch Rejection
    # --------------------------------------------------------------------------
    def test_07_approval_uid_mismatch_rejection(self):
        """User B cannot approve an action requested by User A."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid="victim_user_alice")
        session_id = session_res["session_id"]

        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "print('secret')"],
            caller_uid="victim_user_alice"
        )
        approval_id = result["approval_id"]

        # Attacker Bob tries to approve Alice's token
        thief_resp = TerminalManager.respond_to_approval(
            approval_id=approval_id,
            approved=True,
            caller_uid="attacker_user_bob"
        )
        self.assertEqual(thief_resp.get("status"), "error")
        self.assertEqual(thief_resp.get("error"), "approval_user_mismatch")

    # --------------------------------------------------------------------------
    # 8. Session CWD Mutation Rejection
    # --------------------------------------------------------------------------
    def test_08_approval_session_and_cwd_mismatch_rejection(self):
        """If the session working directory changes before approval, execution is rejected."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        result = TerminalManager.run_command(
            session_id=session_id,
            command="python",
            args=["-c", "print('cwd_test')"],
            caller_uid=self.mock_user["uid"]
        )
        approval_id = result["approval_id"]

        # Mutate the session CWD before approval is processed
        session = TerminalManager.get_session(session_id)
        session.cwd = os.path.dirname(session.cwd)

        cwd_resp = TerminalManager.respond_to_approval(
            approval_id=approval_id,
            approved=True,
            caller_uid=self.mock_user["uid"]
        )
        self.assertEqual(cwd_resp.get("status"), "error")
        self.assertEqual(cwd_resp.get("error"), "approval_cwd_mismatch")

    # --------------------------------------------------------------------------
    # 9. Prohibited Commands Remain Prohibited
    # --------------------------------------------------------------------------
    def test_09_prohibited_commands_rejected_even_with_approval(self):
        """Sudo, destructive commands, or privilege escalation remain denied even if approved."""
        # 1. Sudo is prohibited by Zero Administrator Policy
        decision, rationale = evaluate_command_security("sudo", ["apt-get", "update"])
        self.assertEqual(decision, SecurityDecision.DENIED)
        self.assertIn("Zero Administrator Policy", rationale)

        # 2. AI-initiated file deletion is prohibited by Absolute No-Delete Policy
        ai_del_dec, ai_del_rat = evaluate_command_security("rm", ["-rf", "important_dir"], is_ai_initiated=True)
        self.assertEqual(ai_del_dec, SecurityDecision.DENIED)
        self.assertIn("Absolute No-Delete Policy", ai_del_rat)

        # 3. Even if someone synthesizes an approval record for sudo, respond_to_approval re-verifies and rejects
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid="admin_user")
        session_id = session_res["session_id"]
        with _APPROVAL_LOCK:
            _APPROVAL_REGISTRY["appr-sudo"] = ApprovalRecord(
                approval_id="appr-sudo",
                uid="admin_user",
                session_id=session_id,
                cwd=DEFAULT_WORKSPACE,
                command="sudo",
                args=["whoami"],
                rationale="Prohibited sudo attempt",
                created_at=time.time(),
                expires_at=time.time() + 300,
                consumed=False
            )

        resp = TerminalManager.respond_to_approval("appr-sudo", True, caller_uid="admin_user")
        self.assertEqual(resp.get("status"), "error")
        self.assertEqual(resp.get("error"), "command_prohibited")

    # --------------------------------------------------------------------------
    # 10. Unknown Session ID (No Auto-Create, HTTP 404)
    # --------------------------------------------------------------------------
    def test_10_unknown_session_id_returns_error_no_auto_create(self):
        """Unknown session IDs return error / HTTP 404 and never create a default session."""
        res = TerminalManager.run_command(session_id="term-nonexistent-9999", command="ls", args=[])
        self.assertEqual(res.get("status"), "error")
        self.assertEqual(res.get("error"), "session_not_found")

        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
            http_res = self.client.post(
                "/terminal/run",
                json={"session_id": "term-nonexistent-8888", "command": "ls", "args": []},
                headers=self.auth_headers
            )
            self.assertEqual(http_res.status_code, 404)
            self.assertIn("not found", http_res.json()["detail"].lower())

    # --------------------------------------------------------------------------
    # 11. Stopped Session is Read-Only
    # --------------------------------------------------------------------------
    def test_11_stopped_session_is_read_only(self):
        """Stopped/reaped sessions reject command execution (HTTP 400), but output remains readable."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        # Run a safe command first
        TerminalManager.run_command(session_id=session_id, command="echo", args=["historical_line"])

        # Stop terminal
        stop_res = TerminalManager.stop_terminal(session_id)
        self.assertEqual(stop_res.get("status"), "terminated")

        # Command execution on stopped session must fail
        run_res = TerminalManager.run_command(session_id=session_id, command="echo", args=["new_attempt"])
        self.assertEqual(run_res.get("status"), "error")
        self.assertEqual(run_res.get("error"), "session_terminated")

        # Output remains readable
        out_res = TerminalManager.read_terminal_output(session_id)
        self.assertIn("historical_line", out_res.get("output", ""))

    # --------------------------------------------------------------------------
    # 12. Capacity Management Never Evicts Running Processes
    # --------------------------------------------------------------------------
    def test_12_capacity_management_never_evicts_active_process(self):
        """When 10 sessions have active running processes, creating an 11th raises RuntimeError (429)."""
        created_sessions = []
        try:
            # Create 10 sessions and mock active running processes on each
            for i in range(MAX_SESSIONS):
                res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid="stress_tester")
                sid = res["session_id"]
                created_sessions.append(sid)
                sess = TerminalManager.get_session(sid)
                mock_proc = MagicMock()
                mock_proc.poll.return_value = None  # Process is running!
                sess.current_process = mock_proc

            # Attempting to create an 11th session must raise RuntimeError (capacity reached)
            with self.assertRaises(RuntimeError) as ctx:
                TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid="stress_tester")
            self.assertIn("capacity reached", str(ctx.exception).lower())

            # Verify HTTP endpoint returns 429
            with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
                http_res = self.client.post("/terminal/create", json={}, headers=self.auth_headers)
                self.assertEqual(http_res.status_code, 429)

        finally:
            # Clean up mocks
            for sid in created_sessions:
                sess = TerminalManager.get_session(sid)
                if sess:
                    sess.current_process = None

    # --------------------------------------------------------------------------
    # 13. Child Process Environment Sanitization
    # --------------------------------------------------------------------------
    def test_13_child_environment_sanitization(self):
        """Sanitized child environment strips all backend secrets and credentials."""
        # Inject sensitive environment variables in parent process
        test_secrets = {
            "FIREBASE_ADMIN_KEY": "secret_fb_key_12345",
            "FIREBASE_PROJECT_ID": "stroke-secret-project",
            "GITHUB_PAT": "ghp_012345678901234567890123456789012345",
            "RESEND_API_KEY": "re_1234567890abcdefghijklmn",
            "STROKE_INTERNAL_SECRET": "STRK_super_secret_token_value_999",
            "CIPHER_ENCRYPTION_KEY": "very_secret_cipher_key",
            "DATABASE_URL": "postgres://user:pass@localhost:5432/stroke",
            "SAFE_DEV_VARIABLE": "visible_routine_data"
        }
        for k, v in test_secrets.items():
            os.environ[k] = v

        child_env = get_sanitized_child_env(DEFAULT_WORKSPACE)

        # Sensitive variables must NOT be present in child env
        for secret_key in [
            "FIREBASE_ADMIN_KEY", "FIREBASE_PROJECT_ID", "GITHUB_PAT",
            "RESEND_API_KEY", "STROKE_INTERNAL_SECRET", "CIPHER_ENCRYPTION_KEY",
            "DATABASE_URL"
        ]:
            self.assertNotIn(secret_key, child_env, f"Secret key {secret_key} leaked into child env!")

        # Whitelisted dev keys must be present if set
        self.assertIn("PATH", child_env)
        self.assertEqual(child_env.get("PYTHONUNBUFFERED"), "1")
        self.assertEqual(child_env.get("PYTHONDONTWRITEBYTECODE"), "1")

    # --------------------------------------------------------------------------
    # 14. Windows and POSIX os.pathsep PATH Construction
    # --------------------------------------------------------------------------
    def test_14_windows_and_posix_pathsep(self):
        """Child PATH is joined using os.pathsep and includes venv bin/Scripts."""
        child_env = get_sanitized_child_env(DEFAULT_WORKSPACE)
        child_path = child_env.get("PATH", "")
        self.assertTrue(len(child_path) > 0)
        # Verify separator matches platform
        if sys.platform == "win32":
            self.assertIn(";", child_path)
        else:
            self.assertIn(":", child_path)

    # --------------------------------------------------------------------------
    # 15. Process Tree Termination on Timeout
    # --------------------------------------------------------------------------
    def test_15_process_tree_termination(self):
        """Processes exceeding timeout are cleanly terminated along with their process group."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        sleep_script = os.path.join(DEFAULT_WORKSPACE, "test_sleep_tmp.py")
        with open(sleep_script, "w") as f:
            f.write("import time\ntime.sleep(10)\n")

        try:
            start = time.time()
            res = TerminalManager.run_command(
                session_id=session_id,
                command="python",
                args=["test_sleep_tmp.py"],
                timeout_sec=1,
                caller_uid=self.mock_user["uid"]
            )
            elapsed = time.time() - start

            self.assertEqual(res.get("state"), "timed_out")
            self.assertTrue(res.get("timed_out"))
            self.assertLess(elapsed, 4.0, "Process tree termination should happen promptly upon timeout.")
        finally:
            if os.path.exists(sleep_script):
                os.remove(sleep_script)

    # --------------------------------------------------------------------------
    # 16. Stream Bounded Output Cap (256 KB)
    # --------------------------------------------------------------------------
    def test_16_stream_bounded_output_cap_256kb(self):
        """Excess output exceeding 256KB buffer cap is truncated without hanging the pipe."""
        session_res = TerminalManager.create_terminal(DEFAULT_WORKSPACE, caller_uid=self.mock_user["uid"])
        session_id = session_res["session_id"]

        cap_script = os.path.join(DEFAULT_WORKSPACE, "test_cap_tmp.py")
        with open(cap_script, "w") as f:
            f.write("import sys\nsys.stdout.write('X' * 500000)\n")

        try:
            res = TerminalManager.run_command(
                session_id=session_id,
                command="python",
                args=["test_cap_tmp.py"],
                timeout_sec=5,
                caller_uid=self.mock_user["uid"]
            )
            self.assertEqual(res.get("state"), "completed")
            self.assertEqual(res.get("exit_code"), 0)

            # Read session buffer
            out_res = TerminalManager.read_terminal_output(session_id)
            combined_output = out_res.get("output", "")
            # Total buffered bytes must be bounded near MAX_OUTPUT_BYTES
            self.assertLessEqual(len(combined_output.encode("utf-8")), MAX_OUTPUT_BYTES + 4096)
            self.assertIn("256KB buffer limit", combined_output)
        finally:
            if os.path.exists(cap_script):
                os.remove(cap_script)


if __name__ == "__main__":
    unittest.main()
