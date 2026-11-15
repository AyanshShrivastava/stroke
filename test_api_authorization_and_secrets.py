"""
Stroke AI // API Authorization, OAuth & Secret Security Test Suite
Exhaustively audits route-level authorization, loopback boundaries, DNS rebinding,
CSRF, OAuth state integrity, fail-closed secrets, and injection protections.
"""

import os
import sys
import time
import json
import stat
import html
import urllib.parse
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"
os.environ["FIREBASE_PROJECT_ID"] = "stroke-test-matrix"

from fastapi.testclient import TestClient
import main
from main import (
    app,
    db,
    encrypt_token,
    decrypt_token,
    save_env_variable,
    _OAUTH_STATE_REGISTRY
)
import auth_service


class TestComprehensiveRouteAuthorization(unittest.TestCase):
    """Audits route-by-route access control policies across the entire API."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_claims = {
            "user_id": "verified_auth_user_1",
            "email": "verified@stroke.internal",
            "email_verified": True,
            "aud": "stroke-test-matrix",
            "iss": "https://securetoken.google.com/stroke-test-matrix",
            "exp": time.time() + 3600
        }
        self.auth_headers = {"Authorization": "Bearer mock-verified-token"}

    def test_01_all_sensitive_routes_require_authentication(self):
        """
        Comprehensive Audit: All sensitive endpoints must return HTTP 401
        when unauthenticated (missing Bearer token).
        """
        protected_endpoints = [
            ("GET", "/auth/email-config"),
            ("POST", "/auth/email-config", {"email_from": "test@stroke.ai"}),
            ("POST", "/database/feed-5x", {}),
            ("GET", "/database/mandatory-cache"),
            ("GET", "/mcp/servers"),
            ("POST", "/mcp/execute", {"tool_name": "test_tool", "arguments": {}}),
            ("POST", "/mcp/connect", {"server_id": "s1", "name": "n1", "url": "http://127.0.0.1:1234"}),
            ("POST", "/mcp/disconnect", {"server_id": "s1"}),
            ("GET", "/mcp/config"),
            ("POST", "/mcp/config", {"config": {}}),
            ("GET", "/mcp/tools"),
            ("POST", "/ai/notes/chat", {"prompt": "Write VFX script"}),
            ("POST", "/ai/search", {"query": "Roblox TweenService"}),
            ("GET", "/ai/status"),
            ("POST", "/ai/model/download", {}),
            ("POST", "/ai/model/pull", {"model": "llama3.2"}),
            ("GET", "/ai/model/weights-status"),
            ("POST", "/ai/model/download-weights", {}),
            ("GET", "/ai/learned-insights"),
            ("POST", "/ai/learn-from-chats", {"prompt": "p", "response": "r"}),
            ("POST", "/ai/refeed-with-learnings", {}),
            ("POST", "/ai/chat", {"messages": [{"role": "user", "content": "hi"}]}),
            ("POST", "/ai/verify-code", {"code": "print('hello')", "language": "luau"}),
            ("POST", "/terminal/create", {}),
            ("POST", "/terminal/run", {"command": "echo test"}),
            ("GET", "/terminal/list"),
            ("POST", "/fs/list", {"dir_path": "."}),
            ("POST", "/fs/read", {"file_path": "main.py"}),
            ("GET", "/workspace/list-approved"),
            ("GET", "/backups/history"),
            ("GET", "/models/status"),
            ("GET", "/system/elevation-status"),
            ("GET", "/system/paths"),
        ]

        for item in protected_endpoints:
            method = item[0]
            endpoint = item[1]
            body = item[2] if len(item) > 2 else None

            if method == "GET":
                res = self.client.get(endpoint)
            elif method == "POST":
                res = self.client.post(endpoint, json=body or {})
            elif method == "DELETE":
                res = self.client.delete(endpoint)

            self.assertEqual(
                res.status_code,
                401,
                f"Expected HTTP 401 for unauthenticated {method} {endpoint}, got {res.status_code}"
            )
            self.assertIn("Authentication required", res.json().get("detail", ""))

    def test_02_zero_trust_loopback_blocks_unauthenticated_terminal(self):
        """
        Zero Trust Loopback: Loopback IP alone is NOT authentication.
        Terminal operations from 127.0.0.1 must be rejected without token.
        """
        # Connection from localhost without credentials must be rejected
        res = self.client.post("/terminal/create", json={})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Authentication required", res.json()["detail"])

        # Connection with internal daemon secret must be authorized
        with patch.dict(os.environ, {"STROKE_INTERNAL_SECRET": "agent_secret_abc999"}):
            headers = {"X-Internal-Token": "agent_secret_abc999"}
            res_auth = self.client.get("/terminal/list", headers=headers)
            self.assertEqual(res_auth.status_code, 200)

        # Connection with verified Firebase user token must be authorized
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            res_user = self.client.get("/terminal/list", headers=self.auth_headers)
            self.assertEqual(res_user.status_code, 200)

    def test_03_mcp_execute_derives_identity_from_token_not_payload(self):
        """
        Privilege Escalation Defense: /mcp/execute looks up github_token using verified UID,
        ignoring any caller-supplied spoofed email payload.
        """
        # Set victim's github token
        victim_email = "victim@stroke.ai"
        db.collection("users").document(victim_email).set({
            "email": victim_email,
            "github_token": encrypt_token("ghp_victim_secret_token_123")
        })

        # Set attacker's document (without github token)
        attacker_uid = self.mock_claims["user_id"]
        db.collection("users").document(attacker_uid).set({
            "uid": attacker_uid,
            "github_token": None
        })

        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            with patch("mcp_bridge.execute_mcp_tool") as mock_exec:
                mock_exec.return_value = {"status": "success"}
                # Attacker tries to supply victim's email to steal victim's PAT
                payload = {
                    "tool_name": "github_create_issue",
                    "arguments": {"repo": "test", "title": "test"},
                    "email": victim_email
                }
                res = self.client.post("/mcp/execute", json=payload, headers=self.auth_headers)
                self.assertEqual(res.status_code, 200)

                # The token passed to execute_mcp_tool MUST be None (from attacker's UID), NOT victim's PAT!
                call_args = mock_exec.call_args[0]
                passed_token = call_args[2]
                self.assertIsNone(passed_token, "Attacker successfully hijacked victim's GitHub PAT!")


class TestDnsRebindingAndCsrfProtection(unittest.TestCase):
    """Audits Host header validation, DNS rebinding defenses, and CSRF Origin checks."""

    def setUp(self):
        self.client = TestClient(app)

    def test_04_dns_rebinding_untrusted_host_rejected(self):
        """
        DNS Rebinding Protection: Requests with external or malicious Host headers
        must be rejected with HTTP 400.
        """
        res = self.client.get("/", headers={"Host": "evil-attacker.com"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("DNS rebinding protection", res.json()["detail"])

        res2 = self.client.get("/auth/config", headers={"Host": "rebinder.local.attacker.org"})
        self.assertEqual(res2.status_code, 400)

    def test_05_csrf_untrusted_origin_rejected_on_state_change(self):
        """
        CSRF Protection: POST/PUT/DELETE requests with untrusted Origin headers
        must be rejected with HTTP 403 Forbidden.
        """
        res = self.client.post(
            "/auth/send-otp",
            json={"email": "dev@stroke.ai"},
            headers={"Origin": "https://malicious-website.com"}
        )
        self.assertEqual(res.status_code, 403)
        self.assertIn("Cross-origin request rejected", res.json()["detail"])

    def test_06_legitimate_local_origins_accepted(self):
        """
        Legitimate local origins (localhost:8501, localhost:3000, tauri://localhost) are accepted.
        """
        res = self.client.get("/", headers={"Host": "localhost:8501"})
        self.assertEqual(res.status_code, 200)

        # Pre-flight OPTIONS request
        res_opt = self.client.options(
            "/auth/config",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET"
            }
        )
        self.assertIn(res_opt.status_code, (200, 204))


class TestGitHubOAuthSecurity(unittest.TestCase):
    """Audits GitHub OAuth state integrity, fail-closed configuration, XSS, and postMessage safety."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_claims = {
            "user_id": "oauth_dev_user_42",
            "email": "dev_oauth@stroke.ai",
            "email_verified": True,
            "aud": "stroke-test-matrix",
            "iss": "https://securetoken.google.com/stroke-test-matrix",
            "exp": time.time() + 3600
        }
        self.auth_headers = {"Authorization": "Bearer mock-token-oauth"}

    def test_07_oauth_fails_closed_when_unconfigured(self):
        """
        Fail Closed: If GITHUB_CLIENT_ID or GITHUB_CLIENT_SECRET is missing,
        /auth/github-connect must return HTTP 503.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            with patch("main.GITHUB_CLIENT_ID", ""):
                with patch("main.GITHUB_CLIENT_SECRET", ""):
                    res = self.client.get("/auth/github-connect", headers=self.auth_headers)
                    self.assertEqual(res.status_code, 503)
                    self.assertIn("GitHub OAuth is not configured", res.json()["detail"])

    def test_08_oauth_state_tied_to_uid_and_consumed_atomically(self):
        """
        State Security:
        1. State token binds to user UID.
        2. Replay attack fails on second callback.
        """
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_claims):
            with patch("main.GITHUB_CLIENT_ID", "Ov23validclientid"):
                with patch("main.GITHUB_CLIENT_SECRET", "valid_secret_123"):
                    # 1. Initiate OAuth
                    res = self.client.get("/auth/github-connect", headers=self.auth_headers, follow_redirects=False)
                    self.assertEqual(res.status_code, 307)
                    redirect_url = res.headers["Location"]
                    self.assertIn("https://github.com/login/oauth/authorize", redirect_url)

                    # Extract state
                    import urllib.parse
                    parsed = urllib.parse.urlparse(redirect_url)
                    query_params = urllib.parse.parse_qs(parsed.query)
                    state_token = query_params["state"][0]

                    # Verify state contains user UID
                    self.assertIn(self.mock_claims["user_id"], state_token)
                    self.assertIn(state_token, _OAUTH_STATE_REGISTRY)

                    # 2. Simulate valid callback exchange
                    with patch("httpx.AsyncClient.post") as mock_post:
                        mock_resp = MagicMock()
                        mock_resp.json.return_value = {"access_token": "ghp_mock_live_token_456"}
                        mock_post.return_value = mock_resp

                        cb_res = self.client.get(f"/auth/github/callback?code=valid_code&state={state_token}")
                        self.assertEqual(cb_res.status_code, 200)

                        # 3. Replay attack with same state must fail with HTTP 400
                        replay_res = self.client.get(f"/auth/github/callback?code=valid_code&state={state_token}")
                        self.assertEqual(replay_res.status_code, 400)
                        self.assertIn("Compromised, unrecognized, or missing", replay_res.json()["detail"])

    def test_09_oauth_callback_xss_prevention(self):
        """
        XSS Defense: Injected script tags in error_description are HTML-escaped
        and never executed as raw markup.
        """
        xss_payload = "<script>alert('XSS_ATTACK')</script><img src=x onerror=alert(1)>"
        res = self.client.get(f"/auth/github/callback?error=access_denied&error_description={urllib.parse.quote(xss_payload)}")
        self.assertEqual(res.status_code, 400)
        self.assertNotIn("<script>alert('XSS_ATTACK')</script>", res.text)
        self.assertIn(html.escape(xss_payload), res.text)

    def test_10_postmessage_origin_safety_and_no_token_preview(self):
        """
        Origin Safety: Callback bridge never uses postMessage with '*',
        and never leaks token previews.
        """
        test_state = "STRK_test_uid_9999_nonce"
        _OAUTH_STATE_REGISTRY[test_state] = {
            "uid": "test_uid_9999",
            "email": "test@stroke.ai",
            "origin": "http://localhost:3000",
            "expires_at": time.time() + 600
        }

        with patch("main.GITHUB_CLIENT_ID", "Ov23validclientid"):
            with patch("main.GITHUB_CLIENT_SECRET", "valid_secret_123"):
                with patch("httpx.AsyncClient.post") as mock_post:
                    mock_resp = MagicMock()
                    mock_resp.json.return_value = {"access_token": "ghp_secret_access_token_super_private"}
                    mock_post.return_value = mock_resp

                    res = self.client.get(f"/auth/github/callback?code=valid_code&state={test_state}")
                    self.assertEqual(res.status_code, 200)

                    # Verify exact origin used in postMessage
                    self.assertIn('"http://localhost:3000"', res.text)
                    self.assertNotIn("'*'", res.text)

                    # Verify zero token previews in HTML response
                    self.assertNotIn("ghp_secret", res.text)
                    self.assertNotIn("token_preview", res.text)


class TestSecretManagementAndEncryption(unittest.TestCase):
    """Audits fail-closed encryption, safe .env persistence, and control-character rejection."""

    def test_11_encrypt_token_fails_closed(self):
        """
        Fail Closed Encryption: If cipher encryption fails, raises RuntimeError
        and never returns raw plaintext.
        """
        with patch.object(main._FERNET, "encrypt", side_effect=Exception("Cryptographic failure")):
            with self.assertRaises(RuntimeError) as ctx:
                encrypt_token("sensitive_token_payload")
            self.assertIn("refusing to store unencrypted credential", str(ctx.exception))

    def test_12_decrypt_token_fails_closed(self):
        """
        Fail Closed Decryption: If decryption fails, returns None and never returns raw ciphertext.
        """
        with patch.object(main._FERNET, "decrypt", side_effect=Exception("Corrupted ciphertext")):
            result = decrypt_token("gAAAAABmockCiphertext==")
            self.assertIsNone(result)

    def test_13_env_newline_injection_rejected(self):
        """
        Injection Defense: save_env_variable rejects newlines, null bytes, or delimiters in keys/values.
        """
        with self.assertRaises(ValueError):
            save_env_variable("RESEND_API_KEY", "valid_key\nINJECTED_VAR=hacked")

        with self.assertRaises(ValueError):
            save_env_variable("KEY\r\nEVIL", "val")

        with self.assertRaises(ValueError):
            save_env_variable("KEY=INJECT", "val")

    def test_14_env_file_has_restrictive_permissions(self):
        """
        Credential Protection: .env file created by save_env_variable must have 0600 permissions.
        """
        test_key = "STROKE_TEST_SECURITY_KEY"
        test_val = "stroke_sec_val_999"
        save_env_variable(test_key, test_val)

        env_path = os.path.join(ROOT_DIR, ".env")
        self.assertTrue(os.path.exists(env_path))
        file_mode = stat.S_IMODE(os.stat(env_path).st_mode)
        self.assertEqual(file_mode, 0o600, f"Expected 0600 permissions on .env, got {oct(file_mode)}")


if __name__ == "__main__":
    unittest.main()
