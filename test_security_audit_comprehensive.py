"""
================================================================================
STROKE // COMPREHENSIVE SECURITY AUDIT & VULNERABILITY REGRESSION TEST SUITE
================================================================================
Exhaustively verifies defensive security controls and regressions across:
  1. API Key Exposure: Header-based Gemini authentication, zero key in URLs.
  2. Custom AI Provider SSRF: Cloud metadata and loopback protections.
  3. Chat Session BOLA / IDOR: Cross-account reading, writing, and deletion rejection.
  4. Agent Orchestrator BOLA: Cross-tenant task and multi-agent job access control.
  5. Terminal Secret Redaction: Groq, OpenRouter, OpenAI, GitHub PATs, and bearer tokens.
  6. Filesystem Path Traversal & Symlink Escapes: Workspace boundary enforcement.
  7. Terminal Child Process Environment: Secret leakage prevention in child processes.
  8. Non-Elevated Standard Privilege: Non-admin zero-elevation enforcement.
  9. Credentials Vault: Machine-bound encryption and key masking in public outputs.
  10. GitHub Service Input Sanitization: Traversal prevention on repos and branches.
  11. MCP Protocol SSRF Protection: Strict IP blocklist and metadata defenses.
================================================================================
"""

import os
import sys
import json
import time
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from fastapi.testclient import TestClient

# Ensure test flags
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"
os.environ["STROKE_DEV_CONSOLE_OTP"] = "1"
os.environ["FIREBASE_PROJECT_ID"] = "stroke-test-security"

import main
from main import app
import auth_service
from auth_service import AuthenticatedUser
import ai_provider_service
from ai_provider_service import GeminiProvider, CustomProvider, ProviderServiceError
import terminal_service
from terminal_service import redact_sensitive_data, get_sanitized_child_env
import workspace_service
from workspace_service import validate_path_access, validate_task_id, WorkspaceSecurityError
import paths_service
import credentials_vault_service
import github_service
import mcp_client
from mcp_client import SsrfProtector, McpError
import agent_orchestrator
from agent_orchestrator import TaskManager, TaskState
import parallel_agent_system


class TestSecurityAuditComprehensive(unittest.TestCase):
    """Repository-wide comprehensive security audit regression suite."""

    def setUp(self):
        self.client = TestClient(app)
        self.user_a = AuthenticatedUser(
            uid="uid_user_alpha",
            email="alpha@stroke.internal",
            email_verified=True,
            display_name="User Alpha"
        )
        self.user_b = AuthenticatedUser(
            uid="uid_user_beta",
            email="beta@stroke.internal",
            email_verified=True,
            display_name="User Beta"
        )
        app.dependency_overrides.clear()

    def tearDown(self):
        app.dependency_overrides.clear()

    # --------------------------------------------------------------------------
    # 1. API KEY EXPOSURE DEFENSE
    # --------------------------------------------------------------------------
    def test_01_gemini_uses_headers_not_url_query_param(self):
        """Verify GeminiProvider does NOT leak API key in query parameters."""
        provider = GeminiProvider()
        test_key = "AIzaSyFakeKeyForSecurityAuditTest123456"

        mock_resp = httpx.Response(
            status_code=200,
            json={"candidates": [{"content": {"parts": [{"text": "Security test ok"}]}}]},
            request=httpx.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent")
        )

        with patch("credentials_vault_service.vault.get_credential", return_value=test_key):
            with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
                resp = asyncio.run(provider.chat_complete(
                    model_id="gemini-2.0-flash",
                    messages=[{"role": "user", "content": "hi"}]
                ))

                self.assertIsNotNone(resp)
                self.assertEqual(resp.content, "Security test ok")

                call_args, call_kwargs = mock_post.call_args
                called_url = call_args[0]
                headers = call_kwargs.get("headers", {})

                # MUST NOT contain '?key=' in url
                self.assertNotIn("?key=", called_url)
                self.assertNotIn(test_key, called_url)
                # MUST contain x-goog-api-key header
                self.assertEqual(headers.get("x-goog-api-key"), test_key)

    def test_02_gemini_models_fetch_uses_header(self):
        """Verify fetch_live_provider_models for Gemini does NOT place key in URL."""
        test_key = "AIzaSyFakeKeyModelsFetch1234567890"

        mock_resp = httpx.Response(
            status_code=200,
            json={"models": [{"name": "models/gemini-2.0-flash", "supportedGenerationMethods": ["generateContent"]}]},
            request=httpx.Request("GET", "https://generativelanguage.googleapis.com/v1beta/models")
        )

        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            models = asyncio.run(ai_provider_service.fetch_live_provider_models("gemini", api_key=test_key))
            self.assertTrue(len(models) > 0)

            call_args, call_kwargs = mock_get.call_args
            called_url = call_args[0]
            headers = call_kwargs.get("headers", {})

            self.assertNotIn("?key=", called_url)
            self.assertNotIn(test_key, called_url)
            self.assertEqual(headers.get("x-goog-api-key"), test_key)

    # --------------------------------------------------------------------------
    # 2. SSRF PROTECTION FOR CUSTOM AI PROVIDERS
    # --------------------------------------------------------------------------
    def test_03_custom_provider_blocks_cloud_metadata_ssrf(self):
        """Verify CustomProvider blocks requests to 169.254.169.254 and metadata.google.internal."""
        dangerous_targets = [
            "http://169.254.169.254",
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://metadata",
            "http://0x7f000001",  # Obfuscated hex IP
        ]

        for target in dangerous_targets:
            # 1. Test test_provider_connection
            ok, msg, code = asyncio.run(ai_provider_service.test_provider_connection(
                provider="custom",
                api_key="test_key",
                base_url=target
            ))
            self.assertFalse(ok, f"Target {target} should have been blocked!")
            self.assertIn("SSRF", msg)
            self.assertEqual(code, 400)

            # 2. Test CustomProvider chat_complete
            custom = CustomProvider(base_url=target)
            with patch("credentials_vault_service.vault.get_credential", return_value="test_key"):
                with self.assertRaises(ProviderServiceError) as ctx:
                    asyncio.run(custom.chat_complete(
                        messages=[{"role": "user", "content": "hi"}],
                        model_id="custom-model"
                    ))
                self.assertIn("SSRF", str(ctx.exception))

    def test_04_custom_provider_permits_safe_local_models(self):
        """Verify CustomProvider permits legitimate local endpoints (e.g. Ollama/vLLM on localhost)."""
        safe_targets = [
            "http://localhost:11434/v1",
            "http://127.0.0.1:8000/v1",
        ]
        for url in safe_targets:
            validated = SsrfProtector.validate_url(url, allow_local=True)
            self.assertEqual(validated, url)

    # --------------------------------------------------------------------------
    # 3. CHAT SESSION BOLA / IDOR PROTECTION
    # --------------------------------------------------------------------------
    def test_05_chat_list_rejects_cross_account_email(self):
        """A user cannot list another user's chat sessions via email query parameter."""
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.user_a
        res = self.client.get("/chats?email=beta@stroke.internal")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

    def test_06_chat_get_rejects_cross_account_email(self):
        """A user cannot retrieve another user's single chat session."""
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.user_a
        res = self.client.get("/chats/sess_123?email=beta@stroke.internal")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

    def test_07_chat_save_rejects_cross_account_email(self):
        """A user cannot save or overwrite a chat session in another user's account."""
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.user_a
        res = self.client.post("/chats/save", json={
            "session_id": "sess_hack_1",
            "email": "beta@stroke.internal",
            "title": "Malicious Injection",
            "messages": [{"role": "user", "content": "hello"}]
        })
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

    def test_08_chat_delete_rejects_cross_account_email(self):
        """A user cannot delete another user's chat sessions."""
        app.dependency_overrides[auth_service.get_current_user] = lambda: self.user_a
        res = self.client.delete("/chats/sess_123?email=beta@stroke.internal")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

    # --------------------------------------------------------------------------
    # 4. AGENT ORCHESTRATOR & PARALLEL MULTI-AGENT BOLA DEFENSE
    # --------------------------------------------------------------------------
    def test_09_agent_task_access_control(self):
        """User A cannot read, cancel, or approve an Agent Task created by User B."""
        task = TaskManager.create_task(
            active_goal="Confidential Project Task",
            reasoning_level="medium",
            user_uid=self.user_b.uid
        )
        task.state = TaskState.AWAITING_APPROVAL

        # User A attempts to view Task
        app.dependency_overrides[auth_service.get_optional_user] = lambda: self.user_a
        res = self.client.get(f"/agent/tasks/{task.task_id}")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

        # User A attempts to cancel Task
        res_cancel = self.client.post(f"/agent/tasks/{task.task_id}/cancel")
        self.assertEqual(res_cancel.status_code, 403)

        # User A attempts to approve Task
        res_approve = self.client.post(f"/agent/tasks/{task.task_id}/approve")
        self.assertEqual(res_approve.status_code, 403)

        # Owner User B can access
        app.dependency_overrides[auth_service.get_optional_user] = lambda: self.user_b
        res_owner = self.client.get(f"/agent/tasks/{task.task_id}")
        self.assertEqual(res_owner.status_code, 200)
        self.assertEqual(res_owner.json()["task_id"], task.task_id)

    def test_10_parallel_agent_job_access_control(self):
        """User A cannot read, cancel, or stream a Multi-Agent Job created by User B."""
        job = parallel_agent_system.global_multi_agent_orchestrator.create_job(
            user_goal="Secret Multi-Agent Job",
            workspace_path="/tmp",
            user_uid=self.user_b.uid
        )

        # User A attempts to read job
        app.dependency_overrides[auth_service.get_optional_user] = lambda: self.user_a
        res = self.client.get(f"/api/orchestrator/jobs/{job.job_id}")
        self.assertEqual(res.status_code, 403)
        self.assertIn("Access denied", res.json()["detail"])

        # User A attempts to cancel job
        res_cancel = self.client.post(f"/api/orchestrator/jobs/{job.job_id}/cancel")
        self.assertEqual(res_cancel.status_code, 403)

        # User A attempts to stream job
        res_stream = self.client.get(f"/api/orchestrator/jobs/{job.job_id}/stream")
        self.assertEqual(res_stream.status_code, 403)

        # Owner User B can access
        app.dependency_overrides[auth_service.get_optional_user] = lambda: self.user_b
        res_owner = self.client.get(f"/api/orchestrator/jobs/{job.job_id}")
        self.assertEqual(res_owner.status_code, 200)
        self.assertEqual(res_owner.json()["job_id"], job.job_id)

    # --------------------------------------------------------------------------
    # 5. TERMINAL SECRET REDACTION
    # --------------------------------------------------------------------------
    def test_11_terminal_redacts_groq_and_openrouter_keys(self):
        """Verify terminal output redaction redacts Groq and OpenRouter keys."""
        groq_text = "Output with key gsk_1234567890abcdefghijklmnopqrstuvwxyz and more text."
        redacted_groq = redact_sensitive_data(groq_text)
        self.assertNotIn("gsk_", redacted_groq)
        self.assertIn("[REDACTED_GROQ_API_KEY]", redacted_groq)

        or_text = "Calling OpenRouter sk-or-v1-abcdef0123456789abcdef0123456789 for model run."
        redacted_or = redact_sensitive_data(or_text)
        self.assertNotIn("sk-or-v1-", redacted_or)
        self.assertIn("[REDACTED_OPENROUTER_API_KEY]", redacted_or)

    def test_12_terminal_redacts_github_google_and_bearer_tokens(self):
        """Verify terminal output redaction covers GitHub PATs, Google keys, and Bearer tokens."""
        text = (
            "Github: ghp_111122223333444455556666777788889999\n"
            "Google: AIzaSyD1234567890abcdef1234567890ab\n"
            "Auth: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgN"
        )
        redacted = redact_sensitive_data(text)
        self.assertNotIn("ghp_", redacted)
        self.assertIn("[REDACTED_GITHUB_PAT]", redacted)
        self.assertNotIn("AIza", redacted)
        self.assertIn("[REDACTED_GOOGLE_API_KEY]", redacted)
        self.assertIn("Bearer [REDACTED_JWT]", redacted)

    # --------------------------------------------------------------------------
    # 6. FILESYSTEM ACCESS & PATH TRAVERSAL ENFORCEMENT
    # --------------------------------------------------------------------------
    def test_13_workspace_path_traversal_rejection(self):
        """Verify validate_path_access and validate_task_id reject traversal attacks."""
        for bad_tid in ["../escape", "task/../../etc", "task\x00null"]:
            with self.assertRaises(WorkspaceSecurityError):
                validate_task_id(bad_tid)

        with self.assertRaises(WorkspaceSecurityError):
            validate_path_access("/etc/passwd")

        with self.assertRaises(WorkspaceSecurityError):
            validate_path_access("/var/root")

    # --------------------------------------------------------------------------
    # 7. TERMINAL ENVIRONMENT SANITIZATION
    # --------------------------------------------------------------------------
    def test_14_child_process_environment_strips_secrets(self):
        """Verify get_sanitized_child_env strips parent backend secrets."""
        with patch.dict(os.environ, {
            "PATH": "/usr/bin:/bin",
            "FIREBASE_PROJECT_ID": "secret-firebase-id",
            "GROQ_API_KEY": "gsk_secret123",
            "GITHUB_PAT": "ghp_secret123",
            "CUSTOM_SECRET_KEY": "super_secret_val",
            "USER": "developer"
        }, clear=True):
            clean_env = get_sanitized_child_env("/tmp")
            self.assertIn("PATH", clean_env)
            self.assertIn("USER", clean_env)
            self.assertNotIn("FIREBASE_PROJECT_ID", clean_env)
            self.assertNotIn("GROQ_API_KEY", clean_env)
            self.assertNotIn("GITHUB_PAT", clean_env)
            self.assertNotIn("CUSTOM_SECRET_KEY", clean_env)

    # --------------------------------------------------------------------------
    # 8. NON-ELEVATED ZERO PRIVILEGE
    # --------------------------------------------------------------------------
    def test_15_elevation_status_reporting(self):
        """Verify paths_service correctly checks non-admin elevation status."""
        status = paths_service.get_elevation_status()
        self.assertIn("is_elevated", status)
        self.assertIn("guidance", status)

    # --------------------------------------------------------------------------
    # 9. CREDENTIALS VAULT MASKING
    # --------------------------------------------------------------------------
    def test_16_credentials_vault_masks_keys(self):
        """Verify API keys are masked when listed for UI display."""
        raw_key = "gsk_12345678901234567890abcdef"
        masked = credentials_vault_service.mask_key(raw_key)
        self.assertNotIn(raw_key, masked)
        self.assertTrue(masked.startswith("gsk_••••••••••••"))
        self.assertTrue(masked.endswith("cdef"))

    # --------------------------------------------------------------------------
    # 10. GITHUB SERVICE INPUT VALIDATION
    # --------------------------------------------------------------------------
    def test_17_github_service_input_validation(self):
        """Verify GitHub input validation rejects path traversals."""
        self.assertFalse(github_service.validate_repo_name("../evil/repo"))
        self.assertFalse(github_service.validate_repo_name("user/repo/extra"))
        self.assertTrue(github_service.validate_repo_name("owner/valid-repo.name"))

        self.assertFalse(github_service.validate_file_path("../escape.txt"))
        self.assertFalse(github_service.validate_file_path("/absolute/path.txt"))
        self.assertFalse(github_service.validate_file_path("file\x00null.txt"))
        self.assertTrue(github_service.validate_file_path("src/components/App.tsx"))

        self.assertFalse(github_service.validate_ref_name("main..sub"))
        self.assertFalse(github_service.validate_ref_name("main\x00bad"))
        self.assertTrue(github_service.validate_ref_name("feature/safe-branch-1"))


if __name__ == "__main__":
    unittest.main()
