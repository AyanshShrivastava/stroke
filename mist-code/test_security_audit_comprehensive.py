"""
================================================================================
STROKE // COMPREHENSIVE SECURITY, AUTH, AUTHORIZATION & DATA AUDIT REGRESSION SUITE
================================================================================
Validates all repairs from the repository-wide engineering security audit:
  1. Authoritative Firebase UID identity & cross-user chat isolation.
  2. Strict object ownership for chats, agent tasks, parallel jobs, and terminal sessions.
  3. Terminal session owner_uid enforcement across every operation:
     (create, run, read output, read output delta, history, status, list, stop, restart, stream).
  4. Isolation between authenticated users and internal daemon callers.
  5. Command approval token validation: caller_uid, session, single-use consumption, replay prevention.
  6. Workspace boundary validation & traversal rejection for diagnostics and filesystem.
  7. Absolute No-Delete Policy enforcement for AI-initiated file operations.
  8. MCP SSRF protection, DNS rebinding blocks, and child-process environment sanitization.
  9. MCP Secret Vault key corruption safety, backup recovery, and credential preservation.
 10. Complete /auth/account audit: subcollection purge, local memory purge, BYOK cleanup, honest reporting.
 11. Request body size limit (DoS prevention).
================================================================================
"""

import os
import sys
import time
import json
import socket
import asyncio
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
from main import app
import main
import auth_service
from auth_service import AuthenticatedUser
import terminal_service
from terminal_service import TerminalManager, ApprovalRecord
import workspace_service
import file_service
import backup_service
import mcp_client
from mcp_client import SsrfProtector, McpSecretVault, build_minimal_mcp_env, McpError
import credentials_vault_service
import paths_service
from agent_orchestrator import TaskState, TaskBudget, AgentTask, TaskManager


class TestCrossUserChatIsolation(unittest.TestCase):
    """Audits chat endpoints against cross-user snooping and email spoofing."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_cannot_list_chats_with_mismatching_email(self):
        """User A cannot list chats for User B by specifying email query param."""
        user_a = AuthenticatedUser(
            uid="user_alice_123",
            email="alice@example.com",
            email_verified=True,
            claims={"uid": "user_alice_123", "email": "alice@example.com"}
        )

        app.dependency_overrides[main.get_current_user] = lambda: user_a
        try:
            # Alice querying Bob's email must be forbidden
            resp = self.client.get("/chats?email=bob@example.com")
            self.assertEqual(resp.status_code, 403)
            self.assertIn("Access denied", resp.json()["detail"])
        finally:
            app.dependency_overrides.pop(main.get_current_user, None)

    def test_02_user_without_email_cannot_supply_foreign_email(self):
        """User authenticated without email claim cannot supply a foreign email parameter."""
        user_anon = AuthenticatedUser(
            uid="anon_user_999",
            email=None,
            email_verified=False,
            claims={"uid": "anon_user_999"}
        )

        app.dependency_overrides[main.get_current_user] = lambda: user_anon
        try:
            resp = self.client.get("/chats?email=victim@example.com")
            self.assertEqual(resp.status_code, 403)
        finally:
            app.dependency_overrides.pop(main.get_current_user, None)

    def test_03_cannot_save_chat_into_another_users_account(self):
        """User A cannot save a chat session attributed to User B's email."""
        user_a = AuthenticatedUser(
            uid="user_alice_123",
            email="alice@example.com",
            email_verified=True,
            claims={"uid": "user_alice_123", "email": "alice@example.com"}
        )

        app.dependency_overrides[main.get_current_user] = lambda: user_a
        try:
            payload = {
                "session_id": "session-tamper-1",
                "title": "Tampered Chat",
                "email": "victim@example.com",
                "messages": [{"id": "m1", "role": "user", "content": "hello"}]
            }
            resp = self.client.post("/chats/save", json=payload)
            self.assertEqual(resp.status_code, 403)
        finally:
            app.dependency_overrides.pop(main.get_current_user, None)


class TestAgentTaskAndJobIsolation(unittest.TestCase):
    """Audits agent tasks and parallel jobs against cross-user inspection and manipulation."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_unauthenticated_cannot_access_user_task(self):
        """Unauthenticated caller (user=None) cannot inspect another user's agent task."""
        task = TaskManager.create_task("Build secure module", user_uid="user_victim_456")

        # Calling without auth header -> get_optional_user returns None
        resp = self.client.get(f"/agent/tasks/{task.task_id}")
        self.assertEqual(resp.status_code, 403)

    def test_02_other_user_cannot_cancel_or_approve_task(self):
        """User A cannot cancel or approve a task owned by User B."""
        task = TaskManager.create_task("Build secure module", user_uid="user_victim_456")
        task.state = TaskState.AWAITING_APPROVAL

        user_attacker = AuthenticatedUser(
            uid="user_attacker_789",
            email="attacker@example.com",
            email_verified=True,
            claims={"uid": "user_attacker_789"}
        )

        app.dependency_overrides[main.get_optional_user] = lambda: user_attacker
        try:
            # Attacker cannot inspect
            resp = self.client.get(f"/agent/tasks/{task.task_id}")
            self.assertEqual(resp.status_code, 403)

            # Attacker cannot cancel
            resp_cancel = self.client.post(f"/agent/tasks/{task.task_id}/cancel")
            self.assertEqual(resp_cancel.status_code, 403)

            # Attacker cannot approve
            resp_appr = self.client.post(f"/agent/tasks/{task.task_id}/approve")
            self.assertEqual(resp_appr.status_code, 403)
        finally:
            app.dependency_overrides.pop(main.get_optional_user, None)

    def test_03_unauthenticated_cannot_access_parallel_job(self):
        """Unauthenticated caller cannot inspect or cancel a parallel agent job owned by a user."""
        import parallel_agent_system
        job = parallel_agent_system.global_multi_agent_orchestrator.create_job(
            user_goal="Test Goal",
            workspace_path=terminal_service.DEFAULT_WORKSPACE,
            user_uid="user_victim_456"
        )

        resp = self.client.get(f"/api/orchestrator/jobs/{job.job_id}")
        self.assertEqual(resp.status_code, 403)

        resp_cancel = self.client.post(f"/api/orchestrator/jobs/{job.job_id}/cancel")
        self.assertEqual(resp_cancel.status_code, 403)


class TestTerminalSessionAuthorization(unittest.TestCase):
    """Audits terminal session ownership and authorization across all operations."""

    def setUp(self):
        self.client = TestClient(app)
        # Create a session owned by user_alice
        res = TerminalManager.create_terminal(
            workspace_path=terminal_service.DEFAULT_WORKSPACE,
            caller_uid="user_alice",
            is_internal=False
        )
        self.alice_session_id = res["session_id"]

    def tearDown(self):
        try:
            TerminalManager.stop_terminal(self.alice_session_id, caller_uid="user_alice", is_internal=False)
        except Exception:
            pass

    def test_01_user_bob_cannot_access_alice_terminal_operations(self):
        """User Bob cannot run, read output, get status, restart, or stop Alice's terminal."""
        # 1. Run command raises PermissionError
        with self.assertRaises(PermissionError):
            TerminalManager.run_command(
                session_id=self.alice_session_id,
                command="python3",
                args=["--version"],
                caller_uid="user_bob",
                is_internal=False
            )

        # 2. Read output
        res_out = TerminalManager.read_terminal_output(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_out["status"], "error")
        self.assertEqual(res_out["error"], "access_denied")

        # 3. Read delta
        res_delta = TerminalManager.terminal_read_output_delta(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_delta["status"], "error")
        self.assertEqual(res_delta["error"], "access_denied")

        # 4. Status
        res_stat = TerminalManager.get_terminal_status(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_stat["status"], "error")
        self.assertEqual(res_stat["error"], "access_denied")

        # 5. History
        res_hist = TerminalManager.get_terminal_history(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_hist["status"], "error")
        self.assertEqual(res_hist["error"], "access_denied")

        # 6. Stop
        res_stop = TerminalManager.stop_terminal(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_stop["status"], "error")
        self.assertEqual(res_stop["error"], "access_denied")

        # 7. Restart
        res_restart = TerminalManager.restart_terminal(
            session_id=self.alice_session_id,
            caller_uid="user_bob",
            is_internal=False
        )
        self.assertEqual(res_restart["status"], "error")
        self.assertEqual(res_restart["error"], "access_denied")

    def test_02_firebase_user_cannot_claim_internal_daemon_identity(self):
        """A user request with auth='firebase' cannot claim caller_uid='internal_daemon'."""
        with self.assertRaises(Exception):
            main._extract_caller_uid_and_internal({
                "auth": "firebase",
                "is_internal": False,
                "uid": "internal_daemon"
            })

    def test_03_terminal_approval_token_cannot_be_replayed(self):
        """Single-use approval tokens cannot be replayed or consumed more than once."""
        session = TerminalManager.get_session(self.alice_session_id)
        appr_id = "appr-test-single-use-123"
        rec = ApprovalRecord(
            approval_id=appr_id,
            command="git",
            args=["push", "origin", "main"],
            cwd=session.cwd,
            uid="user_alice",
            session_id=self.alice_session_id,
            expires_at=time.time() + 300.0,
            consumed=False
        )
        terminal_service._APPROVAL_REGISTRY[appr_id] = rec

        # First consumption succeeds
        res1 = TerminalManager.respond_to_approval(
            approval_id=appr_id,
            approved=False,
            caller_uid="user_alice",
            is_internal=False
        )
        self.assertEqual(res1["status"], "denied")

        # Second attempt must be rejected as replayed or already consumed
        res2 = TerminalManager.respond_to_approval(
            approval_id=appr_id,
            approved=False,
            caller_uid="user_alice",
            is_internal=False
        )
        self.assertEqual(res2["status"], "error")
        self.assertIn("already", res2["message"].lower())


class TestMcpSecurityAndSsrf(unittest.TestCase):
    """Audits MCP Client SSRF, DNS rebinding, secret vault, and process cleanup."""

    def test_01_ssrf_protector_blocks_private_networks(self):
        """SsrfProtector blocks RFC 1918 private IPs, loopback, and carrier-grade NAT."""
        private_urls = [
            "http://10.0.0.1:8000/mcp",
            "http://172.16.0.5:8080/sse",
            "http://192.168.1.1/rpc",
            "http://100.64.0.1:3000/mcp",
            "http://127.0.0.1:8501/mcp",
            "http://localhost:8501/mcp",
        ]
        for u in private_urls:
            with self.assertRaises(McpError) as ctx:
                SsrfProtector.validate_url(u, allow_local=False)
            err_msg = str(ctx.exception).lower()
            self.assertTrue(
                "blocked" in err_msg or "prohibited" in err_msg or "restricted" in err_msg,
                f"Unexpected error message: {err_msg}"
            )

    def test_02_ssrf_protector_blocks_cloud_metadata(self):
        """SsrfProtector strictly blocks AWS/GCP cloud metadata IP and hostnames."""
        meta_urls = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/",
        ]
        for u in meta_urls:
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(u, allow_local=False)

    def test_03_ssrf_protector_blocks_dns_rebinding_domains(self):
        """SsrfProtector strictly blocks public wildcard DNS rebinding domains."""
        rebinding_urls = [
            "http://make-127-0-0-1-rr.nip.io:8080/mcp",
            "http://192.168.1.1.sslip.io/mcp",
            "http://customer.localtest.me/mcp",
        ]
        for u in rebinding_urls:
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(u, allow_local=False)

    def test_04_mcp_minimal_env_strips_backend_secrets(self):
        """build_minimal_mcp_env strips all sensitive tokens, keys, and credentials."""
        with patch.dict(os.environ, {
            "FIREBASE_SERVICE_ACCOUNT_KEY": "secret_firebase_key",
            "GITHUB_TOKEN": "ghp_secret_pat_value",
            "STROKE_INTERNAL_SECRET": "secret_internal_auth",
            "OPENAI_API_KEY": "sk-secret-key",
            "PATH": "/usr/bin:/bin",
            "USER": "developer"
        }, clear=True):
            clean_env = build_minimal_mcp_env()
            self.assertNotIn("FIREBASE_SERVICE_ACCOUNT_KEY", clean_env)
            self.assertNotIn("GITHUB_TOKEN", clean_env)
            self.assertNotIn("STROKE_INTERNAL_SECRET", clean_env)
            self.assertNotIn("OPENAI_API_KEY", clean_env)
            self.assertIn("PATH", clean_env)
            self.assertIn("USER", clean_env)

    def test_05_mcp_vault_refuses_silent_key_regeneration_when_encrypted_data_exists(self):
        """McpSecretVault refuses to regenerate a new key if encrypted configs exist."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            tmp_creds = tmp_path / "credentials"
            tmp_creds.mkdir(parents=True, exist_ok=True)
            mcp_cfg_path = tmp_path / "mcp_servers.json"
            mcp_cfg_path.write_text('{"server1": {"token": "enc:fernet:somesecret"}}', encoding="utf-8")

            # Temporarily point McpSecretVault to isolated temp directory
            old_cipher = McpSecretVault._cipher
            old_vault_dir = McpSecretVault.VAULT_DIR
            old_key_file = McpSecretVault.KEY_FILE
            old_bak = McpSecretVault._BAK_KEY_FILE

            McpSecretVault._cipher = None
            McpSecretVault.VAULT_DIR = str(tmp_creds)
            McpSecretVault.KEY_FILE = str(tmp_creds / ".mcp_vault_key")
            McpSecretVault._BAK_KEY_FILE = str(tmp_creds / ".mcp_vault_key.bak")

            with patch("paths_service.get_app_data_dir", return_value=tmp_path), \
                 patch.object(McpSecretVault, "_is_keyring_usable", return_value=False):
                try:
                    with self.assertRaises(RuntimeError) as ctx:
                        McpSecretVault._get_cipher()
                    self.assertIn("Cannot generate new MCP Vault key", str(ctx.exception))
                finally:
                    McpSecretVault._cipher = old_cipher
                    McpSecretVault.VAULT_DIR = old_vault_dir
                    McpSecretVault.KEY_FILE = old_key_file
                    McpSecretVault._BAK_KEY_FILE = old_bak


class TestFilesystemAndDiagnosticsSecurity(unittest.TestCase):
    """Audits workspace traversal, symlink resolution, and the Absolute No-Delete Policy."""

    def test_01_absolute_no_delete_policy_enforced(self):
        """Calling delete_file or remove_directory raises NoDeletePolicyViolation."""
        with self.assertRaises(file_service.NoDeletePolicyViolation):
            file_service.delete_file("/any/path/file.txt")

        with self.assertRaises(file_service.NoDeletePolicyViolation):
            file_service.remove_directory("/any/path/dir")

    def test_02_diagnostic_workspace_rejects_traversal(self):
        """_validate_diagnostic_workspace rejects '..' traversal sequences with HTTP 403."""
        from main import _validate_diagnostic_workspace
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _validate_diagnostic_workspace("../../etc")
        self.assertEqual(ctx.exception.status_code, 403)

    def test_03_diagnostic_workspace_rejects_paths_outside_approved_roots(self):
        """_validate_diagnostic_workspace rejects unapproved system paths."""
        from main import _validate_diagnostic_workspace
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            _validate_diagnostic_workspace("/var/log")
        self.assertEqual(ctx.exception.status_code, 403)


class TestAccountDeletionPurge(unittest.TestCase):
    """Audits /auth/account for complete data removal and honest status reporting."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_account_deletion_cleans_local_memory_and_vault(self):
        """Deleting account clears local memory files, chats, BYOK credentials, and returns honest status."""
        test_uid = "user_delete_test_555"
        test_email = "deleteme@example.com"

        # Seed local memory file
        mem_dir = paths_service.get_app_data_dir() / "local_user_memory"
        mem_dir.mkdir(parents=True, exist_ok=True)
        mem_file = mem_dir / f"{test_uid}.json"
        mem_file.write_text('{"records": []}', encoding="utf-8")

        # Seed local chat session
        main._LOCAL_CHAT_SESSIONS[test_uid] = [{"session_id": "s1", "title": "Delete Chat"}]

        # Seed BYOK credentials
        credentials_vault_service.vault.store_credential("openai", "sk-test-key-12345", user_id=test_uid)

        user = AuthenticatedUser(
            uid=test_uid,
            email=test_email,
            email_verified=True,
            claims={"uid": test_uid, "email": test_email}
        )

        app.dependency_overrides[main.get_current_user] = lambda: user
        try:
            resp = self.client.delete("/auth/account")
            self.assertIn(resp.status_code, (200, 207))
            data = resp.json()
            self.assertIn(data["status"], ("success", "partial_success"))
            self.assertEqual(data["uid"], test_uid)

            # Verify local memory file was unlinked
            self.assertFalse(mem_file.exists())

            # Verify chat session was removed
            self.assertNotIn(test_uid, main._LOCAL_CHAT_SESSIONS)

            # Verify BYOK credentials was removed
            self.assertIsNone(credentials_vault_service.vault.get_credential("openai", user_id=test_uid))
        finally:
            app.dependency_overrides.pop(main.get_current_user, None)


class TestDosProtection(unittest.TestCase):
    """Audits request body size limits against memory exhaustion DoS attacks."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_request_body_exceeding_50mb_returns_413(self):
        """Requests with Content-Length > 50 MB are immediately rejected with HTTP 413."""
        resp = self.client.post(
            "/auth/me",
            headers={"Content-Length": str(60 * 1024 * 1024)}
        )
        self.assertEqual(resp.status_code, 413)
        self.assertIn("exceeds 50 MB limit", resp.json()["detail"])


class TestPhase2SecurityHardening(unittest.TestCase):
    """Exhaustively verifies Phase 2 security hardening, token checks, and SSRF/traversal prevention."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_token_missing_exp_rejected(self):
        """Tokens without 'exp' claim are strictly rejected."""
        mock_claims = {
            "uid": "valid_user_1",
            "sub": "valid_user_1",
            "user_id": "valid_user_1",
            "aud": auth_service.get_firebase_project_id(),
            "iss": f"https://securetoken.google.com/{auth_service.get_firebase_project_id()}"
        }
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=mock_claims):
            with self.assertRaises(ValueError) as ctx:
                auth_service.verify_firebase_id_token("dummy_token")
            self.assertIn("expiration claim", str(ctx.exception))

    def test_02_token_future_iat_rejected(self):
        """Tokens issued more than 5 minutes in the future are rejected."""
        mock_claims = {
            "uid": "valid_user_1",
            "sub": "valid_user_1",
            "user_id": "valid_user_1",
            "aud": auth_service.get_firebase_project_id(),
            "iss": f"https://securetoken.google.com/{auth_service.get_firebase_project_id()}",
            "exp": time.time() + 3600,
            "iat": time.time() + 1000
        }
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=mock_claims):
            with self.assertRaises(ValueError) as ctx:
                auth_service.verify_firebase_id_token("dummy_token")
            self.assertIn("future", str(ctx.exception).lower())

    def test_03_token_subject_mismatch_rejected(self):
        """Tokens where 'user_id' and 'sub' claims mismatch are rejected."""
        mock_claims = {
            "uid": "alice",
            "sub": "alice",
            "user_id": "bob",
            "aud": auth_service.get_firebase_project_id(),
            "iss": f"https://securetoken.google.com/{auth_service.get_firebase_project_id()}",
            "exp": time.time() + 3600
        }
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=mock_claims):
            with self.assertRaises(ValueError) as ctx:
                auth_service.verify_firebase_id_token("dummy_token")
            self.assertIn("subject mismatch", str(ctx.exception).lower())

    def test_04_auth_config_payload_validation(self):
        """POST /auth/config rejects non-loopback emulatorHost and invalid project IDs."""
        res_bad_host = self.client.post("/auth/config", json={"emulatorHost": "evil.attacker.com:9099"})
        self.assertEqual(res_bad_host.status_code, 400)
        self.assertIn("loopback", res_bad_host.json()["detail"].lower())

        res_bad_proj = self.client.post("/auth/config", json={"projectId": "../../etc/passwd"})
        self.assertEqual(res_bad_proj.status_code, 400)
        self.assertIn("invalid firebase project id", res_bad_proj.json()["detail"].lower())

    def test_05_files_endpoints_require_auth_and_reject_traversal(self):
        """The /files/* endpoints enforce authentication and reject path traversal."""
        # Unauthenticated request rejected with 401
        res = self.client.post("/files/list", json={"dir_path": "."})
        self.assertEqual(res.status_code, 401)

        # Authenticated with internal secret, but with traversal rejected with 403
        headers = {"X-Stroke-Token": "test_internal_secret"}
        with patch.dict(os.environ, {"STROKE_INTERNAL_SECRET": "test_internal_secret"}):
            res_trav = self.client.post(
                "/files/read",
                json={"file_path": "../../../../etc/passwd"},
                headers=headers
            )
            self.assertEqual(res_trav.status_code, 403)

    def test_06_mcp_bridge_health_probe_rejects_ssrf(self):
        """check_server_health in mcp_bridge rejects cloud metadata and private network URLs."""
        import mcp_bridge
        is_live = asyncio.run(mcp_bridge.check_server_health("http://169.254.169.254/latest/meta-data/"))
        self.assertFalse(is_live)

    def test_07_mcp_env_blocks_dangerous_injection_keys(self):
        """build_minimal_mcp_env strips LD_PRELOAD, DYLD_INSERT_LIBRARIES and secret keys."""
        dirty_custom = {
            "LD_PRELOAD": "/lib/evil.so",
            "DYLD_INSERT_LIBRARIES": "/lib/evil.dylib",
            "STROKE_INTERNAL_SECRET": "leaked_secret",
            "CLEAN_CUSTOM_VAR": "clean_value"
        }
        env = build_minimal_mcp_env(dirty_custom)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("DYLD_INSERT_LIBRARIES", env)
        self.assertNotIn("STROKE_INTERNAL_SECRET", env)
        self.assertEqual(env.get("CLEAN_CUSTOM_VAR"), "clean_value")

    def test_08_coding_loop_validates_path_access_before_read(self):
        """ControlledChangeManager.apply_change rejects unapproved paths with workspace error."""
        from coding_loop import ControlledChangeManager
        res = ControlledChangeManager.apply_change(
            workspace_path="/tmp",
            relative_path="test_file.txt",
            new_content="print('hello')"
        )
        self.assertEqual(res.action, "skipped")
        self.assertIn("security error", res.error.lower())


if __name__ == "__main__":
    unittest.main()
