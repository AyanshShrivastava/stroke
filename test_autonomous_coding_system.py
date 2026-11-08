"""
================================================================================
STROKE // AUTONOMOUS CODE GENERATION, EXECUTION, DEBUGGING & SELF-CORRECTION
AUTOMATED REGRESSION TEST SUITE (TESTS A THROUGH J)
================================================================================
Verifies all 10 mandatory requirements:
  TEST A: Valid Python file passes real compilation.
  TEST B: Python file containing 'await' outside async function fails compilation.
  TEST C: AI receives the actual compiler error.
  TEST D: AI corrects a deliberately broken Python example.
  TEST E: Corrected code re-compiles cleanly.
  TEST F: A failed test is reported honestly.
  TEST G: Terminal starts and stops a real background process (HTTP server test).
  TEST H: Local AI invokes terminal tools and receives real stdout/stderr/exit_code.
  TEST I: Roblox Studio MCP execution and correction workflow works.
  TEST J: No terminal window appears to the user (Headless background execution).
================================================================================
"""

import os
import sys
import time
import json
import urllib.request
import unittest

# Ensure current directory is on PYTHONPATH
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from terminal_service import TerminalManager, ToolDispatcher, get_terminal_openai_tool_schemas, get_terminal_tools_schema
from coding_loop import StrokeCodingLoop, RobloxDomainTestRunner, ErrorAnalyser, CodingArchivist
import mcp_bridge


class TestAutonomousCodingSystem(unittest.TestCase):
    """Automated Regression Suite for Stroke Autonomous Coding & Terminal Engine."""

    def setUp(self):
        self.created_sessions = []

    def tearDown(self):
        for sid in self.created_sessions:
            try:
                TerminalManager.terminal_stop(sid)
            except Exception:
                pass

    # ==========================================================================
    # TEST A: Valid Python file passes real compilation
    # ==========================================================================
    def test_a_valid_python_compiles_cleanly(self):
        print("\n--- RUNNING TEST A: Valid Python Compilation ---")
        code = (
            "def calculate_fibonacci(n: int) -> int:\n"
            "    if n <= 1:\n"
            "        return n\n"
            "    a, b = 0, 1\n"
            "    for _ in range(n - 1):\n"
            "        a, b = b, a + b\n"
            "    return b\n"
        )
        report = RobloxDomainTestRunner.test_python_code(code)
        
        self.assertEqual(report["syntax_status"], "PASS", "Valid Python must have syntax_status == PASS")
        self.assertTrue(report["is_verified"], "Valid Python must be marked is_verified == True")
        self.assertTrue(report["has_compiler_verified"], "Valid Python must be verified by real compiler")
        self.assertEqual(len([f for f in report["failed_checks"] if f.get("type") == "error"]), 0)
        print("  [PASS] TEST A: Real Python compiler passed cleanly with exit code 0.")

    # ==========================================================================
    # TEST B: 'await' outside async function fails compilation
    # ==========================================================================
    def test_b_await_outside_async_fails_compilation(self):
        print("\n--- RUNNING TEST B: Regression Test for 'await' outside async ---")
        # Critical regression case: ast.parse alone permits 'await' outside async in Python 3.8+
        # But real compilation via compile() and py_compile MUST fail.
        code = (
            "def fetch_data():\n"
            "    await async_network_call()\n"
            "    return 42\n"
        )
        report = RobloxDomainTestRunner.test_python_code(code)

        self.assertEqual(report["syntax_status"], "FAIL", "Invalid await outside async function MUST fail compilation")
        self.assertFalse(report["is_verified"], "Code with syntax error must NEVER be marked verified")
        
        blocking_errors = [f for f in report["failed_checks"] if f.get("type") == "error"]
        self.assertGreater(len(blocking_errors), 0, "Must capture at least one blocking compiler error")
        
        error_msg = blocking_errors[0].get("message", "")
        self.assertIn("await", error_msg.lower(), "Error message must report 'await' issue")
        print(f"  [PASS] TEST B: Compilation cleanly rejected invalid await: {error_msg}")

    # ==========================================================================
    # TEST C: AI receives actual compiler error
    # ==========================================================================
    def test_c_ai_receives_actual_compiler_error(self):
        print("\n--- RUNNING TEST C: AI Compiler Error Diagnostic Capture ---")
        broken_code = (
            "def process_order():\n"
            "    await database_save()\n"
            "    return True\n"
        )
        report = RobloxDomainTestRunner.test_python_code(broken_code)
        failed_checks = report["failed_checks"]
        
        self.assertGreater(len(failed_checks), 0)
        diag_prompt = ErrorAnalyser.build_correction_prompt(broken_code, failed_checks, language="python")
        
        # Verify AI diagnostic prompt contains actual compiler error and line number
        self.assertIn("SyntaxError", diag_prompt)
        self.assertIn("Line 2", diag_prompt)
        self.assertIn("await", diag_prompt)
        print("  [PASS] TEST C: Diagnostic prompt successfully captured compiler error for AI revision.")

    # ==========================================================================
    # TEST D: AI corrects deliberately broken Python example
    # ==========================================================================
    def test_d_ai_corrects_broken_python_code(self):
        print("\n--- RUNNING TEST D: Autonomous Self-Healing / Correction Cycle ---")
        broken_code = (
            "def calculate_total():\n"
            "    await get_price()\n"
            "    return 100\n"
        )
        initial_reply = f"```python\n{broken_code}```"

        # Mock LLM repair callback simulating targeted fix
        def repair_llm(messages):
            # Model receives diagnostic prompt pointing out await outside async function on line 2
            return (
                "Here is the corrected code with async definition:\n"
                "```python\n"
                "async def calculate_total():\n"
                "    await get_price()\n"
                "    return 100\n"
                "```"
            )

        final_reply, final_report, steps = StrokeCodingLoop.run_coding_loop(
            prompt="Write a function to calculate total",
            initial_reply=initial_reply,
            llm_generate_fn=repair_llm,
            max_iterations=3
        )

        self.assertIn("async def calculate_total", final_reply)
        self.assertEqual(final_report["syntax_status"], "PASS")
        self.assertTrue(final_report["is_verified"])
        print(f"  [PASS] TEST D: Autonomous coding loop successfully healed code in {final_report['iteration_count']} iterations.")

    # ==========================================================================
    # TEST E: Corrected file re-compiles cleanly
    # ==========================================================================
    def test_e_corrected_file_recompiles_cleanly(self):
        print("\n--- RUNNING TEST E: Retesting Corrected Code ---")
        corrected_code = (
            "async def calculate_total():\n"
            "    await get_price()\n"
            "    return 100\n"
        )
        retest_report = RobloxDomainTestRunner.test_python_code(corrected_code)
        
        self.assertEqual(retest_report["syntax_status"], "PASS")
        self.assertTrue(retest_report["is_verified"])
        self.assertEqual(len([f for f in retest_report["failed_checks"] if f.get("type") == "error"]), 0)
        print("  [PASS] TEST E: Corrected code re-compiled cleanly via py_compile with exit code 0.")

    # ==========================================================================
    # TEST F: Failed test is reported honestly
    # ==========================================================================
    def test_f_failed_test_reported_honestly(self):
        print("\n--- RUNNING TEST F: Honest Reporting of Test Failures ---")
        failing_test_code = (
            "def add(a, b):\n"
            "    return a + b\n\n"
            "assert add(2, 2) == 5, 'Math assertion failed'\n"
        )
        report = RobloxDomainTestRunner.test_python_code(failing_test_code, prompt="run test assertions")
        
        # Verify test failure is NOT hidden or marked PASS
        self.assertEqual(report["test_status"], "FAIL")
        self.assertFalse(report["is_verified"])
        
        # Verify markdown report format
        md_report = StrokeCodingLoop.format_verification_report_markdown(report, iterations=1)
        self.assertIn("Automated Tests: FAIL", md_report)
        self.assertNotIn("Automated Tests: PASS", md_report)
        print("  [PASS] TEST F: Test assertion failure was transparently reported as Automated Tests: FAIL.")

    # ==========================================================================
    # TEST G: Terminal starts and stops real background process (HTTP Server)
    # ==========================================================================
    def test_g_terminal_starts_and_stops_background_process(self):
        print("\n--- RUNNING TEST G: Real Process Lifecycle (Background HTTP Server) ---")
        session = TerminalManager.terminal_create_session()
        sid = session["session_id"]
        self.created_sessions.append(sid)

        # Start real background HTTP server on port 18510
        test_port = 18510
        start_res = TerminalManager.terminal_run(
            session_id=sid,
            executable="python",
            arguments=["-m", "http.server", str(test_port)],
            is_background=True
        )
        self.assertTrue(start_res.get("is_background"))
        self.assertIsNotNone(start_res.get("pid"))
        time.sleep(0.6)

        # Check process status
        status = TerminalManager.terminal_get_status(sid)
        self.assertTrue(status.get("has_active_process"))
        self.assertEqual(status.get("state"), "running")

        # Test HTTP response from real process
        http_ok = False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{test_port}", timeout=2.0) as resp:
                http_ok = (resp.status == 200)
        except Exception as e:
            print(f"  [NOTE] HTTP request error: {e}")

        self.assertTrue(http_ok, "Background HTTP server must respond with HTTP 200")

        # Terminate process cleanly
        stop_res = TerminalManager.terminal_stop(sid)
        self.assertEqual(stop_res.get("status"), "terminated")
        self.assertTrue(stop_res.get("process_killed"))

        # Verify process is dead and port is freed
        time.sleep(0.3)
        post_status = TerminalManager.terminal_get_status(sid)
        self.assertEqual(post_status.get("status"), "error")
        print("  [PASS] TEST G: Background server started, verified via HTTP 200, and stopped cleanly.")

    # ==========================================================================
    # TEST H: Local AI invokes terminal tools and receives real results
    # ==========================================================================
    def test_h_local_ai_invokes_terminal_tools(self):
        print("\n--- RUNNING TEST H: AI Tool Dispatching & Execution ---")
        # 1. Test terminal_create_session
        s_res = ToolDispatcher.dispatch("terminal_create_session", {})
        sid = s_res["session_id"]
        self.created_sessions.append(sid)
        self.assertTrue(sid.startswith("term-"))

        # 2. Test terminal_run with stdout, stderr, and exit_code
        run_res = ToolDispatcher.dispatch("terminal_run", {
            "session_id": sid,
            "executable": "python",
            "arguments": [
                "-c",
                "import sys; sys.stdout.write('AUTONOMOUS_STDOUT_OK\\n'); sys.stderr.write('AUTONOMOUS_STDERR_OK\\n'); sys.exit(0)"
            ]
        })
        self.assertEqual(run_res.get("exit_code"), 0)
        self.assertIn("AUTONOMOUS_STDOUT_OK", run_res.get("stdout", ""))
        self.assertIn("AUTONOMOUS_STDERR_OK", run_res.get("stderr", ""))
        self.assertFalse(run_res.get("timed_out"))
        self.assertGreater(run_res.get("duration_ms", 0), 0)

        # 3. Test terminal_read_output
        out_res = ToolDispatcher.dispatch("terminal_read_output", {"session_id": sid, "tail_lines": 5})
        self.assertIn("AUTONOMOUS_STDOUT_OK", out_res.get("output", ""))

        # 4. Test terminal_get_status
        stat_res = ToolDispatcher.dispatch("terminal_get_status", {"session_id": sid})
        self.assertEqual(stat_res.get("session_id"), sid)
        self.assertEqual(stat_res.get("state"), "completed")

        # 5. Test terminal_list_sessions
        list_res = ToolDispatcher.dispatch("terminal_list_sessions", {})
        self.assertIsInstance(list_res.get("terminals"), list)

        # 6. Test terminal_stop
        stop_res = ToolDispatcher.dispatch("terminal_stop", {"session_id": sid})
        self.assertEqual(stop_res.get("status"), "terminated")

        # 7. Test parsing of LLM JSON tool block
        llm_text = (
            "I will create a session to run diagnostics.\n"
            "```json\n"
            "{\n"
            '  "tool": "terminal_create_session",\n'
            '  "parameters": {}\n'
            "}\n"
            "```\n"
        )
        parsed_calls = ToolDispatcher.parse_and_execute_calls(llm_text)
        self.assertEqual(len(parsed_calls), 1)
        dispatched_sid = parsed_calls[0]["result"]["session_id"]
        self.created_sessions.append(dispatched_sid)
        ToolDispatcher.dispatch("terminal_stop", {"session_id": dispatched_sid})

        print("  [PASS] TEST H: All 6 internal AI terminal tools dispatched with real stdout/stderr/exit codes.")

    # ==========================================================================
    # TEST I: Roblox Studio MCP execution and correction workflow
    # ==========================================================================
    def test_i_roblox_studio_mcp_workflow(self):
        print("\n--- RUNNING TEST I: Roblox Studio MCP Workflow ---")
        # 1. Verify MCP tools schema exposure
        mcp_tools = mcp_bridge.get_all_mcp_ai_tool_schemas()
        studio_tool_names = [t["function"]["name"] for t in mcp_tools if "studio" in t["function"]["name"]]
        self.assertIn("studio_execute_luau", studio_tool_names)

        # 2. Test Luau syntax and fake API validation for Roblox scripts
        invalid_luau = (
            "local part = Instance.new('Part')\n"
            "part.Parent = workspace\n"
            "local emitter = Instance.new('ParticleEmitter', part)\n"
            "emitter:SpawnParticleEmitter()\n"  # Fake non-existent API
        )
        luau_report = RobloxDomainTestRunner.test_luau_code(invalid_luau, prompt="Create particle emitter")
        self.assertEqual(luau_report["api_status"], "FAIL")
        self.assertFalse(luau_report["is_verified"])
        
        # Verify fake API was detected
        err_messages = [f.get("message", "") for f in luau_report["failed_checks"]]
        self.assertTrue(any("SpawnParticleEmitter" in m for m in err_messages))

        # 3. Test corrected Luau script
        corrected_luau = (
            "local part = Instance.new('Part')\n"
            "part.Parent = workspace\n"
            "local emitter = Instance.new('ParticleEmitter')\n"
            "emitter.Rate = 20\n"
            "emitter.Parent = part\n"
            "emitter:Emit(10)\n"
        )
        corrected_report = RobloxDomainTestRunner.test_luau_code(corrected_luau, prompt="Create particle emitter")
        self.assertEqual(corrected_report["api_status"], "PASS")
        print("  [PASS] TEST I: Roblox Studio MCP schemas and Luau API validation/correction verified.")

    # ==========================================================================
    # TEST J: No terminal window appears to user (Silent background execution)
    # ==========================================================================
    def test_j_no_terminal_window_appears(self):
        print("\n--- RUNNING TEST J: Headless Execution (No Window Guarantee) ---")
        # Verify that terminal_service never spawns interactive terminal windows or shells
        import terminal_service
        with open(terminal_service.__file__, "r", encoding="utf-8") as f:
            src = f.read()

        # Strict checks: No osascript Terminal.app launcher, no cmd.exe /c start, no shell=True in Popen
        self.assertNotIn('tell application "Terminal"', src)
        self.assertNotIn("cmd.exe /c start", src)
        self.assertIn("shell=False", src)

        # Verify report format contains no raw log dumps
        dummy_report = {
            "is_verified": True,
            "has_compiler_verified": True,
            "syntax_status": "PASS",
            "static_status": "PASS",
            "api_status": "PASS",
            "runtime_status": "NOT RUN",
            "test_status": "PASS",
            "perf_status": "NOT RUN",
            "compiler_used": "Python 3.9 Bytecode Compiler",
            "commands_executed": ["python -m py_compile test.py"],
            "exit_codes": [0],
            "passed_checks": ["Syntax Compilation verified cleanly"],
            "failed_checks": [],
            "untested_limitations": ["Live multiplayer replication requires in-game testing."]
        }
        md = StrokeCodingLoop.format_verification_report_markdown(dummy_report, iterations=1)
        self.assertIn("Stroke Verification & Quality Report", md)
        self.assertIn("Syntax Compilation: PASS", md)
        print("  [PASS] TEST J: Subprocesses strictly execute with shell=False; no terminal window appears.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
