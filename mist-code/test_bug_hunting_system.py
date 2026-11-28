"""
================================================================================
STROKE // AUTOMATED BUG-HUNTING SYSTEM REGRESSION TEST SUITE
================================================================================
Comprehensive verification for Stroke's permanent bug hunting and diagnostic engine:
  1. Test Discovery Engine: Backend AST parsing & Frontend Vitest discovery
  2. Test Execution Runner: Truthful pass/fail/skip counting (never count skip as pass)
  3. API Endpoint Health Prober: Latency, status codes, and schema validation
  4. AI Provider Connection Diagnostics: Configured providers, keys, and mock mode
  5. Authentication Diagnostics: Forged HMAC rejection, malformed token handling
  6. Terminal Functionality Diagnostics: Session lifecycle, cwd tracking, policy checks
  7. MCP Integrations Diagnostics: 35-tool Roblox Studio audit, dynamic discovery
  8. Filesystem Operations Diagnostics: No-delete enforcement, version backups
  9. Broken Import Scanner: AST static analysis distinguishing guarded from unguarded
  10. Application Startup Diagnostics: Route catalog completeness and app health
  11. Actionable Bug Report Generator: Markdown generation & metric aggregation
  12. ToolDispatcher Integration: CLI & Agent tool dispatch
  13. REST API Gateway Endpoints: /diagnostics/* endpoints
================================================================================
"""

import os
import sys
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

os.environ["STROKE_ALLOW_OFFLINE_DB"] = "1"

from fastapi.testclient import TestClient
import main
import auth_service
from terminal_service import ToolDispatcher
import bug_hunter_service
from bug_hunter_service import (
    TestDiscoveryEngine,
    TestExecutionRunner,
    ApiProbeDiagnostic,
    ProviderDiagnostic,
    AuthDiagnostic,
    TerminalDiagnostic,
    McpDiagnostic,
    FilesystemDiagnostic,
    BrokenImportScanner,
    AppStartupDiagnostic,
    BugReportGenerator,
    StrokeBugHunter,
    DiagnosticIssue,
    BugHuntReport
)


class TestBugHuntingSystem(unittest.TestCase):
    """Audits the permanent automated bug-hunting and diagnostic architecture."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)
        cls.test_user = auth_service.AuthenticatedUser(
            uid="diagnostic_tester_user",
            email="diagnostic_tester@stroke.internal",
            claims={"uid": "diagnostic_tester_user"}
        )

    def setUp(self):
        main.app.dependency_overrides[auth_service.get_current_user] = lambda: self.test_user
        main.app.dependency_overrides[main.verify_terminal_access] = lambda: {"auth": "internal_token"}

    def tearDown(self):
        main.app.dependency_overrides.clear()

    # --------------------------------------------------------------------------
    # 1. Test Discovery Engine
    # --------------------------------------------------------------------------
    def test_01_backend_test_discovery(self):
        """TestDiscoveryEngine discovers backend pytest files with AST parsing."""
        res = TestDiscoveryEngine.discover_backend_tests(ROOT_DIR)
        self.assertGreaterEqual(res["total_files"], 30)
        self.assertGreaterEqual(res["total_tests"], 400)
        self.assertIn("test_firebase_auth.py", res["files"])

        auth_meta = res["files"]["test_firebase_auth.py"]
        self.assertEqual(auth_meta["subsystem"], "Authentication & Authorization")
        self.assertGreater(len(auth_meta["classes"]), 0)

        # Check method details
        first_cls = auth_meta["classes"][0]
        self.assertTrue(len(first_cls["methods"]) > 0)
        self.assertTrue(any("test_" in m["name"] for m in first_cls["methods"]))

    def test_02_frontend_test_discovery(self):
        """TestDiscoveryEngine discovers frontend TypeScript test files and counts."""
        res = TestDiscoveryEngine.discover_frontend_tests(ROOT_DIR)
        self.assertGreaterEqual(res["total_files"], 1)
        self.assertGreaterEqual(res["total_tests"], 10)
        matched = any("streamingAndVerification.test.ts" in k or "models.test.ts" in k for k in res["files"].keys())
        self.assertTrue(matched, f"Expected repository TypeScript tests in: {list(res['files'].keys())}")

    # --------------------------------------------------------------------------
    # 2. Test Execution Runner (Truthful Pass/Fail/Skip Counting)
    # --------------------------------------------------------------------------
    def test_03_test_runner_truthful_counts(self):
        """Pytest execution runner strictly separates skipped tests from passed tests."""
        # Run a single fast test file
        res = TestExecutionRunner.run_backend_pytest(ROOT_DIR, target_file="test_bug_fixes.py", timeout_seconds=30)
        self.assertEqual(res["exit_code"], 0)
        self.assertGreater(res["passed"], 0)
        self.assertEqual(res["failed"], 0)
        self.assertTrue(res["success"])
        self.assertIsInstance(res["skipped"], int)

        # Mock output with skipped tests to verify skipped is NEVER marked as passing
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="10 passed, 5 skipped in 1.23s",
                stderr=""
            )
            parsed = TestExecutionRunner.run_backend_pytest(ROOT_DIR, target_file="test_dummy.py")
            self.assertEqual(parsed["passed"], 10)
            self.assertEqual(parsed["skipped"], 5)
            self.assertEqual(parsed["failed"], 0)
            # Verify passed was not inflated to 15
            self.assertNotEqual(parsed["passed"], 15)

    # --------------------------------------------------------------------------
    # 3. API Endpoint Health Prober
    # --------------------------------------------------------------------------
    def test_04_api_endpoint_probes(self):
        """ApiProbeDiagnostic tests critical endpoints and collects metrics."""
        probes, issues = ApiProbeDiagnostic.probe_all_endpoints()
        self.assertGreaterEqual(len(probes), 8)
        # All probes should succeed under testclient
        for probe in probes:
            self.assertEqual(probe["status_code"], probe["expected_status"], f"Probe failed for {probe['path']}")
            self.assertTrue(probe["success"])
            self.assertGreaterEqual(probe["latency_ms"], 0.0)

    # --------------------------------------------------------------------------
    # 4. AI Provider Connection Diagnostics
    # --------------------------------------------------------------------------
    def test_05_provider_diagnostics(self):
        """ProviderDiagnostic audits registered models and offline mock capabilities."""
        data, issues = ProviderDiagnostic.audit_providers()
        self.assertGreater(data["registered_count"], 0)
        self.assertGreater(data["catalog_model_count"], 0)
        self.assertTrue(data["offline_mock_capable"])

    # --------------------------------------------------------------------------
    # 5. Authentication Diagnostics
    # --------------------------------------------------------------------------
    def test_06_auth_diagnostics(self):
        """AuthDiagnostic verifies token validation, forged HMAC rejection, and security."""
        data, issues = AuthDiagnostic.run_auth_diagnostics()
        self.assertEqual(data["checks_passed"], data["total_checks"])
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(len(issues), 0)

    # --------------------------------------------------------------------------
    # 6. Terminal Functionality Diagnostics
    # --------------------------------------------------------------------------
    def test_07_terminal_diagnostics(self):
        """TerminalDiagnostic verifies command execution, policy enforcement, and lifecycle."""
        data, issues = TerminalDiagnostic.run_terminal_diagnostics()
        self.assertEqual(data["checks_passed"], data["total_checks"])
        self.assertEqual(data["status"], "PASS")
        self.assertEqual(len(issues), 0)

    # --------------------------------------------------------------------------
    # 7. MCP Integrations Diagnostics
    # --------------------------------------------------------------------------
    def test_08_mcp_diagnostics(self):
        """McpDiagnostic verifies 35 Roblox Studio tools and credentials vault."""
        data, issues = McpDiagnostic.run_mcp_diagnostics()
        self.assertGreaterEqual(data["studio_tools_registered"], 35)
        self.assertTrue(data["dynamic_mcp_supported"])
        self.assertEqual(data["status"], "PASS")

    # --------------------------------------------------------------------------
    # 8. Filesystem Operations Diagnostics
    # --------------------------------------------------------------------------
    def test_09_filesystem_diagnostics(self):
        """FilesystemDiagnostic verifies no-delete enforcement and backup creation."""
        data, issues = FilesystemDiagnostic.run_filesystem_diagnostics(ROOT_DIR)
        self.assertEqual(data["checks_passed"], data["total_checks"])
        self.assertEqual(data["status"], "PASS")

    # --------------------------------------------------------------------------
    # 9. Broken Import Scanner
    # --------------------------------------------------------------------------
    def test_10_broken_import_scanner(self):
        """BrokenImportScanner scans Python files and correctly identifies guarded vs unguarded."""
        data, issues = BrokenImportScanner.scan_project_imports(ROOT_DIR)
        self.assertGreater(data["total_files_scanned"], 30)
        self.assertGreater(data["total_imports_inspected"], 100)
        # Stroke codebase has 0 unguarded broken imports
        self.assertEqual(data["broken_unguarded_count"], 0)
        self.assertEqual(len(issues), 0)

        # Create a temp file with an unguarded broken import to verify scanner detection
        with tempfile.NamedTemporaryFile("w+", suffix=".py", dir=str(ROOT_DIR), delete=False) as tf:
            tf.write("import non_existent_super_module_xyz_123\n")
            temp_path = tf.name

        try:
            temp_data, temp_issues = BrokenImportScanner.scan_project_imports(ROOT_DIR)
            found_broken = any("non_existent_super_module_xyz_123" in i.description for i in temp_issues)
            self.assertTrue(found_broken, "BrokenImportScanner failed to detect unguarded broken import in temp file.")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    # --------------------------------------------------------------------------
    # 10. Application Startup Diagnostics
    # --------------------------------------------------------------------------
    def test_11_app_startup_diagnostic(self):
        """AppStartupDiagnostic verifies route registry count and application startup."""
        data, issues = AppStartupDiagnostic.verify_app_startup()
        self.assertGreater(data["total_routes"], 25)
        self.assertTrue(data["startup_clean"])
        self.assertEqual(len(issues), 0)

    # --------------------------------------------------------------------------
    # 11. Actionable Bug Report Generator
    # --------------------------------------------------------------------------
    def test_12_bug_report_generator_markdown(self):
        """BugReportGenerator produces structured, actionable markdown report."""
        report = BugHuntReport(
            report_id="HUNT-TEST-001",
            timestamp=time.time(),
            workspace_path="/test/workspace",
            duration_ms=125.5,
            total_issues=1,
            critical_count=0,
            high_count=1,
            medium_count=0,
            low_count=0,
            test_summary={
                "backend_passed": 455,
                "backend_failed": 0,
                "backend_skipped": 2,
                "frontend_passed": 17,
                "frontend_failed": 0,
                "frontend_skipped": 0,
                "api_probes_passed": 11,
                "api_probes_total": 11,
                "broken_imports": 0,
                "providers_count": 6,
                "models_count": 12,
                "auth_status": "PASS",
                "terminal_status": "PASS",
                "mcp_status": "PASS",
                "mcp_tools": 35,
                "filesystem_status": "PASS",
                "frontend_build_status": "PASS",
                "total_routes": 45
            },
            subsystems_checked=["Authentication", "API Gateway"],
            issues=[
                DiagnosticIssue(
                    issue_id="ISSUE-001",
                    severity="HIGH",
                    subsystem="API Gateway",
                    title="Simulated Test Issue",
                    description="Simulated issue description",
                    reproduction_steps=["Step 1: Test call"],
                    remediation="Remediation advice here"
                )
            ]
        )
        md = BugReportGenerator.generate_markdown_report(report)
        self.assertIn("# Stroke Automated Bug Hunting & Test Diagnostic Report", md)
        self.assertIn("HUNT-TEST-001", md)
        self.assertIn("455 Passed, 0 Failed, 2 Skipped", md)
        self.assertIn("Simulated Test Issue", md)
        self.assertIn("Skipped tests are never counted as passing", md)

    # --------------------------------------------------------------------------
    # 12. Master Orchestrator (Fast Mode)
    # --------------------------------------------------------------------------
    def test_13_stroke_bug_hunter_fast_run(self):
        """StrokeBugHunter coordinates fast diagnostic sweep and writes report."""
        hunter = StrokeBugHunter(workspace_path=str(ROOT_DIR))
        report = hunter.hunt_bugs(run_full_tests=False)
        self.assertIsInstance(report, BugHuntReport)
        self.assertEqual(report.critical_count, 0)
        self.assertEqual(report.high_count, 0)
        self.assertTrue(hunter.docs_file.exists())

    # --------------------------------------------------------------------------
    # 13. ToolDispatcher Integration
    # --------------------------------------------------------------------------
    def test_14_tool_dispatcher_diagnostic_tools(self):
        """ToolDispatcher routes diagnostic tools seamlessly."""
        self.assertTrue(ToolDispatcher.is_supported("hunt_bugs"))
        self.assertTrue(ToolDispatcher.is_supported("discover_tests"))
        self.assertTrue(ToolDispatcher.is_supported("get_bug_report"))

        # Test discover_tests dispatch
        res = ToolDispatcher.dispatch("discover_tests", {"workspace": str(ROOT_DIR)})
        self.assertEqual(res.get("status"), "success")
        self.assertIn("backend", res)
        self.assertIn("frontend", res)

        # Test get_bug_report dispatch
        res_rep = ToolDispatcher.dispatch("get_bug_report", {"workspace": str(ROOT_DIR)})
        self.assertEqual(res_rep.get("status"), "success")
        self.assertIn("content", res_rep)

    # --------------------------------------------------------------------------
    # 14. REST API Gateway Endpoints
    # --------------------------------------------------------------------------
    def test_15_rest_api_diagnostics_endpoints(self):
        """FastAPI REST endpoints under /diagnostics/* are operational and secured."""
        # 1. GET /diagnostics/tests
        resp = self.client.get("/diagnostics/tests")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("backend_tests", data)

        # 2. GET /diagnostics/report
        resp = self.client.get("/diagnostics/report")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("content", data)

        # 3. POST /diagnostics/probe-endpoints
        resp = self.client.post("/diagnostics/probe-endpoints")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("probes", data)

        # 4. POST /diagnostics/broken-imports
        resp = self.client.post("/diagnostics/broken-imports", json={"workspace_path": str(ROOT_DIR)})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["import_scan"]["broken_unguarded_count"], 0)

        # 5. POST /diagnostics/hunt (fast)
        resp = self.client.post("/diagnostics/hunt", json={"workspace_path": str(ROOT_DIR), "run_full_tests": False})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["report"]["critical_count"], 0)


if __name__ == "__main__":
    unittest.main()
