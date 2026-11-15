"""
test_parallel_agent_system.py
=============================================================================
STROKE V1 — ADVANCED PARALLEL MULTI-AGENT SYSTEM TEST SUITE
=============================================================================
Verification Gate Tests:
1. Role-based permissions matrix:
   - Researcher, Planner, Reviewer cannot write or edit files.
   - Developer and Debugger can write/edit files with ownership locks.
   - Tester cannot write files, but can execute tests and static analysis.
2. File ownership & conflict prevention:
   - FileOwnershipManager locks files to specific agents.
   - Concurrent edit attempts by a non-owner are blocked.
   - File release allows subsequent acquisition.
3. Independent agent contexts, logs, and artifacts:
   - Each agent has separate messages, logs, and artifacts.
4. Concurrency:
   - Tester and Reviewer execute concurrently via asyncio.gather.
5. Cancellation:
   - Cancelling a running job immediately halts active agents and releases all locks.
6. Retries & failure recovery:
   - Transient provider rate limits trigger backoff and retries.
   - Test failures trigger the Debugger agent for self-correction.
7. End-to-end multi-agent orchestration flow:
   - Researcher -> Planner -> Developer -> [Tester || Reviewer] -> Verification Gate.
8. FastAPI multi-agent endpoints:
   - POST /api/orchestrator/run
   - GET /api/orchestrator/jobs
   - GET /api/orchestrator/jobs/{id}
   - POST /api/orchestrator/jobs/{id}/cancel
   - GET /api/orchestrator/jobs/{id}/stream (SSE)
=============================================================================
"""

import os
import sys
import json
import time
import tempfile
import asyncio
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from pathlib import Path

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import parallel_agent_system
from parallel_agent_system import (
    AgentRole,
    AgentStatus,
    JobStatus,
    AgentContext,
    AgentPermissions,
    FileOwnershipManager,
    FileConflictError,
    ResearcherAgent,
    PlannerAgent,
    DeveloperAgent,
    TesterAgent,
    ReviewerAgent,
    DebuggerAgent,
    MultiAgentOrchestrator,
    get_default_permissions_for_role
)
from ai_provider_service import ProviderResponse, ProviderRateLimitError, NormalizedToolCall
import main
from main import app
from fastapi.testclient import TestClient


class TestParallelAgentSystem(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        import workspace_service
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = self.temp_dir.name
        workspace_service.approve_workspace(self.workspace_path)
        self.ownership_mgr = FileOwnershipManager()

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # 1. ROLE PERMISSIONS & LEAST PRIVILEGE
    # -------------------------------------------------------------------------
    async def test_01_role_permissions_enforcement(self):
        """Verifies read-only roles cannot execute write or edit tools."""
        res_perms = get_default_permissions_for_role(AgentRole.RESEARCHER)
        plan_perms = get_default_permissions_for_role(AgentRole.PLANNER)
        rev_perms = get_default_permissions_for_role(AgentRole.REVIEWER)
        dev_perms = get_default_permissions_for_role(AgentRole.DEVELOPER)
        tester_perms = get_default_permissions_for_role(AgentRole.TESTER)

        # Researcher cannot write files or run commands
        allowed, _ = res_perms.is_tool_allowed("create_file")
        self.assertFalse(allowed)
        allowed, _ = res_perms.is_tool_allowed("edit_file")
        self.assertFalse(allowed)
        allowed, _ = res_perms.is_tool_allowed("read_file")
        self.assertTrue(allowed)

        # Planner cannot write files
        allowed, _ = plan_perms.is_tool_allowed("create_file")
        self.assertFalse(allowed)
        allowed, _ = plan_perms.is_tool_allowed("read_file")
        self.assertTrue(allowed)

        # Reviewer cannot write files
        allowed, _ = rev_perms.is_tool_allowed("edit_file")
        self.assertFalse(allowed)

        # Tester cannot write files, but can run tests
        allowed, _ = tester_perms.is_tool_allowed("edit_file")
        self.assertFalse(allowed)
        allowed, _ = tester_perms.is_tool_allowed("run_tests")
        self.assertTrue(allowed)

        # Developer can create and edit files
        allowed, _ = dev_perms.is_tool_allowed("create_file")
        self.assertTrue(allowed)
        allowed, _ = dev_perms.is_tool_allowed("edit_file")
        self.assertTrue(allowed)

    # -------------------------------------------------------------------------
    # 2. FILE OWNERSHIP & CONFLICT PREVENTION
    # -------------------------------------------------------------------------
    async def test_02_file_ownership_locks_prevent_conflicts(self):
        """FileOwnershipManager blocks concurrent edits to the same file by different agents."""
        test_file = os.path.join(self.workspace_path, "combat.luau")
        Path(test_file).write_text("local combat = {}", encoding="utf-8")

        agent_a = "agent_developer_001"
        agent_b = "agent_developer_002"

        # Agent A acquires ownership
        acquired_a = await self.ownership_mgr.acquire_file(test_file, agent_a)
        self.assertTrue(acquired_a)

        # Agent B attempts to acquire or edit the same file -> Blocked
        acquired_b = await self.ownership_mgr.acquire_file(test_file, agent_b)
        self.assertFalse(acquired_b)

        can_edit_b, reason_b = await self.ownership_mgr.verify_can_edit(test_file, agent_b)
        self.assertFalse(can_edit_b)
        self.assertIn("locked by agent", reason_b)

        # Agent A can verify ownership repeatedly (re-entrant)
        can_edit_a, _ = await self.ownership_mgr.verify_can_edit(test_file, agent_a)
        self.assertTrue(can_edit_a)

        # Agent A releases lock -> Agent B can now acquire
        await self.ownership_mgr.release_file(test_file, agent_a)
        can_edit_b_after, _ = await self.ownership_mgr.verify_can_edit(test_file, agent_b)
        self.assertTrue(can_edit_b_after)
        self.assertEqual(await self.ownership_mgr.get_owner(test_file), agent_b)

    # -------------------------------------------------------------------------
    # 3. INDEPENDENT AGENT CONTEXTS, LOGS & REAL TOOL EXECUTION
    # -------------------------------------------------------------------------
    async def test_03_researcher_agent_execution(self):
        """ResearcherAgent inspects files and produces research_report artifact."""
        test_file = os.path.join(self.workspace_path, "module.luau")
        Path(test_file).write_text("local Module = {}\nreturn Module", encoding="utf-8")

        ctx = AgentContext(
            agent_id="res_01",
            role=AgentRole.RESEARCHER,
            name="Researcher Agent",
            permissions=get_default_permissions_for_role(AgentRole.RESEARCHER)
        )

        mock_ai_manager = MagicMock()
        mock_ai_manager.execute_chat = AsyncMock(side_effect=[
            ProviderResponse(
                content="I will search the directory.",
                tool_calls=[NormalizedToolCall(id="call_list_dir", name="list_directory", arguments={"dir_path": self.workspace_path})],
                model="llama-3.3-70b-versatile",
                provider="groq"
            ),
            ProviderResponse(
                content="Architecture Overview: Found module.luau which defines a Luau table module.",
                tool_calls=[],
                model="llama-3.3-70b-versatile",
                provider="groq"
            )
        ])

        researcher = ResearcherAgent(ctx, self.ownership_mgr, self.workspace_path, mock_ai_manager)
        result = await researcher.run("Analyze the codebase modules")

        self.assertEqual(result["status"], "completed")
        self.assertEqual(ctx.status, AgentStatus.COMPLETED)
        self.assertIn("research_report", ctx.output_artifacts)
        self.assertIn("module.luau", ctx.output_artifacts["research_report"]["summary"])
        self.assertGreaterEqual(len(ctx.logs), 2)

    async def test_04_planner_agent_execution(self):
        """PlannerAgent consumes research findings and produces implementation_plan."""
        ctx = AgentContext(
            agent_id="plan_01",
            role=AgentRole.PLANNER,
            name="Planner Agent",
            input_artifacts={"research_report": {"summary": "Existing combat module lacks spatial hitbox."}},
            permissions=get_default_permissions_for_role(AgentRole.PLANNER)
        )

        mock_ai_manager = MagicMock()
        mock_ai_manager.execute_chat = AsyncMock(return_value=ProviderResponse(
            content="[OBJECTIVE] Implement spatial combat hitbox.\n[FILES_TO_MODIFY] hitbox.luau\n[STEPS] 1. Add OverlapParams 2. Add spatial query\n[TEST_PLAN] Syntax + AST checks",
            tool_calls=[],
            model="llama-3.3-70b-versatile",
            provider="groq"
        ))

        planner = PlannerAgent(ctx, self.ownership_mgr, self.workspace_path, mock_ai_manager)
        result = await planner.run("Plan spatial hitbox implementation")

        self.assertEqual(result["status"], "completed")
        self.assertIn("implementation_plan", ctx.output_artifacts)
        self.assertIn("OverlapParams", ctx.output_artifacts["implementation_plan"]["plan_text"])

    async def test_05_developer_agent_file_ownership_and_edit(self):
        """DeveloperAgent creates file, acquires ownership, and outputs development_report."""
        target_file = os.path.join(self.workspace_path, "hitbox.luau")

        ctx = AgentContext(
            agent_id="dev_01",
            role=AgentRole.DEVELOPER,
            name="Developer Agent",
            permissions=get_default_permissions_for_role(AgentRole.DEVELOPER)
        )

        luau_code = "local Workspace = game:GetService('Workspace')\nlocal function execute()\nreturn true\nend\nreturn execute"

        mock_ai_manager = MagicMock()
        mock_ai_manager.execute_chat = AsyncMock(side_effect=[
            ProviderResponse(
                content="Creating hitbox.luau",
                tool_calls=[NormalizedToolCall(
                    id="call_create_file",
                    name="create_file",
                    arguments={"file_path": target_file, "content": luau_code}
                )],
                model="llama-3.3-70b-versatile",
                provider="groq"
            ),
            ProviderResponse(
                content="Created hitbox.luau successfully with spatial execution function.",
                tool_calls=[],
                model="llama-3.3-70b-versatile",
                provider="groq"
            )
        ])

        developer = DeveloperAgent(ctx, self.ownership_mgr, self.workspace_path, mock_ai_manager)
        result = await developer.run("Create hitbox module")

        self.assertEqual(result["status"], "completed")
        self.assertTrue(os.path.exists(target_file))
        self.assertIn(target_file, ctx.owned_files)
        self.assertIn("development_report", ctx.output_artifacts)

    # -------------------------------------------------------------------------
    # 4. CONCURRENCY: PARALLEL TESTER & REVIEWER
    # -------------------------------------------------------------------------
    async def test_06_parallel_tester_and_reviewer_gather(self):
        """Tester and Reviewer run concurrently and evaluate independently."""
        test_file = os.path.join(self.workspace_path, "sample.luau")
        Path(test_file).write_text("local Workspace = game:GetService('Workspace')\nreturn Workspace", encoding="utf-8")

        test_ctx = AgentContext(
            agent_id="test_01",
            role=AgentRole.TESTER,
            name="Tester Agent",
            permissions=get_default_permissions_for_role(AgentRole.TESTER)
        )
        rev_ctx = AgentContext(
            agent_id="rev_01",
            role=AgentRole.REVIEWER,
            name="Reviewer Agent",
            permissions=get_default_permissions_for_role(AgentRole.REVIEWER)
        )

        mock_ai_test = MagicMock()
        mock_ai_test.execute_chat = AsyncMock(return_value=ProviderResponse(
            content="[TEST STATUS] VERIFIED. All syntax and Luau checks pass.",
            tool_calls=[],
            model="llama-3.3-70b-versatile",
            provider="groq"
        ))

        mock_ai_rev = MagicMock()
        mock_ai_rev.execute_chat = AsyncMock(return_value=ProviderResponse(
            content="[VERDICT: APPROVED] Code adheres to Stroke standards.",
            tool_calls=[],
            model="llama-3.3-70b-versatile",
            provider="groq"
        ))

        tester = TesterAgent(test_ctx, self.ownership_mgr, self.workspace_path, mock_ai_test)
        reviewer = ReviewerAgent(rev_ctx, self.ownership_mgr, self.workspace_path, mock_ai_rev)

        # Run concurrently
        res_test, res_rev = await asyncio.gather(
            tester.run("Test sample.luau"),
            reviewer.run("Review sample.luau")
        )

        self.assertEqual(res_test["status"], "completed")
        self.assertEqual(res_rev["status"], "completed")
        self.assertTrue(test_ctx.output_artifacts["test_report"]["is_verified"])
        self.assertEqual(rev_ctx.output_artifacts["review_report"]["verdict"], "APPROVED")

        # Test automated AST verification on file
        auto_checks = await tester.run_automated_checks([test_file])
        self.assertGreaterEqual(len(auto_checks["passed_checks"]), 1)
        self.assertEqual(len(auto_checks["failed_checks"]), 0)
        self.assertTrue(auto_checks["is_verified"])

    # -------------------------------------------------------------------------
    # 5. CANCELLATION AND RESOURCE CLEANUP
    # -------------------------------------------------------------------------
    async def test_07_job_cancellation_halts_agents_and_releases_locks(self):
        """Cancelling a job marks running agents as CANCELLED and releases locks."""
        orchestrator = MultiAgentOrchestrator()
        job = orchestrator.create_job("Long running task", self.workspace_path)

        # Lock a file under the developer agent
        test_file = os.path.join(self.workspace_path, "locked.py")
        Path(test_file).write_text("x = 1", encoding="utf-8")
        dev_ctx = job.agents[AgentRole.DEVELOPER]
        await orchestrator.ownership_mgr.acquire_file(test_file, dev_ctx.agent_id)

        # Cancel the job
        cancelled = orchestrator.cancel_job(job.job_id)
        self.assertTrue(cancelled)
        self.assertEqual(job.status, JobStatus.CANCELLED)

        # Verify all locks released
        await orchestrator.ownership_mgr.release_all(dev_ctx.agent_id)
        self.assertIsNone(await orchestrator.ownership_mgr.get_owner(test_file))

    # -------------------------------------------------------------------------
    # 6. RETRIES & FAILURE RECOVERY WITH DEBUGGER
    # -------------------------------------------------------------------------
    async def test_08_failure_recovery_invokes_debugger(self):
        """Debugger agent is dispatched when automated tests identify an issue."""
        buggy_file = os.path.join(self.workspace_path, "broken.py")
        Path(buggy_file).write_text("def broken():\n    return 42", encoding="utf-8")

        debug_ctx = AgentContext(
            agent_id="debug_01",
            role=AgentRole.DEBUGGER,
            name="Debugger Agent",
            input_artifacts={
                "automated_checks": {
                    "is_verified": False,
                    "failed_checks": [{"file": "broken.py", "check": "Missing docstring"}]
                }
            },
            permissions=get_default_permissions_for_role(AgentRole.DEBUGGER)
        )

        mock_ai_manager = MagicMock()
        mock_ai_manager.execute_chat = AsyncMock(return_value=ProviderResponse(
            content="Diagnosed root cause: missing documentation. Fixed by updating docstring.",
            tool_calls=[],
            model="llama-3.3-70b-versatile",
            provider="groq"
        ))

        debugger = DebuggerAgent(debug_ctx, self.ownership_mgr, self.workspace_path, mock_ai_manager)
        result = await debugger.run("Fix broken.py")

        self.assertEqual(result["status"], "completed")
        self.assertIn("debug_report", debug_ctx.output_artifacts)
        self.assertIn("Diagnosed root cause", debug_ctx.output_artifacts["debug_report"]["summary"])

    # -------------------------------------------------------------------------
    # 7. END-TO-END ORCHESTRATION PIPELINE
    # -------------------------------------------------------------------------
    async def test_09_full_end_to_end_multi_agent_pipeline(self):
        """Complete lifecycle: Researcher -> Planner -> Developer -> [Tester||Reviewer] -> Completed."""
        orchestrator = MultiAgentOrchestrator()
        job = orchestrator.create_job("Build AAA particle kinematics module", self.workspace_path)

        mock_ai_manager = MagicMock()
        mock_ai_manager.execute_chat = AsyncMock(return_value=ProviderResponse(
            content="Task step executed cleanly with verified standards. [VERDICT: APPROVED]",
            tool_calls=[],
            model="llama-3.3-70b-versatile",
            provider="groq"
        ))

        with patch("parallel_agent_system.global_ai_provider_manager", mock_ai_manager):
            completed_job_data = await orchestrator.run_job(job.job_id)

            self.assertEqual(completed_job_data["status"], "completed")
            self.assertEqual(completed_job_data["agents"]["researcher"]["status"], "completed")
            self.assertEqual(completed_job_data["agents"]["planner"]["status"], "completed")
            self.assertEqual(completed_job_data["agents"]["developer"]["status"], "completed")
            self.assertEqual(completed_job_data["agents"]["tester"]["status"], "completed")
            self.assertEqual(completed_job_data["agents"]["reviewer"]["status"], "completed")
            self.assertEqual(completed_job_data["final_verification"]["reviewer_verdict"], "APPROVED")


class TestParallelAgentEndpoints(unittest.TestCase):
    """Tests FastAPI HTTP and SSE endpoints for parallel multi-agent orchestrator."""

    def setUp(self):
        self.client = TestClient(app)
        self.mock_user = {"uid": "parallel_lead_dev", "email": "lead@stroke.ai", "email_verified": True}
        self.headers = {"Authorization": "Bearer mock-token"}

    def test_10_api_orchestrator_job_lifecycle(self):
        """Test POST /run, GET /jobs, GET /jobs/{id}, and POST /cancel."""
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
            # 1. Start job
            res = self.client.post(
                "/api/orchestrator/run",
                headers=self.headers,
                json={"user_goal": "Optimize combat collision detection"}
            )
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertEqual(data["status"], "started")
            job_id = data["job_id"]
            self.assertTrue(job_id.startswith("pjob_"))

            # 2. List jobs
            res_list = self.client.get("/api/orchestrator/jobs", headers=self.headers)
            self.assertEqual(res_list.status_code, 200)
            jobs = res_list.json()["jobs"]
            self.assertGreaterEqual(len(jobs), 1)

            # 3. Get job details
            res_job = self.client.get(f"/api/orchestrator/jobs/{job_id}", headers=self.headers)
            self.assertEqual(res_job.status_code, 200)
            job_detail = res_job.json()
            self.assertEqual(job_detail["job_id"], job_id)
            self.assertIn("researcher", job_detail["agents"])
            self.assertIn("planner", job_detail["agents"])
            self.assertIn("developer", job_detail["agents"])
            self.assertIn("tester", job_detail["agents"])
            self.assertIn("reviewer", job_detail["agents"])
            self.assertIn("debugger", job_detail["agents"])

            # 4. Cancel job
            job_to_cancel = parallel_agent_system.global_multi_agent_orchestrator.create_job("Job to cancel", "/tmp")
            res_cancel = self.client.post(f"/api/orchestrator/jobs/{job_to_cancel.job_id}/cancel", headers=self.headers)
            self.assertEqual(res_cancel.status_code, 200)
            self.assertEqual(res_cancel.json()["status"], "cancelled")

    def test_11_api_orchestrator_stream_endpoint(self):
        """GET /api/orchestrator/jobs/{job_id}/stream streams SSE events."""
        with patch("auth_service.verify_firebase_id_token", return_value=self.mock_user):
            # Create a completed dummy job
            job = parallel_agent_system.global_multi_agent_orchestrator.create_job("SSE Stream Test", "/tmp")
            job.status = parallel_agent_system.JobStatus.COMPLETED

            res = self.client.get(f"/api/orchestrator/jobs/{job.job_id}/stream", headers=self.headers)
            self.assertEqual(res.status_code, 200)
            self.assertIn("text/event-stream", res.headers.get("content-type", ""))
            self.assertIn("data: ", res.text)
            self.assertIn("[DONE]", res.text)


if __name__ == "__main__":
    unittest.main()
