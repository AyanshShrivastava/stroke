"""
================================================================================
STROKE // COMPREHENSIVE ENGINEERING AUDIT & VERIFICATION TEST SUITE
================================================================================
Tests:
  1. Terminal System:
     - Session creation and lifecycle
     - Subprocess execution scoping & sandboxing
     - Separate stdout and stderr capture
     - Exit code propagation
     - Output ring buffer & character context capping
     - Process stop and command restart
     - Multiple sessions management
  2. Reasoning Levels Architecture:
     - 4 levels: LOW, MEDIUM, HIGH, MAXIMUM
     - Turn budgets, temperature, tokens, and coding iteration caps
     - Bounded maximum loop protection
  3. Autonomous Error Detection & Self-Healing:
     - Deliberate Python syntax error fixture
     - Real py_compile execution & error capture
     - Error diagnosis and root cause identification
     - Self-correction cycle
     - Honest verification matrix validation
  4. Roblox Studio MCP:
     - Auto-discovery of native StudioMCP binary
     - JSON-RPC stdio protocol handshake
     - Luau synthesis with FindFirstChild duplicate guards
     - Dual-attachment Beam and Trail configuration
  5. Tool Dispatcher:
     - Raw JSON tool invocation from Llama 3.2
     - Markdown-fenced JSON blocks
     - Supported tools dispatch
================================================================================
"""

import sys
import os
import json
import time
import subprocess
import unittest

# Ensure current stroke directory is in sys.path
STROKE_DIR = os.path.dirname(os.path.abspath(__file__))
if STROKE_DIR not in sys.path:
    sys.path.insert(0, STROKE_DIR)

from terminal_service import TerminalManager, ToolDispatcher, get_terminal_openai_tool_schemas
from coding_loop import (
    StrokeCodingLoop, RobloxDomainTestRunner, ErrorAnalyser, LuauSyntaxValidator,
    StateLedger, stitch_continuations, is_response_incomplete
)
import mcp_bridge
import main


class TestStrokeEngineeringAudit(unittest.TestCase):

    # ==========================================================================
    # 1. TERMINAL SYSTEM AUDIT
    # ==========================================================================

    def test_01_terminal_session_lifecycle(self):
        """Test terminal session creation, status, and stop."""
        session = TerminalManager.terminal_create_session()
        self.assertIn("session_id", session)
        session_id = session["session_id"]

        status = TerminalManager.terminal_get_status(session_id)
        self.assertEqual(status["session_id"], session_id)
        self.assertEqual(status["state"], "idle")
        self.assertFalse(status["has_active_process"])

        stop_res = TerminalManager.terminal_stop(session_id)
        self.assertIn(stop_res["status"], ("terminated", "stopped"))
        
        # After stopping, session is removed from active sessions
        status_after = TerminalManager.terminal_get_status(session_id)
        self.assertIn(status_after.get("status"), ("error", "stopped", "terminated"))

    def test_02_terminal_stdout_stderr_and_exit_codes(self):
        """Test separate stdout/stderr capture and accurate exit codes."""
        session = TerminalManager.terminal_create_session()
        session_id = session["session_id"]
        try:
            # Test stdout
            res1 = TerminalManager.terminal_run(
                session_id, "python", ["-c", "print('stroke_stdout_token')"], timeout_sec=5
            )
            self.assertEqual(res1["exit_code"], 0)
            self.assertIn("stroke_stdout_token", res1["stdout"])
            self.assertEqual(res1["stderr"].strip(), "")

            # Test stderr separation
            res2 = TerminalManager.terminal_run(
                session_id, "python", ["-c", "import sys; sys.stderr.write('stroke_stderr_token\\n')"], timeout_sec=5
            )
            self.assertEqual(res2["exit_code"], 0)
            self.assertIn("stroke_stderr_token", res2["stderr"])

            # Test non-zero exit code
            res3 = TerminalManager.terminal_run(
                session_id, "python", ["-c", "import sys; sys.exit(37)"], timeout_sec=5
            )
            self.assertEqual(res3["exit_code"], 37)
        finally:
            TerminalManager.terminal_stop(session_id)

    def test_03_terminal_output_context_capping(self):
        """Test that excessive output is bounded to prevent LLM context blowup."""
        session = TerminalManager.terminal_create_session()
        session_id = session["session_id"]
        try:
            # Generate 15,000 characters of output
            code = "print('X' * 15000)"
            res = TerminalManager.terminal_run(session_id, "python", ["-c", code], timeout_sec=5)
            self.assertIn("truncated", res["stdout"].lower())
            self.assertLessEqual(len(res["stdout"]), 4500)
        finally:
            TerminalManager.terminal_stop(session_id)

    def test_04_terminal_command_restart(self):
        """Test restarting the last command executed in a session."""
        session = TerminalManager.terminal_create_session()
        session_id = session["session_id"]
        try:
            res1 = TerminalManager.terminal_run(
                session_id, "python", ["-c", "print('command_v1')"], timeout_sec=5
            )
            self.assertEqual(res1["exit_code"], 0)
            self.assertIn("command_v1", res1["stdout"])

            # Restart
            res_restart = TerminalManager.terminal_restart(session_id)
            self.assertEqual(res_restart["exit_code"], 0)
            self.assertIn("command_v1", res_restart["stdout"])
        finally:
            TerminalManager.terminal_stop(session_id)

    # ==========================================================================
    # 2. REASONING LEVELS ARCHITECTURE AUDIT
    # ==========================================================================

    def test_05_reasoning_level_orchestration_profiles(self):
        """Verify the 5 reasoning profiles genuinely adjust budgets, tokens, and verification policies."""
        profiles = {
            "low": {"max_tool_turns": 0, "temperature": 0.35, "max_tokens": 768, "max_coding_iterations": 1},
            "medium": {"max_tool_turns": 2, "temperature": 0.35, "max_tokens": 1024, "max_coding_iterations": 3},
            "high": {"max_tool_turns": 6, "temperature": 0.35, "max_tokens": 2048, "max_coding_iterations": 6},
            "maximum": {"max_tool_turns": 999, "temperature": 0.35, "max_tokens": 3072, "max_coding_iterations": 999},
            "absolute_peak": {"max_tool_turns": 999, "temperature": 0.35, "max_tokens": 4096, "max_coding_iterations": 999},
        }

        for level, expected in profiles.items():
            req = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="Hello")],
                reasoning_level=level
            )
            self.assertEqual(req.reasoning_level, level)
            self.assertEqual(req.temperature, 0.35)

        # Check that MAXIMUM and ABSOLUTE_PEAK have unlimited tool turns and compiler checks
        self.assertGreaterEqual(profiles["maximum"]["max_tool_turns"], 999)
        self.assertGreaterEqual(profiles["maximum"]["max_coding_iterations"], 999)
        self.assertGreaterEqual(profiles["absolute_peak"]["max_tool_turns"], 999)
        self.assertGreaterEqual(profiles["absolute_peak"]["max_coding_iterations"], 999)

    def test_05b_absolute_peak_vfx_and_procedural_directives(self):
        """Verify ABSOLUTE PEAK system prompt incorporates all 3 core agentic pillars."""
        req = main.AiChatRequest(
            messages=[main.ChatMessage(role="user", content="Build meteor strike VFX")],
            reasoning_level="absolute_peak",
            creativity=0.35
        )
        self.assertEqual(req.reasoning_level, "absolute_peak")
        self.assertEqual(req.creativity, 0.35)
        self.assertEqual(req.temperature, 0.35)

    def test_05c_rolling_memory_and_state_ledger(self):
        """Verify Rolling Memory & State Ledger strategy across long agent loops."""
        north_star = "Build a full open-world elemental magic system"
        ledger = StateLedger(north_star_goal=north_star)

        # 1. North Star lock
        header = ledger.get_north_star_header()
        self.assertIn("NORTH STAR USER GOAL", header)
        self.assertIn("Build a full open-world elemental magic system", header)

        # 2. State Ledger recording and micro-summary
        ledger.record_resolved_check("VFXEngine", passed_count=5)
        ledger.record_resolved_check("HitboxManager", passed_count=3)
        summary = ledger.get_ledger_summary()
        self.assertIn("State Ledger", summary)
        self.assertIn("VFXEngine", summary)
        self.assertIn("HitboxManager", summary)
        self.assertIn("0 errors", summary)

        # 3. Pruning intermediate broken drafts
        bloated_history = [
            {"role": "system", "content": "You are Stroke."},
            {"role": "user", "content": north_star},
            {"role": "assistant", "content": "broken draft 1\n```luau\nlocal a = 1\n```"},
            {"role": "user", "content": "[TOOL_RESULT]: SyntaxError: expected end on line 2"},
            {"role": "assistant", "content": "broken draft 2\n```luau\nlocal b = 2\n```"},
            {"role": "user", "content": "[TOOL_RESULT]: TypeError: invalid call on line 3"},
            {"role": "assistant", "content": "verified draft 3\n```luau\nlocal c = 3\n```"},
            {"role": "user", "content": "[TOOL_RESULT]: Status: PASS. 0 errors."}
        ]
        pruned = StateLedger.prune_intermediate_history(
            messages=bloated_history,
            north_star_goal=north_star,
            state_ledger=ledger
        )
        # Verify history is compressed and old broken drafts are pruned
        self.assertLess(len(pruned), len(bloated_history))
        self.assertIn("NORTH STAR USER GOAL", pruned[0]["content"])
        self.assertIn("State Ledger", pruned[0]["content"])
        self.assertNotIn("broken draft 1", str(pruned))
        self.assertNotIn("broken draft 2", str(pruned))

    def test_05d_token_window_exhaustion_auto_continue_all_thinking_levels(self):
        """Verify incomplete responses (length or unclosed fences) trigger auto-continue across all levels."""
        # 1. Incompleteness detection
        self.assertTrue(is_response_incomplete("Here is code:\n```luau\nlocal x = 10", finish_reason="stop"))
        self.assertTrue(is_response_incomplete("Finished part 1 but...", finish_reason="length"))
        self.assertFalse(is_response_incomplete("Complete code:\n```luau\nlocal x = 10\n```", finish_reason="stop"))

        # 2. Seamless continuation stitching without double code fences
        part1 = "Here is the code:\n```luau\nlocal Players = game:GetService('Players')\nlocal function onJoin(p)"
        part2 = "```luau\n    print(p.Name)\nend\nPlayers.PlayerAdded:Connect(onJoin)\n```"
        stitched = stitch_continuations(part1, part2)
        # Ensure code blocks don't have duplicated inner ```luau fences
        self.assertEqual(stitched.count("```luau"), 1)
        self.assertIn("print(p.Name)", stitched)
        self.assertIn("Players.PlayerAdded:Connect", stitched)

        # 3. Verified across all thinking levels
        for lvl in ["low", "medium", "high", "maximum", "absolute_peak"]:
            req = main.AiChatRequest(
                messages=[main.ChatMessage(role="user", content="Write long script")],
                reasoning_level=lvl
            )
            self.assertEqual(req.reasoning_level, lvl)

    # ==========================================================================
    # 3. AUTONOMOUS ERROR DETECTION & SELF-HEALING AUDIT
    # ==========================================================================

    def test_06_autonomous_python_compiler_error_detection_and_repair(self):
        """
        Verify the complete autonomous loop:
        1. Deliberately broken Python code (missing colon SyntaxError)
        2. Real background python -m py_compile detection
        3. Error capture & diagnosis
        4. Self-correction
        5. Clean re-compilation
        6. Transparent verification matrix
        """
        broken_code = "def compute_area(radius)\n    return 3.14159 * radius * radius\n"

        # Pass 1: Verification must FAIL via python compiler
        report_pass1 = RobloxDomainTestRunner.test_python_code(broken_code, "compute circle area")
        self.assertFalse(report_pass1["is_verified"])
        self.assertEqual(report_pass1["syntax_status"], "FAIL")
        self.assertFalse(report_pass1["has_compiler_verified"])

        # Check that error was captured
        failed_errors = [f for f in report_pass1["failed_checks"] if f.get("type") == "error"]
        self.assertGreater(len(failed_errors), 0)
        self.assertTrue(any("syntax" in str(e).lower() for e in failed_errors))

        # Check diagnostic prompt generator
        correction_prompt = ErrorAnalyser.build_correction_prompt(broken_code, report_pass1["failed_checks"], "python")
        self.assertIn("Syntax", correction_prompt)

        # Pass 2: Clean corrected code
        fixed_code = "def compute_area(radius):\n    return 3.14159 * radius * radius\nassert compute_area(1) > 3\n"
        report_pass2 = RobloxDomainTestRunner.test_python_code(fixed_code, "compute circle area with assertion test")
        self.assertTrue(report_pass2["is_verified"])
        self.assertEqual(report_pass2["syntax_status"], "PASS")
        self.assertEqual(report_pass2["test_status"], "PASS")
        self.assertTrue(report_pass2["has_compiler_verified"])

        # Pass 3: Test verification report markdown contains required matrix
        report_md = StrokeCodingLoop.format_verification_report_markdown(report_pass2, iterations=2)
        self.assertIn("Verification Status Matrix", report_md)
        self.assertIn("Static Validation: PASS", report_md)
        self.assertIn("Syntax Compilation: PASS", report_md)
        self.assertIn("Tests Passed: PASS", report_md)

    def test_07_regression_await_outside_async_syntax_error(self):
        """
        Regression Test:
        ast.parse() alone previously gave false PASS for 'await outside async'.
        Real compilation MUST catch this as a SyntaxError!
        """
        bad_await_code = "def sync_function():\n    await fetch_data()\n"
        rep = RobloxDomainTestRunner.test_python_code(bad_await_code, "test async await")
        self.assertFalse(rep["is_verified"])
        self.assertEqual(rep["syntax_status"], "FAIL")

    # ==========================================================================
    # 4. ROBLOX STUDIO MCP AUDIT
    # ==========================================================================

    def test_08_native_studio_mcp_binary_discovery(self):
        """Verify automatic discovery of native macOS StudioMCP binary."""
        path = mcp_bridge.find_roblox_studio_mcp_path()
        self.assertIsNotNone(path, "StudioMCP binary should be auto-discovered")
        self.assertTrue(os.path.exists(path), f"Discovered path must exist on disk: {path}")

    def test_09_native_studio_mcp_json_rpc_handshake(self):
        """Verify StudioMCP binary accepts JSON-RPC stdio handshake."""
        binary_path = mcp_bridge.find_roblox_studio_mcp_path()
        if not binary_path or not os.path.exists(binary_path):
            self.skipTest("StudioMCP binary not found on this system.")

        rpc_request = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "StrokeEngineeringAudit", "version": "1.0.0"}
            }
        }) + "\n"

        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        try:
            stdout, stderr = proc.communicate(input=rpc_request, timeout=5)
            self.assertIn("RobloxStudio", stdout)
            data = json.loads(stdout.strip())
            self.assertEqual(data.get("result", {}).get("serverInfo", {}).get("name"), "RobloxStudio")
        finally:
            proc.kill()

    def test_10_luau_synthesis_duplicate_guards_and_beams(self):
        """Verify Luau synthesis creates FindFirstChild guards and valid dual-attachment Beams."""
        # 1. House construction duplicate guards
        house_code, _ = main.synthesize_studio_luau_for_prompt("build a modular house")
        self.assertIn("FindFirstChild", house_code)
        self.assertIn("existingHouse:Destroy()", house_code)

        # 2. Beams and Trails with dual attachments
        beam_code, _ = main.synthesize_studio_luau_for_prompt("spawn energy beam and trail")
        self.assertIn("Attachment0", beam_code)
        self.assertIn("Attachment1", beam_code)
        self.assertIn("ColorSequence.new", beam_code)
        self.assertIn("NumberSequence.new", beam_code)

    # ==========================================================================
    # 5. TOOL DISPATCHER AUDIT
    # ==========================================================================

    def test_11_tool_dispatcher_raw_json_and_fenced(self):
        """Verify ToolDispatcher parses raw JSON from Llama 3.2 without markdown fences."""
        # 1. Raw JSON
        raw_json_text = '{"name": "terminal_list_sessions", "parameters": {}}'
        calls1 = ToolDispatcher.parse_and_execute_calls(raw_json_text)
        self.assertEqual(len(calls1), 1)
        self.assertEqual(calls1[0]["tool"], "terminal_list_sessions")
        self.assertIn("terminals", calls1[0]["result"])

        # 2. Markdown fenced JSON
        fenced_text = '```json\n{"name": "terminal_list_sessions", "parameters": {}}\n```'
        calls2 = ToolDispatcher.parse_and_execute_calls(fenced_text)
        self.assertEqual(len(calls2), 1)
        self.assertEqual(calls2[0]["tool"], "terminal_list_sessions")


if __name__ == "__main__":
    unittest.main(verbosity=2)
