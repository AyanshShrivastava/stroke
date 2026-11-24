"""
Comprehensive Production Test Suite for Stroke Terminal Infrastructure.
Verifies:
1. Persistent session-scoped environment variables (export, unset, child process inheritance)
2. Directory tracking and navigation (cd, cd -, cd ~, workspace boundary enforcement)
3. Real-time streaming into output ring buffer without output duplication
4. Chronological execution history tracking (session.execution_history & get_terminal_history)
5. Cancellation preservation (stopping process sets state to 'terminated' without race conditions)
6. Multi-session and multi-agent isolation (stopping one session leaves other running sessions unaffected)
7. HTTP SSE streaming and history endpoints (/terminal/{id}/stream, /terminal/{id}/history)
8. Task orchestrator and parallel agent runner terminal session isolation
"""

import os
import sys
import time
import json
import asyncio
import tempfile
import pytest
from fastapi.testclient import TestClient

from terminal_service import (
    TerminalManager,
    TerminalSession,
    ToolDispatcher,
    SecurityDecision,
    evaluate_command_security,
    get_sanitized_child_env,
    MAX_TIMEOUT_SEC
)
from main import app, verify_terminal_access
import auth_service


@pytest.fixture(autouse=True)
def clean_terminals():
    TerminalManager.cleanup_all()
    yield
    TerminalManager.cleanup_all()


@pytest.fixture
def test_client():
    app.dependency_overrides[verify_terminal_access] = lambda: {"auth": "internal", "user": {"uid": "test_user"}}
    client = TestClient(app)
    yield client
    app.dependency_overrides.pop(verify_terminal_access, None)


class TestTerminalProductionSuite:

    def test_01_max_timeout_and_config(self):
        """Verifies MAX_TIMEOUT_SEC is raised to production standard (300s)."""
        assert MAX_TIMEOUT_SEC >= 300

    def test_02_persistent_session_environment_export_and_unset(self):
        """
        Tests session-scoped persistent environment variables:
        - export KEY=VALUE persists across subsequent commands
        - Child Python processes inherit the exported environment
        - unset KEY removes the variable from the session environment
        - Other sessions do not see or leak the variable
        """
        sess_a = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]
        sess_b = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            # 1. Export in session A
            res_export = TerminalManager.run_command(
                sess_a, "export", ["STROKE_TEST_VAR=stroke_prod_val_42", "ANOTHER_VAR=alpha_beta"],
                caller_uid="internal_daemon", approved=True
            )
            assert res_export["exit_code"] == 0
            assert "Exported" in res_export["stdout"]

            # Check status env keys
            status_a = TerminalManager.get_terminal_status(sess_a)
            assert "STROKE_TEST_VAR" in status_a["session_env_keys"]
            assert "ANOTHER_VAR" in status_a["session_env_keys"]

            # Session B should NOT have STROKE_TEST_VAR
            status_b = TerminalManager.get_terminal_status(sess_b)
            assert "STROKE_TEST_VAR" not in status_b.get("session_env_keys", [])

            # 2. Run child process in session A to verify environment variable inheritance
            py_code = "import os; print(f'VAL={os.environ.get(\"STROKE_TEST_VAR\")}')"
            res_run_a = TerminalManager.run_command(
                sess_a, sys.executable, ["-c", py_code],
                caller_uid="internal_daemon", approved=True
            )
            assert res_run_a["exit_code"] == 0
            assert "VAL=stroke_prod_val_42" in res_run_a["stdout"]

            # Child process in session B should NOT see STROKE_TEST_VAR
            res_run_b = TerminalManager.run_command(
                sess_b, sys.executable, ["-c", py_code],
                caller_uid="internal_daemon", approved=True
            )
            assert res_run_b["exit_code"] == 0
            assert "VAL=None" in res_run_b["stdout"]

            # 3. Unset variable in session A
            res_unset = TerminalManager.run_command(
                sess_a, "unset", ["STROKE_TEST_VAR"],
                caller_uid="internal_daemon", approved=True
            )
            assert res_unset["exit_code"] == 0

            status_a_after = TerminalManager.get_terminal_status(sess_a)
            assert "STROKE_TEST_VAR" not in status_a_after["session_env_keys"]
            assert "ANOTHER_VAR" in status_a_after["session_env_keys"]

            # Verify child process in session A no longer sees STROKE_TEST_VAR
            res_run_a_after = TerminalManager.run_command(
                sess_a, sys.executable, ["-c", py_code],
                caller_uid="internal_daemon", approved=True
            )
            assert "VAL=None" in res_run_a_after["stdout"]

        finally:
            TerminalManager.stop_terminal(sess_a)
            TerminalManager.stop_terminal(sess_b)

    def test_03_directory_tracking_and_boundary_enforcement(self):
        """
        Tests robust working directory navigation:
        - cd into subdirectories
        - cd - toggles back to previous directory
        - Directory traversal outside approved workspace is rejected
        """
        sess_res = TerminalManager.create_terminal(caller_uid="internal_daemon")
        sid = sess_res["session_id"]
        base_ws = sess_res["workspace_path"]

        try:
            # Create a safe subdirectory inside workspace
            sub_name = "test_sub_dir_prod"
            sub_path = os.path.join(base_ws, sub_name)
            os.makedirs(sub_path, exist_ok=True)

            try:
                # 1. cd into sub_path
                res_cd = TerminalManager.run_command(sid, "cd", [sub_name], caller_uid="internal_daemon")
                assert res_cd["exit_code"] == 0
                assert os.path.realpath(res_cd["cwd"]) == os.path.realpath(sub_path)

                # Verify pwd/status reflects cwd
                stat = TerminalManager.get_terminal_status(sid)
                assert os.path.realpath(stat["cwd"]) == os.path.realpath(sub_path)

                # 2. cd - toggles back to base_ws
                res_prev = TerminalManager.run_command(sid, "cd", ["-"], caller_uid="internal_daemon")
                assert res_prev["exit_code"] == 0
                assert os.path.realpath(res_prev["cwd"]) == os.path.realpath(base_ws)

                # 3. Path traversal attack: cd / or cd ../../../.. outside workspace
                res_traversal = TerminalManager.run_command(sid, "cd", ["/"], caller_uid="internal_daemon")
                assert res_traversal["exit_code"] == 1
                assert "denied" in res_traversal["stderr"].lower() or "outside" in res_traversal["stderr"].lower()
                # cwd must NOT change to /
                stat_after = TerminalManager.get_terminal_status(sid)
                assert os.path.realpath(stat_after["cwd"]) == os.path.realpath(base_ws)

            finally:
                if os.path.exists(sub_path):
                    try:
                        os.rmdir(sub_path)
                    except Exception:
                        pass
        finally:
            TerminalManager.stop_terminal(sid)

    def test_04_execution_history_tracking(self):
        """
        Verifies that every executed command (successful, failed, or blocked)
        is accurately recorded in chronological execution history.
        """
        sid = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            # 1. Successful export command
            TerminalManager.run_command(sid, "export", ["APP_ENV=test"], caller_uid="internal_daemon", approved=True)
            # 2. Python execution
            TerminalManager.run_command(sid, sys.executable, ["-c", "print('history_item_1')"], caller_uid="internal_daemon", approved=True)
            # 3. Failing execution (exit code 42)
            TerminalManager.run_command(sid, sys.executable, ["-c", "import sys; sys.exit(42)"], caller_uid="internal_daemon", approved=True)
            # 4. Blocked command (exit code 126)
            TerminalManager.run_command(sid, "sudo", ["rm", "-rf", "/"], caller_uid="internal_daemon")

            # Query history via TerminalManager
            hist_res = TerminalManager.get_terminal_history(sid)
            assert hist_res["status"] == "success"
            history = hist_res["history"]
            assert len(history) == 4

            # Verify records
            assert history[0]["command"] == "export"
            assert history[0]["exit_code"] == 0
            assert history[0]["state"] == "completed"

            assert history[1]["exit_code"] == 0
            assert history[1]["state"] == "completed"

            assert history[2]["exit_code"] == 42
            assert history[2]["state"] == "failed"

            assert history[3]["command"] == "sudo"
            assert history[3]["exit_code"] == 126
            assert history[3]["state"] == "failed"

            # Check dispatch via ToolDispatcher
            td_res = ToolDispatcher.dispatch("terminal_get_history", {"session_id": sid})
            assert td_res["status"] == "success"
            assert len(td_res["history"]) == 4

        finally:
            TerminalManager.stop_terminal(sid)

    def test_05_synchronous_real_time_streaming_no_duplicates(self):
        """
        Verifies that synchronous commands stream line-by-line into the output ring buffer
        without duplicating lines at command completion.
        """
        sid = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            py_script = (
                "import sys\n"
                "print('LINE_ALPHA')\n"
                "print('LINE_BETA')\n"
                "print('LINE_GAMMA')\n"
            )
            res = TerminalManager.run_command(
                sid, sys.executable, ["-c", py_script],
                caller_uid="internal_daemon", approved=True
            )
            assert res["exit_code"] == 0

            # Read all lines from terminal output buffer
            out = TerminalManager.read_terminal_output(sid, tail_lines=100)
            lines = out["output"].splitlines()

            # Count occurrences of the specific test lines in stdout stream
            alpha_count = sum(1 for line in lines if line == "[stdout] LINE_ALPHA")
            beta_count = sum(1 for line in lines if line == "[stdout] LINE_BETA")
            gamma_count = sum(1 for line in lines if line == "[stdout] LINE_GAMMA")

            # Each line must appear EXACTLY once (no duplicate output appends)
            assert alpha_count == 1, f"Expected 1 LINE_ALPHA, found {alpha_count}"
            assert beta_count == 1, f"Expected 1 LINE_BETA, found {beta_count}"
            assert gamma_count == 1, f"Expected 1 LINE_GAMMA, found {gamma_count}"

        finally:
            TerminalManager.stop_terminal(sid)

    def test_06_process_cancellation_preserves_terminated_state(self):
        """
        Verifies that when an active process is stopped, its state is preserved as
        'terminated' without being overwritten as 'failed'.
        """
        sid = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            # Start background sleep process
            bg_res = TerminalManager.run_command(
                sid,
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                is_background=True,
                caller_uid="internal_daemon",
                approved=True
            )
            assert bg_res["state"] == "running"

            # Stop session immediately
            stop_res = TerminalManager.stop_terminal(sid)
            assert stop_res["status"] == "terminated"
            assert stop_res["state"] == "terminated"

            # Verify status in reaped history reflects terminated
            stat = TerminalManager.get_terminal_status(sid)
            assert stat["state"] == "terminated"

        finally:
            TerminalManager.stop_terminal(sid)

    def test_07_multi_session_and_parallel_agent_isolation(self):
        """
        Critical test: Stopping/cancelling one session or agent task must NEVER
        affect, kill, or corrupt another parallel session or task.
        """
        sid_1 = TerminalManager.create_terminal(caller_uid="agent_tester_1")["session_id"]
        sid_2 = TerminalManager.create_terminal(caller_uid="agent_tester_2")["session_id"]

        try:
            # Launch background worker in Session 1
            bg_1 = TerminalManager.run_command(
                sid_1,
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                is_background=True,
                caller_uid="internal_daemon",
                approved=True
            )
            assert bg_1["state"] == "running"

            # Launch background worker in Session 2
            bg_2 = TerminalManager.run_command(
                sid_2,
                sys.executable,
                ["-c", "import time; time.sleep(10)"],
                is_background=True,
                caller_uid="internal_daemon",
                approved=True
            )
            assert bg_2["state"] == "running"

            # Verify both are running
            stat_1_before = TerminalManager.get_terminal_status(sid_1)
            stat_2_before = TerminalManager.get_terminal_status(sid_2)
            assert stat_1_before["has_active_process"] is True
            assert stat_2_before["has_active_process"] is True

            # CANCEL / STOP Session 1 only
            stop_1 = TerminalManager.stop_terminal(sid_1)
            assert stop_1["state"] == "terminated"

            # Session 1 must be terminated
            stat_1_after = TerminalManager.get_terminal_status(sid_1)
            assert stat_1_after["has_active_process"] is False
            assert stat_1_after["state"] == "terminated"

            # Session 2 MUST STILL BE ACTIVE AND RUNNING!
            stat_2_after = TerminalManager.get_terminal_status(sid_2)
            assert stat_2_after["has_active_process"] is True
            assert stat_2_after["state"] == "running"

            # Execute a command in Session 2 to prove session health
            ping_2 = TerminalManager.run_command(
                sid_2, sys.executable, ["-c", "print('SESSION_2_HEALTHY')"],
                caller_uid="internal_daemon", approved=True
            )
            assert ping_2["exit_code"] == 0
            assert "SESSION_2_HEALTHY" in ping_2["stdout"]

        finally:
            TerminalManager.stop_terminal(sid_1)
            TerminalManager.stop_terminal(sid_2)

    def test_08_http_history_endpoint(self, test_client):
        """Verifies GET /terminal/{session_id}/history endpoint returns accurate history."""
        # 1. Create a terminal session
        sid = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            TerminalManager.run_command(sid, "export", ["PORT=8080"], caller_uid="internal_daemon", approved=True)
            TerminalManager.run_command(sid, sys.executable, ["-c", "print('API_TEST')"], caller_uid="internal_daemon", approved=True)

            # Query history via REST API
            resp = test_client.get(f"/terminal/{sid}/history")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "success"
            assert data["session_id"] == sid
            assert len(data["history"]) >= 2
            assert data["history"][0]["command"] == "export"

            # Query non-existent session
            resp_404 = test_client.get("/terminal/non-existent-sid/history")
            assert resp_404.status_code == 404

        finally:
            TerminalManager.stop_terminal(sid)

    def test_09_http_stream_sse_endpoint(self, test_client):
        """Verifies GET /terminal/{session_id}/stream SSE streaming endpoint."""
        sid = TerminalManager.create_terminal(caller_uid="internal_daemon")["session_id"]

        try:
            # Run quick command
            TerminalManager.run_command(sid, sys.executable, ["-c", "print('STREAM_PULSE')"], caller_uid="internal_daemon", approved=True)

            with test_client.stream("GET", f"/terminal/{sid}/stream") as response:
                assert response.status_code == 200
                assert "text/event-stream" in response.headers.get("content-type", "")

                received_events = []
                for chunk in response.iter_lines():
                    if chunk and chunk.startswith("data: "):
                        payload = json.loads(chunk[6:])
                        received_events.append(payload)
                        if payload.get("type") in ("exit", "output"):
                            break

                assert len(received_events) > 0
                assert received_events[0]["type"] == "init"

        finally:
            TerminalManager.stop_terminal(sid)

    def test_10_parallel_agent_runner_terminal_isolation(self):
        """
        Verifies that BaseAgentRunner automatically binds a dedicated terminal session,
        executes commands cleanly, and cleans up its session upon termination without
        interfering with another runner's session.
        """
        async def _test():
            from parallel_agent_system import (
                BaseAgentRunner,
                AgentContext,
                AgentRole,
                FileOwnershipManager,
                AgentPermissions
            )

            ownership_mgr = FileOwnershipManager()
            ws = os.getcwd()

            ctx_1 = AgentContext(
                agent_id="agent_1",
                role=AgentRole.TESTER,
                name="Tester 1",
                permissions=AgentPermissions.for_role(AgentRole.TESTER)
            )
            runner_1 = BaseAgentRunner(ctx_1, ownership_mgr, ws)

            ctx_2 = AgentContext(
                agent_id="agent_2",
                role=AgentRole.TESTER,
                name="Tester 2",
                permissions=AgentPermissions.for_role(AgentRole.TESTER)
            )
            runner_2 = BaseAgentRunner(ctx_2, ownership_mgr, ws)

            try:
                # Runner 1 executes a terminal tool
                res_1 = await runner_1.execute_tool(
                    "terminal_run",
                    {"executable": "python", "arguments": ["--version"]}
                )
                assert res_1["exit_code"] == 0
                assert "Python" in (res_1["stdout"] or res_1["stderr"] or "")
                assert runner_1.terminal_session_id is not None

                # Runner 2 executes a terminal tool
                res_2 = await runner_2.execute_tool(
                    "terminal_run",
                    {"executable": "python", "arguments": ["--version"]}
                )
                assert res_2["exit_code"] == 0
                assert "Python" in (res_2["stdout"] or res_2["stderr"] or "")
                assert runner_2.terminal_session_id is not None

                # Verify they have distinct session IDs
                assert runner_1.terminal_session_id != runner_2.terminal_session_id

                # Stopping runner 1's terminal session leaves runner 2's session healthy
                TerminalManager.stop_terminal(runner_1.terminal_session_id)
                stat_1 = TerminalManager.get_terminal_status(runner_1.terminal_session_id)
                assert stat_1["state"] == "terminated"

                stat_2 = TerminalManager.get_terminal_status(runner_2.terminal_session_id)
                assert stat_2["state"] != "terminated"

                # Runner 2 can still execute commands in its session
                res_2_subsequent = await runner_2.execute_tool(
                    "terminal_run",
                    {"executable": "python", "arguments": ["--version"]}
                )
                assert res_2_subsequent["exit_code"] == 0
                assert "Python" in (res_2_subsequent["stdout"] or res_2_subsequent["stderr"] or "")

            finally:
                if runner_1.terminal_session_id:
                    TerminalManager.stop_terminal(runner_1.terminal_session_id)
                if runner_2.terminal_session_id:
                    TerminalManager.stop_terminal(runner_2.terminal_session_id)

        asyncio.run(_test())

    def test_11_orchestrator_task_terminal_isolation_and_cancellation(self):
        """
        Verifies that AgentTask automatically isolates its terminal session and
        TaskManager.cancel_task cleanly reaps the task's dedicated terminal process.
        """
        async def _test():
            from agent_orchestrator import TaskManager, AgentExecutionGate
            from terminal_service import ToolDispatcher

            task_a = TaskManager.create_task("Run isolated background terminal task A")
            task_b = TaskManager.create_task("Run isolated background terminal task B")

            try:
                # Execute tool for task A
                res_a = await AgentExecutionGate.authorize_and_execute(
                    task_a,
                    "terminal_run",
                    {"executable": "python", "arguments": ["--version"]},
                    tool_dispatcher=ToolDispatcher
                )
                assert res_a["exit_code"] == 0
                assert task_a.terminal_session_id is not None

                # Execute tool for task B
                res_b = await AgentExecutionGate.authorize_and_execute(
                    task_b,
                    "terminal_run",
                    {"executable": "python", "arguments": ["--version"]},
                    tool_dispatcher=ToolDispatcher
                )
                assert res_b["exit_code"] == 0
                assert task_b.terminal_session_id is not None

                # Distinct sessions
                assert task_a.terminal_session_id != task_b.terminal_session_id

                # Cancel task A
                cancel_success = TaskManager.cancel_task(task_a.task_id, reason="Test cancellation")
                assert cancel_success is True

                # Task A session must be terminated
                stat_a = TerminalManager.get_terminal_status(task_a.terminal_session_id)
                assert stat_a["state"] == "terminated"

                # Task B session must be unaffected
                stat_b = TerminalManager.get_terminal_status(task_b.terminal_session_id)
                assert stat_b["state"] != "terminated"

            finally:
                if task_a.terminal_session_id:
                    TerminalManager.stop_terminal(task_a.terminal_session_id)
                if task_b.terminal_session_id:
                    TerminalManager.stop_terminal(task_b.terminal_session_id)

        asyncio.run(_test())
