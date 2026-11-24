"""
Stroke AI // Firebase Authentication & Identity Engine Regression Test Suite
Validates the complete migration from custom OTP/Supabase to Firebase Authentication:
  1. Cryptographic token verification & rejection of forged/expired/invalid tokens.
  2. Endpoint authorization & rejection of unauthenticated requests (HTTP 401).
  3. Strict identity scoping (preventing caller-supplied email spoofing).
  4. Permanent deprecation of legacy OTP and switch-account endpoints (HTTP 410).
  5. Absence of guest bypasses and elimination of custom password stores.
"""

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
import jwt  # PyJWT for test token generation
import main
from main import app
import auth_service
from auth_service import (
    verify_firebase_id_token,
    get_current_user,
    AuthenticatedUser,
    get_firebase_project_id
)


class TestFirebaseAuthVerification(unittest.TestCase):
    """Audits cryptographic ID token validation and security boundaries."""

    def test_01_empty_and_malformed_tokens_rejected(self):
        """Tokens that are empty, non-string, or malformed must be rejected immediately."""
        with self.assertRaises(ValueError):
            verify_firebase_id_token("")

        with self.assertRaises(ValueError):
            verify_firebase_id_token("   ")

        with self.assertRaises(ValueError):
            verify_firebase_id_token("not-a-jwt-token")

        with self.assertRaises(ValueError):
            verify_firebase_id_token("abc.def.ghi")

    def test_02_forged_hmac_tokens_rejected(self):
        """Tokens forged with symmetric keys (HS256) instead of Google's RS256 must be rejected."""
        proj_id = get_firebase_project_id()
        payload = {
            "sub": "attacker_user_123",
            "email": "attacker@stroke.internal",
            "aud": proj_id,
            "iss": f"https://securetoken.google.com/{proj_id}",
            "exp": time.time() + 3600,
            "iat": time.time(),
        }
        forged_token = jwt.encode(payload, "forged_secret_key", algorithm="HS256")

        with self.assertRaises(ValueError) as ctx:
            verify_firebase_id_token(forged_token)
        self.assertIn("verification failed", str(ctx.exception).lower())

    def test_03_expired_tokens_rejected(self):
        """Tokens with expiration in the past must be rejected."""
        proj_id = get_firebase_project_id()
        expired_claims = {
            "sub": "user_456",
            "email": "developer@stroke.internal",
            "aud": proj_id,
            "iss": f"https://securetoken.google.com/{proj_id}",
            "exp": time.time() - 300,  # Expired 5 minutes ago
            "iat": time.time() - 3900,
        }

        # Mock the cryptographic verification layer to return decoded claims with expired timestamp
        with patch("google.oauth2.id_token.verify_firebase_token", return_value=expired_claims):
            with self.assertRaises(ValueError) as ctx:
                verify_firebase_id_token("mock.expired.token")
            self.assertIn("expired", str(ctx.exception).lower())

    def test_04_wrong_audience_project_id_rejected(self):
        """Tokens intended for a different Firebase project must be rejected."""
        wrong_aud_claims = {
            "sub": "user_789",
            "email": "developer@stroke.internal",
            "aud": "wrong-malicious-project-id",
            "iss": "https://securetoken.google.com/wrong-malicious-project-id",
            "exp": time.time() + 3600,
        }

        with patch("google.oauth2.id_token.verify_firebase_token", return_value=wrong_aud_claims):
            with self.assertRaises(ValueError) as ctx:
                verify_firebase_id_token("mock.wrong.aud.token")
            self.assertIn("audience mismatch", str(ctx.exception).lower())

    def test_05_missing_subject_uid_rejected(self):
        """Tokens without a valid non-empty subject (UID) must be rejected."""
        proj_id = get_firebase_project_id()
        missing_sub_claims = {
            "sub": "",
            "email": "developer@stroke.internal",
            "aud": proj_id,
            "iss": f"https://securetoken.google.com/{proj_id}",
            "exp": time.time() + 3600,
        }

        with patch("google.oauth2.id_token.verify_firebase_token", return_value=missing_sub_claims):
            with self.assertRaises(ValueError) as ctx:
                verify_firebase_id_token("mock.missing.sub.token")
            self.assertIn("missing valid subject", str(ctx.exception).lower())


class TestFirebaseAuthEndpoints(unittest.TestCase):
    """Audits HTTP authorization policies on FastAPI routes."""

    def setUp(self):
        self.client = TestClient(app)

    def test_01_unauthenticated_requests_return_401(self):
        """Endpoints requiring authentication must return HTTP 401 when Authorization header is missing."""
        protected_endpoints = [
            ("GET", "/auth/me"),
            ("POST", "/auth/session"),
            ("DELETE", "/auth/account"),
            ("GET", "/user/status"),
            ("GET", "/chats"),
            ("GET", "/memory/stats"),
            ("POST", "/memory/clear"),
            ("GET", "/auth/github-connect"),
            ("POST", "/github/token"),
            ("DELETE", "/github/token"),
            ("POST", "/auth/email-config"),
        ]

        for method, endpoint in protected_endpoints:
            if method == "GET":
                res = self.client.get(endpoint)
            elif method == "POST":
                res = self.client.post(endpoint, json={})
            elif method == "DELETE":
                res = self.client.delete(endpoint)
            self.assertEqual(
                res.status_code,
                401,
                f"Expected 401 Unauthorized for {method} {endpoint}, got {res.status_code}"
            )
            self.assertIn("Authentication required", res.json().get("detail", ""))

    def test_02_invalid_bearer_token_returns_401(self):
        """Providing an invalid Bearer token must return HTTP 401."""
        res = self.client.get("/auth/me", headers={"Authorization": "Bearer completely-invalid-token"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Unauthorized", res.json().get("detail", ""))

    def test_03_valid_firebase_token_authorizes_session(self):
        """Valid verified Firebase ID token must authenticate user and populate user claims."""
        proj_id = get_firebase_project_id()
        mock_claims = {
            "user_id": "firebase_verified_dev_01",
            "sub": "firebase_verified_dev_01",
            "email": "lead_developer@stroke.internal",
            "email_verified": True,
            "name": "Stroke Lead",
            "aud": proj_id,
            "iss": f"https://securetoken.google.com/{proj_id}",
            "exp": time.time() + 3600,
        }

        with patch("auth_service.verify_firebase_id_token", return_value=mock_claims):
            headers = {"Authorization": "Bearer mock-valid-firebase-id-token"}
            res = self.client.get("/auth/me", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["user"]["uid"], "firebase_verified_dev_01")
            self.assertEqual(data["user"]["email"], "lead_developer@stroke.internal")
            self.assertTrue(data["user"]["email_verified"])

            # Verify /auth/session endpoint
            res_sess = self.client.post("/auth/session", headers=headers)
            self.assertEqual(res_sess.status_code, 200)
            self.assertEqual(res_sess.json()["session_active"], True)
            self.assertEqual(res_sess.json()["uid"], "firebase_verified_dev_01")

    def test_04_user_identity_derived_from_token_not_caller_query(self):
        """User identity must be derived strictly from verified token, ignoring spoofed ?email= query params."""
        proj_id = get_firebase_project_id()
        mock_claims = {
            "user_id": "genuine_dev_uid",
            "sub": "genuine_dev_uid",
            "email": "genuine_dev@stroke.internal",
            "email_verified": True,
            "aud": proj_id,
            "iss": f"https://securetoken.google.com/{proj_id}",
            "exp": time.time() + 3600,
        }

        with patch("auth_service.verify_firebase_id_token", return_value=mock_claims):
            headers = {"Authorization": "Bearer mock-valid-firebase-id-token"}
            # Attacker attempts to spoof victim_admin's telemetry
            res = self.client.get("/user/status?email=victim_admin@stroke.internal", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            # The returned email must match the token's authenticated email, not the attacker's query param
            self.assertEqual(data["email"], "genuine_dev@stroke.internal")

    def test_05_legacy_endpoints_permanently_deprecated_410(self):
        """Custom OTP endpoints (/auth/send-otp, /auth/verify-otp, /auth/switch-account) must return HTTP 410 Gone."""
        res_send = self.client.post("/auth/send-otp", json={"email": "dev@test.internal"})
        self.assertEqual(res_send.status_code, 410)
        self.assertIn("migrated to Firebase Authentication", res_send.json()["detail"])

        res_verify = self.client.post("/auth/verify-otp", json={"email": "dev@test.internal", "otp_code": "123456"})
        self.assertEqual(res_verify.status_code, 410)
        self.assertIn("migrated to Firebase Authentication", res_verify.json()["detail"])

        res_switch = self.client.post("/auth/switch-account", json={"email": "dev@test.internal"})
        self.assertEqual(res_switch.status_code, 410)
        self.assertIn("migrated to Firebase Authentication", res_switch.json()["detail"])

    def test_06_auth_config_returns_public_metadata(self):
        """Public /auth/config endpoint returns project metadata without exposing secrets."""
        proj_id = get_firebase_project_id()
        res = self.client.get("/auth/config")
        self.assertEqual(res.status_code, 200)
        cfg = res.json()
        self.assertEqual(cfg["status"], "success")
        self.assertEqual(cfg["projectId"], proj_id)
        self.assertEqual(cfg["authDomain"], f"{proj_id}.firebaseapp.com")
        # Ensure no secret keys exist in config response
        self.assertNotIn("private_key", cfg)
        self.assertNotIn("client_secret", cfg)

    def test_07_no_custom_password_stores_in_memory(self):
        """Ensure _LOCAL_OTP_STORE and _AUTHENTICATED_IDENTITIES are absent from main.py."""
        self.assertFalse(hasattr(main, "_LOCAL_OTP_STORE"))
        self.assertFalse(hasattr(main, "_AUTHENTICATED_IDENTITIES"))
        self.assertFalse(hasattr(main, "_FAILED_OTP_ATTEMPTS"))
        self.assertFalse(hasattr(main, "hash_password"))
        self.assertFalse(hasattr(main, "verify_password"))


if __name__ == "__main__":
    unittest.main()
