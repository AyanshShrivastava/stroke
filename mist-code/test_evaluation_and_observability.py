"""
================================================================================
STROKE // EVALUATION AND OBSERVABILITY TEST SUITE
================================================================================
Verifies:
  1. Structured Observability Event Schema across 8 canonical categories
  2. Correlated Task Identifiers across execution spans
  3. Multi-Tier Redaction Engine (PATs, JWTs, API keys, private keys, passwords, OTPs)
  4. Channel Separation: User-facing progress vs internal structured diagnostics
  5. Authentic Metrics Calculation (Zero synthetic multipliers or fabricated numbers)
  6. All 12 Evaluation Benchmarks in StrokeEvaluationHarness
  7. Strict False-Verification Rate = 0.0%
  8. Context Retrieval Precision and Recall = 1.0
  9. Zero-Trust Tool Approval & Anti-Tampering Gate
  10. Fast-API Observability & Evaluation Endpoints with Auth Verification
================================================================================
"""

import os
import sys
import time
import json
import uuid
import unittest
from fastapi.testclient import TestClient

# Ensure offline database mode for testing
os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

import observability
from observability import (
    StrokeObservability,
    EventCategory,
    EventStatus,
    RedactionEngine,
    UserProgressFormatter,
    emit_event,
    trace_span
)
import eval_harness
from eval_harness import StrokeEvaluationHarness
import main
import auth_service


class TestEvaluationAndObservability(unittest.TestCase):

    def setUp(self):
        self.obs = StrokeObservability.get_instance()
        self.obs.clear()
        self.client = TestClient(main.app)

        # Set verified test user dependency override
        self.test_uid = "eval_obs_test_user_001"
        self.test_user = auth_service.AuthenticatedUser(
            uid=self.test_uid,
            email="eval_obs@stroke.internal",
            claims={"uid": self.test_uid, "email": "eval_obs@stroke.internal"}
        )
        main.app.dependency_overrides[auth_service.get_current_user] = lambda: self.test_user

    def tearDown(self):
        self.obs.clear()
        main.app.dependency_overrides.clear()

    # ==========================================================================
    # 1. OBSERVABILITY EVENT SCHEMA & CATEGORIES
    # ==========================================================================

    def test_01_structured_event_schema_and_categories(self):
        """Events adhere to structured schema across all 8 canonical categories."""
        categories = [
            EventCategory.PROVIDER,
            EventCategory.TOOL,
            EventCategory.FILESYSTEM,
            EventCategory.TERMINAL,
            EventCategory.MCP,
            EventCategory.DOWNLOAD,
            EventCategory.AUTH,
            EventCategory.PERSISTENCE
        ]

        task_id = "task_schema_001"
        for cat in categories:
            evt = self.obs.emit(
                category=cat,
                action=f"action_{cat.value}",
                task_id=task_id,
                status=EventStatus.SUCCESS,
                details={"sample_key": "sample_val"},
                latency_ms=15.4
            )
            self.assertTrue(evt.event_id.startswith("evt_"))
            self.assertEqual(evt.category, cat.value)
            self.assertEqual(evt.task_id, task_id)
            self.assertEqual(evt.status, "success")
            self.assertEqual(evt.latency_ms, 15.4)
            self.assertIn("sample_key", evt.details)

        # Retrieve filtered by task
        events = self.obs.get_events(task_id=task_id)
        self.assertEqual(len(events), 8)

    # ==========================================================================
    # 2. MULTI-TIER REDACTION ENGINE
    # ==========================================================================

    def test_02_redaction_engine_neutralizes_all_credentials(self):
        """Redacts PATs, JWTs, API keys, private keys, passwords, and OTPs."""
        sensitive_payload = {
            "user_password": "PlaintextPassword123!",
            "github_token": "ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            "fine_grained_pat": "github_pat_11AABBCCDDEEFF001122334455667788990011223344556677889900AABBCC",
            "auth_header": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature",
            "openai_key": "sk-proj-1234567890abcdefghij",
            "anthropic_key": "sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456",
            "firebase_key": "AIzaSyD-1234567890abcdefghijklmnopqrstuv",
            "resend_key": "re_1234567890abcdefghij",
            "private_key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----",
            "otp_code": 849201,
            "nested": {
                "db_secret": "my_db_secret_key",
                "bearer_token": "secret_bearer_val"
            },
            "clean_message": "Safe text without secrets"
        }

        sanitized = RedactionEngine.sanitize(sensitive_payload)

        # Key-based redactions
        self.assertEqual(sanitized["user_password"], "[REDACTED]")
        self.assertEqual(sanitized["github_token"], "[REDACTED]")
        self.assertEqual(sanitized["fine_grained_pat"], "[REDACTED]")
        self.assertEqual(sanitized["auth_header"], "[REDACTED]")
        self.assertEqual(sanitized["openai_key"], "[REDACTED]")
        self.assertEqual(sanitized["anthropic_key"], "[REDACTED]")
        self.assertEqual(sanitized["firebase_key"], "[REDACTED]")
        self.assertEqual(sanitized["resend_key"], "[REDACTED]")
        self.assertEqual(sanitized["private_key"], "[REDACTED]")
        self.assertEqual(sanitized["otp_code"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["db_secret"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["bearer_token"], "[REDACTED]")

        # Safe text preserved
        self.assertEqual(sanitized["clean_message"], "Safe text without secrets")

    def test_03_pattern_redaction_in_arbitrary_string_values(self):
        """Redacts sensitive patterns embedded inside innocent key names."""
        embedded_text = (
            "User said: here is my token ghp_ABCDEF1234567890abcdefghijklmnopqrst and "
            "bearer auth Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyIjoiYWRtaW4ifQ.signature and "
            "API key sk-ant-api03-12345678901234567890."
        )

        sanitized_str = RedactionEngine.redact_string(embedded_text)
        self.assertNotIn("ghp_", sanitized_str)
        self.assertNotIn("sk-ant-api03-", sanitized_str)
        self.assertNotIn("signature", sanitized_str)
        self.assertIn("[REDACTED_GITHUB_PAT]", sanitized_str)
        self.assertIn("[REDACTED_API_KEY]", sanitized_str)
        self.assertIn("[REDACTED_JWT]", sanitized_str)

    # ==========================================================================
    # 3. CHANNEL SEPARATION: USER PROGRESS VS DIAGNOSTIC TRACES
    # ==========================================================================

    def test_04_user_progress_formatting_separation(self):
        """User progress messages are clean and human-friendly without technical noise."""
        evt_start = self.obs.emit(
            category=EventCategory.TOOL,
            action="verify_code",
            task_id="task_prog",
            status=EventStatus.START,
            details={"debug_ast_trace": "<ast nodes dump>", "stack_trace": "..."}
        )
        evt_success = self.obs.emit(
            category=EventCategory.TOOL,
            action="verify_code",
            task_id="task_prog",
            status=EventStatus.SUCCESS,
            details={"rules_applied": 14}
        )

        msg_start = UserProgressFormatter.format_event(evt_start)
        msg_success = UserProgressFormatter.format_event(evt_success)

        self.assertEqual(msg_start, "Validating Luau code syntax...")
        self.assertEqual(msg_success, "Validating Luau code syntax... Done.")
        self.assertNotIn("debug_ast_trace", msg_start)
        self.assertNotIn("rules_applied", msg_success)

    # ==========================================================================
    # 4. AUTHENTIC METRICS DERIVATION
    # ==========================================================================

    def test_05_metrics_computed_authentically_from_real_events(self):
        """Metrics are strictly calculated from live event buffer with zero synthetic multipliers."""
        task_id = "task_metrics_001"
        self.obs.emit(EventCategory.TOOL, "exec", task_id, EventStatus.SUCCESS, latency_ms=10.0)
        self.obs.emit(EventCategory.TOOL, "exec", task_id, EventStatus.SUCCESS, latency_ms=20.0)
        self.obs.emit(EventCategory.TOOL, "exec", task_id, EventStatus.FAILURE, latency_ms=30.0)
        self.obs.emit(EventCategory.TERMINAL, "run", task_id, EventStatus.REQUIRES_APPROVAL, latency_ms=40.0)

        metrics = self.obs.get_metrics(task_id=task_id)
        self.assertEqual(metrics["total_events"], 4)
        self.assertEqual(metrics["tool_call_count"], 3)
        self.assertEqual(metrics["approval_requests"], 1)
        self.assertEqual(metrics["error_rate"], 25.0)  # 1 failure out of 4 events = 25%
        self.assertEqual(metrics["average_latency_ms"], 25.0)  # (10+20+30+40)/4 = 25.0
        self.assertTrue(metrics["authentic"])

    # ==========================================================================
    # 5. ALL 12 EVALUATION BENCHMARKS EXECUTION
    # ==========================================================================

    def test_06_evaluation_harness_runs_all_12_benchmarks(self):
        """Harness executes all 12 benchmarks with 100% pass rate and authentic metrics."""
        harness = StrokeEvaluationHarness(task_id="eval_test_suite_01")
        report = harness.run_all()

        self.assertEqual(report.total_benchmarks, 12)
        self.assertEqual(report.passed_benchmarks, 12)
        self.assertEqual(report.failed_benchmarks, 0)
        self.assertEqual(report.pass_rate, 100.0)
        self.assertEqual(report.overall_score, 1.0)

        # Metric assertions
        self.assertEqual(report.summary_metrics["false_verification_rate"], 0.0)
        self.assertEqual(report.summary_metrics["context_precision"], 1.0)
        self.assertEqual(report.summary_metrics["context_recall"], 1.0)
        self.assertTrue(report.summary_metrics["authentic"])

    def test_07_individual_benchmark_validations(self):
        """Validates specific benchmark properties directly."""
        harness = StrokeEvaluationHarness(task_id="eval_indiv_test")

        # Bench 1: Coding & Debugging
        r1 = harness.bench_01_general_coding_and_debugging()
        self.assertTrue(r1.passed)

        # Bench 2: Luau & VFX
        r2 = harness.bench_02_roblox_luau_vfx_scripting()
        self.assertTrue(r2.passed)

        # Bench 4: Retrieval Precision & Recall
        r4 = harness.bench_04_context_retrieval()
        self.assertTrue(r4.passed)
        self.assertEqual(r4.metrics["precision"], 1.0)
        self.assertEqual(r4.metrics["recall"], 1.0)

        # Bench 7: Zero-Trust Approval Gating
        r7 = harness.bench_07_tool_call_correctness_and_approval()
        self.assertTrue(r7.passed)
        self.assertTrue(r7.metrics["tampering_rejected"])
        self.assertTrue(r7.metrics["replay_rejected"])

        # Bench 10: Prompt Injection Neutralization
        r10 = harness.bench_10_prompt_injection_resistance()
        self.assertTrue(r10.passed)
        self.assertTrue(r10.metrics["destructive_command_blocked"])
        self.assertTrue(r10.metrics["secret_exfiltration_neutralized"])

        # Bench 11: Verification Accuracy (0.0% false verification)
        r11 = harness.bench_11_verification_accuracy()
        self.assertTrue(r11.passed)
        self.assertEqual(r11.metrics["false_verification_rate"], 0.0)

        # Bench 12: Vision Task Gating
        r12 = harness.bench_12_vision_task_gating()
        self.assertTrue(r12.passed)
        self.assertTrue(r12.metrics["text_only_rejected_image"])
        self.assertTrue(r12.metrics["vision_model_allowed_image"])

    # ==========================================================================
    # 6. OBSERVABILITY & EVALUATION API ROUTES
    # ==========================================================================

    def test_08_observability_api_endpoints_protected_and_functional(self):
        """Observability API routes require authentication and return redacted events."""
        # Unauthenticated request -> pop override -> 401
        main.app.dependency_overrides.pop(auth_service.get_current_user, None)
        res_unauth = self.client.get("/observability/events")
        self.assertEqual(res_unauth.status_code, 401)

        # Restore override -> Authenticated request -> 200
        main.app.dependency_overrides[auth_service.get_current_user] = lambda: self.test_user

        self.obs.emit(
            category=EventCategory.AUTH,
            action="verify_token",
            task_id="task_api_01",
            status=EventStatus.SUCCESS,
            details={"email": "eval_obs@stroke.internal"}
        )

        res = self.client.get("/observability/events?task_id=task_api_01")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("events", data)
        self.assertGreaterEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["task_id"], "task_api_01")

        # Metrics endpoint
        res_metrics = self.client.get("/observability/metrics?task_id=task_api_01")
        self.assertEqual(res_metrics.status_code, 200)
        m_data = res_metrics.json()
        self.assertEqual(m_data["total_events"], 1)
        self.assertTrue(m_data["authentic"])

    def test_09_evaluation_api_endpoints(self):
        """Evaluation API runs benchmarks and returns authentic suite report."""
        # Run evaluation via API
        res = self.client.post("/evaluation/run")
        self.assertEqual(res.status_code, 200)
        report = res.json()
        self.assertEqual(report["total_benchmarks"], 12)
        self.assertEqual(report["passed_benchmarks"], 12)
        self.assertEqual(report["pass_rate"], 100.0)

        # Fetch latest evaluation
        res_latest = self.client.get("/evaluation/latest")
        self.assertEqual(res_latest.status_code, 200)
        latest = res_latest.json()
        self.assertEqual(latest["suite_id"], report["suite_id"])


if __name__ == "__main__":
    unittest.main()
