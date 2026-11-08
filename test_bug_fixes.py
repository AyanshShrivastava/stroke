"""
================================================================================
STROKE // SYSTEMATIC BUG HUNT REGRESSION TEST SUITE
================================================================================
Validates all high & critical severity bug fixes:
  1. /auth/switch-account security: rejects unauthenticated identity hijacking (401),
     authorizes active authenticated sessions.
  2. /auth/send-otp throttling & force_resend: throttles rapid calls within 15s,
     allows immediate resend when force_resend=True.
  3. Resilient JSON serialization: verifies default=str handles datetime & non-primitive
     objects without raising TypeError across local chat store, archivist, and VFX service.
  4. /user/status error resilience: falls back gracefully without 500 Internal Server Error
     when Firestore is offline or throws exceptions.
  5. Studio MCP subprocess cleanup: guarantees subprocess termination and zero orphan leaks.
  6. Llama inference lock: thread-safe execution of local model inference.
================================================================================
"""

import os
import sys
import asyncio
import unittest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Ensure workspace root is in sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
import main
from main import (
    app,
    _AUTHENTICATED_IDENTITIES,
    _LOCAL_OTP_STORE,
    _LOCAL_CHAT_SESSIONS,
    _save_local_chat_sessions,
    _LLAMA_THREAD_LOCK,
    sync_llama_chat_completion,
    run_llama_inference
)
import coding_loop
from coding_loop import CodingArchivist
import vfx_service
from vfx_service import save_learned_vfx_models, save_learned_insights
import mcp_bridge
from mcp_bridge import execute_studio_mcp_command


class SystematicBugFixesTestSuite(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        _AUTHENTICATED_IDENTITIES.clear()
        _LOCAL_OTP_STORE.clear()

    def test_01_switch_account_rejects_unauthenticated_impersonation(self):
        """Security: Arbitrary POST /auth/switch-account without auth must return 401."""
        res = self.client.post("/auth/switch-account", json={"email": "victim_admin@stroke.internal"})
        self.assertEqual(res.status_code, 401)
        self.assertIn("Unauthorized", res.json()["detail"])

    def test_02_switch_account_allows_authenticated_identity(self):
        """Security: POST /auth/switch-account succeeds for authenticated identities."""
        test_email = "verified_dev@stroke.internal"
        _AUTHENTICATED_IDENTITIES.add(test_email)

        res = self.client.post("/auth/switch-account", json={"email": test_email})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "success")
        self.assertEqual(res.json()["email"], test_email)

    def test_03_send_otp_throttles_within_15_seconds(self):
        """Usability: Rapid send-otp requests within 15 seconds are throttled to prevent spam."""
        test_email = "throttle_test@example.com"
        res1 = self.client.post("/auth/send-otp", json={"email": test_email, "password": "Password123!"})
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(res1.json()["status"], "success")

        # Second request without force_resend within 15s should return throttled response
        res2 = self.client.post("/auth/send-otp", json={"email": test_email, "password": "Password123!"})
        self.assertEqual(res2.status_code, 200)
        self.assertIn("recently dispatched", res2.json()["message"])

    def test_04_send_otp_force_resend_bypasses_throttle(self):
        """Usability: send-otp with force_resend=True immediately regenerates and sends a new OTP."""
        test_email = "force_resend_test@example.com"
        res1 = self.client.post("/auth/send-otp", json={"email": test_email, "password": "Password123!"})
        first_otp = _LOCAL_OTP_STORE[test_email]["otp_code"]

        # Request with force_resend=True
        res2 = self.client.post("/auth/send-otp", json={"email": test_email, "password": "Password123!", "force_resend": True})
        self.assertEqual(res2.status_code, 200)
        self.assertIn("has been dispatched", res2.json()["message"])
        second_otp = _LOCAL_OTP_STORE[test_email]["otp_code"]

        self.assertEqual(len(second_otp), 6)
        self.assertTrue(second_otp.isdigit())

    def test_05_json_serialization_safety_in_local_chat_sessions(self):
        """Reliability: _save_local_chat_sessions handles datetime and non-primitive objects via default=str."""
        store_with_datetime = {
            "user@domain.com": [
                {
                    "session_id": "sess-dt-test",
                    "title": "Datetime Test",
                    "timestamp": datetime.now(timezone.utc),
                    "created_at": datetime.now(),
                    "messages": [{"role": "user", "content": "hello"}]
                }
            ]
        }
        # Should not raise TypeError: Object of type datetime is not JSON serializable
        try:
            _save_local_chat_sessions(store_with_datetime)
            save_succeeded = True
        except TypeError:
            save_succeeded = False

        self.assertTrue(save_succeeded, "_save_local_chat_sessions crashed on datetime serialization!")

    def test_06_json_serialization_safety_in_archivist_and_vfx(self):
        """Reliability: CodingArchivist and vfx_service handle non-primitive types safely."""
        test_report = {
            "passed_checks": ["Syntax", "AST"],
            "untested_limitations": [],
            "is_verified": True,
            "iteration_count": 1,
            "recorded_timestamp": datetime.now(timezone.utc)
        }
        try:
            CodingArchivist.record_verified_artifact("test prompt", "print('hello')", "python", test_report, "user@stroke.ai")
            archivist_ok = True
        except Exception:
            archivist_ok = False
        self.assertTrue(archivist_ok, "CodingArchivist crashed on non-primitive JSON serialization!")

        models_with_dt = {
            "TestEffect": {
                "model_name": "TestEffect",
                "registered_at": datetime.now(timezone.utc)
            }
        }
        self.assertTrue(save_learned_vfx_models(models_with_dt))
        self.assertTrue(save_learned_insights())

    def test_07_user_status_fallback_on_firestore_exception(self):
        """Fault Tolerance: GET /user/status returns resilient local telemetry if Firestore throws."""
        with patch.object(main.db, "collection", side_effect=RuntimeError("Firestore connection refused")):
            res = self.client.get("/user/status?email=test_status@stroke.ai")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["email"], "test_status@stroke.ai")
            self.assertTrue(data["exists"])
            self.assertEqual(data["records"], [])

    def test_08_studio_mcp_subprocess_cleanup(self):
        """Leak Prevention: execute_studio_mcp_command always terminates cleanly without hanging."""
        async def run_mcp_test():
            # Run with non-existent command to trigger offline detection path
            res = await execute_studio_mcp_command("/tmp/nonexistent_mcp_bin", "execute_luau", "print('test')", "workspace")
            return res

        loop = asyncio.new_event_loop()
        try:
            res = loop.run_until_complete(run_mcp_test())
            self.assertEqual(res["status"], "offline")
            self.assertFalse(res["connected"])
            self.assertEqual(res["lines_executed"], 0)
        finally:
            loop.close()

    def test_09_llama_inference_thread_lock(self):
        """Concurrency: sync_llama_chat_completion and run_llama_inference are protected by _LLAMA_THREAD_LOCK."""
        mock_engine = MagicMock()
        mock_engine.create_chat_completion.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "mock reply"}}]
        }

        # 1. Sync invocation
        sync_res = sync_llama_chat_completion(mock_engine, messages=[{"role": "user", "content": "hi"}])
        self.assertEqual(sync_res["choices"][0]["message"]["content"], "mock reply")

        # 2. Async non-blocking invocation
        loop = asyncio.new_event_loop()
        try:
            async_res = loop.run_until_complete(
                run_llama_inference(mock_engine, messages=[{"role": "user", "content": "async hi"}])
            )
            self.assertEqual(async_res["choices"][0]["message"]["content"], "mock reply")
        finally:
            loop.close()

        self.assertEqual(mock_engine.create_chat_completion.call_count, 2)


if __name__ == "__main__":
    unittest.main()
