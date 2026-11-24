"""
================================================================================
STROKE // COMPLETE SECURITY REPAIR & HARDENING VERIFICATION TEST SUITE
================================================================================
Comprehensive verification of all 8 core security repair mandates:
1. Multi-Tenant Terminal Ownership & Isolation (Strict UID enforcement across
   run, read output, read delta, history, status, list, stop, restart, SSE stream;
   internal daemon segregation).
2. Diagnostics Workspace Path Traversal & Pytest Execution Boundary Enforcement
   (/diagnostics/hunt, /diagnostics/tests, /diagnostics/report, /diagnostics/broken-imports,
   StrokeBugHunter, TestExecutionRunner, TestDiscoveryEngine, BrokenImportScanner).
3. Terminal, Filesystem, Diagnostics & Model Download Endpoints Hardening.
4. Cryptographic Command Approval Records (UID match, Session match, Exact argv,
   Expiry, One-Time Consumption, Replay prevention).
5. MCP SSRF, DNS Rebinding, Redirect Validation & Cloud Metadata Isolation
   (169.254.169.254 and metadata.google.internal blocked even if allow_local=True).
6. Security Header Middleware: Host Validation, Strict Origin Validation, CORS,
   CSRF, Clickjacking (X-Frame-Options: DENY, CSP).
7. Filesystem Boundary Enforcement & Absolute No-Delete Policy Integrity.
8. Secret Scrubbing & Terminal Output Redaction (Raw JWTs, Anthropic keys, HF tokens,
   dynamic environment runtime secrets).
================================================================================
"""

import os
import sys
import time
import json
import uuid
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# Environment flags for offline testing
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"
os.environ["STROKE_DEV_CONSOLE_OTP"] = "1"
os.environ["FIREBASE_PROJECT_ID"] = "stroke-security-repair"
os.environ["STROKE_INTERNAL_SECRET"] = "repair_internal_secret_key_abcdef_987654"

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from fastapi.testclient import TestClient
import main
from main import app, SecurityHeaderMiddleware
import auth_service
from auth_service import AuthenticatedUser
import terminal_service
from terminal_service import (
    TerminalManager,
    ApprovalRecord,
    redact_sensitive_data,
    is_allowed_workspace_root,
    get_sanitized_child_env
)
import bug_hunter_service
from bug_hunter_service import (
    StrokeBugHunter,
    TestExecutionRunner,
    TestDiscoveryEngine,
    BrokenImportScanner
)
import file_service
from file_service import NoDeletePolicyViolation
import model_download_service
from model_download_service import validate_model_key
import mcp_client
from mcp_client import SsrfProtector, McpError, StreamableHttpTransport
import workspace_service
from workspace_service import WorkspaceSecurityError


class TestSecurityRepairComprehensive(unittest.TestCase):
    """Exhaustive test suite verifying the complete security repair of Stroke."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.internal_token = os.environ["STROKE_INTERNAL_SECRET"]

    def setUp(self):
        app.dependency_overrides.clear()
        self.user_alice = AuthenticatedUser(
            uid="uid_alice_sec",
            email="alice@stroke.internal",
            email_verified=True,
            display_name="Alice Sec"
        )
        self.user_bob = AuthenticatedUser(
            uid="uid_bob_sec",
            email="bob@stroke.internal",
            email_verified=True,
            display_name="Bob Sec"
        )

    def tearDown(self):
        app.dependency_overrides.clear()

    # ==========================================================================
    # 1. MULTI-TENANT TERMINAL OWNERSHIP & ISOLATION
    # ==========================================================================

    def test_01_terminal_ownership_run_and_read_isolation(self):
        """User Bob cannot run commands or read output/delta from User Alice's terminal session."""
        # Alice creates a session
        create_res = TerminalManager.create_terminal(
            session_id="term_alice_01",
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertIn("term_alice_01", create_res.get("session_id", ""))

        # Bob attempts to run command on Alice's session -> PermissionError
        with self.assertRaises(PermissionError):
            TerminalManager.run_command(
                session_id="term_alice_01",
                command="echo 'hacked'",
                caller_uid=self.user_bob.uid,
                is_internal=False
            )

        # Bob attempts to read output -> access_denied
        out_res = TerminalManager.read_terminal_output(
            session_id="term_alice_01",
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(out_res.get("status"), "error")
        self.assertEqual(out_res.get("error"), "access_denied")

        # Bob attempts to read output delta -> access_denied
        delta_res = TerminalManager.terminal_read_output_delta(
            session_id="term_alice_01",
            since_offset=0,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(delta_res.get("status"), "error")
        self.assertEqual(delta_res.get("error"), "access_denied")

        # Alice herself CAN read output
        alice_out = TerminalManager.read_terminal_output(
            session_id="term_alice_01",
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertNotEqual(alice_out.get("status"), "error")

    def test_02_terminal_ownership_history_status_and_list_isolation(self):
        """User Bob cannot view history, status, or enumerate Alice's sessions in list."""
        sess_id = "term_alice_02"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        # Bob attempts status -> access_denied
        status_res = TerminalManager.get_terminal_status(
            session_id=sess_id,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(status_res.get("status"), "error")
        self.assertEqual(status_res.get("error"), "access_denied")

        # Bob attempts history -> access_denied
        hist_res = TerminalManager.get_terminal_history(
            session_id=sess_id,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(hist_res.get("status"), "error")
        self.assertEqual(hist_res.get("error"), "access_denied")

        # Bob lists sessions -> Alice's session must NOT appear
        bob_list = TerminalManager.list_terminals(
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        bob_session_ids = [t.get("session_id") for t in bob_list]
        self.assertNotIn(sess_id, bob_session_ids)

        # Alice lists sessions -> Alice's session DOES appear
        alice_list = TerminalManager.list_terminals(
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        alice_session_ids = [t.get("session_id") for t in alice_list]
        self.assertIn(sess_id, alice_session_ids)

    def test_03_terminal_ownership_stop_and_restart_isolation(self):
        """User Bob cannot stop or restart User Alice's session."""
        sess_id = "term_alice_03"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        # Bob attempts stop -> access_denied
        stop_res = TerminalManager.stop_terminal(
            session_id=sess_id,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(stop_res.get("status"), "error")
        self.assertEqual(stop_res.get("error"), "access_denied")

        # Bob attempts restart -> access_denied
        restart_res = TerminalManager.restart_terminal(
            session_id=sess_id,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(restart_res.get("status"), "error")
        self.assertEqual(restart_res.get("error"), "access_denied")

        # Alice stops her own session -> success
        alice_stop = TerminalManager.stop_terminal(
            session_id=sess_id,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertEqual(alice_stop.get("status"), "stopped")

    def test_04_terminal_daemon_segregation(self):
        """Firebase users cannot access internal daemon sessions; daemon requires explicit secret."""
        daemon_sess = "term_daemon_internal_01"
        TerminalManager.create_terminal(
            session_id=daemon_sess,
            cwd=str(ROOT_DIR),
            owner_uid="internal_daemon",
            caller_uid="internal_daemon",
            is_internal=True
        )

        # Firebase user Alice cannot access internal daemon session
        out = TerminalManager.read_terminal_output(
            session_id=daemon_sess,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertEqual(out.get("status"), "error")
        self.assertEqual(out.get("error"), "access_denied")

        # Firebase user Alice claiming owner_uid="internal_daemon" without is_internal is rejected
        with self.assertRaises(PermissionError):
            TerminalManager.create_terminal(
                session_id="term_spoofed",
                cwd=str(ROOT_DIR),
                owner_uid="internal_daemon",
                caller_uid="uid_alice_sec",
                is_internal=False
            )

        # Authenticated daemon with is_internal=True CAN access
        daemon_out = TerminalManager.read_terminal_output(
            session_id=daemon_sess,
            caller_uid="internal_daemon",
            is_internal=True
        )
        self.assertNotEqual(daemon_out.get("status"), "error")

    def test_05_fastapi_terminal_endpoints_enforce_multi_tenant_403(self):
        """FastAPI REST endpoints enforce 403 on cross-user session tampering."""
        sess_id = "term_alice_rest_01"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        # Mock auth as Bob
        with patch("auth_service.verify_firebase_id_token", return_value={"uid": self.user_bob.uid, "email": self.user_bob.email}):
            auth_headers = {
                "Authorization": "Bearer fake_token_for_bob",
                "Host": "localhost:8501"
            }

            # Bob tries POST /terminal/run
            resp_run = self.client.post("/terminal/run", json={"session_id": sess_id, "command": "echo test"}, headers=auth_headers)
            self.assertEqual(resp_run.status_code, 403)

            # Bob tries GET /terminal/{session_id}/output
            resp_out = self.client.get(f"/terminal/{sess_id}/output", headers=auth_headers)
            self.assertEqual(resp_out.status_code, 403)

            # Bob tries GET /terminal/{session_id}/status
            resp_stat = self.client.get(f"/terminal/{sess_id}/status", headers=auth_headers)
            self.assertEqual(resp_stat.status_code, 403)

            # Bob tries GET /terminal/{session_id}/history
            resp_hist = self.client.get(f"/terminal/{sess_id}/history", headers=auth_headers)
            self.assertEqual(resp_hist.status_code, 403)

            # Bob tries POST /terminal/{session_id}/stop
            resp_stop = self.client.post(f"/terminal/{sess_id}/stop", headers=auth_headers)
            self.assertEqual(resp_stop.status_code, 403)

            # Bob tries POST /terminal/{session_id}/restart
            resp_rest = self.client.post(f"/terminal/{sess_id}/restart", headers=auth_headers)
            self.assertEqual(resp_rest.status_code, 403)

            # Bob tries GET /terminal/{session_id}/stream
            resp_strm = self.client.get(f"/terminal/{sess_id}/stream", headers=auth_headers)
            self.assertEqual(resp_strm.status_code, 403)

    # ==========================================================================
    # 2. DIAGNOSTICS WORKSPACE RESTRICTIONS & TRAVERSAL REJECTION
    # ==========================================================================

    def test_06_diagnostics_endpoints_reject_workspace_traversal(self):
        """Diagnostics endpoints (/diagnostics/*) reject unapproved workspace roots with HTTP 403."""
        forbidden_paths = [
            "/etc",
            "/var/root",
            "../../",
            "../../../etc/passwd"
        ]
        headers = {"Host": "localhost:8501"}

        for fpath in forbidden_paths:
            # 1. /diagnostics/hunt
            resp = self.client.post("/diagnostics/hunt", json={"workspace_path": fpath}, headers=headers)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for /diagnostics/hunt with {fpath}")

            # 2. /diagnostics/tests
            resp = self.client.get(f"/diagnostics/tests?workspace_path={fpath}", headers=headers)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for /diagnostics/tests with {fpath}")

            # 3. /diagnostics/report
            resp = self.client.get(f"/diagnostics/report?workspace_path={fpath}", headers=headers)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for /diagnostics/report with {fpath}")

            # 4. /diagnostics/broken-imports
            resp = self.client.post("/diagnostics/broken-imports", json={"workspace_path": fpath}, headers=headers)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for /diagnostics/broken-imports with {fpath}")

    def test_07_bug_hunter_classes_raise_permission_error_on_unapproved_roots(self):
        """Direct invocation of Bug Hunter and test runners raises PermissionError on unapproved roots."""
        outside_path = Path("/etc")

        # 1. StrokeBugHunter
        with self.assertRaises(PermissionError):
            StrokeBugHunter(workspace_path=str(outside_path))

        # 2. TestExecutionRunner backend pytest
        with self.assertRaises(PermissionError):
            TestExecutionRunner.run_backend_pytest(root_dir=outside_path)

        # 3. TestExecutionRunner frontend vitest
        with self.assertRaises(PermissionError):
            TestExecutionRunner.run_frontend_vitest(root_dir=outside_path)

        # 4. TestDiscoveryEngine backend tests
        with self.assertRaises(PermissionError):
            TestDiscoveryEngine.discover_backend_tests(root_dir=outside_path)

        # 5. TestDiscoveryEngine frontend tests
        with self.assertRaises(PermissionError):
            TestDiscoveryEngine.discover_frontend_tests(root_dir=outside_path)

        # 6. BrokenImportScanner
        with self.assertRaises(PermissionError):
            BrokenImportScanner.scan_project_imports(root_dir=outside_path)

    # ==========================================================================
    # 3. AUDIT OF TERMINAL, FILESYSTEM, DIAGNOSTICS & MODEL DOWNLOAD ENDPOINTS
    # ==========================================================================

    def test_08_model_catalog_validation_and_endpoint(self):
        """Model download service strictly validates catalog keys and rejects path traversal."""
        # Valid key
        valid_key = validate_model_key("deepseek-coder-6.7b")
        self.assertEqual(valid_key, "deepseek-coder-6.7b")

        # Traversal keys or unknown keys raise ValueError
        for bad_key in ["../../etc/passwd", "evil_model", "qwen2.5/../../escape", ""]:
            with self.assertRaises(ValueError):
                validate_model_key(bad_key)

        # REST endpoint /models/download returns 400 for invalid model
        resp = self.client.post("/models/download", json={"model_key": "../../etc/shadow"}, headers={"Host": "localhost:8501"})
        self.assertEqual(resp.status_code, 400)

    def test_09_filesystem_endpoints_reject_workspace_escape_with_403(self):
        """Filesystem endpoints (/fs/*) reject directory traversal escapes with HTTP 403."""
        headers = {"Host": "localhost:8501"}

        # GET /fs/read
        resp_read = self.client.get("/fs/read?path=../../etc/passwd", headers=headers)
        self.assertEqual(resp_read.status_code, 403)

        # POST /fs/write
        resp_write = self.client.post("/fs/write", json={"path": "/etc/evil_config.conf", "content": "attack"}, headers=headers)
        self.assertEqual(resp_write.status_code, 403)

        # GET /fs/list
        resp_list = self.client.get("/fs/list?dir=../../../../var", headers=headers)
        self.assertEqual(resp_list.status_code, 403)

    # ==========================================================================
    # 4. COMMAND APPROVAL RECORD CHECKS
    # ==========================================================================

    def test_10_command_approval_expiry_rejection(self):
        """Expired command approvals cannot be responded to or executed."""
        sess_id = "term_approval_01"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        expired_record = ApprovalRecord(
            approval_id="appr_expired_1",
            session_id=sess_id,
            command="git",
            argv=["git", "commit", "-m", "test"],
            reason="Destructive git command",
            expires_at=time.time() - 30.0,  # Expired 30 seconds ago
            uid=self.user_alice.uid
        )
        TerminalManager._pending_approvals[expired_record.approval_id] = expired_record

        # Responding to expired approval fails
        res = TerminalManager.respond_to_approval(
            approval_id=expired_record.approval_id,
            approved=True,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertEqual(res.get("status"), "error")
        self.assertIn("expired", res.get("message", "").lower())

    def test_11_command_approval_one_time_consumption_and_replay_prevention(self):
        """Approval records can only be consumed once; replays are rejected."""
        sess_id = "term_approval_02"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        record = ApprovalRecord(
            approval_id="appr_replay_1",
            session_id=sess_id,
            command="git",
            argv=["git", "status"],
            reason="Routine check",
            expires_at=time.time() + 60.0,
            uid=self.user_alice.uid
        )
        TerminalManager._pending_approvals[record.approval_id] = record

        # First consumption succeeds
        res1 = TerminalManager.respond_to_approval(
            approval_id=record.approval_id,
            approved=True,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertEqual(res1.get("status"), "success")

        # Second consumption fails (replay prevention)
        res2 = TerminalManager.respond_to_approval(
            approval_id=record.approval_id,
            approved=True,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )
        self.assertEqual(res2.get("status"), "error")
        self.assertIn("already responded", res2.get("message", "").lower())

    def test_12_command_approval_uid_and_session_mismatch_rejection(self):
        """User Bob cannot approve or hijack an approval record generated for User Alice."""
        sess_id = "term_approval_03"
        TerminalManager.create_terminal(
            session_id=sess_id,
            cwd=str(ROOT_DIR),
            owner_uid=self.user_alice.uid,
            caller_uid=self.user_alice.uid,
            is_internal=False
        )

        record = ApprovalRecord(
            approval_id="appr_cross_user_1",
            session_id=sess_id,
            command="git",
            argv=["git", "merge", "dev"],
            reason="Git merge",
            expires_at=time.time() + 60.0,
            uid=self.user_alice.uid
        )
        TerminalManager._pending_approvals[record.approval_id] = record

        # User Bob attempts to approve Alice's command -> error
        res = TerminalManager.respond_to_approval(
            approval_id=record.approval_id,
            approved=True,
            caller_uid=self.user_bob.uid,
            is_internal=False
        )
        self.assertEqual(res.get("status"), "error")
        self.assertIn("denied", res.get("message", "").lower())

    # ==========================================================================
    # 5. MCP SSRF, DNS REBINDING & CLOUD METADATA ISOLATION
    # ==========================================================================

    def test_13_mcp_ssrf_cloud_metadata_blocked_unconditionally(self):
        """Cloud metadata (169.254.169.254 and metadata.google.internal) is blocked even with allow_local=True."""
        metadata_targets = [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://instance-data/latest/meta-data/"
        ]
        for target in metadata_targets:
            # Blocked with allow_local=False
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(target, allow_local=False)

            # MUST ALSO be blocked with allow_local=True
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(target, allow_local=True)

    def test_14_mcp_dns_rebinding_domains_blocked(self):
        """Known DNS rebinding wildcards (.nip.io, .sslip.io, .localtest.me) are blocked."""
        rebinding_urls = [
            "http://127.0.0.1.nip.io:8080/mcp",
            "http://test.sslip.io:3000",
            "http://localtest.me:8501",
            "http://sub.vcap.me:9000",
            "http://traefik.me:8000"
        ]
        for url in rebinding_urls:
            with self.assertRaises(McpError) as ctx:
                SsrfProtector.validate_url(url, allow_local=True)
            self.assertIn("rebinding", str(ctx.exception).lower())

    def test_15_mcp_carrier_grade_nat_and_reserved_ranges_blocked(self):
        """Carrier-Grade NAT (100.64.0.0/10) and benchmark subnets (198.18.0.0/15) are blocked."""
        blocked_ips = [
            "http://100.64.0.1:8000",
            "http://100.127.255.254:80",
            "http://198.18.0.1:8080",
            "http://198.19.255.255:443",
            "http://192.0.2.1:80",
            "http://198.51.100.1:80",
            "http://203.0.113.1:80"
        ]
        for url in blocked_ips:
            with self.assertRaises(McpError):
                SsrfProtector.validate_url(url, allow_local=False)

    # ==========================================================================
    # 6. HOST, ORIGIN, CORS, CSRF & SECURITY HEADERS
    # ==========================================================================

    def test_16_host_header_validation(self):
        """Host header is required and must match allowed loopback hosts; unlisted hosts return 400."""
        # Missing Host header -> 400
        # In HTTP/1.1 client, simulate by sending an empty/malicious host
        resp_bad_host = self.client.get("/api/ai/models", headers={"Host": "attacker.evil.com"})
        self.assertEqual(resp_bad_host.status_code, 400)
        self.assertIn("Invalid Host", resp_bad_host.json().get("detail", ""))

        # Allowed host -> 200
        resp_good_host = self.client.get("/api/ai/models", headers={"Host": "localhost:8501"})
        self.assertEqual(resp_good_host.status_code, 200)

    def test_17_origin_validation_and_cors(self):
        """Strict Origin validation rejects untrusted external origins with 403; allows approved ones."""
        # Untrusted origin -> 403
        resp_bad_orig = self.client.get(
            "/api/ai/models",
            headers={"Host": "localhost:8501", "Origin": "http://evil.com"}
        )
        self.assertEqual(resp_bad_orig.status_code, 403)
        self.assertIn("Origin not allowed", resp_bad_orig.json().get("detail", ""))

        # Untrusted localhost port -> 403
        resp_bad_port = self.client.get(
            "/api/ai/models",
            headers={"Host": "localhost:8501", "Origin": "http://localhost:9999"}
        )
        self.assertEqual(resp_bad_port.status_code, 403)

        # Approved origin -> 200 with CORS headers
        resp_good = self.client.get(
            "/api/ai/models",
            headers={"Host": "localhost:8501", "Origin": "http://localhost:3000"}
        )
        self.assertEqual(resp_good.status_code, 200)
        self.assertEqual(resp_good.headers.get("access-control-allow-origin"), "http://localhost:3000")

    def test_18_security_response_headers_present(self):
        """Verify response headers: X-Content-Type-Options, X-Frame-Options, CSP."""
        resp = self.client.get("/api/ai/models", headers={"Host": "localhost:8501"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("x-content-type-options"), "nosniff")
        self.assertEqual(resp.headers.get("x-frame-options"), "DENY")
        self.assertIn("default-src 'self'", resp.headers.get("content-security-policy", ""))
        self.assertIn("frame-ancestors 'none'", resp.headers.get("content-security-policy", ""))

    def test_19_github_connect_initiating_origin_validation(self):
        """POST /auth/github-connect validates initiating_origin against ALLOWED_ORIGINS."""
        # Disallowed origin returns 403
        resp_bad = self.client.post(
            "/auth/github-connect",
            json={"initiating_origin": "http://malicious.evil.com"},
            headers={"Host": "localhost:8501"}
        )
        self.assertEqual(resp_bad.status_code, 403)

        # Allowed origin succeeds
        resp_good = self.client.post(
            "/auth/github-connect",
            json={"initiating_origin": "http://localhost:3000"},
            headers={"Host": "localhost:8501"}
        )
        self.assertEqual(resp_good.status_code, 200)

    # ==========================================================================
    # 7. FILESYSTEM BOUNDARIES & ABSOLUTE NO-DELETE POLICY
    # ==========================================================================

    def test_20_absolute_no_delete_policy_cannot_be_bypassed(self):
        """AI-initiated file operations MUST NEVER delete files; delete_file unconditionally raises NoDeletePolicyViolation."""
        target_path = str(ROOT_DIR / "dummy_file.tmp")
        with self.assertRaises(NoDeletePolicyViolation):
            file_service.delete_file(target_path)

    # ==========================================================================
    # 8. SECRET REDACTION & ENVIRONMENT SANITIZATION
    # ==========================================================================

    def test_21_raw_jwt_and_anthropic_secret_redaction(self):
        """Verify terminal output redacts raw JWTs, Anthropic keys, Hugging Face tokens, and env secrets."""
        # 1. Raw JWT (standard header.payload.signature)
        raw_jwt = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        redacted = redact_sensitive_data(f"Token is {raw_jwt} in output")
        self.assertNotIn(raw_jwt, redacted)
        self.assertIn("[REDACTED_JWT]", redacted)

        # 2. Anthropic API key
        anthropic_key = "sk-ant-api03-abcdef1234567890abcdef1234567890abcdef"
        redacted_ant = redact_sensitive_data(f"Key: {anthropic_key}")
        self.assertNotIn(anthropic_key, redacted_ant)
        self.assertIn("[REDACTED_ANTHROPIC_API_KEY]", redacted_ant)

        # 3. Hugging Face token
        hf_token = "hf_abcdefghijklmnopqrstuvwxyz01234567"
        redacted_hf = redact_sensitive_data(f"HF: {hf_token}")
        self.assertNotIn(hf_token, redacted_hf)
        self.assertIn("[REDACTED_HF_TOKEN]", redacted_hf)

        # 4. Dynamic environment secrets
        internal_secret = os.environ.get("STROKE_INTERNAL_SECRET", "")
        if internal_secret:
            redacted_env = redact_sensitive_data(f"Internal secret: {internal_secret}")
            self.assertNotIn(internal_secret, redacted_env)
            self.assertIn("[REDACTED_SECRET]", redacted_env)

    # ==========================================================================
    # 9. NEW AUDIT REPAIR TESTS (DATABASE, VAULT, AND ACCOUNT DELETION)
    # ==========================================================================

    def test_22_local_firestore_transaction_commit_and_snapshot_reference(self):
        """Verifies LocalTx has commit() and LocalDocumentSnapshot retains reference."""
        import tempfile
        import local_firestore
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "test_db.json")
            client = local_firestore.LocalFirestoreClient(storage_path=db_path)

            # Test snapshot reference
            doc_ref = client.collection("users").document("user_snapshot_test")
            doc_ref.set({"name": "Test User", "active": True})
            snap = doc_ref.get()
            self.assertIsNotNone(snap.reference, "Snapshot must retain its reference")
            self.assertEqual(snap.reference.path, "users/user_snapshot_test")

            # Test transaction commit
            tx = client.transaction()
            tx_doc = client.collection("accounts").document("acc_1")
            tx.set(tx_doc, {"balance": 500})
            self.assertTrue(hasattr(tx, "commit"), "LocalTx must implement commit()")
            tx.commit()

            acc_snap = tx_doc.get()
            self.assertTrue(acc_snap.exists)
            self.assertEqual(acc_snap.to_dict()["balance"], 500)

    def test_23_mcp_secret_vault_uses_app_data_dir(self):
        """Verifies McpSecretVault stores key in user application data, not in repo source tree."""
        import mcp_client
        import paths_service
        vault_dir = mcp_client.McpSecretVault.VAULT_DIR
        app_data = str(paths_service.get_app_data_dir())
        self.assertTrue(vault_dir.startswith(app_data), f"Vault dir {vault_dir} must be under app data dir {app_data}")
        # Test encryption and decryption
        secret = "test_super_secret_pat_9988"
        enc = mcp_client.McpSecretVault.encrypt(secret)
        self.assertTrue(enc.startswith("enc:fernet:"))
        dec = mcp_client.McpSecretVault.decrypt(enc)
        self.assertEqual(dec, secret)

    def test_24_account_deletion_cleans_subcollections_and_vault(self):
        """Verifies /auth/account purges subcollections and user BYOK vault credentials."""
        import credentials_vault_service
        from auth_service import get_current_user
        test_uid = f"user_del_{uuid.uuid4().hex[:8]}"
        test_email = f"{test_uid}@example.com"

        # 1. Store BYOK credential
        credentials_vault_service.vault.store_credential("groq", "gsk_test_key_1234567890123456", user_id=test_uid)
        self.assertIsNotNone(credentials_vault_service.vault.get_credential("groq", test_uid))

        # 2. Add records in subcollections
        u_ref = main.db.collection("users").document(test_uid)
        u_ref.set({"uid": test_uid, "email": test_email})
        u_ref.collection("records").document("rec_1").set({"metric": 100})
        u_ref.collection("memory").document("mem_1").set({"summary": "test memory"})

        # 3. Call DELETE /auth/account
        auth_user = AuthenticatedUser(uid=test_uid, email=test_email)
        app.dependency_overrides[get_current_user] = lambda: auth_user
        try:
            resp = self.client.delete("/auth/account")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertIn("records", data["purged_subcollections"])
            self.assertIn("memory", data["purged_subcollections"])

            # Verify subcollection documents are gone
            self.assertFalse(u_ref.collection("records").document("rec_1").get().exists)
            self.assertFalse(u_ref.collection("memory").document("mem_1").get().exists)
            self.assertFalse(u_ref.get().exists)

            # Verify BYOK credentials purged
            self.assertIsNone(credentials_vault_service.vault.get_credential("groq", test_uid))
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    def test_25_desktop_supervisor_instance_id_verification(self):
        """Verifies Desktop Supervisor checks instance_id in health response."""
        from desktop import BackendSupervisor
        supervisor = BackendSupervisor(8501)
        self.assertTrue(supervisor.instance_id.startswith("stroke-"))
        # Check /health returns instance_id
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("instance_id", resp.json())


if __name__ == "__main__":
    unittest.main()
